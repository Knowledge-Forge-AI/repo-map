from threading import Event, Thread

import psycopg
import pytest

from repomap_test_support.observer_trace import (
    ObserverCaller,
    ObserverTraceKind,
    ObserverTraceRecorder,
    instrument_observer_runtime,
)
from scale28_backend_observer_session import (
    BackendMonitorError,
    BackendObserverSession,
    ObserverFailureBoundary,
    ObserverSessionState,
)
from scale28_observer_deadlines import ObserverDeadlinePolicy


class _Observer:
    def register_connection(self, _connection) -> None:
        return None


class _Connection:
    def __init__(self, *, cancel="success") -> None:
        self.broken = False
        self.closed = False
        self.cancel = cancel
        self.cancel_started = Event()
        self.cancel_finished = Event()
        self.allow_cancel_return = Event()
        self.release_operation = Event()
        self.cancel_calls = 0
        self.close_calls = 0

    def cancel_safe(self, *, timeout: float) -> None:
        self.cancel_calls += 1
        self.cancel_started.set()
        try:
            if self.cancel == "success":
                self.release_operation.set()
            elif self.cancel == "timeout":
                raise psycopg.errors.CancellationTimeout("private cancellation")
            elif self.cancel == "held":
                assert self.allow_cancel_return.wait(1.0)
            elif self.cancel == "success-without-release":
                pass
            else:
                raise AssertionError("unknown cancellation fixture")
        finally:
            self.cancel_finished.set()

    def close(self) -> None:
        self.close_calls += 1
        self.closed = True


class _StatementTimeout(psycopg.errors.QueryCanceled):
    @property
    def diag(self):
        return type("_Diag", (), {"message_primary": "statement timeout"})()


def _policy(*, cancel_after=0.02, caller=0.08, request=0.01):
    return ObserverDeadlinePolicy(
        server_statement_timeout_ms=10,
        client_cancel_after_seconds=cancel_after,
        cancel_request_timeout_seconds=request,
        caller_operation_timeout_seconds=caller,
    )


def _session(connection, policy=None):
    session = BackendObserverSession(
        observer_factory=_Observer,
        connection_factory=lambda _settings=None: connection,
        failure_causality=None,
        child_released=lambda: True,
        deadline_policy=policy or _policy(),
    )
    session.open(1)
    session.mark_startup_validated()
    session.activate_and_release(lambda: None)
    return session


def _events(recorder, kind):
    return [event for event in recorder.snapshot().events if event.kind is kind]




def test_server_statement_timeout_is_separate_from_client_timer() -> None:
    recorder = ObserverTraceRecorder()
    connection = _Connection()
    session = _session(connection)

    with instrument_observer_runtime(recorder):
        with pytest.raises(BackendMonitorError) as caught:
            session.run(
                ObserverFailureBoundary.ACTIVE_SUMMARY,
                lambda *_args: (_ for _ in ()).throw(_StatementTimeout()),
                allowed_states=(ObserverSessionState.ACTIVE,),
                timeout_seconds=0.08,
            )
    session.close()

    assert caught.value.observer_timeout_mechanism is not None
    assert caught.value.observer_timeout_mechanism.value == "server_statement_timeout"
    assert _events(recorder, ObserverTraceKind.TIMER_ACTUAL_FIRE) == []
    assert _events(recorder, ObserverTraceKind.CANCELLATION_OUTCOME) == []


@pytest.mark.parametrize(
    ("cancel_mode", "outcome"),
    (("success", "request_succeeded"), ("timeout", "request_timed_out")),
)
def test_client_timer_and_cancellation_request_outcomes(cancel_mode, outcome) -> None:
    recorder = ObserverTraceRecorder()
    connection = _Connection(cancel=cancel_mode)
    session = _session(connection)
    failures = []

    def operation(*_args):
        if cancel_mode == "success":
            assert connection.release_operation.wait(1.0)
        else:
            assert connection.cancel_started.wait(1.0)
        return "late"

    with instrument_observer_runtime(recorder):
        try:
            session.run(
                ObserverFailureBoundary.ACTIVE_SUMMARY,
                operation,
                allowed_states=(ObserverSessionState.ACTIVE,),
                timeout_seconds=0.08,
            )
        except BackendMonitorError as error:
            failures.append(error)
    session.close()

    assert failures[0].observer_boundary is ObserverFailureBoundary.OPERATION_EXECUTION_TIMEOUT
    assert connection.cancel_calls == 1
    actual = _events(recorder, ObserverTraceKind.TIMER_ACTUAL_FIRE)[0]
    scheduled = _events(recorder, ObserverTraceKind.TIMER_SCHEDULED)[0]
    assert actual.monotonic_ns >= scheduled.nominal_ns
    assert actual.duration_ns == actual.monotonic_ns - scheduled.nominal_ns
    assert actual.caller_thread_token is not None
    assert _events(recorder, ObserverTraceKind.CANCELLATION_OUTCOME)[0].detail == outcome


def test_operation_settles_before_held_cancellation_request() -> None:
    recorder = ObserverTraceRecorder()
    connection = _Connection(cancel="held")
    session = _session(connection, _policy(request=0.2, caller=0.25))
    operation_release = Event()
    failures = []

    def invoke():
        try:
            session.run(
                ObserverFailureBoundary.ACTIVE_SUMMARY,
                lambda *_args: operation_release.wait(1.0),
                allowed_states=(ObserverSessionState.ACTIVE,),
                timeout_seconds=0.25,
            )
        except BaseException as error:
            failures.append(error)

    with instrument_observer_runtime(recorder):
        thread = Thread(target=invoke)
        thread.start()
        assert connection.cancel_started.wait(1.0)
        operation_release.set()
        while not _events(recorder, ObserverTraceKind.OPERATION_SETTLEMENT):
            pass
        connection.allow_cancel_return.set()
        assert connection.cancel_finished.wait(1.0)
        while not _events(recorder, ObserverTraceKind.REQUEST_SETTLEMENT):
            pass
        thread.join(1.0)
    session.close()

    operation_settled = _events(recorder, ObserverTraceKind.OPERATION_SETTLEMENT)[0]
    request_settled = _events(recorder, ObserverTraceKind.REQUEST_SETTLEMENT)[0]
    assert operation_settled.monotonic_ns < request_settled.monotonic_ns
    assert failures


def test_cancellation_request_settles_before_operation_owner() -> None:
    recorder = ObserverTraceRecorder()
    connection = _Connection(cancel="success-without-release")
    session = _session(connection)
    release = Event()
    failures = []

    def invoke():
        try:
            session.run(
                ObserverFailureBoundary.ACTIVE_SUMMARY,
                lambda *_args: release.wait(1.0),
                allowed_states=(ObserverSessionState.ACTIVE,),
                timeout_seconds=0.08,
            )
        except BaseException as error:
            failures.append(error)

    with instrument_observer_runtime(recorder):
        thread = Thread(target=invoke)
        thread.start()
        assert connection.cancel_finished.wait(1.0)
        while not _events(recorder, ObserverTraceKind.REQUEST_SETTLEMENT):
            pass
        release.set()
        thread.join(1.0)
    session.close()

    request_settled = _events(recorder, ObserverTraceKind.REQUEST_SETTLEMENT)[0]
    operation_settled = _events(recorder, ObserverTraceKind.OPERATION_SETTLEMENT)[0]
    assert request_settled.monotonic_ns < operation_settled.monotonic_ns
    assert failures


def test_close_begins_with_active_operation_and_preserves_settlement_order() -> None:
    recorder = ObserverTraceRecorder()
    connection = _Connection(cancel="success")
    session = _session(connection, _policy(cancel_after=0.2, caller=0.3))
    started = Event()
    failures = []

    def operation(*_args):
        started.set()
        assert connection.release_operation.wait(1.0)

    with instrument_observer_runtime(recorder):
        def invoke():
            try:
                session.run(
                    ObserverFailureBoundary.ACTIVE_SUMMARY,
                    operation,
                    allowed_states=(ObserverSessionState.ACTIVE,),
                    timeout_seconds=0.3,
                )
            except BaseException as error:
                failures.append(error)

        thread = Thread(target=invoke)
        thread.start()
        assert started.wait(1.0)
        session.close(timeout_seconds=0.5)
        thread.join(1.0)

    close = _events(recorder, ObserverTraceKind.CLOSE_BEGIN)[0]
    request = _events(recorder, ObserverTraceKind.CANCELLATION_REQUEST_CREATED)[0]
    request_settlement = _events(recorder, ObserverTraceKind.REQUEST_SETTLEMENT)[0]
    dispatch = _events(recorder, ObserverTraceKind.CANCELLATION_DISPATCH_START)[0]
    assert close.active_owner_operation_id is not None
    assert request.operation_id == close.active_owner_operation_id
    assert request.caller is ObserverCaller.CLOSE_OR_SETTLEMENT
    assert request_settlement.caller is ObserverCaller.CLOSE_OR_SETTLEMENT
    assert dispatch.caller is ObserverCaller.CLOSE_OR_SETTLEMENT
    assert connection.close_calls == 1
    assert _events(recorder, ObserverTraceKind.CLOSE_FINISH)
    assert len(failures) == 1
    assert isinstance(failures[0], BackendMonitorError)


def test_disabled_instrumentation_does_not_replace_run_callable() -> None:
    recorder = ObserverTraceRecorder(enabled=False)
    original = BackendObserverSession.run

    with instrument_observer_runtime(recorder):
        assert BackendObserverSession.run is original

    assert recorder.snapshot().events == ()
