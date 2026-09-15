"""Close, settlement, cancellation dispatch, and quiescence for observer sessions."""

from __future__ import annotations

from threading import Timer
from typing import TYPE_CHECKING

import psycopg

from scale28_backend_observer_session_values import (
    BackendMonitorError,
    ObserverFailureBoundary,
    ObserverSessionState,
    _DEFAULT_OPERATION_TIMEOUT_SECONDS,
)
from scale28_observer_deadlines import (
    ObserverCancellationRequestOutcome,
    ObserverTimeoutMechanism,
)

if TYPE_CHECKING:
    from scale28_backend_observer_session import BackendObserverSession


def is_session_closed_locked(session: BackendObserverSession) -> bool:
    return session._state is ObserverSessionState.CLOSED


def begin_close(session: BackendObserverSession) -> None:
    """Reject new operations before external readers are interrupted."""
    with session._condition:
        if is_session_closed_locked(session):
            return
        session._close_begun = True
        if session._state is not ObserverSessionState.CLOSING:
            session._state = ObserverSessionState.CLOSING
        session._condition.notify_all()


def perform_close(
    session: BackendObserverSession,
    timeout_seconds: float = _DEFAULT_OPERATION_TIMEOUT_SECONDS,
) -> None:
    """Wait for in-flight work and close the exact connection once."""
    timeout = min(
        session._validated_timeout(timeout_seconds, allow_zero=True),
        session._deadline_policy.close_timeout_seconds,
    )
    deadline = session._now() + timeout
    session.begin_close()
    with session._condition:
        if is_session_closed_locked(session):
            return
        if session._close_retry_available:
            if (
                session._operation_in_flight
                or session._cancellation_state.request_in_flight
            ):
                raise session._close_timeout_failure_locked()
            session._close_retry_available = False
            session._close_retry_used = True
        elif not session._cleanup_complete:
            raise session._failure(
                ObserverFailureBoundary.SETTLEMENT_TIMEOUT,
                "backend observer close retry authority is exhausted",
                session._operation_cancellation_error,
                category="backend_quiescence_timeout",
                terminal_secondary=True,
            )
    session._request_active_cancellation(deadline)
    with session._condition:
        while (
            session._operation_in_flight
            or session._cancellation_state.request_in_flight
        ):
            session._classify_operation_settlement_locked()
            remaining = deadline - session._now()
            if remaining <= 0:
                raise session._close_timeout_failure_locked()
            session._condition.wait(remaining)
        if is_session_closed_locked(session):
            return
        while session._close_in_flight:
            remaining = deadline - session._now()
            if remaining <= 0:
                raise session._close_timeout_failure_locked()
            session._condition.wait(remaining)
            if is_session_closed_locked(session):
                return
        connection = session._connection
        if not session._cancellation_state.close_eligible:
            raise session._failure(
                ObserverFailureBoundary.SETTLEMENT_TIMEOUT,
                "backend observer settlement is unproved",
                session._operation_cancellation_error,
                category="backend_quiescence_timeout",
                terminal_secondary=True,
            )
        session._close_in_flight = True
    failure = None
    close = getattr(connection, "close", None)
    if callable(close):
        try:
            close()
        except Exception as cause:
            failure = session._failure(
                ObserverFailureBoundary.LOCAL_CLOSE,
                "backend observer local close failed",
                cause,
                category="backend_quiescence_timeout",
                terminal_secondary=True,
            )
    with session._condition:
        session._close_in_flight = False
        if failure is None:
            session._connection = None
            session._state = ObserverSessionState.CLOSED
            session._quarantined = False
            session._cleanup_complete = True
            session._close_retry_available = False
        else:
            session._quarantined = True
            session._cleanup_complete = False
        session._condition.notify_all()
    if failure is not None:
        raise failure


def close_timeout_failure_locked(
    session: BackendObserverSession,
) -> BackendMonitorError:
    """Record an incomplete quarantined close without touching the connection."""
    if (
        session._operation_in_flight
        and not session._cancellation_state.settlement_limitation
    ):
        session._cancellation_state = (
            session._cancellation_state.record_settlement_limitation()
        )
    if (
        session._cancellation_state.request_in_flight
        and not session._cancellation_state.request_settlement_limitation
    ):
        session._cancellation_state = (
            session._cancellation_state.record_request_settlement_limitation()
        )
    session._quarantined = True
    session._cleanup_complete = False
    if not session._close_retry_used:
        session._close_retry_available = True
    return session._failure(
        ObserverFailureBoundary.SETTLEMENT_TIMEOUT,
        "backend observer settlement timed out",
        session._operation_cancellation_error,
        category="backend_quiescence_timeout",
        terminal_secondary=True,
    )


def expire_operation(
    session: BackendObserverSession,
    operation_generation: int,
) -> None:
    with session._condition:
        if (
            not session._operation_in_flight
            or session._operation_generation != operation_generation
            or session._cancellation_state.cancellation_requested
        ):
            return
        session._cancellation_state = session._cancellation_state.request(
            ObserverTimeoutMechanism.CLIENT_CANCEL_FALLBACK
        )
        connection = session._connection
    session._cancel_connection(
        connection,
        session._deadline_policy.cancel_request_timeout_seconds,
        operation_generation,
    )


def request_active_cancellation(
    session: BackendObserverSession,
    deadline: float,
) -> None:
    with session._condition:
        if (
            not session._operation_in_flight
            or session._cancellation_state.cancellation_requested
        ):
            return
        remaining = deadline - session._now()
        if remaining <= 0:
            return
        session._cancellation_state = session._cancellation_state.request(
            ObserverTimeoutMechanism.CLIENT_CANCEL_FALLBACK
        )
        operation_generation = session._operation_generation
        connection = session._connection
    session._cancel_connection(
        connection,
        min(
            session._deadline_policy.cancel_request_timeout_seconds,
            remaining / 2,
        ),
        operation_generation,
    )


def cancel_connection(
    session: BackendObserverSession,
    connection: object | None,
    timeout_seconds: float,
    operation_generation: int,
) -> None:
    cancel = getattr(connection, "cancel_safe", None)
    if not callable(cancel):
        session._record_cancellation_result(
            operation_generation,
            RuntimeError("backend observer cancellation is unavailable"),
        )
        return
    dispatched_at = session._now()
    with session._condition:
        session._cancellation_dispatched_at[operation_generation] = (
            dispatched_at
        )
    try:
        cancel(timeout=timeout_seconds)
    except Exception as error:
        session._record_cancellation_result(operation_generation, error)
    else:
        session._record_cancellation_result(operation_generation, None)


def record_cancellation_result(
    session: BackendObserverSession,
    operation_generation: int,
    error: Exception | None,
) -> None:
    outcome = ObserverCancellationRequestOutcome.REQUEST_SUCCEEDED
    if isinstance(error, psycopg.errors.CancellationTimeout):
        outcome = ObserverCancellationRequestOutcome.REQUEST_TIMED_OUT
    elif error is not None:
        outcome = ObserverCancellationRequestOutcome.REQUEST_FAILED
    with session._condition:
        if session._operation_generation != operation_generation:
            session._cancellation_dispatched_at.pop(
                operation_generation,
                None,
            )
            return
        dispatched_at = session._cancellation_dispatched_at.pop(
            operation_generation,
            None,
        )
        if (
            dispatched_at is not None
            and session._now() - dispatched_at
            > session._deadline_policy.request_terminal_timeout_seconds
        ):
            session._cancellation_state = (
                session._cancellation_state
                .record_request_settlement_limitation()
            )
        session._cancellation_state = (
            session._cancellation_state.record_request_outcome(outcome)
        )
        session._operation_cancellation_error = error
        session._condition.notify_all()


def classify_operation_settlement_locked(
    session: BackendObserverSession,
) -> None:
    """Record D_op expiry at a safe observation point without reclamation."""
    if (
        not session._operation_in_flight
        or session._operation_dispatched_at is None
        or session._cancellation_state.settlement_limitation
        or session._now() - session._operation_dispatched_at
        < session._deadline_policy.operation_settlement_timeout_seconds
    ):
        return
    session._cancellation_state = (
        session._cancellation_state.record_settlement_limitation()
    )


def settle_operation(
    session: BackendObserverSession,
    timer: Timer | None,
    deadline: float,
) -> None:
    if timer is not None:
        timer.cancel()
        timer.join(timeout=max(0.0, deadline - session._now()))
    with session._condition:
        session._classify_operation_settlement_locked()
        session._operation_in_flight = False
        session._active_operation = None
        session._operation_thread = None
        session._operation_dispatched_at = None
        session._cancellation_state = (
            session._cancellation_state.settle_operation()
        )
        session._condition.notify_all()


def execution_timeout(
    session: BackendObserverSession,
    category: str,
    cause: Exception | None = None,
) -> BackendMonitorError:
    with session._condition:
        cancellation_error = session._operation_cancellation_error
        if session._state is not ObserverSessionState.CLOSING:
            session._state = ObserverSessionState.FAILED
    return session._failure(
        ObserverFailureBoundary.OPERATION_EXECUTION_TIMEOUT,
        "backend observer operation execution timed out",
        cause or cancellation_error,
        category=category,
        timeout_mechanism=ObserverTimeoutMechanism.CLIENT_CANCEL_FALLBACK,
        cancellation_limitation=session._cancellation_limitation(
            cancellation_error
        ),
    )


def query_canceled_failure(
    session: BackendObserverSession,
    category: str,
    cause: psycopg.errors.QueryCanceled,
) -> BackendMonitorError:
    primary = str(getattr(getattr(cause, "diag", None), "message_primary", ""))
    if "statement timeout" in primary.lower():
        return session._failure(
            ObserverFailureBoundary.OPERATION_EXECUTION_TIMEOUT,
            "backend observer operation execution timed out",
            cause,
            category=category,
            timeout_mechanism=(
                ObserverTimeoutMechanism.SERVER_STATEMENT_TIMEOUT
            ),
        )
    return session._failure(
        ObserverFailureBoundary.UNEXPECTED_CANCELLATION,
        "backend observer operation was unexpectedly canceled",
        cause,
        category=category,
        timeout_mechanism=(
            ObserverTimeoutMechanism.UNEXPECTED_QUERY_CANCELED
        ),
    )
