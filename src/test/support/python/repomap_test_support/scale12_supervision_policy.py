"""Narrow qualification policies for SCALE12 live-attribution tests."""

from __future__ import annotations

import math

from scale11_threshold_evaluator import (
    ActionableThresholdStop,
    IncrementalThresholdEvaluation,
    IncrementalThresholdMonitor,
    MetricSample,
    MetricSpec,
)
from scale12_resource_sampling import threshold_specs


_ATTRIBUTION_METRICS = frozenset({"elapsed_seconds", "client_peak_rss_bytes"})


def attribution_qualification_monitor() -> IncrementalThresholdMonitor:
    """Keep process bounds without claiming full host campaign qualification."""

    return IncrementalThresholdMonitor(
        tuple(
            spec
            for spec in threshold_specs()
            if spec.category in _ATTRIBUTION_METRICS
        )
    )


class OperationArmedElapsedMonitor:
    """Arm an elapsed stop only after the target operation is active."""

    def __init__(self, operation_code: str, *, delay_seconds: int) -> None:
        if not operation_code:
            raise ValueError("operation code is required")
        if (
            isinstance(delay_seconds, bool)
            or not isinstance(delay_seconds, int)
            or not 1 <= delay_seconds <= 60
        ):
            raise ValueError("operation elapsed delay is invalid")
        self._operation_code = operation_code
        self._delay_seconds = delay_seconds
        self._armed_at_seconds: float | None = None
        self._monitor: IncrementalThresholdMonitor | None = None

    @property
    def actionable_stop(self) -> ActionableThresholdStop | None:
        return None if self._monitor is None else self._monitor.actionable_stop

    @property
    def metric_codes(self) -> frozenset[str]:
        return frozenset({"elapsed_seconds"})

    def observe(
        self,
        sample: MetricSample,
        *,
        active_operation: str | None = None,
        operation_attribution: str = "exact",
    ) -> ActionableThresholdStop | None:
        monitor = self._monitor
        if monitor is None:
            if active_operation != self._operation_code and not sample.terminal:
                return None
            self._armed_at_seconds = sample.timestamp_seconds
            monitor = IncrementalThresholdMonitor(
                (MetricSpec("elapsed_seconds", self._delay_seconds, 0),)
            )
            self._monitor = monitor
        assert self._armed_at_seconds is not None
        elapsed_from_arm = max(
            0, math.ceil(sample.timestamp_seconds - self._armed_at_seconds)
        )
        armed_sample = MetricSample(
            sample.timestamp_seconds,
            {"elapsed_seconds": elapsed_from_arm},
            sample.cancellation_started,
            sample.ownership_exclusive,
            sample.terminal,
        )
        return monitor.observe(
            armed_sample,
            active_operation=active_operation,
            operation_attribution=operation_attribution,
        )

    def mark_cancellation_started(self, monotonic_offset_seconds: float) -> None:
        if self._monitor is None:
            raise RuntimeError("operation elapsed monitor is not armed")
        self._monitor.mark_cancellation_started(monotonic_offset_seconds)

    def finalize(self) -> IncrementalThresholdEvaluation:
        monitor = self._monitor
        if monitor is None:
            monitor = IncrementalThresholdMonitor(
                (MetricSpec("elapsed_seconds", self._delay_seconds, 0),)
            )
            self._monitor = monitor
        return monitor.finalize()
