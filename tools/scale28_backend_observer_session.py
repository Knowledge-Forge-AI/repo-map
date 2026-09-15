"""Private live backend-observer session and operation-lifetime authority."""

from __future__ import annotations

from threading import Condition, Timer
from time import monotonic as _monotonic
from typing import Callable, Generic, Iterable
from typing_extensions import TypeVar

import psycopg

from actual_refresh_failure_causality import FailureCausalityAuthority
from repomap_kg.storage.backend_observer import BackendObservationError
from repomap_kg.storage.backend_telemetry_contracts import ConnectionTelemetryError
from scale15_terminal_contracts import ControlFailure
from scale28_backend_observer_session_cleanup import (
    begin_close as _begin_close_func,
    cancel_connection as _cancel_connection_func,
    classify_operation_settlement_locked as _classify_operation_settlement_locked_func,
    close_timeout_failure_locked as _close_timeout_failure_locked_func,
    execution_timeout as _execution_timeout_func,
    expire_operation as _expire_operation_func,
    perform_close as _perform_close_func,
    query_canceled_failure as _query_canceled_failure_func,
    record_cancellation_result as _record_cancellation_result_func,
    request_active_cancellation as _request_active_cancellation_func,
    settle_operation as _settle_operation_func,
)
from scale28_backend_observer_session_startup import (
    acquire_operation as _acquire_operation_func,
    activate_and_release as _activate_and_release_func,
    activate_legacy_monitor as _activate_legacy_monitor_func,
    before_child_release as _before_child_release_func,
    configure_bounded_connection as _configure_bounded_connection_func,
    connection_failure_boundary as _connection_failure_boundary_func,
    create_connection as _create_connection_func,
    mark_startup_validated as _mark_startup_validated_func,
    perform_open as _perform_open_func,
)
from scale28_backend_observer_session_values import (
    _DEFAULT_OPERATION_TIMEOUT_SECONDS,
    BackendMonitorError,
    BackendObserverProtocol,
    ConnectionFactory,
    ObserverFailureBoundary,
    ObserverSessionSnapshot,
    ObserverSessionState,
    build_session_snapshot as _build_session_snapshot_func,
    cancellation_limitation as _cancellation_limitation_func,
    failure_boundary as _failure_boundary_func,
    operation_class_for as _operation_class_for_func,
    session_failure as _session_failure_func,
    validated_timeout as _validated_timeout_func,
)
from scale28_observer_deadlines import (
    DEFAULT_OBSERVER_DEADLINE_POLICY,
    ObserverCancellationLimitation,
    ObserverCancellationState,
    ObserverConnectionSettings,
    ObserverDeadlinePolicy,
    ObserverOperationClass,
    ObserverTimeoutMechanism,
)

__all__ = [
    "BackendMonitorError",
    "BackendObserverProtocol",
    "BackendObserverSession",
    "ConnectionFactory",
    "ObserverFailureBoundary",
    "ObserverSessionSnapshot",
    "ObserverSessionState",
    "_DEFAULT_OPERATION_TIMEOUT_SECONDS",
]

_ObserverT = TypeVar(
    "_ObserverT",
    bound=BackendObserverProtocol,
    default=BackendObserverProtocol,
    covariant=True,
)
_ResultT = TypeVar("_ResultT")


class BackendObserverSession(Generic[_ObserverT]):
    """Own and serialize one observer, connection, identity, and close."""

    _connection_failure_boundary = staticmethod(_connection_failure_boundary_func)
    _validated_timeout = staticmethod(_validated_timeout_func)
    _cancellation_limitation = staticmethod(_cancellation_limitation_func)
    _operation_class_for = staticmethod(_operation_class_for_func)

    @staticmethod
    def _now() -> float:
        return _monotonic()

    def __init__(
        self,
        *,
        observer_factory: Callable[[], _ObserverT],
        connection_factory: ConnectionFactory,
        failure_causality: FailureCausalityAuthority | None,
        child_released: Callable[[], bool] | None,
        deadline_policy: ObserverDeadlinePolicy = DEFAULT_OBSERVER_DEADLINE_POLICY,
    ) -> None:
        self._connection_factory = connection_factory
        self._failure_causality = failure_causality
        self._child_released = child_released
        self._deadline_policy = deadline_policy
        self._connection_settings = ObserverConnectionSettings.from_policy(
            deadline_policy
        )
        self._condition = Condition()
        self._state = ObserverSessionState.CONSTRUCTED
        self._connection: object | None = None
        self._active_operation: ObserverFailureBoundary | None = None
        self._operation_thread: int | None = None
        self._operation_in_flight = False
        self._event_apply_waiters = 0
        self._operation_generation = 0
        self._operation_dispatched_at: float | None = None
        self._cancellation_state = ObserverCancellationState()
        self._cancellation_dispatched_at: dict[int, float] = {}
        self._operation_cancellation_error: Exception | None = None
        self._close_begun = False
        self._close_in_flight = False
        self._quarantined = False
        self._cleanup_complete = True
        self._close_retry_available = False
        self._close_retry_used = False
        try:
            self._observer = observer_factory()
        except Exception as cause:
            self._state = ObserverSessionState.FAILED
            raise self._failure(
                ObserverFailureBoundary.CONSTRUCTION,
                "backend observer construction failed",
                cause,
            ) from cause

    @property
    def is_registered(self) -> bool:
        with self._condition:
            return self._state in {
                ObserverSessionState.REGISTERED,
                ObserverSessionState.STARTUP_VALIDATED,
                ObserverSessionState.ACTIVE,
            }

    def open(self, attempts: int) -> None:
        """Create and register one exact connection with bounded startup retry."""
        _perform_open_func(self, attempts)

    def run(
        self,
        boundary: ObserverFailureBoundary,
        operation: Callable[[_ObserverT, object], _ResultT],
        *,
        allowed_states: Iterable[ObserverSessionState],
        category: str = "backend_observer_failed",
        operation_class: ObserverOperationClass | None = None,
        timeout_seconds: float = _DEFAULT_OPERATION_TIMEOUT_SECONDS,
    ) -> _ResultT:
        """Run one bounded operation without concurrent use or close."""

        timeout = self._validated_timeout(timeout_seconds)
        deadline = _monotonic() + timeout
        exact_operation_class = (
            operation_class or self._operation_class_for(boundary)
        )
        connection, execution_seconds, operation_generation = (
            _acquire_operation_func(
                self,
                boundary,
                allowed_states,
                deadline,
                exact_operation_class,
                category,
            )
        )
        timer: Timer | None = None
        if execution_seconds is not None:
            timer = Timer(
                execution_seconds,
                self._expire_operation,
                args=(operation_generation,),
            )
            timer.name = "scale28-backend-observer-deadline"
            timer.daemon = True
            timer.start()
        try:
            result = operation(self._observer, connection)
            if (
                exact_operation_class is ObserverOperationClass.SQL_BOUNDED
                and _monotonic() >= deadline
                and not self._operation_expired(operation_generation)
            ):
                self._expire_operation(operation_generation)
            if (
                exact_operation_class is ObserverOperationClass.SQL_BOUNDED
                and self._operation_expired(operation_generation)
            ):
                raise self._execution_timeout(category)
            if (
                exact_operation_class
                is ObserverOperationClass.SERIALIZATION_ONLY
                and _monotonic() >= deadline
            ):
                raise self._failure(
                    ObserverFailureBoundary.OPERATION_EXECUTION_TIMEOUT,
                    "backend observer serialization timed out",
                    None,
                    category=category,
                )
            return result
        except ControlFailure:
            raise
        except BackendMonitorError:
            with self._condition:
                if self._state is not ObserverSessionState.CLOSING:
                    self._state = ObserverSessionState.FAILED
            raise
        except Exception as cause:
            if self._operation_expired(operation_generation):
                raise self._execution_timeout(category, cause) from cause
            if isinstance(cause, psycopg.errors.QueryCanceled):
                raise self._query_canceled_failure(category, cause) from cause
            exact_boundary = self._failure_boundary(boundary, connection, cause)
            exact_category = (
                "backend_telemetry_failed"
                if boundary is ObserverFailureBoundary.EVENT_APPLY
                and isinstance(
                    cause,
                    (BackendObservationError, ConnectionTelemetryError),
                )
                else category
            )
            with self._condition:
                if self._state is not ObserverSessionState.CLOSING:
                    self._state = ObserverSessionState.FAILED
            raise self._failure(
                exact_boundary,
                "backend observer operation failed",
                cause,
                category=exact_category,
            ) from cause
        finally:
            _settle_operation_func(self, timer, deadline)

    def mark_startup_validated(self) -> None:
        _mark_startup_validated_func(self)

    def activate_legacy_monitor(self) -> None:
        """Preserve standalone monitor use that has no child-release authority."""
        _activate_legacy_monitor_func(self)

    def activate_and_release(self, release: Callable[[], None]) -> None:
        """Make the session active before atomically releasing the child."""
        _activate_and_release_func(self, release)

    def begin_close(self) -> None:
        """Reject new operations before external readers are interrupted."""
        _begin_close_func(self)

    def close(
        self,
        timeout_seconds: float = _DEFAULT_OPERATION_TIMEOUT_SECONDS,
    ) -> None:
        """Wait for in-flight work and close the exact connection once."""
        _perform_close_func(self, timeout_seconds)

    def _close_timeout_failure_locked(self) -> BackendMonitorError:
        """Record an incomplete quarantined close without touching the connection."""
        return _close_timeout_failure_locked_func(self)

    def _configure_bounded_connection(self, connection: object) -> None:
        _configure_bounded_connection_func(connection)

    def _create_connection(self) -> object:
        """Create one connection through the validated startup policy."""
        return _create_connection_func(
            self._connection_factory, self._connection_settings
        )

    def _expire_operation(
        self,
        operation_generation: int,
    ) -> None:
        _expire_operation_func(self, operation_generation)

    def _request_active_cancellation(self, deadline: float) -> None:
        _request_active_cancellation_func(self, deadline)

    def _cancel_connection(
        self,
        connection: object | None,
        timeout_seconds: float,
        operation_generation: int,
    ) -> None:
        _cancel_connection_func(
            self, connection, timeout_seconds, operation_generation
        )

    def _record_cancellation_result(
        self,
        operation_generation: int,
        error: Exception | None,
    ) -> None:
        _record_cancellation_result_func(self, operation_generation, error)

    def _operation_expired(self, operation_generation: int) -> bool:
        with self._condition:
            return (
                self._operation_generation == operation_generation
                and self._cancellation_state.operation_timeout_created
            )

    def _execution_timeout(
        self,
        category: str,
        cause: Exception | None = None,
    ) -> BackendMonitorError:
        return _execution_timeout_func(self, category, cause)

    def _query_canceled_failure(
        self,
        category: str,
        cause: psycopg.errors.QueryCanceled,
    ) -> BackendMonitorError:
        return _query_canceled_failure_func(self, category, cause)

    def snapshot(self) -> ObserverSessionSnapshot:
        return _build_session_snapshot_func(self)

    def _classify_operation_settlement_locked(self) -> None:
        """Record D_op expiry at a safe observation point without reclamation."""
        _classify_operation_settlement_locked_func(self)

    def _failure_boundary(
        self,
        boundary: ObserverFailureBoundary,
        connection: object,
        cause: Exception,
    ) -> ObserverFailureBoundary:
        return _failure_boundary_func(boundary, connection, cause)

    def _invalid_state(
        self,
        message: str,
        boundary: ObserverFailureBoundary = ObserverFailureBoundary.CONTRACT_VALIDATION,
        *,
        category: str = "backend_observer_failed",
    ) -> BackendMonitorError:
        return self._failure(boundary, message, None, category=category)

    def _failure(
        self,
        boundary: ObserverFailureBoundary,
        message: str,
        cause: Exception | None,
        *,
        category: str = "backend_observer_failed",
        terminal_secondary: bool | None = None,
        timeout_mechanism: ObserverTimeoutMechanism | None = None,
        cancellation_limitation: ObserverCancellationLimitation | None = None,
    ) -> BackendMonitorError:
        return _session_failure_func(
            self,
            boundary,
            message,
            cause,
            category=category,
            terminal_secondary=terminal_secondary,
            timeout_mechanism=timeout_mechanism,
            cancellation_limitation=cancellation_limitation,
        )

    def _before_child_release(self) -> bool:
        return _before_child_release_func(self._child_released)
