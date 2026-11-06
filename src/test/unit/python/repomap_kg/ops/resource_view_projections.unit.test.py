"""Pure context/staging projections and terminal outcome mappings."""

from __future__ import annotations

from types import SimpleNamespace

from common_lore_index.ops.resource_view import ResourceObserver, begin, mark, note_lexical_limits
from common_lore_index.ops.resource_view._projections import (
    finish_lexical, finish_server, project_compact_context, project_staging_resources,
)
from common_lore_index.storage._staging_measurement_records import (
    StagingMeasurementCategory, StagingMeasurementEvent, StagingMeasurementUnit,
)


def _ledger() -> dict[str, int | None]:
    return {
        "config_revalidations_executed": 1, "logical_read_units": 2,
        "sql_statements_executed": 3, "scan_units_executed": 1,
        "seed_expansions_executed": 1, "candidate_rows_scanned": 4,
        "evidence_rows_scanned": 5, "elapsed_ms": 6, "actual_bytes": 700,
        "sqlite_progress_callbacks": 8, "sqlite_vm_steps_estimate": 8000,
        "sqlite_progress_interval_ops": 1000, "max_logical_read_units": 16,
        "max_sql_statements": 36, "max_scan_units": 8, "max_seed_expansions": 5,
    }


def test_context_projection_reads_existing_values_without_mutating_packet() -> None:
    packet = {
        "status": "complete",
        "scope": {"backend": "sqlite"},
        "request": {"budget_bytes": 4096},
        "work_ledger": _ledger(),
        "items": [{"public": True}],
    }
    before = {key: value.copy() if isinstance(value, dict) else value for key, value in packet.items()}
    report = project_compact_context(packet)
    assert packet == before
    assert report.operation == "compact_context"
    assert report.backend == "sqlite"
    assert report.outcome == "complete"
    assert {metric.name for metric in report.metrics} >= {
        "actual_bytes", "sqlite_progress_callbacks", "sqlite_vm_steps_estimate",
    }
    limits = {limit.name: limit for limit in report.limits}
    assert limits["wall_clock_deadline"].value == 10_000
    assert limits["sqlite_progress_callback_limit"].value == 250
    assert limits["wall_clock_deadline"].applies_this_call is None
    assert limits["sqlite_progress_callback_limit"].applies_this_call is None
    assert limits["budget_bytes"].applies_this_call is True


def test_context_custom_ledger_controls_are_not_replaced_by_owner_ceiling() -> None:
    ledger = dict(_ledger(), deadline_ms=7, sqlite_progress_callback_limit=9)
    report = project_compact_context(
        {"status": "partial", "scope": {"backend": "sqlite"}, "request": {"budget_bytes": 8192}, "work_ledger": ledger},
        work_ledger=ledger,
    )
    limits = {limit.name: limit for limit in report.limits}
    assert limits["wall_clock_deadline"].value == 7
    assert limits["sqlite_progress_callback_limit"].value == 9
    assert limits["wall_clock_deadline"].applies_this_call is True
    assert limits["sqlite_progress_callback_limit"].applies_this_call is True


def test_budget_error_does_not_read_or_report_ledger_controls() -> None:
    report = project_compact_context(
        {"schema": "cloe-compact-context-v1", "status": "budget_error", "work_ledger": _ledger()},
        work_ledger=SimpleNamespace(deadline_ms=1),
    )
    assert report.outcome == "budget_error"
    assert report.limits == ()
    assert all(metric.reason == "not_reached" for metric in report.metrics)


def test_postgres_context_marks_sqlite_only_rows_not_applicable() -> None:
    report = project_compact_context(
        {
            "status": "unavailable", "scope": {"backend": "postgresql"},
            "request": {"budget_bytes": 4096}, "work_ledger": _ledger(),
        }
    )
    rows = [metric for metric in report.metrics if metric.name in {
        "sqlite_progress_callbacks", "sqlite_vm_steps_estimate", "sqlite_progress_interval_ops",
    }]
    assert len(rows) == 3
    assert all(row.value is None and row.reason == "backend_not_applicable" for row in rows)


def test_context_snapshot_counters_are_not_replaced_by_a_live_ledger() -> None:
    snapshot = _ledger()
    report = project_compact_context(
        {"status": "complete", "scope": {"backend": "sqlite"}, "work_ledger": snapshot},
        work_ledger=SimpleNamespace(logical_read_units=999, actual_bytes=0, deadline_ms=7,
                                    sqlite_progress_callback_limit=9),
    )
    rows = {row.name: row for row in report.metrics}
    assert rows["logical_read_units"].value == snapshot["logical_read_units"]
    assert rows["actual_bytes"].value == snapshot["actual_bytes"]
    assert rows["sqlite_vm_steps_estimate"].value == snapshot["sqlite_vm_steps_estimate"]


def test_staging_projection_has_fixed_slots_and_honest_duplicates() -> None:
    wal = StagingMeasurementEvent.measured(
        StagingMeasurementCategory.WAL_UPPER_BOUND, value=4,
        unit=StagingMeasurementUnit.BYTES, upper_bound=True,
    )
    duplicate = StagingMeasurementEvent.measured(
        StagingMeasurementCategory.WAL_UPPER_BOUND, value=5,
        unit=StagingMeasurementUnit.BYTES, upper_bound=True,
    )
    unavailable = StagingMeasurementEvent.unavailable(
        StagingMeasurementCategory.CLIENT_MEMORY, unit=StagingMeasurementUnit.BYTES,
        upper_bound=True,
    )
    metrics = project_staging_resources((wal, duplicate, unavailable), measurements_failed=False)
    by_name = {metric.name: metric for metric in metrics}
    assert by_name["wal_upper_bound"].reason == "ambiguous_repeat"
    assert by_name["temporary_byte_upper_bound"].reason == "not_emitted"
    assert by_name["client_memory"].reason == "not_observed"
    failed = project_staging_resources((), measurements_failed=True)
    assert all(metric.reason == "observer_failed" for metric in failed)


def test_server_failure_keeps_open_publication_stage_incomplete() -> None:
    observer = ResourceObserver(_monotonic_ns=iter((0, 5, 9)).__next__, _process_time_ns=iter((0, 1)).__next__)
    begin(observer, "server_refresh", "postgresql")
    mark(observer, "publication")
    result = SimpleNamespace(result="failure", publication_state="not_started", error_category="worker_crash")
    assert finish_server(observer, result) is result
    report = observer.report()
    assert report.outcome == "failed"
    assert report.instrumentation == "incomplete"
    assert "lock_and_reconcile_elapsed" not in {metric.name for metric in report.metrics}
    assert next(metric for metric in report.metrics if metric.name == "publication_elapsed").reason == "not_reached"


def test_lexical_published_plan_is_projected_and_refusal_has_no_zero_measurement() -> None:
    observer = ResourceObserver(_monotonic_ns=iter((0, 5)).__next__, _process_time_ns=iter((0, 1)).__next__)
    begin(observer, "lexical_build", "postgresql")
    note_lexical_limits(
        observer, max_projected_files=4, max_aggregate_input_bytes=5,
        max_input_artifact_bytes=6, max_projected_file_bytes=7,
        max_chunk_lines=8, max_chunk_bytes=9, statement_timeout_ms=10,
    )
    plan = SimpleNamespace(aggregate_input_bytes=11, aggregate_projected_bytes=12, documents=(1, 2), omissions=(3,))
    result = SimpleNamespace(result="published", plan=plan)
    assert finish_lexical(observer, result) is result
    report = observer.report()
    values = {metric.name: metric.value for metric in report.metrics}
    assert values["lexical_input_bytes"] == 11
    assert values["lexical_documents"] == 2
    assert all(limit.applies_this_call is True for limit in report.limits)
    assert next(
        limit for limit in report.limits if limit.name == "lexical_build_statement_timeout"
    ).enforcement == "database_statement_timeout"
