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
STAGING_GATE = WORKFLOW_DIR / "repomap-staging-gate.yml"
MAIN_SYSTEM_GATE = WORKFLOW_DIR / "repomap-main-system-gate.yml"
TRUSTED_GATE_CONTRACT = '"${RUNNER_TEMP}/gate_contract.py"'
TRUSTED_GATE_INVOCATION = f"python3 -S -E {TRUSTED_GATE_CONTRACT}"


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


def test_exhaustive_qualification_no_longer_runs_on_pull_requests() -> None:
    assert set(load_workflow(STAGING_GATE).triggers) == {"workflow_dispatch"}


def test_staging_gate_requires_an_explicit_logical_gate_request() -> None:
    inputs = load_workflow(STAGING_GATE).triggers["workflow_dispatch"]["inputs"]

    assert set(inputs) == {
        "pr_number",
        "approved_base_sha",
        "approved_head_sha",
        "approval_id",
    }
    for definition in inputs.values():
        assert definition["required"] is True


def test_staging_gate_binds_the_candidate_before_expensive_work() -> None:
    steps = load_workflow(STAGING_GATE).steps()
    text = ["\n".join(str(step.get(key, "")) for key in ("run", "uses")) for step in steps]

    trusted_checkout_index = next(
        i
        for i, step in enumerate(steps)
        if str(step.get("uses", "")).startswith("actions/checkout@")
        and step.get("with", {}).get("ref") == "${{ github.sha }}"
    )
    preserve_index = next(
        i for i, item in enumerate(text) if f"cp tools/ci/gate_contract.py {TRUSTED_GATE_CONTRACT}" in item
    )
    resolve_index = next(
        i for i, item in enumerate(text) if f"{TRUSTED_GATE_INVOCATION} resolve" in item
    )
    candidate_checkout_index = next(
        i
        for i, step in enumerate(steps)
        if str(step.get("uses", "")).startswith("actions/checkout@")
        and str(step.get("with", {}).get("ref", "")).startswith("refs/pull/")
    )
    verify_index = next(
        i for i, item in enumerate(text) if f"{TRUSTED_GATE_INVOCATION} verify" in item
    )
    expensive = [
        i
        for i, item in enumerate(text)
        if any(marker in item for marker in ("pip install", "docker pull", "setup-go", "setup-python"))
    ]
    suite_index = next(i for i, item in enumerate(text) if "python3 tools/run_tests.py" in item)

    assert (
        trusted_checkout_index
        < preserve_index
        < resolve_index
        < candidate_checkout_index
        < verify_index
        < min(expensive)
        < suite_index
    )


def test_staging_gate_uses_the_trusted_contract_for_every_authorization_command() -> None:
    commands = "\n".join(load_workflow(STAGING_GATE).run_commands())

    assert '--executor-ref "${GITHUB_REF}"' in commands
    assert '--executor-sha "${GITHUB_SHA}"' in commands
    for command in ("resolve", "verify", "record"):
        assert commands.count(f"{TRUSTED_GATE_INVOCATION} {command}") == 1
        assert f"tools/ci/gate_contract.py {command}" not in commands


def test_staging_gate_records_the_exact_candidate_sha_and_tree() -> None:
    commands = "\n".join(load_workflow(STAGING_GATE).run_commands())

    assert "git rev-parse HEAD" in commands
    assert "git rev-parse 'HEAD^{tree}'" in commands
    assert "git rev-parse 'HEAD^1'" in commands
    assert "git rev-parse 'HEAD^2'" in commands
    assert f"{TRUSTED_GATE_INVOCATION} record" in commands
    assert "repomap-ci-gate-result-v1.json" in commands


def test_staging_command_preserves_its_accepted_arguments() -> None:
    workflow = load_workflow(STAGING_GATE)
    commands = "\n".join(workflow.run_commands())

    assert workflow.jobs["repomap-staging-gate"]["timeout-minutes"] == 180
    for argument in (
        "--suite staging",
        "--hygiene-profile exhaustive",
        "--declared-complete-gates 1",
        "--operator-attest-exclusive",
        "--operator-attest-pressure-degradation",
        "--pg-container-port 55433",
        "--sandbox",
        "--report",
        '--report-dir "${GITHUB_WORKSPACE}/ci-test-report"',
    ):
        assert argument in commands
    assert commands.count("--suite staging") == 1
    assert "--suite all" not in commands
    assert "--suite unit" not in commands
    assert "docker pull postgres:16-alpine" not in commands
    assert "docker pull alpine:latest" not in commands
    assert commands.count("df -B1 /") == 1
    assert not any(action.lower().startswith("actions/setup-go@") for action in workflow.action_uses())
    lowered_commands = commands.lower()
    assert "pip install" not in lowered_commands
    assert "go install" not in lowered_commands
    assert "golangci-lint" not in lowered_commands
    assert "32" not in commands.split("--hygiene-profile")[1][:40]


def test_main_system_command_preserves_its_accepted_arguments() -> None:
    workflow = load_workflow(MAIN_SYSTEM_GATE)
    commands = "\n".join(workflow.run_commands())

    assert workflow.jobs["repomap-main-system-gate"]["timeout-minutes"] == 90
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
    assert not any(action.lower().startswith("actions/setup-go@") for action in workflow.action_uses())
    lowered_commands = commands.lower()
    assert "pip install" not in lowered_commands
    assert "go install" not in lowered_commands
    assert "golangci-lint" not in lowered_commands


def test_main_system_gate_passes_the_bound_request_and_candidate_identities() -> None:
    workflow = load_workflow(MAIN_SYSTEM_GATE)
    system_steps = [
        step for step in workflow.steps() if "--suite system" in str(step.get("run", ""))
    ]
    assert len(system_steps) == 1
    assert system_steps[0].get("env") == {
        "APPROVAL_ID": "${{ inputs.approval_id }}",
        "PR_NUMBER": "${{ inputs.pr_number }}",
    }

    commands = [
        command for command in workflow.run_commands() if "--suite system" in command
    ]
    assert len(commands) == 1
    for argument in (
        '--gate-request-json "${RUNNER_TEMP}/gate-request.json"',
        '--candidate-sha "${CANDIDATE_SHA}"',
        '--candidate-tree "${CANDIDATE_TREE}"',
        '--candidate-base-parent "${CANDIDATE_BASE_PARENT}"',
        '--candidate-head-parent "${CANDIDATE_HEAD_PARENT}"',
        '--approval-id "${APPROVAL_ID}"',
        '--pr-number "${PR_NUMBER}"',
        '--repository "${GITHUB_REPOSITORY}"',
    ):
        assert commands[0].count(argument) == 1


def test_main_system_gate_records_the_closed_report_and_binding() -> None:
    commands = [
        command
        for command in load_workflow(MAIN_SYSTEM_GATE).run_commands()
        if 'gate_contract.py" record' in command
    ]
    assert len(commands) == 1
    record_command = commands[0]
    assert record_command.count(
        '--system-report-json "${GITHUB_WORKSPACE}/ci-system-report/'
        'repomap-system-gate-report.json"'
    ) == 1
    assert record_command.count(
        '--system-binding-json "${GITHUB_WORKSPACE}/ci-system-report/'
        'repomap-system-gate-binding-v1.json"'
    ) == 1


def test_main_system_gate_holds_no_git_or_pull_request_write_permission() -> None:
    assert load_workflow(MAIN_SYSTEM_GATE).permissions == {
        "contents": "read",
        "pull-requests": "read",
    }


def test_staging_gate_holds_no_git_or_pull_request_write_permission() -> None:
    assert load_workflow(STAGING_GATE).permissions == {
        "contents": "read",
        "pull-requests": "read",
    }


@pytest.mark.parametrize(
    ("name", "old", "new", "expected"),
    [
        (
            "repomap-staging-gate.yml",
            "on:\n  workflow_dispatch:",
            "on:\n  pull_request:\n  workflow_dispatch:",
            "explicit ",
        ),
        (
            "repomap-staging-gate.yml",
            "  pull-requests: read",
            "  pull-requests: write",
            "not read-only",
        ),
        (
            "repomap-staging-gate.yml",
            "        run: df -B1 /\n\n      - name: Run the staging smoke and integration gate",
            "        run: git push origin HEAD\n\n      - name: Run the staging smoke and integration gate",
            "not git",
        ),
        (
            "repomap-staging-gate.yml",
            "uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
            "uses: actions/upload-artifact@v7",
            "40-hex SHA pin",
        ),
        (
            "repomap-staging-gate.yml",
            "      - name: Record free disk before the staging suite\n",
            "      - name: Duplicate host Go setup\n"
            "        uses: actions/setup-go@b7ad1dad31e06c5925ef5d2fc7ad053ef454303e\n"
            "        with:\n"
            '          go-version: "1.25"\n\n'
            "      - name: Record free disk before the staging suite\n",
            "must not duplicate host toolchain bootstrap",
        ),
        (
            "repomap-staging-gate.yml",
            "      - name: Record free disk before the staging suite\n",
            "      - name: Duplicate host Python test environment\n"
            '        run: python -m pip install --editable ".[test,scale-tools,static-analysis]"\n\n'
            "      - name: Record free disk before the staging suite\n",
            "must not duplicate host toolchain bootstrap",
        ),
        (
            "repomap-staging-gate.yml",
            "      - name: Record free disk before the staging suite\n",
            "      - name: Duplicate host linter install\n"
            "        run: go install github.com/golangci/golangci-lint/v2/cmd/golangci-lint@v2.6.2\n\n"
            "      - name: Record free disk before the staging suite\n",
            "must not duplicate host toolchain bootstrap",
        ),
        (
            "repomap-staging-gate.yml",
            "            --sandbox \\\n",
            "",
            "must use --sandbox",
        ),
        (
            "repomap-staging-gate.yml",
            'python3 -S -E "${RUNNER_TEMP}/gate_contract.py" verify',
            "python3 -S -E tools/ci/gate_contract.py verify",
            "trusted gate contract",
        ),
        (
            "repomap-staging-gate.yml",
            'python3 -S -E "${RUNNER_TEMP}/gate_contract.py" record',
            'python3 "${RUNNER_TEMP}/gate_contract.py" record',
            "trusted gate contract",
        ),
        (
            "repomap-staging-gate.yml",
            '--executor-ref "${GITHUB_REF}"',
            '--executor-ref "refs/heads/staging"',
            "trusted executor ref/SHA inputs",
        ),
        (
            "repomap-staging-gate.yml",
            "          ref: ${{ github.sha }}",
            "          ref: refs/heads/feature",
            "capture trusted staging semantics",
        ),
        (
            "repomap-main-system-gate.yml",
            "      - name: Run the main system gate\n"
            "        id: system\n"
            "        env:\n"
            "          APPROVAL_ID: ${{ inputs.approval_id }}",
            "      - name: Run the main system gate\n"
            "        id: system\n"
            "        env:\n"
            "          APPROVAL_ID: ${{ inputs.request_kind }}",
            "exact step environment",
        ),
    ],
)
def test_gate_contracts_detect_their_own_violation(
    tmp_path: Path, name: str, old: str, new: str, expected: str
) -> None:
    violations = violations_after(tmp_path, lambda root: edit(root, name, old, new))
    assert any(expected in violation for violation in violations), violations
