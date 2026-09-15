"""Connection startup, registration, and activation helpers for observer sessions."""

from __future__ import annotations

import inspect
from threading import get_ident
from typing import TYPE_CHECKING, Callable, Iterable

import psycopg

from scale28_backend_observer_session_values import (
    BackendMonitorError,
    ConnectionFactory,
    ObserverFailureBoundary,
    ObserverSessionState,
)
from scale28_observer_deadlines import (
    ObserverConnectionSettings,
    ObserverOperationClass,
)

if TYPE_CHECKING:
    from scale28_backend_observer_session import BackendObserverSession


def configure_bounded_connection(connection: object) -> None:
    """Verify cancel safety when connected through PostgreSQL."""
    if not isinstance(connection, psycopg.Connection):
        return
    if not psycopg.capabilities.has_cancel_safe():
        raise BackendMonitorError(
            "backend observer bounded cancellation is unavailable",
            category="backend_observer_failed",
            observer_boundary=ObserverFailureBoundary.REGISTRATION,
        )


def connection_failure_boundary(
    cause: Exception,
) -> ObserverFailureBoundary:
    """Classify connection creation causes against operational timeouts."""
    if isinstance(cause, psycopg.OperationalError) and "timeout" in str(
        cause
    ).lower():
        return ObserverFailureBoundary.CONNECTION_TIMEOUT
    return ObserverFailureBoundary.CONNECTION_CREATE


def create_connection(
    connection_factory: ConnectionFactory,
    connection_settings: ObserverConnectionSettings,
) -> object:
    """Create one connection through the validated startup policy."""
    try:
        signature = inspect.signature(connection_factory)
        signature.bind(connection_settings)
    except (TypeError, ValueError):
        return connection_factory()
    return connection_factory(connection_settings)


def perform_open(session: BackendObserverSession, attempts: int) -> None:
    """Create and register one exact connection with bounded startup retry."""
    if attempts < 1:
        raise ValueError("observer registration attempts are invalid")
    with session._condition:
        if session._state is not ObserverSessionState.CONSTRUCTED:
            raise session._invalid_state("backend observer session cannot start")
    last_cause: Exception | None = None
    last_boundary = ObserverFailureBoundary.CONNECTION_CREATE
    for _attempt in range(attempts):
        connection = None
        try:
            connection = session._create_connection()
            with session._condition:
                session._state = ObserverSessionState.CONNECTION_CREATED
            session._configure_bounded_connection(connection)
            last_boundary = ObserverFailureBoundary.REGISTRATION
            session._observer.register_connection(connection)
            with session._condition:
                session._connection = connection
                session._state = ObserverSessionState.REGISTERED
            return
        except Exception as cause:
            last_cause = cause
            if connection is None:
                last_boundary = session._connection_failure_boundary(cause)
            close = getattr(connection, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
            with session._condition:
                session._connection = None
                session._state = ObserverSessionState.CONSTRUCTED
    assert last_cause is not None
    with session._condition:
        session._state = ObserverSessionState.FAILED
    message = (
        "backend observer connection creation failed"
        if last_boundary is ObserverFailureBoundary.CONNECTION_CREATE
        else "backend observer registration failed"
    )
    raise session._failure(last_boundary, message, last_cause) from last_cause


def mark_startup_validated(session: BackendObserverSession) -> None:
    with session._condition:
        if session._state is ObserverSessionState.ACTIVE:
            return
        if session._state is not ObserverSessionState.REGISTERED:
            raise session._invalid_state(
                "backend observer startup validation is out of order",
                ObserverFailureBoundary.CONTRACT_VALIDATION,
            )
        session._state = ObserverSessionState.STARTUP_VALIDATED


def activate_legacy_monitor(session: BackendObserverSession) -> None:
    """Preserve standalone monitor use that has no child-release authority."""
    with session._condition:
        if session._state is not ObserverSessionState.REGISTERED:
            raise session._invalid_state(
                "backend observer activation is out of order",
                ObserverFailureBoundary.CONTRACT_VALIDATION,
            )
        session._state = ObserverSessionState.ACTIVE


def activate_and_release(
    session: BackendObserverSession,
    release: Callable[[], None],
) -> None:
    """Make the session active before atomically releasing the child."""
    with session._condition:
        if session._state is ObserverSessionState.ACTIVE:
            release()
            return
        if (
            session._state is not ObserverSessionState.STARTUP_VALIDATED
            or session._operation_in_flight
            or session._close_begun
        ):
            raise session._invalid_state(
                "backend observer activation is out of order",
                ObserverFailureBoundary.CONTRACT_VALIDATION,
            )
        session._state = ObserverSessionState.ACTIVE
        try:
            release()
        except Exception as cause:
            session._state = ObserverSessionState.FAILED
            raise session._failure(
                ObserverFailureBoundary.CONTRACT_VALIDATION,
                "backend observer child release failed",
                cause,
            ) from cause


def acquire_operation(
    session: BackendObserverSession,
    boundary: ObserverFailureBoundary,
    allowed_states: Iterable[ObserverSessionState],
    deadline: float,
    exact_operation_class: ObserverOperationClass,
    category: str,
) -> tuple[object, float | None, int]:
    """Acquire and reserve the session for one bounded operation."""
    allowed = frozenset(allowed_states)
    event_apply = boundary is ObserverFailureBoundary.EVENT_APPLY
    with session._condition:
        if event_apply:
            session._event_apply_waiters += 1
        try:
            while (
                session._operation_in_flight
                or session._cancellation_state.request_in_flight
                or (not event_apply and session._event_apply_waiters)
            ) and not session._close_begun:
                remaining = deadline - session._now()
                if remaining <= 0:
                    raise session._failure(
                        ObserverFailureBoundary.OPERATION_WAIT_TIMEOUT,
                        "backend observer operation acquisition timed out",
                        None,
                        category=category,
                    )
                session._condition.wait(remaining)
        finally:
            if event_apply:
                session._event_apply_waiters -= 1
                session._condition.notify_all()
        if session._close_begun or session._state not in allowed:
            if session._close_begun:
                raise BackendMonitorError(
                    "backend observer operation is outside its session lifetime",
                    category=category,
                    observer_boundary=ObserverFailureBoundary.LOCAL_CLOSE,
                )
            raise session._invalid_state(
                "backend observer operation is outside its session lifetime",
                boundary,
                category=category,
            )
        remaining = deadline - session._now()
        if remaining <= 0:
            raise session._failure(
                ObserverFailureBoundary.OPERATION_WAIT_TIMEOUT,
                "backend observer operation acquisition timed out",
                None,
                category=category,
            )
        execution_seconds: float | None = None
        if exact_operation_class is ObserverOperationClass.SQL_BOUNDED:
            try:
                execution_seconds, _request_seconds = (
                    session._deadline_policy.operation_deadlines(remaining)
                )
            except ValueError as cause:
                raise session._failure(
                    ObserverFailureBoundary.OPERATION_WAIT_TIMEOUT,
                    "backend observer SQL authority is insufficient",
                    cause,
                    category=category,
                ) from cause
        connection = session._connection
        if connection is None:
            raise session._invalid_state(
                "backend observer connection is unavailable",
                ObserverFailureBoundary.CONNECTION_LOST,
                category=category,
            )
        session._operation_in_flight = True
        session._active_operation = boundary
        session._operation_thread = get_ident()
        session._operation_generation += 1
        operation_generation = session._operation_generation
        session._cancellation_state = session._cancellation_state.begin_operation()
        session._operation_cancellation_error = None
        session._operation_dispatched_at = session._now()
    return connection, execution_seconds, operation_generation


def before_child_release(child_released: Callable[[], bool] | None) -> bool:
    if child_released is None:
        return False
    try:
        return not bool(child_released())
    except Exception:
        return False
