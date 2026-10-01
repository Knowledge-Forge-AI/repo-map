from pathlib import Path

from repomap_kg.runtime.commands import render_server_dockerfile
from repomap_kg.runtime.release import SETUPTOOLS_RELEASE_VERSION


REPO_ROOT = Path(__file__).resolve().parents[4]
FIXED_SETUPTOOLS_VERSION = "83.0.0"
VULNERABLE_SETUPTOOLS_VERSION = "80.9.0"


def test_live_setuptools_authorities_use_one_exact_fixed_version() -> None:
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    release = (
        REPO_ROOT / "src/main/python/repomap_kg/runtime/release.py"
    ).read_text(encoding="utf-8")
    notices = (
        REPO_ROOT / "docs/legal/third-party-notices.md"
    ).read_text(encoding="utf-8")
    dockerfile = render_server_dockerfile()

    assert SETUPTOOLS_RELEASE_VERSION == FIXED_SETUPTOOLS_VERSION
    assert f'requires = ["setuptools=={FIXED_SETUPTOOLS_VERSION}"]' in pyproject
    assert (
        f'SETUPTOOLS_RELEASE_VERSION = "{FIXED_SETUPTOOLS_VERSION}"'
        in release
    )
    assert f"- Selected version: `{FIXED_SETUPTOOLS_VERSION}`" in notices
    assert (
        f"python -m pip install --no-cache-dir "
        f"setuptools=={FIXED_SETUPTOOLS_VERSION}"
        in dockerfile
    )

    for live_authority in (pyproject, release, notices, dockerfile):
        assert VULNERABLE_SETUPTOOLS_VERSION not in live_authority


def test_historical_statuses_are_not_live_dependency_authorities() -> None:
    historical_statuses = tuple(
        (REPO_ROOT / "docs/status").rglob("*-exit.md")
    )

    assert historical_statuses
    assert any(
        VULNERABLE_SETUPTOOLS_VERSION
        in status.read_text(encoding="utf-8")
        for status in historical_statuses
    )
    assert all(
        "docs/status" not in path.as_posix()
        for path in (
            REPO_ROOT / "pyproject.toml",
            REPO_ROOT / "src/main/python/repomap_kg/runtime/release.py",
            REPO_ROOT / "docs/legal/third-party-notices.md",
        )
    )
