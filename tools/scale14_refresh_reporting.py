"""Observation and failure reporting for protected actual refresh supervision."""

from __future__ import annotations

import math
from typing import Callable, ContextManager, Mapping, Protocol

from actual_refresh_event_pump import ActualRefreshEventPump, _EventChannel
from actual_refresh_failure_causality import FailureCausalityAuthority, failure_owner
from actual_refresh_thresholds import seconds as _seconds
from repomap_kg.storage.staging_event_transport import StagingEventFrame
from scale11_threshold_evaluator import IncrementalThresholdMonitor, MetricSample
from scale14_active_boundary import ActiveBoundaryState
from scale14_resource_sampling import Scale14ResourceSampler
from scale14_supervisor_contracts import Scale14SupervisorError, validate_backend_summary, validate_required_resources
from scale15_terminal_contracts import ControlFailure, ControlFailureCode, ExpectedRefreshAuthority, TerminalReadback
from scale16_launch_binding import LaunchBindingError, LaunchBindingState
from scale25_terminal_settlement import TerminalResourceStatus

class _BackendMonitor(Protocol):
    def start(self) -> None: ...
    def summary(self) -> Mapping[str, int]: ...
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
    ) -> Mapping[str, int]: ...
    def wait_quiescent(self, timeout_seconds: float) -> Mapping[str, int]: ...
    def close_with_timeout(self, timeout_seconds: float) -> None: ...

_UNKNOWN_BOUNDARIES = frozenset(
    {"between_boundaries", "pre_final_attribution_unknown", "operation_attribution_unknown"}
)

def _failure_code(error: BaseException, fallback: ControlFailureCode) -> ControlFailureCode:
    if isinstance(error, ControlFailure):
        return error.code
    category = getattr(error, "category", None)
    if isinstance(category, str):
        try:
            return ControlFailureCode(category)
        except ValueError:
            pass
    return fallback

class _ActualRefreshReportingMixin:
    """Own sampled reporting, terminal authorities, and failure projections."""
    _channel: _EventChannel[StagingEventFrame]
    _resources: Scale14ResourceSampler
    _backends: _BackendMonitor
    _event_pump: ActualRefreshEventPump | None
    _terminal_reader: Callable[..., TerminalReadback]
    _terminal_backend_reader: Callable[[], Mapping[str, int]] | None
    _prelaunch_expectation: object | None
    _failure_lock: ContextManager[object]
    _event_state_lock: ContextManager[object]
    _failure_causality: FailureCausalityAuthority | None
    _clock_ns: Callable[[], int]
    _monitor: IncrementalThresholdMonitor
    _boundaries: ActiveBoundaryState
    _launch_binding: LaunchBindingState
    _poll_interval_seconds: float
    _signal_grace_ns: int
    _waiter: Callable[[float], None]
    _last_event_offset_ns: int
    _last_event_received_ns: int | None
    _signal_ns: int | None
    _last_active_boundary: str | None
    _backend_started: bool
    _live_backend_valid: bool
    _event_authority_settled: bool
    _resource_authority_settled: bool
    _backend_authority_settled: bool
    def _signal_once(self, *, reason: str) -> None: ...
    def _observe(self, now_ns: int, started_ns: int, *, terminal: bool) -> None:
        if not terminal:
            try:
                summary = self._backends.summary()
                validate_summary = getattr(self._backends, "validate_summary", None)
                if callable(validate_summary):
                    validate_summary(
                        summary,
                        lambda current: validate_backend_summary(
                            current, require_quiescent=False
                        ),
                    )
                else:
                    validate_backend_summary(summary, require_quiescent=False)
                if self._prelaunch_expectation is not None and any(
                    summary.get(key, 0)
                    for key in ("direct_owned_client", "direct_owned_parallel_worker")
                ):
                    with self._event_state_lock:
                        if self._launch_binding.bound_attempt is None:
                            self._launch_binding.mark_late()
                            raise LaunchBindingError("launch_authority_late")
            except BaseException:
                self._live_backend_valid = False
                raise
        sample = self._resources.capture(force=terminal)
        if sample is None:
            if terminal:
                raise Scale14SupervisorError("terminal resource sample is unavailable")
            return
        validate_required_resources(sample)
        elapsed_seconds = max(0.0, (now_ns - started_ns) / 1_000_000_000)
        boundary = None
        if not terminal:
            with self._event_state_lock:
                offset = self._last_event_offset_ns
                if self._last_event_received_ns is None:
                    offset = max(0, now_ns - started_ns)
                else:
                    offset += max(0, now_ns - self._last_event_received_ns)
                boundary = self._boundaries.snapshot(offset)
            if boundary.attribution not in _UNKNOWN_BOUNDARIES:
                self._last_active_boundary = boundary.attribution
        values = {code: value for code, value in sample.values.items() if code in self._monitor.metric_codes}
        boundary_values = {
            "attempt_elapsed_seconds": math.ceil(elapsed_seconds),
            "phase_elapsed_seconds": None if boundary is None else _seconds(boundary.phase_elapsed_ns),
            "operation_elapsed_seconds": None if boundary is None else _seconds(boundary.operation_elapsed_ns),
            "final_transaction_elapsed_seconds": _seconds(None if boundary is None else boundary.final_transaction_elapsed_ns),
        }
        values.update(
            (code, value)
            for code, value in boundary_values.items()
            if code in self._monitor.metric_codes
        )
        attribution = (
            "operation_attribution_unknown"
            if boundary is not None
            and boundary.attribution == "operation_attribution_unknown"
            else "exact"
        )
        active = None if boundary is None or boundary.attribution in _UNKNOWN_BOUNDARIES else boundary.attribution
        self._monitor.observe(MetricSample(
            elapsed_seconds, values, cancellation_started=self._signal_ns is not None,
            ownership_exclusive=True, terminal=terminal,
        ), active_operation=active, operation_attribution=attribution)
    def _settle_resource_authority(self) -> BaseException | None:
        """Settle resource-owned readers before terminal backend readback."""

        close = getattr(self._resources, "close", None)
        if not callable(close):
            return None
        try:
            close()
        except BaseException as error:
            self._record_terminal_error(
                error, ControlFailureCode.TERMINAL_RESOURCE_UNAVAILABLE
            )
            return error
        finally:
            self._resource_authority_settled = True
        return None
    @staticmethod
    def _resource_error_status(
        error: BaseException,
        *,
        settlement: bool = False,
    ) -> TerminalResourceStatus:
        if getattr(error, "category", None) == ControlFailureCode.RESOURCE_READER_UNAVAILABLE.value:
            return TerminalResourceStatus.READER_FAILED
        return TerminalResourceStatus.SAMPLER_UNSETTLED if settlement else TerminalResourceStatus.SAMPLE_UNAVAILABLE
    def _settle_event_authority(self) -> None:
        """Close the event owner before terminal resource settlement."""
        close = self._channel.close if self._event_pump is None else self._event_pump.close
        try:
            close()
        except BaseException as error:
            self._record_terminal_error(
                error, ControlFailureCode.EVENT_TRANSPORT_FAILED
            )
        finally:
            self._event_authority_settled = True
    def _record_terminal_event_status(self) -> None:
        """Retain a closed post-failure event channel as a secondary fact."""
        try:
            if self._event_pump is None:
                def reject_late_frame(_frame: StagingEventFrame) -> None:
                    raise ControlFailure(
                        ControlFailureCode.EVENT_TRANSPORT_FAILED
                    )
                self._channel.receive(
                    timeout_seconds=self._poll_interval_seconds,
                    validator=reject_late_frame,
                )
            else:
                if self._event_pump.terminal_eof() is not None:
                    self._record_secondary(ControlFailureCode.EVENT_TRANSPORT_EOF)
                    return
                self._event_pump.receive(timeout_seconds=self._poll_interval_seconds)
                raise ControlFailure(ControlFailureCode.EVENT_TRANSPORT_FAILED)
        except TimeoutError:
            return
        except EOFError:
            self._record_secondary(ControlFailureCode.EVENT_TRANSPORT_EOF)
        except BaseException as error:
            code = (
                error.code
                if isinstance(error, ControlFailure)
                else ControlFailureCode.EVENT_TRANSPORT_FAILED
            )
            self._record_secondary(code)
    def _reconcile_backends(
        self,
        child_quiescent: bool,
    ) -> tuple[Mapping[str, int], bool]:
        live_summary: Mapping[str, int] = {}
        if self._backend_started and child_quiescent and self._live_backend_valid:
            try:
                live_summary = self._backends.wait_quiescent(
                    self._signal_grace_ns / 1_000_000_000
                )
            except BaseException as error:
                self._record_backend_failure(error)
            finally:
                self._backend_started = False
        closed = False
        try:
            self._close_backend_authority()
            closed = True
        except BaseException as error:
            self._record_backend_failure(error)
        self._backend_started = False
        self._backend_authority_settled = closed
        if self._terminal_backend_reader is None:
            summary = live_summary
        else:
            try:
                summary = dict(self._terminal_backend_reader())
            except BaseException as error:
                self._record_backend_failure(error)
                return live_summary, False
        try:
            validate_backend_summary(summary)
        except BaseException as error:
            self._record_backend_failure(error)
            return summary, False
        return summary, bool(summary)
    def _record_backend_failure(self, error: BaseException) -> None:
        self._record_terminal_error(error, ControlFailureCode.BACKEND_QUIESCENCE_TIMEOUT)
    def _close_backend_authority(self) -> None:
        self._backends.close_with_timeout(
            self._signal_grace_ns / 1_000_000_000
        )

    def _read_terminal_state(self) -> TerminalReadback | None:
        try:
            if self._prelaunch_expectation is None:
                readback = self._terminal_reader()
            else:
                if not isinstance(
                    self._prelaunch_expectation,
                    ExpectedRefreshAuthority,
                ):
                    raise TypeError("prelaunch expectation is invalid")
                attempt = self._launch_binding.bound_attempt
                expectation = (
                    self._prelaunch_expectation
                    if attempt is None
                    else self._prelaunch_expectation.bind(attempt)
                )
                readback = self._terminal_reader(expectation)
            if not isinstance(readback, TerminalReadback):
                raise TypeError("terminal reader returned an invalid contract")
            return readback
        except BaseException as error:
            self._record_terminal_error(error, ControlFailureCode.RECEIPT_READBACK_FAILED)
            return None
    def _record_control_failure(
        self,
        error: BaseException,
        fallback: ControlFailureCode = ControlFailureCode.RESOURCE_READER_UNAVAILABLE,
    ) -> None:
        code = _failure_code(error, fallback)
        causality = self._causality()
        candidate = causality.observe_exception(error)
        if candidate is None:
            candidate = causality.record_exception(
                error,
                code=code,
                authority_owner=failure_owner(code),
                lifecycle_boundary=self._failure_boundary(),
                existed_before_child_release=self._before_child_release(),
                test_injected=bool(getattr(error, "test_injected", False)),
                terminal_secondary=bool(causality.candidates()),
            )
            causality.observe(candidate)
        self._refresh_failure_views()

    def _record_async_event_failure(self, error: BaseException) -> None:
        """Arbitrate a semantic pump failure before other authorities proceed."""
        if isinstance(error, EOFError):
            return
        with self._failure_lock:
            self._record_control_failure(
                error,
                ControlFailureCode.EVENT_TRANSPORT_FAILED,
            )
            try:
                self._signal_once(reason="control")
            except BaseException:
                self._record_failure(
                    ControlFailureCode.CHILD_EXIT_UNAVAILABLE,
                    primary=False,
                )
    def _record_and_signal(
        self,
        error: BaseException,
    ) -> None:
        """Record one control failure and issue its signal atomically."""
        with self._failure_lock:
            self._record_control_failure(error)
            try:
                self._signal_once(reason="control")
            except BaseException:
                self._record_failure(
                    ControlFailureCode.CHILD_EXIT_UNAVAILABLE,
                    primary=False,
                )
    def _record_terminal_error(
        self,
        error: BaseException,
        fallback: ControlFailureCode,
    ) -> None:
        self._record_control_failure(error, fallback)

    def _record_failure(
        self,
        code: ControlFailureCode,
        *,
        primary: bool = True,
    ) -> None:
        with self._failure_lock:
            code = ControlFailureCode(code)
            self._record_causal_code(code, terminal_secondary=not primary)
    def _record_secondary(self, code: ControlFailureCode) -> None:
        with self._failure_lock:
            self._record_causal_code(code, terminal_secondary=True)
    def _record_causal_code(
        self,
        code: object,
        *,
        terminal_secondary: bool = False,
    ) -> None:
        causality = self._causality()
        candidate = causality.record_code(
            code,
            authority_owner=failure_owner(code),
            lifecycle_boundary=self._failure_boundary(),
            existed_before_child_release=self._before_child_release(),
            terminal_secondary=terminal_secondary,
        )
        causality.observe(candidate)
        self._refresh_failure_views()
    def _refresh_failure_views(self) -> None:
        candidates = self._causality().candidates()
        primary: ControlFailureCode | None = None
        if candidates:
            try:
                primary = ControlFailureCode(candidates[0].code)
            except ValueError:
                pass
        start = 1 if primary is not None else 0
        secondary: list[ControlFailureCode] = []
        for candidate in candidates[start:]:
            try:
                code = ControlFailureCode(candidate.code)
            except ValueError:
                continue
            if code is not primary and code not in secondary:
                secondary.append(code)
        self._primary_failure = primary
        self._secondary_failures = secondary

    def _causality(self) -> FailureCausalityAuthority:
        causality = getattr(self, "_failure_causality", None)
        if causality is None:
            causality = FailureCausalityAuthority(clock_ns=self._clock_ns)
            self._failure_causality = causality
        return causality

    def _before_child_release(self) -> bool:
        startup = getattr(self, "_startup", None)
        return startup is not None and not startup.released
    def _failure_boundary(self) -> str:
        if self._before_child_release():
            return "startup"
        return getattr(self, "_last_active_boundary", None) or "active_supervision"


__all__ = ["_ActualRefreshReportingMixin"]
