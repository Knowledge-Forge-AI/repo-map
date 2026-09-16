"""REPOMAP-CI-PIPE0 qualification-gate topology contracts."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Callable

import pytest

ROOT = Path(__file__).resolve().parents[6]
TOOLS_ROOT = ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from ci.ci_topology import check_topology
from ci.workflow_model import load_workflow


WORKFLOW_DIR = ROOT / ".github/workflows"
RELEASE_WORKFLOW = WORKFLOW_DIR / "repomap-release-qualification.yml"


def clone_workflows(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / ".github/workflows").mkdir(parents=True)
    for path in WORKFLOW_DIR.iterdir():
        shutil.copy(path, root / ".github/workflows" / path.name)
    return root


def edit(root: Path, name: str, old: str, new: str) -> None:
    path = root / ".github/workflows" / name
    content = path.read_text(encoding="utf-8")
    assert old in content, f"{name} no longer contains {old!r}"
    path.write_text(content.replace(old, new, 1), encoding="utf-8")


def violations_after(tmp_path: Path, mutate: Callable[[Path], None]) -> tuple[str, ...]:
    root = clone_workflows(tmp_path)
    mutate(root)
    return check_topology(root)


def test_staging_command_preserves_its_accepted_arguments() -> None:
    workflow = load_workflow(RELEASE_WORKFLOW)
    job = workflow.jobs["staging-integration-gate"]
    commands = "\n".join(str(s["run"]) for s in job["steps"] if "run" in s)

    assert job["timeout-minutes"] == 180
    for argument in (
        "--suite staging",
        "--hygiene-profile exhaustive",
        "--declared-complete-gates 1",
        "--operator-attest-exclusive",
        "--operator-attest-pressure-degradation",
        "--pg-container-port 55433",
        "--sandbox",
        "--report",
        '--report-dir "${GITHUB_WORKSPACE}/ci-staging-report"',
    ):
        assert argument in commands
    assert commands.count("--suite staging") == 1
    assert "--suite all" not in commands
    assert "--suite unit" not in commands
    assert commands.count("df -B1 /") == 1
    steps = job["steps"]
    assert not any(str(s.get("uses", "")).lower().startswith("actions/setup-go@") for s in steps)
    lowered_commands = commands.lower()
    assert "pip install" not in lowered_commands
    assert "go install" not in lowered_commands
    assert "golangci-lint" not in lowered_commands


def test_main_system_command_preserves_its_accepted_arguments() -> None:
    workflow = load_workflow(RELEASE_WORKFLOW)
    job = workflow.jobs["main-system-gate"]
    commands = "\n".join(str(s["run"]) for s in job["steps"] if "run" in s)

    for argument in (
        "--suite system",
        "--system-timeout 3600",
        "--hygiene-profile exhaustive",
        "--declared-complete-gates 1",
        "--operator-attest-exclusive",
        "--operator-attest-pressure-degradation",
        "--sandbox",
        "--report",
        '--report-dir "${GITHUB_WORKSPACE}/ci-system-report"',
    ):
        assert argument in commands
    assert commands.count("--suite system") == 1
    for retired in ("--suite all", "--suite unit", "--suite int", "--suite staging", "--suite smoke"):
        assert retired not in commands
    assert commands.count("df -B1 /") == 1
    steps = job["steps"]
    assert not any(str(s.get("uses", "")).lower().startswith("actions/setup-go@") for s in steps)
    lowered_commands = commands.lower()
    assert "pip install" not in lowered_commands
    assert "go install" not in lowered_commands
    assert "golangci-lint" not in lowered_commands


def test_main_system_gate_passes_the_bound_request_and_candidate_identities() -> None:
    workflow = load_workflow(RELEASE_WORKFLOW)
    job = workflow.jobs["main-system-gate"]
    commands = [str(s["run"]) for s in job["steps"] if "run" in s and "--suite system" in str(s.get("run", ""))]
    assert len(commands) == 1
    system_command = commands[0]

    for argument in (
        '--gate-request-json "${RUNNER_TEMP}/gate-request.json"',
        '--candidate-sha "${CANDIDATE_SHA}"',
        '--candidate-tree "${CANDIDATE_TREE}"',
        '--candidate-base-parent "${CANDIDATE_BASE_PARENT}"',
        '--candidate-head-parent "${CANDIDATE_HEAD_PARENT}"',
        '--approval-id "pr-${PR_NUMBER}"',
        '--pr-number "${PR_NUMBER}"',
        '--repository "${GITHUB_REPOSITORY}"',
    ):
        assert system_command.count(argument) == 1

    bind_step = next(s for s in job["steps"] if s.get("id") == "bind")
    bind_script = str(bind_step["run"])
    for required in (
        'CANDIDATE_SHA="$(git rev-parse HEAD)"',
        "CANDIDATE_TREE=\"$(git rev-parse 'HEAD^{tree}')\"",
        "CANDIDATE_BASE_PARENT=\"$(git rev-parse 'HEAD^1')\"",
        "CANDIDATE_HEAD_PARENT=\"$(git rev-parse 'HEAD^2')\"",
        "repomap-ci-gate-request-v1",
        "gate-request.json",
    ):
        assert required in bind_script


def test_release_qualification_holds_read_only_contents_permission() -> None:
    workflow = load_workflow(RELEASE_WORKFLOW)
    assert workflow.permissions == {
        "contents": "read",
    }


@pytest.mark.parametrize(
    ("name", "old", "new", "expected"),
    [
        (
            "repomap-release-qualification.yml",
            "            --sandbox \\\n",
            "",
            "must use --sandbox",
        ),
        (
            "repomap-release-qualification.yml",
            "            --pg-container-port 55433 \\\n",
            "",
            "bind pg-container-port 55433",
        ),
        (
            "repomap-release-qualification.yml",
            "    timeout-minutes: 180\n",
            "    timeout-minutes: 60\n",
            "staging lane timeout must be 180 minutes",
        ),
        (
            "repomap-release-qualification.yml",
            "      - name: Record free disk before the staging suite\n",
            "      - name: Duplicate host Go setup\n"
            "        uses: actions/setup-go@b7ad1dad31e06c5925ef5d2fc7ad053ef454303e # v7.0.0\n"
            "        with:\n"
            '          go-version: "1.25"\n\n'
            "      - name: Record free disk before the staging suite\n",
            "must not duplicate host toolchain bootstrap",
        ),
        (
            "repomap-release-qualification.yml",
            "      - name: Record free disk before the staging suite\n",
            "      - name: Duplicate host Python test environment\n"
            '        run: python -m pip install --editable ".[test,scale-tools,static-analysis]"\n\n'
            "      - name: Record free disk before the staging suite\n",
            "must not duplicate host toolchain bootstrap",
        ),
        (
            "repomap-release-qualification.yml",
            'CANDIDATE_SHA="$(git rev-parse HEAD)"',
            'CANDIDATE_SHA="missing"',
            "missing candidate/parent binding",
        ),
        (
            "repomap-release-qualification.yml",
            "            --suite system \\\n",
            "            --suite system \\\n            --suite int \\\n",
            "system gate must not contain '--suite int'",
        ),
    ],
)
def test_gate_contracts_detect_their_own_violation(
    tmp_path: Path, name: str, old: str, new: str, expected: str
) -> None:
    violations = violations_after(tmp_path, lambda root: edit(root, name, old, new))
    assert any(expected in violation for violation in violations), violations
