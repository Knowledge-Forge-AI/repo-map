from __future__ import annotations

import json

import pytest

from repomap_kg.storage.staging_family_contracts import STAGING_FAMILY_DESCRIPTORS
from repomap_kg.storage.staging_observability import (
    StagingMeasurementCategory,
    StagingMeasurementEvent,
    StagingMeasurementUnit,
)
from repomap_kg.storage.staging_phase_events import (
    StagingPhaseEvent,
    StagingPhaseEventCategory,
)
from repomap_test_support.performance_baseline import (
    ClosedSpan,
    PerformanceEvidenceError,
    QuerySummary,
    QueryWorkload,
    close_phase_spans,
    critical_path_ns,
    exclusive_wall_ns,
    interval_union_ns,
    measurement_index,
    nearest_rank,
    overhead_summary,
    public_baseline_projection,
    reconcile_copy_rows,
    reconcile_families,
    reconcile_replays,
    require_output_equivalence,
    spool_threshold_decision,
    work_sum_ns,
)


def _events(code: str = "refresh.total", *, duration: int = 10):
    return (
        StagingPhaseEvent.started(code, 1, 5),
        StagingPhaseEvent.terminal(
            code,
            1,
            StagingPhaseEventCategory.COMPLETED,
            5 + duration,
            duration,
            duration // 2,
        ),
    )


def _span(code: str, sequence: int, start: int, finish: int) -> ClosedSpan:
    return ClosedSpan(code, sequence, start, finish, finish - start, 1, "completed")


def _family_events():
    events: list[StagingMeasurementEvent] = []
    for family in STAGING_FAMILY_DESCRIPTORS:
        events.extend(
            (
                StagingMeasurementEvent.measured(
                    StagingMeasurementCategory.FAMILY_ROW_COUNT,
                    value=2,
                    unit=StagingMeasurementUnit.ROWS,
                    family=family,
                ),
                StagingMeasurementEvent.measured(
                    StagingMeasurementCategory.NORMALIZED_BYTES,
                    value=20,
                    unit=StagingMeasurementUnit.BYTES,
                    family=family,
                ),
                StagingMeasurementEvent.unavailable(
                    StagingMeasurementCategory.SPOOL_BYTES,
                    unit=StagingMeasurementUnit.BYTES,
                    family=family,
                ),
                StagingMeasurementEvent.unavailable(
                    StagingMeasurementCategory.SPOOL_ALLOCATED_BYTES,
                    unit=StagingMeasurementUnit.BYTES,
                    family=family,
                ),
            )
        )
    return tuple(events)


def _equivalence():
    return {
        "source_input_digest": "opaque-a",
        "configuration_digest": "opaque-b",
        "extractor_digest": "opaque-c",
        "structural_digest": "opaque-d",
        "family_counts": {family: 1 for family in STAGING_FAMILY_DESCRIPTORS},
        "publication_state": "published",
    }


def _replay_events(rows: int = 12):
    events: list[StagingMeasurementEvent] = []
    for duration, row_count in (
        (
            StagingMeasurementCategory.OBSERVATION_FILE_REPLAY,
            StagingMeasurementCategory.OBSERVATION_FILE_REPLAY_ROWS,
        ),
        (
            StagingMeasurementCategory.OBSERVATION_CANONICALIZATION_REPLAY,
            StagingMeasurementCategory.OBSERVATION_CANONICALIZATION_REPLAY_ROWS,
        ),
        (
            StagingMeasurementCategory.OBSERVATION_RAW_REPLAY,
            StagingMeasurementCategory.OBSERVATION_RAW_REPLAY_ROWS,
        ),
    ):
        events.extend(
            (
                StagingMeasurementEvent.measured(
                    duration, value=5, unit=StagingMeasurementUnit.NANOSECONDS
                ),
                StagingMeasurementEvent.measured(
                    row_count, value=rows, unit=StagingMeasurementUnit.ROWS
                ),
            )
        )
    return tuple(events)


def test_one_span_success_closes_with_wall_and_cpu() -> None:
    assert close_phase_spans(_events()) == (
        ClosedSpan("refresh.total", 1, 5, 15, 10, 5, "completed"),
    )


def test_one_span_failure_is_retained() -> None:
    events = (
        StagingPhaseEvent.started("refresh.total", 1, 0),
        StagingPhaseEvent.terminal(
            "refresh.total", 1, StagingPhaseEventCategory.FAILED, 4, 4, 3
        ),
    )
    assert close_phase_spans(events)[0].outcome == "failed"


def test_duplicate_terminal_is_rejected() -> None:
    with pytest.raises(PerformanceEvidenceError, match="duplicate"):
        close_phase_spans((*_events(), _events()[1]))


def test_missing_terminal_is_evidence_loss() -> None:
    with pytest.raises(PerformanceEvidenceError, match="missing"):
        close_phase_spans((_events()[0],))


def test_nested_inclusive_exclusive_arithmetic() -> None:
    parent = _span("refresh.total", 1, 0, 20)
    child = _span("refresh.extraction", 2, 3, 8)
    assert exclusive_wall_ns(parent, (parent, child)) == 15


def test_overlapping_concurrent_spans_use_interval_union() -> None:
    spans = (_span("a", 1, 0, 10), _span("b", 2, 5, 15))
    assert work_sum_ns(spans) == 20
    assert critical_path_ns(spans) == 15


def test_queue_wait_and_execution_remain_distinct() -> None:
    assert work_sum_ns((_span("queue_wait", 1, 0, 3), _span("execution", 2, 3, 8))) == 8


@pytest.mark.parametrize("value", [-1, True, 1.5])
def test_nonnegative_exact_integer_fields(value) -> None:
    with pytest.raises(PerformanceEvidenceError):
        ClosedSpan("x", value, 0, 0, 0, 0, "completed")


def test_unknown_query_stage_is_rejected() -> None:
    with pytest.raises(ValueError):
        QuerySummary("unknown", 3, (1,), 1, 1, 1)  # type: ignore[arg-type]


def test_fabricated_zero_query_duration_is_rejected() -> None:
    with pytest.raises(PerformanceEvidenceError, match="fabricated"):
        QuerySummary(QueryWorkload.EXACT_CANONICAL_LOOKUP, 3, (0,), 1, 1, 1)


def test_child_outside_parent_is_not_subtracted() -> None:
    parent = _span("parent", 1, 10, 20)
    child = _span("child", 2, 0, 30)
    assert exclusive_wall_ns(parent, (parent, child)) == 10


def test_interval_rejects_inversion() -> None:
    with pytest.raises(PerformanceEvidenceError, match="inverted"):
        interval_union_ns(((2, 1),))


def test_counter_index_rejects_duplicate() -> None:
    event = _family_events()[0]
    with pytest.raises(PerformanceEvidenceError, match="duplicate"):
        measurement_index((event, event))


def test_counter_index_aggregates_repeated_merge_operation_timings() -> None:
    first = StagingMeasurementEvent.measured(
        StagingMeasurementCategory.SEMANTIC_GUARD,
        value=7,
        unit=StagingMeasurementUnit.NANOSECONDS,
    )
    second = StagingMeasurementEvent.measured(
        StagingMeasurementCategory.SEMANTIC_GUARD,
        value=11,
        unit=StagingMeasurementUnit.NANOSECONDS,
    )
    result = measurement_index((first, second))
    assert result[(StagingMeasurementCategory.SEMANTIC_GUARD.value, None)].value == 18


def test_family_reconciliation_covers_every_family() -> None:
    result = reconcile_families(measurement_index(_family_events()))
    assert set(result) == set(STAGING_FAMILY_DESCRIPTORS)
    assert {row["path"] for row in result.values()} == {"buffered"}


def test_missing_family_rows_are_rejected() -> None:
    with pytest.raises(PerformanceEvidenceError, match="missing"):
        reconcile_families(measurement_index(_family_events()[:-1]))


def test_copy_rows_reconcile_exactly() -> None:
    rows: dict[str, int] = {family: 2 for family in STAGING_FAMILY_DESCRIPTORS}
    reconcile_copy_rows(rows, rows)


def test_copy_rows_cannot_be_inferred_from_other_counts() -> None:
    rows: dict[str, int] = {family: 2 for family in STAGING_FAMILY_DESCRIPTORS}
    wrong = dict(rows)
    wrong["files"] = 1
    with pytest.raises(PerformanceEvidenceError, match="COPY"):
        reconcile_copy_rows(rows, wrong)


def test_exact_three_replay_consumers_reconcile() -> None:
    reconcile_replays(measurement_index(_replay_events()), 12)


def test_missing_replay_is_rejected() -> None:
    with pytest.raises(PerformanceEvidenceError, match="incomplete"):
        reconcile_replays(measurement_index(_replay_events()[:-1]), 12)


def test_nearest_rank_percentile_is_deterministic() -> None:
    assert nearest_rank((5, 1, 4, 2, 3), 95) == 5


def test_warmups_are_not_query_samples() -> None:
    summary = QuerySummary(QueryWorkload.PATH_PREFIX_LOOKUP, 3, (4, 5), 2, 20, 3)
    assert summary.to_public_payload()["measured_iterations"] == 2


def test_overhead_requires_all_three_pairs() -> None:
    with pytest.raises(PerformanceEvidenceError, match="three pairs"):
        overhead_summary((1, 2), (1, 2))


def test_overhead_keeps_outliers_and_reports_overlap() -> None:
    result = overhead_summary((100, 101, 500), (102, 103, 104))
    assert result["disabled_median_ns"] == 101
    assert result["ranges_overlap"] is True


def test_threshold_authorizes_from_current_measurements() -> None:
    result = spool_threshold_decision(spool_ns=10, pre_final_ns=100, total_refresh_ns=300)
    assert result["vdep2_r1_authorized"] is True


def test_threshold_does_not_accept_stale_estimate_fields() -> None:
    with pytest.raises(TypeError):
        spool_threshold_decision(  # type: ignore[call-arg]
            spool_ns=1, pre_final_ns=100, total_refresh_ns=100, stale_estimate=99
        )


def test_unavailable_metric_is_not_zero() -> None:
    result = reconcile_families(measurement_index(_family_events()))
    assert result["files"]["spool_logical_bytes"] is None


def test_output_equivalence_accepts_exact_published_state() -> None:
    require_output_equivalence(_equivalence(), _equivalence())


def test_semantic_mismatch_cannot_be_a_performance_result() -> None:
    changed = _equivalence()
    changed["structural_digest"] = "different"
    with pytest.raises(PerformanceEvidenceError, match="mismatch"):
        require_output_equivalence(_equivalence(), changed)


def test_public_projection_contains_only_closed_aggregates() -> None:
    query = QuerySummary(QueryWorkload.ONE_HOP_NEIGHBORHOOD, 3, (1, 2), 2, 10, 1)
    payload = public_baseline_projection(
        stages_ns={"refresh.total": 3},
        query_summaries=(query,),
        decision={"vdep2_r1_authorized": False},
    )
    rendered = json.dumps(payload, sort_keys=True)
    assert "filename" not in rendered and "canonical_key" not in rendered


def test_public_projection_rejects_path_like_stage() -> None:
    with pytest.raises(PerformanceEvidenceError, match="identity"):
        public_baseline_projection(
            stages_ns={"private_stage": 1}, query_summaries=(), decision={}
        )


def test_report_schema_is_stable() -> None:
    payload = public_baseline_projection(
        stages_ns={"refresh.total": 1}, query_summaries=(), decision={}
    )
    assert payload["schema"] == "repomap-performance-baseline-v1"
