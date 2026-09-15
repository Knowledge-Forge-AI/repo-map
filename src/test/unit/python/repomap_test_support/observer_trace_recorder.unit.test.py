from dataclasses import replace

import pytest

from repomap_test_support.observer_trace import (
    ObserverCaller,
    ObserverTraceEvidenceError,
    ObserverTraceKind,
    ObserverTraceRecorder,
    reconcile_terminal_counts,
)


def test_trace_is_bounded_ordered_and_uses_monotonic_nanoseconds() -> None:
    ticks = iter((10, 20, 30))
    recorder = ObserverTraceRecorder(max_events=3, clock_ns=lambda: next(ticks))

    recorder.record(ObserverTraceKind.RUN_CALL_ENTRY, caller=ObserverCaller.UNKNOWN)
    recorder.record(ObserverTraceKind.CALLBACK_DISPATCH)
    recorder.record(ObserverTraceKind.CALLBACK_RETURN)

    snapshot = recorder.snapshot()
    assert [event.sequence for event in snapshot.events] == [1, 2, 3]
    assert [event.monotonic_ns for event in snapshot.events] == [10, 20, 30]


def test_trace_overflow_fails_closed_without_discarding_existing_events() -> None:
    recorder = ObserverTraceRecorder(max_events=1)
    recorder.record(ObserverTraceKind.RUN_CALL_ENTRY)
    recorder.record(ObserverTraceKind.CALLBACK_DISPATCH)

    with pytest.raises(ObserverTraceEvidenceError, match="overflow"):
        recorder.snapshot()
    assert recorder.retained_event_count == 1


def test_trace_disabled_records_nothing() -> None:
    recorder = ObserverTraceRecorder(enabled=False)
    recorder.record(ObserverTraceKind.RUN_CALL_ENTRY)

    assert recorder.snapshot().events == ()


def test_private_values_cannot_be_serialized() -> None:
    recorder = ObserverTraceRecorder()

    recorder.record(ObserverTraceKind.RUN_CALL_ENTRY, detail="password=private")

    with pytest.raises(ObserverTraceEvidenceError, match="closed vocabulary"):
        recorder.snapshot()


@pytest.mark.parametrize(
    "events, message",
    (
        ((ObserverTraceKind.CALLBACK_RETURN,), "callback completion"),
        ((ObserverTraceKind.CANCELLATION_OUTCOME,), "cancellation outcome"),
        ((ObserverTraceKind.REQUEST_SETTLEMENT,), "request settlement"),
        ((ObserverTraceKind.OPERATION_SETTLEMENT,), "operation settlement"),
    ),
)
def test_anti_inflation_rejects_impossible_event_sequences(events, message) -> None:
    recorder = ObserverTraceRecorder()
    for kind in events:
        recorder.record(kind, operation_id=1, session_token="session-1")

    with pytest.raises(ObserverTraceEvidenceError, match=message):
        recorder.snapshot()


def test_anti_inflation_rejects_negative_duration() -> None:
    recorder = ObserverTraceRecorder()
    recorder.record(
        ObserverTraceKind.RUN_CALL_ENTRY,
        operation_id=1,
        session_token="session-1",
        generation=1,
        duration_ns=-1,
    )
    with pytest.raises(ObserverTraceEvidenceError, match="negative duration"):
        recorder.snapshot()


def test_anti_inflation_rejects_mixed_generations() -> None:
    recorder = ObserverTraceRecorder()
    recorder.record(
        ObserverTraceKind.RUN_CALL_ENTRY,
        operation_id=1,
        session_token="session-1",
        generation=1,
    )
    recorder.record(
        ObserverTraceKind.CALLBACK_DISPATCH,
        operation_id=1,
        session_token="session-1",
        generation=2,
    )

    with pytest.raises(ObserverTraceEvidenceError, match="mixes generations"):
        recorder.snapshot()


def test_anti_inflation_rejects_fabricated_owner() -> None:
    recorder = ObserverTraceRecorder()
    recorder.record(
        ObserverTraceKind.RUN_CALL_ENTRY,
        operation_id=1,
        session_token="session-1",
    )
    recorder.record(
        ObserverTraceKind.RUN_CALL_ENTRY,
        operation_id=2,
        session_token="session-1",
        active_owner_operation_id=99,
    )

    with pytest.raises(ObserverTraceEvidenceError, match="fabricated"):
        recorder.snapshot()


def test_anti_inflation_rejects_reused_operation_trace() -> None:
    recorder = ObserverTraceRecorder()
    recorder.record(
        ObserverTraceKind.RUN_CALL_ENTRY,
        operation_id=1,
        session_token="session-1",
    )
    recorder.record(
        ObserverTraceKind.RUN_CALL_ENTRY,
        operation_id=1,
        session_token="session-2",
    )

    with pytest.raises(ObserverTraceEvidenceError, match="operation trace"):
        recorder.snapshot()


def test_snapshot_validation_rejects_mutated_event_sequence() -> None:
    recorder = ObserverTraceRecorder(clock_ns=iter((10, 20)).__next__)
    recorder.record(ObserverTraceKind.RUN_CALL_ENTRY)
    recorder.record(ObserverTraceKind.CALLBACK_DISPATCH)
    snapshot = recorder.snapshot()
    mutated = replace(snapshot, events=(snapshot.events[1], snapshot.events[0]))

    with pytest.raises(ObserverTraceEvidenceError, match="event sequence"):
        mutated.validate()


def test_snapshot_validation_rejects_nonmonotonic_timestamp() -> None:
    recorder = ObserverTraceRecorder(clock_ns=iter((10, 20)).__next__)
    recorder.record(ObserverTraceKind.RUN_CALL_ENTRY)
    recorder.record(ObserverTraceKind.CALLBACK_DISPATCH)
    snapshot = recorder.snapshot()
    mutated = replace(
        snapshot,
        events=(
            replace(snapshot.events[0], monotonic_ns=30),
            replace(snapshot.events[1], monotonic_ns=20),
        ),
    )

    with pytest.raises(ObserverTraceEvidenceError, match="not monotonic"):
        mutated.validate()


def test_terminal_counts_are_disjoint_and_reconcile() -> None:
    counts = reconcile_terminal_counts(
        attempted=15,
        terminally_classified=15,
        published=12,
        failed=3,
        unclassified_or_interrupted=0,
    )

    assert counts.terminally_classified == counts.published + counts.failed
    with pytest.raises(ObserverTraceEvidenceError, match="reconcile"):
        reconcile_terminal_counts(
            attempted=15,
            terminally_classified=15,
            published=13,
            failed=3,
            unclassified_or_interrupted=0,
        )
