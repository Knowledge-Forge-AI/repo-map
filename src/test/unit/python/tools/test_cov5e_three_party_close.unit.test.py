from __future__ import annotations

from itertools import product
from threading import Event, Lock, Thread

import psycopg
import pytest

import scale28_backend_observer_session as observer_session
from repomap_test_support.observer_schedule import ObserverSchedule

from scale28_backend_observer_session import (
    BackendMonitorError,
    BackendObserverSession,
    ObserverFailureBoundary,
    ObserverSessionState,
)
from scale28_observer_deadlines import ObserverDeadlinePolicy


_POLICY = ObserverDeadlinePolicy(
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
        (
            "readback_before_close",
            "readback_while_close_waits",
            "readback_after_both",
        ),
    )
)
_THREE_PARTY_SCHEDULES = _ALL_SCHEDULES[:50]
assert len(_THREE_PARTY_SCHEDULES) == 50
for _dimension in range(5):
    assert {case[_dimension] for case in _THREE_PARTY_SCHEDULES} == {
        case[_dimension] for case in _ALL_SCHEDULES
    }


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


class _FreshReadback:
    def __init__(
        self,
        live_connection: _BarrierConnection,
        trace: list[str],
        trace_lock: Lock,
    ) -> None:
        self._live_connection = live_connection
        self._trace = trace
        self._trace_lock = trace_lock
        self.open_count = 0
        self.read_count = 0
        self.close_count = 0
        self.live_closed_at_read: list[bool] = []

    def run(self) -> None:
        with self._trace_lock:
            self._trace.append("fresh_readback_started")
        self.open_count += 1
        self.read_count += 1
        self.live_closed_at_read.append(self._live_connection.closed)
        self.close_count += 1
        with self._trace_lock:
            self._trace.append("fresh_readback_settled")


def _active_session(
    connection: _BarrierConnection,
) -> BackendObserverSession:
    session = BackendObserverSession(
        observer_factory=_Observer,
        connection_factory=lambda: connection,
        failure_causality=None,
        child_released=lambda: True,
        deadline_policy=_POLICY,
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
        "readback_order",
    ),
    _THREE_PARTY_SCHEDULES,
)
def test_fifty_request_operation_close_and_terminal_readback_schedules(
    monkeypatch: pytest.MonkeyPatch,
    settlement_order: str,
    request_outcome: str,
    close_start: str,
    close_mode: str,
    readback_order: str,
) -> None:
    schedule = ObserverSchedule()
    monkeypatch.setattr(observer_session, "Timer", schedule.make_timer)
    connection = _BarrierConnection(request_outcome)
    session = _active_session(connection)
    operation_started = Event()
    allow_operation_return = Event()
    operation_finished = Event()
    close_entered = Event()
    child_terminal = Event()
    trace: list[str] = []
    trace_lock = Lock()
    fresh_readback = _FreshReadback(connection, trace, trace_lock)
    operation_failures: list[BaseException] = []
    close_failures: list[BaseException] = []
    readback_thread: Thread | None = None

    def record(event: str) -> None:
        with trace_lock:
            trace.append(event)

    def operation(_observer: object, _connection: object) -> str:
        record("operation_started")
        operation_started.set()
        assert allow_operation_return.wait(1.0)
        record("operation_returned")
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
            record("operation_settled")

    def terminal_arrives() -> None:
        if child_terminal.is_set():
            return
        record("child_terminal")
        child_terminal.set()
        session.begin_close()

    def start_readback() -> Thread:
        thread = Thread(target=fresh_readback.run)
        thread.start()
        return thread

    close_timeout = 0.05 if close_mode == "timeout_then_retry" else 0.5

    def close_session() -> None:
        record("close_started")
        close_entered.set()
        try:
            session.close(timeout_seconds=close_timeout)
        except BaseException as error:
            close_failures.append(error)
        finally:
            record("close_attempt_settled")

    operation_thread = Thread(target=run_operation)
    close_thread = Thread(target=close_session)
    operation_thread.start()
    try:
        assert operation_started.wait(1.0)
        assert connection.cancel_started.wait(1.0)
        record("request_started")

        def before_close_sources() -> None:
            nonlocal readback_thread
            terminal_arrives()
            if readback_order == "readback_before_close":
                readback_thread = start_readback()
                readback_thread.join(1.0)

        def while_close_sources() -> None:
            nonlocal readback_thread
            if readback_order != "readback_while_close_waits":
                return
            assert close_entered.wait(1.0)
            assert close_thread.is_alive()
            terminal_arrives()
            readback_thread = start_readback()
            readback_thread.join(1.0)

        if close_start == "before_first_settlement":
            if readback_order != "readback_while_close_waits":
                before_close_sources()
            close_thread.start()
            while_close_sources()

        if settlement_order == "operation_first":
            allow_operation_return.set()
            schedule.wait_for_operation_return()
            # run() still owns settlement until the request finishes.
            assert operation_finished.is_set() is False
            assert session.snapshot().cancellation.request_in_flight is True
        else:
            connection.allow_cancel_return.set()
            assert connection.cancel_finished.wait(1.0)
            schedule.wait_for_request_settlement()
            record("request_settled")
            assert session.snapshot().operation_in_flight is True

        if close_start == "after_first_settlement":
            if readback_order != "readback_while_close_waits":
                before_close_sources()
            close_thread.start()
            while_close_sources()

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
            schedule.wait_for_request_settlement()
            record("request_settled")
        else:
            allow_operation_return.set()
            assert operation_finished.wait(1.0)

        if readback_order == "readback_after_both":
            terminal_arrives()
            readback_thread = start_readback()
            readback_thread.join(1.0)

        operation_thread.join(1.0)
        assert operation_thread.is_alive() is False
        close_thread.join(1.0)
        assert close_thread.is_alive() is False
        if close_mode == "timeout_then_retry":
            session.close(timeout_seconds=0.5)
        session.close(timeout_seconds=0.5)

        assert len(operation_failures) == 1
        assert isinstance(operation_failures[0], BackendMonitorError)
        assert child_terminal.is_set()
        assert fresh_readback.open_count == 1
        assert fresh_readback.read_count == 1
        assert fresh_readback.close_count == 1
        if readback_order != "readback_after_both":
            assert fresh_readback.live_closed_at_read == [False]
        assert connection.close_count == 1
        assert connection.close_under_use is False
        snapshot = session.snapshot()
        assert snapshot.cancellation.operation_settled is True
        assert snapshot.cancellation.request_in_flight is False
        assert snapshot.cancellation.close_eligible is True
        assert trace.count("child_terminal") == 1
        assert trace.count("fresh_readback_started") == 1
    finally:
        allow_operation_return.set()
        connection.allow_cancel_return.set()
        operation_thread.join(1.0)
        if close_thread.ident is not None:
            close_thread.join(1.0)
        if readback_thread is not None:
            readback_thread.join(1.0)
        if not connection.closed:
            session.close()
