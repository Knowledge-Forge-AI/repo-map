"""Closed PERF-BASE1 event reconciliation and report arithmetic."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace

from repomap_test_support.performance_baseline_values import (
    ClosedSpan as ClosedSpan,
    PerformanceEvidenceError as PerformanceEvidenceError,
    QuerySummary as QuerySummary,
    QueryWorkload as QueryWorkload,
    _require_nonnegative_int as _require_nonnegative_int,
    _validate_interval as _validate_interval,
    nearest_rank as nearest_rank,
)

from repomap_kg.storage.staging_family_contracts import STAGING_FAMILY_DESCRIPTORS
from repomap_kg.storage.staging_observability import (
    StagingMeasurementAvailability,
    StagingMeasurementCategory,
    StagingMeasurementEvent,
)
from repomap_kg.storage.staging_operation_events import StagingOperationEvent
from repomap_kg.storage.staging_phase_events import (
    STAGING_PHASE_CODES,
    StagingPhaseEvent,
    StagingPhaseEventCategory,
)


def close_phase_spans(events: Sequence[StagingPhaseEvent]) -> tuple[ClosedSpan, ...]:
    starts: dict[int, StagingPhaseEvent] = {}
    closed: list[ClosedSpan] = []
    terminal_sequences: set[int] = set()
    for event in events:
        sequence = event.attempt_local_sequence
        if event.event_category is StagingPhaseEventCategory.STARTED:
            if sequence in starts or sequence in terminal_sequences:
                raise PerformanceEvidenceError("duplicate phase start")
            starts[sequence] = event
            continue
        if sequence in terminal_sequences:
            raise PerformanceEvidenceError("duplicate phase terminal")
        started = starts.pop(sequence, None)
        if started is None or started.phase_code != event.phase_code:
            raise PerformanceEvidenceError("phase terminal has no matching start")
        assert event.duration_ns is not None
        finish = event.monotonic_offset_ns
        start = started.monotonic_offset_ns
        closed.append(
            ClosedSpan(
                event.phase_code,
                sequence,
                start,
                finish,
                event.duration_ns,
                event.process_cpu_duration_ns,
                event.event_category.value,
            )
        )
        terminal_sequences.add(sequence)
    if starts:
        raise PerformanceEvidenceError("phase terminal evidence is missing")
    return tuple(sorted(closed, key=lambda span: span.sequence))


def validate_operation_terminals(events: Sequence[StagingOperationEvent]) -> None:
    starts: dict[int, str] = {}
    terminals: set[int] = set()
    for event in events:
        sequence = event.attempt_local_sequence
        if event.event_category.value == "started":
            if sequence in starts or sequence in terminals:
                raise PerformanceEvidenceError("duplicate operation start")
            starts[sequence] = event.operation_code
        else:
            if sequence in terminals or starts.pop(sequence, None) != event.operation_code:
                raise PerformanceEvidenceError("operation terminal is invalid")
            terminals.add(sequence)
    if starts:
        raise PerformanceEvidenceError("operation terminal evidence is missing")


def exclusive_wall_ns(span: ClosedSpan, spans: Sequence[ClosedSpan]) -> int:
    children = [
        (candidate.start_ns, candidate.finish_ns)
        for candidate in spans
        if candidate.sequence != span.sequence
        and span.start_ns <= candidate.start_ns
        and candidate.finish_ns <= span.finish_ns
    ]
    covered = interval_union_ns(children)
    if covered > span.wall_ns:
        raise PerformanceEvidenceError("child duration exceeds parent")
    return span.wall_ns - covered


def interval_union_ns(intervals: Iterable[tuple[int, int]]) -> int:
    ordered = sorted(intervals)
    if not ordered:
        return 0
    total = 0
    start, finish = ordered[0]
    _validate_interval(start, finish)
    for next_start, next_finish in ordered[1:]:
        _validate_interval(next_start, next_finish)
        if next_start <= finish:
            finish = max(finish, next_finish)
        else:
            total += finish - start
            start, finish = next_start, next_finish
    return total + finish - start


def work_sum_ns(spans: Sequence[ClosedSpan]) -> int:
    return sum(span.wall_ns for span in spans)


def critical_path_ns(spans: Sequence[ClosedSpan]) -> int:
    return interval_union_ns((span.start_ns, span.finish_ns) for span in spans)


def measurement_index(
    events: Sequence[StagingMeasurementEvent],
) -> dict[tuple[str, str | None], StagingMeasurementEvent]:
    result: dict[tuple[str, str | None], StagingMeasurementEvent] = {}
    for event in events:
        key = (event.category.value, event.family)
        if key in result:
            existing = result[key]
            if event.category not in {
                StagingMeasurementCategory.SEMANTIC_GUARD,
                StagingMeasurementCategory.MERGE,
            } or not isinstance(existing.value, int) or not isinstance(
                event.value, int
            ):
                raise PerformanceEvidenceError("duplicate measurement event")
            result[key] = replace(existing, value=existing.value + event.value)
            continue
        result[key] = event
    return result


def family_path(
    index: Mapping[tuple[str, str | None], StagingMeasurementEvent],
    family: str,
) -> str:
    event = index.get((StagingMeasurementCategory.SPOOL_BYTES.value, family))
    if event is None:
        raise PerformanceEvidenceError("family spool evidence is missing")
    return (
        "spooled"
        if event.availability is StagingMeasurementAvailability.MEASURED
        else "buffered"
    )


def reconcile_families(
    index: Mapping[tuple[str, str | None], StagingMeasurementEvent],
) -> dict[str, dict[str, int | str | None]]:
    result: dict[str, dict[str, int | str | None]] = {}
    for family in STAGING_FAMILY_DESCRIPTORS:
        row_event = _required(index, StagingMeasurementCategory.FAMILY_ROW_COUNT, family)
        logical = _required(index, StagingMeasurementCategory.NORMALIZED_BYTES, family)
        spool = _required(index, StagingMeasurementCategory.SPOOL_BYTES, family)
        allocated = _required(
            index, StagingMeasurementCategory.SPOOL_ALLOCATED_BYTES, family
        )
        if spool.availability is not allocated.availability:
            raise PerformanceEvidenceError("family spool availability differs")
        result[family] = {
            "path": family_path(index, family),
            "records": row_event.value,
            "logical_payload_bytes": logical.value,
            "spool_logical_bytes": spool.value,
            "spool_allocated_bytes": allocated.value,
        }
    return result


def reconcile_copy_rows(
    family_rows: Mapping[str, int], copy_rows: Mapping[str, int]
) -> None:
    if set(family_rows) != set(STAGING_FAMILY_DESCRIPTORS):
        raise PerformanceEvidenceError("family rows are incomplete")
    if dict(family_rows) != dict(copy_rows):
        raise PerformanceEvidenceError("COPY rows do not reconcile")


def reconcile_replays(
    index: Mapping[tuple[str, str | None], StagingMeasurementEvent],
    observation_count: int,
) -> None:
    _require_nonnegative_int(observation_count)
    pairs = (
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
    )
    for duration_category, rows_category in pairs:
        duration = index.get((duration_category.value, None))
        rows = index.get((rows_category.value, None))
        if (
            duration is None
            or rows is None
            or duration.availability is not StagingMeasurementAvailability.MEASURED
            or rows.value != observation_count
        ):
            raise PerformanceEvidenceError("observation replay set is incomplete")


def overhead_summary(
    disabled_ns: Sequence[int], enabled_ns: Sequence[int]
) -> dict[str, int | float | bool | str]:
    if len(disabled_ns) != 3 or len(enabled_ns) != 3:
        raise PerformanceEvidenceError("overhead campaign must retain three pairs")
    disabled = nearest_rank(disabled_ns, 50)
    enabled = nearest_rank(enabled_ns, 50)
    if disabled <= 0:
        raise PerformanceEvidenceError("disabled median is invalid")
    delta = enabled - disabled
    percent = delta * 100.0 / disabled
    overlap = max(min(disabled_ns), min(enabled_ns)) <= min(
        max(disabled_ns), max(enabled_ns)
    )
    return {
        "disabled_median_ns": disabled,
        "enabled_median_ns": enabled,
        "absolute_overhead_ns": delta,
        "overhead_percent": percent,
        "ranges_overlap": overlap,
        "interpretation": "within_measurement_noise" if overlap else "separated",
        "accepted": percent <= 3.0,
    }


def spool_threshold_decision(
    *, spool_ns: int, pre_final_ns: int, total_refresh_ns: int
) -> dict[str, float | bool]:
    for value in (spool_ns, pre_final_ns, total_refresh_ns):
        _require_nonnegative_int(value)
    if pre_final_ns == 0 or total_refresh_ns == 0:
        raise PerformanceEvidenceError("performance denominator is invalid")
    pre_final_share = spool_ns * 100.0 / pre_final_ns
    total_share = spool_ns * 100.0 / total_refresh_ns
    return {
        "spool_share_of_pre_final_percent": pre_final_share,
        "spool_share_of_total_refresh_percent": total_share,
        "vdep2_r1_authorized": pre_final_share >= 10.0 or total_share >= 5.0,
    }


def require_output_equivalence(
    disabled: Mapping[str, object], enabled: Mapping[str, object]
) -> None:
    required = {
        "source_input_digest",
        "configuration_digest",
        "extractor_digest",
        "structural_digest",
        "family_counts",
        "publication_state",
    }
    if set(disabled) != required or set(enabled) != required or disabled != enabled:
        raise PerformanceEvidenceError("semantic output mismatch")


def public_baseline_projection(
    *,
    stages_ns: Mapping[str, int],
    query_summaries: Sequence[QuerySummary],
    decision: Mapping[str, float | bool],
) -> dict[str, object]:
    for stage, value in stages_ns.items():
        if stage not in STAGING_PHASE_CODES:
            raise PerformanceEvidenceError("public stage identity is invalid")
        _require_nonnegative_int(value)
    return {
        "schema": "repomap-performance-baseline-v1",
        "stages_ns": dict(sorted(stages_ns.items())),
        "queries": [summary.to_public_payload() for summary in query_summaries],
        "decision": dict(decision),
    }


def _required(
    index: Mapping[tuple[str, str | None], StagingMeasurementEvent],
    category: StagingMeasurementCategory,
    family: str,
) -> StagingMeasurementEvent:
    event = index.get((category.value, family))
    if event is None:
        raise PerformanceEvidenceError("family measurement is missing")
    return event


__all__ = [
    "ClosedSpan",
    "PerformanceEvidenceError",
    "QuerySummary",
    "QueryWorkload",
    "close_phase_spans",
    "critical_path_ns",
    "exclusive_wall_ns",
    "family_path",
    "interval_union_ns",
    "measurement_index",
    "nearest_rank",
    "overhead_summary",
    "public_baseline_projection",
    "reconcile_copy_rows",
    "reconcile_families",
    "reconcile_replays",
    "require_output_equivalence",
    "spool_threshold_decision",
    "validate_operation_terminals",
    "work_sum_ns",
]
