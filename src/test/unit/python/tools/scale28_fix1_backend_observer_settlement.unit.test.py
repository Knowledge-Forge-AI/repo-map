from __future__ import annotations

from threading import Event, Thread

import pytest

from actual_refresh_failure_causality import FailureCausalityAuthority
from scale14_actual_refresh_supervisor import ActualRefreshSupervisor
from scale14_supervisor_contracts import validate_backend_summary
from scale15_terminal_contracts import ControlFailure, ControlFailureCode
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
_WAIT_SYNTHETIC_DEADLINE_POLICY = ObserverDeadlinePolicy(
    server_statement_timeout_ms=10,
    client_cancel_after_seconds=0.2,
    cancel_request_timeout_seconds=0.01,
    caller_operation_timeout_seconds=0.25,
)


class _Connection:
    def __init__(self, cancellation_release: Event | None = None) -> None:
        self.broken = False
        self.cancel_count = 0
        self.cancellation_release = cancellation_release
        self.close_count = 0
        self.closed = False

    def cancel_safe(self, *, timeout: float) -> None:
        assert timeout > 0
        self.cancel_count += 1
        if self.cancellation_release is not None:
            self.cancellation_release.set()

    def close(self) -> None:
        self.close_count += 1
        self.closed = True


class _Observer:
    def __init__(self) -> None:
        self.registered_connection = None

    def register_connection(self, connection) -> None:
        self.registered_connection = connection


def _active_session(
    *,
    connection: _Connection | None = None,
    causality: FailureCausalityAuthority | None = None,
    deadline_policy: ObserverDeadlinePolicy = _SYNTHETIC_DEADLINE_POLICY,
) -> tuple[BackendObserverSession, _Connection]:
    exact_connection = connection or _Connection()
    session = BackendObserverSession(
        observer_factory=_Observer,
        connection_factory=lambda: exact_connection,
        failure_causality=causality,
        child_released=lambda: True,
        deadline_policy=deadline_policy,
    )
    session.open(1)
    session.mark_startup_validated()
    session.activate_and_release(lambda: None)
    return session, exact_connection


@pytest.mark.parametrize(
    ("summary", "code"),
    (
        ({"ambient_client": 1}, ControlFailureCode.AMBIENT_CLIENT_DETECTED),
        ({"unknown": 1}, ControlFailureCode.BACKEND_OWNERSHIP_UNKNOWN),
        ({"ambient_client": -1}, ControlFailureCode.BACKEND_OWNERSHIP_UNKNOWN),
        ({"unknown": True}, ControlFailureCode.BACKEND_OWNERSHIP_UNKNOWN),
        ({"unknown": "1"}, ControlFailureCode.BACKEND_OWNERSHIP_UNKNOWN),
        (
            {"direct_owned_client": 1},
            ControlFailureCode.BACKEND_QUIESCENCE_TIMEOUT,
        ),
    ),
)
def test_structured_summary_failure_keeps_identity_and_session(
    summary: dict[str, object],
    code: ControlFailureCode,
) -> None:
    causality = FailureCausalityAuthority()
    session, connection = _active_session(causality=causality)
    created: list[ControlFailure] = []

    def validate(_observer, _connection) -> None:
        try:
            globals()["validate_backend_summary"](summary)
        except ControlFailure as error:
            created.append(error)
            raise

    try:
        with pytest.raises(ControlFailure) as caught:
            session.run(
                ObserverFailureBoundary.CONTRACT_VALIDATION,
                validate,
                allowed_states=(ObserverSessionState.ACTIVE,),
                timeout_seconds=0.2,
            )

        assert caught.value is created[0]
        assert caught.value.code is code
        assert causality.candidates() == ()
        assert session.snapshot().state is ObserverSessionState.ACTIVE

        supervisor = ActualRefreshSupervisor.__new__(ActualRefreshSupervisor)
        supervisor._failure_causality = causality
        supervisor._primary_failure = None
        supervisor._secondary_failures = []
        supervisor._startup = None
        supervisor._last_active_boundary = "active_backend_observation"
        supervisor._record_control_failure(caught.value)
        supervisor._record_control_failure(caught.value)
        assert causality.observe_exception(caught.value) is not None
        assert len(causality.candidates()) == 1
        assert causality.candidates()[0].code == code.value
    finally:
        session.close(timeout_seconds=0.2)
    assert connection.close_count == 1


def test_supervisor_active_probe_uses_session_validation_path() -> None:
    class _Backend:
        def __init__(self) -> None:
            self.validation_calls = 0

        def summary(self) -> dict[str, int]:
            return {"ambient_client": 1}

        def validate_summary(self, summary, validator) -> None:
            self.validation_calls += 1
            validator(summary)

    backend = _Backend()
    supervisor = ActualRefreshSupervisor.__new__(ActualRefreshSupervisor)
    setattr(supervisor, "_backends", backend)
    supervisor._live_backend_valid = True

    with pytest.raises(ControlFailure) as caught:
        supervisor._probe_control_authorities()

    assert caught.value.code is ControlFailureCode.AMBIENT_CLIENT_DETECTED
    assert backend.validation_calls == 1
    assert supervisor._live_backend_valid is False


def test_operation_wait_timeout_does_not_disturb_current_owner() -> None:
    session, connection = _active_session(
        deadline_policy=_WAIT_SYNTHETIC_DEADLINE_POLICY
    )
    owner_entered = Event()
    owner_release = Event()
    owner_errors: list[BaseException] = []

    def own_operation() -> None:
        def _op(_observer, _connection) -> None:
            owner_entered.set()
            owner_release.wait()

        try:
            session.run(
                ObserverFailureBoundary.ACTIVE_SUMMARY,
                _op,
                allowed_states=(ObserverSessionState.ACTIVE,),
                timeout_seconds=1.0,
            )
        except BaseException as error:
            owner_errors.append(error)

    owner = Thread(target=own_operation)
    owner.start()
    assert owner_entered.wait(1)

    try:
        with pytest.raises(BackendMonitorError) as caught:
            session.run(
                ObserverFailureBoundary.EVENT_APPLY,
                lambda _observer, _connection: None,
                allowed_states=(ObserverSessionState.ACTIVE,),
                timeout_seconds=0.02,
            )
        assert caught.value.category == "backend_observer_failed"
        assert (
            caught.value.observer_boundary
            is ObserverFailureBoundary.OPERATION_WAIT_TIMEOUT
        )
        assert session.snapshot().operation_in_flight is True
        assert connection.close_count == 0
    finally:
        owner_release.set()
        owner.join(timeout=1)
        session.close(timeout_seconds=0.2)
    assert not owner.is_alive()
    assert owner_errors == []


def test_operation_execution_timeout_cancels_exact_connection() -> None:
    operation_release = Event()
    connection = _Connection(operation_release)
    session, _connection = _active_session(connection=connection)

    with pytest.raises(BackendMonitorError) as caught:
        session.run(
            ObserverFailureBoundary.ACTIVE_SUMMARY,
            lambda _observer, _connection: operation_release.wait(),
            allowed_states=(ObserverSessionState.ACTIVE,),
            timeout_seconds=0.05,
        )

    assert caught.value.category == "backend_observer_failed"
    assert (
        caught.value.observer_boundary
        is ObserverFailureBoundary.OPERATION_EXECUTION_TIMEOUT
    )
    assert connection.cancel_count == 1
    session.close(timeout_seconds=0.2)
    assert connection.close_count == 1


def test_close_timeout_retains_connection_until_operation_finishes() -> None:
    operation_entered = Event()
    operation_release = Event()
    session, connection = _active_session()
    operation_errors: list[BaseException] = []

    def never_release() -> None:
        def _op(_observer, _connection) -> None:
            operation_entered.set()
            operation_release.wait()

        try:
            session.run(
                ObserverFailureBoundary.ACTIVE_SUMMARY,
                _op,
                allowed_states=(ObserverSessionState.ACTIVE,),
                timeout_seconds=1.0,
            )
        except BaseException as error:
            operation_errors.append(error)

    worker = Thread(target=never_release)
    worker.start()
    assert operation_entered.wait(1)

    try:
        with pytest.raises(BackendMonitorError) as caught:
            session.close(timeout_seconds=0.02)
        assert caught.value.category == "backend_quiescence_timeout"
        assert (
            caught.value.observer_boundary
            is ObserverFailureBoundary.SETTLEMENT_TIMEOUT
        )
        snapshot = session.snapshot()
        assert snapshot.state is ObserverSessionState.CLOSING
        assert snapshot.operation_in_flight is True
        assert connection.close_count == 0
    finally:
        operation_release.set()
        worker.join(timeout=1)
        session.close(timeout_seconds=0.2)
    assert not worker.is_alive()
    assert len(operation_errors) == 1
    assert isinstance(operation_errors[0], BackendMonitorError)
    assert (
        operation_errors[0].observer_boundary
        is ObserverFailureBoundary.OPERATION_EXECUTION_TIMEOUT
    )
    assert connection.close_count == 1


def test_twenty_production_category_preservation_campaigns() -> None:
    cases = (
        ({"ambient_client": 1}, ControlFailureCode.AMBIENT_CLIENT_DETECTED),
        ({"unknown": 1}, ControlFailureCode.BACKEND_OWNERSHIP_UNKNOWN),
        ({"unknown": True}, ControlFailureCode.BACKEND_OWNERSHIP_UNKNOWN),
        (
            {"direct_owned_parallel_worker": 1},
            ControlFailureCode.BACKEND_QUIESCENCE_TIMEOUT,
        ),
    )
    for iteration in range(20):
        causality = FailureCausalityAuthority()
        session, connection = _active_session(causality=causality)
        summary, expected_code = cases[iteration % len(cases)]
        try:
            with pytest.raises(ControlFailure) as caught:
                session.run(
                    ObserverFailureBoundary.CONTRACT_VALIDATION,
                    lambda _observer, _connection: validate_backend_summary(summary),
                    allowed_states=(ObserverSessionState.ACTIVE,),
                    timeout_seconds=0.2,
                )
            exact_error = caught.value
            supervisor = ActualRefreshSupervisor.__new__(ActualRefreshSupervisor)
            supervisor._failure_causality = causality
            supervisor._primary_failure = None
            supervisor._secondary_failures = []
            supervisor._startup = None
            supervisor._last_active_boundary = "active_backend_observation"
            supervisor._record_control_failure(exact_error)

            assert exact_error.code is expected_code
            assert causality.observe_exception(exact_error) is not None
            assert len(causality.candidates()) == 1
            assert session.snapshot().state is ObserverSessionState.ACTIVE
        finally:
            session.close(timeout_seconds=0.2)
        assert connection.close_count == 1


def test_twenty_bounded_observer_settlement_campaigns() -> None:
    for _iteration in range(20):
        operation_entered = Event()
        operation_release = Event()
        session, connection = _active_session()
        operation_errors: list[BaseException] = []

        def hold_operation() -> None:
            def _op(_observer, _connection) -> None:
                operation_entered.set()
                operation_release.wait()

            try:
                session.run(
                    ObserverFailureBoundary.ACTIVE_SUMMARY,
                    _op,
                    allowed_states=(ObserverSessionState.ACTIVE,),
                    timeout_seconds=1.0,
                )
            except BaseException as error:
                operation_errors.append(error)

        worker = Thread(target=hold_operation)
        worker.start()
        assert operation_entered.wait(1)
        try:
            with pytest.raises(BackendMonitorError) as caught:
                session.close(timeout_seconds=0.001)
            assert (
                caught.value.observer_boundary
                is ObserverFailureBoundary.SETTLEMENT_TIMEOUT
            )
            assert connection.close_count == 0
        finally:
            operation_release.set()
            worker.join(timeout=1)
            session.close(timeout_seconds=0.2)
        assert not worker.is_alive()
        assert len(operation_errors) == 1
        assert connection.close_count == 1
