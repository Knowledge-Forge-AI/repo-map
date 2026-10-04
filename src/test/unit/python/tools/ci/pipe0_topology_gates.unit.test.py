"""REPOMAP-CI-PIPE0 qualification-gate topology contracts."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[6]
TOOLS_ROOT = ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from ci.ci_topology import (
    _validate_main_system_gate_ordering,
    _validate_staging_runner_tokens,
)
from ci.ci_topology_contracts import check_trusted_gate_copy_set
from ci.workflow_model import Workflow, load_workflow
from src.test.unit.python.tools.ci.pipe0_topology_support import (
    GATE_VIOLATION_CASES,
    MAIN_SYSTEM_GATE,
    PUBLIC_QUALIFICATION_GATE,
    STAGING_GATE,
    TRUSTED_GATE_CONTRACT,
    TRUSTED_GATE_INVOCATION,
    WORKFLOW_DIR,
    edit,
    violations_after,
)


def test_exhaustive_qualification_no_longer_runs_on_pull_requests() -> None:
    if not STAGING_GATE.exists():
        pytest.skip("withheld in public projection: STAGING_GATE absent")
    assert set(load_workflow(STAGING_GATE).triggers) == {"workflow_dispatch"}


def test_staging_gate_requires_an_explicit_logical_gate_request() -> None:
    if not STAGING_GATE.exists():
        pytest.skip("withheld in public projection: STAGING_GATE absent")
    inputs = load_workflow(STAGING_GATE).triggers["workflow_dispatch"]["inputs"]
    assert set(inputs) == {
        "pr_number", "approved_base_sha", "approved_head_sha", "approval_id",
    }
    for definition in inputs.values():
        assert definition["required"] is True


def test_staging_gate_binds_the_candidate_before_expensive_work() -> None:
    if not STAGING_GATE.exists():
        workflow = load_workflow(PUBLIC_QUALIFICATION_GATE)
        policy_steps = workflow.jobs["source-and-export-policy"].get("steps", [])
        policy_text = ["\n".join(str(s.get(k, "")) for k in ("run", "uses")) for s in policy_steps]
        assert any("python3 tools/ci/public_export_policy.py" in item for item in policy_text)
        downstream = ["pre-review-static", "unit-tests", "staging-integration-gate", "main-system-gate"]
        codeql_sbom = [k for k in workflow.jobs if any(m in k.lower() for m in ("codeql", "sbom"))]
        assert codeql_sbom, "codeql/sbom jobs must be declared"
        for key in (*downstream, *codeql_sbom):
            raw_needs = workflow.jobs[key].get("needs")
            needs = [raw_needs] if isinstance(raw_needs, str) else (raw_needs or [])
            assert "source-and-export-policy" in needs, f"{key} missing source-and-export-policy dependency"
        assert _validate_main_system_gate_ordering(workflow, "main-system-gate") == []
        return
    steps = load_workflow(STAGING_GATE).steps()
    text = ["\n".join(str(step.get(key, "")) for key in ("run", "uses")) for step in steps]
    trusted_checkout_index = next(
        i for i, step in enumerate(steps)
        if str(step.get("uses", "")).startswith("actions/checkout@")
        and step.get("with", {}).get("ref") == "${{ github.sha }}"
    )
    preserve_index = next(i for i, item in enumerate(text) if f"cp tools/ci/gate_contract.py {TRUSTED_GATE_CONTRACT}" in item)
    resolve_index = next(i for i, item in enumerate(text) if f"{TRUSTED_GATE_INVOCATION} resolve" in item)
    candidate_checkout_index = next(
        i for i, step in enumerate(steps)
        if str(step.get("uses", "")).startswith("actions/checkout@")
        and str(step.get("with", {}).get("ref", "")).startswith("refs/pull/")
    )
    verify_index = next(i for i, item in enumerate(text) if f"{TRUSTED_GATE_INVOCATION} verify" in item)
    expensive = [i for i, item in enumerate(text) if any(m in item for m in ("pip install", "docker pull", "setup-go", "setup-python"))]
    suite_index = next(i for i, item in enumerate(text) if "python3 tools/run_tests.py" in item)
    assert trusted_checkout_index < preserve_index < resolve_index < candidate_checkout_index < verify_index < min(expensive) < suite_index


def test_staging_gate_uses_the_trusted_contract_for_every_authorization_command() -> None:
    if not STAGING_GATE.exists():
        pytest.skip("withheld in public projection: trusted gate contract copy and invocation is private-authority only")
    commands = "\n".join(load_workflow(STAGING_GATE).run_commands())
    assert '--executor-ref "${GITHUB_REF}"' in commands
    assert '--executor-sha "${GITHUB_SHA}"' in commands
    for command in ("resolve", "verify", "record"):
        assert commands.count(f"{TRUSTED_GATE_INVOCATION} {command}") == 1
        assert f"tools/ci/gate_contract.py {command}" not in commands


def test_staging_gate_records_the_exact_candidate_sha_and_tree() -> None:
    if not STAGING_GATE.exists():
        workflow = load_workflow(PUBLIC_QUALIFICATION_GATE)
        system_commands = "\n".join(str(s.get("run", "")) for s in workflow.jobs["main-system-gate"].get("steps", []))
        for check in ("git rev-parse HEAD", "git rev-parse 'HEAD^{tree}'", "git rev-parse 'HEAD^1'", "git rev-parse 'HEAD^2'", "repomap-ci-gate-request-v1"):
            assert check in system_commands
        return
    commands = "\n".join(load_workflow(STAGING_GATE).run_commands())
    for check in ("git rev-parse HEAD", "git rev-parse 'HEAD^{tree}'", "git rev-parse 'HEAD^1'", "git rev-parse 'HEAD^2'", f"{TRUSTED_GATE_INVOCATION} record", "repomap-ci-gate-result-v1.json"):
        assert check in commands


def test_staging_command_preserves_its_accepted_arguments() -> None:
    is_staging = STAGING_GATE.exists()
    workflow = load_workflow(STAGING_GATE if is_staging else PUBLIC_QUALIFICATION_GATE)
    job_name = "repomap-staging-gate" if is_staging else "staging-integration-gate"
    assert workflow.jobs[job_name]["timeout-minutes"] == 180
    assert _validate_staging_runner_tokens(workflow, job_name) == []
    commands = "\n".join(workflow.job_run_commands(job_name))
    assert commands.count("--suite staging") == 1
    assert commands.count("df -B1 /") == 1


def test_main_system_command_preserves_its_accepted_arguments() -> None:
    is_main = MAIN_SYSTEM_GATE.exists()
    workflow = load_workflow(MAIN_SYSTEM_GATE if is_main else PUBLIC_QUALIFICATION_GATE)
    job_name = "repomap-main-system-gate" if is_main else "main-system-gate"
    assert workflow.jobs[job_name]["timeout-minutes"] == 90
    assert _validate_main_system_gate_ordering(workflow, job_name) == []
    commands = "\n".join(workflow.job_run_commands(job_name))
    for argument in (
        "--suite system", "--system-timeout 3600", "--hygiene-profile exhaustive",
        "--declared-complete-gates 1", "--operator-attest-exclusive",
        "--operator-attest-pressure-degradation", "--sandbox", "--report",
    ):
        assert argument in commands
    assert commands.count("--suite system") == 1
    for retired in ("--suite all", "--suite unit", "--suite int", "--suite staging", "--suite smoke"):
        assert retired not in commands
    assert commands.count("df -B1 /") == 1
    assert not any(action.lower().startswith("actions/setup-go@") for action in workflow.job_action_uses(job_name))
    lowered = commands.lower()
    assert "pip install" not in lowered and "go install" not in lowered and "golangci-lint" not in lowered


def test_main_system_gate_passes_the_bound_request_and_candidate_identities() -> None:
    if not MAIN_SYSTEM_GATE.exists():
        workflow = load_workflow(PUBLIC_QUALIFICATION_GATE)
        system_steps = [s for s in workflow.jobs["main-system-gate"].get("steps", []) if "--suite system" in str(s.get("run", ""))]
        assert len(system_steps) == 1
        assert system_steps[0].get("env") == {"PR_NUMBER": "${{ github.event.pull_request.number }}"}
        cmd = str(system_steps[0].get("run", ""))
        for argument in (
            '--gate-request-json "${RUNNER_TEMP}/gate-request.json"',
            '--candidate-sha "${CANDIDATE_SHA}"', '--candidate-tree "${CANDIDATE_TREE}"',
            '--candidate-base-parent "${CANDIDATE_BASE_PARENT}"', '--candidate-head-parent "${CANDIDATE_HEAD_PARENT}"',
            '--approval-id "pr-${PR_NUMBER}"', '--pr-number "${PR_NUMBER}"', '--repository "${GITHUB_REPOSITORY}"',
        ):
            assert cmd.count(argument) == 1
        return
    workflow = load_workflow(MAIN_SYSTEM_GATE)
    system_steps = [step for step in workflow.steps() if "--suite system" in str(step.get("run", ""))]
    assert len(system_steps) == 1
    assert system_steps[0].get("env") == {"APPROVAL_ID": "${{ inputs.approval_id }}", "PR_NUMBER": "${{ inputs.pr_number }}"}
    commands = [c for c in workflow.run_commands() if "--suite system" in c]
    assert len(commands) == 1
    expected_args = (
        '--gate-request-json "${RUNNER_TEMP}/gate-request.json"', '--candidate-sha "${CANDIDATE_SHA}"',
        '--candidate-tree "${CANDIDATE_TREE}"', '--candidate-base-parent "${CANDIDATE_BASE_PARENT}"',
        '--candidate-head-parent "${CANDIDATE_HEAD_PARENT}"', '--approval-id "${APPROVAL_ID}"',
        '--pr-number "${PR_NUMBER}"', '--repository "${GITHUB_REPOSITORY}"',
    )
    for argument in expected_args:
        assert commands[0].count(argument) == 1


def test_main_system_gate_records_the_closed_report_and_binding() -> None:
    if not MAIN_SYSTEM_GATE.exists():
        workflow = load_workflow(PUBLIC_QUALIFICATION_GATE)
        upload_step = next(s for s in workflow.jobs["main-system-gate"].get("steps", []) if str(s.get("uses", "")).startswith("actions/upload-artifact@"))
        assert upload_step.get("with", {}).get("name") == "repomap-main-system-gate-report"
        assert upload_step.get("with", {}).get("path") == "ci-system-report"
        return
    commands = [c for c in load_workflow(MAIN_SYSTEM_GATE).run_commands() if 'gate_contract.py" record' in c]
    assert len(commands) == 1
    assert commands[0].count('--system-report-json "${GITHUB_WORKSPACE}/ci-system-report/repomap-system-gate-report.json"') == 1
    assert commands[0].count('--system-binding-json "${GITHUB_WORKSPACE}/ci-system-report/repomap-system-gate-binding-v1.json"') == 1


def test_main_system_gate_holds_no_git_or_pull_request_write_permission() -> None:
    if not MAIN_SYSTEM_GATE.exists():
        assert load_workflow(PUBLIC_QUALIFICATION_GATE).permissions == {"contents": "read"}
        return
    assert load_workflow(MAIN_SYSTEM_GATE).permissions == {"contents": "read", "pull-requests": "read"}


def test_staging_and_main_gates_match_declared_trusted_copy_set() -> None:
    if not STAGING_GATE.exists():
        pytest.skip("withheld in public projection: trusted gate copy set is private-authority only")
    for gate_path in (STAGING_GATE, MAIN_SYSTEM_GATE):
        workflow = load_workflow(gate_path)
        steps = workflow.steps()
        text = ["\n".join(str(s.get(k, "")) for k in ("run", "uses")) for s in steps]
        preserve_idx = next(i for i, item in enumerate(text) if f"cp tools/ci/gate_contract.py {TRUSTED_GATE_CONTRACT}" in item)
        assert check_trusted_gate_copy_set(gate_path.name, steps, preserve_idx) == []


def test_staging_gate_holds_no_git_or_pull_request_write_permission() -> None:
    if not STAGING_GATE.exists():
        assert load_workflow(PUBLIC_QUALIFICATION_GATE).permissions == {"contents": "read"}
        return
    assert load_workflow(STAGING_GATE).permissions == {"contents": "read", "pull-requests": "read"}


@pytest.mark.parametrize(("name", "old", "new", "expected"), GATE_VIOLATION_CASES)
def test_gate_contracts_detect_their_own_violation(
    tmp_path: Path, name: str, old: str, new: str, expected: str
) -> None:
    if not (WORKFLOW_DIR / name).exists():
        pytest.skip(f"withheld in public projection: workflow {name} absent")
    violations = violations_after(tmp_path, lambda root: edit(root, name, old, new))
    assert any(expected in violation for violation in violations), violations


def test_main_system_gate_needs_source_and_export_policy_and_not_staging() -> None:
    if STAGING_GATE.exists():
        pytest.skip("withheld in private workspace: STAGING_GATE present")
    workflow = load_workflow(PUBLIC_QUALIFICATION_GATE)
    needs = workflow.jobs["main-system-gate"].get("needs")
    if isinstance(needs, str):
        needs = [needs]
    assert needs == ["source-and-export-policy"]


def test_staging_runner_missing_report_flag_is_detected() -> None:
    path = STAGING_GATE if STAGING_GATE.exists() else PUBLIC_QUALIFICATION_GATE
    wf = load_workflow(path)
    job_name = "repomap-staging-gate" if STAGING_GATE.exists() else "staging-integration-gate"
    steps = wf.job_steps(job_name)
    mutated_steps = []
    for s in steps:
        if s.get("run") and "--suite staging" in str(s["run"]):
            mutated_run = str(s["run"]).replace("--report \\\n", "").replace("--report \n", "").replace("--report ", "")
            mutated_steps.append({**s, "run": mutated_run})
        else:
            mutated_steps.append(s)
    mutated_jobs = {**wf.jobs, job_name: {**wf.jobs[job_name], "steps": mutated_steps}}
    mutated_wf = Workflow(wf.path, {**wf.document, "jobs": mutated_jobs})
    violations = _validate_staging_runner_tokens(mutated_wf, job_name)
    assert any("missing exact --report flag" in v for v in violations)


def test_staging_runner_cross_job_leakage_is_detected() -> None:
    path = STAGING_GATE if STAGING_GATE.exists() else PUBLIC_QUALIFICATION_GATE
    wf = load_workflow(path)
    job_name = "repomap-staging-gate" if STAGING_GATE.exists() else "staging-integration-gate"
    staging_step = next(s for s in wf.job_steps(job_name) if s.get("run") and "--suite staging" in str(s["run"]))
    mutated_jobs = {**wf.jobs, "other-job": {"steps": [staging_step]}}
    mutated_wf = Workflow(wf.path, {**wf.document, "jobs": mutated_jobs})
    violations = _validate_staging_runner_tokens(mutated_wf, job_name)
    assert any("cross-job leakage: staging runner found in other-job" in v for v in violations)


def test_staging_runner_duplicate_runner_is_detected() -> None:
    path = STAGING_GATE if STAGING_GATE.exists() else PUBLIC_QUALIFICATION_GATE
    wf = load_workflow(path)
    job_name = "repomap-staging-gate" if STAGING_GATE.exists() else "staging-integration-gate"
    steps = list(wf.job_steps(job_name))
    staging_step = next(s for s in steps if s.get("run") and "--suite staging" in str(s["run"]))
    steps.append(staging_step)
    mutated_jobs = {**wf.jobs, job_name: {**wf.jobs[job_name], "steps": steps}}
    mutated_wf = Workflow(wf.path, {**wf.document, "jobs": mutated_jobs})
    violations = _validate_staging_runner_tokens(mutated_wf, job_name)
    assert any("duplicate staging runner" in v and "found 2" in v for v in violations)


def test_main_system_gate_bind_ordering_on_real_workflow() -> None:
    path = MAIN_SYSTEM_GATE if MAIN_SYSTEM_GATE.exists() else PUBLIC_QUALIFICATION_GATE
    wf = load_workflow(path)
    job_name = "repomap-main-system-gate" if MAIN_SYSTEM_GATE.exists() else "main-system-gate"
    assert _validate_main_system_gate_ordering(wf, job_name) == []
    steps = list(wf.job_steps(job_name))
    bind_idx = next(i for i, s in enumerate(steps) if s.get("id") == "bind" or "CANDIDATE_SHA=" in str(s.get("run", "")))
    setup_idx = next(i for i, s in enumerate(steps) if str(s.get("uses", "")).startswith("actions/setup-python@"))
    steps[bind_idx], steps[setup_idx] = steps[setup_idx], steps[bind_idx]
    mutated_jobs = {**wf.jobs, job_name: {**wf.jobs[job_name], "steps": steps}}
    mutated_wf = Workflow(wf.path, {**wf.document, "jobs": mutated_jobs})
    violations = _validate_main_system_gate_ordering(mutated_wf, job_name)
    assert any("candidate binding must precede setup-python" in v for v in violations)
