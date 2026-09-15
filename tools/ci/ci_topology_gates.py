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
    check_trusted_gate_copy_set,
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

    steps = workflow.steps()
    trusted_checkout_index = next(
        (
            index
            for index, step in enumerate(steps)
            if str(step.get("uses", "")).startswith("actions/checkout@")
            and step.get("with", {}).get("ref") == "${{ github.sha }}"
        ),
        None,
    )
    preserve_index = first_step_index(
        steps, f"cp tools/ci/gate_contract.py {contracts.trusted_gate_contract}"
    )
    binding_index = first_step_index(
        steps, f"{contracts.trusted_gate_invocation} resolve"
    )
    candidate_checkout_index = next(
        (
            index
            for index, step in enumerate(steps)
            if str(step.get("uses", "")).startswith("actions/checkout@")
            and str(step.get("with", {}).get("ref", "")).startswith("refs/pull/")
        ),
        None,
    )
    candidate_index = first_step_index(
        steps, f"{contracts.trusted_gate_invocation} verify"
    )
    record_index = first_step_index(
        steps, f"{contracts.trusted_gate_invocation} record"
    )
    commands = "\n".join(workflow.run_commands())
    if commands.count(contracts.staging_marker) != 1:
        violations.append(
            f"{workflow.path.name}: staging command must appear exactly once"
        )
    for retired in ("--suite all", "--suite unit"):
        if retired in commands:
            violations.append(
                f"{workflow.path.name}: staging gate must not contain {retired!r}"
            )
    if "--sandbox" not in commands:
        violations.append(
            f"{workflow.path.name}: staging qualification must use --sandbox"
        )
    duplicate_bootstrap = [
        action
        for action in workflow.action_uses()
        if action.lower().startswith("actions/setup-go@")
    ]
    lowered_commands = commands.lower()
    duplicate_bootstrap.extend(
        marker
        for marker in ("pip install", "go install", "golangci-lint")
        if marker in lowered_commands
    )
    if duplicate_bootstrap:
        violations.append(
            f"{workflow.path.name}: sandbox-backed staging gate must not duplicate "
            f"host toolchain bootstrap; found {duplicate_bootstrap}"
        )
    if (
        '--executor-ref "${GITHUB_REF}"' not in commands
        or '--executor-sha "${GITHUB_SHA}"' not in commands
    ):
        violations.append(
            f"{workflow.path.name}: trusted executor ref/SHA inputs must come from "
            "the workflow-dispatch context"
        )
    trusted_command_counts = {
        command: commands.count(f"{contracts.trusted_gate_invocation} {command}")
        for command in ("resolve", "verify", "record")
    }
    if any(count != 1 for count in trusted_command_counts.values()):
        violations.append(
            f"{workflow.path.name}: trusted gate contract must execute resolve, "
            "verify, and record exactly once"
        )
    if (
        trusted_checkout_index is None
        or preserve_index is None
        or binding_index is None
        or candidate_checkout_index is None
        or candidate_index is None
    ):
        violations.append(
            f"{workflow.path.name}: gate must capture trusted staging semantics, "
            "resolve the request, and verify the merge candidate"
        )
        return violations
    ordered_indices = (
        trusted_checkout_index,
        preserve_index,
        binding_index,
        candidate_checkout_index,
        candidate_index,
    )
    if list(ordered_indices) != sorted(ordered_indices):
        violations.append(
            f"{workflow.path.name}: trusted binding and candidate checkout order is invalid"
        )
    violations.extend(
        check_trusted_gate_copy_set(workflow.path.name, steps, preserve_index, contracts)
    )
    expensive_index = first_expensive_step_index(steps, contracts)
    if expensive_index is None:
        violations.append(f"{workflow.path.name}: staging qualification is missing")
    elif max(binding_index, candidate_index) >= expensive_index:
        violations.append(
            f"{workflow.path.name}: gate binding must fail before expensive work"
        )
    if record_index is None:
        violations.append(
            f"{workflow.path.name}: gate must emit repomap-ci-gate-result-v1"
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
    triggers = workflow.triggers
    if set(triggers) != {"workflow_dispatch"}:
        violations.append(
            f"{workflow.path.name}: main-system qualification must require an explicit "
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
            f"{workflow.path.name}: main-system gate permissions must be exactly "
            f"contents/pull-requests read, got {dict(workflow.permissions)}"
        )
    job = workflow.jobs.get("repomap-main-system-gate")
    if not isinstance(job, dict) or job.get("timeout-minutes") != 90:
        violations.append(
            f"{workflow.path.name}: main-system lane timeout must be 90 minutes"
        )

    steps = workflow.steps()
    commands = "\n".join(workflow.run_commands())
    if commands.count("--system-timeout 3600") != 1:
        violations.append(
            f"{workflow.path.name}: main-system internal deadline must be exactly 3600 seconds"
        )
    trusted_checkout_index = next(
        (
            index
            for index, step in enumerate(steps)
            if str(step.get("uses", "")).startswith("actions/checkout@")
            and step.get("with", {}).get("ref") == "${{ github.sha }}"
        ),
        None,
    )
    preserve_index = first_step_index(
        steps, f"cp tools/ci/gate_contract.py {contracts.trusted_gate_contract}"
    )
    binding_index = first_step_index(
        steps, f"{contracts.trusted_gate_invocation} resolve"
    )
    candidate_checkout_index = next(
        (
            index
            for index, step in enumerate(steps)
            if str(step.get("uses", "")).startswith("actions/checkout@")
            and str(step.get("with", {}).get("ref", "")).startswith("refs/pull/")
        ),
        None,
    )
    candidate_index = first_step_index(
        steps, f"{contracts.trusted_gate_invocation} verify"
    )
    record_index = first_step_index(
        steps, f"{contracts.trusted_gate_invocation} record"
    )
    system_step = next(
        (step for step in steps if contracts.system_marker in str(step.get("run", ""))),
        None,
    )
    system_env = system_step.get("env") if isinstance(system_step, dict) else None
    if system_env != {
        "APPROVAL_ID": "${{ inputs.approval_id }}",
        "PR_NUMBER": "${{ inputs.pr_number }}",
    }:
        violations.append(
            f"{workflow.path.name}: system runner dispatch inputs must be passed "
            "through the exact step environment"
        )
    if commands.count(contracts.system_marker) != 1:
        violations.append(
            f"{workflow.path.name}: system command must appear exactly once"
        )
    for retired in ("--suite all", "--suite unit", "--suite int", "--suite staging", "--suite smoke"):
        if retired in commands:
            violations.append(
                f"{workflow.path.name}: main-system gate must not contain {retired!r}"
            )
    if "--sandbox" not in commands:
        violations.append(
            f"{workflow.path.name}: main-system qualification must use --sandbox"
        )
    if "--gate-kind main-system" not in commands:
        violations.append(
            f"{workflow.path.name}: main-system gate must bind gate_kind main-system"
        )
    duplicate_bootstrap = [
        action
        for action in workflow.action_uses()
        if action.lower().startswith("actions/setup-go@")
    ]
    lowered_commands = commands.lower()
    duplicate_bootstrap.extend(
        marker
        for marker in ("pip install", "go install", "golangci-lint")
        if marker in lowered_commands
    )
    if duplicate_bootstrap:
        violations.append(
            f"{workflow.path.name}: sandbox-backed system gate must not duplicate "
            f"host toolchain bootstrap; found {duplicate_bootstrap}"
        )
    if (
        '--executor-ref "${GITHUB_REF}"' not in commands
        or '--executor-sha "${GITHUB_SHA}"' not in commands
    ):
        violations.append(
            f"{workflow.path.name}: trusted executor ref/SHA inputs must come from "
            "the workflow-dispatch context"
        )
    trusted_command_counts = {
        command: commands.count(f"{contracts.trusted_gate_invocation} {command}")
        for command in ("resolve", "verify", "record")
    }
    if any(count != 1 for count in trusted_command_counts.values()):
        violations.append(
            f"{workflow.path.name}: trusted gate contract must execute resolve, "
            "verify, and record exactly once"
        )
    if (
        trusted_checkout_index is None
        or preserve_index is None
        or binding_index is None
        or candidate_checkout_index is None
        or candidate_index is None
    ):
        violations.append(
            f"{workflow.path.name}: gate must capture trusted main semantics, "
            "resolve the request, and verify the merge candidate"
        )
        return violations
    ordered_indices = (
        trusted_checkout_index,
        preserve_index,
        binding_index,
        candidate_checkout_index,
        candidate_index,
    )
    if list(ordered_indices) != sorted(ordered_indices):
        violations.append(
            f"{workflow.path.name}: trusted binding and candidate checkout order is invalid"
        )
    violations.extend(
        check_trusted_gate_copy_set(workflow.path.name, steps, preserve_index, contracts)
    )
    expensive_index = first_expensive_step_index(steps, contracts)
    if expensive_index is None:
        violations.append(f"{workflow.path.name}: system qualification is missing")
    elif max(binding_index, candidate_index) >= expensive_index:
        violations.append(
            f"{workflow.path.name}: gate binding must fail before expensive work"
        )
    for required_runner_arg in (
        '--gate-request-json "${RUNNER_TEMP}/gate-request.json"',
        '--candidate-sha "${CANDIDATE_SHA}"',
        '--candidate-tree "${CANDIDATE_TREE}"',
        '--candidate-base-parent "${CANDIDATE_BASE_PARENT}"',
        '--candidate-head-parent "${CANDIDATE_HEAD_PARENT}"',
        '--approval-id "${APPROVAL_ID}"',
        '--pr-number "${PR_NUMBER}"',
        '--repository "${GITHUB_REPOSITORY}"',
    ):
        if required_runner_arg not in commands:
            violations.append(
                f"{workflow.path.name}: system runner must receive {required_runner_arg}"
            )
    for required_record_arg in (
        '--system-report-json "${GITHUB_WORKSPACE}/ci-system-report/repomap-system-gate-report.json"',
        '--system-binding-json "${GITHUB_WORKSPACE}/ci-system-report/repomap-system-gate-binding-v1.json"',
    ):
        if required_record_arg not in commands:
            violations.append(
                f"{workflow.path.name}: gate record step must receive {required_record_arg}"
            )

    if record_index is None:
        violations.append(
            f"{workflow.path.name}: gate must emit repomap-ci-gate-result-v1"
        )
    return violations
