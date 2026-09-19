from __future__ import annotations

from pathlib import Path
import re
import sys
import tomllib


ROOT = Path(__file__).resolve().parents[5]
TOOLS_CI = ROOT / "tools"
if str(TOOLS_CI) not in sys.path:
    sys.path.insert(0, str(TOOLS_CI))

from ci.workflow_model import load_workflow  # noqa: E402


RELEASE_WORKFLOW = ROOT / ".github/workflows/repomap-release-qualification.yml"
RETIRED_WORKFLOWS = (
    ROOT / ".github/workflows/repomap-static-analysis.yml",
    ROOT / ".github/workflows/repomap-unit-tests.yml",
    ROOT / ".github/workflows/repomap-staging-gate.yml",
    ROOT / ".github/workflows/repomap-main-system-gate.yml",
    ROOT / ".github/workflows/repomap-main-source-policy.yml",
    ROOT / ".github/workflows/async14-windows-runtime.yml",
    ROOT / ".github/workflows/async15-windows-startup.yml",
    ROOT / ".github/workflows/async16-desired-state.yml",
)
PRESERVED_WINDOWS_ARTIFACTS = (
    ROOT / "tools/run_windows_async14_tests.py",
    ROOT / "tools/run_windows_async15_tests.py",
    ROOT / "tools/run_windows_async16_tests.py",
    ROOT / "src/test/int/python/repomap_kg/coordinator/windows_runtime.int.test.py",
    ROOT / "src/test/int/python/repomap_kg/service_package/windows_startup.int.test.py",
    ROOT / "src/test/unit/python/tools/windows_startup_probe.unit.test.py",
)


def test_repomap_static_analysis_workflow_contracts() -> None:
    workflow = load_workflow(RELEASE_WORKFLOW)
    assert workflow.name == "repomap-release-qualification"
    assert "pre-review-static" in workflow.jobs
    job = workflow.jobs["pre-review-static"]
    assert job["runs-on"] == "ubuntu-latest"
    assert job["timeout-minutes"] == 40
    assert job["needs"] == ["source-and-export-policy"]
    pull_request = workflow.triggers["pull_request"]
    assert pull_request["branches"] == ["main"]
    assert sorted(pull_request["types"]) == [
        "opened", "ready_for_review", "reopened", "synchronize"
    ]
    assert "paths" not in pull_request
    assert workflow.permissions == {"contents": "read"}
    assert workflow.document["concurrency"]["cancel-in-progress"] is True

    for action in workflow.action_uses():
        name, separator, sha = action.partition("@")
        assert separator and re.fullmatch(r"[0-9a-f]{40}", sha), name
    checkout = next(
        step for step in job["steps"]
        if str(step.get("uses", "")).startswith("actions/checkout@")
    )
    assert checkout["with"]["fetch-depth"] == 0
    assert checkout["with"]["persist-credentials"] is False

    commands = "\n".join(str(s["run"]) for s in job["steps"] if "run" in s)
    assert commands.count("tools/ci/bootstrap_pre_review.py") == 1
    assert commands.count("tools/ci/run_pre_review.py") == 1
    assert 'pip install --editable ".[static-analysis]"' not in commands
    assert '"${RUNNER_TEMP}/repomap-pre-review-tools/python/bin/python"' in commands
    assert '--tool-root "${RUNNER_TEMP}/repomap-pre-review-tools"' in commands
    assert "continue-on-error" not in RELEASE_WORKFLOW.read_text(encoding="utf-8")
    for forbidden in ("docker", "postgres", "pytest", "run_tests.py", "--suite"):
        assert forbidden not in commands.lower()

    driver = (ROOT / "tools/ci/run_pre_review.py").read_text(encoding="utf-8")
    assert "from ci.pre_review_checks import" in driver
    catalog = (ROOT / "tools/ci/pre_review_checks.py").read_text(encoding="utf-8")
    for name in (
        "ruff", "pyflakes", "mypy", "actionlint", "zizmor", "pip-audit",
        "govulncheck", "semgrep", "betterleaks", "malskanner",
        "retained-python-ratchets",
        "python-retention-inventory",
        "prompt-defense-audit", "scanner-suppressions", "liquibase",
        "hadolint", "generated-code-drift",
    ):
        assert f'"{name}"' in catalog


def test_legacy_windows_workflows_are_retired() -> None:
    for retired in RETIRED_WORKFLOWS:
        assert not retired.exists(), f"Retired workflow {retired.name} must not exist"
    for preserved in PRESERVED_WINDOWS_ARTIFACTS:
        assert preserved.exists(), f"Windows evidence {preserved.name} must remain"


def test_pyproject_static_analysis_configuration() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["optional-dependencies"]["static-analysis"] == [
        "mypy==2.1.0", "ruff==0.16.2",
        "types-docker==7.2.0.20260819", "types-psutil==7.2.2.20260518",
        "types-requests==2.33.0.20260518",
    ]
    assert pyproject["tool"]["ruff"]["target-version"] == "py312"
    assert set(pyproject["tool"]["ruff"]) == {"target-version", "lint"}
    assert set(pyproject["tool"]["ruff"]["lint"]) == {"select"}
    assert pyproject["tool"]["ruff"]["lint"]["select"] == [
        "E9", "F821", "F822", "F823"
    ]
    mypy = pyproject["tool"]["mypy"]
    assert mypy["python_version"] == "3.12"
    assert mypy["check_untyped_defs"] is True
    assert mypy["strict_equality"] is True
    assert "ignore_errors" not in mypy
    assert "ignore_missing_imports" not in mypy
    assert mypy.get("follow_imports", "normal") != "skip"
