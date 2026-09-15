from __future__ import annotations

from dataclasses import dataclass
from threading import Event, Thread

import psycopg
import pytest

from scale28_backend_observer_session import (
    BackendMonitorError,
    BackendObserverSession,
    ObserverFailureBoundary,
    ObserverSessionState,
)
from scale28_observer_deadlines import ObserverDeadlinePolicy


_BOUNDARIES = (
    ObserverFailureBoundary.STARTUP_SUMMARY,
    ObserverFailureBoundary.ACTIVE_SUMMARY,
    ObserverFailureBoundary.EVENT_APPLY,
    ObserverFailureBoundary.RESOURCE_READ,
    ObserverFailureBoundary.TERMINAL_WAIT,
)
_SYNTHETIC_DEADLINE_POLICY = ObserverDeadlinePolicy(
    server_statement_timeout_ms=10,
    client_cancel_after_seconds=0.02,
    cancel_request_timeout_seconds=0.01,
    caller_operation_timeout_seconds=0.05,
)


@dataclass(frozen=True, slots=True)
class _CloseSchedule:
    trigger: str
    cancellation: str
    completion: str
    ordering: str

    @property
    def case_id(self) -> str:
        return "-".join(
            (
                self.trigger,
                self.cancellation,
                self.completion,
                self.ordering,
            )
        )


_TIMER_SCHEDULES = tuple(
    _CloseSchedule("timer", cancellation, completion, ordering)
    for cancellation in ("success", "timeout", "transport_failure")
    for completion in ("natural_return", "connector_error")
    for ordering in ("cancel_before_operation", "operation_before_cancel")
)
_LOCAL_CLOSE_SCHEDULES = tuple(
    _CloseSchedule("local_close", cancellation, "natural_return", ordering)
    for cancellation in ("success", "timeout", "transport_failure")
    for ordering in ("cancel_before_operation", "operation_before_cancel")
)
_SETTLEMENT_SCHEDULES = (
    _CloseSchedule(
        "settlement_timeout",
        "timeout",
        "natural_return",
        "cancel_before_operation",
    ),
    _CloseSchedule(
        "settlement_timeout",
        "transport_failure",
        "connector_error",
        "cancel_before_operation",
    ),
)
_SCHEDULES = (
    _TIMER_SCHEDULES + _LOCAL_CLOSE_SCHEDULES + _SETTLEMENT_SCHEDULES
)
_CASES = tuple(
    pytest.param(
        boundary,
        schedule,
        id=f"{boundary.value}-{schedule.case_id}",
    )
    for boundary in _BOUNDARIES
    for schedule in _SCHEDULES
)


class _Observer:
    def register_connection(self, _connection: object) -> None:
        return None


class _Connection:
    def __init__(self, schedule: _CloseSchedule, release: Event) -> None:
        self.broken = False
        self.closed = False
        self.close_count = 0
        self.close_while_active = False
        self.cancel_attempted = Event()
        self.cancel_returned = Event()
        self.allow_cancel_return = Event()
        self._schedule = schedule
        self._release = release
        self.session: BackendObserverSession | None = None

    def cancel_safe(self, *, timeout: float) -> None:
        assert timeout > 0
        self.cancel_attempted.set()
        try:
            assert self.allow_cancel_return.wait(1.0)
            if self._schedule.cancellation == "success":
                self._release.set()
                return
            if self._schedule.cancellation == "timeout":
                raise psycopg.errors.CancellationTimeout(
                    "bounded cancellation timeout"
                )
            raise OSError("bounded cancellation transport failure")
        finally:
            self.cancel_returned.set()

    def close(self) -> None:
        if self.session is not None:
            self.close_while_active |= self.session.snapshot().operation_in_flight
        self.close_count += 1
        self.closed = True


def _active_session(connection: _Connection) -> BackendObserverSession:
    session = BackendObserverSession(
        observer_factory=_Observer,
        connection_factory=lambda: connection,
        failure_causality=None,
        child_released=lambda: True,
        deadline_policy=_SYNTHETIC_DEADLINE_POLICY,
    )
    connection.session = session
    session.open(1)
    session.mark_startup_validated()
    session.activate_and_release(lambda: None)
    return session


def _operation(
    schedule: _CloseSchedule,
    started: Event,
    release: Event,
):
    def run(_observer: object, _connection: object) -> str:
        started.set()
        assert release.wait(1.0)
        if schedule.completion == "connector_error":
            raise OSError("observer connector operation failed")
        return "settled"

    return run


@pytest.mark.parametrize(("boundary", "schedule"), _CASES)
def test_one_hundred_distinct_close_under_use_orderings(
    boundary: ObserverFailureBoundary,
    schedule: _CloseSchedule,
) -> None:
    release = Event()
    started = Event()
    connection = _Connection(schedule, release)
    session = _active_session(connection)
    operation_failures: list[BaseException] = []
    close_failures: list[BaseException] = []
    operation_finished = Event()

    def run_operation() -> None:
        try:
            session.run(
                boundary,
                _operation(schedule, started, release),
                allowed_states=(ObserverSessionState.ACTIVE,),
                timeout_seconds=0.15,
            )
        except BaseException as error:
            operation_failures.append(error)
        finally:
            operation_finished.set()

    def close_session(timeout_seconds: float) -> None:
        try:
            session.close(timeout_seconds=timeout_seconds)
        except BaseException as error:
            close_failures.append(error)

    operation_thread = Thread(target=run_operation)
    operation_thread.start()
    close_thread = None
    try:
        assert started.wait(1.0)
        if schedule.trigger != "timer":
            close_thread = Thread(
                target=close_session,
                args=(0.05 if schedule.trigger == "settlement_timeout" else 0.5,),
            )
            close_thread.start()

        assert connection.cancel_attempted.wait(1.0)
        assert session.snapshot().operation_in_flight is True
        assert connection.closed is False

        if schedule.ordering == "cancel_before_operation":
            connection.allow_cancel_return.set()
        else:
            release.set()
            assert operation_finished.wait(1.0)
            assert session.snapshot().operation_in_flight is False
            connection.allow_cancel_return.set()
        assert connection.cancel_returned.wait(1.0)

        if schedule.trigger == "settlement_timeout":
            assert close_thread is not None
            close_thread.join(1.0)
            assert close_thread.is_alive() is False
            assert len(close_failures) == 1
            close_error = close_failures[0]
            assert isinstance(close_error, BackendMonitorError)
            assert close_error.observer_boundary is (
                ObserverFailureBoundary.SETTLEMENT_TIMEOUT
            )
            assert connection.close_count == 0
            assert session.snapshot().operation_in_flight is True
            release.set()
        elif schedule.cancellation != "success":
            release.set()

        operation_thread.join(1.0)
        assert operation_thread.is_alive() is False
        assert len(operation_failures) == 1
        operation_error = operation_failures[0]
        assert isinstance(operation_error, BackendMonitorError)
        assert operation_error.observer_boundary is (
            ObserverFailureBoundary.OPERATION_EXECUTION_TIMEOUT
        )
        expected_limitation = {
            "success": None,
            "timeout": "cancellation_timeout",
            "transport_failure": "cancellation_failure",
        }[schedule.cancellation]
        actual_limitation = operation_error.observer_cancellation_limitation
        assert (
            None if actual_limitation is None else actual_limitation.value
        ) == (
            None
            if schedule.ordering == "operation_before_cancel"
            else expected_limitation
        )
        expected_outcome = {
            "success": "request_succeeded",
            "timeout": "request_timed_out",
            "transport_failure": "request_failed",
        }[schedule.cancellation]
        assert session.snapshot().cancellation.request_outcome.value == (
            expected_outcome
        )

        if schedule.trigger == "timer":
            session.close()
        elif schedule.trigger == "local_close":
            assert close_thread is not None
            close_thread.join(1.0)
            assert close_thread.is_alive() is False
            assert close_failures == []
        else:
            session.close()

        session.close()
        snapshot = session.snapshot()
        assert snapshot.operation_in_flight is False
        assert snapshot.cancellation.operation_settled is True
        assert snapshot.cancellation.close_eligible is True
        assert connection.close_count == 1
        assert connection.close_while_active is False
    finally:
        release.set()
        operation_thread.join(1.0)
        if close_thread is not None:
            close_thread.join(1.0)
        if not connection.closed:
            session.close()


def test_close_schedule_matrix_has_one_hundred_unique_semantic_cases() -> None:
    assert len(_SCHEDULES) == 20
    assert len({schedule.case_id for schedule in _SCHEDULES}) == 20
    assert len(_CASES) == 100
