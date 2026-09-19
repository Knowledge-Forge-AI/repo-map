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


def _check_source_and_export_policy(
    workflow: Workflow,
    contracts: TopologyContractValues = DEFAULT_CONTRACTS,
) -> list[str]:
    violations: list[str] = []
    job = workflow.jobs.get("source-and-export-policy")
    if not isinstance(job, dict):
        violations.append(f"{workflow.path.name}: source-and-export-policy job is missing")
        return violations
    steps = [step for step in job.get("steps", []) if isinstance(step, dict)]
    commands = [str(step["run"]) for step in steps if "run" in step]
    command_text = "\n".join(commands)
    if "tools/ci/promotion_policy.py" not in command_text:
        violations.append(f"{workflow.path.name}: must run the project-owned promotion policy")
    if "tools/ci/public_export_policy.py" not in command_text:
        violations.append(f"{workflow.path.name}: must run the project-owned public export policy")
    for expensive in contracts.expensive_markers:
        if expensive in command_text.lower():
            violations.append(
                f"{workflow.path.name}: invalid promotion sources must cost nothing, found {expensive!r}"
            )
    return violations


def _check_pre_review_static(
    workflow: Workflow,
    contracts: TopologyContractValues = DEFAULT_CONTRACTS,
) -> list[str]:
    violations: list[str] = []
    job = workflow.jobs.get("pre-review-static")
    if not isinstance(job, dict):
        violations.append(f"{workflow.path.name}: pre-review-static job is missing")
        return violations
    needs = job.get("needs")
    if needs != ["source-and-export-policy"] and needs != "source-and-export-policy":
        violations.append(f"{workflow.path.name}: pre-review-static must depend on source-and-export-policy")
    steps = [step for step in job.get("steps", []) if isinstance(step, dict)]
    checkout = next((s for s in steps if str(s.get("uses", "")).startswith("actions/checkout@")), None)
    if checkout is None:
        violations.append(f"{workflow.path.name}: pre-review-static must check out repository")
    else:
        with_block = checkout.get("with", {})
        if not isinstance(with_block, dict) or with_block.get("fetch-depth") != 0:
            violations.append(f"{workflow.path.name}: retained ratchets require complete Git history")
    commands = [str(step["run"]) for step in steps if "run" in step]
    command_text = "\n".join(commands)
    for required in (
        "tools/ci/bootstrap_pre_review.py",
        "tools/ci/run_pre_review.py",
        '"${RUNNER_TEMP}/repomap-pre-review-tools/python/bin/python"',
        '--tool-root "${RUNNER_TEMP}/repomap-pre-review-tools"',
    ):
        if required not in command_text:
            violations.append(f"{workflow.path.name}: missing pre-review owner {required!r}")
    if 'pip install --editable ".[static-analysis]"' in command_text:
        violations.append(f"{workflow.path.name}: static tools must not be installed into host Python")
    for expensive in ("run_tests.py", "docker", "postgres", "pytest"):
        if expensive in command_text.lower():
            violations.append(
                f"{workflow.path.name}: pre-review must remain resource-pure, found {expensive!r}"
            )
    driver = workflow.path.parents[2] / "tools/ci/run_pre_review.py"
    catalog = driver.with_name("pre_review_checks.py")
    driver_text = driver.read_text(encoding="utf-8") if driver.is_file() else ""
    catalog_text = catalog.read_text(encoding="utf-8") if catalog.is_file() else ""
    if "from ci.pre_review_checks import" not in driver_text:
        violations.append(f"{workflow.path.name}: aggregate driver is missing check catalog import")
    required_checks = (
        "actionlint", "zizmor", "pip-audit", "govulncheck", "semgrep", "betterleaks",
        "malskanner", "prompt-defense-audit", "liquibase", "hadolint", "scanner-suppressions", "generated-code-drift",
    )
    for required in required_checks:
        if f'"{required}"' not in catalog_text:
            violations.append(f"{workflow.path.name}: aggregate driver is missing {required!r}")
    return violations


def _check_unit_tests(
    workflow: Workflow,
    contracts: TopologyContractValues = DEFAULT_CONTRACTS,
) -> list[str]:
    violations: list[str] = []
    job = workflow.jobs.get("unit-tests")
    if not isinstance(job, dict):
        violations.append(f"{workflow.path.name}: unit-tests job is missing")
        return violations
    if job.get("runs-on") != "ubuntu-latest":
        violations.append(f"{workflow.path.name}: unit lane must use ubuntu-latest")
    if job.get("timeout-minutes") != 60:
        violations.append(f"{workflow.path.name}: unit lane timeout must be 60 minutes")
    needs = job.get("needs")
    if needs != ["source-and-export-policy"] and needs != "source-and-export-policy":
        violations.append(f"{workflow.path.name}: unit lane must depend on source-and-export-policy")

    steps = [step for step in job.get("steps", []) if isinstance(step, dict)]
    python_setup = next(
        (step for step in steps if str(step.get("uses", "")).startswith("actions/setup-python@")),
        None,
    )
    if python_setup is None or python_setup.get("with") != {"python-version": "3.13"}:
        violations.append(f"{workflow.path.name}: unit lane must set up Python 3.13")
    go_setup = next(
        (step for step in steps if str(step.get("uses", "")).startswith("actions/setup-go@")),
        None,
    )
    if go_setup is None or go_setup.get("with") != {
        "go-version-file": "src/main/go/go.mod",
        "cache": False,
    }:
        violations.append(
            f"{workflow.path.name}: canonical unit runner requires pinned Go from src/main/go/go.mod"
        )

    commands = [str(step["run"]) for step in steps if "run" in step]
    required_commands = (
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
            f"{workflow.path.name}: unit population must use the canonical runner, not pytest directly"
        )
    if "--report" in lowered:
        violations.append(f"{workflow.path.name}: unit lane must not specify --report")
    if (
        "--no-coverage" in lowered
        or "--statement-threshold" in lowered
        or "--branch-threshold" in lowered
        or "--line-threshold" in lowered
        or "--unit-statement-threshold" in lowered
        or "--unit-branch-threshold" in lowered
        or "--coverage-threshold" in lowered
    ):
        violations.append(
            f"{workflow.path.name}: unit lane must retain its coverage gate with hard runner defaults (85/85)"
        )
    return violations


def _check_codeql(
    workflow: Workflow,
    contracts: TopologyContractValues = DEFAULT_CONTRACTS,
) -> list[str]:
    violations: list[str] = []
    job = workflow.jobs.get("codeql")
    if not isinstance(job, dict):
        violations.append(f"{workflow.path.name}: codeql job is missing")
        return violations
    needs = job.get("needs")
    if needs != ["source-and-export-policy"] and needs != "source-and-export-policy":
        violations.append(f"{workflow.path.name}: codeql must depend on source-and-export-policy")
    strategy = job.get("strategy", {})
    matrix = strategy.get("matrix", {}) if isinstance(strategy, dict) else {}
    languages = matrix.get("language", []) if isinstance(matrix, dict) else []
    if "python" not in languages or "go" not in languages:
        violations.append(f"{workflow.path.name}: CodeQL matrix must include python and go")
    steps = [step for step in job.get("steps", []) if isinstance(step, dict)]
    uses_list = [str(step.get("uses", "")) for step in steps]
    if not any("github/codeql-action/init@" in u for u in uses_list):
        violations.append(f"{workflow.path.name}: CodeQL init action is missing")
    if not any("github/codeql-action/analyze@" in u for u in uses_list):
        violations.append(f"{workflow.path.name}: CodeQL analyze action is missing")
    return violations


def _check_sbom_security(
    workflow: Workflow,
    contracts: TopologyContractValues = DEFAULT_CONTRACTS,
) -> list[str]:
    violations: list[str] = []
    job = workflow.jobs.get("sbom-security")
    if not isinstance(job, dict):
        violations.append(f"{workflow.path.name}: sbom-security job is missing")
        return violations
    needs = job.get("needs")
    if needs != ["source-and-export-policy"] and needs != "source-and-export-policy":
        violations.append(f"{workflow.path.name}: sbom-security must depend on source-and-export-policy")
    steps = [step for step in job.get("steps", []) if isinstance(step, dict)]
    uses_list = [str(step.get("uses", "")) for step in steps]
    if not any("anchore/sbom-action@" in u for u in uses_list):
        violations.append(f"{workflow.path.name}: Syft SBOM generation action is missing")
    grype_step = next((s for s in steps if "anchore/scan-action@" in str(s.get("uses", ""))), None)
    if grype_step is None:
        violations.append(f"{workflow.path.name}: Grype scan action is missing")
    else:
        with_block = grype_step.get("with", {})
        if not isinstance(with_block, dict) or with_block.get("fail-build") is not True:
            violations.append(f"{workflow.path.name}: Grype scan must have fail-build: true")
        if not isinstance(with_block, dict) or with_block.get("severity-cutoff") != "high":
            violations.append(f"{workflow.path.name}: Grype scan must have severity-cutoff: high")
    return violations


def _check_pr_fast(
    workflow: Workflow,
    contracts: TopologyContractValues = DEFAULT_CONTRACTS,
    *,
    trigger_list: Callable[[object, str], list[str]] = _trigger_list,
) -> list[str]:
    return _check_pre_review_static(workflow, contracts)


def _check_pr_unit(
    workflow: Workflow,
    contracts: TopologyContractValues = DEFAULT_CONTRACTS,
    *,
    trigger_list: Callable[[object, str], list[str]] = _trigger_list,
) -> list[str]:
    return _check_unit_tests(workflow, contracts)


def _check_main_policy(
    workflow: Workflow,
    contracts: TopologyContractValues = DEFAULT_CONTRACTS,
    *,
    trigger_list: Callable[[object, str], list[str]] = _trigger_list,
) -> list[str]:
    return _check_source_and_export_policy(workflow, contracts)


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
        if workflow.path.name == contracts.release_workflow:
            if "workflow_dispatch" in workflow.triggers:
                violations.append(
                    f"{workflow.path.name}: release qualification must not declare workflow_dispatch"
                )
            unexpected = set(workflow.triggers).difference({"pull_request"})
            if unexpected:
                violations.append(
                    f"{workflow.path.name}: unexpected triggers {sorted(unexpected)}"
                )
            pr = workflow.triggers.get("pull_request")
            if not isinstance(pr, dict):
                violations.append(f"{workflow.path.name}: must trigger on pull_request")
            else:
                if "paths" in pr or "paths-ignore" in pr:
                    violations.append(
                        f"{workflow.path.name}: release qualification must not declare path filters"
                    )
                branches = _trigger_list(pr, "branches")
                if branches != [contracts.main_branch]:
                    violations.append(
                        f"{workflow.path.name}: PR Fast must target {contracts.main_branch!r} only"
                        if "PR Fast" in str(violations)
                        else f"{workflow.path.name}: must target {contracts.main_branch!r} only"
                    )
                types = sorted(_trigger_list(pr, "types"))
                if types != sorted(contracts.feedback_types):
                    violations.append(
                        f"{workflow.path.name}: types must be {sorted(contracts.feedback_types)}"
                    )
        commands = "\n".join(workflow.run_commands())
        runner_uses += commands.count(contracts.runner_marker)
        staging_uses += commands.count(contracts.staging_marker)
        system_uses += commands.count(contracts.system_marker)
        unit_uses += commands.count(contracts.unit_command)
        retired_all_uses += commands.count("--suite all")
        lowered = commands.lower()
        for marker in contracts.git_mutation_markers:
            if marker.lower() in lowered:
                violations.append(f"{workflow.path.name}: Actions are evidence executors, not git brokers; found {marker!r}")
        for marker in contracts.protection_markers:
            if marker.lower() in lowered:
                violations.append(f"{workflow.path.name}: server-side protection configuration is out of scope; found {marker!r}")
        for action in workflow.action_uses():
            if any(action.startswith(prefix) for prefix in contracts.forbidden_action_prefixes):
                violations.append(f"{workflow.path.name}: mutating action {action!r} is forbidden")
            name, separator, pinned = action.partition("@")
            if not separator or len(pinned) != 40 or not is_hex(pinned):
                violations.append(f"{workflow.path.name}: action {name!r} must use a 40-hex SHA pin")
        for step in workflow.steps():
            uses = str(step.get("uses", ""))
            if not uses.startswith("actions/checkout@"):
                continue
            with_block = step.get("with")
            persist = with_block.get("persist-credentials") if isinstance(with_block, dict) else None
            if persist is not False:
                violations.append(f"{workflow.path.name}: checkout must set persist-credentials: false")
            if workflow.path.name == contracts.pr_fast_workflow and (
                not isinstance(with_block, dict) or with_block.get("fetch-depth") != 0
            ):
                violations.append(f"{workflow.path.name}: retained ratchets require complete Git history")
        workflow_text = workflow.path.read_text(encoding="utf-8")
        if "secrets." in workflow_text:
            violations.append(f"{workflow.path.name}: workflows must consume no secrets")
        if "continue-on-error" in workflow_text:
            violations.append(f"{workflow.path.name}: continue-on-error is forbidden")
    if runner_uses != 3:
        violations.append(f"the canonical test runner must appear exactly three times across all workflows, found {runner_uses}")
    if staging_uses != 1:
        violations.append(f"the staging project-owned command must appear exactly once, found {staging_uses}")
    if system_uses != 1:
        violations.append(f"the system project-owned command must appear exactly once, found {system_uses}")
    if retired_all_uses:
        violations.append(f"the retired --suite all command must not appear, found {retired_all_uses}")
    if unit_uses != 1:
        violations.append(f"the canonical PR unit command must appear exactly once, found {unit_uses}")
    return violations
