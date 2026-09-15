"""Reporting, summary synchronization, and release authority for SCALE14."""

from __future__ import annotations

from threading import Event, Thread
import time
from typing import Callable, Mapping
from typing_extensions import TypeVar

from scale14_backend_monitor_events import MonitorObserverProtocol
from scale28_backend_observer_session import (
    BackendMonitorError,
    BackendObserverSession,
    ObserverFailureBoundary,
    ObserverSessionState,
)
from scale28_observer_deadlines import (
    ObserverDeadlinePolicy,
    ObserverOperationClass,
)

_SummaryObserverT = TypeVar(
    "_SummaryObserverT",
    bound=MonitorObserverProtocol,
)


def execute_observer_summary(
    *,
    session: BackendObserverSession[_SummaryObserverT],
    boundary: ObserverFailureBoundary,
    timeout_seconds: float,
) -> dict[str, int]:
    """Sample one public-safe summary dictionary from the bound session."""
    allowed = (
        (ObserverSessionState.ACTIVE,)
        if boundary is ObserverFailureBoundary.ACTIVE_SUMMARY
        else (
            ObserverSessionState.REGISTERED,
            ObserverSessionState.STARTUP_VALIDATED,
            ObserverSessionState.ACTIVE,
        )
    )
    return dict(
        session.run(
            boundary,
            lambda observer, connection: observer.public_summary(connection),
            allowed_states=allowed,
            operation_class=ObserverOperationClass.SQL_BOUNDED,
            timeout_seconds=timeout_seconds,
        )
    )


def _check_startup_floor(
    remaining: float,
    deadline_policy: ObserverDeadlinePolicy,
    summary: Mapping[str, int],
    blocked: bool,
) -> None:
    floor = deadline_policy.minimum_sql_caller_seconds or 0
    if remaining < floor:
        if summary.get("ambient_client", 0):
            category = "ambient_client_detected"
        elif summary.get("unknown", 0):
            category = "backend_ownership_unknown"
        elif blocked:
            category = "backend_quiescence_timeout"
        else:
            category = "backend_observer_failed"
        raise BackendMonitorError(
            "backend startup ownership did not become quiescent",
            category=category,
        )


def perform_startup_summary(
    session: BackendObserverSession,
    reader_ready: Event,
    done: Event,
    ownership_changed: Event,
    deadline_policy: ObserverDeadlinePolicy,
    summary_fn: Callable[[ObserverFailureBoundary, float], dict[str, int]],
    raise_telemetry_error: Callable[[], None],
    *,
    timeout_seconds: float,
    startup_timeout_seconds: float,
) -> Mapping[str, int]:
    """Return registered ownership before child telemetry begins."""
    if not session.is_registered or not reader_ready.is_set():
        raise BackendMonitorError(
            "backend monitor startup is incomplete",
            category="backend_observer_failed",
        )
    if done.is_set():
        raise_telemetry_error()
        raise BackendMonitorError(
            "backend telemetry ended before reader readiness",
            category="backend_telemetry_failed",
        )
    if not 0 < timeout_seconds <= startup_timeout_seconds:
        raise ValueError("backend startup timeout is invalid")
    deadline = time.monotonic() + timeout_seconds
    quiescent_once = False
    summary: Mapping[str, int] = {}
    blocked = False
    while True:
        if done.is_set():
            raise_telemetry_error()
            raise BackendMonitorError(
                "backend telemetry ended during startup ownership handoff",
                category="backend_telemetry_failed",
            )
        try:
            remaining = deadline - time.monotonic()
            _check_startup_floor(remaining, deadline_policy, summary, blocked)
            summary = summary_fn(ObserverFailureBoundary.STARTUP_SUMMARY, remaining)
        except BackendMonitorError:
            raise
        except Exception as error:
            raise BackendMonitorError(
                "backend startup ownership sampling failed",
                category="backend_observer_failed",
            ) from error
        if done.is_set():
            raise_telemetry_error()
            raise BackendMonitorError(
                "backend telemetry ended during startup ownership handoff",
                category="backend_telemetry_failed",
            )
        blocked = any(
            summary.get(category, 0)
            for category in (
                "direct_owned_client",
                "direct_owned_parallel_worker",
                "ambient_client",
                "unknown",
            )
        )
        if not blocked and quiescent_once:
            session.mark_startup_validated()
            return summary
        quiescent_once = not blocked
        remaining = deadline - time.monotonic()
        _check_startup_floor(remaining, deadline_policy, summary, blocked)
        ownership_changed.wait(min(remaining, 0.05))


def perform_live_summary(
    session: BackendObserverSession,
    reader_ready: Event,
    ownership_changed: Event,
    deadline_policy: ObserverDeadlinePolicy,
    summary_fn: Callable[[ObserverFailureBoundary, float], dict[str, int]],
    raise_active_telemetry_error: Callable[[], None],
    *,
    boundary: ObserverFailureBoundary,
    require_stable: bool,
    timeout_seconds: float,
) -> Mapping[str, int]:
    """Return one synchronized public-safe category-count projection."""
    if not session.is_registered or not reader_ready.is_set():
        raise BackendMonitorError(
            "backend monitor startup is incomplete",
            category="backend_observer_failed",
        )
    raise_active_telemetry_error()
    if not 0 < timeout_seconds <= deadline_policy.final_release_max_seconds:
        raise BackendMonitorError(
            "backend ownership sampling authority is invalid",
            category="backend_observer_failed",
        )
    deadline = time.monotonic() + timeout_seconds
    clean_once = False
    while True:
        try:
            raise_active_telemetry_error()
            ownership_changed.clear()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BackendMonitorError(
                    "backend ownership sampling timed out",
                    category="backend_observer_failed",
                    observer_boundary=ObserverFailureBoundary.OPERATION_EXECUTION_TIMEOUT,
                )
            summary = summary_fn(boundary, remaining)
        except BackendMonitorError:
            raise
        except Exception as error:
            raise BackendMonitorError(
                "backend ownership sampling failed",
                category="backend_observer_failed",
            ) from error
        if not summary.get("ambient_client", 0) and (not require_stable or clean_once):
            return summary
        clean_once = not summary.get("ambient_client", 0)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return summary
        ownership_changed.wait(min(remaining, 0.05))
        raise_active_telemetry_error()


def _check_readiness_timeout(
    remaining: float,
    validation_error: Exception | None,
    threshold: float = 0.0,
) -> None:
    if remaining <= threshold:
        if validation_error is not None:
            raise validation_error
        raise BackendMonitorError(
            "backend readiness was not stable before child release",
            category="backend_observer_failed",
        )


def perform_release_when_ready(
    session: BackendObserverSession,
    done: Event,
    ownership_changed: Event,
    deadline_policy: ObserverDeadlinePolicy,
    summary_fn: Callable[[ObserverFailureBoundary, float], dict[str, int]],
    raise_telemetry_error: Callable[[], None],
    *,
    release: Callable[[], None],
    summary_validator: Callable[[Mapping[str, int]], None],
    stable_sample: Callable[[], None] | None = None,
    stable_samples: Callable[[int, int], None] | None = None,
    before_release: Callable[[], None] | None = None,
    timeout_seconds: float | None = None,
    initial_stable_sample_ns: int | None = None,
) -> Mapping[str, int]:
    """Validate final readiness and release while telemetry is excluded."""
    release_timeout = (
        deadline_policy.final_release_timeout_seconds
        if timeout_seconds is None
        else timeout_seconds
    )
    if not 0 < release_timeout <= deadline_policy.final_release_max_seconds:
        raise BackendMonitorError(
            "backend final release authority is invalid",
            category="backend_observer_failed",
        )
    deadline = time.monotonic() + release_timeout
    quiescent_once = initial_stable_sample_ns is not None
    first_stable_sample_ns = initial_stable_sample_ns
    validation_error: Exception | None = None
    while True:
        if done.is_set():
            raise_telemetry_error()
            raise BackendMonitorError(
                "backend telemetry ended before child release",
                category="backend_telemetry_failed",
            )
        ownership_changed.clear()
        remaining = deadline - time.monotonic()
        _check_readiness_timeout(remaining, validation_error)
        summary = summary_fn(ObserverFailureBoundary.STARTUP_SUMMARY, remaining)
        try:
            summary_validator(summary)
        except Exception as error:
            if stable_sample is not None and stable_samples is None and quiescent_once:
                raise
            quiescent_once = False
            first_stable_sample_ns = None
            validation_error = error
        else:
            sampled_ns = time.monotonic_ns()
            if stable_samples is not None:
                if first_stable_sample_ns is None:
                    first_stable_sample_ns = sampled_ns
                else:
                    stable_samples(first_stable_sample_ns, sampled_ns)
            elif stable_sample is not None:
                stable_sample()
            if quiescent_once:
                if before_release is not None:
                    before_release()
                session.activate_and_release(release)
                return summary
            quiescent_once = True
            validation_error = None
        remaining = deadline - time.monotonic()
        _check_readiness_timeout(remaining, validation_error)
        sample_floor = deadline_policy.final_sample_floor_seconds
        _check_readiness_timeout(remaining, validation_error, threshold=sample_floor)
        time.sleep(sample_floor)


def perform_wait_quiescent(
    *,
    done: Event,
    thread: Thread | None,
    child_is_live: Callable[[], bool] | None,
    current_child_is_live: Callable[[], bool],
    raise_telemetry_error: Callable[[], None],
    summary_fn: Callable[[ObserverFailureBoundary, float], dict[str, int]],
    close_connection_fn: Callable[[float], None],
    timeout_seconds: float,
) -> Mapping[str, int]:
    """Wait for telemetry EOF, then return the exact settled summary."""
    deadline = time.monotonic() + timeout_seconds
    try:
        if not done.wait(timeout_seconds):
            raise BackendMonitorError(
                "backend telemetry did not quiesce",
                category="backend_quiescence_timeout",
            )
        if thread is not None:
            thread.join(timeout=max(0.0, deadline - time.monotonic()))
        raise_telemetry_error()
        if child_is_live is not None and current_child_is_live():
            raise BackendMonitorError(
                "backend telemetry ended while the child was active",
                category="backend_telemetry_failed",
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise BackendMonitorError(
                "backend terminal observation timed out",
                category="backend_quiescence_timeout",
                observer_boundary=ObserverFailureBoundary.SETTLEMENT_TIMEOUT,
            )
        return summary_fn(ObserverFailureBoundary.TERMINAL_WAIT, remaining)
    finally:
        close_connection_fn(max(0.0, deadline - time.monotonic()))
