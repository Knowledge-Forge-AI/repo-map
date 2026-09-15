import os
from pathlib import Path
from unittest.mock import patch

import pytest

from repomap_kg.service_package import artifacts
from repomap_kg.service_package.artifacts import (
    ServiceArtifactError,
    ensure_private_directory,
    inspect_owned_artifact,
    install_owned_artifact,
    remove_owned_artifact,
    replace_owned_artifact,
    restore_owned_artifact,
)


def _recognized(content: bytes) -> bool:
    return content.startswith(b"repomap-owned-v1\n")


def _write(path: Path, content: bytes, mode: int = 0o600) -> None:
    path.write_bytes(content)
    path.chmod(mode)


def test_private_directory_creation_is_owner_only_and_idempotent(tmp_path):
    directory = tmp_path / "nested" / "service"

    ensure_private_directory(directory)
    ensure_private_directory(directory)

    assert directory.is_dir()
    assert directory.stat().st_uid == os.getuid()
    assert directory.stat().st_mode & 0o777 == 0o700


def test_artifact_install_inspection_and_removal_are_recognized_only(tmp_path):
    target = tmp_path / "service.definition"
    content = b"repomap-owned-v1\nnew\n"

    assert inspect_owned_artifact(target, _recognized) is None
    install_owned_artifact(target, content, _recognized)
    artifact = inspect_owned_artifact(target, _recognized)

    assert artifact is not None
    assert artifact.content == content
    assert artifact.mode == 0o600
    assert target.stat().st_mode & 0o777 == 0o600
    remove_owned_artifact(target, _recognized)
    assert not target.exists()


def test_install_never_overwrites_an_existing_owned_artifact(tmp_path):
    target = tmp_path / "service.definition"
    original = b"repomap-owned-v1\nold\n"
    _write(target, original)

    with pytest.raises(ServiceArtifactError, match="service_definition_exists"):
        install_owned_artifact(
            target,
            b"repomap-owned-v1\nnew\n",
            _recognized,
        )

    assert target.read_bytes() == original


@pytest.mark.parametrize("kind", ["symlink", "directory", "unsafe_mode", "unrecognized"])
def test_inspection_rejects_unsafe_or_unrecognized_existing_targets(tmp_path, kind):
    target = tmp_path / "service.definition"
    if kind == "symlink":
        backing = tmp_path / "backing"
        _write(backing, b"repomap-owned-v1\n")
        target.symlink_to(backing)
    elif kind == "directory":
        target.mkdir()
    elif kind == "unsafe_mode":
        _write(target, b"repomap-owned-v1\n", mode=0o644)
    else:
        _write(target, b"unrecognized\n")

    with pytest.raises(ServiceArtifactError, match="service_definition_unsafe"):
        inspect_owned_artifact(target, _recognized)


def test_inspection_rejects_wrong_owner_without_reading_content(tmp_path):
    target = tmp_path / "service.definition"
    _write(target, b"repomap-owned-v1\n")
    details = target.lstat()
    wrong_owner = os.stat_result(
        (
            details.st_mode,
            details.st_ino,
            details.st_dev,
            details.st_nlink,
            details.st_uid + 1,
            details.st_gid,
            details.st_size,
            details.st_atime,
            details.st_mtime,
            details.st_ctime,
        )
    )

    with patch("repomap_kg.service_package.artifacts.os.lstat", return_value=wrong_owner):
        with pytest.raises(ServiceArtifactError, match="service_definition_unsafe"):
            inspect_owned_artifact(target, _recognized)


def test_replacement_is_atomic_and_returns_the_prior_known_good_artifact(tmp_path):
    target = tmp_path / "service.definition"
    original = b"repomap-owned-v1\nold\n"
    replacement = b"repomap-owned-v1\nnew\n"
    _write(target, original)

    prior = replace_owned_artifact(target, replacement, _recognized)

    assert prior.content == original
    assert prior.mode == 0o600
    assert target.read_bytes() == replacement
    assert target.stat().st_mode & 0o777 == 0o600


def test_failed_atomic_replacement_leaves_the_prior_file_unchanged(tmp_path):
    target = tmp_path / "service.definition"
    original = b"repomap-owned-v1\nold\n"
    _write(target, original)

    with patch(
        "repomap_kg.service_package.artifacts.os.replace",
        side_effect=OSError("synthetic replacement failure"),
    ):
        with pytest.raises(ServiceArtifactError, match="service_definition_write_failed"):
            replace_owned_artifact(
                target,
                b"repomap-owned-v1\nnew\n",
                _recognized,
            )

    assert target.read_bytes() == original


def test_install_directory_sync_failure_restores_absence(tmp_path):
    target = tmp_path / "service.definition"

    with patch(
        "repomap_kg.service_package.artifacts._fsync_directory",
        side_effect=[OSError("synthetic sync failure"), None],
    ):
        with pytest.raises(ServiceArtifactError, match="service_definition_write_failed"):
            install_owned_artifact(
                target,
                b"repomap-owned-v1\nnew\n",
                _recognized,
            )

    assert not target.exists()


def test_replacement_directory_sync_failure_restores_prior_file(tmp_path):
    target = tmp_path / "service.definition"
    original = b"repomap-owned-v1\nold\n"
    _write(target, original)

    with patch(
        "repomap_kg.service_package.artifacts._fsync_directory",
        side_effect=[OSError("synthetic sync failure"), None],
    ):
        with pytest.raises(ServiceArtifactError, match="service_definition_write_failed"):
            replace_owned_artifact(
                target,
                b"repomap-owned-v1\nnew\n",
                _recognized,
            )

    assert target.read_bytes() == original


def test_replacement_rejects_a_target_changed_after_initial_inspection(tmp_path):
    target = tmp_path / "service.definition"
    _write(target, b"repomap-owned-v1\nold\n")
    check = artifacts._require_unchanged_target

    def swap_then_check(*args, **kwargs):
        _write(target, b"unrecognized concurrent file\n")
        return check(*args, **kwargs)

    with patch.object(artifacts, "_require_unchanged_target", swap_then_check):
        with pytest.raises(ServiceArtifactError, match="service_definition_unsafe"):
            replace_owned_artifact(
                target,
                b"repomap-owned-v1\nnew\n",
                _recognized,
            )

    assert target.read_bytes() == b"unrecognized concurrent file\n"


def test_removal_rejects_a_target_changed_after_initial_inspection(tmp_path):
    target = tmp_path / "service.definition"
    _write(target, b"repomap-owned-v1\nold\n")
    check = artifacts._require_unchanged_target

    def swap_then_check(*args, **kwargs):
        _write(target, b"unrecognized concurrent file\n")
        return check(*args, **kwargs)

    with patch.object(artifacts, "_require_unchanged_target", swap_then_check):
        with pytest.raises(ServiceArtifactError, match="service_definition_unsafe"):
            remove_owned_artifact(target, _recognized)

    assert target.read_bytes() == b"unrecognized concurrent file\n"


def test_restore_reinstates_prior_bytes_and_removes_a_new_install(tmp_path):
    target = tmp_path / "service.definition"
    original = b"repomap-owned-v1\nold\n"
    _write(target, original)
    prior = replace_owned_artifact(
        target,
        b"repomap-owned-v1\nnew\n",
        _recognized,
    )

    restore_owned_artifact(target, prior, _recognized)
    assert target.read_bytes() == original

    created = tmp_path / "created.definition"
    install_owned_artifact(created, b"repomap-owned-v1\nnew\n", _recognized)
    restore_owned_artifact(created, None, _recognized)
    assert not created.exists()


def test_oversized_artifact_is_rejected_before_validation(tmp_path):
    target = tmp_path / "service.definition"
    _write(target, b"repomap-owned-v1\n" + b"x" * (1024 * 1024))

    with pytest.raises(ServiceArtifactError, match="service_definition_unsafe"):
        inspect_owned_artifact(target, _recognized)


def test_ensure_and_require_owner_directory_valid_and_rejections(tmp_path):
    owner_dir = tmp_path / "owner_controlled"
    artifacts.ensure_owner_directory(owner_dir)
    assert owner_dir.is_dir()

    # Success on existing
    artifacts.require_owner_directory(owner_dir)

    # Rejection on group/other writable mode
    owner_dir.chmod(0o777)
    with pytest.raises(ServiceArtifactError, match="service_directory_unsafe"):
        artifacts.require_owner_directory(owner_dir)
    owner_dir.chmod(0o755)

    # Rejection on mismatched uid
    with pytest.raises(ServiceArtifactError, match="service_directory_unsafe"):
        artifacts.require_owner_directory(owner_dir, owner_uid=99999)

    # Rejection on non-directory target
    file_target = tmp_path / "regular_file"
    file_target.write_text("not a dir")
    file_target.chmod(0o700)
    with pytest.raises(ServiceArtifactError, match="service_directory_unsafe"):
        artifacts.require_owner_directory(file_target)

    # Rejection on non-existent directory
    with pytest.raises(ServiceArtifactError, match="service_directory_unavailable"):
        artifacts.require_owner_directory(tmp_path / "missing_dir")


def test_ensure_private_directory_permission_and_uid_rejections(tmp_path):
    priv_dir = tmp_path / "private_test"
    artifacts.ensure_private_directory(priv_dir)

    # Rejection if mode is not 0o700
    priv_dir.chmod(0o755)
    with pytest.raises(ServiceArtifactError, match="service_directory_unsafe"):
        artifacts.ensure_private_directory(priv_dir)
    priv_dir.chmod(0o700)

    # Rejection if owner uid doesn't match
    with pytest.raises(ServiceArtifactError, match="service_directory_unsafe"):
        artifacts.ensure_private_directory(priv_dir, owner_uid=99999)

    # Rejection if target is a file instead of directory (mkdir fails)
    file_path = tmp_path / "file_blocking_dir"
    file_path.write_text("blocking")
    file_path.chmod(0o700)
    with pytest.raises(ServiceArtifactError, match="service_directory_unavailable"):
        artifacts.ensure_private_directory(file_path)
