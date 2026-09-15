"""Same-invocation paired integration execution with strict measured sessions."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any
from uuid import uuid4

from runner_abrupt_evidence import AbruptRunnerContext
from runner_integration_population import LegPartitionPytestPlugin
from runner_coverage import ChildCoverageSession
from staging_report_contract import (
    SCHEMA, POLICY, digest_partition, execution_succeeded, persist_staging_report,
)
from test_report_coverage import CoverageStatus, coverage_diagnostics
from test_report import TestRecord


def candidate_identity(repo_root: Path) -> dict[str, str]:
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo_root, text=True).strip()
    paths = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard",
         "--", "src/main", "src/test", "tools", "pyproject.toml"], cwd=repo_root)
    digest = hashlib.sha256()
    for name in sorted(set(paths.split(b"\0")) - {b""}):
        path = repo_root / os.fsdecode(name)
        if not path.is_file():
            raise RuntimeError("candidate source file disappeared")
        digest.update(name + b"\0" + hashlib.sha256(path.read_bytes()).digest())
    return {"commit": commit, "source_sha256": digest.hexdigest()}


def _leg_record(planned, enabled, leg="M"):
    return {"status": "blocked" if planned else "not_selected", "pytest_exit": None,
            "planned": list(planned), "records": [], "completed": [],
            "measurement": {"state": "unavailable" if enabled or leg == "A" else "disabled",
                            "valid": False, "summary": None, "session_id": None},
            "abrupt_roles": [], "cleanup": "unknown"}


def _summary(coverage, repo_root):
    result = asdict(coverage)
    result["files"] = list(result["files"])
    for entry in result["files"]:
        path = Path(entry["path"])
        entry["path"] = str(path.relative_to(repo_root) if path.is_absolute() else path)
    return result


def record_smoke_refusal(args) -> None:
    """Export a failed admission without pretending a population was executed."""
    payload: dict[str, Any] = {
        "schema": SCHEMA, "policy": POLICY, "invocation_id": uuid4().hex,
        "candidate": candidate_identity(Path(__file__).resolve().parents[1]),
        "scoped": False, "coverage_enabled": not args.no_coverage,
        "smoke": "failed", "partition": {}, "go_coverage": None,
        "legs": {name: _leg_record((), not args.no_coverage, name) for name in ("M", "A")},
        "errors": ["smoke admission failed; integration obligations not executed"],
    }
    for entry in payload["legs"].values():
        entry["status"] = "blocked"
    persist_staging_report(
        Path(args.report_dir) / "staging" / "latest" / "staging_contract_report.json", payload)


def execute_staging_decision_b(
    args, suites, forwarded_pytest_args, *, source_root, test_support_root,
    repo_root, pytest_module, pytest_args, pytest_environment_for_fn,
    run_pytest_fn, import_coverage_fn, run_pytest_with_coverage_fn, coverage_policy,
    collect_coverage_summary_fn, report_coverage_fn, write_html_report_fn,
    forwarded_selection_args_fn,
    discovery_fn=None,
) -> int:
    invocation = uuid4().hex
    identity = candidate_identity(repo_root)
    enabled = not args.no_coverage
    scoped = bool(forwarded_selection_args_fn(forwarded_pytest_args))
    report: dict[str, Any] = {"schema": SCHEMA, "policy": POLICY, "invocation_id": invocation,
              "candidate": identity, "scoped": scoped, "coverage_enabled": enabled,
              "smoke": "passed" if args.suite == "staging" else "not_required",
              "go_coverage": None,
              "partition": {}, "legs": {"M": _leg_record((), enabled),
                                          "A": _leg_record((), enabled, "A")}, "errors": []}
    output = Path(args.report_dir) / args.suite / "latest" / "staging_contract_report.json"
    sessions = []
    records: list[TestRecord] = []
    measured = None
    go_summary = None
    collectors: dict[str, Any] = {}

    def verify_source():
        if candidate_identity(repo_root) != identity:
            raise RuntimeError("candidate source changed during invocation")

    try:
        if discovery_fn is None:
            from runner_staging_discovery import discover_staging_population
            discovery_fn = discover_staging_population
        with pytest_environment_for_fn(suites, args):
            partition = discovery_fn(
                args, pytest_args, repo_root=repo_root, source_root=source_root,
                test_support_root=test_support_root, invocation_id=invocation,
                candidate_identity=identity, scoped=scoped,
            )
        verify_source()
        partition_data: dict[str, Any] = {
            "collected": list(partition.collected_nodes),
            "required": list(partition.all_nodes), "measured": list(partition.m_nodes),
            "abrupt": list(partition.a_nodes), "deferred": list(partition.deferred_nodes),
        }
        partition_data["sha256"] = digest_partition(partition_data)
        report["partition"] = partition_data
        report["legs"] = {name: _leg_record(nodes, enabled, name)
                          for name, nodes in (("M", partition.m_nodes), ("A", partition.a_nodes))}
        # The sealed plan is exported before either execution, including refusals.
        persist_staging_report(output, report)
        safe = True
        for leg, nodes in (("M", partition.m_nodes), ("A", partition.a_nodes)):
            entry = report["legs"][leg]
            if not nodes or not safe:
                continue
            verify_source()
            plugin = LegPartitionPytestPlugin(partition, leg, suite=args.suite,
                                              full_population=not scoped)
            abrupt = None
            if leg == "A":
                abrupt = AbruptRunnerContext(nodeids=nodes, invocation_id=invocation,
                    source_sha256=identity["source_sha256"], verify_source=verify_source)
                plugin.abrupt_context = abrupt
            previous_go = os.environ.get("GOCOVERDIR")
            if leg == "A" and enabled:
                from repomap_test_support.test_scratch import establish_run
                a_go = establish_run().go_tmp / ("abrupt-" + invocation)
                a_go.mkdir(mode=0o700)
                os.environ["GOCOVERDIR"] = str(a_go)
            try:
                with pytest_environment_for_fn(suites, args):
                    if not enabled:
                        with abrupt.bind_session(None) if abrupt else nullcontext():
                            entry["pytest_exit"] = int(run_pytest_fn(pytest_module, pytest_args, plugin))
                        entry["measurement"].update(
                            state="unavailable" if leg == "A" else "disabled", valid=True)
                    else:
                        cov_module = import_coverage_fn()
                        session = ChildCoverageSession(coverage_module=cov_module,
                                                       source_root=source_root, suite=args.suite)
                        sessions.append(session)
                        entry["measurement"]["session_id"] = session.session_dir.name
                        exit_code, cov_runner = run_pytest_with_coverage_fn(
                            cov_module, pytest_module, pytest_args, plugin,
                            session=session, suite=args.suite)
                        entry["pytest_exit"] = int(exit_code)
                        collectors[leg] = cov_runner
                        instrumentation_error = getattr(cov_runner, "_instrumentation_error", None)
                        if instrumentation_error:
                            entry["measurement"]["state"] = "incomplete"
                            report["errors"].append(f"{leg}: ordinary measurement incomplete")
                            # Missing child completion can also mean unsettled
                            # resources. Preserve evidence and refuse continuation.
                            safe = False
                        else:
                            entry["measurement"].update(
                                state="measured" if leg == "M" else "unavailable", valid=True)
                            if leg == "M":
                                measured = collect_coverage_summary_fn(
                                    cov_runner, args.suite, coverage_policy,
                                    json_report_path=Path(args.report_dir) / args.suite / "coverage.json"
                                    if args.report else None)
                                entry["measurement"]["summary"] = _summary(measured, repo_root)
                                if not report_coverage_fn(measured):
                                    report["errors"].append("M: coverage floors not met")
                        diagnostics = coverage_diagnostics(session)
                        if diagnostics and args.report:
                            (output.parent / f"{leg}-measurement-diagnostics.json").write_text(
                                json.dumps(diagnostics, indent=2) + "\n")
                if leg == "M":
                    from go_runner_coverage import evaluate_go_integration_gate
                    go_summary, go_ok = evaluate_go_integration_gate(args.suite, args.no_coverage)
                    report["go_coverage"] = asdict(go_summary) if go_summary is not None else None
                    if not go_ok:
                        report["errors"].append("M: Go measurement failed")
            except BaseException as error:
                # Interrupted/setup/collector failures retain all available records
                # and block unsafe continuation. No hidden retry of either leg.
                report["errors"].append(f"{leg}: execution {type(error).__name__}")
                safe = False
            finally:
                if leg == "A":
                    if previous_go is None:
                        os.environ.pop("GOCOVERDIR", None)
                    else:
                        os.environ["GOCOVERDIR"] = previous_go
                entry["records"] = [asdict(record) for record in plugin.test_records]
                records.extend(plugin.test_records)
                entry["completed"] = list(plugin.completed_nodeids)
                if abrupt is not None:
                    entry["abrupt_roles"] = list(abrupt.records.values())
                safe = (safe and not plugin.teardown_failed
                        and set(plugin.executed_nodeids) == set(plugin.completed_nodeids)
                        and entry["pytest_exit"] in (0, 1))
                entry["cleanup"] = "passed" if safe else "unknown"
                entry["status"] = "passed" if (
                    safe and entry["pytest_exit"] == 0 and entry["measurement"]["valid"]
                    and len(entry["records"]) == len(nodes)
                    and (leg != "A" or len(entry["abrupt_roles"]) == len(nodes))) else "failed"
                persist_staging_report(output, report)
        verify_source()
    except BaseException as error:
        report["errors"].append(f"accounting: {type(error).__name__}")
    finally:
        try:
            persist_staging_report(output, report)
            if args.report:
                state = report["legs"]["M"]["measurement"]["state"]
                try:
                    write_html_report_fn(report_root=args.report_dir, suite_name=args.suite,
                        test_records=tuple(records), coverage=measured, repo_root=repo_root,
                        go_coverage=go_summary, coverage_status=CoverageStatus(state),
                        staging_obligations=report)
                except Exception as error:
                    report["errors"].append(f"rendering: {type(error).__name__}")
                    persist_staging_report(output, report)
        finally:
            from go_runner_coverage import restore_go_environment
            restore_go_environment()
            for session in sessions:
                try:
                    session.cleanup()
                except Exception as error:
                    report["errors"].append(f"measurement cleanup: {type(error).__name__}")
                    for entry in report["legs"].values():
                        if entry["measurement"]["session_id"] == session.session_dir.name:
                            entry.update(cleanup="unknown", status="failed")
            persist_staging_report(output, report)
    return 0 if execution_succeeded(report) else 1
