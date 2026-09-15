"""Typed invocation capabilities for the canonical runner lifecycle."""
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from dataclasses import dataclass
import os
from pathlib import Path
import sys
import time
from typing import Protocol

from repomap_test_support.resource_hygiene_policy import HygieneConfig, HygieneProfile
from repomap_test_support.resource_retention import TerminalOutcome
from repomap_test_support.resource_run import TestResourceRun
from repomap_test_support.resource_runner_profile import RunnerProfileSelection
from repomap_test_support.resource_docker_boundary import RunWideDockerBoundary
from repomap_test_support.test_scratch import TestScratchLayout
import runner_arguments as _runner_arguments


class LoadHygieneConfig(Protocol):
    def __call__(self, *, cli_overrides: Mapping[str, object],
                 environ: Mapping[str, str], local_path: Path) -> HygieneConfig: ...


class ResolveProfile(Protocol):
    def __call__(self, suite: str, *, requested_profile: HygieneProfile | None,
                 declared_complete_gates: int, campaign_plan_id: str | None,
                 operator_attested_exclusive: bool,
                 operator_attested_pressure_degradation: bool) -> RunnerProfileSelection: ...


class FinalizeRun(Protocol):
    def __call__(self, layout: TestScratchLayout, result: str, *, exit_status: int,
                 live_runtime_residue: bool = False) -> None: ...


class ReportProjection(Protocol):
    def __call__(self, projection: dict[str, int], *, boundary: str) -> None: ...


class RunSuites(Protocol):
    def __call__(self, args: argparse.Namespace, forwarded_pytest_args: list[str],
                 resource_run: TestResourceRun | None,
                 docker_boundary: RunWideDockerBoundary | None = None) -> int: ...


@dataclass(frozen=True)
class RunnerDependencies:
    """Resolve facade globals for each invocation, including patched call sites."""

    repo_root: Path
    default_report_root: Path
    split_forwarded_args: Callable[[list[str]], tuple[list[str], list[str]]]
    parse_jobs: Callable[[str], str]
    validate_sandbox_admission_options: Callable[[argparse.Namespace], None]
    integration_sandbox_dispatch: Callable[[argparse.Namespace, list[str]], int | None]
    establish_test_scratch: Callable[[argparse.Namespace], TestScratchLayout]
    load_hygiene_config: LoadHygieneConfig
    resolve_runner_profile: ResolveProfile
    resource_run_type: type[TestResourceRun]
    cleanup_unadmitted_layout: Callable[[TestScratchLayout], None]
    finalize_run: FinalizeRun
    start_runwide_docker_boundary: Callable[[argparse.Namespace, TestResourceRun], RunWideDockerBoundary | None]
    run_selected_suites: RunSuites
    report_docker_projection: ReportProjection
    terminal_outcome_type: type[TerminalOutcome]


def run_test_runner(argv: list[str] | None, *, dependencies: RunnerDependencies) -> int:
    """Execute admission and cleanup with the caller's exact capability bindings."""
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    runner_argv, forwarded_pytest_args = dependencies.split_forwarded_args(raw_argv)
    parser = argparse.ArgumentParser(
        description="Run RepoMap tests with host-safe coverage gates."
    )
    _runner_arguments.add_runner_arguments(
        parser,
        hygiene_profiles=tuple(profile.value for profile in HygieneProfile),
        default_report_root=dependencies.default_report_root,
        parse_jobs=dependencies.parse_jobs,
    )
    args = parser.parse_args(runner_argv)

    if args.suite in {"smoke", "staging"}:
        from smoke import is_exact_image_reference

        if args.smoke_image_reference and not is_exact_image_reference(args.smoke_image_reference):
            print(
                "ERROR: --smoke-image-reference override must be "
                "sha256:<64 lowercase hex>",
                file=sys.stderr,
            )
            return 2
        if args.smoke_timeout < 1:
            print(
                "ERROR: --suite smoke/staging requires --smoke-timeout >= 1",
                file=sys.stderr,
            )
            return 2

    if args.suite == "system":
        if not 120 <= args.system_timeout <= 3600:
            print(
                "ERROR: --suite system requires 120 <= --system-timeout <= 3600",
                file=sys.stderr,
            )
            return 2
        from tools.system.config import (
            ENV_SYSTEM_DEADLINE_EPOCH,
            ENV_SYSTEM_START_EPOCH,
        )

        if ENV_SYSTEM_DEADLINE_EPOCH not in os.environ:
            start_epoch = time.time()
            os.environ[ENV_SYSTEM_START_EPOCH] = str(start_epoch)
            os.environ[ENV_SYSTEM_DEADLINE_EPOCH] = str(
                start_epoch + float(args.system_timeout)
            )

    try:
        dependencies.validate_sandbox_admission_options(args)
    except RuntimeError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2

    sandbox_result = dependencies.integration_sandbox_dispatch(args, raw_argv)
    if sandbox_result is not None:
        return sandbox_result

    layout = dependencies.establish_test_scratch(args)
    cli_hygiene = {
        key: value
        for key, value in {
            "PROFILE": args.hygiene_profile,
            "SOFT_WATERMARK_BYTES": args.hygiene_soft_watermark_bytes,
            "SOFT_WATERMARK_INODES": args.hygiene_soft_watermark_inodes,
            "HARD_WATERMARK_BYTES": args.hygiene_hard_watermark_bytes,
            "HARD_WATERMARK_INODES": args.hygiene_hard_watermark_inodes,
            "MIN_FREE_DISK_BYTES": args.hygiene_min_free_disk_bytes,
            "MIN_FREE_DISK_PERCENT": args.hygiene_min_free_disk_percent,
            "PROFILE_FREE_DISK_RESERVE_BYTES": args.hygiene_profile_free_disk_reserve_bytes,
        }.items()
        if value is not None
    }
    try:
        hygiene_config = dependencies.load_hygiene_config(
            cli_overrides=cli_hygiene,
            environ=dict(os.environ),
            local_path=dependencies.repo_root / "test-hygiene.local.toml",
        )
        profile_selection = dependencies.resolve_runner_profile(
            args.suite,
            requested_profile=hygiene_config.requested_profile,
            declared_complete_gates=args.declared_complete_gates,
            campaign_plan_id=args.campaign_plan_id,
            operator_attested_exclusive=args.operator_attest_exclusive,
            operator_attested_pressure_degradation=(
                args.operator_attest_pressure_degradation
            ),
        )
        resource_run: TestResourceRun | None = dependencies.resource_run_type.start(
            layout,
            profile=profile_selection.selected_profile,
            config=hygiene_config,
            operator_attested_exclusive=(
                profile_selection.operator_attested_exclusive
            ),
            operator_attested_pressure_degradation=(
                profile_selection.operator_attested_pressure_degradation
            ),
            campaign_plan_id=profile_selection.campaign_plan_id,
            declared_complete_gates=profile_selection.declared_complete_gates,
        )
    except RuntimeError as error:
        print(f"ERROR: test hygiene admission failed: {error}", file=sys.stderr)
        resource_cleanup_failed = False
        if layout.allocated:
            try:
                dependencies.cleanup_unadmitted_layout(layout)
            except RuntimeError as cleanup_error:
                print(
                    f"ERROR: unadmitted scratch cleanup failed: {cleanup_error}",
                    file=sys.stderr,
                )
                resource_cleanup_failed = True
        dependencies.finalize_run(
            layout,
            "failed",
            exit_status=2,
            live_runtime_residue=resource_cleanup_failed,
        )
        return 2
    if args.report and args.report_dir == dependencies.default_report_root and resource_run:
        evidence_root = layout.run_root / "evidence"
        evidence_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        resource_run.retain_evidence(evidence_root, reason="report_source")
        report_root = evidence_root / "test-report"
        report_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        args.report_dir = report_root
    exit_code = 2
    resource_cleanup_failed = False
    docker_boundary = None
    try:
        if resource_run is not None and resource_run.quota_exceeded is True:
            print("ERROR: quota_exceeded before workload creation", file=sys.stderr)
            exit_code = 2
        elif resource_run is None and args.suite in {"int", "smoke", "staging", "system"}:
            print(
                "ERROR: int/smoke/staging/system requires an allocating managed resource run; "
                "an inherited REPOMAP_TEST_RUN_ROOT is not sufficient",
                file=sys.stderr,
            )
            exit_code = 2
        elif resource_run is None:
            exit_code = dependencies.run_selected_suites(args, forwarded_pytest_args, resource_run)
        else:
            docker_boundary = dependencies.start_runwide_docker_boundary(args, resource_run)
            with resource_run.bounded_subprocess(f"suite_{args.suite}"):
                exit_code = dependencies.run_selected_suites(
                    args,
                    forwarded_pytest_args,
                    resource_run,
                    docker_boundary,
                )
    except RuntimeError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        exit_code = 2
    finally:
        if docker_boundary is not None:
            try:
                projection = docker_boundary.verify_terminal()
                dependencies.report_docker_projection(projection, boundary="terminal")
            except RuntimeError as error:
                err_projection = getattr(error, "projection", None)
                if err_projection is not None:
                    dependencies.report_docker_projection(err_projection, boundary="terminal")
                print(f"ERROR: {error}", file=sys.stderr)
                exit_code = 2
                resource_cleanup_failed = True
            finally:
                try:
                    docker_boundary.close(resource_run)
                except Exception as error:
                    print(
                        f"ERROR: Docker boundary closeout failed: {error}",
                        file=sys.stderr,
                    )
                    exit_code = 2
                    resource_cleanup_failed = True
        if resource_run is not None:
            try:
                resource_run.close(
                    dependencies.terminal_outcome_type.PASSED
                    if exit_code == 0
                    else dependencies.terminal_outcome_type.FAILED
                )
            except RuntimeError as error:
                print(f"ERROR: test resource cleanup failed: {error}", file=sys.stderr)
                exit_code = 2
                resource_cleanup_failed = True
        dependencies.finalize_run(
            layout,
            "passed" if exit_code == 0 else "failed",
            exit_status=exit_code,
            live_runtime_residue=resource_cleanup_failed,
        )
    return exit_code

