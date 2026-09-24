from __future__ import annotations

from threading import Event, Thread
from typing import Callable

import pytest

import scale28_backend_observer_session as observer_session
import scale28_observer_deadlines as deadlines
from scale28_backend_observer_session import (
    BackendMonitorError,
    BackendObserverSession,
    ObserverFailureBoundary,
    ObserverSessionState,
)


class _Observer:
    def register_connection(self, _connection: object) -> None:
        return None


class _Connection:
    def __init__(self) -> None:
        self.closed = False
        self.broken = False
        self.cancel_timeouts: list[float] = []
        self.close_count = 0
        self.session: BackendObserverSession | None = None

    def cancel_safe(self, *, timeout: float) -> None:
        self.cancel_timeouts.append(timeout)

    def close(self) -> None:
        assert self.session is not None
        snapshot = self.session.snapshot()
        assert snapshot.operation_in_flight is False
        assert snapshot.cancellation.request_in_flight is False
        self.close_count += 1
        self.closed = True


def _active_session(
    connection: _Connection,
    *,
    policy: deadlines.ObserverDeadlinePolicy = deadlines.DEFAULT_OBSERVER_DEADLINE_POLICY,
) -> BackendObserverSession:
    session = BackendObserverSession(
        observer_factory=_Observer,
        connection_factory=lambda _settings=None: connection,
        failure_causality=None,
        child_released=lambda: True,
        deadline_policy=policy,
    )
    connection.session = session
    session.open(1)
    session.mark_startup_validated()
    session.activate_and_release(lambda: None)
    return session


def test_observer_policy_has_four_closed_operation_classes_and_exact_bounds() -> None:
    assert {member.value for member in deadlines.ObserverOperationClass} == {
        "connection_startup",
        "sql_bounded",
        "serialization_only",
        "settlement",
    }
    policy = deadlines.DEFAULT_OBSERVER_DEADLINE_POLICY
    assert policy.server_statement_timeout_ms == 400
    assert policy.client_cancel_after_seconds == pytest.approx(0.450)
    assert policy.cancel_request_timeout_seconds == pytest.approx(0.250)
    assert policy.cancel_request_max_seconds == pytest.approx(0.300)
    assert policy.cancel_request_publication_margin_seconds == pytest.approx(0.050)
    assert policy.request_terminal_timeout_seconds == pytest.approx(0.300)
    assert policy.operation_settlement_timeout_seconds == pytest.approx(0.900)
    assert policy.close_timeout_seconds == pytest.approx(1.000)
    assert policy.terminal_readback_timeout_seconds == pytest.approx(0.500)
    assert policy.cleanup_timeout_seconds == pytest.approx(5.000)
    assert policy.final_release_timeout_seconds == pytest.approx(0.600)
    assert policy.final_release_max_seconds == pytest.approx(0.650)
    assert policy.minimum_sql_caller_seconds == pytest.approx(0.420)
    assert policy.final_sample_floor_seconds == pytest.approx(0.050)


def test_serialization_only_operation_arms_no_timer_or_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection()
    session = _active_session(connection)

    class ForbiddenTimer:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("serialization-only operation armed a timer")

    monkeypatch.setattr(observer_session, "Timer", ForbiddenTimer)

    result = session.run(
        ObserverFailureBoundary.CONTRACT_VALIDATION,
        lambda _observer, _connection: "serialized",
        allowed_states=(ObserverSessionState.ACTIVE,),
        operation_class=deadlines.ObserverOperationClass.SERIALIZATION_ONLY,
        timeout_seconds=0.100,
    )

    assert result == "serialized"
    assert connection.cancel_timeouts == []


def test_sql_operation_refuses_insufficient_remaining_authority_before_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection()
    session = _active_session(connection)
    called = False

    class ForbiddenTimer:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("refused SQL operation armed a timer")

    def operation(_observer: object, _connection: object) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(observer_session, "Timer", ForbiddenTimer)

    with pytest.raises(BackendMonitorError, match="insufficient"):
        session.run(
            ObserverFailureBoundary.ACTIVE_SUMMARY,
            operation,
            allowed_states=(ObserverSessionState.ACTIVE,),
            operation_class=deadlines.ObserverOperationClass.SQL_BOUNDED,
            timeout_seconds=0.419,
        )

    assert called is False
    assert connection.cancel_timeouts == []


def test_delayed_timer_wake_does_not_consume_request_dispatch_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection()
    session = _active_session(connection)
    now = [0.0]

    class DelayedTimer:
        def __init__(
            self,
            _delay: float,
            callback: Callable[..., object],
            args: tuple[object, ...],
        ) -> None:
            self.callback = callback
            self.args = args
            self.name = ""
            self.daemon = False

        def start(self) -> None:
            now[0] = 0.700
            self.callback(*self.args)

        def cancel(self) -> None:
            return None

        def join(self, *, timeout: float) -> None:
            assert timeout == pytest.approx(0.300)

    monkeypatch.setattr(observer_session, "_monotonic", lambda: now[0])
    monkeypatch.setattr(observer_session, "Timer", DelayedTimer)

    with pytest.raises(BackendMonitorError, match="timed out"):
        session.run(
            ObserverFailureBoundary.ACTIVE_SUMMARY,
            lambda _observer, _connection: None,
            allowed_states=(ObserverSessionState.ACTIVE,),
            operation_class=deadlines.ObserverOperationClass.SQL_BOUNDED,
            timeout_seconds=0.500,
        )

    assert connection.cancel_timeouts == [pytest.approx(0.250)]


def test_operation_settlement_expiry_classifies_without_closing_active_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection()
    now = [0.0]
    monkeypatch.setattr(observer_session, "_monotonic", lambda: now[0])
    session = _active_session(connection)
    started = Event()
    release = Event()
    failures: list[BaseException] = []

    def operation(_observer: object, _connection: object) -> None:
        started.set()
        assert release.wait(1.0)

    def run_operation() -> None:
        try:
            session.run(
                ObserverFailureBoundary.ACTIVE_SUMMARY,
                operation,
                allowed_states=(ObserverSessionState.ACTIVE,),
                operation_class=deadlines.ObserverOperationClass.SQL_BOUNDED,
                timeout_seconds=0.500,
            )
        except BaseException as error:
            failures.append(error)

    operation_thread = Thread(target=run_operation)
    operation_thread.start()
    try:
        assert started.wait(1.0)
        now[0] = 0.901
        snapshot = session.snapshot()
        assert snapshot.cancellation.settlement_limitation is True
        assert snapshot.quarantined is False
        assert connection.close_count == 0
    finally:
        release.set()
        operation_thread.join(1.0)
        assert len(failures) == 1
        assert isinstance(failures[0], BackendMonitorError)


def test_request_terminal_deadline_starts_at_actual_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [0.0]

    class SlowPublicationConnection(_Connection):
        def cancel_safe(self, *, timeout: float) -> None:
            super().cancel_safe(timeout=timeout)
            now[0] += 0.301

    class ImmediateTimer:
        def __init__(
            self,
            _delay: float,
            callback: Callable[..., object],
            args: tuple[object, ...],
        ) -> None:
            self.callback = callback
            self.args = args
            self.name = ""
            self.daemon = False

        def start(self) -> None:
            now[0] = 0.450
            self.callback(*self.args)

        def cancel(self) -> None:
            return None

        def join(self, *, timeout: float) -> None:
            assert timeout == pytest.approx(0.300)

    connection = SlowPublicationConnection()
    session = _active_session(connection)
    monkeypatch.setattr(observer_session, "_monotonic", lambda: now[0])
    monkeypatch.setattr(observer_session, "Timer", ImmediateTimer)

    with pytest.raises(BackendMonitorError, match="timed out"):
        session.run(
            ObserverFailureBoundary.ACTIVE_SUMMARY,
            lambda _observer, _connection: None,
            allowed_states=(ObserverSessionState.ACTIVE,),
            operation_class=deadlines.ObserverOperationClass.SQL_BOUNDED,
            timeout_seconds=0.500,
        )

    snapshot = session.snapshot()
    assert snapshot.cancellation.request_in_flight is False
    assert snapshot.cancellation.request_settlement_limitation is True
    assert connection.cancel_timeouts == [pytest.approx(0.250)]


def test_close_expiry_quarantines_and_one_late_retry_preserves_limitations() -> None:
    connection = _Connection()
    session = _active_session(connection)
    started = Event()
    release = Event()
    failures: list[BaseException] = []

    def _validation_operation(_observer: object, _connection: object) -> None:
        started.set()
        release.wait(1.0)

    def run_operation() -> None:
        try:
            session.run(
                ObserverFailureBoundary.CONTRACT_VALIDATION,
                _validation_operation,
                allowed_states=(ObserverSessionState.ACTIVE,),
                operation_class=deadlines.ObserverOperationClass.SERIALIZATION_ONLY,
                timeout_seconds=0.500,
            )
        except BaseException as error:
            failures.append(error)

    operation_thread = Thread(target=run_operation)
    operation_thread.start()
    try:
        assert started.wait(1.0)
        with pytest.raises(BackendMonitorError, match="settlement timed out"):
            session.close(timeout_seconds=0)
        limited = session.snapshot()
        assert limited.quarantined is True
        assert limited.cleanup_complete is False
        assert limited.close_retry_available is True
        assert limited.cancellation.settlement_limitation is True
        assert connection.close_count == 0

        release.set()
        operation_thread.join(1.0)
        assert failures == []
        session.close(timeout_seconds=0.500)
        closed = session.snapshot()
        assert closed.state is ObserverSessionState.CLOSED
        assert closed.close_retry_used is True
        assert closed.cancellation.settlement_limitation is True
        assert connection.close_count == 1
        session.close(timeout_seconds=0.500)
        assert connection.close_count == 1
    finally:
        release.set()
        operation_thread.join(1.0)
