from __future__ import annotations

import os
from threading import Event, Thread

import pytest

from actual_refresh_failure_causality import FailureCausalityAuthority
from scale14_backend_monitor import BackendOwnershipMonitor
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


def test_local_close_waits_for_inflight_active_summary() -> None:
    connection = _Connection()
    observer = _BarrierObserver()
    reader_release = Event()
    read_fd, write_fd = os.pipe()
    monitor = BackendOwnershipMonitor(
        connection_factory=lambda: connection,
        event_reader=_Reader(reader_release),
        event_stream=_Stream(reader_release),
        acknowledgement_fd=write_fd,
        observer_factory=lambda: observer,
        _deadline_policy=_SYNTHETIC_DEADLINE_POLICY,
    )
    summary_result: list[dict[str, int]] = []
    summary_errors: list[BaseException] = []

    try:
        monitor.start()
        monitor.startup_summary()
        monitor.release_when_ready(lambda: None, lambda _summary: None)

        def summarize() -> None:
            try:
                summary_result.append(dict(monitor.summary()))
            except BaseException as error:
                summary_errors.append(error)

        summary_thread = Thread(target=summarize)
        summary_thread.start()
        assert observer.active_summary_entered.wait(1)

        close_thread = Thread(target=monitor.close)
        close_thread.start()

        assert not connection.close_entered.wait(0.05)
        observer.active_summary_release.set()
        summary_thread.join(timeout=1)
        close_thread.join(timeout=1)

        assert not summary_thread.is_alive()
        assert not close_thread.is_alive()
        assert len(summary_errors) == 1
        assert isinstance(summary_errors[0], BackendMonitorError)
        assert (
            summary_errors[0].observer_boundary
            is ObserverFailureBoundary.OPERATION_EXECUTION_TIMEOUT
        )
        assert summary_result == []
        assert connection.close_count == 1
    finally:
        observer.active_summary_release.set()
        reader_release.set()
        monitor.close()
        os.close(read_fd)


def test_session_progresses_monotonically_and_closes_once() -> None:
    session, connection = _session()
    assert session.snapshot().state is ObserverSessionState.CONSTRUCTED

    session.open(1)
    assert session.snapshot().state is ObserverSessionState.REGISTERED
    session.mark_startup_validated()
    assert session.snapshot().state is ObserverSessionState.STARTUP_VALIDATED
    session.activate_and_release(lambda: None)
    assert session.snapshot().state is ObserverSessionState.ACTIVE

    session.close()
    session.close()
    assert session.snapshot().state is ObserverSessionState.CLOSED
    assert connection.close_count == 1


def test_session_rejects_duplicate_open_with_exact_contract_boundary() -> None:
    session, _connection = _session()
    session.open(1)

    with pytest.raises(BackendMonitorError) as captured:
        session.open(1)

    assert captured.value.observer_boundary is (
        ObserverFailureBoundary.CONTRACT_VALIDATION
    )
    session.close()


def test_session_records_observer_construction_failure_once() -> None:
    causality = FailureCausalityAuthority()

    def fail_construction():
        raise RuntimeError("private construction detail")

    with pytest.raises(BackendMonitorError) as captured:
        BackendObserverSession(
            observer_factory=fail_construction,
            connection_factory=_Connection,
            failure_causality=causality,
            child_released=lambda: False,
        )

    assert captured.value.observer_boundary is ObserverFailureBoundary.CONSTRUCTION
    candidate = causality.observe_exception(captured.value)
    assert candidate is not None
    assert candidate.lifecycle_boundary == "observer_construction"
    assert causality.record_exception(
        captured.value,
        code="backend_observer_failed",
        authority_owner="backend_ownership",
        lifecycle_boundary="observer_construction",
        existed_before_child_release=True,
    ) is candidate


def test_session_classifies_connection_creation_failure() -> None:
    causality = FailureCausalityAuthority()
    attempts = 0

    def fail_connection():
        nonlocal attempts
        attempts += 1
        raise OSError("private connection detail")

    session = BackendObserverSession(
        observer_factory=_SessionObserver,
        connection_factory=fail_connection,
        failure_causality=causality,
        child_released=lambda: False,
    )

    with pytest.raises(BackendMonitorError) as captured:
        session.open(2)

    assert attempts == 2
    assert captured.value.observer_boundary is (
        ObserverFailureBoundary.CONNECTION_CREATE
    )
    assert causality.candidates()[0].lifecycle_boundary == (
        "observer_connection_create"
    )


def test_session_classifies_registration_failure_and_closes_candidate() -> None:
    connection = _Connection()
    session, _ = _session(
        observer=_SessionObserver(RuntimeError("private registration detail")),
        connection=connection,
    )

    with pytest.raises(BackendMonitorError) as captured:
        session.open(1)

    assert captured.value.observer_boundary is ObserverFailureBoundary.REGISTRATION
    assert connection.close_count == 1


@pytest.mark.parametrize(
    "boundary",
    [
        ObserverFailureBoundary.STARTUP_SUMMARY,
        ObserverFailureBoundary.ACTIVE_SUMMARY,
        ObserverFailureBoundary.EVENT_APPLY,
        ObserverFailureBoundary.CONTRACT_VALIDATION,
        ObserverFailureBoundary.TERMINAL_WAIT,
    ],
)
def test_session_preserves_exact_operation_failure_boundary(boundary) -> None:
    causality = FailureCausalityAuthority()
    released = [False]
    session, _connection = _session(causality=causality, released=released)
    session.open(1)
    if boundary is not ObserverFailureBoundary.STARTUP_SUMMARY:
        session.mark_startup_validated()
        released[0] = True
        session.activate_and_release(lambda: None)

    def fail(_observer, _connection):
        raise RuntimeError("private operation detail")

    allowed = (
        (ObserverSessionState.REGISTERED,)
        if boundary is ObserverFailureBoundary.STARTUP_SUMMARY
        else (ObserverSessionState.ACTIVE,)
    )
    with pytest.raises(BackendMonitorError) as captured:
        session.run(boundary, fail, allowed_states=allowed)

    assert captured.value.observer_boundary is boundary
    candidate = causality.observe_exception(captured.value)
    assert candidate is not None
    assert boundary is not None
    assert candidate.lifecycle_boundary == boundary.value
    assert candidate.existed_before_child_release is (
        boundary is ObserverFailureBoundary.STARTUP_SUMMARY
    )
    session.close()


def test_session_classifies_closed_active_connection_as_loss() -> None:
    session, connection = _session()
    _activate(session)
    connection.closed = True

    with pytest.raises(BackendMonitorError) as captured:
        session.run(
            ObserverFailureBoundary.ACTIVE_SUMMARY,
            lambda _observer, _connection: (_ for _ in ()).throw(OSError()),
            allowed_states=(ObserverSessionState.ACTIVE,),
        )

    assert captured.value.observer_boundary is (
        ObserverFailureBoundary.CONNECTION_LOST
    )
    session.close()
