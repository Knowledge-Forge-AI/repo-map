"""Exact native-job raw Python selection; AMD component diagnostic authority only."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any

import pytest

from ci.d12_hosted_reports import validate_canonical_exploration_report
from ci.qualification_native_contracts import (
    D12_NATIVE_AMD64_RAW_PYTHON_CONFIG,
    load_native_amd64_job_fragment,
    validate_d12_native_amd64_job,
    validate_d12_native_amd64_runner_command,
)
from ci.workflow_model import load_workflow
import d12_native_python_observer as observer
from common_lore_index.runtime import python_payload as payload

ROOT = Path(__file__).resolve().parents[6]
WORKFLOW = ROOT / ".github/workflows/repomap-release-qualification.yml"
PIN = f"--smoke-image-reference {D12_NATIVE_AMD64_RAW_PYTHON_CONFIG}"
PIN_REQUIRED = "must pass exactly one literal --smoke-image-reference"
ORIGINAL_HOOK = observer.observe_exploration


def test_native_job_requires_exact_raw_python_config() -> None:
    job = load_native_amd64_job_fragment()["d12-native-amd64"]
    script = next(step["run"] for step in job["steps"] if "tools/run_tests.py" in step.get("run", ""))
    missing_override = re.sub(r"--smoke-image-reference\s+\S+", "", script)
    violations = validate_d12_native_amd64_runner_command(missing_override)
    assert any("--smoke-image-reference" in item for item in violations), (
        "native diagnostic must require its exact raw config before dependency-runtime preparation", violations)


def _script() -> str:
    steps = load_native_amd64_job_fragment()["d12-native-amd64"]["steps"]
    [script] = [step["run"] for step in steps if "tools/run_tests.py" in step.get("run", "")]
    return str(script)


def test_fragment_and_workflow_select_the_pin_once_in_their_one_unchanged_runner() -> None:
    script = _script()
    assert D12_NATIVE_AMD64_RAW_PYTHON_CONFIG == payload.PYTHON_31216_AMD64_CONFIG
    assert validate_d12_native_amd64_runner_command(script) == [] and script.count("--smoke-image-reference") == 1
    assert re.search(r"--d12-core-image-preflight \\\n\s+" + re.escape(PIN) + r" \\\n", script), script
    assert script.count("python3 tools/run_tests.py") == 1 and "for " not in script and "retry" not in script
    if not WORKFLOW.exists():
        pytest.skip("withheld in public projection: release qualification workflow absent")
    workflow = load_workflow(WORKFLOW)
    runners = [s for s in workflow.job_steps("d12-native-amd64") if "tools/run_tests.py" in str(s.get("run", ""))]
    assert [str(step["run"]) for step in runners] == [script], "the workflow runner is the canonical fragment"
    assert validate_d12_native_amd64_job(workflow) == []
    text = WORKFLOW.read_text(encoding="utf-8")
    assert text.count("--smoke-image-reference") == 1 and text.count("python3 tools/run_tests.py") == 4


@pytest.mark.parametrize("old, new, expected", [
    (PIN, PIN.replace(payload.PYTHON_31216_AMD64_CONFIG, payload.PYTHON_31216_ARM64_CONFIG), [PIN_REQUIRED]),
    (PIN, PIN.replace(payload.PYTHON_31216_AMD64_CONFIG, "sha256:" + "0" * 64), [PIN_REQUIRED]),
    (PIN, f"{PIN} \\\n            {PIN}", [PIN_REQUIRED]),
    (PIN, f"{PIN} \\\n            --smoke-image-reference {payload.PYTHON_31216_ARM64_CONFIG}", [PIN_REQUIRED]),
    (PIN, PIN.replace("--smoke-image-reference ", "--smoke-image-reference="), [PIN_REQUIRED]),
    (PIN, PIN.replace("--smoke-image-reference", "--smoke-image-ref"),
     [PIN_REQUIRED, "unknown or abbreviated option '--smoke-image-ref'"]),
    (PIN, PIN.replace("--smoke-image-reference", "--smoke-image-reference-x"),
     [PIN_REQUIRED, "unknown or abbreviated option '--smoke-image-reference-x'"]),
    (PIN, '--smoke-image-reference "${RAW_PYTHON_IMAGE}"', [PIN_REQUIRED]),
    (PIN, "--smoke-image-reference", [PIN_REQUIRED]),
    (PIN, f"{PIN} \\\n            --unknown-flag", ["unknown or abbreviated option '--unknown-flag'"]),
    (PIN, f"{PIN} \\\n            stray", ["unknown or abbreviated option 'stray'"]),
    ("--d12-core-image-preflight \\", "--d12-core-image-pre \\",
     ["unknown or abbreviated option '--d12-core-image-pre'", "runner missing --d12-core-image-preflight"]),
    ("--no-coverage \\", "--no-cov \\", ["unknown or abbreviated option '--no-cov'", "runner missing --no-coverage"]),
    ("--jobs 1 \\", "--jobs=1 \\", []),
    ('exit "${status}"', f'python3 tools/run_tests.py {PIN}\nexit "${{status}}"',
     ["must invoke python3 tools/run_tests.py once; found 2"]),
])
def test_runner_contract_rejects_every_unknown_abbreviated_duplicate_or_foreign_pin(old: str, new: str,
                                                                                    expected: list[str]) -> None:
    script = _script()
    assert script.count(old) == 1, old
    violations = validate_d12_native_amd64_runner_command(script.replace(old, new))
    for item in expected:
        assert any(item in violation for violation in violations), (item, violations)
    assert bool(violations) is bool(expected), violations


def test_retry_loop_or_second_invocation_still_refuses_with_the_pin() -> None:
    script = _script()
    assert any("retry loop" in v for v in validate_d12_native_amd64_runner_command(f"for i in 1 2; do {script}; done"))
    doubled = validate_d12_native_amd64_runner_command(script + "\n" + script)
    assert any("once; found 2" in v for v in doubled)


def _exploration(tmp_path: Path, *, positive: bool, component: dict[str, object] | None) -> dict[str, object]:
    from src.test.unit.python.tools.ci.d12_hosted_fixtures import write_inner_reports

    path = write_inner_reports(tmp_path, positive=positive, component=component) / "exploration.json"
    report = dict(json.loads(path.read_text(encoding="utf-8")))
    assert observer.observe_exploration is ORIGINAL_HOOK, "the explicit component double is restored"
    return report


@pytest.mark.parametrize("positive", [False, True])
def test_hosted_report_retains_the_component_slot_without_changing_refusal_or_result_rules(
        tmp_path: Path, positive: bool) -> None:
    from src.test.unit.python.tools.ci.d12_hosted_fixtures import (
        SYNTHETIC_D12_DOCKERFILE_SHA256, SYNTHETIC_D12_RECIPE_SHA256, SYNTHETIC_D12_SOURCE_SHA256,
    )

    component = {**observer.new_record("linux/amd64"), "stage": "daemon",
                 "reasons": ["daemon: NativeComponentError: synthetic refusal; no AMD observation"]}
    plain = _exploration(tmp_path / "plain", positive=positive, component=None)
    with_slot = _exploration(tmp_path / "slot", positive=positive, component=component)
    steps = with_slot["steps"]
    expected = {**component, "closure_cross_check": {"result": "unavailable", "fields": []}}
    assert isinstance(steps, dict) and steps.pop(observer.SLOT) == expected
    assert "closure_cross_check" not in component, "the retained component double is copied before annotation"
    assert isinstance(plain["steps"], dict) and observer.SLOT not in plain["steps"]
    for report in (plain, with_slot):  # free capacity is a live host forecast, not part of the comparison
        report_steps = report["steps"]
        assert isinstance(report_steps, dict) and report_steps.pop("capacity")
    assert with_slot == plain and plain["result"] == ("observed" if positive else "refused")
    helper = hashlib.sha256((ROOT / "tools/native_apt_prerequisites.py").read_bytes()).hexdigest()
    kwargs: dict[str, Any] = {
        "expected_source_sha256": SYNTHETIC_D12_SOURCE_SHA256, "expected_recipe_sha256": SYNTHETIC_D12_RECIPE_SHA256,
        "expected_dockerfile_sha256": SYNTHETIC_D12_DOCKERFILE_SHA256, "expected_context_file_count": 694,
        "expected_helper_sha256": helper, "require_positive_observation": positive}
    full = _exploration(tmp_path / "full", positive=positive, component=component)
    assert validate_canonical_exploration_report(full, **kwargs) == validate_canonical_exploration_report(
        _exploration(tmp_path / "base", positive=positive, component=None), **kwargs)
