"""Contract tests for the bounded, detached resource-view records."""

from __future__ import annotations

import json

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
    first["metrics"][0]["value"] = 99  # type: ignore[index]
    second = report.to_payload()
    assert second["metrics"][0]["value"] == 24  # type: ignore[index]
    encoded = json.dumps(second, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    assert len(encoded) <= 8192
    assert all(isinstance(key, str) for key in second)


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


def test_report_rejects_backend_mismatch_or_partial_unbegun_shape() -> None:
    with pytest.raises(ValueError):
        ResourceReport(SCHEMA, None, "sqlite", "not_recorded", Instrumentation.INCOMPLETE)
    with pytest.raises(ValueError):
        ResourceReport(SCHEMA, "local_refresh", "postgresql", "not_recorded", Instrumentation.INCOMPLETE)


def test_not_recorded_is_valid_for_every_begun_operation() -> None:
    report = ResourceReport(
        SCHEMA, "compact_context", None, "not_recorded", Instrumentation.INCOMPLETE
    )
    assert report.outcome == "not_recorded"


def test_duplicate_slots_are_rejected() -> None:
    metric = ResourceMetric.measured("actual_bytes", 1, Unit.BYTES, Basis.LEDGER_COUNTER)
    with pytest.raises(ValueError):
        ResourceReport(
            SCHEMA, "compact_context", "sqlite", "complete", Instrumentation.COMPLETE,
            (metric, metric),
        )
