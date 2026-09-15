#!/usr/bin/env python3
"""Run RepoMap pytest suites and containerized smoke checks."""

from __future__ import annotations

from collections.abc import Sequence
import os
import sys
from pathlib import Path


if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if str(Path(__file__).resolve().parents[1] / "tools") not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from test_report import (
    CoverageFileRecord,
    CoverageSummary,
    TestRecord as TestRecord,
    report_docker_projection,
    write_html_report,
)
from runner_coverage import (
    ChildCoverageSession,
    CoveragePolicy,
    collect_coverage_summary,
    coverage_policy_for_suite,
    report_coverage,
)
from build_go_helper import build_go_helper, validate_go_sources
from runner_dependencies import (
    import_coverage,
    import_pytest,
    import_xdist,
)

if str(Path(__file__).resolve().parents[1] / "src" / "test" / "support" / "python") not in sys.path:
    sys.path.insert(
        0,
        str(
            Path(__file__).resolve().parents[1]
            / "src"
            / "test"
            / "support"
            / "python"
        ),
    )

from test_sandbox_dispatch import integration_sandbox_dispatch as integration_sandbox_dispatch
from repomap_test_support.test_scratch import (
    ENV_PHASE,
    TestScratchLayout,
    establish_run,
    finalize_run as finalize_run,
)
from repomap_test_support.unit_purity import UnitPurityState as UnitPurityState
from repomap_test_support.resource_hygiene_policy import (
    HygieneProfile as HygieneProfile,
    load_hygiene_config as load_hygiene_config,
)
from repomap_test_support.resource_retention import TerminalOutcome as TerminalOutcome
from repomap_test_support.resource_runner_profile import (
    resolve_runner_profile as resolve_runner_profile,
)
from repomap_test_support.resource_run import (
    TestResourceRun,
    cleanup_unadmitted_layout as cleanup_unadmitted_layout,
)
from repomap_test_support.resource_docker_boundary import (
    RunWideDockerBoundary,
)
from repomap_test_support.build_profile_debt import (
    DEFERRED_BUILD_PROFILE_NODE_IDS as DEFERRED_BUILD_PROFILE_NODE_IDS,
)

import runner_arguments as _runner_arguments
import runner_unit_execution as _runner_unit_execution


REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = REPO_ROOT / "tools"
SOURCE_ROOT = REPO_ROOT / "src" / "main" / "python"
TEST_SUPPORT_ROOT = REPO_ROOT / "src" / "test" / "support" / "python"
TEST_ROOTS = {
    "unit": REPO_ROOT / "src" / "test" / "unit" / "python",
    "int": REPO_ROOT / "src" / "test" / "int" / "python",
}
DEFAULT_UNIT_STATEMENT_HARD_THRESHOLD = 85.0
DEFAULT_UNIT_BRANCH_HARD_THRESHOLD = 85.0
DEFAULT_INT_LINE_HARD_THRESHOLD = 80.0
DEFAULT_INT_BRANCH_HARD_THRESHOLD = 80.0
DEFAULT_ADVISORY_THRESHOLD = 90.0
DEFAULT_REPORT_ROOT = REPO_ROOT / ".test-reports"


# Retained as public runner-module test-support exports.
__all__ = ("CoverageFileRecord", "CoveragePolicy", "CoverageSummary")


from test_runner_entry import RunnerDependencies, run_test_runner


def main(argv: list[str] | None = None) -> int:
    dependencies = RunnerDependencies(
        repo_root=REPO_ROOT, default_report_root=DEFAULT_REPORT_ROOT,
        split_forwarded_args=split_forwarded_args, parse_jobs=parse_jobs,
        validate_sandbox_admission_options=validate_sandbox_admission_options,
        integration_sandbox_dispatch=integration_sandbox_dispatch,
        establish_test_scratch=establish_test_scratch,
        load_hygiene_config=load_hygiene_config,
        resolve_runner_profile=resolve_runner_profile,
        resource_run_type=TestResourceRun,
        cleanup_unadmitted_layout=cleanup_unadmitted_layout,
        finalize_run=finalize_run,
        start_runwide_docker_boundary=start_runwide_docker_boundary,
        run_selected_suites=run_selected_suites,
        report_docker_projection=report_docker_projection,
        terminal_outcome_type=TerminalOutcome,
    )
    return run_test_runner(argv, dependencies=dependencies)


def establish_test_scratch(args) -> TestScratchLayout:
    """Select or validate the scratch root and install the run layout."""
    phase = os.environ.get(ENV_PHASE) or f"run-tests-{args.suite}"
    layout = establish_run(project="repo-map_dev", phase=phase).apply()
    print(f"Test run: {layout.run_root.name} (suite {args.suite})")
    print(f"Test run root: {layout.run_root}")
    return layout


def run_selected_suites(
    args,
    forwarded_pytest_args: list[str],
    resource_run: TestResourceRun | None,
    docker_boundary: RunWideDockerBoundary | None = None,
) -> int:
    return _runner_unit_execution.run_selected_suites(
        args,
        forwarded_pytest_args,
        resource_run,
        docker_boundary,
        require_integration_sandbox_fn=require_integration_sandbox,
        validate_runner_options_fn=validate_runner_options,
        run_system_suite_fn=_run_system_suite if args.suite == "system" else None,
        run_smoke_suite_fn=run_smoke_suite,
        prepare_go_test_environment_fn=prepare_go_test_environment,
        run_pytest_suites_fn=run_pytest_suites,
        report_docker_projection_fn=report_docker_projection,
    )


def _load_system_runner():
    from tools.system.runner_entry import run_system_suite

    return run_system_suite


def _run_system_suite(args, resource_run, docker_boundary):
    return _load_system_runner()(args, resource_run, docker_boundary)


def start_runwide_docker_boundary(args, resource_run):
    """Snapshot exact image/volume IDs before container-capable canonical work."""
    require_integration_sandbox(args.suite)
    if args.suite not in {"int", "smoke", "staging", "system"}:
        return None
    if not isinstance(resource_run, TestResourceRun):
        raise RuntimeError("run-wide Docker boundary requires an exact managed run")
    if args.pg_container_runtime != "docker":
        raise RuntimeError("run-wide Docker boundary requires Docker runtime")
    client = None
    authority = None
    try:
        import docker

        from repomap_test_support.resource_docker_mediation import install_canonical_authority
        from repomap_test_support.resource_test_image_materialization import recover_interrupted_runtime_materialization
        # Installed before any client exists so every independently constructed
        # docker.from_env() in this process shares the same mediation.
        authority = install_canonical_authority(resource_run.ledger)
        client = docker.from_env()
        recovered = recover_interrupted_runtime_materialization(
            client, repo_root=REPO_ROOT
        )
        if recovered is not None:
            print("Recovered one exact interrupted runtime materialization container before the run-wide Docker snapshot.")
        return RunWideDockerBoundary(resource_run, client, authority=authority)
    except Exception as error:
        if client is not None:
            client.close()
        if authority is not None:
            authority.uninstall()
        raise RuntimeError("run-wide Docker baseline is unavailable") from error
def prepare_go_test_environment(suite: str) -> None:
    _runner_unit_execution.prepare_go_test_environment(
        suite,
        establish_run_fn=establish_run,
        validate_go_sources_fn=validate_go_sources,
        build_go_helper_fn=build_go_helper,
    )


def run_pytest_suites(
    args,
    suites: tuple[str, ...],
    forwarded_pytest_args: list[str],
) -> int:
    from runner_staging_discovery import discover_staging_population

    return _runner_unit_execution.run_pytest_suites(
        args,
        suites,
        forwarded_pytest_args,
        source_root=SOURCE_ROOT,
        test_support_root=TEST_SUPPORT_ROOT,
        validate_runner_options_fn=validate_runner_options,
        coverage_policy_for_suite_fn=coverage_policy_for_suite,
        parallel_jobs_enabled_fn=parallel_jobs_enabled,
        import_pytest_fn=import_pytest,
        import_xdist_fn=import_xdist,
        build_pytest_args_fn=build_pytest_args,
        forwarded_selection_args_fn=forwarded_selection_args,
        establish_run_fn=establish_run,
        pytest_environment_for_fn=pytest_environment_for,
        run_pytest_fn=run_pytest,
        discovery_fn=discover_staging_population,
        import_coverage_fn=import_coverage,
        run_pytest_with_coverage_fn=run_pytest_with_coverage,
        collect_coverage_summary_fn=collect_coverage_summary,
        report_coverage_fn=report_coverage,
        write_html_report_fn=write_html_report,
        plugin_factory=RecordingPytestPlugin,
    )


def run_smoke_suite(
    args,
    resource_run: TestResourceRun | None,
    docker_boundary: RunWideDockerBoundary | None,
) -> int:
    return _runner_unit_execution.run_smoke_suite(
        args,
        resource_run,
        docker_boundary,
        repo_root=REPO_ROOT,
        source_root=SOURCE_ROOT,
    )


def split_forwarded_args(argv: list[str]) -> tuple[list[str], list[str]]:
    return _runner_arguments.split_forwarded_args(argv)


def parse_jobs(value: str) -> str:
    return _runner_arguments.parse_jobs(value)


def normalize_jobs(value: str) -> str:
    return _runner_arguments.normalize_jobs(value)


def validate_runner_options(args, suites: tuple[str, ...]) -> None:
    _runner_arguments.validate_runner_options(
        args,
        suites,
        parallel_jobs_enabled_fn=parallel_jobs_enabled,
    )


def validate_sandbox_admission_options(args) -> None:
    _runner_arguments.validate_sandbox_admission_options(
        args,
        validate_runner_options_fn=validate_runner_options,
    )


def require_integration_sandbox(suite: str) -> None:
    if suite not in {"int", "staging"}:
        return
    from test_sandbox import active_sandbox

    try:
        authenticated = active_sandbox()
    except RuntimeError as error:
        raise RuntimeError(
            "integration and staging execution requires the authenticated "
            "RepoMap container sandbox"
        ) from error
    if not authenticated:
        raise RuntimeError(
            "integration and staging execution requires the authenticated "
            "RepoMap container sandbox"
        )


def parallel_jobs_enabled(jobs: str) -> bool:
    return _runner_arguments.parallel_jobs_enabled(jobs)


def build_pytest_args(
    suites: tuple[str, ...],
    forwarded_pytest_args: list[str],
    *,
    jobs: str = "1",
    basetemp: Path | None = None,
) -> list[str]:
    return _runner_arguments.build_pytest_args(
        suites,
        forwarded_pytest_args,
        test_roots=TEST_ROOTS,
        repo_root=REPO_ROOT,
        jobs=jobs,
        basetemp=basetemp,
    )


def explicit_basetemp(forwarded_pytest_args: list[str]) -> bool:
    return _runner_arguments.explicit_basetemp(forwarded_pytest_args)


def forwarded_selection_args(forwarded_pytest_args: list[str]) -> tuple[str, ...]:
    return _runner_arguments.forwarded_selection_args(forwarded_pytest_args)


def validate_forwarded_selections(
    suites: tuple[str, ...],
    selections: tuple[str, ...],
) -> None:
    _runner_arguments.validate_forwarded_selections(
        suites,
        selections,
        TEST_ROOTS,
        REPO_ROOT,
    )


def is_relative_to(path: Path, root: Path) -> bool:
    return _runner_arguments.is_relative_to(path, root)


def pytest_environment_for(suites: tuple[str, ...], args):
    return _runner_unit_execution.pytest_environment_for(suites, args)


def run_pytest(pytest_module, pytest_args: list[str], plugin) -> int:
    return _runner_unit_execution.run_pytest(pytest_module, pytest_args, plugin)


def run_pytest_with_coverage(
    coverage_module,
    pytest_module,
    pytest_args,
    plugin,
    *,
    scratch_dir: Path | None = None,
    source_paths: Sequence[Path | str] = (),
    session: ChildCoverageSession | None = None,
    suite: str | None = None,
):
    return _runner_unit_execution.run_pytest_with_coverage(
        coverage_module,
        pytest_module,
        pytest_args,
        plugin,
        scratch_dir=scratch_dir,
        source_paths=source_paths,
        session=session,
        suite=suite,
        run_pytest_fn=run_pytest,
        child_coverage_session_cls=ChildCoverageSession,
        source_root=SOURCE_ROOT,
    )


RecordingPytestPlugin = _runner_unit_execution.RecordingPytestPlugin


if __name__ == "__main__":
    raise SystemExit(main())
