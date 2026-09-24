#!/usr/bin/env python3
"""Structural CI topology contracts for the staged promotion pipeline.

These checks parse the repository's own workflow YAML rather than grepping it,
so a reformatted workflow cannot silently drop a contract. They are stdlib-only
and seconds-scale by design.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
import sys
from pathlib import Path

if __package__ in (None, ""):
    tools_root = Path(__file__).resolve().parents[1]
    if str(tools_root) not in sys.path:
        sys.path.insert(0, str(tools_root))

from ci.ci_topology_contracts import (
    ALLOWED_WORKFLOWS,
    DEFAULT_CONTRACTS,
    EXPENSIVE_MARKERS,
    FEEDBACK_TYPES,
    FORBIDDEN_ACTION_PREFIXES,
    GIT_MUTATION_MARKERS,
    MAIN_BRANCH,
    MAIN_POLICY_WORKFLOW,
    MAIN_SYSTEM_GATE_WORKFLOW,
    PR_FAST_WORKFLOW,
    PR_UNIT_WORKFLOW,
    PROTECTION_MARKERS,
    PROTECTION_PATHS,
    READ_ONLY_PERMISSIONS,
    RELEASE_WORKFLOW,
    REQUIRED_GATE_INPUTS,
    REQUIRED_RELEASE_JOBS,
    RETIRED_WORKFLOWS,
    RUNNER_MARKER,
    STAGING_BRANCH,
    STAGING_GATE_WORKFLOW,
    STAGING_MARKER,
    SYSTEM_MARKER,
    TRUSTED_GATE_CONTRACT,
    TRUSTED_GATE_INVOCATION,
    UNIT_COMMAND,
    UNIT_PATHS,
    TopologyContractValues,
    _by_name as _contracts_by_name,
    _check_protection_config as _contracts_check_protection_config,
    _is_hex as _contracts_is_hex,
    _permission_violations as _contracts_permission_violations,
    _step_text as _contracts_step_text,
    _trigger_list as _contracts_trigger_list,
)
from ci.ci_topology_gates import (
    _check_main_system_gate as _gates_check_main_system_gate,
    _check_staging_gate as _gates_check_staging_gate,
)
from ci.ci_topology_pr import (
    _check_codeql as _pr_check_codeql,
    _check_global as _pr_check_global,
    _check_main_policy as _pr_check_main_policy,
    _check_pre_review_static as _pr_check_pre_review_static,
    _check_pr_fast as _pr_check_pr_fast,
    _check_pr_unit as _pr_check_pr_unit,
    _check_sbom_security as _pr_check_sbom_security,
    _check_source_and_export_policy as _pr_check_source_and_export_policy,
    _check_unit_tests as _pr_check_unit_tests,
)
from ci.workflow_model import Workflow, WorkflowParseError, load_workflows


def _contract_values() -> TopologyContractValues:
    """Capture current module globals for compatibility with old patch points."""
    return replace(
        DEFAULT_CONTRACTS,
        pr_fast_workflow=PR_FAST_WORKFLOW,
        pr_unit_workflow=PR_UNIT_WORKFLOW,
        staging_gate_workflow=STAGING_GATE_WORKFLOW,
        main_system_gate_workflow=MAIN_SYSTEM_GATE_WORKFLOW,
        main_policy_workflow=MAIN_POLICY_WORKFLOW,
        release_workflow=RELEASE_WORKFLOW,
        retired_workflows=RETIRED_WORKFLOWS,
        allowed_workflows=ALLOWED_WORKFLOWS,
        required_release_jobs=REQUIRED_RELEASE_JOBS,
        staging_branch=STAGING_BRANCH,
        main_branch=MAIN_BRANCH,
        feedback_types=FEEDBACK_TYPES,
        runner_marker=RUNNER_MARKER,
        staging_marker=STAGING_MARKER,
        system_marker=SYSTEM_MARKER,
        unit_command=UNIT_COMMAND,
        unit_paths=UNIT_PATHS,
        required_gate_inputs=REQUIRED_GATE_INPUTS,
        read_only_permissions=READ_ONLY_PERMISSIONS,
        git_mutation_markers=GIT_MUTATION_MARKERS,
        forbidden_action_prefixes=FORBIDDEN_ACTION_PREFIXES,
        protection_markers=PROTECTION_MARKERS,
        expensive_markers=EXPENSIVE_MARKERS,
        trusted_gate_contract=TRUSTED_GATE_CONTRACT,
        trusted_gate_invocation=TRUSTED_GATE_INVOCATION,
        protection_paths=PROTECTION_PATHS,
    )


def _by_name(workflows: Iterable[Workflow]) -> dict[str, Workflow]:
    return _contracts_by_name(workflows)


def _trigger_list(trigger: object, key: str) -> list[str]:
    return _contracts_trigger_list(trigger, key)


def _permission_violations(workflow: Workflow) -> list[str]:
    return _contracts_permission_violations(workflow, _contract_values())


def _step_text(step: Mapping[str, object]) -> str:
    return _contracts_step_text(step)


def _first_step_index(steps: Sequence[Mapping[str, object]], marker: str) -> int | None:
    for index, step in enumerate(steps):
        if marker in _step_text(step):
            return index
    return None


def _first_expensive_step_index(
    steps: Sequence[Mapping[str, object]],
) -> int | None:
    contracts = _contract_values()
    markers = (
        contracts.staging_marker,
        contracts.system_marker,
        "pip install",
        "docker pull",
        "setup-go",
        "setup-python",
    )
    indexes = [
        index
        for index, step in enumerate(steps)
        if any(marker in _step_text(step) for marker in markers)
    ]
    return min(indexes) if indexes else None


def _first_expensive_for_contracts(
    steps: Sequence[Mapping[str, object]], _contracts: TopologyContractValues
) -> int | None:
    return _first_expensive_step_index(steps)


def _is_hex(value: str) -> bool:
    return _contracts_is_hex(value)


def _check_pr_fast(workflow: Workflow) -> list[str]:
    return _pr_check_pr_fast(
        workflow, _contract_values(), trigger_list=_trigger_list
    )


def _check_pr_unit(workflow: Workflow) -> list[str]:
    return _pr_check_pr_unit(
        workflow, _contract_values(), trigger_list=_trigger_list
    )


def _check_staging_gate(workflow: Workflow) -> list[str]:
    return _gates_check_staging_gate(
        workflow,
        _contract_values(),
        trigger_list=_trigger_list,
        first_step_index=_first_step_index,
        first_expensive_step_index=_first_expensive_for_contracts,
    )


def _check_main_system_gate(workflow: Workflow) -> list[str]:
    return _gates_check_main_system_gate(
        workflow,
        _contract_values(),
        trigger_list=_trigger_list,
        first_step_index=_first_step_index,
        first_expensive_step_index=_first_expensive_for_contracts,
    )


def _check_main_policy(workflow: Workflow) -> list[str]:
    return _pr_check_main_policy(
        workflow, _contract_values(), trigger_list=_trigger_list
    )


def _check_global(workflows: Sequence[Workflow]) -> list[str]:
    return _pr_check_global(
        workflows,
        _contract_values(),
        permission_violations=_permission_violations,
        is_hex=_is_hex,
    )


def _check_protection_config(repo_root: Path) -> list[str]:
    return _contracts_check_protection_config(repo_root, _contract_values())


def check_topology(repo_root: Path) -> tuple[str, ...]:
    """Return every CI topology violation for the repository at ``repo_root``."""
    workflow_dir = repo_root / ".github/workflows"
    contracts = _contract_values()
    violations: list[str] = []

    for retired in contracts.retired_workflows:
        if (workflow_dir / retired).exists():
            violations.append(f"{retired}: retired workflow must not exist")

    workflows = load_workflows(workflow_dir)
    by_name = _by_name(workflows)

    for name in by_name:
        if name not in contracts.allowed_workflows:
            violations.append(f"{name}: unexpected workflow file; only {contracts.release_workflow} is allowed")

    if contracts.release_workflow not in by_name:
        violations.append(f"{contracts.release_workflow} is missing")
        return tuple(violations)

    release_wf = by_name[contracts.release_workflow]
    violations.extend(_check_global(workflows))
    violations.extend(_pr_check_source_and_export_policy(release_wf, contracts))
    violations.extend(_pr_check_pre_review_static(release_wf, contracts))
    violations.extend(_pr_check_unit_tests(release_wf, contracts))
    violations.extend(_check_staging_gate(release_wf))
    violations.extend(_check_main_system_gate(release_wf))
    violations.extend(_pr_check_codeql(release_wf, contracts))
    violations.extend(_pr_check_sbom_security(release_wf, contracts))
    violations.extend(_check_protection_config(repo_root))
    return tuple(violations)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="repository root to inspect",
    )
    arguments = parser.parse_args(argv)
    try:
        violations = check_topology(arguments.repo_root)
    except WorkflowParseError as error:
        print(f"CI topology check could not parse a workflow: {error}", file=sys.stderr)
        return 1
    for violation in violations:
        print(f"CI topology violation: {violation}", file=sys.stderr)
    if violations:
        return 1
    print("CI topology contracts hold")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
