"""Shared values and small structural helpers for CI topology checks."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ci.workflow_model import Workflow


PR_FAST_WORKFLOW = "repomap-static-analysis.yml"
PR_UNIT_WORKFLOW = "repomap-unit-tests.yml"
STAGING_GATE_WORKFLOW = "repomap-staging-gate.yml"
MAIN_SYSTEM_GATE_WORKFLOW = "repomap-main-system-gate.yml"
MAIN_POLICY_WORKFLOW = "repomap-main-source-policy.yml"

STAGING_BRANCH = "staging"
MAIN_BRANCH = "main"
FEEDBACK_TYPES = ["opened", "reopened", "ready_for_review", "synchronize"]
RUNNER_MARKER = "python3 tools/run_tests.py"
STAGING_MARKER = "--suite staging"
SYSTEM_MARKER = "--suite system"
UNIT_COMMAND = "python3 tools/run_tests.py --suite unit"
UNIT_PATHS = [
    "src/main/python/**",
    "src/main/go/**",
    "src/test/**",
    "tools/**",
    "pyproject.toml",
    ".github/workflows/**",
]
REQUIRED_GATE_INPUTS = frozenset(
    {"pr_number", "approved_base_sha", "approved_head_sha", "approval_id"}
)
READ_ONLY_PERMISSIONS = frozenset({"read", "none"})

GIT_MUTATION_MARKERS = (
    "git push",
    "git merge",
    "git commit",
    "git tag",
    "git rebase",
    "git reset",
    "git update-ref",
    "git branch",
    "gh pr merge",
    "gh pr close",
    "gh pr edit",
    "gh pr review",
    "gh pr ready",
    "gh api --method",
    "gh api -X",
    "auto-merge",
    "automerge",
    "enablePullRequestAutoMerge",
)
FORBIDDEN_ACTION_PREFIXES = (
    "peter-evans/",
    "pascalgn/automerge-action",
    "actions/github-script",
    "ad-m/github-push-action",
)
PROTECTION_MARKERS = (
    "/protection",
    "/rulesets",
    "branch_protection",
    "branch-protection",
)
EXPENSIVE_MARKERS = ("run_tests.py", "docker", "postgres", "pytest", "pip install")
TRUSTED_GATE_CONTRACT = '"${RUNNER_TEMP}/gate_contract.py"'
TRUSTED_GATE_INVOCATION = f"python3 -S -E {TRUSTED_GATE_CONTRACT}"
PROTECTION_PATHS = (
    ".github/rulesets",
    ".github/CODEOWNERS",
    "CODEOWNERS",
    "docs/CODEOWNERS",
    ".github/branch-protection.yml",
)


TRUSTED_GATE_COPY_SET: tuple[tuple[str, str], ...] = (
    ("tools/ci/gate_contract.py", '"${RUNNER_TEMP}/gate_contract.py"'),
    (
        "tools/ci/gate_contract_bindings.py",
        '"${RUNNER_TEMP}/ci/gate_contract_bindings.py"',
    ),
    (
        "tools/ci/gate_contract_results.py",
        '"${RUNNER_TEMP}/ci/gate_contract_results.py"',
    ),
    (
        "tools/ci/gate_contract_runtime.py",
        '"${RUNNER_TEMP}/ci/gate_contract_runtime.py"',
    ),
)


@dataclass(frozen=True, slots=True)
class TopologyContractValues:
    """Values used by a topology check, captured for compatibility wrappers."""

    pr_fast_workflow: str
    pr_unit_workflow: str
    staging_gate_workflow: str
    main_system_gate_workflow: str
    main_policy_workflow: str
    staging_branch: str
    main_branch: str
    feedback_types: list[str]
    runner_marker: str
    staging_marker: str
    system_marker: str
    unit_command: str
    unit_paths: list[str]
    required_gate_inputs: frozenset[str]
    read_only_permissions: frozenset[str]
    git_mutation_markers: tuple[str, ...]
    forbidden_action_prefixes: tuple[str, ...]
    protection_markers: tuple[str, ...]
    expensive_markers: tuple[str, ...]
    trusted_gate_contract: str
    trusted_gate_invocation: str
    protection_paths: tuple[str, ...]
    trusted_gate_copy_set: tuple[tuple[str, str], ...] = TRUSTED_GATE_COPY_SET


DEFAULT_CONTRACTS = TopologyContractValues(
    pr_fast_workflow=PR_FAST_WORKFLOW,
    pr_unit_workflow=PR_UNIT_WORKFLOW,
    staging_gate_workflow=STAGING_GATE_WORKFLOW,
    main_system_gate_workflow=MAIN_SYSTEM_GATE_WORKFLOW,
    main_policy_workflow=MAIN_POLICY_WORKFLOW,
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
    trusted_gate_copy_set=TRUSTED_GATE_COPY_SET,
)


def _by_name(workflows: Iterable[Workflow]) -> dict[str, Workflow]:
    return {workflow.path.name: workflow for workflow in workflows}


def _trigger_list(trigger: object, key: str) -> list[str]:
    if not isinstance(trigger, Mapping):
        return []
    value = trigger.get(key)
    if value is None:
        return []
    return [str(item) for item in value] if isinstance(value, list) else [str(value)]


def _permission_violations(
    workflow: Workflow, contracts: TopologyContractValues = DEFAULT_CONTRACTS
) -> list[str]:
    violations: list[str] = []
    for scope, level in workflow.permissions.items():
        if str(level) not in contracts.read_only_permissions:
            violations.append(
                f"{workflow.path.name}: permission {scope}={level!r} is not read-only"
            )
    return violations


def _step_text(step: Mapping[str, object]) -> str:
    run = step.get("run")
    uses = step.get("uses")
    return "\n".join(str(value) for value in (run, uses) if value is not None)


def _first_step_index(steps: Sequence[Mapping[str, object]], marker: str) -> int | None:
    for index, step in enumerate(steps):
        if marker in _step_text(step):
            return index
    return None


def _first_expensive_step_index(
    steps: Sequence[Mapping[str, object]], contracts: TopologyContractValues
) -> int | None:
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


def _is_hex(value: str) -> bool:
    return all(character in "0123456789abcdef" for character in value)


def _check_protection_config(
    repo_root: Path, contracts: TopologyContractValues = DEFAULT_CONTRACTS
) -> list[str]:
    return [
        f"{relative}: GitHub protection/ruleset configuration is owned by the future "
        "JACA broker, not this phase"
        for relative in contracts.protection_paths
        if (repo_root / relative).exists()
    ]


def check_trusted_gate_copy_set(
    workflow_name: str,
    steps: Sequence[Mapping[str, object]],
    preserve_index: int | None,
    contracts: TopologyContractValues = DEFAULT_CONTRACTS,
) -> list[str]:
    violations: list[str] = []
    if preserve_index is None:
        return violations
    preserve_step = steps[preserve_index]
    text = _step_text(preserve_step)
    expected = ['mkdir -p "${RUNNER_TEMP}/ci"'] + [
        f"cp {source} {destination}"
        for source, destination in contracts.trusted_gate_copy_set
    ]
    if [line.strip() for line in text.splitlines() if line.strip()] != expected:
        violations.append(f"{workflow_name}: trusted copy step is not the exact declared copy set")
    if 'mkdir -p "${RUNNER_TEMP}/ci"' not in text:
        violations.append(
            f"{workflow_name}: trusted copy step must create ci directory"
        )
    last_pos = -1
    for src, dst in contracts.trusted_gate_copy_set:
        cmd = f"cp {src} {dst}"
        pos = text.find(cmd)
        if pos == -1:
            violations.append(
                f"{workflow_name}: trusted copy step missing copy command: {cmd}"
            )
        elif pos < last_pos:
            violations.append(
                f"{workflow_name}: trusted copy step order is invalid for {cmd}"
            )
        else:
            last_pos = pos
    return violations
