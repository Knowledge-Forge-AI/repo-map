"""Topology contracts and verified hermetic gate copy set validation."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[6]
TOOLS_ROOT = ROOT / "tools"
TOOLS_CI = TOOLS_ROOT / "ci"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from ci.ci_topology_contracts import (
    MAIN_SYSTEM_GATE_WORKFLOW,
    STAGING_GATE_WORKFLOW,
    TRUSTED_GATE_COPY_SET,
    check_trusted_gate_copy_set,
)
from ci.ci_topology_gates import _check_main_system_gate, _check_staging_gate
from ci.workflow_model import Workflow, load_workflow

WORKFLOWS_DIR = ROOT / ".github/workflows"
STAGING_WORKFLOW_PATH = WORKFLOWS_DIR / STAGING_GATE_WORKFLOW
MAIN_WORKFLOW_PATH = WORKFLOWS_DIR / MAIN_SYSTEM_GATE_WORKFLOW


def test_production_gate_workflows_satisfy_topology_contracts() -> None:
    staging_wf = load_workflow(STAGING_WORKFLOW_PATH)
    staging_violations = _check_staging_gate(staging_wf)
    assert staging_violations == [], f"staging gate violations: {staging_violations}"

    main_wf = load_workflow(MAIN_WORKFLOW_PATH)
    main_violations = _check_main_system_gate(main_wf)
    assert main_violations == [], f"main system gate violations: {main_violations}"


@pytest.mark.parametrize(
    ("workflow_path", "gate_name"),
    [
        (STAGING_WORKFLOW_PATH, "repomap-staging-gate.yml"),
        (MAIN_WORKFLOW_PATH, "repomap-main-system-gate.yml"),
    ],
)
def test_trusted_gate_copy_set_is_exact_in_both_workflows(
    workflow_path: Path, gate_name: str
) -> None:
    workflow = load_workflow(workflow_path)
    steps = workflow.steps()
    preserve_step = next(
        (step for step in steps if "Preserve the trusted gate contract" in str(step.get("name", ""))),
        None,
    )
    assert preserve_step is not None, f"{gate_name} missing preserve step"
    text = str(preserve_step.get("run", ""))

    assert 'mkdir -p "${RUNNER_TEMP}/ci"' in text
    last_pos = -1
    for src, dst in TRUSTED_GATE_COPY_SET:
        cmd = f"cp {src} {dst}"
        assert cmd in text, f"{gate_name} missing copy command: {cmd}"
        pos = text.find(cmd)
        assert pos > last_pos, f"{gate_name} copy command out of order: {cmd}"
        last_pos = pos


@pytest.mark.parametrize(
    "workflow_path",
    [STAGING_WORKFLOW_PATH, MAIN_WORKFLOW_PATH],
)
def test_trusted_copy_set_provenance_and_ordering(workflow_path: Path) -> None:
    workflow: Workflow = load_workflow(workflow_path)
    steps = workflow.steps()

    trusted_checkout_idx = next(
        i for i, step in enumerate(steps)
        if str(step.get("uses", "")).startswith("actions/checkout@")
        and step.get("with", {}).get("ref") == "${{ github.sha }}"
    )
    preserve_idx = next(
        i for i, step in enumerate(steps)
        if "Preserve the trusted gate contract" in str(step.get("name", ""))
    )
    candidate_checkout_idx = next(
        i for i, step in enumerate(steps)
        if str(step.get("uses", "")).startswith("actions/checkout@")
        and str(step.get("with", {}).get("ref", "")).startswith("refs/pull/")
    )

    assert trusted_checkout_idx < preserve_idx < candidate_checkout_idx


def test_check_trusted_gate_copy_set_detects_missing_directory() -> None:
    steps: list[Mapping[str, object]] = [
        {"run": "cp tools/ci/gate_contract.py \"${RUNNER_TEMP}/gate_contract.py\""}
    ]
    violations = check_trusted_gate_copy_set("test.yml", steps, 0)
    assert any("must create ci directory" in v for v in violations)


@pytest.mark.parametrize("missing_src,missing_dst", TRUSTED_GATE_COPY_SET)
def test_check_trusted_gate_copy_set_detects_missing_command(
    missing_src: str, missing_dst: str
) -> None:
    lines = ['mkdir -p "${RUNNER_TEMP}/ci"']
    for src, dst in TRUSTED_GATE_COPY_SET:
        if src != missing_src:
            lines.append(f"cp {src} {dst}")
    steps: list[Mapping[str, object]] = [{"run": "\n".join(lines)}]

    violations = check_trusted_gate_copy_set("test.yml", steps, 0)
    expected = f"missing copy command: cp {missing_src} {missing_dst}"
    assert any(expected in v for v in violations), violations


def test_check_trusted_gate_copy_set_detects_reversed_order() -> None:
    lines = ['mkdir -p "${RUNNER_TEMP}/ci"']
    for src, dst in reversed(TRUSTED_GATE_COPY_SET):
        lines.append(f"cp {src} {dst}")
    steps: list[Mapping[str, object]] = [{"run": "\n".join(lines)}]

    violations = check_trusted_gate_copy_set("test.yml", steps, 0)
    assert any("order is invalid" in v for v in violations), violations


def test_check_trusted_gate_copy_set_empty_when_no_preserve_step() -> None:
    assert check_trusted_gate_copy_set("test.yml", [], None) == []


@pytest.mark.parametrize("extra", (
    'cp candidate.py "${RUNNER_TEMP}/ci/gate_contract_bindings.py"',
    'cp tools/ci/*.py "${RUNNER_TEMP}/ci/"',
))
def test_trusted_copy_set_rejects_extra_or_overwriting_commands(extra: str) -> None:
    lines = ['mkdir -p "${RUNNER_TEMP}/ci"']
    lines.extend(f"cp {source} {destination}" for source, destination in TRUSTED_GATE_COPY_SET)
    steps: list[Mapping[str, object]] = [{"run": "\n".join([*lines, extra])}]
    assert any("exact declared copy set" in item
               for item in check_trusted_gate_copy_set("test.yml", steps, 0))
