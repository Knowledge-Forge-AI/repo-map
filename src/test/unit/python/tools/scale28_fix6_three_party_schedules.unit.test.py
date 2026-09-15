from __future__ import annotations

from itertools import product
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


_SCHEDULE_POLICY = ObserverDeadlinePolicy(
    server_statement_timeout_ms=10,
    client_cancel_after_seconds=0.02,
    cancel_request_timeout_seconds=0.08,
    caller_operation_timeout_seconds=0.12,
)
_ALL_SCHEDULES = tuple(
    product(
        ("operation_first", "request_first"),
        ("success", "request_timeout", "transport_failure"),
        ("before_first_settlement", "after_first_settlement"),
        ("wait_for_both", "timeout_then_retry"),
    )
)
_THREE_PARTY_SCHEDULES = _ALL_SCHEDULES[:20]
assert len(_THREE_PARTY_SCHEDULES) == 20


class _Observer:
    def register_connection(self, _connection: object) -> None:
        return None


class _BarrierConnection:
    def __init__(self, request_outcome: str) -> None:
        self.broken = False
        self.closed = False
        self.close_count = 0
        self.close_under_use = False
        self.request_outcome = request_outcome
        self.cancel_started = Event()
        self.allow_cancel_return = Event()
        self.cancel_finished = Event()
        self.session: BackendObserverSession | None = None

    def cancel_safe(self, *, timeout: float) -> None:
        assert timeout == pytest.approx(0.08)
        self.cancel_started.set()
        assert self.allow_cancel_return.wait(1.0)
        try:
            if self.request_outcome == "request_timeout":
                raise psycopg.errors.CancellationTimeout(
                    "bounded cancellation timeout"
                )
            if self.request_outcome == "transport_failure":
                raise OSError("bounded cancellation transport failure")
        finally:
            self.cancel_finished.set()

    def close(self) -> None:
        assert self.session is not None
        snapshot = self.session.snapshot()
        self.close_under_use |= (
            snapshot.operation_in_flight
            or snapshot.cancellation.request_in_flight
        )
        self.close_count += 1
        self.closed = True


def _active_session(
    connection: _BarrierConnection,
) -> BackendObserverSession:
    session = BackendObserverSession(
        observer_factory=_Observer,
        connection_factory=lambda: connection,
        failure_causality=None,
        child_released=lambda: True,
        deadline_policy=_SCHEDULE_POLICY,
    )
    connection.session = session
    session.open(1)
    session.mark_startup_validated()
    session.activate_and_release(lambda: None)
    return session


@pytest.mark.parametrize(
    (
        "settlement_order",
        "request_outcome",
        "close_start",
        "close_mode",
    ),
    _THREE_PARTY_SCHEDULES,
)
def test_twenty_timer_request_operation_and_close_schedules(
    settlement_order: str,
    request_outcome: str,
    close_start: str,
    close_mode: str,
) -> None:
    connection = _BarrierConnection(request_outcome)
    session = _active_session(connection)
    operation_started = Event()
    allow_operation_return = Event()
    operation_finished = Event()
    operation_failures: list[BaseException] = []
    close_failures: list[BaseException] = []

    def operation(_observer: object, _connection: object) -> str:
        operation_started.set()
        assert allow_operation_return.wait(1.0)
        return "settled"

    def run_operation() -> None:
        try:
            session.run(
                ObserverFailureBoundary.ACTIVE_SUMMARY,
                operation,
                allowed_states=(ObserverSessionState.ACTIVE,),
                timeout_seconds=0.12,
            )
        except BaseException as error:
            operation_failures.append(error)
        finally:
            operation_finished.set()

    close_timeout = 0.01 if close_mode == "timeout_then_retry" else 0.5

    def close_session() -> None:
        try:
            session.close(timeout_seconds=close_timeout)
        except BaseException as error:
            close_failures.append(error)

    operation_thread = Thread(target=run_operation)
    close_thread = Thread(target=close_session)
    operation_thread.start()
    try:
        assert operation_started.wait(1.0)
        assert connection.cancel_started.wait(1.0)

        if close_start == "before_first_settlement":
            close_thread.start()

        if settlement_order == "operation_first":
            allow_operation_return.set()
            assert operation_finished.wait(1.0)
            assert session.snapshot().cancellation.request_in_flight is True
        else:
            connection.allow_cancel_return.set()
            assert connection.cancel_finished.wait(1.0)
            assert session.snapshot().operation_in_flight is True

        if close_start == "after_first_settlement":
            close_thread.start()

        if close_mode == "timeout_then_retry":
            close_thread.join(1.0)
            assert close_thread.is_alive() is False
            assert len(close_failures) == 1
            assert isinstance(close_failures[0], BackendMonitorError)
            assert close_failures[0].observer_boundary is (
                ObserverFailureBoundary.SETTLEMENT_TIMEOUT
            )
        else:
            assert close_thread.is_alive() is True
        assert connection.close_count == 0

        if settlement_order == "operation_first":
            connection.allow_cancel_return.set()
            assert connection.cancel_finished.wait(1.0)
        else:
            allow_operation_return.set()
            assert operation_finished.wait(1.0)

        close_thread.join(1.0)
        assert close_thread.is_alive() is False
        if close_mode == "timeout_then_retry":
            session.close(timeout_seconds=0.5)

        assert len(operation_failures) == 1
        assert isinstance(operation_failures[0], BackendMonitorError)
        assert connection.close_count == 1
        assert connection.close_under_use is False
        snapshot = session.snapshot()
        assert snapshot.cancellation.operation_settled is True
        assert snapshot.cancellation.request_in_flight is False
        assert snapshot.cancellation.close_eligible is True
    finally:
        allow_operation_return.set()
        connection.allow_cancel_return.set()
        operation_thread.join(1.0)
        if close_thread.ident is not None:
            close_thread.join(1.0)
        if not connection.closed:
            session.close()
