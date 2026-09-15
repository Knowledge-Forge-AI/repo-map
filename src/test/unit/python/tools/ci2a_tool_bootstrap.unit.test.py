from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import tomllib
import tarfile

import pytest

from ci.bootstrap_tool import install_tool


ROOT = Path(__file__).resolve().parents[5]


def _archive(member_name: str, payload: bytes) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        info = tarfile.TarInfo(member_name)
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


def _manifest(path: Path, archive: bytes, *, digest: str) -> None:
    path.write_text(
        json.dumps(
            {
                "schema": "repomap-pre-review-tools-v1",
                "tools": {
                    "example": {
                        "assets": {
                            "linux-amd64": {
                                "url": "https://invalid.example/tool.tar.gz",
                                "sha256": digest,
                                "binary_path": "tool/example",
                            }
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def test_ci2a_bootstrap_installs_only_hash_verified_archive_member(tmp_path: Path) -> None:
    archive = _archive("tool/example", b"verified executable")
    manifest = tmp_path / "manifest.json"
    _manifest(manifest, archive, digest=hashlib.sha256(archive).hexdigest())

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

    installed = install_tool(
        "example",
        tmp_path / "bin",
        manifest_path=manifest,
        platform_name="linux-amd64",
        opener=lambda *_args, **_kwargs: Response(archive),
    )

    assert installed.read_bytes() == b"verified executable"
    assert installed.stat().st_mode & 0o777 == 0o700


def test_ci2a_bootstrap_refuses_integrity_mismatch(tmp_path: Path) -> None:
    archive = _archive("tool/example", b"untrusted")
    manifest = tmp_path / "manifest.json"
    _manifest(manifest, archive, digest="0" * 64)

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

    with pytest.raises(RuntimeError, match="integrity mismatch"):
        install_tool(
            "example",
            tmp_path / "bin",
            manifest_path=manifest,
            platform_name="linux-amd64",
            opener=lambda *_args, **_kwargs: Response(archive),
        )


def test_ci2a_sealed_python_owns_exact_ruff_and_mypy_versions() -> None:
    requirements = (ROOT / "tools/ci/pre_review_python.in").read_text(encoding="utf-8")
    lock = (ROOT / "tools/ci/pre_review_python.lock").read_text(encoding="utf-8")
    bootstrap = (ROOT / "tools/ci/bootstrap_pre_review.py").read_text(encoding="utf-8")

    for requirement, version in (("ruff", "0.16.2"), ("mypy", "2.1.0")):
        assert f"{requirement}=={version}" in requirements
        assert f"{requirement}=={version}" in lock
        assert f'python_root / "bin" / "{requirement}"' in bootstrap
        assert version in bootstrap
    assert "--require-hashes" in bootstrap
    assert "--no-deps" in bootstrap


def test_ci2a_sealed_python_installs_and_attests_exact_runtime_dependencies() -> None:
    requirements = (ROOT / "tools/ci/project_dependencies.in").read_text(
        encoding="utf-8"
    )
    lock = (ROOT / "tools/ci/project_dependencies.lock").read_text(encoding="utf-8")
    bootstrap = (ROOT / "tools/ci/bootstrap_pre_review.py").read_text(
        encoding="utf-8"
    )

    assert "psycopg[binary]==3.2.12" in requirements
    assert "psycopg==3.2.12" in lock
    assert "psycopg-binary==3.2.12" in lock
    assert "typing-extensions==4.16.0" in lock
    assert 'str(CI_ROOT / "project_dependencies.lock")' in bootstrap
    assert '"psycopg", "psycopg", "3.2.12"' in bootstrap
    assert '"typing_extensions", "typing-extensions", "4.16.0"' in bootstrap


def test_static_extra_and_hashed_bootstrap_share_exact_stub_pins() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    extra = project["project"]["optional-dependencies"]["static-analysis"]
    declared = {pin for pin in extra if pin.startswith("types-")}
    inputs = (ROOT / "tools/ci/pre_review_python.in").read_text().splitlines()
    locked = (ROOT / "tools/ci/pre_review_python.lock").read_text().splitlines()
    input_stubs = {pin for pin in inputs if pin.startswith("types-")}
    lock_stubs = {line.split()[0] for line in locked if line.startswith("types-")}
    assert declared == input_stubs == lock_stubs
    assert len(declared) == 3
    assert all("==" in pin for pin in declared)
    assert not any("paramiko" in pin for pin in declared)
    assert any(line.startswith("urllib3==") for line in locked)
