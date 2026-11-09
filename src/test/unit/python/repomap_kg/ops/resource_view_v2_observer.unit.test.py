"""v2 observer: explicit schema, sealing/worker notes, outcomes and the v1 guard."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from common_lore_index.artifacts._sealing_meter import SealingMeter, SealingPlanFacts
from common_lore_index.artifacts.sealing_governance import SealingBudget, SealingBudgetExceeded
from common_lore_index.coordinator._usage_reaper import WorkerResourceUsage
from common_lore_index.ops._portable_governance import (
    BUDGET_REQUIRES_SCHEMA_2, require_budget_schema, seal_with_meter, start_sealing_meter, usage_kwargs,
)
from common_lore_index.ops.resource_reports._codec import decode_report, encode_report
from common_lore_index.ops.resource_view import (
    ResourceObserver, begin, end_stage, finish_local, mark, note_lexical_limits, note_sealing_budget,
    note_sealing_meter, note_sealing_refusal, note_worker_launch, note_worker_usage,
)
from common_lore_index.ops.resource_view._contracts_v2 import SCHEMA_V2, ResourceReportV2
from common_lore_index.ops.resource_view._projections import finish_lexical, finish_server


def _payload(observer: ResourceObserver) -> dict[str, Any]:
    report = observer.report()
    assert decode_report(encode_report(report)) == report
    return report.to_payload()


def _row(payload: dict, name: str, key: str = "metrics") -> dict:
    return next(item for item in payload[key] if item["name"] == name)


def _v2() -> ResourceObserver:
    return ResourceObserver(report_schema=SCHEMA_V2)


def test_schema_selection_is_explicit_and_validated() -> None:
    assert ResourceObserver().report_schema == "cloe-resource-view-v1"
    with pytest.raises(ValueError):
        ResourceObserver(report_schema="cloe-resource-view-v3")
    assert type(_v2().report()) is ResourceReportV2


def test_v1_observers_ignore_v2_notes_and_keep_the_absent_sealing_limit() -> None:
    observer = ResourceObserver()
    begin(observer, "local_refresh", "sqlite")
    note_sealing_budget(observer, SealingBudget(max_opens=3))
    note_sealing_meter(observer, SealingMeter(None, governed=False))
    payload: dict[str, Any] = observer.report().to_payload()
    assert payload["instrumentation"] != "degraded"
    assert payload["limits"][-1] == {
        "name": "sealing_io_limit", "value": None, "unit": "bytes", "enforcement": "absent",
        "applies_this_call": None,
    }


def test_budget_with_a_v1_observer_is_refused_before_any_work() -> None:
    with pytest.raises(ValueError, match=BUDGET_REQUIRES_SCHEMA_2):
        require_budget_schema(ResourceObserver(), SealingBudget(max_opens=1))
    with pytest.raises(ValueError, match=BUDGET_REQUIRES_SCHEMA_2):
        start_sealing_meter(ResourceObserver(), SealingBudget(max_opens=1))
    assert require_budget_schema(ResourceObserver(), SealingBudget()) is None
    assert require_budget_schema(None, SealingBudget(max_opens=1)) == SealingBudget(max_opens=1)
    assert start_sealing_meter(None, None) is None and start_sealing_meter(ResourceObserver(), None) is None
    assert usage_kwargs(None) == usage_kwargs(ResourceObserver()) == {}
    assert usage_kwargs(_v2()) == {"collect_usage": True}


def test_a_v1_observer_subclass_with_a_budget_is_refused_too() -> None:
    class Derived(ResourceObserver):
        pass

    with pytest.raises(ValueError, match=BUDGET_REQUIRES_SCHEMA_2):
        require_budget_schema(Derived(), SealingBudget(max_opens=1))
    budget = SealingBudget(max_opens=1)
    assert require_budget_schema(Derived(report_schema=SCHEMA_V2), budget) == budget
    assert require_budget_schema(SimpleNamespace(report_schema="x"), budget) == budget, (
        "a non-observer emits no v1 report, so it has nothing to misreport"
    )


def test_seal_with_meter_forwards_only_when_metered_and_closes_on_success() -> None:
    assert seal_with_meter(None, None, lambda **kwargs: kwargs) == {}
    meter = SealingMeter(None, governed=False)
    assert seal_with_meter(None, meter, lambda **kwargs: kwargs) == {"io_meter": meter}
    assert meter.closed
    refused = SealingMeter(SealingBudget(max_opens=0), governed=True)
    observer = _v2()
    begin(observer, "server_refresh", "postgresql")
    note_sealing_meter(observer, refused)
    with pytest.raises(SealingBudgetExceeded):
        seal_with_meter(observer, refused, lambda io_meter: io_meter.admit_open())
    assert not refused.closed and observer._sealing_refusal is not None


def _local_success(observer: ResourceObserver, meter: SealingMeter, usage: object) -> None:
    begin(observer, "local_refresh", "sqlite")
    note_sealing_budget(observer, meter.budget)
    mark(observer, "lock_and_reconcile")
    end_stage(observer, "lock_and_reconcile")
    mark(observer, "capture")
    note_sealing_meter(observer, meter)
    meter.admit_open()
    meter.close()
    note_worker_launch(observer, SimpleNamespace(max_artifact_bytes=1, max_bundle_bytes=2),
                       SimpleNamespace(process_deadline_seconds=3))
    note_worker_usage(observer, usage)
    end_stage(observer, "capture")
    finish_local(observer, SimpleNamespace(reconciled=False))


def test_published_local_v2_report_carries_exact_meter_and_worker_rows() -> None:
    observer = _v2()
    usage = WorkerResourceUsage(5000, 2000, 4096, "wait4_platform_defined", "wait4_platform_defined", None, 0, None)
    _local_success(observer, SealingMeter(None, governed=False), usage)
    payload = _payload(observer)
    assert (payload["schema"], payload["outcome"], payload["instrumentation"]) == (SCHEMA_V2, "published", "complete")
    assert len(payload["metrics"]) == 31 and len(payload["limits"]) == 14
    assert _row(payload, "sealing_opens") == {
        "name": "sealing_opens", "value": 1, "unit": "count", "availability": "measured",
        "basis": "call_meter_exact", "reason": None,
    }
    assert _row(payload, "planned_min_read_bytes")["reason"] == "not_selected"
    assert _row(payload, "worker_cpu")["value"] == 7000 and _row(payload, "worker_launches")["value"] == 1
    assert _row(payload, "worker_group_members_after_reap")["value"] == 0
    assert _row(payload, "sealing_max_read_bytes", "limits")["enforcement"] == "absent"
    assert _row(payload, "classification_max_retained_chars", "limits")["applies_this_call"] is False
    assert _row(payload, "stable_capture_max_attempts", "limits")["applies_this_call"] is True


def test_governed_budget_rows_report_the_effective_entry_ceiling() -> None:
    observer = _v2()
    budget = SealingBudget(max_read_bytes=10**6)
    meter = SealingMeter(budget, governed=True)
    meter.note_plan(SealingPlanFacts(1, 2, 30, 0))
    _local_success(observer, meter, WorkerResourceUsage.unavailable("platform_unsupported"))
    payload = _payload(observer)
    assert _row(payload, "sealing_max_read_bytes", "limits")["value"] == 10**6
    entries = _row(payload, "sealing_max_directory_entries", "limits")
    assert (entries["value"], entries["enforcement"], entries["applies_this_call"]) == (
        100_000, "call_budget_pre_io", True,
    )
    # Accepted planned lower bound is 4S+1 for the S=30 inventory (no longer 6S+1).
    assert _row(payload, "planned_min_read_bytes")["value"] == 4 * 30 + 1 == 121
    assert _row(payload, "planned_inventory_bytes")["basis"] == "metadata_inventory"
    assert _row(payload, "worker_cpu")["reason"] == "platform_unsupported"
    assert _row(payload, "inventory_max_artifacts", "limits")["applies_this_call"] is True


def test_local_refusal_is_refused_with_partial_meter_rows_and_no_worker() -> None:
    observer = _v2()
    budget = SealingBudget(max_opens=0)
    begin(observer, "local_refresh", "sqlite")
    note_sealing_budget(observer, budget)
    mark(observer, "capture")
    meter = SealingMeter(budget, governed=True)
    note_sealing_meter(observer, meter)
    with pytest.raises(SealingBudgetExceeded) as raised:
        meter.admit_open()
    note_sealing_refusal(observer, raised.value)
    payload = _payload(observer)
    assert (payload["outcome"], payload["instrumentation"]) == ("refused", "incomplete")
    assert _row(payload, "sealing_opens")["basis"] == "call_meter_partial"
    assert _row(payload, "worker_launches")["value"] == 0
    assert _row(payload, "worker_cpu")["reason"] == "not_started"


def test_local_replay_marks_sealing_and_worker_not_started_and_budgets_not_applied() -> None:
    observer = _v2()
    begin(observer, "local_refresh", "sqlite")
    note_sealing_budget(observer, SealingBudget(max_write_bytes=9))
    mark(observer, "lock_and_reconcile")
    end_stage(observer, "lock_and_reconcile")
    finish_local(observer, SimpleNamespace(reconciled=True))
    payload = _payload(observer)
    assert (payload["outcome"], payload["instrumentation"]) == ("reconciled_replay", "complete")
    assert {_row(payload, name)["reason"] for name in ("sealing_read_bytes", "worker_launches", "planned_inventory_files")} == {"not_started"}
    assert _row(payload, "sealing_max_write_bytes", "limits")["applies_this_call"] is False


def test_server_refused_requires_category_not_started_and_a_noted_refusal() -> None:
    def server(category: str, state: str, *, refused: bool) -> str:
        observer = _v2()
        begin(observer, "server_refresh", "postgresql")
        mark(observer, "capture")
        meter = SealingMeter(SealingBudget(max_opens=0), governed=True)
        note_sealing_meter(observer, meter)
        if refused:
            with pytest.raises(SealingBudgetExceeded) as raised:
                meter.admit_open()
            note_sealing_refusal(observer, raised.value)
        finish_server(observer, SimpleNamespace(result="failure", publication_state=state, error_category=category))
        return _payload(observer)["outcome"]

    assert server("resource_budget_exceeded", "not_started", refused=True) == "refused"
    assert server("resource_budget_exceeded", "not_started", refused=False) == "failed"
    assert server("worker_crash", "not_started", refused=True) == "failed", "a later cleanup failure stays failed"
    assert server("publication_unknown", "commit_unknown", refused=True) == "commit_unknown"
    assert server("cancelled", "not_started", refused=True) == "cancelled"


def test_mismatched_or_repeated_notes_degrade_without_raising() -> None:
    observer = _v2()
    begin(observer, "local_refresh", "sqlite")
    note_sealing_meter(observer, SealingMeter(None, governed=False))
    note_sealing_refusal(observer, SealingBudgetExceeded("opens"))  # the meter never refused
    payload = _payload(observer)
    assert payload["instrumentation"] == "degraded"
    assert {item["reason"] for item in payload["metrics"]} == {"observer_failed"}
    assert all(item["applies_this_call"] is None for item in payload["limits"])
    late = _v2()
    begin(late, "local_refresh", "sqlite")
    note_worker_usage(late, WorkerResourceUsage.unavailable("not_observed"))  # no launch was noted
    assert late.report().instrumentation == "degraded"


def test_lexical_operations_keep_v1_tables_under_the_v2_schema() -> None:
    observer = _v2()
    begin(observer, "lexical_build", "postgresql")
    note_lexical_limits(observer, max_projected_files=1, max_aggregate_input_bytes=2, max_input_artifact_bytes=3,
                        max_projected_file_bytes=4, max_chunk_lines=5, max_chunk_bytes=6, statement_timeout_ms=7)
    note_sealing_meter(observer, SealingMeter(None, governed=False))  # not a refresh: degrades
    finish_lexical(observer, SimpleNamespace(result="refused", plan=None))
    report = observer.report()
    assert type(report) is ResourceReportV2 and report.operation == "lexical_build"
    clean = _v2()
    begin(clean, "lexical_build", "postgresql")
    finish_lexical(clean, SimpleNamespace(result="refused", plan=None))
    payload = _payload(clean)
    assert payload["schema"] == SCHEMA_V2 and payload["outcome"] == "refused" and len(payload["metrics"]) == 6
