"""Unit tests for candidate image build, label verification, and self-test."""

from __future__ import annotations

import stat
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from repomap_kg.runtime.release import (
    GO_RELEASE_IMAGE,
    PRODUCT_MINIMUM_LIBPQ_VERSION,
    DebPackage,
    PlatformPackages,
)

ROOT = Path(__file__).resolve().parents[6]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from tools.system import candidate_image
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


def _valid_platform_packages(arch: str) -> PlatformPackages:
    ver = "18.6-1.pgdg13+2"
    return PlatformPackages(
        postgres_config_digest="sha256:" + ("a" * 64),
        pgdg_source=("/etc/apt/sources.list.d/pgdg.sources", "b" * 64),
        pgdg_keyring=("/usr/share/postgresql-common/pgdg/apt.postgresql.org.gpg", "c" * 64),
        key_fingerprints=("D" * 40,),
        libpq_path=f"/usr/lib/{arch}-linux-gnu/libpq.so.5.18",
        libpq_sha256="e" * 64,
        libpq5_version=ver,
        builder=(
            DebPackage("libpq5", ver, arch, "1" * 64),
            DebPackage("libpq-dev", ver, arch, "2" * 64),
        ),
        closure=(DebPackage("libpq5", ver, arch, "1" * 64),),
        lib_dynload=("_ssl", "math"),
    )


def _seed_resolved_release_prerequisites(
    monkeypatch: pytest.MonkeyPatch,
    libpq_version: int = PRODUCT_MINIMUM_LIBPQ_VERSION,
) -> None:
    manifest = {arch: _valid_platform_packages(arch) for arch in ("amd64", "arm64")}
    monkeypatch.setattr(candidate_image, "PSYCOPG_LIBPQ_VERSION", libpq_version, raising=False)
    monkeypatch.setattr(candidate_image, "DYNAMIC_PACKAGE_MANIFEST", manifest, raising=False)


def test_build_and_verify_candidate_image_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_resolved_release_prerequisites(monkeypatch)
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
        LABEL_RELEASE_POSTGRES: "16.15",
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
        b'{"python": "3.12.13", "psycopg": "3.2.12", "libpq": "170006", '
        b'"postgresql": "psql (PostgreSQL) 16.15", '
        b'"go_helper": "/usr/local/bin/repomap-go-extract", "go_helper_protocol": "1"}\n'
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


def test_build_and_verify_candidate_image_rejects_missing_labels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_resolved_release_prerequisites(monkeypatch)
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


def test_build_and_verify_candidate_image_rejects_invalid_self_test_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_resolved_release_prerequisites(monkeypatch)
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
        LABEL_RELEASE_POSTGRES: "16.15",
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


def test_build_and_verify_candidate_image_rejects_version_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_resolved_release_prerequisites(monkeypatch)
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
        LABEL_RELEASE_POSTGRES: "16.15",
        LABEL_RELEASE_PYTHON: "3.12.13",
        LABEL_RELEASE_GO: "1.25.12",
        LABEL_RELEASE_PSYCOPG: "3.2.12",
        LABEL_RELEASE_LIBPQ: "170006",
    }
    client.images.get.return_value = mock_image

    mock_container = MagicMock()
    mock_container.wait.return_value = {"StatusCode": 0}
    mock_container.logs.return_value = (
        b'{"python": "3.11.0", "psycopg": "3.2.12", "libpq": "170006", '
        b'"postgresql": "psql (PostgreSQL) 16.15", '
        b'"go_helper": "/bin/go", "go_helper_protocol": "1", "go_version": "go1.25.12"}\n'
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


def test_build_and_verify_candidate_image_refuses_unresolved_prerequisites_before_render_or_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tree_sha = "e" * 40
    config = SystemTestConfig.create(
        candidate_tree_sha=tree_sha,
        run_id="run-image-held",
    )
    render_calls: list[str] = []
    tempfile_calls: list[str] = []
    docker_calls: list[list[str]] = []
    boundary = MagicMock()

    def _fake_render() -> str:
        render_calls.append("render")
        return "FROM scratch\n"

    monkeypatch.setattr(candidate_image, "get_current_tree_sha", lambda _r: tree_sha)
    monkeypatch.setattr(candidate_image, "render_server_dockerfile", _fake_render)
    monkeypatch.setattr(
        candidate_image.tempfile,
        "NamedTemporaryFile",
        lambda **_kw: tempfile_calls.append("tmp"),
    )
    monkeypatch.setattr(
        candidate_image.subprocess,
        "run",
        lambda args, **_kw: docker_calls.append(list(args)),
    )

    valid_amd = _valid_platform_packages("amd64")
    valid_arm = _valid_platform_packages("arm64")
    for accepted_ver in (PRODUCT_MINIMUM_LIBPQ_VERSION, 180006):
        monkeypatch.setattr(candidate_image, "PSYCOPG_LIBPQ_VERSION", accepted_ver, raising=False)
        monkeypatch.setattr(
            candidate_image, "DYNAMIC_PACKAGE_MANIFEST", {"amd64": valid_amd}, raising=False
        )
        candidate_image.require_release_prerequisites_resolved("amd64")

    legacy_dict_row = {
        "name": "libpq5",
        "arch": "amd64",
        "version": "18.6-1.pgdg13+2",
        "sha256": "1" * 64,
        "source_url": "http://apt.postgresql.org/pub/repos/apt/pool/main/p/postgresql-18/libpq5.deb",
    }
    cases: list[tuple[str, object, object]] = [
        ("amd64", None, {}),
        ("amd64", PRODUCT_MINIMUM_LIBPQ_VERSION - 1, {"amd64": valid_amd}),
        ("amd64", True, {"amd64": valid_amd}),
        ("amd64", 180006, {}),
        ("amd64", 180006, {"arm64": valid_arm}),
        ("amd64", 180006, {"amd64": (legacy_dict_row,)}),
        ("amd64", 180006, {"amd64": valid_amd._replace(libpq_sha256="bad")}),
    ]
    for arch, libpq_ver, manifest in cases:
        monkeypatch.setattr(
            candidate_image, "PSYCOPG_LIBPQ_VERSION", libpq_ver, raising=False
        )
        monkeypatch.setattr(
            candidate_image, "DYNAMIC_PACKAGE_MANIFEST", manifest, raising=False
        )
        monkeypatch.setattr(
            candidate_image, "resolve_target_arch", lambda _m=None, _a=arch: _a, raising=False
        )
        with pytest.raises(SystemTestError, match="refused before Docker build"):
            candidate_image.require_release_prerequisites_resolved(arch)
        with pytest.raises(SystemTestError, match="refused before Docker build"):
            build_and_verify_candidate_image(
                ROOT, config, boundary=boundary, client=MagicMock(),
            )
    with pytest.raises(SystemTestError, match="requires an established D12SystemSession"):
        build_and_verify_candidate_image(
            ROOT, config, boundary=boundary, client=MagicMock(), d12_session=MagicMock(),
        )
    assert render_calls == []
    assert tempfile_calls == []
    assert docker_calls == []
    boundary.managed_system_candidate_build.assert_not_called()
