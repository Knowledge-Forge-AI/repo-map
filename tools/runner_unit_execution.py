"""Unit-oriented execution helpers for the compatibility runner facade."""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import nullcontext
import json
import sys
from pathlib import Path
from typing import Any

from repomap_test_support.test_scratch import establish_run
from runner_coverage import (
    ChildCoverageSession,
    collect_coverage_summary,
    coverage_policy_for_suite,
    report_coverage,
)
from runner_unit_environment import (
    RecordingPytestPlugin,
    prepare_go_test_environment,
    pytest_environment_for,
)
from test_report import write_html_report
from test_report_coverage import (
    CoverageStatus,
    coverage_diagnostics as _coverage_diagnostics,
    coverage_error_detail as _coverage_error_detail,
    finish_coverage_run as _finish_coverage_run,
)


def run_selected_suites(
    args,
    forwarded_pytest_args: list[str],
    resource_run,
    docker_boundary=None,
    *,
    require_integration_sandbox_fn,
    validate_runner_options_fn,
    run_system_suite_fn,
    run_smoke_suite_fn,
    prepare_go_test_environment_fn,
    run_pytest_suites_fn,
    report_docker_projection_fn,
) -> int:
    require_integration_sandbox_fn(args.suite)
    if args.suite == "system":
        validate_runner_options_fn(args, ("system",))
        if run_system_suite_fn is None:
            raise RuntimeError("system runner is unavailable")
        return run_system_suite_fn(args, resource_run, docker_boundary)

    if args.suite == "smoke":
        validate_runner_options_fn(args, ("smoke",))
        return run_smoke_suite_fn(args, resource_run, docker_boundary)

    if args.suite == "staging":
        smoke_exit_code = run_smoke_suite_fn(args, resource_run, docker_boundary)
        if smoke_exit_code != 0:
            if getattr(args, "report", False):
                from runner_integration_execution import record_smoke_refusal
                record_smoke_refusal(args)
            return smoke_exit_code
        if docker_boundary is not None:
            projection = docker_boundary.verify_terminal()
            report_docker_projection_fn(projection, boundary="post-smoke")
        suites = ("int",)
    else:
        suites = (args.suite,)
    prepare_go_test_environment_fn(args.suite)
    pytest_exit_code = run_pytest_suites_fn(args, suites, forwarded_pytest_args)
    if pytest_exit_code != 0:
        return pytest_exit_code
    if docker_boundary is not None:
        projection = docker_boundary.verify_terminal()
        report_docker_projection_fn(projection, boundary="post-pytest")
    return 0


def run_smoke_suite(
    args,
    resource_run,
    docker_boundary,
    *,
    repo_root: Path,
    source_root: Path,
) -> int:
    from smoke.container_smoke import SmokeConfig, run_container_smoke

    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))
    from repomap_kg.runtime.release import PSYCOPG_RELEASE_VERSION

    image_reference = args.smoke_image_reference
    if image_reference is None:
        if resource_run is None or docker_boundary is None:
            raise RuntimeError("managed smoke image ensure requires the run-wide boundary")
        from repomap_test_support.resource_test_images import ensure_canonical_runtime_image

        image_reference = ensure_canonical_runtime_image(
            repo_root=repo_root,
            resource_run=resource_run,
            client=docker_boundary.client,
            boundary=docker_boundary,
        )
    print()
    print("=== RepoMap container smoke suite ===", flush=True)
    config = SmokeConfig(
        repo_root=repo_root,
        timeout_seconds=args.smoke_timeout,
        image_reference=image_reference,
        psycopg_release_version=PSYCOPG_RELEASE_VERSION,
        pg_container_port=args.pg_container_port,
    )
    return run_container_smoke(config, resource_run=resource_run)


def run_pytest_suites(
    args,
    suites: tuple[str, ...],
    forwarded_pytest_args: list[str],
    *,
    source_root: Path,
    test_support_root: Path,
    validate_runner_options_fn,
    coverage_policy_for_suite_fn=coverage_policy_for_suite,
    parallel_jobs_enabled_fn,
    import_pytest_fn,
    import_xdist_fn,
    build_pytest_args_fn,
    forwarded_selection_args_fn,
    establish_run_fn=establish_run,
    pytest_environment_for_fn,
    run_pytest_fn,
    discovery_fn=None,
    import_coverage_fn,
    run_pytest_with_coverage_fn,
    collect_coverage_summary_fn=collect_coverage_summary,
    report_coverage_fn=report_coverage,
    write_html_report_fn=write_html_report,
    plugin_factory,
) -> int:
    coverage_policy = coverage_policy_for_suite_fn(
        args.suite,
        threshold_override=args.threshold,
    )
    sys.path.insert(0, str(source_root))
    sys.path.insert(0, str(test_support_root))

    validate_runner_options_fn(args, suites)
    pytest_module = import_pytest_fn()
    if parallel_jobs_enabled_fn(args.jobs):
        import_xdist_fn()
    pytest_args = build_pytest_args_fn(
        suites,
        forwarded_pytest_args,
        jobs=args.jobs,
        basetemp=establish_run_fn().pytest_basetemp,
    )
    if args.suite in {"int", "staging"}:
        from runner_integration_execution import execute_staging_decision_b
        return execute_staging_decision_b(
            args,
            suites,
            forwarded_pytest_args,
            source_root=source_root,
            test_support_root=test_support_root,
            repo_root=source_root.parents[2],
            pytest_module=pytest_module,
            pytest_args=pytest_args,
            pytest_environment_for_fn=pytest_environment_for_fn,
            run_pytest_fn=run_pytest_fn,
            discovery_fn=discovery_fn,
            import_coverage_fn=import_coverage_fn,
            run_pytest_with_coverage_fn=run_pytest_with_coverage_fn,
            coverage_policy=coverage_policy,
            collect_coverage_summary_fn=collect_coverage_summary_fn,
            report_coverage_fn=report_coverage_fn,
            write_html_report_fn=write_html_report_fn,
            forwarded_selection_args_fn=forwarded_selection_args_fn,
        )

    plugin = plugin_factory(
        suite=args.suite,
        full_population=not forwarded_selection_args_fn(forwarded_pytest_args),
    )
    session = None
    coverage_runner = None
    coverage = None
    coverage_status = CoverageStatus(
        "disabled" if args.no_coverage else "unavailable"
    )
    coverage_diagnostics: tuple[dict[str, Any], ...] = ()
    coverage_ok = True
    pytest_exit_code = 2
    report_error: Exception | None = None
    try:
        with pytest_environment_for_fn(suites, args):
            if args.no_coverage:
                pytest_exit_code = int(run_pytest_fn(pytest_module, pytest_args, plugin))
            else:
                try:
                    coverage_module = import_coverage_fn()
                    pytest_exit_code, coverage_runner = run_pytest_with_coverage_fn(
                        coverage_module, pytest_module, pytest_args, plugin,
                    )
                    session = getattr(coverage_runner, "_repomap_session", None)
                except Exception as error:
                    coverage_ok = False
                    coverage_status = CoverageStatus(
                        "unavailable", detail=_coverage_error_detail(error)
                    )
                    print(
                        f"ERROR: coverage execution failed: {coverage_status.detail}",
                        file=sys.stderr,
                    )
            print(f"Deferred build-profile tests: {plugin.deferred_build_count}")
            if pytest_exit_code == int(pytest_module.ExitCode.NO_TESTS_COLLECTED):
                print(f"ERROR: no tests discovered for suite {args.suite}", file=sys.stderr)
                # Keep the runner's established terminal code for an empty
                # selection while still writing the records and coverage
                # status gathered above.
                pytest_exit_code = 2
            if args.no_coverage:
                print("Coverage disabled for this run (--no-coverage).")
            elif coverage_runner is None:
                coverage_ok = False
                if coverage_status.state == "unavailable" and not coverage_status.detail:
                    coverage_status = CoverageStatus(
                        "unavailable", detail="coverage runner was not created"
                    )
            else:
                instrumentation_error = getattr(
                    coverage_runner, "_instrumentation_error", None
                )
                if instrumentation_error:
                    coverage_ok = False
                    coverage_status = CoverageStatus(
                        "incomplete", detail=_coverage_error_detail(instrumentation_error)
                    )
                    print(
                        f"ERROR: coverage collection failed: {coverage_status.detail}",
                        file=sys.stderr,
                    )
                else:
                    try:
                        coverage = collect_coverage_summary_fn(
                            coverage_runner,
                            args.suite,
                            coverage_policy,
                            json_report_path=(
                                Path(args.report_dir) / args.suite / "coverage.json"
                                if args.report
                                else None
                            ),
                        )
                        coverage_status = CoverageStatus("measured")
                        coverage_ok = report_coverage_fn(coverage)
                    except Exception as error:
                        coverage_ok = False
                        coverage_status = CoverageStatus(
                            "unavailable", detail=_coverage_error_detail(error)
                        )
                        print(
                            f"ERROR: coverage reporting failed: {coverage_status.detail}",
                            file=sys.stderr,
                        )
            if coverage_status.state != "measured":
                coverage_diagnostics = _coverage_diagnostics(session)
                if coverage_diagnostics:
                    coverage_status = CoverageStatus(
                        coverage_status.state,
                        detail=coverage_status.detail,
                        diagnostics=coverage_diagnostics,
                    )
                if coverage_diagnostics:
                    diag = json.dumps(list(coverage_diagnostics), indent=2)
                    print(f"DIAGNOSTIC SNAPSHOT:\n{diag}", file=sys.stderr)
                    if args.report and args.report_dir:
                        snap_out = (
                            Path(args.report_dir)
                            / args.suite
                            / "latest"
                            / "coverage_anomaly_snapshot.json"
                        )
                        snap_out.parent.mkdir(parents=True, exist_ok=True)
                        snap_out.write_text(diag + "\n", encoding="utf-8")
            from go_runner_coverage import evaluate_go_integration_gate

            go_coverage, go_ok = evaluate_go_integration_gate(args.suite, args.no_coverage)
            if not go_ok:
                coverage_ok = False
        if args.report:
            try:
                report_path = write_html_report_fn(
                    report_root=args.report_dir,
                    suite_name=args.suite,
                    test_records=plugin.test_records,
                    coverage=coverage,
                    repo_root=source_root.parents[2],
                    go_coverage=go_coverage,
                    coverage_status=coverage_status,
                )
                print(f"Detailed report: {report_path}")
            except Exception as error:
                report_error = error
                print(
                    f"ERROR: report generation failed: {_coverage_error_detail(error)}",
                    file=sys.stderr,
                )
    finally:
        if session is not None and hasattr(session, "cleanup"):
            session.cleanup()

    if pytest_exit_code != 0:
        return pytest_exit_code
    if not coverage_ok:
        return 1
    if report_error is not None:
        return 1
    return 0


def run_pytest(pytest_module, pytest_args: list[str], plugin) -> int:
    return pytest_module.main(pytest_args, plugins=[plugin])


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
    run_pytest_fn=run_pytest,
    child_coverage_session_cls=ChildCoverageSession,
    source_root: Path,
):
    active_suite = suite or getattr(plugin, "_suite", getattr(plugin, "suite", None)) or "inert"
    if active_suite == "unit" and session is None and not source_paths and scratch_dir is None:
        coverage_runner = coverage_module.Coverage(
            branch=True,
            source=[str(source_root)],
            data_file=None,
            config_file=False,
        )
        coverage_runner.start()
        try:
            pytest_exit_code = int(run_pytest_fn(pytest_module, pytest_args, plugin))
        finally:
            coverage_runner = _finish_coverage_run(
                coverage_runner,
                session=None,
                save=False,
            )
        return pytest_exit_code, coverage_runner
    if session is None:
        session = child_coverage_session_cls(
            coverage_module=coverage_module,
            scratch_dir=scratch_dir,
            source_paths=source_paths,
            suite=active_suite,
        )
    with session:
        coverage_runner = session.create_coverage(coverage_module)
        setattr(coverage_runner, "_repomap_session", session)
        coverage_runner.start()
        try:
            abrupt = getattr(plugin, "abrupt_context", None)
            with abrupt.bind_session(session) if abrupt is not None else nullcontext():
                pytest_exit_code = int(run_pytest_fn(pytest_module, pytest_args, plugin))
        finally:
            coverage_runner = _finish_coverage_run(
                coverage_runner,
                session=session,
                save=True,
            )
    return pytest_exit_code, coverage_runner


__all__ = (
    "RecordingPytestPlugin",
    "prepare_go_test_environment",
    "pytest_environment_for",
    "run_pytest",
    "run_pytest_suites",
    "run_pytest_with_coverage",
    "run_selected_suites",
    "run_smoke_suite",
)
