"""Bounded retained-record custody and compare-and-replace checks."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat

import pytest

from common_lore_index.ops import _retained_attempt_record as records

from common_lore_index.ops._retained_attempt_record import (
    BACKUP_NAME,
    RECONCILIATION,
    TERMINAL_ACCEPTED,
    RetainedRecordError,
    install_terminal_accepted,
    read_retained_record,
    same_record,
)


def _reference(seed: str) -> dict[str, object]:
    digest = "sha256:" + seed * 64
    return {
        "content_digest": digest,
        "size_bytes": 1,
        "media_type": "application/octet-stream",
        "record_format": "canonical-json-v1",
        "privacy": "public",
        "locator": {"kind": "filesystem", "value": "objects/" + seed * 64},
    }


def _record_tree(tmp_path: Path, *, payload: dict[str, object] | None = None) -> tuple[Path, dict[str, object]]:
    anchor = tmp_path / "portable-publication"
    anchor.mkdir(mode=0o755)
    anchor.chmod(0o755)
    attempts = anchor / "attempts"
    attempts.mkdir(mode=0o700)
    root = attempts / ("a" * 64)
    root.mkdir(mode=0o700)
    value = payload or {
        "manifest_id": "snapmanifest1:" + "b" * 64,
        "manifest": _reference("c"),
        "receipt": _reference("d"),
        "bundle": _reference("e"),
        "retention_class": RECONCILIATION,
    }
    (root / "portable-result.json").write_bytes(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    )
    (root / "portable-result.json").chmod(0o600)
    return root, value


def test_current_record_accepts_0755_anchor_and_preserves_identity(
    tmp_path: Path,
) -> None:
    root, payload = _record_tree(tmp_path)
    record = read_retained_record(root)

    assert record.payload == payload
    assert record.root == root
    assert record.file_identity[3:] == (1, 0o600)
    assert len(record.directory_identity) == 3


def test_duplicate_keys_are_held_as_invalid(tmp_path: Path) -> None:
    root, _ = _record_tree(tmp_path)
    path = root / "portable-result.json"
    path.write_bytes(b'{"manifest_id":"x","manifest_id":"y"}')

    with pytest.raises(RetainedRecordError, match="record-invalid"):
        read_retained_record(root)


def test_missing_manifest_reference_is_held_as_legacy(tmp_path: Path) -> None:
    root, payload = _record_tree(tmp_path)
    payload.pop("manifest")
    (root / "portable-result.json").write_bytes(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    )

    with pytest.raises(RetainedRecordError, match="legacy-record"):
        read_retained_record(root)


def test_settlement_keeps_exact_backup_and_changes_only_terminal_metadata(
    tmp_path: Path,
) -> None:
    root, _ = _record_tree(tmp_path)
    before = read_retained_record(root)
    install_terminal_accepted(before, now=100)
    after = read_retained_record(root)

    assert after.retention_class == TERMINAL_ACCEPTED
    assert after.payload["expires_at_epoch"] == 100 + 24 * 60 * 60
    backup = root / BACKUP_NAME
    assert backup.read_bytes() == before.raw
    assert backup.stat().st_uid == os.getuid()
    assert backup.stat().st_nlink == 1
    assert backup.stat().st_mode & 0o777 == 0o600
    assert not same_record(before, after)


def test_conflicting_backup_refuses_without_replacing_record(tmp_path: Path) -> None:
    root, _ = _record_tree(tmp_path)
    before = read_retained_record(root)
    backup = root / BACKUP_NAME
    backup.write_bytes(b"different")
    backup.chmod(0o600)

    with pytest.raises(RetainedRecordError, match="backup-conflict"):
        install_terminal_accepted(before, now=100)
    assert read_retained_record(root).raw == before.raw


@pytest.mark.parametrize("case", ["symlink", "hardlink", "public-mode", "oversize", "public-directory"])
def test_unsafe_record_or_selected_directory_never_becomes_readable_proof(tmp_path: Path, case: str) -> None:
    root, _ = _record_tree(tmp_path)
    path = root / "portable-result.json"
    if case == "symlink":
        real = root / "original-record"
        path.rename(real)
        path.symlink_to(real.name)
    elif case == "hardlink":
        os.link(path, root / "second-name")
    elif case == "public-mode":
        path.chmod(0o644)
    elif case == "oversize":
        path.write_bytes(b"x" * (records.RECORD_LIMIT + 1))
    else:
        root.chmod(0o755)
    with pytest.raises(RetainedRecordError, match="unsafe-record"):
        read_retained_record(root)


@pytest.mark.parametrize("error_type", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("at", ["before-replace", "after-replace"])
def test_install_interrupt_keeps_exact_primary_and_truthful_record_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error_type: type[BaseException], at: str,
) -> None:
    root, _ = _record_tree(tmp_path)
    before = read_retained_record(root)
    primary = error_type("injected metadata interruption")
    original_replace = os.replace
    original_sync = records._sync_directory

    def replace(source, destination):
        if at == "before-replace" and Path(destination) == before.path:
            raise primary
        return original_replace(source, destination)

    def sync(path):
        accepted = json.loads(before.path.read_bytes())["retention_class"] == TERMINAL_ACCEPTED
        if at == "after-replace" and accepted:
            raise primary
        return original_sync(path)

    with monkeypatch.context() as patch:
        patch.setattr(records.os, "replace", replace)
        patch.setattr(records, "_sync_directory", sync)
        with pytest.raises(error_type) as caught:
            install_terminal_accepted(before, now=100)
    assert caught.value is primary
    assert (root / BACKUP_NAME).read_bytes() == before.raw
    assert not tuple(root.glob(".portable-result.json.*.tmp"))
    expected = TERMINAL_ACCEPTED if at == "after-replace" else RECONCILIATION
    assert read_retained_record(root).retention_class == expected


def test_failed_new_backup_write_cleans_only_its_owned_partial_and_can_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _ = _record_tree(tmp_path)
    before = read_retained_record(root)
    backup = root / BACKUP_NAME
    original_open, original_write = os.open, os.write
    backup_fd = None
    wrote = False

    def opened(path, flags, *args, **kwargs):
        nonlocal backup_fd
        fd = original_open(path, flags, *args, **kwargs)
        if Path(path) == backup:
            backup_fd = fd
        return fd

    def written(fd, data):
        nonlocal wrote
        if fd == backup_fd:
            if wrote:
                raise OSError("injected partial backup failure")
            wrote = True
            return original_write(fd, data[:7])
        return original_write(fd, data)

    with monkeypatch.context() as patch:
        patch.setattr(records.os, "open", opened)
        patch.setattr(records.os, "write", written)
        with pytest.raises(OSError):
            install_terminal_accepted(before, now=100)
    assert before.path.read_bytes() == before.raw
    assert not backup.exists()
    install_terminal_accepted(before, now=100)
    assert backup.read_bytes() == before.raw
    assert read_retained_record(root).retention_class == TERMINAL_ACCEPTED


def test_resync_flushes_the_verified_record_and_directory_without_extending_expiry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _ = _record_tree(tmp_path)
    install_terminal_accepted(read_retained_record(root), now=100)
    accepted = read_retained_record(root)
    original = os.fsync
    kinds: list[str] = []

    def synced(fd):
        mode = os.fstat(fd).st_mode
        kinds.append("file" if stat.S_ISREG(mode) else "directory")
        return original(fd)

    monkeypatch.setattr(records.os, "fsync", synced)
    records.resync_retained_record(accepted)
    assert kinds.count("file") == 1 and kinds.count("directory") >= 1
    assert accepted.path.read_bytes() == accepted.raw


def test_temporary_name_collision_never_deletes_a_file_this_install_did_not_create(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _ = _record_tree(tmp_path)
    before = read_retained_record(root)
    monkeypatch.setattr(records.secrets, "token_hex", lambda _count: "collision")
    temporary = root / ".portable-result.json.collision.tmp"
    temporary.write_bytes(b"independently owned retained work")
    temporary.chmod(0o600)
    with pytest.raises(records.MetadataInstallError):
        install_terminal_accepted(before, now=100)
    assert temporary.read_bytes() == b"independently owned retained work"
    assert before.path.read_bytes() == before.raw
