import json
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
    # Invariant 1: Withheld status records must remain absent on public line
    assert not (REPO_ROOT / "docs/status").exists()

    # Invariant 2: Live authorities and runtime code never reference withheld status tree or vulnerable setuptools version
    live_authorities = [
        REPO_ROOT / "pyproject.toml",
        REPO_ROOT / "src/main/python/repomap_kg/runtime/release.py",
        REPO_ROOT / "docs/legal/third-party-notices.md",
    ]
    runtime_dir = REPO_ROOT / "src/main/python/repomap_kg/runtime"
    if runtime_dir.is_dir():
        live_authorities.extend(runtime_dir.rglob("*.py"))

    dockerfile = render_server_dockerfile()
    for live_authority in live_authorities:
        text = live_authority.read_text(encoding="utf-8")
        assert "docs/status" not in text
        assert VULNERABLE_SETUPTOOLS_VERSION not in text

    assert "docs/status" not in dockerfile
    assert VULNERABLE_SETUPTOOLS_VERSION not in dockerfile

    # Invariant 3: Historical provenance is supplied by machine-readable public lineage
    public_lineage = REPO_ROOT / "tools/ci/retained_python_scope_transitions.json"
    historical_manifests = REPO_ROOT / "tools/ci/historical_ownership_manifests.json"
    assert public_lineage.is_file()
    assert historical_manifests.is_file()

    lineage_doc = json.loads(public_lineage.read_text(encoding="utf-8"))
    assert "records" in lineage_doc and len(lineage_doc["records"]) > 0
    hist_doc = json.loads(historical_manifests.read_text(encoding="utf-8"))
    assert isinstance(hist_doc, dict) and bool(hist_doc)

    # Invariant 4: No live dependency/version decision or retention authority depends on a withheld status record
    for record in lineage_doc.get("records", []):
        if "status_path" in record:
            assert not (REPO_ROOT / record["status_path"]).exists()

    import sys
    sys_tools = str(REPO_ROOT / "tools")
    added = False
    if sys_tools not in sys.path:
        sys.path.insert(0, sys_tools)
        added = True
    try:
        from ci.public_export_policy import check_retention_independence
        assert check_retention_independence(REPO_ROOT) == []
    finally:
        if added and sys_tools in sys.path:
            sys.path.remove(sys_tools)
