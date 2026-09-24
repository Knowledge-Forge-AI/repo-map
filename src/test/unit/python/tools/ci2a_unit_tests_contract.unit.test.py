"""REPOMAP-CI2A hosted PR unit-lane contracts."""

from __future__ import annotations

from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[5]
TOOLS_ROOT = ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from ci.workflow_model import load_workflow


RELEASE_WORKFLOW = ROOT / ".github/workflows/repomap-release-qualification.yml"
CANONICAL_UNIT_COMMAND = "python3 tools/run_tests.py --suite unit"


def test_repomap_unit_workflow_contracts() -> None:
    assert RELEASE_WORKFLOW.exists(), "repomap-release-qualification.yml must exist"
    workflow = load_workflow(RELEASE_WORKFLOW)

    assert "unit-tests" in workflow.jobs
    job = workflow.jobs["unit-tests"]
    assert job["name"] == "unit-tests"
    assert job["runs-on"] == "ubuntu-latest"
    assert job["timeout-minutes"] == 60
    assert job["needs"] == ["source-and-export-policy"]

    steps = [s for s in job.get("steps", []) if isinstance(s, dict)]
    job_action_uses = tuple(
        str(step["uses"]) for step in steps if "uses" in step
    )
    assert job_action_uses == (
        "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
        "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97",
        "actions/setup-go@b7ad1dad31e06c5925ef5d2fc7ad053ef454303e",
    )
    for action in job_action_uses:
        name, separator, pinned = action.partition("@")
        assert separator and re.fullmatch(r"[0-9a-f]{40}", pinned), name

    checkout = next(
        step for step in steps if str(step.get("uses", "")).startswith("actions/checkout@")
    )
    assert checkout["with"]["persist-credentials"] is False
    python_setup = next(
        step
        for step in steps
        if str(step.get("uses", "")).startswith("actions/setup-python@")
    )
    assert python_setup["with"] == {"python-version": "3.13"}
    go_setup = next(
        step for step in steps if str(step.get("uses", "")).startswith("actions/setup-go@")
    )
    assert go_setup["with"] == {
        "go-version-file": "src/main/go/go.mod",
        "cache": False,
    }

    commands = [str(step["run"]) for step in steps if "run" in step]
    assert commands.count('python -m pip install --editable ".[test,scale-tools,static-analysis]"') == 1
    bootstrap_command = next(
        command for command in commands if "bootstrap_tool.py" in command
    )
    assert "--tool golangci-lint" in bootstrap_command
    assert '--bin-dir "${RUNNER_TEMP}/repomap-tools/bin"' in bootstrap_command
    assert '"${RUNNER_TEMP}/repomap-tools/bin/golangci-lint" version' in bootstrap_command
    assert commands.count("df -B1 /") == 1
    assert commands.count(CANONICAL_UNIT_COMMAND) == 1

    unit_step = next(
        step for step in steps if step.get("run") == CANONICAL_UNIT_COMMAND
    )
    assert unit_step.get("env") == {
        "REPOMAP_TEST_HYGIENE_MIN_FREE_DISK_BYTES": "10737418240"
    }

    command_text = "\n".join(commands)
    lowered = command_text.lower()
    for forbidden in (
        "--suite int",
        "--suite all",
        "--suite smoke",
        "--sandbox",
        "--pg-container-port",
        "docker pull",
        "docker run",
        "docker build",
        "postgres",
        "go test",
        "go build",
        "go install",
    ):
        assert forbidden not in lowered
    assert not any(
        command.strip().startswith("pytest") or "python -m pytest" in command
        for command in commands
    )
    assert "--report" not in command_text
    assert "--no-coverage" not in command_text

    content = RELEASE_WORKFLOW.read_text(encoding="utf-8").lower()
    assert "secrets." not in content
    assert "continue-on-error" not in content


def test_static_and_unit_lanes_remain_independent() -> None:
    workflow = load_workflow(RELEASE_WORKFLOW)
    static_job = workflow.jobs["pre-review-static"]
    assert "unit-tests" in workflow.jobs

    static_commands = "\n".join(str(s["run"]) for s in static_job["steps"] if "run" in s)
    assert CANONICAL_UNIT_COMMAND not in static_commands
