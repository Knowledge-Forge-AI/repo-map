"""Unit tests for public native D12 qualification job and system-hold contracts."""

from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[6]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ci.qualification_native_contracts import (
    D12_NATIVE_AMD64_NODE_ID,
    load_native_amd64_job_fragment,
    load_system_hold_step_fragment,
    project_public_qualification_workflow,
    validate_d12_native_amd64_job,
    validate_d12_native_amd64_runner_command,
    validate_d12_system_hold_step,
    validate_maintained_fragments,
)
from ci.workflow_model import load_workflow
from src.test.unit.python.tools.ci.d12_hosted_workflow_fixture import (
    PUBLIC_RELEASE_QUALIFICATION_WORKFLOW_TEXT,
)

BASE_PUBLIC_WORKFLOW = PUBLIC_RELEASE_QUALIFICATION_WORKFLOW_TEXT


def _load(tmp_path: Path, text: str, name: str = "repomap-release-qualification.yml"):
    wf_path = tmp_path / name
    wf_path.write_text(text, encoding="utf-8")
    return load_workflow(wf_path)


def test_maintained_yaml_fragments_and_projected_public_workflow_pass(
    tmp_path: Path,
) -> None:
    assert validate_maintained_fragments(REPO_ROOT) == []
    job_frag = load_native_amd64_job_fragment()
    assert "d12-native-amd64" in job_frag
    hold_steps = load_system_hold_step_fragment()
    assert len(hold_steps) == 1

    projected_text = project_public_qualification_workflow(BASE_PUBLIC_WORKFLOW)
    wf = _load(tmp_path, projected_text)
    assert validate_d12_native_amd64_job(wf) == []
    assert validate_d12_system_hold_step(wf) == []


def test_native_runner_command_contract_rejects_hidden_wrong_or_ledger_flags() -> None:
    valid_cmd = (
        "python3 tools/run_tests.py --sandbox --suite int --no-coverage --jobs 1 "
        "--pg-container-port 55433 --d12-core-image-profile linux/amd64 "
        "--d12-core-image-preflight "
        '--d12-core-image-source-sha256 "${D12_EXPECTED_SOURCE_SHA256}" '
        '--report-dir "${RUNNER_TEMP}/d12-native-amd64-report" '
        f"-- {D12_NATIVE_AMD64_NODE_ID}"
    )
    assert validate_d12_native_amd64_runner_command(valid_cmd) == []

    hidden = "python3 tools/ci/d12_hosted_qualification.py run-inner"
    assert any("run_tests.py" in v for v in validate_d12_native_amd64_runner_command(hidden))

    with_ledger = valid_cmd + ' --d12-core-image-budget-ledger "/tmp/ledger.json"'
    assert any(
        "budget-ledger" in v
        for v in validate_d12_native_amd64_runner_command(with_ledger)
    )

    with_arm = valid_cmd.replace("linux/amd64", "linux/arm64")
    assert validate_d12_native_amd64_runner_command(with_arm) != []

    with_retry = f"for attempt in 1 2; do {valid_cmd} && break; done"
    assert any("retry" in v or "loop" in v for v in validate_d12_native_amd64_runner_command(with_retry))

    with_while = f"while true; do {valid_cmd}; break; done"
    assert any("retry" in v or "loop" in v for v in validate_d12_native_amd64_runner_command(with_while))

    with_subshell_loop = f"(until true; do break; done) && {valid_cmd}"
    assert any("retry" in v or "loop" in v for v in validate_d12_native_amd64_runner_command(with_subshell_loop))

    with_cmd_sub_loop = f'echo "$(while true; do break; done)" && {valid_cmd}'
    assert any("retry" in v or "loop" in v for v in validate_d12_native_amd64_runner_command(with_cmd_sub_loop))

    with_quoted_words = f'echo "waiting for native lane while until done" && {valid_cmd}'
    assert validate_d12_native_amd64_runner_command(with_quoted_words) == []

    with_arg_words = f"echo for while until && {valid_cmd}"
    assert validate_d12_native_amd64_runner_command(with_arg_words) == []


def test_native_job_contract_requires_bind_step_and_rejects_arm_emulation_bad_timeout(
    tmp_path: Path,
) -> None:
    projected = project_public_qualification_workflow(BASE_PUBLIC_WORKFLOW)
    wf = _load(tmp_path, projected, "valid.yml")
    native_steps = list(wf.jobs["d12-native-amd64"].get("steps", []))
    bind_steps = [step for step in native_steps if step.get("id") == "bind"]
    assert len(bind_steps) == 1
    assert "CANDIDATE_SHA=" in str(bind_steps[0].get("run", ""))
    assert "CANDIDATE_TREE=" in str(bind_steps[0].get("run", ""))

    bad_runner = _load(
        tmp_path, projected.replace("runs-on: ubuntu-24.04", "runs-on: ubuntu-24.04-arm"), "r.yml"
    )
    assert any("ubuntu-24.04" in v for v in validate_d12_native_amd64_job(bad_runner))

    bad_timeout = _load(
        tmp_path, projected.replace("timeout-minutes: 90", "timeout-minutes: 120"), "t.yml"
    )
    assert any("timeout" in v for v in validate_d12_native_amd64_job(bad_timeout))

    with_qemu = _load(
        tmp_path,
        projected.replace(
            "uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97",
            "uses: docker/setup-qemu-action@v3",
        ),
        "q.yml",
    )
    assert any("action" in v or "qemu" in v for v in validate_d12_native_amd64_job(with_qemu))

    bad_retention = _load(
        tmp_path, projected.replace("retention-days: 14", "retention-days: 7"), "ret.yml"
    )
    assert any("retention-days" in v for v in validate_d12_native_amd64_job(bad_retention))

    extra_arm_job = _load(
        tmp_path,
        projected + "\n  d12-native-arm64:\n    runs-on: ubuntu-24.04-arm\n    steps:\n      - run: echo hi\n",
        "arm.yml",
    )
    assert any("arm64" in v for v in validate_d12_native_amd64_job(extra_arm_job))


def test_system_hold_contract_requires_step_after_setup_python_and_before_system_runner(
    tmp_path: Path,
) -> None:
    unprojected = _load(tmp_path, BASE_PUBLIC_WORKFLOW, "unproj.yml")
    assert any("system-hold" in v for v in validate_d12_system_hold_step(unprojected))

    projected = project_public_qualification_workflow(BASE_PUBLIC_WORKFLOW)
    wf = _load(tmp_path, projected, "proj.yml")
    steps = list(wf.jobs["main-system-gate"].get("steps", []))
    setup_idx = next(
        idx
        for idx, step in enumerate(steps)
        if str(step.get("uses", "")).startswith("actions/setup-python@")
    )
    hold_idx = next(idx for idx, step in enumerate(steps) if step.get("id") == "d12-system-hold")
    sys_idx = next(
        idx
        for idx, step in enumerate(steps)
        if "tools/run_tests.py" in str(step.get("run", ""))
    )
    assert setup_idx < hold_idx < sys_idx

    misordered_doc = dict(wf.document)
    misordered_jobs = dict(wf.jobs)
    misordered_main = dict(misordered_jobs["main-system-gate"])
    reordered_steps = list(steps)
    hold_step = reordered_steps.pop(hold_idx)
    reordered_steps.insert(setup_idx, hold_step)
    misordered_main["steps"] = reordered_steps
    misordered_jobs["main-system-gate"] = misordered_main
    misordered_doc["jobs"] = misordered_jobs
    from ci.workflow_model import Workflow

    misordered_wf = Workflow(wf.path, misordered_doc)
    assert any("setup-python" in v for v in validate_d12_system_hold_step(misordered_wf))

    hold_hdr = "- name: Verify release prerequisites before system SDK or candidate build\n"
    continue_on_err = _load(
        tmp_path,
        projected.replace(hold_hdr, hold_hdr + "        continue-on-error: true\n"),
        "coe.yml",
    )
    assert any(
        "continue-on-error" in v for v in validate_d12_system_hold_step(continue_on_err)
    )


def test_system_hold_contract_rejects_if_gating_and_continue_on_error_expressions(
    tmp_path: Path,
) -> None:
    projected = project_public_qualification_workflow(BASE_PUBLIC_WORKFLOW)
    hold_hdr = "- name: Verify release prerequisites before system SDK or candidate build\n"
    for idx, cond in enumerate(("false", "${{ false }}", "always()")):
        gated = _load(
            tmp_path,
            projected.replace(hold_hdr, hold_hdr + f"        if: {cond}\n", 1),
            f"hold-if-{idx}.yml",
        )
        violations = validate_d12_system_hold_step(gated)
        assert any("d12-system-hold" in v and "if" in v for v in violations)

    expr_coe = _load(
        tmp_path,
        projected.replace(hold_hdr, hold_hdr + "        continue-on-error: ${{ true }}\n", 1),
        "hold-coe-expr.yml",
    )
    assert any("continue-on-error" in v for v in validate_d12_system_hold_step(expr_coe))


def test_native_prepare_step_contract_rejects_if_gating_and_continue_on_error(
    tmp_path: Path,
) -> None:
    projected = project_public_qualification_workflow(BASE_PUBLIC_WORKFLOW)
    prep_hdr = "      - name: Prepare native D12 qualification\n"
    for idx, cond in enumerate(("false", "${{ false }}", "always()")):
        gated = _load(
            tmp_path,
            projected.replace(prep_hdr, prep_hdr + f"        if: {cond}\n", 1),
            f"prep-if-{idx}.yml",
        )
        violations = validate_d12_native_amd64_job(gated)
        assert any("prepare" in v and "if" in v for v in violations)

    for idx, coe in enumerate(("true", "${{ true }}")):
        with_coe = _load(
            tmp_path,
            projected.replace(prep_hdr, prep_hdr + f"        continue-on-error: {coe}\n", 1),
            f"prep-coe-{idx}.yml",
        )
        violations = validate_d12_native_amd64_job(with_coe)
        assert any("prepare" in v and "continue-on-error" in v for v in violations)


def test_native_runner_step_contract_rejects_if_gating_and_continue_on_error(
    tmp_path: Path,
) -> None:
    projected = project_public_qualification_workflow(BASE_PUBLIC_WORKFLOW)
    run_hdr = "      - name: Run canonical D12 native preflight\n"
    for idx, cond in enumerate(("false", "${{ false }}", "always()")):
        gated = _load(
            tmp_path,
            projected.replace(run_hdr, run_hdr + f"        if: {cond}\n", 1),
            f"run-if-{idx}.yml",
        )
        violations = validate_d12_native_amd64_job(gated)
        assert any("runner" in v and "if" in v for v in violations)

    for idx, coe in enumerate(("true", "${{ true }}")):
        with_coe = _load(
            tmp_path,
            projected.replace(run_hdr, run_hdr + f"        continue-on-error: {coe}\n", 1),
            f"run-coe-{idx}.yml",
        )
        violations = validate_d12_native_amd64_job(with_coe)
        assert any("runner" in v and "continue-on-error" in v for v in violations)
