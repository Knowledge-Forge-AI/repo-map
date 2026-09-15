"""Live child supervision and one-signal cancellation for SCALE12 profiles."""

from __future__ import annotations

import math
import signal
import socket
import subprocess
import time
from typing import Mapping, NoReturn

from repomap_kg.storage.staging_operation_events import StagingOperationEventCategory
from scale11_threshold_evaluator import IncrementalThresholdMonitor, MetricSample
from scale12_event_transport import Scale12EventChannel, Scale12Frame, Scale12TransportError
from scale12_operation_state import (
    ActiveOperationState, OperationAttributionError, operation_event_from_payload,
)
from scale12_resource_sampling import threshold_specs
from scale12_stderr_drain import (
    Scale12StderrDrainer, Scale12SupervisorError, classify_exception,
)


from scale12_profile_spawner import (
    _ChildProcess,
    _EventChannel,
    _ResourceSampler,
    _ThresholdMonitor as _ThresholdMonitor,
    Scale12SupervisionResult as Scale12SupervisionResult,
    start_profile_child as start_profile_child,
)


class Scale12ProfileSupervisor:
    """Supervise one current-source publication without owning its transaction."""

    def __init__(
        self,
        process: _ChildProcess,
        event_channel: _EventChannel,
        resource_sampler: _ResourceSampler,
        *,
        monitor: _ThresholdMonitor | None = None,
        clock_ns=time.monotonic_ns,
        poll_interval_seconds: float = 0.25,
        signal_grace_seconds: float = 60.0,
    ) -> None:
        if not 0 < poll_interval_seconds <= 1:
            raise ValueError("supervisor poll interval is invalid")
        if not 0 < signal_grace_seconds <= 60:
            raise ValueError("supervisor signal grace is invalid")
        self._process = process
        self._channel = event_channel
        self._resources = resource_sampler
        self._monitor = monitor or IncrementalThresholdMonitor(threshold_specs())
        self._clock_ns = clock_ns
        self._poll_interval_seconds = poll_interval_seconds
        self._signal_grace_ns = int(signal_grace_seconds * 1_000_000_000)
        self._operations = ActiveOperationState()
        self._operation_sequence: list[str] = []
        self._cancelled_operation_sequence: list[str] = []
        self._operation_max_duration_ns: dict[str, int] = {}
        self._ready = False
        self._terminal_category: str | None = None
        self._terminal_received_ns: int | None = None
        self._profile_summary: Mapping[str, object] | None = None
        self._signal_count = 0
        self._signal_ns: int | None = None
        self._crossing_to_signal_seconds: float | None = None
        self._primary_stop_operation: str | None = None
        self._last_event_offset_ns = 0
        self._last_event_received_ns: int | None = None
        self._drainer: Scale12StderrDrainer | None = None
        self._drainer_settlement_failed = False
        self.cleanup_failures: list[Exception] = []
        stderr = getattr(process, "stderr", None)
        if stderr is not None and not getattr(stderr, "closed", True):
            self._drainer = Scale12StderrDrainer(stderr, 4096)

    def run(self) -> Scale12SupervisionResult:
        """Run the bounded event, sample, deadline, and cancellation loop."""

        started_ns = self._clock_ns()
        primary_exc: BaseException | None = None
        try:
            while True:
                exit_code = self._process.poll()
                if exit_code is not None:
                    return self._finish_or_refuse(exit_code, started_ns)
                try:
                    frame = self._channel.receive(
                        timeout_seconds=self._poll_interval_seconds
                    )
                except TimeoutError:
                    frame = None
                except (Scale12TransportError, OperationAttributionError) as exc:
                    if self._terminal_category is not None:
                        time.sleep(self._poll_interval_seconds)
                        frame = None
                    else:
                        self._fail_closed("event transport failed", exc)
                if frame is not None:
                    self._handle_frame(frame)
                now_ns = self._clock_ns()
                self._observe(now_ns, started_ns, terminal=False)
                if self._terminal_category is None:
                    self._enforce_stop(now_ns, started_ns)
                elif (
                    self._terminal_received_ns is not None
                    and now_ns - self._terminal_received_ns > self._signal_grace_ns
                ):
                    raise Scale12SupervisorError("child exceeded the terminal exit bound")
                if (
                    self._signal_ns is not None
                    and now_ns - self._signal_ns > self._signal_grace_ns
                ):
                    raise Scale12SupervisorError("child ignored the bounded direct signal")
        except BaseException as exc:
            primary_exc = exc
            raise
        finally:
            self._cleanup(primary_exc)

    @property
    def drainer(self) -> Scale12StderrDrainer | None:
        """Return the underlying stderr drainer, if one was constructed."""
        return self._drainer

    def settle(self, primary_exc: BaseException | None = None) -> None:
        """Coordinate post-wait reader settlement and stream closure once child exits."""
        child_alive = self._process.poll() is None
        if not child_alive and self._drainer is not None and not self._drainer.settled:
            if not self._drainer.settle(timeout=0.5):
                if not self._drainer_settlement_failed:
                    self._drainer_settlement_failed = True
                    failure = self._drainer.settlement_failure or OSError(
                        "stderr stream settlement failed"
                    )
                    self.cleanup_failures.append(failure)
        elif child_alive and self._drainer is not None and not self._drainer.settled:
            if primary_exc is not None:
                existing_notes = getattr(primary_exc, "__notes__", [])
                if not any("stderr_settlement=" in str(n) for n in existing_notes):
                    primary_exc.add_note("stderr_settlement=deferred_live_child")
            else:
                live_failure = Scale12SupervisorError("cannot settle stderr while child is alive")
                if not any(
                    isinstance(f, Scale12SupervisorError) and str(f) == str(live_failure)
                    for f in self.cleanup_failures
                ):
                    self.cleanup_failures.append(live_failure)

        if primary_exc is None:
            if self.cleanup_failures:
                first_failure = self.cleanup_failures[0]
                distinct_tokens = sorted({classify_exception(f) for f in self.cleanup_failures})
                token_parts = " ".join(f"cleanup_failure={t}" for t in distinct_tokens)
                phase = (
                    "readiness"
                    if not self._ready
                    else "terminal"
                    if self._terminal_category
                    else "operation"
                )
                error = Scale12SupervisorError("child cleanup failed")
                error.add_note(
                    f"role=scale12_profile_child phase={phase} return=cleanup_failed "
                    f"cleanup_failures={len(self.cleanup_failures)} {token_parts}"
                )
                raise error from first_failure
        elif self.cleanup_failures:
            distinct_tokens = sorted({classify_exception(f) for f in self.cleanup_failures})
            existing_notes = getattr(primary_exc, "__notes__", [])
            for token in distinct_tokens:
                note_content = f"cleanup_failure={token}"
                if not any(note_content in str(n) for n in existing_notes):
                    primary_exc.add_note(note_content)

    def _cleanup(self, primary_exc: BaseException | None) -> None:
        try:
            self._channel.close()
        except Exception as exc:
            self.cleanup_failures.append(exc)
        self.settle(primary_exc)

    def _handle_frame(self, frame: Scale12Frame) -> None:
        if frame.category == "ready":
            if self._ready or frame.payload:
                self._fail_closed("child readiness frame is invalid")
            self._ready = True
            return
        if not self._ready:
            self._fail_closed("child emitted an event before readiness")
        if frame.category == "operation":
            try:
                event = operation_event_from_payload(frame.payload)
                self._operations.accept(event)
            except OperationAttributionError as exc:
                self._fail_closed("operation attribution failed", exc)
            if event.event_category is StagingOperationEventCategory.STARTED:
                self._operation_sequence.append(event.operation_code)
            elif event.duration_ns is not None:
                self._operation_max_duration_ns[event.operation_code] = max(
                    event.duration_ns,
                    self._operation_max_duration_ns.get(event.operation_code, 0),
                )
                if event.event_category is StagingOperationEventCategory.CANCELLED:
                    self._cancelled_operation_sequence.append(event.operation_code)
            self._last_event_offset_ns = event.monotonic_offset_ns
            self._last_event_received_ns = self._clock_ns()
            return
        if frame.category != "terminal" or self._terminal_category is not None:
            self._fail_closed("child terminal frame is invalid")
        if set(frame.payload) != {"terminal_category", "profile_summary"}:
            self._fail_closed("child terminal payload is invalid")
        category = frame.payload["terminal_category"]
        summary = frame.payload["profile_summary"]
        if category not in {"completed", "cancelled", "failed"}:
            self._fail_closed("child terminal category is invalid")
        if summary is not None and not isinstance(summary, dict):
            self._fail_closed("child profile summary is invalid")
        try:
            self._operations.close()
        except OperationAttributionError as exc:
            self._fail_closed("child terminated with open operation", exc)
        self._terminal_category = category
        self._terminal_received_ns = self._clock_ns()
        self._profile_summary = summary

    def _observe(self, now_ns: int, started_ns: int, *, terminal: bool) -> None:
        resource_sample = self._resources.capture(force=terminal)
        values: dict[str, int | None] = {}
        if resource_sample is not None:
            values.update(
                (code, value)
                for code, value in resource_sample.values.items()
                if code in self._monitor.metric_codes
            )
        elapsed_seconds = max(0.0, (now_ns - started_ns) / 1_000_000_000)
        values["elapsed_seconds"] = math.ceil(elapsed_seconds)
        snapshot_offset = self._last_event_offset_ns
        if self._last_event_received_ns is not None:
            snapshot_offset += max(0, now_ns - self._last_event_received_ns)
        try:
            snapshot = self._operations.snapshot(snapshot_offset)
        except OperationAttributionError as exc:
            self._fail_closed("operation sample attribution failed", exc)
        self._monitor.observe(
            MetricSample(
                elapsed_seconds,
                values,
                cancellation_started=self._signal_ns is not None,
                terminal=terminal,
            ),
            active_operation=snapshot.most_specific_active_operation,
            operation_attribution=snapshot.attribution,
        )

    def _enforce_stop(self, now_ns: int, started_ns: int) -> None:
        stop = self._monitor.actionable_stop
        if stop is None or self._signal_count:
            return
        self._process.send_signal(signal.SIGINT)
        self._signal_count = 1
        self._signal_ns = now_ns
        self._primary_stop_operation = stop.active_operation
        cancellation_offset_seconds = max(0.0, (now_ns - started_ns) / 1_000_000_000)
        self._crossing_to_signal_seconds = max(
            0.0, cancellation_offset_seconds - stop.monotonic_offset_seconds
        )
        self._monitor.mark_cancellation_started(cancellation_offset_seconds)

    def _finish_or_refuse(
        self, exit_code: int, started_ns: int
    ) -> Scale12SupervisionResult:
        if not self._ready:
            raise self._error("child exited before readiness", exit_code)
        if self._terminal_category is None:
            raise self._error("child exited without a terminal frame", exit_code)
        now_ns = self._clock_ns()
        self._observe(now_ns, started_ns, terminal=True)
        evaluation = self._monitor.finalize()
        signal_to_child_exit_seconds = (
            None if self._signal_ns is None else max(0.0, (now_ns - self._signal_ns) / 1_000_000_000)
        )
        return Scale12SupervisionResult(
            self._terminal_category,
            exit_code,
            self._signal_count,
            self._crossing_to_signal_seconds,
            signal_to_child_exit_seconds,
            self._primary_stop_operation,
            tuple(self._operation_sequence),
            tuple(self._cancelled_operation_sequence),
            {code: d / 1_000_000_000 for code, d in sorted(self._operation_max_duration_ns.items())},
            evaluation,
            self._profile_summary,
        )

    def _error(self, message: str, exit_code: int | None) -> Scale12SupervisorError:
        child_alive = self._process.poll() is None
        if self._drainer is not None and not child_alive and not self._drainer.settled:
            self._drainer.settle(timeout=0.5)
        phase = "readiness" if not self._ready else "terminal" if self._terminal_category else "operation"
        outcome = "not_exited" if exit_code is None else f"signal_{-exit_code}" if exit_code < 0 else f"exit_{exit_code}"
        error = Scale12SupervisorError(message)
        expected = "ready_frame" if not self._ready else "terminal_frame"
        note = (
            f"role=scale12_profile_child phase={phase} return={outcome} "
            f"expected={expected} signal_count={self._signal_count}"
        )
        if self._drainer is not None:
            total, retained, trunc, status = self._drainer.diagnostic_projection(
                child_alive=child_alive
            )
            trunc_str = "true" if trunc else "false"
            note += (
                f" stderr_bytes={total} stderr_retained={retained} "
                f"stderr_truncated={trunc_str} stderr_status={status}"
            )
            if self._drainer.drain_failure is not None:
                note += f" drain_failure={classify_exception(self._drainer.drain_failure)}"
        error.add_note(note)
        return error

    def _fail_closed(
        self, message: str, cause: Exception | None = None
    ) -> NoReturn:
        if self._process.poll() is None and self._signal_count == 0:
            self._process.send_signal(signal.SIGINT)
            self._signal_count = 1
            self._signal_ns = self._clock_ns()
        if cause is None:
            raise self._error(message, self._process.poll())
        raise self._error(message, self._process.poll()) from cause


def supervise_profile_child(
    process: _ChildProcess,
    event_socket: socket.socket,
    resource_sampler: _ResourceSampler,
) -> Scale12SupervisionResult:
    """Construct the production supervisor around an already-started child."""
    supervisor = Scale12ProfileSupervisor(
        process, Scale12EventChannel(event_socket), resource_sampler
    )
    primary_exc: BaseException | None = None
    try:
        return supervisor.run()
    except BaseException as error:
        primary_exc = error
        raise
    finally:
        try:
            try:
                process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                if primary_exc is None:
                    wait_error = Scale12SupervisorError("child wait timed out")
                    wait_error.add_note(
                        "role=scale12_profile_child phase=terminal return=timeout wait_failure=timeout"
                    )
                    primary_exc = wait_error
                    raise wait_error from None
                else:
                    primary_exc.add_note("wait_failure=timeout")
        finally:
            supervisor.settle(primary_exc=primary_exc)
