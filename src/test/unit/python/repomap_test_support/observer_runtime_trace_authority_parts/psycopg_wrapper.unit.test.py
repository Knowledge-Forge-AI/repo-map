import psycopg
import pytest

from repomap_test_support.observer_trace import (
    ObserverTraceEvidenceError,
    ObserverTraceKind,
    ObserverTraceRecorder,
    instrument_observer_runtime,
)
from scale28_backend_observer_session import (
    BackendObserverSession,
    ObserverFailureBoundary,
    ObserverSessionState,
)
from scale28_observer_deadlines import (
    ObserverDeadlinePolicy,
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


@pytest.mark.parametrize("outcome", ("return", "raise"))
def test_installed_cancel_safe_wrapper_preserves_exact_delegation(outcome) -> None:
    recorder = ObserverTraceRecorder()
    connection = _Connection()
    session = _session(connection)
    original = psycopg.Connection.cancel_safe
    calls = []
    sentinel_result = object()
    sentinel_error = RuntimeError("private fixture detail")

    def delegated(self, *, timeout):
        calls.append((self, timeout))
        if outcome == "raise":
            raise sentinel_error
        return sentinel_result

    setattr(psycopg.Connection, "cancel_safe", delegated)
    observed = []
    try:
        with instrument_observer_runtime(recorder):
            def operation(*_args):
                try:
                    return psycopg.Connection.cancel_safe(connection, timeout=0.125)
                except RuntimeError as error:
                    observed.append(error)
                    return "caught"

            result = session.run(
                ObserverFailureBoundary.ACTIVE_SUMMARY,
                operation,
                allowed_states=(ObserverSessionState.ACTIVE,),
                timeout_seconds=0.5,
            )
            session.close()
        assert psycopg.Connection.cancel_safe is delegated
    finally:
        setattr(psycopg.Connection, "cancel_safe", original)

    assert psycopg.Connection.cancel_safe is original
    assert calls == [(connection, 0.125)]
    if outcome == "return":
        assert result is sentinel_result
        assert observed == []
    else:
        assert result == "caught"
        assert observed == [sentinel_error]
    assert len(_events(recorder, ObserverTraceKind.CANCEL_SAFE_START)) == 1
    terminal = ObserverTraceKind.CANCEL_SAFE_RETURN if outcome == "return" else ObserverTraceKind.CANCEL_SAFE_RAISE
    assert len(_events(recorder, terminal)) == 1


def test_global_psycopg_wrapper_ignores_foreign_connection() -> None:
    recorder = ObserverTraceRecorder()
    connection = _Connection()
    foreign = _Connection()
    session = _session(connection)
    original = psycopg.Connection.cancel_safe
    calls = []

    def delegated(self, *, timeout):
        calls.append((self, timeout))

    setattr(psycopg.Connection, "cancel_safe", delegated)
    try:
        with instrument_observer_runtime(recorder):
            def operation(*_args):
                psycopg.Connection.cancel_safe(connection, timeout=0.1)
                psycopg.Connection.cancel_safe(foreign, timeout=0.2)

            session.run(
                ObserverFailureBoundary.ACTIVE_SUMMARY,
                operation,
                allowed_states=(ObserverSessionState.ACTIVE,),
                timeout_seconds=0.5,
            )
            session.close()
    finally:
        setattr(psycopg.Connection, "cancel_safe", original)

    assert calls == [(connection, 0.1), (foreign, 0.2)]
    assert len(_events(recorder, ObserverTraceKind.CANCEL_SAFE_START)) == 1


@pytest.mark.parametrize(
    "kind",
    (ObserverTraceKind.TIMER_ACTUAL_FIRE, ObserverTraceKind.CANCEL_SAFE_START),
)
def test_orphan_timer_and_cancellation_events_invalidate_evidence(kind) -> None:
    recorder = ObserverTraceRecorder()
    assert recorder.record(kind, session_token="session-1", generation=1) is not None

    with pytest.raises(ObserverTraceEvidenceError, match="linkage"):
        recorder.snapshot()


def test_recorder_clock_failure_never_changes_production_run_result() -> None:
    def broken_clock() -> int:
        raise StopIteration

    recorder = ObserverTraceRecorder(clock_ns=broken_clock)
    session = _session()

    with instrument_observer_runtime(recorder):
        result = session.run(
            ObserverFailureBoundary.CONTRACT_VALIDATION,
            lambda *_args: "complete",
            allowed_states=(ObserverSessionState.ACTIVE,),
            timeout_seconds=0.5,
        )
    session.close()

    assert result == "complete"
    with pytest.raises(ObserverTraceEvidenceError, match="recorder fault"):
        recorder.snapshot()


def test_recorder_owner_is_absent_after_production_run_returns() -> None:
    recorder = ObserverTraceRecorder()
    session = _session()

    with instrument_observer_runtime(recorder):
        session.run(
            ObserverFailureBoundary.CONTRACT_VALIDATION,
            lambda *_args: "complete",
            allowed_states=(ObserverSessionState.ACTIVE,),
            timeout_seconds=0.5,
        )
    token = recorder.session_token(session)
    session.close()

    assert recorder.active_owner(token) is None
    kinds = [event.kind for event in recorder.snapshot().events]
    assert kinds.index(ObserverTraceKind.SESSION_OWNER_RELEASED) < kinds.index(ObserverTraceKind.SESSION_RUN_RETURN)
