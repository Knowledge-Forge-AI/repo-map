"""Staging and main-system qualification topology contracts."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING

from ci.ci_topology_contracts import (
    DEFAULT_CONTRACTS,
    TopologyContractValues,
    _first_expensive_step_index,
    _first_step_index,
    _trigger_list,
)

if TYPE_CHECKING:
    from ci.workflow_model import Workflow


def _check_staging_gate(
    workflow: Workflow,
    contracts: TopologyContractValues = DEFAULT_CONTRACTS,
    *,
    trigger_list: Callable[[object, str], list[str]] = _trigger_list,
    first_step_index: Callable[[Sequence[Mapping[str, object]], str], int | None] = _first_step_index,
    first_expensive_step_index: Callable[
        [Sequence[Mapping[str, object]], TopologyContractValues], int | None
    ] = _first_expensive_step_index,
) -> list[str]:
    violations: list[str] = []
    if workflow.name == "repomap-staging-gate":
        triggers = workflow.triggers
        if set(triggers) != {"workflow_dispatch"}:
            violations.append(
                f"{workflow.path.name}: staging qualification must require an explicit "
                f"logical gate request, got triggers {sorted(triggers)}"
            )
        dispatch = triggers.get("workflow_dispatch")
        inputs = dispatch.get("inputs") if isinstance(dispatch, dict) else None
        declared = set(inputs) if isinstance(inputs, dict) else set()
        missing = contracts.required_gate_inputs.difference(declared)
        if missing:
            violations.append(
                f"{workflow.path.name}: gate request is missing inputs {sorted(missing)}"
            )
        if dict(workflow.permissions) != {"contents": "read", "pull-requests": "read"}:
            violations.append(
                f"{workflow.path.name}: staging gate permissions must be exactly "
                f"contents/pull-requests read, got {dict(workflow.permissions)}"
            )
        job = workflow.jobs.get("repomap-staging-gate")
        if not isinstance(job, dict) or job.get("timeout-minutes") != 180:
            violations.append(
                f"{workflow.path.name}: staging lane timeout must be 180 minutes"
            )

    job = workflow.jobs.get("staging-integration-gate") or workflow.jobs.get("repomap-staging-gate")
    if not isinstance(job, dict):
        violations.append(f"{workflow.path.name}: staging gate job is missing")
        return violations
    if job.get("timeout-minutes") != 180:
        violations.append(
            f"{workflow.path.name}: staging lane timeout must be 180 minutes"
        )

    steps = [s for s in job.get("steps", []) if isinstance(s, dict)]
    commands = [str(step["run"]) for step in steps if "run" in step]
    command_text = "\n".join(commands)

    if commands.count(contracts.staging_marker) != 1 and command_text.count(contracts.staging_marker) != 1:
        violations.append(
            f"{workflow.path.name}: staging command must appear exactly once"
        )
    for retired in ("--suite all", "--suite unit"):
        if retired in command_text:
            violations.append(
                f"{workflow.path.name}: staging gate must not contain {retired!r}"
            )
    if "--sandbox" not in command_text:
        violations.append(
            f"{workflow.path.name}: staging qualification must use --sandbox"
        )
    if "--pg-container-port 55433" not in command_text:
        violations.append(
            f"{workflow.path.name}: staging qualification must bind pg-container-port 55433"
        )
    if "--hygiene-profile exhaustive" not in command_text:
        violations.append(
            f"{workflow.path.name}: staging qualification must specify exhaustive hygiene profile"
        )
    if "--declared-complete-gates 1" not in command_text:
        violations.append(
            f"{workflow.path.name}: staging qualification must declare complete gates 1"
        )
    if "--operator-attest-exclusive" not in command_text:
        violations.append(
            f"{workflow.path.name}: staging qualification must attest exclusive operator access"
        )
    if "--operator-attest-pressure-degradation" not in command_text:
        violations.append(
            f"{workflow.path.name}: staging qualification must attest pressure degradation"
        )
    if "--report" not in command_text or "--report-dir" not in command_text:
        violations.append(
            f"{workflow.path.name}: staging qualification must generate a report"
        )

    for action in [str(s.get("uses", "")) for s in steps]:
        if action.lower().startswith("actions/setup-go@") or "golangci-lint" in action.lower():
            violations.append(
                f"{workflow.path.name}: must not duplicate host toolchain bootstrap"
            )
    if 'pip install --editable ".[test,scale-tools,static-analysis]"' in command_text:
        violations.append(
            f"{workflow.path.name}: must not duplicate host toolchain bootstrap"
        )
    return violations


def _check_main_system_gate(
    workflow: Workflow,
    contracts: TopologyContractValues = DEFAULT_CONTRACTS,
    *,
    trigger_list: Callable[[object, str], list[str]] = _trigger_list,
    first_step_index: Callable[[Sequence[Mapping[str, object]], str], int | None] = _first_step_index,
    first_expensive_step_index: Callable[
        [Sequence[Mapping[str, object]], TopologyContractValues], int | None
    ] = _first_expensive_step_index,
) -> list[str]:
    violations: list[str] = []
    if workflow.name == "repomap-main-system-gate":
        triggers = workflow.triggers
        if set(triggers) != {"workflow_dispatch"}:
            violations.append(
                f"{workflow.path.name}: main-system qualification must require an "
                f"explicit logical gate request, got triggers {sorted(triggers)}"
            )
        dispatch = triggers.get("workflow_dispatch")
        inputs = dispatch.get("inputs") if isinstance(dispatch, dict) else None
        declared = set(inputs) if isinstance(inputs, dict) else set()
        missing = contracts.required_gate_inputs.difference(declared)
        if missing:
            violations.append(
                f"{workflow.path.name}: gate request is missing inputs {sorted(missing)}"
            )
        if dict(workflow.permissions) != {"contents": "read", "pull-requests": "read"}:
            violations.append(
                f"{workflow.path.name}: main-system gate permissions must be exactly "
                f"contents/pull-requests read, got {dict(workflow.permissions)}"
            )

    job = workflow.jobs.get("main-system-gate") or workflow.jobs.get("repomap-main-system-gate")
    if not isinstance(job, dict):
        violations.append(f"{workflow.path.name}: main system gate job is missing")
        return violations

    needs = job.get("needs")
    if needs != ["source-and-export-policy"] and needs != "source-and-export-policy":
        violations.append(
            f"{workflow.path.name}: main system gate must depend on source-and-export-policy"
        )

    steps = [s for s in job.get("steps", []) if isinstance(s, dict)]
    commands = [str(step["run"]) for step in steps if "run" in step]
    command_text = "\n".join(commands)

    for marker in (
        "git rev-parse HEAD",
        "git rev-parse 'HEAD^{tree}'",
        "git rev-parse 'HEAD^1'",
        "git rev-parse 'HEAD^2'",
        "CANDIDATE_SHA",
        "CANDIDATE_TREE",
        "CANDIDATE_BASE_PARENT",
        "CANDIDATE_HEAD_PARENT",
        "export CANDIDATE_SHA CANDIDATE_TREE CANDIDATE_BASE_PARENT CANDIDATE_HEAD_PARENT",
        "repomap-ci-gate-request-v1",
        "gate-request.json",
    ):
        if marker not in command_text:
            violations.append(
                f"{workflow.path.name}: main system gate missing candidate/parent binding: {marker!r}"
            )

    if commands.count(contracts.system_marker) != 1 and command_text.count(contracts.system_marker) != 1:
        violations.append(
            f"{workflow.path.name}: system command must appear exactly once"
        )
    for argument in (
        "--system-timeout 3600",
        "--hygiene-profile exhaustive",
        "--declared-complete-gates 1",
        "--operator-attest-exclusive",
        "--operator-attest-pressure-degradation",
        "--sandbox",
        '--gate-request-json "${RUNNER_TEMP}/gate-request.json"',
        '--candidate-sha "${CANDIDATE_SHA}"',
        '--candidate-tree "${CANDIDATE_TREE}"',
        '--candidate-base-parent "${CANDIDATE_BASE_PARENT}"',
        '--candidate-head-parent "${CANDIDATE_HEAD_PARENT}"',
        "--report",
        "--report-dir",
    ):
        if argument not in command_text:
            violations.append(
                f"{workflow.path.name}: system gate command missing argument {argument!r}"
            )
    for retired in (
        "--suite all",
        "--suite unit",
        "--suite int",
        "--suite staging",
        "--suite smoke",
    ):
        if retired in command_text:
            violations.append(
                f"{workflow.path.name}: system gate must not contain {retired!r}"
            )
    return violations
