from threading import Event, Thread

import psycopg
import pytest

import scale28_backend_observer_session as session_module
import scale28_observer_deadlines as deadline_module
import repomap_test_support.observer_trace as trace_module
from repomap_test_support.observer_trace import (
    ObserverCaller,
    ObserverTraceKind,
    ObserverTraceRecorder,
    _ActiveOwner,
    instrument_observer_runtime,
)
from scale28_backend_observer_session import (
    BackendMonitorError,
    BackendObserverSession,
    ObserverFailureBoundary,
    ObserverSessionState,
)
from scale28_observer_deadlines import (
    ObserverCancellationRequestOutcome,
    ObserverCancellationState,
    ObserverDeadlinePolicy,
    ObserverTimeoutMechanism,
)


class _Observer:
    def register_connection(self, _connection) -> None:
        return None


class _Connection(psycopg.Connection[tuple[object, ...]]):
    broken = False
    closed = False

    def __init__(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True

    def cancel_safe(self, *, timeout: float = 0.0) -> None:
        return None


def _session(connection=None) -> BackendObserverSession:
    policy = ObserverDeadlinePolicy(
        server_statement_timeout_ms=10,
        client_cancel_after_seconds=0.2,
        cancel_request_timeout_seconds=0.05,
        caller_operation_timeout_seconds=0.5,
    )
    session = BackendObserverSession(
        observer_factory=_Observer,
        connection_factory=lambda _settings=None: connection or _Connection(),
        failure_causality=None,
        child_released=lambda: True,
        deadline_policy=policy,
    )
    session.open(1)
    session.mark_startup_validated()
    session.activate_and_release(lambda: None)
    return session


def _events(
    recorder: ObserverTraceRecorder,
    kind: ObserverTraceKind,
):
    return [event for event in recorder.snapshot().events if event.kind is kind]


def test_owner_survives_callback_until_production_run_releases_serialization(
    monkeypatch,
) -> None:
    recorder = ObserverTraceRecorder()
    session = _session()
    settlement_entered = Event()
    allow_settlement = Event()
    original_settle = deadline_module.ObserverCancellationState.settle_operation

    def held_settle(state):
        settlement_entered.set()
        assert allow_settlement.wait(1.0)
        return original_settle(state)

    monkeypatch.setattr(
        deadline_module.ObserverCancellationState,
        "settle_operation",
        held_settle,
    )
    first = Thread(
        target=lambda: session.run(
            ObserverFailureBoundary.CONTRACT_VALIDATION,
            lambda *_args: "first",
            allowed_states=(ObserverSessionState.ACTIVE,),
            timeout_seconds=0.5,
        )
    )
    second = Thread(
        target=lambda: session.run(
            ObserverFailureBoundary.RESOURCE_READ,
            lambda *_args: "second",
            allowed_states=(ObserverSessionState.ACTIVE,),
            timeout_seconds=0.5,
        )
    )

    with instrument_observer_runtime(recorder):
        first.start()
        assert settlement_entered.wait(1.0)
        second.start()
        try:
            while len(_events(recorder, ObserverTraceKind.RUN_CALL_ENTRY)) < 2:
                pass
            waiting = _events(recorder, ObserverTraceKind.RUN_CALL_ENTRY)[1]
        finally:
            allow_settlement.set()
            first.join(1.0)
            second.join(1.0)
    session.close()

    assert waiting.active_owner_operation_id == 1


def test_timer_generation_is_bound_before_original_timer_start(monkeypatch) -> None:
    recorder = ObserverTraceRecorder()
    session = _session()
    observed_bindings = []
    original_start = session_module.Timer.start

    def inspect_then_start(timer):
        generation = int(timer.args[0])
        observed_bindings.append(
            recorder.operation_for_generation(
                recorder.session_token(session),
                generation,
            )
        )
        return original_start(timer)

    monkeypatch.setattr(session_module.Timer, "start", inspect_then_start)
    with instrument_observer_runtime(recorder):
        session.run(
            ObserverFailureBoundary.ACTIVE_SUMMARY,
            lambda *_args: "complete",
            allowed_states=(ObserverSessionState.ACTIVE,),
            timeout_seconds=0.5,
        )
    session.close()

    entry = _events(recorder, ObserverTraceKind.RUN_CALL_ENTRY)[0]
    assert observed_bindings == [entry.operation_id]


def test_unobserved_prebinding_close_request_suppresses_paired_settlement(
    monkeypatch,
) -> None:
    recorder = ObserverTraceRecorder()
    session = _session()
    session_token = recorder.session_token(session)
    state = {"value": ObserverCancellationState().begin_operation()}

    def settle_request(_session, _connection, _timeout_seconds, _generation):
        state["value"] = state["value"].record_request_outcome(
            ObserverCancellationRequestOutcome.REQUEST_SUCCEEDED
        )

    monkeypatch.setattr(
        session_module.BackendObserverSession,
        "_cancel_connection",
        settle_request,
    )
    recorder.record(
        ObserverTraceKind.RUN_CALL_ENTRY,
        session_token=session_token,
        operation_id=1,
        boundary="observer_active_summary",
        operation_class="sql_bounded",
        caller=ObserverCaller.ACTIVE_SUMMARY,
        caller_thread_token="thread-1",
    )
    close_context = trace_module._TraceContext(
        recorder,
        session_token,
        None,
        "unknown",
        "settlement",
        ObserverCaller.CLOSE_OR_SETTLEMENT,
    )

    with instrument_observer_runtime(recorder):
        token = trace_module._TRACE.set(close_context)
        try:
            state["value"] = state["value"].request(
                ObserverTimeoutMechanism.CLIENT_CANCEL_FALLBACK
            )
            owner = _ActiveOwner(
                1,
                "observer_active_summary",
                "sql_bounded",
                1,
                "thread-1",
                ObserverCaller.ACTIVE_SUMMARY,
            )
            recorder.acquire_owner(session_token, owner)
            session._cancel_connection(session._connection, 0.05, 1)
        finally:
            trace_module._TRACE.reset(token)
    recorder.settle_and_release_owner(session_token, 1)
    recorder.record(
        ObserverTraceKind.SESSION_RUN_RETURN,
        session_token=session_token,
        operation_id=1,
        generation=1,
        boundary="observer_active_summary",
        operation_class="sql_bounded",
        caller=ObserverCaller.ACTIVE_SUMMARY,
    )

    events = recorder.snapshot().events
    assert not any(
        event.kind is ObserverTraceKind.CANCELLATION_REQUEST_CREATED
        for event in events
    )
    assert not any(
        event.kind is ObserverTraceKind.REQUEST_SETTLEMENT for event in events
    )
    assert any(
        event.kind is ObserverTraceKind.CANCELLATION_DISPATCH_START
        for event in events
    )
    dispatch = next(
        event
        for event in events
        if event.kind is ObserverTraceKind.CANCELLATION_DISPATCH_START
    )
    assert dispatch.caller is ObserverCaller.CLOSE_OR_SETTLEMENT


class _ImmediateTimer:
    def __init__(self, interval, function, args=()):
        self.interval = interval
        self.function = function
        self.args = args
        self.name = ""
        self.daemon = False

    def start(self):
        self.function(*self.args)

    def cancel(self):
        return None

    def join(self, timeout=None):
        return None


def test_timer_fire_before_callback_retains_one_operation_link(monkeypatch) -> None:
    recorder = ObserverTraceRecorder()
    session = _session(_Connection())
    monkeypatch.setattr(session_module, "Timer", _ImmediateTimer)

    with instrument_observer_runtime(recorder):
        with pytest.raises(BackendMonitorError):
            session.run(
                ObserverFailureBoundary.ACTIVE_SUMMARY,
                lambda *_args: "callback-ran",
                allowed_states=(ObserverSessionState.ACTIVE,),
                timeout_seconds=0.5,
            )
    session.close()

    events = recorder.snapshot().events
    timer = next(event for event in events if event.kind is ObserverTraceKind.TIMER_ACTUAL_FIRE)
    callback = next(event for event in events if event.kind is ObserverTraceKind.CALLBACK_DISPATCH)
    entry = next(event for event in events if event.kind is ObserverTraceKind.RUN_CALL_ENTRY)
    linked = [event.operation_id for event in events if event.kind in {
        ObserverTraceKind.TIMER_SCHEDULED,
        ObserverTraceKind.TIMER_ACTUAL_FIRE,
        ObserverTraceKind.CANCELLATION_DISPATCH_START,
        ObserverTraceKind.CANCELLATION_OUTCOME,
        ObserverTraceKind.REQUEST_SETTLEMENT,
    }]
    assert timer.sequence < callback.sequence
    assert linked and set(linked) == {entry.operation_id}
