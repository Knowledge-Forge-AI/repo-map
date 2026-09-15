"""Thread-safe backend ownership and telemetry monitoring for SCALE14."""

from __future__ import annotations

import os
from threading import Event, Lock, Thread
import time
from typing import Callable, Generic, Mapping
from typing_extensions import TypeVar

from actual_refresh_failure_causality import FailureCausalityAuthority
from repomap_kg.storage.backend_observer import BackendOwnershipObserver
from scale14_backend_monitor_events import (
    EventReaderProtocol,
    MonitorObserverProtocol,
    consume_telemetry_stream,
)
from scale14_backend_monitor_reporting import (
    execute_observer_summary,
    perform_live_summary,
    perform_release_when_ready,
    perform_startup_summary,
    perform_wait_quiescent,
)
from scale28_backend_observer_session import (
    BackendMonitorError,
    BackendObserverSession,
    ObserverFailureBoundary,
    ObserverSessionState,
)
from scale28_observer_deadlines import (
    DEFAULT_OBSERVER_DEADLINE_POLICY,
    ObserverDeadlinePolicy,
    ObserverOperationClass,
)


_STARTUP_TIMEOUT_SECONDS = 5.0
_OWNERSHIP_HANDOFF_SECONDS = (
    DEFAULT_OBSERVER_DEADLINE_POLICY.final_release_timeout_seconds
)
_OBSERVER_REGISTRATION_ATTEMPTS = 2


_StreamT = TypeVar("_StreamT", default=object)


class BackendOwnershipMonitor(Generic[_StreamT]):
    """Own one post-launch observer connection and private telemetry consumer."""

    def __init__(
        self,
        *,
        connection_factory: Callable[[], object],
        event_reader: EventReaderProtocol[_StreamT],
        event_stream: _StreamT,
        acknowledgement_fd: int,
        observer_factory: Callable[[], MonitorObserverProtocol] = (
            BackendOwnershipObserver
        ),
        descriptor_closer: Callable[[int], None] = os.close,
        child_is_live: Callable[[], bool] | None = None,
        failure_causality: FailureCausalityAuthority | None = None,
        child_released: Callable[[], bool] | None = None,
        _deadline_policy: ObserverDeadlinePolicy = (
            DEFAULT_OBSERVER_DEADLINE_POLICY
        ),
    ) -> None:
        self._event_reader = event_reader
        self._event_stream = event_stream
        self._acknowledgement_fd = acknowledgement_fd
        self._descriptor_closer = descriptor_closer
        self._child_is_live = child_is_live
        self._failure_causality = failure_causality
        self._child_released = child_released
        self._deadline_policy = _deadline_policy
        self._session: BackendObserverSession[MonitorObserverProtocol] = (
            BackendObserverSession(
                observer_factory=observer_factory,
                connection_factory=connection_factory,
                failure_causality=failure_causality,
                child_released=child_released,
                deadline_policy=_deadline_policy,
            )
        )
        self._thread: Thread | None = None
        self._done = Event()
        self._reader_ready = Event()
        self._ready = Event()
        self._startup_settled = Event()
        self._ownership_changed = Event()
        self._error_lock = Lock()
        self._error: BaseException | None = None
        self._acknowledgement_closed = False

    def start(self) -> None:
        """Create the observer after child launch and start telemetry consumption."""
        if self._thread is not None:
            raise BackendMonitorError(
                "backend monitor is already started",
                category="backend_observer_failed",
            )
        try:
            os.fstat(self._acknowledgement_fd)
        except OSError as error:
            raise BackendMonitorError(
                "backend telemetry acknowledgement descriptor is unavailable",
                category="backend_telemetry_failed",
            ) from error
        self._session.open(_OBSERVER_REGISTRATION_ATTEMPTS)
        if self._child_released is None:
            self._session.activate_legacy_monitor()
        try:
            thread = Thread(
                target=self._consume,
                name="scale14-backend-telemetry",
                daemon=False,
            )
            thread.start()
        except RuntimeError as error:
            self._session.close()
            raise BackendMonitorError(
                "backend telemetry consumer could not start",
                category="backend_telemetry_failed",
            ) from error
        self._thread = thread
        if not self._reader_ready.wait(_STARTUP_TIMEOUT_SECONDS):
            raise BackendMonitorError(
                "backend telemetry reader readiness timed out",
                category="backend_telemetry_failed",
            )
        if self._done.is_set():
            self._raise_telemetry_error()
            raise BackendMonitorError(
                "backend telemetry ended before reader readiness",
                category="backend_telemetry_failed",
            )

    def startup_summary(
        self,
        *,
        timeout_seconds: float = _OWNERSHIP_HANDOFF_SECONDS,
    ) -> Mapping[str, int]:
        """Return registered ownership before child telemetry begins."""
        return perform_startup_summary(
            self._session, self._reader_ready, self._done,
            self._ownership_changed, self._deadline_policy,
            self._summary, self._raise_telemetry_error,
            timeout_seconds=timeout_seconds,
            startup_timeout_seconds=_STARTUP_TIMEOUT_SECONDS,
        )

    def summary(self) -> Mapping[str, int]:
        """Return one synchronized public-safe category-count projection."""
        return self._live_summary(
            ObserverFailureBoundary.ACTIVE_SUMMARY,
            require_stable=False,
        )

    def pre_release_summary(
        self,
        *,
        timeout_seconds: float = _OWNERSHIP_HANDOFF_SECONDS,
    ) -> Mapping[str, int]:
        """Return one synchronized summary while release remains blocked."""
        return self._live_summary(
            ObserverFailureBoundary.STARTUP_SUMMARY,
            require_stable=False,
            timeout_seconds=timeout_seconds,
        )

    def _live_summary(
        self,
        boundary: ObserverFailureBoundary,
        *,
        require_stable: bool,
        timeout_seconds: float = _OWNERSHIP_HANDOFF_SECONDS,
    ) -> Mapping[str, int]:
        return perform_live_summary(
            self._session, self._reader_ready,
            self._ownership_changed, self._deadline_policy,
            self._summary, self._raise_active_telemetry_error,
            boundary=boundary, require_stable=require_stable,
            timeout_seconds=timeout_seconds,
        )

    def release_when_ready(
        self,
        release: Callable[[], None],
        summary_validator: Callable[[Mapping[str, int]], None],
        *,
        stable_sample: Callable[[], None] | None = None,
        stable_samples: Callable[[int, int], None] | None = None,
        before_release: Callable[[], None] | None = None,
        timeout_seconds: float | None = None,
        initial_stable_sample_ns: int | None = None,
    ) -> Mapping[str, int]:
        """Validate final readiness and release while telemetry is excluded."""
        return perform_release_when_ready(
            self._session, self._done, self._ownership_changed,
            self._deadline_policy, self._summary,
            self._raise_telemetry_error, release=release,
            summary_validator=summary_validator,
            stable_sample=stable_sample, stable_samples=stable_samples,
            before_release=before_release,
            timeout_seconds=timeout_seconds,
            initial_stable_sample_ns=initial_stable_sample_ns,
        )

    def wait_quiescent(self, timeout_seconds: float) -> Mapping[str, int]:
        """Wait for telemetry EOF, then return the exact settled summary."""
        return perform_wait_quiescent(
            done=self._done, thread=self._thread,
            child_is_live=self._child_is_live,
            current_child_is_live=self._current_child_is_live,
            raise_telemetry_error=self._raise_telemetry_error,
            summary_fn=self._summary,
            close_connection_fn=self._close_connection,
            timeout_seconds=timeout_seconds,
        )

    def read(self, reader: Callable[[object], int]) -> int:
        """Run one fixed resource reader through the exact observer connection."""
        if not self._session.is_registered:
            raise BackendMonitorError(
                "backend monitor is not started",
                category="backend_observer_failed",
            )
        self._raise_telemetry_error()
        try:
            return self._session.run(
                ObserverFailureBoundary.RESOURCE_READ,
                lambda _observer, connection: reader(connection),
                allowed_states=(
                    ObserverSessionState.STARTUP_VALIDATED,
                    ObserverSessionState.ACTIVE,
                ),
                category="resource_reader_unavailable",
                operation_class=ObserverOperationClass.SQL_BOUNDED,
                timeout_seconds=_OWNERSHIP_HANDOFF_SECONDS,
            )
        except BackendMonitorError:
            raise

    def validate_summary(
        self,
        summary: Mapping[str, int],
        validator: Callable[[Mapping[str, int]], None],
        *,
        timeout_seconds: float = _OWNERSHIP_HANDOFF_SECONDS,
    ) -> None:
        """Validate one projection inside the live session operation order."""
        self._session.run(
            ObserverFailureBoundary.CONTRACT_VALIDATION,
            lambda _observer, _connection: validator(summary),
            allowed_states=(
                ObserverSessionState.STARTUP_VALIDATED,
                ObserverSessionState.ACTIVE,
            ),
            operation_class=ObserverOperationClass.SERIALIZATION_ONLY,
            timeout_seconds=timeout_seconds,
        )

    def close(self) -> None:
        """Close only monitor-owned resources and join its consumer."""
        self.close_with_timeout(_STARTUP_TIMEOUT_SECONDS)

    def close_with_timeout(self, timeout_seconds: float) -> None:
        """Settle monitor-owned resources within one caller-owned budget."""
        timeout_seconds = min(
            timeout_seconds,
            self._deadline_policy.cleanup_timeout_seconds,
        )
        deadline = time.perf_counter() + timeout_seconds
        self._session.begin_close()
        close_stream = getattr(self._event_stream, "close", None)
        if callable(close_stream):
            try:
                close_stream()
            except OSError:
                pass
        failure: BaseException | None = None
        try:
            self._close_connection(max(0.0, deadline - time.perf_counter()))
        except BaseException as error:
            failure = error
        if self._thread is not None:
            self._thread.join(timeout=max(0.0, deadline - time.perf_counter()))
            if self._thread.is_alive() and failure is None:
                failure = BackendMonitorError(
                    "backend observer consumer settlement timed out",
                    category="backend_quiescence_timeout",
                    observer_boundary=ObserverFailureBoundary.SETTLEMENT_TIMEOUT,
                )
        if not self._acknowledgement_closed:
            try:
                self._descriptor_closer(self._acknowledgement_fd)
            except OSError:
                pass
            self._acknowledgement_closed = True
        if failure is not None:
            raise failure

    def _consume(self) -> None:
        failure: BaseException | None = None
        try:
            failure = consume_telemetry_stream(
                event_reader=self._event_reader,
                event_stream=self._event_stream,
                reader_ready=self._reader_ready,
                session=self._session,
                acknowledgement_fd=self._acknowledgement_fd,
                ownership_changed=self._ownership_changed,
                ready=self._ready,
                startup_settled=self._startup_settled,
                failure_causality=self._failure_causality,
                child_released=self._child_released,
                handoff_timeout=_OWNERSHIP_HANDOFF_SECONDS,
            )
        except BaseException as error:
            failure = error
        finally:
            with self._error_lock:
                self._error = failure
                self._startup_settled.set()
                self._done.set()

    def session_snapshot(self):
        """Return bounded private session state for deterministic tests."""
        return self._session.snapshot()

    def _summary(
        self,
        boundary: ObserverFailureBoundary,
        timeout_seconds: float,
    ) -> dict[str, int]:
        return execute_observer_summary(
            session=self._session,
            boundary=boundary,
            timeout_seconds=timeout_seconds,
        )

    def _raise_telemetry_error(self) -> None:
        with self._error_lock:
            error = self._error
        if error is not None:
            if isinstance(error, BackendMonitorError):
                raise error
            raise BackendMonitorError(
                "backend telemetry failed",
                category="backend_telemetry_failed",
            ) from error

    def _raise_active_telemetry_error(self) -> None:
        self._raise_telemetry_error()
        if self._done.is_set() and (
            self._child_is_live is None or self._current_child_is_live()
        ):
            raise BackendMonitorError(
                "backend telemetry ended while the child was active",
                category="backend_telemetry_failed",
            )

    def _current_child_is_live(self) -> bool:
        if self._child_is_live is None:
            raise BackendMonitorError(
                "child terminal authority is unavailable",
                category="backend_telemetry_failed",
            )
        try:
            child_is_live = self._child_is_live()
        except Exception as error:
            raise BackendMonitorError(
                "child terminal authority is unavailable",
                category="backend_telemetry_failed",
            ) from error
        if not isinstance(child_is_live, bool):
            raise BackendMonitorError(
                "child terminal authority is unavailable",
                category="backend_telemetry_failed",
            )
        return child_is_live

    def _close_connection(self, timeout_seconds: float) -> None:
        self._session.close(timeout_seconds=timeout_seconds)


__all__ = ["BackendMonitorError", "BackendOwnershipMonitor"]
