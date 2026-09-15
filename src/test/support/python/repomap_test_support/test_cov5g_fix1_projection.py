"""Deterministic TEST-COV5G-FIX1 publication-order test support."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from threading import Event, Lock, Thread
from typing import Callable

import psycopg

from scale28_backend_observer_session import (
    BackendMonitorError,
    BackendObserverSession,
    ObserverFailureBoundary,
    ObserverSessionSnapshot,
    ObserverSessionState,
)
from scale28_observer_deadlines import ObserverDeadlinePolicy


class PublicationOrder(str, Enum):
    """The owner result made externally visible first."""

    REQUEST_FIRST = "request_first"
    OPERATION_FIRST = "operation_first"


class RequestResult(str, Enum):
    """One terminal cancellation-request result."""

    SUCCESS = "success"
    TIMEOUT = "timeout"
    TRANSPORT_FAILURE = "transport_failure"


class ObservationPoint(str, Enum):
    """A deterministic point at which a snapshot or close begins."""

    BOTH_ACTIVE = "both_active"
    BETWEEN_RESULTS = "between_results"
    BOTH_TERMINAL = "both_terminal"


@dataclass(frozen=True, slots=True)
class ProjectionSchedule:
    """One distinct barrier schedule."""

    order: PublicationOrder
    request_result: RequestResult
    snapshot_at: ObservationPoint
    close_at: ObservationPoint
    close_before_snapshot: bool = False

    @property
    def case_id(self) -> str:
        """Return a stable semantic case identity."""

        return "-".join(
            (
                self.order.value,
                self.request_result.value,
                f"snapshot-{self.snapshot_at.value}",
                f"close-{self.close_at.value}",
                (
                    "close-before-snapshot"
                    if self.close_before_snapshot
                    else "snapshot-before-close"
                ),
            )
        )


@dataclass(frozen=True, slots=True)
class ProjectionObservation:
    """Public-safe immutable evidence from one schedule."""

    schedule: ProjectionSchedule
    sequence: tuple[str, ...]
    error: BackendMonitorError
    error_fields_before_later_publication: tuple[object, ...]
    error_fields_after_later_publication: tuple[object, ...]
    initial_snapshot: ObserverSessionSnapshot
    between_snapshot: ObserverSessionSnapshot
    terminal_snapshot: ObserverSessionSnapshot
    selected_snapshot: ObserverSessionSnapshot
    close_count: int
    close_while_active: bool


_POLICY = ObserverDeadlinePolicy(
    server_statement_timeout_ms=10,
    client_cancel_after_seconds=0.02,
    cancel_request_timeout_seconds=0.2,
    caller_operation_timeout_seconds=0.25,
)


class _Observer:
    def register_connection(self, _connection: object) -> None:
        return None


class _OrderedConnection:
    def __init__(
        self,
        request_result: RequestResult,
        sequence: Callable[[str], None],
    ) -> None:
        self.broken = False
        self.closed = False
        self.close_count = 0
        self.close_while_active = False
        self.request_started = Event()
        self.allow_request_result = Event()
        self.session: BackendObserverSession | None = None
        self._request_result = request_result
        self._sequence = sequence

    def cancel_safe(self, *, timeout: float) -> None:
        assert timeout > 0
        self._sequence("request_started")
        self.request_started.set()
        assert self.allow_request_result.wait(1.0)
        if self._request_result is RequestResult.SUCCESS:
            return
        if self._request_result is RequestResult.TIMEOUT:
            raise psycopg.errors.CancellationTimeout(
                "bounded cancellation timeout"
            )
        raise OSError("bounded cancellation transport failure")

    def close(self) -> None:
        if self.session is not None:
            snapshot = self.session.snapshot()
            self.close_while_active |= (
                snapshot.operation_in_flight
                or snapshot.cancellation.request_in_flight
            )
        self._sequence("connection_closed")
        self.close_count += 1
        self.closed = True


def projection_schedules() -> tuple[ProjectionSchedule, ...]:
    """Return all distinct order, result, snapshot, and close schedules."""

    return tuple(
        ProjectionSchedule(
            order,
            request_result,
            snapshot_at,
            close_at,
            close_before_snapshot,
        )
        for order in PublicationOrder
        for request_result in RequestResult
        for snapshot_at in ObservationPoint
        for close_at in ObservationPoint
        for close_before_snapshot in (False, True)
    )


def _error_fields(error: BackendMonitorError) -> tuple[object, ...]:
    return (
        error.category,
        error.observer_boundary,
        error.observer_timeout_mechanism,
        error.observer_cancellation_limitation,
        str(error),
    )


def _active_session(
    connection: _OrderedConnection,
) -> BackendObserverSession:
    def _create_connection() -> _OrderedConnection:
        return connection

    session = BackendObserverSession(
        observer_factory=_Observer,
        connection_factory=_create_connection,
        failure_causality=None,
        child_released=lambda: True,
        deadline_policy=_POLICY,
    )
    connection.session = session
    session.open(1)
    session.mark_startup_validated()
    session.activate_and_release(lambda: None)
    return session


def run_projection_schedule(
    schedule: ProjectionSchedule,
) -> ProjectionObservation:
    """Force one request/operation publication order without timing authority."""

    sequence_items: list[str] = []
    sequence_lock = Lock()

    def record(item: str) -> None:
        with sequence_lock:
            sequence_items.append(item)

    connection = _OrderedConnection(schedule.request_result, record)
    session = _active_session(connection)
    operation_started = Event()
    allow_operation_return = Event()
    operation_finished = Event()
    request_published = Event()
    close_invoked = Event()
    close_finished = Event()
    operation_failures: list[BaseException] = []
    close_failures: list[BaseException] = []

    original_record = session._record_cancellation_result

    def record_cancellation_result(
        operation_generation: int,
        error: Exception | None,
    ) -> None:
        original_record(operation_generation, error)
        record("request_published")
        request_published.set()

    setattr(session, "_record_cancellation_result", record_cancellation_result)

    def operation(_observer: object, _connection: object) -> str:
        record("operation_started")
        operation_started.set()
        assert allow_operation_return.wait(1.0)
        return "operation-returned"

    def run_operation() -> None:
        try:
            session.run(
                ObserverFailureBoundary.ACTIVE_SUMMARY,
                operation,
                allowed_states=(ObserverSessionState.ACTIVE,),
                timeout_seconds=0.25,
            )
        except BaseException as error:
            record("operation_published")
            operation_failures.append(error)
        finally:
            operation_finished.set()

    def close_session() -> None:
        close_invoked.set()
        try:
            session.close(timeout_seconds=1.0)
        except BaseException as error:
            close_failures.append(error)
        finally:
            close_finished.set()

    operation_thread = Thread(target=run_operation)
    close_thread = Thread(target=close_session)
    operation_thread.start()
    close_started = False
    selected_snapshot: ObserverSessionSnapshot | None = None

    def observe(point: ObservationPoint) -> ObserverSessionSnapshot:
        nonlocal close_started, selected_snapshot
        should_close = schedule.close_at is point and not close_started
        if should_close and schedule.close_before_snapshot:
            record(f"close_requested_{point.value}")
            close_thread.start()
            close_started = True
            assert close_invoked.wait(1.0)
        snapshot = session.snapshot()
        if schedule.snapshot_at is point:
            selected_snapshot = snapshot
            record(f"snapshot_{point.value}")
        if should_close and not schedule.close_before_snapshot:
            record(f"close_requested_{point.value}")
            close_thread.start()
            close_started = True
        return snapshot

    try:
        assert operation_started.wait(1.0)
        assert connection.request_started.wait(1.0)
        initial_snapshot = observe(ObservationPoint.BOTH_ACTIVE)

        if schedule.order is PublicationOrder.REQUEST_FIRST:
            connection.allow_request_result.set()
            assert request_published.wait(1.0)
            between_snapshot = observe(ObservationPoint.BETWEEN_RESULTS)
            allow_operation_return.set()
            assert operation_finished.wait(1.0)
            assert len(operation_failures) == 1
            error = operation_failures[0]
            assert isinstance(error, BackendMonitorError)
            fields_before = _error_fields(error)
        else:
            allow_operation_return.set()
            assert operation_finished.wait(1.0)
            assert len(operation_failures) == 1
            error = operation_failures[0]
            assert isinstance(error, BackendMonitorError)
            fields_before = _error_fields(error)
            between_snapshot = observe(ObservationPoint.BETWEEN_RESULTS)
            connection.allow_request_result.set()
            assert request_published.wait(1.0)

        terminal_snapshot = observe(ObservationPoint.BOTH_TERMINAL)
        fields_after = _error_fields(error)

        if not close_started:
            raise AssertionError("schedule did not start close")
        assert close_finished.wait(1.0)
        close_thread.join(1.0)
        operation_thread.join(1.0)
        assert close_thread.is_alive() is False
        assert operation_thread.is_alive() is False
        assert close_failures == []
        assert selected_snapshot is not None
        return ProjectionObservation(
            schedule=schedule,
            sequence=tuple(sequence_items),
            error=error,
            error_fields_before_later_publication=fields_before,
            error_fields_after_later_publication=fields_after,
            initial_snapshot=initial_snapshot,
            between_snapshot=between_snapshot,
            terminal_snapshot=terminal_snapshot,
            selected_snapshot=selected_snapshot,
            close_count=connection.close_count,
            close_while_active=connection.close_while_active,
        )
    finally:
        allow_operation_return.set()
        connection.allow_request_result.set()
        operation_thread.join(1.0)
        if close_started:
            close_thread.join(1.0)
        if not connection.closed:
            session.close()
