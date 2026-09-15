"""Integrated protected-launch supervision for one actual RepoMap refresh."""

from __future__ import annotations

import signal
from threading import Lock, RLock
import time
from typing import Callable, Mapping, TypeAlias

from actual_refresh_event_pump import ActualRefreshEventPump
from actual_refresh_failure_causality import (
    FailureCausalityAuthority,
)
from actual_refresh_startup import ActualRefreshStartup
from actual_refresh_terminal_coordinator import (
    _ActualRefreshTerminalCoordinator,
)
from repomap_kg.storage.staging_event_transport import StagingEventFrame
from repomap_kg.storage.staging_operation_events import (
    StagingOperationEventCategory,
)
from scale11_threshold_evaluator import IncrementalThresholdMonitor
from actual_refresh_thresholds import threshold_specs as _threshold_specs
from scale12_operation_state import operation_event_from_payload
from scale14_active_boundary import ActiveBoundaryError, ActiveBoundaryState
from scale14_supervisor_contracts import (
    ProtectedLaunchLimits,
    Scale14SupervisorError,
    validate_backend_summary,
    validate_required_resources,
    validate_storage_baseline,
)
from scale15_terminal_contracts import (
    CleanupState,
    ControlFailure,
    ControlFailureCode,
    TerminalControlResult,
    TerminalReadback,
)
from scale16_launch_binding import LaunchBindingError, LaunchBindingState
from scale25_terminal_settlement import (
    ChildTerminalAuthority,
    TerminalSettlementAuthority,
)
from scale28_hybrid_startup import (
    prepare_parent_startup_authorities,
    release_prepared_child,
)
from scale14_refresh_reporting import _ActualRefreshReportingMixin


ActualRefreshSupervisionResult: TypeAlias = TerminalControlResult
_EVENT_RECEIVER_STARTUP_TIMEOUT_SECONDS = 5.0


class ActualRefreshSupervisor(_ActualRefreshReportingMixin):
    """Own the control loop without owning SQL, publication, or rollback."""

    def __init__(
        self,
        process,
        event_channel,
        resource_sampler,
        backend_monitor,
        *,
        terminal_reader: Callable[..., TerminalReadback],
        cleanup_verifier: Callable[[TerminalReadback], CleanupState],
        terminal_backend_reader: Callable[[], Mapping[str, int]] | None = None,
        limits: ProtectedLaunchLimits,
        storage_baseline,
        prelaunch_expectation=None,
        startup: ActualRefreshStartup | None = None,
        child_terminal: ChildTerminalAuthority | None = None,
        monitor: IncrementalThresholdMonitor | None = None,
        clock_ns: Callable[[], int] = time.monotonic_ns,
        poll_interval_seconds: float = 0.25,
        signal_grace_seconds: float = 60.0,
        waiter: Callable[[float], None] = time.sleep,
        failure_causality: FailureCausalityAuthority | None = None,
        preparation_authority=None,
    ) -> None:
        if not 0 < poll_interval_seconds <= 1:
            raise ValueError("supervisor poll interval is invalid")
        if not 0 < signal_grace_seconds <= 60:
            raise ValueError("supervisor signal grace is invalid")
        self._process = process
        self._child_terminal = child_terminal or ChildTerminalAuthority(process)
        self._channel = event_channel
        self._resources = resource_sampler
        self._backends = backend_monitor
        self._terminal_reader = terminal_reader
        self._prelaunch_expectation = prelaunch_expectation
        self._event_state_lock = Lock()
        self._failure_lock = RLock()
        if prelaunch_expectation is not None:
            prelaunch_expectation.validate()
        if prelaunch_expectation is not None and startup is None:
            raise ValueError("supervised refresh startup authority is required")
        self._startup = startup
        self._preparation_authority = preparation_authority
        if preparation_authority is not None and startup is None:
            raise ValueError("hybrid preparation requires startup authority")
        self._clock_ns = clock_ns
        self._failure_causality = failure_causality or FailureCausalityAuthority(
            clock_ns=clock_ns
        )
        self._event_pump = (
            ActualRefreshEventPump(
                event_channel,
                self._handle_frame,
                self._record_async_event_failure,
                failure_causality=self._failure_causality,
                child_released=lambda: startup.released,
            )
            if startup is not None
            else None
        )
        self._launch_binding = LaunchBindingState()
        self._cleanup_verifier = cleanup_verifier
        self._terminal_backend_reader = terminal_backend_reader
        self._limits = limits
        self._storage_baseline = storage_baseline
        self._monitor = monitor or IncrementalThresholdMonitor(
            _threshold_specs(limits)
        )
        self._poll_interval_seconds = poll_interval_seconds
        self._signal_grace_ns = int(signal_grace_seconds * 1_000_000_000)
        self._waiter = waiter
        self._boundaries = ActiveBoundaryState(
            idle_limit_ns=int(2 * poll_interval_seconds * 1_000_000_000)
        )
        self._phase_sequence: list[str] = []
        self._operation_sequence: list[str] = []
        self._last_event_offset_ns = 0
        self._last_event_received_ns: int | None = None
        self._signal_count = 0
        self._signal_ns: int | None = None
        self._primary_stop_boundary: str | None = None
        self._event_eof_ns: int | None = None
        self._primary_failure: ControlFailureCode | None = None
        self._secondary_failures: list[ControlFailureCode] = []
        self._last_active_boundary: str | None = None
        self._signal_reason: str | None = None
        self._backend_started = False
        self._live_backend_valid = True
        self._terminal_result: ActualRefreshSupervisionResult | None = None
        self._terminal_settlement = TerminalSettlementAuthority()
        self._event_authority_settled = False
        self._resource_authority_settled = False
        self._backend_authority_settled = False

    def run(self) -> ActualRefreshSupervisionResult:
        """Run through terminal sampling, quiescence, and receipt-first readback."""

        started_ns = self._clock_ns()
        try:
            try:
                self._prepare_startup()
            except BaseException as error:
                if self._startup is not None:
                    self._startup.fail()
                if self._preparation_authority is not None:
                    self._preparation_authority.refuse()
                self._record_and_signal(error)
            while self._child_terminal.poll() is None:
                if self._primary_failure is not None:
                    break
                try:
                    self._monitor_once(started_ns)
                except BaseException as error:
                    self._record_and_signal(error)
                    break
                now_ns = self._clock_ns()
                if (
                    self._signal_ns is not None
                    and now_ns - self._signal_ns > self._signal_grace_ns
                ):
                    self._record_failure(ControlFailureCode.CHILD_IGNORED_SIGNAL)
                    break
            exit_code = self._settle_child(started_ns)
            return self._reconcile_terminal(exit_code, started_ns)
        finally:
            if not self._event_authority_settled:
                if self._event_pump is None:
                    self._channel.close()
                else:
                    self._event_pump.close()
            if not self._backend_authority_settled:
                self._close_backend_authority()
            if not self._resource_authority_settled:
                close_resources = getattr(self._resources, "close", None)
                if callable(close_resources):
                    close_resources()
            if self._startup is not None:
                self._startup.close()
            if self._preparation_authority is not None:
                self._preparation_authority.settle()

    def _prepare_startup(self) -> None:
        """Make every blocking parent authority ready before child release."""

        validate_storage_baseline(self._storage_baseline)
        if self._startup is not None:
            self._startup.mark_storage_baseline_ready()
        self._backends.start()
        self._backend_started = True
        if self._startup is None:
            return
        prepare_parent_startup_authorities(
            self._startup,
            self._backends,
            self._resources,
            self._preparation_authority,
            self._event_pump,
            self._record_failure,
            event_receiver_timeout_seconds=(
                _EVENT_RECEIVER_STARTUP_TIMEOUT_SECONDS
            ),
            summary_validator=validate_backend_summary,
            resource_validator=validate_required_resources,
        )
        if self._preparation_authority is None:
            self._backends.release_when_ready(
                self._startup.release,
                validate_backend_summary,
            )
        else:
            release_prepared_child(
                self._preparation_authority,
                self._backends,
                self._startup,
                validate_backend_summary,
            )
        self._startup.mark_monitoring()

    def _monitor_once(self, started_ns: int) -> None:
        frame: StagingEventFrame | bool | None
        try:
            if self._event_pump is None:
                frame = self._channel.receive(
                    timeout_seconds=self._poll_interval_seconds,
                    validator=self._handle_frame,
                )
            else:
                frame = self._event_pump.receive(
                    timeout_seconds=self._poll_interval_seconds
                )
        except TimeoutError:
            frame = None
        except EOFError as error:
            now_ns = self._clock_ns()
            if self._event_eof_ns is None:
                self._event_eof_ns = now_ns
            elif (
                now_ns - self._event_eof_ns
                >= 2 * self._poll_interval_seconds * 1_000_000_000
            ):
                raise ControlFailure(
                    ControlFailureCode.EVENT_TRANSPORT_EOF,
                    cause=error,
                ) from error
            self._waiter(self._poll_interval_seconds)
            self._probe_control_authorities()
            return
        except (LaunchBindingError, ControlFailure, ActiveBoundaryError):
            raise
        except BaseException as error:
            raise ControlFailure(
                ControlFailureCode.EVENT_TRANSPORT_FAILED,
                cause=error,
            ) from error
        now_ns = self._clock_ns()
        if frame is None:
            self._observe(now_ns, started_ns, terminal=False)
        self._enforce_stop(now_ns, started_ns)

    def _probe_control_authorities(self, *, probe_resources: bool = True) -> None:
        """Check failure authorities while an event EOF grace is pending."""

        try:
            summary = self._backends.summary()
            validate_summary = getattr(self._backends, "validate_summary", None)
            if callable(validate_summary):
                validate_summary(
                    summary,
                    lambda current: validate_backend_summary(
                        current,
                        require_quiescent=False,
                    ),
                )
            else:
                validate_backend_summary(summary, require_quiescent=False)
        except BaseException:
            self._live_backend_valid = False
            raise
        if probe_resources and self._child_terminal.poll() is None:
            sample = self._resources.capture(force=False)
            if sample is not None:
                validate_required_resources(sample)

    def _handle_frame(self, frame) -> None:
        with self._event_state_lock:
            self._accept_frame(frame)

    def _accept_frame(self, frame) -> None:
        if frame.category == "authority":
            if self._prelaunch_expectation is None:
                raise LaunchBindingError("launch_authority_invalid")
            self._launch_binding.accept(frame)
            self._last_event_offset_ns = frame.payload["monotonic_offset_ns"]
            self._last_event_received_ns = self._clock_ns()
            return
        if self._prelaunch_expectation is not None and self._launch_binding.bound_attempt is None:
            if (
                frame.category == "operation"
                or frame.category == "phase"
                and frame.payload.get("event_category") == "started"
                and frame.payload.get("phase_code")
                not in {
                    "refresh.total",
                    "refresh.source_discovery",
                    "refresh.extraction",
                }
            ):
                self._launch_binding.mark_late()
                raise LaunchBindingError("launch_authority_late")
        if frame.category == "measurement":
            return
        if frame.category == "phase":
            self._boundaries.accept_phase(frame.payload)
            if frame.payload["event_category"] == "started":
                self._phase_sequence.append(frame.payload["phase_code"])
        elif frame.category == "operation":
            self._boundaries.accept_operation(frame.payload)
            event = operation_event_from_payload(frame.payload)
            if event.event_category is StagingOperationEventCategory.STARTED:
                self._operation_sequence.append(event.operation_code)
        else:
            raise ControlFailure(ControlFailureCode.EVENT_TRANSPORT_FAILED)
        self._last_event_offset_ns = frame.payload["monotonic_offset_ns"]
        self._last_event_received_ns = self._clock_ns()

    def _enforce_stop(self, now_ns: int, started_ns: int) -> None:
        stop = self._monitor.actionable_stop
        if stop is None or self._signal_count:
            return
        self._primary_stop_boundary = stop.active_operation
        self._signal_once(reason="threshold")
        elapsed = max(0.0, (now_ns - started_ns) / 1_000_000_000)
        self._monitor.mark_cancellation_started(elapsed)

    def _signal_once(self, *, reason: str) -> None:
        with self._failure_lock:
            if self._signal_count or self._child_terminal.poll() is not None:
                return
            if reason == "threshold":
                self._record_causal_code("threshold_limit_crossed")
            self._process.send_signal(signal.SIGINT)
            self._signal_count = 1
            self._signal_ns = self._clock_ns()
            self._signal_reason = reason

    def _settle_child(
        self,
        started_ns: int,
    ) -> int | None:
        while self._child_terminal.poll() is None:
            with self._failure_lock:
                signal_ns = self._signal_ns
                if signal_ns is None:
                    self._record_failure(
                        ControlFailureCode.CHILD_EXIT_UNAVAILABLE
                    )
                    return None
                now_ns = self._clock_ns()
                if now_ns - signal_ns > self._signal_grace_ns:
                    self._record_failure(
                        ControlFailureCode.CHILD_IGNORED_SIGNAL
                    )
                    return None
            self._waiter(self._poll_interval_seconds)
        return self._child_terminal.poll()

    def _reconcile_terminal(
        self,
        exit_code: int | None,
        started_ns: int,
    ) -> ActualRefreshSupervisionResult:
        return _ActualRefreshTerminalCoordinator(self).reconcile(
            exit_code,
            started_ns,
        )

__all__ = [
    "ActualRefreshSupervisionResult",
    "ActualRefreshSupervisor",
    "ProtectedLaunchLimits",
    "Scale14SupervisorError",
]
