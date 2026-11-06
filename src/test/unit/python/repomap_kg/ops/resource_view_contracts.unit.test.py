"""Contract tests for the bounded, detached resource-view records."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import pytest

from common_lore_index.ops.resource_view import (
    Availability, Basis, Instrumentation, ResourceLimit, ResourceMetric, ResourceReport,
    SCHEMA, Unit, UnavailableReason,
)


def test_metric_and_limit_vocabularies_reject_open_values() -> None:
    with pytest.raises(ValueError):
        ResourceMetric.measured("made_up_metric", 1, Unit.COUNT, Basis.LEDGER_COUNTER)
    with pytest.raises(ValueError):
        ResourceMetric("actual_bytes", 1, Unit.BYTES, "maybe", Basis.LEDGER_COUNTER)
    with pytest.raises(ValueError):
        ResourceLimit("budget_bytes", 1, Unit.BYTES, "soft", True)


def test_unavailable_metric_requires_reason_and_no_value() -> None:
    with pytest.raises(ValueError):
        ResourceMetric("actual_bytes", 1, Unit.BYTES, Availability.UNAVAILABLE, Basis.LEDGER_COUNTER)
    with pytest.raises(ValueError):
        ResourceMetric("actual_bytes", None, Unit.BYTES, Availability.UNAVAILABLE, Basis.LEDGER_COUNTER)
    metric = ResourceMetric.unavailable(
        "actual_bytes", Unit.BYTES, Basis.LEDGER_COUNTER, UnavailableReason.NOT_REACHED
    )
    assert metric.value is None and metric.reason == "not_reached"


def test_non_absent_limit_requires_a_value() -> None:
    with pytest.raises(ValueError):
        ResourceLimit("budget_bytes", None, Unit.BYTES, "owner_enforced", True)


def test_report_payload_is_primitive_bounded_and_detached() -> None:
    metric = ResourceMetric.measured("actual_bytes", 24, Unit.BYTES, Basis.LEDGER_COUNTER)
    report = ResourceReport(
        SCHEMA, "compact_context", "sqlite", "complete", Instrumentation.COMPLETE, (metric,),
    )
    first = report.to_payload()
    first_metrics = first["metrics"]
    assert isinstance(first_metrics, list) and isinstance(first_metrics[0], dict)
    first_metrics[0]["value"] = 99
    second = report.to_payload()
    second_metrics = second["metrics"]
    assert isinstance(second_metrics, list) and isinstance(second_metrics[0], dict)
    assert second_metrics[0]["value"] == 24
    encoded = json.dumps(second, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    assert len(encoded) <= 8192
    assert set(second) == {
        "schema", "operation", "backend", "outcome", "instrumentation", "metrics", "limits",
    }

    def assert_primitives(value: object) -> None:
        if isinstance(value, dict):
            assert all(isinstance(key, str) for key in value)
            for nested in value.values():
                assert_primitives(nested)
        elif isinstance(value, list):
            for nested in value:
                assert_primitives(nested)
        else:
            assert value is None or isinstance(value, (bool, int, str))

    assert_primitives(second)


def test_closed_records_enforce_nonnegative_values_and_fixed_slot_bounds() -> None:
    with pytest.raises(ValueError):
        ResourceMetric.measured("actual_bytes", -1, Unit.BYTES, Basis.LEDGER_COUNTER)
    with pytest.raises(ValueError):
        ResourceMetric.measured("actual_bytes", True, Unit.BYTES, Basis.LEDGER_COUNTER)
    with pytest.raises(ValueError):
        ResourceLimit("budget_bytes", -1, Unit.BYTES, "owner_enforced", True)
    invalid_applicability: Any = 1
    with pytest.raises(ValueError):
        ResourceLimit("budget_bytes", 1, Unit.BYTES, "owner_enforced", invalid_applicability)

    metric_names = (
        "operation_elapsed", "operation_process_cpu", "lock_and_reconcile_elapsed",
        "capture_elapsed", "validation_elapsed", "publication_elapsed",
        "sealed_manifest_files", "sealed_manifest_bytes", "validated_bundle_records",
        "validated_bundle_bytes", "worker_cpu", "worker_peak_rss", "lexical_input_bytes",
        "lexical_projected_bytes", "lexical_documents", "lexical_omissions",
        "config_revalidations_executed", "logical_read_units", "sql_statements_executed",
        "scan_units_executed", "seed_expansions_executed", "candidate_rows_scanned",
        "evidence_rows_scanned", "elapsed_ms", "actual_bytes",
    )
    metrics = tuple(
        ResourceMetric.measured(name, 1, Unit.COUNT, Basis.LEDGER_COUNTER)
        for name in metric_names
    )
    with pytest.raises(ValueError, match="fixed bound"):
        ResourceReport(
            SCHEMA, "compact_context", "sqlite", "complete", Instrumentation.COMPLETE,
            metrics=metrics,
        )

    limit_names = (
        "worker_process_deadline", "worker_max_artifact_bytes", "worker_max_bundle_bytes",
        "manifest_max_artifacts", "manifest_max_total_bytes", "sealing_io_limit",
        "max_projected_files", "max_aggregate_input_bytes", "max_input_artifact_bytes",
        "max_projected_file_bytes", "max_chunk_lines", "max_chunk_bytes",
        "lexical_build_statement_timeout", "max_logical_read_units", "max_sql_statements",
        "max_scan_units", "max_seed_expansions",
    )
    limits = tuple(
        ResourceLimit(name, 1, Unit.COUNT, "owner_enforced", True)
        for name in limit_names
    )
    with pytest.raises(ValueError, match="fixed bound"):
        ResourceReport(
            SCHEMA, "compact_context", "sqlite", "complete", Instrumentation.COMPLETE,
            limits=limits,
        )


def test_unbegun_shape_allows_null_operation_and_backend() -> None:
    report = ResourceReport(SCHEMA, None, None, "not_recorded", Instrumentation.INCOMPLETE)
    assert report.to_payload() == {
        "schema": SCHEMA,
        "operation": None,
        "backend": None,
        "outcome": "not_recorded",
        "instrumentation": "incomplete",
        "metrics": [],
        "limits": [],
    }


@pytest.mark.parametrize("field,value", [
    ("name", "private-canary"), ("unit", "private-canary"),
    ("availability", "private-canary"), ("basis", "private-canary"),
    ("basis", None), ("value", 1.5), ("reason", "not_observed"),
])
def test_measured_metric_rejects_open_or_ambiguous_data_without_echoing_it(
    field: str, value: Any,
) -> None:
    metric = ResourceMetric.measured("actual_bytes", 0, Unit.BYTES, Basis.LEDGER_COUNTER)
    with pytest.raises(ValueError) as error:
        replace(metric, **{field: value})
    assert "private-canary" not in str(error.value)


@pytest.mark.parametrize("operation,backend,outcome", [
    (None, "sqlite", "not_recorded"),
    (None, None, "published"),
    ("local_refresh", "postgresql", "published"),
    ("server_refresh", "sqlite", "committed"),
    ("lexical_build", "sqlite", "published"),
    ("local_refresh", "sqlite", "failed"),
    ("lexical_build", "postgresql", "committed"),
])
def test_report_cannot_misattribute_backend_or_publication_outcome(
    operation: str | None, backend: str | None, outcome: str,
) -> None:
    with pytest.raises(ValueError):
        ResourceReport(SCHEMA, operation, backend, outcome, Instrumentation.COMPLETE)


@pytest.mark.parametrize("field,value", [
    ("schema", "private-canary"), ("operation", "private-canary"),
    ("backend", "private-canary"), ("outcome", "private-canary"),
    ("instrumentation", "private-canary"), ("metrics", []), ("limits", []),
    ("metrics", (object(),)), ("limits", (object(),)),
])
def test_report_rejects_untyped_or_open_payload_records(field: str, value: Any) -> None:
    report = ResourceReport(SCHEMA, "compact_context", "sqlite", "complete", Instrumentation.COMPLETE)
    with pytest.raises(ValueError) as error:
        replace(report, **{field: value})
    assert "private-canary" not in str(error.value)


def test_report_refuses_duplicate_slots_and_oversized_primitive_payload() -> None:
    metric = ResourceMetric.measured("actual_bytes", 0, Unit.BYTES, Basis.LEDGER_COUNTER)
    limit = ResourceLimit("budget_bytes", 4096, Unit.BYTES, "owner_enforced", True)
    report = ResourceReport(SCHEMA, "compact_context", "sqlite", "complete", Instrumentation.COMPLETE)
    with pytest.raises(ValueError, match="metric slot repeated"):
        replace(report, metrics=(metric, metric))
    with pytest.raises(ValueError, match="limit slot repeated"):
        replace(report, limits=(limit, limit))
    huge = 10**3000
    metrics = tuple(ResourceMetric.measured(name, huge, Unit.BYTES, Basis.LEDGER_COUNTER)
        for name in ("actual_bytes", "sealed_manifest_bytes", "validated_bundle_bytes"))
    with pytest.raises(ValueError, match="8192"):
        replace(report, metrics=metrics)


def test_not_recorded_is_valid_for_every_begun_operation() -> None:
    report = ResourceReport(
        SCHEMA, "compact_context", None, "not_recorded", Instrumentation.INCOMPLETE
    )
    assert report.outcome == "not_recorded"
