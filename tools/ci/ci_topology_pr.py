"""Pull-request and repository-wide CI topology contracts."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from ci.ci_topology_contracts import (
    DEFAULT_CONTRACTS,
    TopologyContractValues,
    _is_hex,
    _permission_violations,
    _trigger_list,
)

if TYPE_CHECKING:
    from ci.workflow_model import Workflow


def _check_pr_fast(
    workflow: Workflow,
    contracts: TopologyContractValues = DEFAULT_CONTRACTS,
    *,
    trigger_list: Callable[[object, str], list[str]] = _trigger_list,
) -> list[str]:
    violations: list[str] = []
    triggers = workflow.triggers
    unexpected = set(triggers).difference({"pull_request", "workflow_dispatch"})
    if unexpected:
        violations.append(
            f"{workflow.path.name}: unexpected triggers {sorted(unexpected)}"
        )
    pull_request = triggers.get("pull_request")
    if not isinstance(pull_request, dict):
        violations.append(f"{workflow.path.name}: must trigger on pull_request")
        return violations
    if trigger_list(pull_request, "branches") != [contracts.staging_branch]:
        violations.append(
            f"{workflow.path.name}: PR Fast must target {contracts.staging_branch!r} only"
        )
    if sorted(trigger_list(pull_request, "types")) != sorted(contracts.feedback_types):
        violations.append(
            f"{workflow.path.name}: PR Fast types must be {sorted(contracts.feedback_types)}"
        )

    if workflow.name != "repomap-static-analysis" or set(workflow.jobs) != {
        "repomap-static-analysis"
    }:
        violations.append(
            f"{workflow.path.name}: static workflow/job identity must remain stable"
        )
    if dict(workflow.permissions) != {"contents": "read"}:
        violations.append(
            f"{workflow.path.name}: static permissions must be exactly contents read"
        )
    job = workflow.jobs.get("repomap-static-analysis")
    if not isinstance(job, dict) or job.get("timeout-minutes") != 25:
        violations.append(
            f"{workflow.path.name}: static lane timeout must remain 25 minutes"
        )
    commands = "\n".join(workflow.run_commands())
    for required in (
        "tools/ci/bootstrap_pre_review.py",
        "tools/ci/run_pre_review.py",
        '"${RUNNER_TEMP}/repomap-pre-review-tools/python/bin/python"',
        '--tool-root "${RUNNER_TEMP}/repomap-pre-review-tools"',
    ):
        if required not in commands:
            violations.append(f"{workflow.path.name}: missing pre-review owner {required!r}")
    if 'pip install --editable ".[static-analysis]"' in commands:
        violations.append(
            f"{workflow.path.name}: static tools must not be installed into host Python"
        )
    for expensive in ("run_tests.py", "docker", "postgres", "pytest"):
        if expensive in commands.lower():
            violations.append(
                f"{workflow.path.name}: pre-review must remain resource-pure, found {expensive!r}"
            )
    driver = workflow.path.parents[2] / "tools/ci/run_pre_review.py"
    catalog = driver.with_name("pre_review_checks.py")
    driver_text = driver.read_text(encoding="utf-8") if driver.is_file() else ""
    catalog_text = catalog.read_text(encoding="utf-8") if catalog.is_file() else ""
    if "from ci.pre_review_checks import" not in driver_text:
        violations.append(f"{workflow.path.name}: aggregate driver is missing check catalog import")
    for required in (
        "actionlint",
        "zizmor",
        "pip-audit",
        "govulncheck",
        "semgrep",
        "betterleaks",
        "malskanner",
        "prompt-defense-audit",
        "liquibase",
        "hadolint",
        "scanner-suppressions",
        "generated-code-drift",
    ):
        if f'"{required}"' not in catalog_text:
            violations.append(
                f"{workflow.path.name}: aggregate driver is missing {required!r}"
            )
    return violations


def _check_pr_unit(
    workflow: Workflow,
    contracts: TopologyContractValues = DEFAULT_CONTRACTS,
    *,
    trigger_list: Callable[[object, str], list[str]] = _trigger_list,
) -> list[str]:
    violations: list[str] = []
    triggers = workflow.triggers
    if set(triggers) != {"pull_request", "workflow_dispatch"}:
        violations.append(
            f"{workflow.path.name}: unit lane triggers must be pull_request and "
            "workflow_dispatch only"
        )
    pull_request = triggers.get("pull_request")
    if not isinstance(pull_request, dict):
        violations.append(f"{workflow.path.name}: must trigger on pull_request")
        return violations
    if trigger_list(pull_request, "branches") != [contracts.staging_branch]:
        violations.append(
            f"{workflow.path.name}: unit lane must target {contracts.staging_branch!r} only"
        )
    if sorted(trigger_list(pull_request, "types")) != sorted(contracts.feedback_types):
        violations.append(
            f"{workflow.path.name}: unit lane types must be {sorted(contracts.feedback_types)}"
        )
    if trigger_list(pull_request, "paths") != contracts.unit_paths:
        violations.append(
            f"{workflow.path.name}: unit lane paths must be {contracts.unit_paths!r}"
        )
    if dict(workflow.permissions) != {"contents": "read"}:
        violations.append(
            f"{workflow.path.name}: unit lane permissions must be exactly contents read"
        )
    if workflow.name != "repomap-unit-tests" or set(workflow.jobs) != {
        "repomap-unit-tests"
    }:
        violations.append(
            f"{workflow.path.name}: unit workflow and job identity must remain "
            "repomap-unit-tests"
        )

    job = workflow.jobs.get("repomap-unit-tests")
    if not isinstance(job, dict) or job.get("name") != "repomap-unit-tests":
        violations.append(f"{workflow.path.name}: unit check identity is invalid")
    if not isinstance(job, dict) or job.get("runs-on") != "ubuntu-latest":
        violations.append(f"{workflow.path.name}: unit lane must use ubuntu-latest")
    if not isinstance(job, dict) or job.get("timeout-minutes") != 60:
        violations.append(f"{workflow.path.name}: unit lane timeout must be 60 minutes")

    concurrency = workflow.document.get("concurrency")
    if concurrency != {
        "group": "repomap-unit-tests-${{ github.ref }}",
        "cancel-in-progress": True,
    }:
        violations.append(
            f"{workflow.path.name}: unit lane concurrency must cancel superseded revisions"
        )

    steps = workflow.steps()
    python_setup = next(
        (
            step
            for step in steps
            if str(step.get("uses", "")).startswith("actions/setup-python@")
        ),
        None,
    )
    if python_setup is None or python_setup.get("with") != {"python-version": "3.13"}:
        violations.append(f"{workflow.path.name}: unit lane must set up Python 3.13")
    go_setup = next(
        (
            step
            for step in steps
            if str(step.get("uses", "")).startswith("actions/setup-go@")
        ),
        None,
    )
    if go_setup is None or go_setup.get("with") != {
        "go-version-file": "src/main/go/go.mod",
        "cache": False,
    }:
        violations.append(
            f"{workflow.path.name}: canonical unit runner requires pinned Go from "
            "src/main/go/go.mod"
        )

    commands = workflow.run_commands()
    required_commands = (
        "python3 tools/ci/ci_topology.py",
        'python -m pip install --editable ".[test,scale-tools,static-analysis]"',
        "df -B1 /",
        contracts.unit_command,
    )
    for required in required_commands:
        if commands.count(required) != 1:
            violations.append(
                f"{workflow.path.name}: unit lane must contain {required!r} exactly once"
            )
    unit_step = next(
        (step for step in steps if step.get("run") == contracts.unit_command),
        None,
    )
    if unit_step is not None:
        env = unit_step.get("env")
        if (
            not isinstance(env, dict)
            or env.get("REPOMAP_TEST_HYGIENE_MIN_FREE_DISK_BYTES") != "10737418240"
        ):
            violations.append(
                f"{workflow.path.name}: unit suite must set REPOMAP_TEST_HYGIENE_MIN_FREE_DISK_BYTES "
                "to the 10 GiB architectural floor"
            )
    lowered = "\n".join(commands).lower()
    if "tools/ci/bootstrap_tool.py" not in lowered or "--tool golangci-lint" not in lowered:
        violations.append(
            f"{workflow.path.name}: unit lane must install the pinned golangci-lint asset"
        )
    for forbidden in (
        "--suite int",
        "--suite all",
        "--suite smoke",
        "--suite staging",
        "--sandbox",
        "--pg-container-port",
        "docker pull",
        "docker run",
        "docker build",
        "postgres",
        "go test",
        "go build",
        "go install",
    ):
        if forbidden in lowered:
            violations.append(
                f"{workflow.path.name}: unit lane must not contain {forbidden!r}"
            )
    if any(
        command.strip().startswith("pytest") or "python -m pytest" in command
        for command in commands
    ):
        violations.append(
            f"{workflow.path.name}: unit population must use the canonical runner, "
            "not pytest directly"
        )
    if "--report" in lowered or "--no-coverage" in lowered:
        violations.append(f"{workflow.path.name}: unit lane must retain its coverage gate")
    return violations


def _check_main_policy(
    workflow: Workflow,
    contracts: TopologyContractValues = DEFAULT_CONTRACTS,
    *,
    trigger_list: Callable[[object, str], list[str]] = _trigger_list,
) -> list[str]:
    violations: list[str] = []
    triggers = workflow.triggers
    unexpected = set(triggers).difference({"pull_request", "workflow_dispatch"})
    if unexpected:
        violations.append(
            f"{workflow.path.name}: unexpected triggers {sorted(unexpected)}"
        )
    pull_request = triggers.get("pull_request")
    if not isinstance(pull_request, dict):
        violations.append(f"{workflow.path.name}: must trigger on pull_request")
    elif trigger_list(pull_request, "branches") != [contracts.main_branch]:
        violations.append(
            f"{workflow.path.name}: policy must apply only to PRs targeting "
            f"{contracts.main_branch!r}"
        )
    commands = "\n".join(workflow.run_commands())
    if "tools/ci/promotion_policy.py" not in commands:
        violations.append(
            f"{workflow.path.name}: must run the project-owned promotion policy"
        )
    for expensive in contracts.expensive_markers:
        if expensive in commands.lower():
            violations.append(
                f"{workflow.path.name}: invalid promotion sources must cost nothing, "
                f"found {expensive!r}"
            )
    return violations


def _check_global(
    workflows: Sequence[Workflow],
    contracts: TopologyContractValues = DEFAULT_CONTRACTS,
    *,
    permission_violations: Callable[[Workflow], list[str]] = _permission_violations,
    is_hex: Callable[[str], bool] = _is_hex,
) -> list[str]:
    violations: list[str] = []
    runner_uses = 0
    staging_uses = 0
    system_uses = 0
    retired_all_uses = 0
    unit_uses = 0
    for workflow in workflows:
        violations.extend(permission_violations(workflow))
        if "push" in workflow.triggers:
            violations.append(
                f"{workflow.path.name}: pull_request:synchronize is the "
                "push-to-open-PR feedback signal; no duplicate branch push lane"
            )
        commands = "\n".join(workflow.run_commands())
        if workflow.path.name != "repomap-release-qualification.yml":
            runner_uses += commands.count(contracts.runner_marker)
            staging_uses += commands.count(contracts.staging_marker)
            system_uses += commands.count(contracts.system_marker)
            unit_uses += commands.count(contracts.unit_command)
        retired_all_uses += commands.count("--suite all")
        lowered = commands.lower()
        for marker in contracts.git_mutation_markers:
            if marker.lower() in lowered:
                violations.append(
                    f"{workflow.path.name}: Actions are evidence executors, not git "
                    f"brokers; found {marker!r}"
                )
        for marker in contracts.protection_markers:
            if marker.lower() in lowered:
                violations.append(
                    f"{workflow.path.name}: server-side protection configuration is "
                    f"out of scope; found {marker!r}"
                )
        for action in workflow.action_uses():
            if any(action.startswith(prefix) for prefix in contracts.forbidden_action_prefixes):
                violations.append(
                    f"{workflow.path.name}: mutating action {action!r} is forbidden"
                )
            name, separator, pinned = action.partition("@")
            if not separator or len(pinned) != 40 or not is_hex(pinned):
                violations.append(
                    f"{workflow.path.name}: action {name!r} must use a 40-hex SHA pin"
                )
        for step in workflow.steps():
            uses = str(step.get("uses", ""))
            if not uses.startswith("actions/checkout@"):
                continue
            with_block = step.get("with")
            persist = (
                with_block.get("persist-credentials")
                if isinstance(with_block, dict)
                else None
            )
            if persist is not False:
                violations.append(
                    f"{workflow.path.name}: checkout must set persist-credentials: false"
                )
            if workflow.path.name == contracts.pr_fast_workflow and (
                not isinstance(with_block, dict) or with_block.get("fetch-depth") != 0
            ):
                violations.append(
                    f"{workflow.path.name}: retained ratchets require complete Git history"
                )
        if "secrets." in workflow.path.read_text(encoding="utf-8"):
            violations.append(f"{workflow.path.name}: workflows must consume no secrets")
    if runner_uses != 3:
        violations.append(
            "the canonical test runner must appear exactly three times across all workflows, "
            f"found {runner_uses}"
        )
    if staging_uses != 1:
        violations.append(
            "the staging project-owned command must appear exactly once, "
            f"found {staging_uses}"
        )
    if system_uses != 1:
        violations.append(
            "the system project-owned command must appear exactly once, "
            f"found {system_uses}"
        )
    if retired_all_uses:
        violations.append(
            "the retired --suite all command must not appear, "
            f"found {retired_all_uses}"
        )
    if unit_uses != 1:
        violations.append(
            "the canonical PR unit command must appear exactly once, "
            f"found {unit_uses}"
        )
    return violations
