from __future__ import annotations

from dataclasses import replace

import pytest

from repomap_test_support.scale28_fix10_preparation_trace import (
    CLOSED_EVENTS,
    POSTGRES_RESOURCE_CODES,
    PUBLIC_AGGREGATE_FIELDS,
    ClockDomain,
    EvidenceKind,
    TraceCondition,
    TraceContractError,
    TraceEvent,
    compare_durations,
    expected_clock_domain,
    validate_aggregate_fields,
    validate_trace,
)


def _parent(event: str, attempt: int, sequence: int) -> TraceEvent:
    return TraceEvent(
        event,
        attempt,
        sequence,
        ClockDomain.PARENT_MONOTONIC,
    )


def _worker(event: str, attempt: int, sequence: int) -> TraceEvent:
    return TraceEvent(
        event,
        attempt,
        sequence,
        ClockDomain.WORKER_LOCAL_DURATION,
    )


_VALID = (
    _parent("attempt_authority_created", 1, 0),
    _parent("attempt_deadline_started", 1, 1),
    _parent("process_spawn_requested", 1, 2),
    _worker("worker_entry", 1, 0),
    _worker("request_received", 1, 1),
    _worker("pgdata_walk_started", 1, 2),
    _worker("pgdata_walk_completed", 1, 3),
    _worker("postgres_resource_read_started:temporary_bytes", 1, 4),
    _worker("postgres_resource_read_completed:temporary_bytes", 1, 5),
    _parent("attempt_cleanup_started", 1, 3),
    _parent("attempt_cleanup_completed", 1, 4),
)


def test_fix10_trace_manifest_is_closed_and_repository_consistent() -> None:
    assert len(TraceCondition) == 6
    assert POSTGRES_RESOURCE_CODES == ("temporary_bytes", "wal_bytes")
    assert "attempt_deadline_started" in CLOSED_EVENTS
    assert "attempt_cleanup_completed" in CLOSED_EVENTS
    assert len(PUBLIC_AGGREGATE_FIELDS) == 21


def test_fix10_trace_accepts_local_order_without_comparing_clocks() -> None:
    validate_trace(_VALID)
    validate_aggregate_fields(tuple(sorted(PUBLIC_AGGREGATE_FIELDS)))


@pytest.mark.parametrize(
    "events",
    (
        _VALID + (replace(_VALID[0], sequence=5),),
        _VALID[:-1],
        (replace(_VALID[0], event="private_path"),) + _VALID[1:],
        (
            replace(
                _VALID[0],
                clock_domain=ClockDomain.WORKER_LOCAL_DURATION,
            ),
        )
        + _VALID[1:],
        (replace(_VALID[0], evidence_kind=EvidenceKind.EXPECTED),)
        + _VALID[1:],
        (replace(_VALID[1], sequence=0),) + _VALID[1:],
        (replace(_VALID[0], attempt=3),) + _VALID[1:],
    ),
)
def test_fix10_trace_rejects_closed_schema_violations(
    events: tuple[TraceEvent, ...],
) -> None:
    with pytest.raises(TraceContractError):
        validate_trace(events)


def test_fix10_trace_rejects_attempt_two_before_cleanup() -> None:
    events = _VALID + (
        _parent("attempt_authority_created", 2, 4),
        _parent("attempt_cleanup_completed", 2, 5),
    )
    with pytest.raises(
        TraceContractError,
        match="attempt two begins before attempt-one cleanup",
    ):
        validate_trace(events)


def test_fix10_trace_accepts_attempt_two_after_cleanup() -> None:
    events = _VALID + (
        _parent("attempt_authority_created", 2, 5),
        _parent("attempt_cleanup_completed", 2, 6),
    )
    validate_trace(events)


def test_fix10_trace_rejects_cross_process_absolute_comparison() -> None:
    with pytest.raises(TraceContractError, match="cross-process"):
        compare_durations(
            ClockDomain.PARENT_MONOTONIC,
            ClockDomain.WORKER_LOCAL_DURATION,
        )


def test_fix10_trace_allows_same_domain_duration_comparison() -> None:
    compare_durations(
        ClockDomain.WORKER_LOCAL_DURATION,
        ClockDomain.WORKER_LOCAL_DURATION,
    )


def test_fix10_trace_rejects_private_aggregate_field() -> None:
    with pytest.raises(TraceContractError, match="private"):
        validate_aggregate_fields(("database_name",))


@pytest.mark.parametrize("event", tuple(sorted(CLOSED_EVENTS)))
def test_fix10_every_closed_event_has_exact_clock_owner(event: str) -> None:
    assert expected_clock_domain(event) in ClockDomain
