"""Unit tests for candidate image build, label verification, and self-test."""

from __future__ import annotations

import stat
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from repomap_kg.runtime.release import GO_RELEASE_IMAGE

ROOT = Path(__file__).resolve().parents[6]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from tools.system.candidate_image import (
    build_and_verify_candidate_image,
    get_current_tree_sha,
)
from tools.system.config import (
    IMAGE_CLASS_SYSTEM_CANDIDATE,
    LABEL_CANDIDATE_TREE,
    LABEL_IMAGE_CLASS,
    LABEL_MANAGED,
    LABEL_RELEASE_GO,
    LABEL_RELEASE_LIBPQ,
    LABEL_RELEASE_POSTGRES,
    LABEL_RELEASE_PSYCOPG,
    LABEL_RELEASE_PYTHON,
    LABEL_RUN_ID,
    SystemTestConfig,
    SystemTestError,
)


def test_current_tree_uses_temporary_objects_for_read_only_repository(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(("git", "init", "-q"), cwd=repository, check=True)
    tracked = repository / "tracked.txt"
    tracked.write_text("committed\n", encoding="utf-8")
    subprocess.run(("git", "add", "tracked.txt"), cwd=repository, check=True)
    subprocess.run(
        (
            "git",
            "-c",
            "user.name=RepoMap Test",
            "-c",
            "user.email=repomap-test@example.invalid",
            "commit",
            "-q",
            "-m",
            "fixture",
        ),
        cwd=repository,
        check=True,
    )

    tracked.write_text("dirty candidate\n", encoding="utf-8")
    object_root = repository / ".git" / "objects"
    object_files_before = {
        path.relative_to(object_root) for path in object_root.rglob("*") if path.is_file()
    }
    original_modes = {
        path: stat.S_IMODE(path.stat().st_mode)
        for path in (object_root, *object_root.rglob("*"))
        if path.is_dir()
    }
    try:
        for path in original_modes:
            path.chmod(0o555)
        tree_sha = get_current_tree_sha(repository)
    finally:
        for path, mode in original_modes.items():
            path.chmod(mode)

    assert len(tree_sha) == 40
    assert tree_sha != subprocess.run(
        ("git", "rev-parse", "HEAD^{tree}"),
        cwd=repository,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert {
        path.relative_to(object_root) for path in object_root.rglob("*") if path.is_file()
    } == object_files_before


def test_build_and_verify_candidate_image_success(tmp_path: Path) -> None:
    tree_sha = "e" * 40
    config = SystemTestConfig.create(
        candidate_tree_sha=tree_sha,
        run_id="run-image-test",
    )

    client = MagicMock()
    mock_image = MagicMock()
    mock_image.id = "sha256:11223344556677889900aabbccddeeff"
    mock_image.labels = {
        LABEL_IMAGE_CLASS: IMAGE_CLASS_SYSTEM_CANDIDATE,
        LABEL_CANDIDATE_TREE: tree_sha,
        LABEL_MANAGED: "true",
        LABEL_RUN_ID: "run-image-test",
        LABEL_RELEASE_POSTGRES: "16.14",
        LABEL_RELEASE_PYTHON: "3.12.13",
        LABEL_RELEASE_GO: "1.25.12",
        LABEL_RELEASE_PSYCOPG: "3.2.12",
        LABEL_RELEASE_LIBPQ: "170006",
    }
    mock_image.attrs = {"RepoDigests": ["repomap-candidate@sha256:digest123"]}
    client.images.get.return_value = mock_image

    mock_container = MagicMock()
    mock_container.wait.return_value = {"StatusCode": 0}
    mock_container.logs.return_value = (
        b'{"python": "3.12.13", "psycopg": "3.2.12", "libpq": "170006", "postgresql": "psql (PostgreSQL) 16.14", "go_helper": "/usr/local/bin/repomap-go-extract", "go_helper_protocol": "1"}\n'
    )
    mock_go_container = MagicMock()
    mock_go_container.wait.return_value = {"StatusCode": 0}
    mock_go_container.logs.return_value = b"/probe/helper: go1.25.12\n"
    client.containers.create.side_effect = [mock_container, mock_go_container]

    build_result = MagicMock(returncode=0, stdout="", stderr="")
    with patch("tools.system.candidate_image.get_current_tree_sha", return_value=tree_sha), \
         patch("tools.system.candidate_image.subprocess.run", return_value=build_result):
        meta = build_and_verify_candidate_image(
            ROOT,
            config,
            boundary=None,
            client=client,
        )
        assert meta.image_id == mock_image.id
        assert meta.image_digest == "repomap-candidate@sha256:digest123"
        assert meta.labels[LABEL_IMAGE_CLASS] == IMAGE_CLASS_SYSTEM_CANDIDATE
        assert meta.release_versions.get("python") == "3.12.13"
        assert meta.release_versions.get("psycopg") == "3.2.12"
        assert meta.release_versions.get("libpq") == "170006"
        assert meta.release_versions.get("go") == "1.25.12"
        assert client.containers.create.call_args_list[1].args[0] == GO_RELEASE_IMAGE
        mock_container.remove.assert_called_once_with(force=True, v=True)
        mock_go_container.remove.assert_called_once_with(force=True, v=True)


def test_build_and_verify_candidate_image_rejects_missing_labels(tmp_path: Path) -> None:
    tree_sha = "e" * 40
    config = SystemTestConfig.create(
        candidate_tree_sha=tree_sha,
        run_id="run-image-test",
    )

    client = MagicMock()
    mock_image = MagicMock()
    mock_image.id = "sha256:11223344556677889900aabbccddeeff"
    mock_image.labels = {
        LABEL_IMAGE_CLASS: "wrong-class",
    }
    client.images.get.return_value = mock_image

    build_result = MagicMock(returncode=0, stdout="", stderr="")
    with patch("tools.system.candidate_image.get_current_tree_sha", return_value=tree_sha), \
         patch("tools.system.candidate_image.subprocess.run", return_value=build_result):
        with pytest.raises(SystemTestError, match="missing or invalid label"):
            build_and_verify_candidate_image(
                ROOT,
                config,
                boundary=None,
                client=client,
            )


def test_build_and_verify_candidate_image_rejects_invalid_self_test_json(tmp_path: Path) -> None:
    tree_sha = "e" * 40
    config = SystemTestConfig.create(
        candidate_tree_sha=tree_sha,
        run_id="run-image-test",
    )

    client = MagicMock()
    mock_image = MagicMock()
    mock_image.id = "sha256:11223344556677889900aabbccddeeff"
    mock_image.labels = {
        LABEL_IMAGE_CLASS: IMAGE_CLASS_SYSTEM_CANDIDATE,
        LABEL_CANDIDATE_TREE: tree_sha,
        LABEL_MANAGED: "true",
        LABEL_RUN_ID: "run-image-test",
        LABEL_RELEASE_POSTGRES: "16.14",
        LABEL_RELEASE_PYTHON: "3.12.13",
        LABEL_RELEASE_GO: "1.25.12",
        LABEL_RELEASE_PSYCOPG: "3.2.12",
        LABEL_RELEASE_LIBPQ: "170006",
    }
    client.images.get.return_value = mock_image

    mock_container = MagicMock()
    mock_container.wait.return_value = {"StatusCode": 0}
    mock_container.logs.return_value = b"Traceback (most recent call last):\nRuntimeError: broken\n"
    client.containers.create.return_value = mock_container

    build_result = MagicMock(returncode=0, stdout="", stderr="")
    with patch("tools.system.candidate_image.get_current_tree_sha", return_value=tree_sha), \
         patch("tools.system.candidate_image.subprocess.run", return_value=build_result):
        with pytest.raises(SystemTestError, match="emitted invalid JSON"):
            build_and_verify_candidate_image(
                ROOT,
                config,
                boundary=None,
                client=client,
            )


def test_build_and_verify_candidate_image_rejects_version_mismatch(tmp_path: Path) -> None:
    tree_sha = "e" * 40
    config = SystemTestConfig.create(
        candidate_tree_sha=tree_sha,
        run_id="run-image-test",
    )

    client = MagicMock()
    mock_image = MagicMock()
    mock_image.id = "sha256:11223344556677889900aabbccddeeff"
    mock_image.labels = {
        LABEL_IMAGE_CLASS: IMAGE_CLASS_SYSTEM_CANDIDATE,
        LABEL_CANDIDATE_TREE: tree_sha,
        LABEL_MANAGED: "true",
        LABEL_RUN_ID: "run-image-test",
        LABEL_RELEASE_POSTGRES: "16.14",
        LABEL_RELEASE_PYTHON: "3.12.13",
        LABEL_RELEASE_GO: "1.25.12",
        LABEL_RELEASE_PSYCOPG: "3.2.12",
        LABEL_RELEASE_LIBPQ: "170006",
    }
    client.images.get.return_value = mock_image

    mock_container = MagicMock()
    mock_container.wait.return_value = {"StatusCode": 0}
    mock_container.logs.return_value = (
        b'{"python": "3.11.0", "psycopg": "3.2.12", "libpq": "170006", "postgresql": "psql (PostgreSQL) 16.14", "go_helper": "/bin/go", "go_helper_protocol": "1", "go_version": "go1.25.12"}\n'
    )
    client.containers.create.return_value = mock_container

    build_result = MagicMock(returncode=0, stdout="", stderr="")
    with patch("tools.system.candidate_image.get_current_tree_sha", return_value=tree_sha), \
         patch("tools.system.candidate_image.subprocess.run", return_value=build_result):
        with pytest.raises(SystemTestError, match="python version mismatch"):
            build_and_verify_candidate_image(
                ROOT,
                config,
                boundary=None,
                client=client,
            )
