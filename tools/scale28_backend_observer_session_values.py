"""Private vocabulary, contracts, and snapshot types for observer sessions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from typing import TYPE_CHECKING, Callable, Protocol

import psycopg

from scale28_observer_deadlines import (
    ObserverCancellationLimitation,
    ObserverCancellationState,
    ObserverOperationClass,
    ObserverTimeoutMechanism,
)

if TYPE_CHECKING:
    from scale28_backend_observer_session import BackendObserverSession

_DEFAULT_OPERATION_TIMEOUT_SECONDS = 5.0


class ObserverFailureBoundary(str, Enum):
    """Closed private vocabulary for backend-observer failures."""

    CONSTRUCTION = "observer_construction"
    CONNECTION_CREATE = "observer_connection_create"
    CONNECTION_TIMEOUT = "observer_connection_timeout"
    REGISTRATION = "observer_registration"
    STARTUP_SUMMARY = "observer_startup_summary"
    ACTIVE_SUMMARY = "observer_active_summary"
    EVENT_APPLY = "observer_event_apply"
    CONTRACT_VALIDATION = "observer_contract_validation"
    CONNECTION_LOST = "observer_connection_lost"
    IDENTITY_CHANGED = "observer_identity_changed"
    RESOURCE_READ = "observer_resource_read"
    LOCAL_CLOSE = "observer_local_close"
    TERMINAL_WAIT = "observer_terminal_wait"
    OPERATION_WAIT_TIMEOUT = "observer_operation_wait_timeout"
    OPERATION_EXECUTION_TIMEOUT = "observer_operation_execution_timeout"
    UNEXPECTED_CANCELLATION = "observer_unexpected_cancellation"
    SETTLEMENT_TIMEOUT = "observer_settlement_timeout"


class ObserverSessionState(str, Enum):
    """Monotonic lifetime states for one live observer connection."""

    CONSTRUCTED = "constructed"
    CONNECTION_CREATED = "connection_created"
    REGISTERED = "registered"
    STARTUP_VALIDATED = "startup_validated"
    ACTIVE = "active"
    FAILED = "failed"
    CLOSING = "closing"
    CLOSED = "closed"


class BackendObserverProtocol(Protocol):
    """Structural contract for backend observer instances."""

    def register_connection(self, connection: object, /) -> object:
        ...


ConnectionFactory = Callable[..., object]


@dataclass(frozen=True)
class ObserverSessionSnapshot:
    """Private bounded state without connection or backend identity values."""

    state: ObserverSessionState
    active_operation: ObserverFailureBoundary | None
    operation_thread: int | None
    operation_in_flight: bool
    close_begun: bool
    cancellation: ObserverCancellationState
    quarantined: bool
    cleanup_complete: bool
    close_retry_available: bool
    close_retry_used: bool


class BackendMonitorError(RuntimeError):
    """Raised when backend telemetry or ownership cannot be proven."""

    observer_snapshot: ObserverSessionSnapshot | None
    test_injected: bool

    def __init__(
        self,
        message: str,
        *,
        category: str,
        observer_boundary: ObserverFailureBoundary | None = None,
        observer_timeout_mechanism: ObserverTimeoutMechanism | None = None,
        observer_cancellation_limitation: (
            ObserverCancellationLimitation | None
        ) = None,
        observer_snapshot: ObserverSessionSnapshot | None = None,
        test_injected: bool = False,
    ) -> None:
        self.category = category
        self.observer_boundary = observer_boundary
        self.observer_timeout_mechanism = observer_timeout_mechanism
        self.observer_cancellation_limitation = observer_cancellation_limitation
        self.observer_snapshot = observer_snapshot
        self.test_injected = test_injected
        super().__init__(message)


def build_session_snapshot(
    session: BackendObserverSession,
) -> ObserverSessionSnapshot:
    """Construct an immutable observer session snapshot under session lock."""
    with session._condition:
        session._classify_operation_settlement_locked()
        return ObserverSessionSnapshot(
            session._state,
            session._active_operation,
            session._operation_thread,
            session._operation_in_flight,
            session._close_begun,
            session._cancellation_state,
            session._quarantined,
            session._cleanup_complete,
            session._close_retry_available,
            session._close_retry_used,
        )


def validated_timeout(
    timeout_seconds: float,
    *,
    allow_zero: bool = False,
) -> float:
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or timeout_seconds < 0
        or (timeout_seconds == 0 and not allow_zero)
    ):
        raise ValueError("backend observer timeout is invalid")
    return float(timeout_seconds)


def operation_class_for(
    boundary: ObserverFailureBoundary,
) -> ObserverOperationClass:
    if boundary is ObserverFailureBoundary.CONTRACT_VALIDATION:
        return ObserverOperationClass.SERIALIZATION_ONLY
    return ObserverOperationClass.SQL_BOUNDED


def cancellation_limitation(
    error: Exception | None,
) -> ObserverCancellationLimitation | None:
    if error is None:
        return None
    if isinstance(error, psycopg.errors.CancellationTimeout):
        return ObserverCancellationLimitation.CANCELLATION_TIMEOUT
    return ObserverCancellationLimitation.CANCELLATION_FAILURE


def failure_boundary(
    boundary: ObserverFailureBoundary,
    connection: object,
    cause: Exception,
) -> ObserverFailureBoundary:
    if bool(getattr(connection, "closed", False)) or bool(
        getattr(connection, "broken", False)
    ):
        return ObserverFailureBoundary.CONNECTION_LOST
    if bool(getattr(cause, "observer_identity_changed", False)):
        return ObserverFailureBoundary.IDENTITY_CHANGED
    return boundary


def session_failure(
    session: BackendObserverSession,
    boundary: ObserverFailureBoundary,
    message: str,
    cause: Exception | None,
    *,
    category: str = "backend_observer_failed",
    terminal_secondary: bool | None = None,
    timeout_mechanism: ObserverTimeoutMechanism | None = None,
    cancellation_limitation: ObserverCancellationLimitation | None = None,
) -> BackendMonitorError:
    """Record observer failures with causality tracking and snapshot state."""
    error = BackendMonitorError(
        message,
        category=category,
        observer_boundary=boundary,
        observer_timeout_mechanism=timeout_mechanism,
        observer_cancellation_limitation=cancellation_limitation,
    )
    error.observer_snapshot = session.snapshot()
    if cause is not None:
        error.__cause__ = cause
        if bool(getattr(cause, "test_injected", False)):
            error.test_injected = True
    if session._failure_causality is not None:
        candidates = session._failure_causality.candidates()
        session._failure_causality.record_exception(
            error,
            code=category,
            authority_owner=(
                "resource_sampling"
                if category == "resource_reader_unavailable"
                else "backend_ownership"
            ),
            lifecycle_boundary=boundary.value,
            existed_before_child_release=session._before_child_release(),
            test_injected=bool(getattr(error, "test_injected", False)),
            terminal_secondary=(
                bool(candidates)
                if terminal_secondary is None
                else terminal_secondary
            ),
        )
    return error
