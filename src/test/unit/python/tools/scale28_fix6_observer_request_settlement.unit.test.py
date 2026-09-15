from __future__ import annotations

from threading import Event, Thread

import pytest

import scale14_backend_monitor
from scale28_backend_observer_session import (
    BackendMonitorError,
    BackendObserverSession,
    ObserverFailureBoundary,
    ObserverSessionState,
)
from scale28_observer_deadlines import (
    DEFAULT_OBSERVER_DEADLINE_POLICY,
    ObserverCancellationRequestOutcome,
    ObserverCancellationState,
    ObserverDeadlinePolicy,
    ObserverTimeoutMechanism,
)


class _Observer:
    def register_connection(self, _connection: object) -> None:
        return None


class _HeldCancellationConnection:
    def __init__(self) -> None:
        self.broken = False
        self.closed = False
        self.close_count = 0
        self.close_while_request_active = False
        self.cancel_started = Event()
        self.allow_cancel_return = Event()
        self.cancel_finished = Event()
        self.close_called = Event()

    def cancel_safe(self, *, timeout: float) -> None:
        assert timeout > 0
        self.cancel_started.set()
        try:
            assert self.allow_cancel_return.wait(1.0)
        finally:
            self.cancel_finished.set()

    def close(self) -> None:
        self.close_while_request_active = not self.cancel_finished.is_set()
        self.close_count += 1
        self.closed = True
        self.close_called.set()


def _active_session(
    connection: _HeldCancellationConnection,
    policy: ObserverDeadlinePolicy,
) -> BackendObserverSession:
    session = BackendObserverSession(
        observer_factory=_Observer,
        connection_factory=lambda: connection,
        failure_causality=None,
        child_released=lambda: True,
        deadline_policy=policy,
    )
    session.open(1)
    session.mark_startup_validated()
    session.activate_and_release(lambda: None)
    return session


def test_local_close_waits_for_operation_and_cancellation_request_settlement() -> None:
    policy = ObserverDeadlinePolicy(
        server_statement_timeout_ms=10,
        client_cancel_after_seconds=0.02,
        cancel_request_timeout_seconds=0.2,
        caller_operation_timeout_seconds=0.25,
    )
    connection = _HeldCancellationConnection()
    session = _active_session(connection, policy)
    operation_started = Event()
    allow_operation_return = Event()
    operation_finished = Event()
    close_invoked = Event()
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
                timeout_seconds=0.25,
            )
        except BaseException as error:
            operation_failures.append(error)
        finally:
            operation_finished.set()

    def close_session() -> None:
        close_invoked.set()
        try:
            session.close(timeout_seconds=0.5)
        except BaseException as error:
            close_failures.append(error)

    operation_thread = Thread(target=run_operation)
    close_thread = Thread(target=close_session)
    operation_thread.start()
    try:
        assert operation_started.wait(1.0)
        assert connection.cancel_started.wait(1.0)
        allow_operation_return.set()
        assert operation_finished.wait(1.0)
        assert session.snapshot().operation_in_flight is False
        assert connection.cancel_finished.is_set() is False

        close_thread.start()
        assert close_invoked.wait(1.0)
        assert connection.close_called.wait(0.05) is False
        assert close_thread.is_alive() is True

        connection.allow_cancel_return.set()
        close_thread.join(1.0)
        assert close_thread.is_alive() is False
        assert close_failures == []
        assert connection.close_count == 1
        assert connection.close_while_request_active is False
        snapshot = session.snapshot()
        assert snapshot.cancellation.request_in_flight is False
        assert snapshot.cancellation.operation_settled is True
        assert snapshot.cancellation.close_eligible is True
        assert isinstance(operation_failures[0], BackendMonitorError)
    finally:
        allow_operation_return.set()
        connection.allow_cancel_return.set()
        operation_thread.join(1.0)
        if close_thread.ident is not None:
            close_thread.join(1.0)
        if not connection.closed:
            session.close()


def test_close_eligibility_requires_request_and_operation_settlement() -> None:
    requested = (
        ObserverCancellationState()
        .begin_operation()
        .request(ObserverTimeoutMechanism.CLIENT_CANCEL_FALLBACK)
    )

    assert requested.request_in_flight is True
    assert requested.close_eligible is False

    operation_settled = requested.settle_operation()
    assert operation_settled.operation_settled is True
    assert operation_settled.request_in_flight is True
    assert operation_settled.close_eligible is False

    request_settled = operation_settled.record_request_outcome(
        ObserverCancellationRequestOutcome.REQUEST_SUCCEEDED
    )
    assert request_settled.request_in_flight is False
    assert request_settled.close_eligible is True


def test_zero_budget_close_does_not_create_an_unsettleable_request() -> None:
    policy = ObserverDeadlinePolicy(
        server_statement_timeout_ms=10,
        client_cancel_after_seconds=0.2,
        cancel_request_timeout_seconds=0.01,
        caller_operation_timeout_seconds=0.25,
    )
    connection = _HeldCancellationConnection()
    session = _active_session(connection, policy)
    operation_started = Event()
    allow_operation_return = Event()
    operation_finished = Event()
    operation_failures: list[BaseException] = []

    def operation(_observer: object, _connection: object) -> None:
        operation_started.set()
        assert allow_operation_return.wait(1.0)

    def run_operation() -> None:
        try:
            session.run(
                ObserverFailureBoundary.ACTIVE_SUMMARY,
                operation,
                allowed_states=(ObserverSessionState.ACTIVE,),
                timeout_seconds=0.25,
            )
        except BaseException as error:
            operation_failures.append(error)
        finally:
            operation_finished.set()

    operation_thread = Thread(target=run_operation)
    operation_thread.start()
    try:
        assert operation_started.wait(1.0)
        with pytest.raises(BackendMonitorError) as settlement:
            session.close(timeout_seconds=0)
        assert settlement.value.observer_boundary is (
            ObserverFailureBoundary.SETTLEMENT_TIMEOUT
        )
        snapshot = session.snapshot()
        assert snapshot.cancellation.cancellation_requested is False
        assert snapshot.cancellation.request_in_flight is False

        allow_operation_return.set()
        assert operation_finished.wait(1.0)
        assert operation_failures == []
        session.close()
        assert connection.close_count == 1
    finally:
        allow_operation_return.set()
        operation_thread.join(1.0)
        if not connection.closed:
            session.close()


def test_rejected_candidate_exhausts_the_configured_handoff_margin() -> None:
    candidate = ObserverDeadlinePolicy(
        server_statement_timeout_ms=400,
        client_cancel_after_seconds=0.42,
        cancel_request_timeout_seconds=0.12,
        caller_operation_timeout_seconds=0.57,
    )

    trigger, request_bound = candidate.operation_deadlines(0.54)
    assert trigger == pytest.approx(0.42)
    assert request_bound == pytest.approx(0.12)
    assert trigger + request_bound == pytest.approx(0.54)
    assert candidate.caller_operation_timeout_seconds + 0.05 > 0.6


def test_fix12_corrected_request_bound_replaces_the_prior_product_default() -> None:
    policy = DEFAULT_OBSERVER_DEADLINE_POLICY

    assert (
        policy.connection_timeout_seconds,
        policy.server_statement_timeout_ms,
        policy.client_cancel_after_seconds,
        policy.cancel_request_timeout_seconds,
        policy.caller_operation_timeout_seconds,
    ) == (2, 400, 0.45, 0.25, 0.5)
    assert scale14_backend_monitor._OWNERSHIP_HANDOFF_SECONDS == 0.6


@pytest.mark.parametrize(
    "boundary",
    (
        ObserverFailureBoundary.STARTUP_SUMMARY,
        ObserverFailureBoundary.ACTIVE_SUMMARY,
        ObserverFailureBoundary.EVENT_APPLY,
        ObserverFailureBoundary.CONTRACT_VALIDATION,
        ObserverFailureBoundary.RESOURCE_READ,
        ObserverFailureBoundary.TERMINAL_WAIT,
        ObserverFailureBoundary.LOCAL_CLOSE,
    ),
)
def test_retained_product_tuple_runs_each_operation_boundary(
    boundary: ObserverFailureBoundary,
) -> None:
    connection = _HeldCancellationConnection()
    session = _active_session(connection, DEFAULT_OBSERVER_DEADLINE_POLICY)
    try:
        result = session.run(
            boundary,
            lambda _observer, _connection: boundary.value,
            allowed_states=(ObserverSessionState.ACTIVE,),
            timeout_seconds=scale14_backend_monitor._OWNERSHIP_HANDOFF_SECONDS,
        )
    finally:
        session.close()

    assert result == boundary.value
    assert connection.close_count == 1
