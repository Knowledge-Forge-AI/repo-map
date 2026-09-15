from threading import Event, Thread

import psycopg
import pytest

import repomap_kg.storage.backend_observer as observer_module
import scale28_backend_observer_session as session_module
import scale28_observer_deadlines as deadline_module
from repomap_kg.storage.backend_observer import BackendOwnershipObserver
from repomap_test_support.observer_trace import (
    ObserverTraceEvidenceError,
    ObserverTraceKind,
    ObserverTraceRecorder,
    instrument_observer_runtime,
)
from scale14_backend_monitor import BackendOwnershipMonitor
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


def test_successful_sql_operation_preserves_arguments_return_and_single_delegation() -> None:
    recorder = ObserverTraceRecorder()
    connection = _Connection()
    session = _session(connection)
    calls = []

    def operation(observer, exact_connection):
        calls.append((observer, exact_connection))
        return exact_connection

    with instrument_observer_runtime(recorder):
        result = session.run(
            ObserverFailureBoundary.ACTIVE_SUMMARY,
            operation,
            allowed_states=(ObserverSessionState.ACTIVE,),
            timeout_seconds=0.08,
        )
    session.close()

    assert result is connection
    assert calls == [(session._observer, connection)]
    assert len(_events(recorder, ObserverTraceKind.CALLBACK_DISPATCH)) == 1
    assert len(_events(recorder, ObserverTraceKind.CALLBACK_RETURN)) == 1
    assert len(_events(recorder, ObserverTraceKind.OPERATION_SETTLEMENT)) == 1


def test_overflow_does_not_fabricate_runtime_failure() -> None:
    recorder = ObserverTraceRecorder(max_events=1)
    recorder.record(ObserverTraceKind.CLEANUP_RESULT, detail="completed")
    connection = _Connection()
    session = _session(connection)
    calls = []

    with instrument_observer_runtime(recorder):
        def _run_action(_observer: object, exact_connection: _Connection) -> str:
            calls.append(exact_connection)
            return "ok"

        result = session.run(
            ObserverFailureBoundary.ACTIVE_SUMMARY,
            _run_action,
            allowed_states=(ObserverSessionState.ACTIVE,),
            timeout_seconds=0.08,
        )
    session.close()

    assert result == "ok"
    assert calls == [connection]
    with pytest.raises(ObserverTraceEvidenceError, match="overflow"):
        recorder.snapshot()


def test_partial_install_failure_restores_every_wrapper(monkeypatch) -> None:
    recorder = ObserverTraceRecorder()
    targets = (
        (BackendObserverSession, "run"),
        (session_module, "Timer"),
        (BackendObserverSession, "_expire_operation"),
        (BackendObserverSession, "_cancel_connection"),
        (BackendObserverSession, "_record_cancellation_result"),
        (BackendObserverSession, "close"),
        (deadline_module.ObserverCancellationState, "request"),
        (deadline_module.ObserverCancellationState, "record_request_outcome"),
        (deadline_module.ObserverCancellationState, "settle_operation"),
        (psycopg.Connection, "cancel_safe"),
        (psycopg.Connection, "execute"),
        (psycopg.Cursor, "fetchall"),
        (psycopg.Cursor, "fetchone"),
        (BackendOwnershipObserver, "public_summary"),
        (observer_module, "read_backend_activity"),
        (observer_module, "current_backend_identity"),
        (BackendOwnershipMonitor, "startup_summary"),
        (BackendOwnershipMonitor, "summary"),
        (BackendOwnershipMonitor, "pre_release_summary"),
        (BackendOwnershipMonitor, "validate_summary"),
        (BackendOwnershipMonitor, "read"),
        (BackendOwnershipMonitor, "_consume"),
        (BackendOwnershipMonitor, "release_when_ready"),
    )
    originals = {(owner, name): getattr(owner, name) for owner, name in targets}
    monkeypatch.delattr(BackendOwnershipMonitor, "wait_quiescent")

    with pytest.raises(AttributeError):
        with instrument_observer_runtime(recorder):
            raise AssertionError("unreachable")

    assert all(
        getattr(owner, name) is originals[(owner, name)]
        for owner, name in targets
    )


def test_final_window_trace_preserves_zero_and_validation_boundaries(monkeypatch) -> None:
    expected = BackendMonitorError(
        "private final-window detail",
        category="backend_observer_failed",
    )
    calls = []

    def fake_release(self, release, summary_validator, **kwargs):
        calls.append(kwargs.get("timeout_seconds"))
        if kwargs.get("timeout_seconds") == 0:
            raise expected
        summary = {"observer": 1}
        summary_validator(summary)
        release()
        return summary

    monkeypatch.setattr(BackendOwnershipMonitor, "release_when_ready", fake_release)
    monitor = object.__new__(BackendOwnershipMonitor)
    monitor._session = _session(_Connection())
    monitor._deadline_policy = _policy()
    recorder = ObserverTraceRecorder()
    released = []
    validated = []

    with instrument_observer_runtime(recorder):
        result = monitor.release_when_ready(
            lambda: released.append(True),
            lambda summary: validated.append(summary),
            timeout_seconds=0.05,
        )
        with pytest.raises(BackendMonitorError) as caught:
            monitor.release_when_ready(lambda: None, lambda _summary: None, timeout_seconds=0)

    assert result == {"observer": 1}
    assert released == [True]
    assert validated == [{"observer": 1}]
    assert caught.value is expected
    assert calls == [0.05, 0]
    events = recorder.snapshot().events
    kinds = [event.kind for event in events]
    assert kinds[:4] == [
        ObserverTraceKind.FINAL_WINDOW_OPEN,
        ObserverTraceKind.SUMMARY_VALIDATION_ENTRY,
        ObserverTraceKind.SUMMARY_VALIDATION_RETURN,
        ObserverTraceKind.FINAL_WINDOW_FINISH,
    ]
    assert kinds[-2:] == [
        ObserverTraceKind.FINAL_WINDOW_OPEN,
        ObserverTraceKind.FINAL_WINDOW_RAISE,
    ]
    assert events[-2].caller_timeout_ns == 0


def test_exception_identity_is_preserved() -> None:
    recorder = ObserverTraceRecorder()
    connection = _Connection()
    session = _session(connection)
    expected = RuntimeError("private detail")

    with instrument_observer_runtime(recorder):
        with pytest.raises(RuntimeError) as caught:
            session.run(
                ObserverFailureBoundary.ACTIVE_SUMMARY,
                lambda *_args: (_ for _ in ()).throw(expected),
                allowed_states=(ObserverSessionState.ACTIVE,),
                timeout_seconds=0.08,
            )
    session.close()

    assert caught.value.__cause__ is expected
    assert "private detail" not in recorder.snapshot().to_public_payload().__repr__()


def test_second_caller_records_active_owner_and_real_acquisition_wait() -> None:
    recorder = ObserverTraceRecorder()
    connection = _Connection()
    session = _session(connection, _policy(cancel_after=0.2, caller=0.3))
    first_started = Event()
    release_first = Event()
    results = []

    def first_operation(*_args):
        first_started.set()
        assert release_first.wait(1.0)

    first = Thread(
        target=lambda: session.run(
            ObserverFailureBoundary.ACTIVE_SUMMARY,
            first_operation,
            allowed_states=(ObserverSessionState.ACTIVE,),
            timeout_seconds=0.3,
        )
    )
    with instrument_observer_runtime(recorder):
        first.start()
        assert first_started.wait(1.0)
        second = Thread(
            target=lambda: results.append(
                session.run(
                    ObserverFailureBoundary.RESOURCE_READ,
                    lambda *_args: "second",
                    allowed_states=(ObserverSessionState.ACTIVE,),
                    timeout_seconds=0.3,
                )
            )
        )
        second.start()
        while len(_events(recorder, ObserverTraceKind.RUN_CALL_ENTRY)) < 2:
            pass
        release_first.set()
        first.join(1.0)
        second.join(1.0)
    session.close()

    entries = _events(recorder, ObserverTraceKind.RUN_CALL_ENTRY)
    second_entry = entries[1]
    second_dispatch = _events(recorder, ObserverTraceKind.CALLBACK_DISPATCH)[1]
    assert second_entry.active_owner_operation_id == entries[0].operation_id
    assert second_entry.active_owner_boundary == "observer_active_summary"
    assert second_dispatch.duration_ns > 0
    assert results == ["second"]


def test_pre_dispatch_sql_floor_refusal_has_no_callback_or_sql_events() -> None:
    recorder = ObserverTraceRecorder()
    connection = _Connection()
    session = _session(connection)
    delegated = 0

    def operation(*_args):
        nonlocal delegated
        delegated += 1

    with instrument_observer_runtime(recorder):
        with pytest.raises(BackendMonitorError) as caught:
            session.run(
                ObserverFailureBoundary.ACTIVE_SUMMARY,
                operation,
                allowed_states=(ObserverSessionState.ACTIVE,),
                timeout_seconds=0.005,
            )
    session.close()

    assert caught.value.observer_boundary is ObserverFailureBoundary.OPERATION_WAIT_TIMEOUT
    assert delegated == 0
    assert _events(recorder, ObserverTraceKind.CALLBACK_DISPATCH) == []
    assert _events(recorder, ObserverTraceKind.BACKEND_ACTIVITY_ENTRY) == []


def test_operation_wait_timeout_names_the_still_active_owner() -> None:
    recorder = ObserverTraceRecorder()
    connection = _Connection()
    session = _session(connection, _policy(cancel_after=0.2, caller=0.3))
    started = Event()
    release = Event()
    first_failures = []

    def first_operation(*_args):
        started.set()
        assert release.wait(1.0)

    def invoke_first():
        try:
            session.run(
                ObserverFailureBoundary.ACTIVE_SUMMARY,
                first_operation,
                allowed_states=(ObserverSessionState.ACTIVE,),
                timeout_seconds=0.3,
            )
        except BaseException as error:
            first_failures.append(error)

    with instrument_observer_runtime(recorder):
        first = Thread(target=invoke_first)
        first.start()
        assert started.wait(1.0)
        with pytest.raises(BackendMonitorError) as caught:
            session.run(
                ObserverFailureBoundary.RESOURCE_READ,
                lambda *_args: None,
                allowed_states=(ObserverSessionState.ACTIVE,),
                timeout_seconds=0.03,
            )
        release.set()
        first.join(1.0)
    session.close()

    assert caught.value.observer_boundary is ObserverFailureBoundary.OPERATION_WAIT_TIMEOUT
    entries = _events(recorder, ObserverTraceKind.RUN_CALL_ENTRY)
    assert entries[1].active_owner_operation_id == entries[0].operation_id
    assert len(_events(recorder, ObserverTraceKind.CALLBACK_DISPATCH)) == 1
    assert first_failures == []
