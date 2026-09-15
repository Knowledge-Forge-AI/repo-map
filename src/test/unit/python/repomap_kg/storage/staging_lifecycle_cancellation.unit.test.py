from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from typing import TypeAlias

import pytest

from repomap_kg.storage.staging_observability import (
    StagingMeasurementCategory,
    StagingMeasurementEvent,
    StagingMeasurements,
)
from repomap_kg.storage.staging_operation_events import StagingOperationEvent
from repomap_kg.storage.staging_phase_events import StagingPhaseEvent


_LifecycleEvent: TypeAlias = StagingOperationEvent | StagingPhaseEvent


def _measurements(
    lifecycle: str,
    sink: Callable[[_LifecycleEvent], None],
    *,
    measurement_sink: Callable[[StagingMeasurementEvent], None] | None = None,
    monotonic_ns: Callable[[], int] = time.monotonic_ns,
) -> StagingMeasurements:
    m = measurement_sink or (lambda _e: None)
    p_sink: Callable[[StagingPhaseEvent], None] | None = sink if lifecycle == "phase" else None
    o_sink: Callable[[StagingOperationEvent], None] | None = sink if lifecycle != "phase" else None
    return StagingMeasurements(m, phase_sink=p_sink, operation_sink=o_sink, monotonic_ns=monotonic_ns)


def _scope(
    measurements: StagingMeasurements,
    lifecycle: str,
) -> AbstractContextManager[None]:
    if lifecycle == "phase":
        return measurements.phase("refresh.observation_spool_cleanup")
    return measurements.operation("guard.source_index_stage")


def _event_count(measurements: StagingMeasurements, lifecycle: str) -> int:
    return measurements.phase_event_count if lifecycle == "phase" else measurements.operation_event_count


def _categories(events: Sequence[_LifecycleEvent]) -> list[str]:
    return [event.event_category.value for event in events]


@pytest.mark.parametrize("lifecycle", ("phase", "operation"))
@pytest.mark.parametrize("boundary", ("start_accepted", "body_returned"))
def test_lifecycle_boundary_interrupt_emits_one_cancelled_terminal(
    lifecycle: str,
    boundary: str,
) -> None:
    events: list[_LifecycleEvent] = []
    measurements = _measurements(lifecycle, events.append)
    body_entered = False

    def interrupt_at_boundary(current_lifecycle: str, current_boundary: str) -> None:
        if (current_lifecycle, current_boundary) == (lifecycle, boundary):
            raise KeyboardInterrupt

    setattr(measurements, "_lifecycle_checkpoint", interrupt_at_boundary)

    with pytest.raises(KeyboardInterrupt):
        with _scope(measurements, lifecycle):
            body_entered = True

    assert body_entered is (boundary == "body_returned")
    assert _categories(events) == ["started", "cancelled"]


@pytest.mark.parametrize("lifecycle", ("phase", "operation"))
def test_acknowledged_start_interrupt_emits_one_cancelled_terminal(
    lifecycle: str,
) -> None:
    events: list[_LifecycleEvent] = []

    def interrupt_after_acceptance(event: _LifecycleEvent) -> None:
        events.append(event)
        if event.event_category.value == "started":
            raise KeyboardInterrupt

    measurements = _measurements(lifecycle, interrupt_after_acceptance)

    with pytest.raises(KeyboardInterrupt):
        with _scope(measurements, lifecycle):
            pytest.fail("lifecycle body must not start")

    assert _categories(events) == ["started", "cancelled"]


@pytest.mark.parametrize("inner_lifecycle", ("phase", "operation"))
def test_nested_accepted_start_interrupt_closes_outer_refresh(
    inner_lifecycle: str,
) -> None:
    phase_events: list[StagingPhaseEvent] = []
    operation_events: list[StagingOperationEvent] = []
    measurements = StagingMeasurements(
        lambda _event: None, phase_sink=phase_events.append, operation_sink=operation_events.append,
    )
    accepted_phase_starts = 0

    def interrupt_at_inner_start(lifecycle: str, boundary: str) -> None:
        nonlocal accepted_phase_starts
        if boundary != "start_accepted" or lifecycle != inner_lifecycle:
            return
        if lifecycle == "phase":
            accepted_phase_starts += 1
            if accepted_phase_starts < 2:
                return
        raise KeyboardInterrupt

    setattr(measurements, "_lifecycle_checkpoint", interrupt_at_inner_start)
    inner_scope = (
        measurements.phase("staging.family_copy.files")
        if inner_lifecycle == "phase"
        else measurements.operation("guard.source_index_stage")
    )

    with pytest.raises(KeyboardInterrupt):
        with measurements.phase("refresh.total"):
            with inner_scope:
                pytest.fail("inner lifecycle body must not start")

    assert _categories(phase_events) == (
        ["started", "started", "cancelled", "cancelled"]
        if inner_lifecycle == "phase" else ["started", "cancelled"]
    )
    assert _categories(operation_events) == (
        [] if inner_lifecycle == "phase" else ["started", "cancelled"]
    )


@pytest.mark.parametrize("lifecycle", ("phase", "operation"))
@pytest.mark.parametrize(
    ("raised", "terminal"),
    (
        (None, "completed"),
        (RuntimeError("boom"), "failed"),
        (KeyboardInterrupt(), "cancelled"),
    ),
)
def test_lifecycle_body_exit_emits_exactly_one_classified_terminal(
    lifecycle: str,
    raised: BaseException | None,
    terminal: str,
) -> None:
    events: list[_LifecycleEvent] = []
    measurements = _measurements(lifecycle, events.append)

    if raised is None:
        with _scope(measurements, lifecycle):
            pass
    else:
        with pytest.raises(type(raised)):
            with _scope(measurements, lifecycle):
                raise raised

    assert _categories(events) == ["started", terminal]


@pytest.mark.parametrize("lifecycle", ("phase", "operation"))
def test_acknowledged_terminal_interrupt_does_not_emit_second_terminal(
    lifecycle: str,
) -> None:
    events: list[_LifecycleEvent] = []

    def interrupt_after_terminal_acceptance(event: _LifecycleEvent) -> None:
        events.append(event)
        if event.event_category.value == "completed":
            raise KeyboardInterrupt

    measurements = _measurements(lifecycle, interrupt_after_terminal_acceptance)

    with pytest.raises(KeyboardInterrupt):
        with _scope(measurements, lifecycle):
            pass

    assert _categories(events) == ["started", "completed"]


@pytest.mark.parametrize("lifecycle", ("phase", "operation"))
def test_unaccepted_start_suppresses_terminal_after_observer_failure(
    lifecycle: str,
) -> None:
    attempted_categories: list[str] = []

    def reject(event: _LifecycleEvent) -> None:
        attempted_categories.append(event.event_category.value)
        raise OSError("observer unavailable")

    measurements = _measurements(lifecycle, reject)

    with _scope(measurements, lifecycle):
        pass

    assert attempted_categories == ["started"]
    assert measurements.failed is True


@pytest.mark.parametrize("lifecycle", ("phase", "operation"))
def test_interrupt_before_start_sink_call_emits_no_terminal(
    lifecycle: str,
) -> None:
    events: list[_LifecycleEvent] = []
    called_count = 0

    def interrupting_monotonic() -> int:
        nonlocal called_count
        called_count += 1
        if called_count >= 2:
            raise KeyboardInterrupt
        return 1_000_000

    measurements = _measurements(
        lifecycle, events.append, monotonic_ns=interrupting_monotonic
    )

    with pytest.raises(KeyboardInterrupt):
        with _scope(measurements, lifecycle):
            pass

    assert events == []


@pytest.mark.parametrize("lifecycle", ("phase", "operation"))
@pytest.mark.parametrize("boundary", ("terminal_selected", "terminal_prepared"))
def test_pre_sink_finalizer_interrupt_still_emits_one_cancelled_terminal(
    lifecycle: str,
    boundary: str,
) -> None:
    events: list[_LifecycleEvent] = []
    measurements = _measurements(lifecycle, events.append)
    interrupted = False

    def interrupt_once(current_lifecycle: str, current_boundary: str) -> None:
        nonlocal interrupted
        if interrupted:
            return
        if (current_lifecycle, current_boundary) == (lifecycle, boundary):
            interrupted = True
            raise KeyboardInterrupt

    setattr(measurements, "_lifecycle_checkpoint", interrupt_once)

    with pytest.raises(KeyboardInterrupt):
        with _scope(measurements, lifecycle):
            pass

    assert interrupted is True
    assert _categories(events) == ["started", "cancelled"]


@pytest.mark.parametrize("lifecycle", ("phase", "operation"))
def test_pre_sink_finalizer_interrupt_preserves_contiguous_sequences(
    lifecycle: str,
) -> None:
    events: list[_LifecycleEvent] = []
    measurements = _measurements(lifecycle, events.append)
    interrupted = False

    def interrupt_once(current_lifecycle: str, current_boundary: str) -> None:
        nonlocal interrupted
        if interrupted or current_boundary != "terminal_selected":
            return
        interrupted = True
        raise KeyboardInterrupt

    setattr(measurements, "_lifecycle_checkpoint", interrupt_once)

    with pytest.raises(KeyboardInterrupt):
        with _scope(measurements, lifecycle):
            pass

    assert _event_count(measurements, lifecycle) == 2
    assert [event.attempt_local_sequence for event in events] == [1, 1]


@pytest.mark.parametrize("lifecycle", ("phase", "operation"))
def test_cancelled_terminal_sink_interrupt_is_not_retried(
    lifecycle: str,
) -> None:
    attempted: list[str] = []
    def interrupt_inside_terminal_sink(event: _LifecycleEvent) -> None:
        attempted.append(event.event_category.value)
        if event.event_category.value == "cancelled":
            raise KeyboardInterrupt

    measurements = _measurements(lifecycle, interrupt_inside_terminal_sink)

    with pytest.raises(KeyboardInterrupt):
        with _scope(measurements, lifecycle):
            raise KeyboardInterrupt

    assert attempted == ["started", "cancelled"]


@pytest.mark.parametrize("lifecycle", ("phase", "operation"))
def test_broken_terminal_transport_is_not_retried(
    lifecycle: str,
) -> None:
    attempted: list[str] = []
    def reject_terminal(event: _LifecycleEvent) -> None:
        attempted.append(event.event_category.value)
        if event.event_category.value != "started":
            raise OSError("observer transport broken")

    measurements = _measurements(lifecycle, reject_terminal)

    with _scope(measurements, lifecycle):
        pass

    assert attempted == ["started", "completed"]
    assert measurements.failed is True


def test_measurement_exhaustion_preserves_nested_lifecycle_terminals() -> None:
    phase_events: list[StagingPhaseEvent] = []
    operation_events: list[StagingOperationEvent] = []
    measurements = StagingMeasurements(
        lambda _event: None, phase_sink=phase_events.append,
        operation_sink=operation_events.append, event_limit=2,
    )

    with pytest.raises(KeyboardInterrupt):
        with measurements.phase("refresh.total"):
            with measurements.operation("guard.source_index_stage"):
                measurements.record_bytes(StagingMeasurementCategory.CLIENT_MEMORY, 1)
                measurements.record_bytes(StagingMeasurementCategory.CLIENT_MEMORY, 2)
                measurements.record_bytes(StagingMeasurementCategory.CLIENT_MEMORY, 3)
                assert measurements.failed is True
                raise KeyboardInterrupt

    assert _categories(operation_events) == ["started", "cancelled"]
    assert _categories(phase_events) == ["started", "cancelled"]


@pytest.mark.parametrize("lifecycle", ("phase", "operation"))
def test_measurement_sink_rejection_preserves_lifecycle_terminal(
    lifecycle: str,
) -> None:
    events: list[_LifecycleEvent] = []
    def reject_measurement(_event: object) -> None:
        raise OSError("measurement observer unavailable")

    measurements = _measurements(lifecycle, events.append, measurement_sink=reject_measurement)

    with pytest.raises(KeyboardInterrupt):
        with _scope(measurements, lifecycle):
            measurements.record_bytes(StagingMeasurementCategory.CLIENT_MEMORY, 1)
            assert measurements.failed is True
            raise KeyboardInterrupt

    assert _categories(events) == ["started", "cancelled"]


@pytest.mark.parametrize("lifecycle", ("phase", "operation"))
def test_repeated_finalizer_interrupts_fail_closed_without_duplicate_terminal(
    lifecycle: str,
) -> None:
    events: list[_LifecycleEvent] = []
    measurements = _measurements(lifecycle, events.append)

    def always_interrupt(current_lifecycle: str, current_boundary: str) -> None:
        if current_boundary == "terminal_selected":
            raise KeyboardInterrupt

    setattr(measurements, "_lifecycle_checkpoint", always_interrupt)

    with pytest.raises(KeyboardInterrupt):
        with _scope(measurements, lifecycle):
            pass

    assert _categories(events) == ["started"]


@pytest.mark.parametrize("lifecycle", ("phase", "operation"))
def test_acknowledged_start_interrupt_increments_event_count(
    lifecycle: str,
) -> None:
    events: list[_LifecycleEvent] = []

    def interrupt_after_start_acceptance(event: _LifecycleEvent) -> None:
        events.append(event)
        if event.event_category.value == "started":
            raise KeyboardInterrupt

    measurements = _measurements(lifecycle, interrupt_after_start_acceptance)

    with pytest.raises(KeyboardInterrupt):
        with _scope(measurements, lifecycle):
            pass

    assert _event_count(measurements, lifecycle) == 2
    assert _categories(events) == ["started", "cancelled"]
