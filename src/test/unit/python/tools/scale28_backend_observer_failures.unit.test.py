from __future__ import annotations

from itertools import permutations
from threading import Event, Thread

import pytest

from actual_refresh_failure_causality import FailureCausalityAuthority
from repomap_kg.storage.backend_telemetry_contracts import (
    ConnectionTelemetryError,
)
from scale28_backend_observer_session import (
    BackendMonitorError,
    BackendObserverSession,
    ObserverFailureBoundary,
    ObserverSessionState,
)
from scale28_observer_deadlines import ObserverDeadlinePolicy


_SYNTHETIC_DEADLINE_POLICY = ObserverDeadlinePolicy(
    server_statement_timeout_ms=10,
    client_cancel_after_seconds=0.02,
    cancel_request_timeout_seconds=0.01,
    caller_operation_timeout_seconds=0.05,
)


class _Connection:
    def __init__(self) -> None:
        self.close_entered = Event()
        self.close_count = 0
        self.closed = False
        self.broken = False

    def close(self) -> None:
        self.close_count += 1
        self.closed = True
        self.close_entered.set()


class _FailingCloseConnection(_Connection):
    def close(self) -> None:
        super().close()
        raise OSError("private close detail")


class _Stream:
    def __init__(self, reader_release: Event) -> None:
        self._reader_release = reader_release

    def close(self) -> None:
        self._reader_release.set()


class _Reader:
    def __init__(self, release: Event) -> None:
        self._release = release

    def __call__(self, _stream, *, readiness):
        readiness()
        self._release.wait()
        return None


class _BarrierObserver:
    def __init__(self) -> None:
        self.summary_count = 0
        self.active_summary_entered = Event()
        self.active_summary_release = Event()

    def register_connection(self, _connection) -> None:
        return None

    def public_summary(self, connection) -> dict[str, int]:
        self.summary_count += 1
        if self.summary_count >= 5:
            self.active_summary_entered.set()
            self.active_summary_release.wait()
            if connection.close_entered.is_set():
                raise RuntimeError("observer connection closed during summary")
        return {
            "observer": 1,
            "direct_owned_client": 0,
            "direct_owned_parallel_worker": 0,
            "ambient_client": 0,
            "unknown": 0,
        }

    def consume_pipe_event(self, _event, _connection, _acknowledgement_fd) -> None:
        return None


class _SessionObserver:
    def __init__(self, registration_error: Exception | None = None) -> None:
        self.registration_error = registration_error
        self.registered_connection = None

    def register_connection(self, connection) -> None:
        if self.registration_error is not None:
            raise self.registration_error
        self.registered_connection = connection


def _session(
    *,
    observer=None,
    connection=None,
    causality=None,
    released=None,
) -> tuple[BackendObserverSession, _Connection]:
    exact_connection = connection or _Connection()
    session = BackendObserverSession(
        observer_factory=lambda: observer or _SessionObserver(),
        connection_factory=lambda: exact_connection,
        failure_causality=causality,
        child_released=(None if released is None else lambda: released[0]),
    )
    return session, exact_connection


def _activate(session: BackendObserverSession) -> None:
    session.open(1)
    session.mark_startup_validated()
    session.activate_and_release(lambda: None)


def test_session_classifies_observer_identity_change() -> None:
    session, _connection = _session()
    _activate(session)
    class IdentityChanged(RuntimeError):
        observer_identity_changed = True

    cause = IdentityChanged("private identity detail")

    with pytest.raises(BackendMonitorError) as captured:
        session.run(
            ObserverFailureBoundary.ACTIVE_SUMMARY,
            lambda _observer, _connection: (_ for _ in ()).throw(cause),
            allowed_states=(ObserverSessionState.ACTIVE,),
        )

    assert captured.value.observer_boundary is (
        ObserverFailureBoundary.IDENTITY_CHANGED
    )
    session.close()


def test_session_classifies_resource_read_failure() -> None:
    causality = FailureCausalityAuthority()
    session, _connection = _session(causality=causality)
    _activate(session)

    with pytest.raises(BackendMonitorError) as captured:
        session.run(
            ObserverFailureBoundary.RESOURCE_READ,
            lambda _observer, _connection: (_ for _ in ()).throw(OSError()),
            allowed_states=(ObserverSessionState.ACTIVE,),
            category="resource_reader_unavailable",
        )

    assert captured.value.observer_boundary is ObserverFailureBoundary.RESOURCE_READ
    assert captured.value.category == "resource_reader_unavailable"
    assert causality.candidates()[0].authority_owner == "resource_sampling"
    session.close()


def test_session_classifies_local_close_failure_as_terminal_secondary() -> None:
    causality = FailureCausalityAuthority()
    connection = _FailingCloseConnection()
    session, _connection = _session(connection=connection, causality=causality)
    _activate(session)

    with pytest.raises(BackendMonitorError) as captured:
        session.close()

    assert captured.value.observer_boundary is ObserverFailureBoundary.LOCAL_CLOSE
    assert captured.value.category == "backend_quiescence_timeout"
    assert causality.candidates()[0].terminal_secondary is True
    assert session.snapshot().state is ObserverSessionState.CLOSING
    assert connection.close_count == 1


def test_session_preserves_telemetry_contract_failure_category() -> None:
    causality = FailureCausalityAuthority()
    session, _connection = _session(causality=causality)
    _activate(session)

    with pytest.raises(BackendMonitorError) as captured:
        session.run(
            ObserverFailureBoundary.EVENT_APPLY,
            lambda _observer, _connection: (_ for _ in ()).throw(
                ConnectionTelemetryError("private telemetry detail")
            ),
            allowed_states=(ObserverSessionState.ACTIVE,),
        )

    assert captured.value.category == "backend_telemetry_failed"
    assert captured.value.observer_boundary is ObserverFailureBoundary.EVENT_APPLY
    assert causality.candidates()[0].code == "backend_telemetry_failed"
    session.close()


def test_session_serializes_summary_and_event_operations() -> None:
    session, _connection = _session()
    _activate(session)
    first_entered = Event()
    first_release = Event()
    second_entered = Event()

    def first(_observer, _connection):
        first_entered.set()
        first_release.wait()

    def second(_observer, _connection):
        second_entered.set()

    first_thread = Thread(
        target=lambda: session.run(
            ObserverFailureBoundary.ACTIVE_SUMMARY,
            first,
            allowed_states=(ObserverSessionState.ACTIVE,),
        )
    )
    second_thread = Thread(
        target=lambda: session.run(
            ObserverFailureBoundary.EVENT_APPLY,
            second,
            allowed_states=(ObserverSessionState.ACTIVE,),
        )
    )
    first_thread.start()
    assert first_entered.wait(1)
    second_thread.start()
    assert not second_entered.wait(0.05)
    first_release.set()
    first_thread.join(timeout=1)
    second_thread.join(timeout=1)

    assert second_entered.is_set()
    session.close()


def test_close_waits_for_inflight_event_application() -> None:
    session, connection = _session()
    _activate(session)
    event_entered = Event()
    event_release = Event()
    event_errors: list[BaseException] = []

    def apply_event(_observer, _connection):
        event_entered.set()
        event_release.wait()

    def run_event() -> None:
        try:
            session.run(
                ObserverFailureBoundary.EVENT_APPLY,
                apply_event,
                allowed_states=(ObserverSessionState.ACTIVE,),
            )
        except BaseException as error:
            event_errors.append(error)

    event_thread = Thread(target=run_event)
    event_thread.start()
    assert event_entered.wait(1)
    close_thread = Thread(target=session.close)
    close_thread.start()
    assert not connection.close_entered.wait(0.05)
    event_release.set()
    event_thread.join(timeout=1)
    close_thread.join(timeout=1)

    assert not event_thread.is_alive()
    assert not close_thread.is_alive()
    assert len(event_errors) == 1
    assert isinstance(event_errors[0], BackendMonitorError)
    assert (
        event_errors[0].observer_boundary
        is ObserverFailureBoundary.OPERATION_EXECUTION_TIMEOUT
    )
    assert connection.close_count == 1


def test_session_rejects_operations_after_close_without_failure_candidate() -> None:
    causality = FailureCausalityAuthority()
    session, _connection = _session(causality=causality)
    _activate(session)
    session.close()

    with pytest.raises(BackendMonitorError) as captured:
        session.run(
            ObserverFailureBoundary.ACTIVE_SUMMARY,
            lambda _observer, _connection: None,
            allowed_states=(ObserverSessionState.ACTIVE,),
        )

    assert captured.value.observer_boundary is ObserverFailureBoundary.LOCAL_CLOSE
    assert causality.candidates() == ()


def test_session_snapshot_is_bounded_and_omits_connection_identity() -> None:
    session, _connection = _session()
    _activate(session)

    snapshot = session.snapshot()

    assert snapshot.state is ObserverSessionState.ACTIVE
    assert snapshot.active_operation is None
    assert snapshot.operation_in_flight is False
    assert "Connection" not in repr(snapshot)
    session.close()


def test_one_hundred_observer_telemetry_resource_close_permutations() -> None:
    orderings = tuple(
        permutations(("observer", "telemetry", "resource", "close"))
    )
    codes = {
        "observer": "backend_observer_failed",
        "telemetry": "backend_telemetry_failed",
        "resource": "resource_reader_unavailable",
    }

    for iteration in range(100):
        causality = FailureCausalityAuthority(clock_ns=lambda: 43)
        session, connection = _session(causality=causality, released=[True])
        _activate(session)
        expected_codes = []
        closed = False

        for fact in orderings[iteration % len(orderings)]:
            if fact == "close":
                session.close()
                closed = True
                continue
            if fact == "observer":
                with pytest.raises(BackendMonitorError) as captured:
                    session.run(
                        ObserverFailureBoundary.ACTIVE_SUMMARY,
                        lambda _observer, _connection: (_ for _ in ()).throw(
                            RuntimeError("private observer detail")
                        ),
                        allowed_states=(ObserverSessionState.ACTIVE,),
                    )
                if closed:
                    assert captured.value.observer_boundary is (
                        ObserverFailureBoundary.LOCAL_CLOSE
                    )
                else:
                    expected_codes.append(codes[fact])
                continue
            causality.record_code(
                codes[fact],
                authority_owner=(
                    "backend_ownership"
                    if fact == "telemetry"
                    else "resource_sampling"
                ),
                lifecycle_boundary=f"active_{fact}",
                existed_before_child_release=False,
                terminal_secondary=bool(causality.candidates()),
            )
            expected_codes.append(codes[fact])

        session.close()
        assert connection.close_count == 1
        assert [candidate.code for candidate in causality.candidates()] == (
            expected_codes
        )
