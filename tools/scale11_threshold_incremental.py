"""Incremental threshold monitoring and online attribution for SCALE11 profiling."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Sequence

from scale11_threshold_models import (
    ActionableThresholdStop,
    IncrementalMetricEvaluation,
    IncrementalThresholdEvaluation,
    MetricCrossing,
    MetricSample,
    MetricSpec,
    ThresholdEvaluation,
    ThresholdEvaluationError,
    _OPERATION_PATTERN,
    _validate_samples,
    _validate_specs,
)


@dataclass
class _MetricState:
    spec: MetricSpec
    first_crossing_timestamp_seconds: float | None = None
    first_crossing_sample: int | None = None
    first_crossing_value: int | None = None
    crossing_timing: str = "none"
    maximum_observed_value: int | None = None
    terminal_sample_value: int | None = None
    ownership_exclusive: bool = True
    counter_reset_or_wrap: bool = False
    observed_sample_count: int = 0
    missing_sample_count: int = 0
    previous_counter_value: int | None = None
    first_crossing_active_operation: str | None = None
    maximum_pre_cancel_value: int | None = None
    maximum_terminal_value: int | None = None
    crossed_before_cancel: bool = False
    crossed_after_cancel: bool = False
    crossed_terminal: bool = False
    exclusive_attribution: bool = True
    sample_count: int = 0

    def observe(
        self,
        sample: MetricSample,
        sample_index: int,
        *,
        active_operation: str | None = None,
        operation_attribution: str = "exact",
    ) -> None:
        self.sample_count += 1
        self.ownership_exclusive &= sample.ownership_exclusive
        self.exclusive_attribution &= (
            sample.ownership_exclusive and operation_attribution == "exact"
        )
        value = sample.values.get(self.spec.category)
        if value is None:
            self.missing_sample_count += 1
            if sample.terminal:
                self.terminal_sample_value = None
            return
        self.observed_sample_count += 1
        if self.maximum_observed_value is None:
            self.maximum_observed_value = value
        else:
            self.maximum_observed_value = max(self.maximum_observed_value, value)
        if sample.terminal:
            self.terminal_sample_value = value
            if self.maximum_terminal_value is None:
                self.maximum_terminal_value = value
            else:
                self.maximum_terminal_value = max(
                    self.maximum_terminal_value, value
                )
        elif not sample.cancellation_started:
            if self.maximum_pre_cancel_value is None:
                self.maximum_pre_cancel_value = value
            else:
                self.maximum_pre_cancel_value = max(
                    self.maximum_pre_cancel_value, value
                )
        if self.spec.counter:
            previous = self.previous_counter_value
            if previous is not None and value < previous:
                self.counter_reset_or_wrap = True
                self.ownership_exclusive = False
                self.exclusive_attribution = False
            self.previous_counter_value = value
        crossed = (
            value < self.spec.limit
            if self.spec.lower_bound
            else value > self.spec.limit
        )
        if not crossed:
            return
        if sample.terminal:
            timing = "terminal_only"
            self.crossed_terminal = True
        elif sample.cancellation_started:
            timing = "after_cancellation"
            self.crossed_after_cancel = True
        else:
            timing = "before_cancellation"
            self.crossed_before_cancel = True
        if self.first_crossing_sample is not None:
            return
        self.first_crossing_timestamp_seconds = sample.timestamp_seconds
        self.first_crossing_sample = sample_index
        self.first_crossing_value = value
        self.first_crossing_active_operation = (
            active_operation if operation_attribution == "exact" else None
        )
        self.crossing_timing = timing

    def result(self) -> MetricCrossing:
        crossed = self.first_crossing_sample is not None
        return MetricCrossing(
            category=self.spec.category,
            limit=self.spec.limit,
            crossed=crossed,
            first_crossing_timestamp_seconds=(
                self.first_crossing_timestamp_seconds
            ),
            first_crossing_sample=self.first_crossing_sample,
            first_crossing_value=self.first_crossing_value,
            maximum_observed_value=self.maximum_observed_value,
            terminal_sample_value=self.terminal_sample_value,
            crossing_timing=self.crossing_timing,
            crossed_before_cancellation=(
                self.crossing_timing == "before_cancellation"
            ),
            ownership_exclusive=self.ownership_exclusive,
            counter_reset_or_wrap=self.counter_reset_or_wrap,
            observed_sample_count=self.observed_sample_count,
            missing_sample_count=self.missing_sample_count,
        )


def _primary_stop(states: tuple[_MetricState, ...]) -> str | None:
    candidates = tuple(
        state
        for state in states
        if state.crossing_timing == "before_cancellation"
    )
    if not candidates:
        return None
    selected = min(
        candidates,
        key=lambda state: (
            state.first_crossing_timestamp_seconds,
            state.first_crossing_sample,
            state.spec.priority,
            state.spec.category,
        ),
    )
    return selected.spec.category


class IncrementalThresholdMonitor:
    """Evaluate every applicable metric as each live sample arrives."""

    def __init__(
        self,
        specs: Sequence[MetricSpec],
        *,
        max_payload_bytes: int = 1_048_576,
    ) -> None:
        self._specs = _validate_specs(specs)
        if (
            isinstance(max_payload_bytes, bool)
            or not isinstance(max_payload_bytes, int)
            or not 1 <= max_payload_bytes <= 1_048_576
        ):
            raise ThresholdEvaluationError("threshold payload limit is invalid")
        self._max_payload_bytes = max_payload_bytes
        self._states = tuple(_MetricState(spec) for spec in self._specs)
        self._sample_count = 0
        self._last_timestamp = -math.inf
        self._cancellation_started = False
        self._terminal_seen = False
        self._actionable_stop: ActionableThresholdStop | None = None

    @property
    def actionable_stop(self) -> ActionableThresholdStop | None:
        """Return the first deterministic live stop, if one exists."""

        return self._actionable_stop

    @property
    def metric_codes(self) -> frozenset[str]:
        """Return the closed metric set accepted by this monitor."""

        return frozenset(spec.category for spec in self._specs)

    def observe(
        self,
        sample: MetricSample,
        *,
        active_operation: str | None = None,
        operation_attribution: str = "exact",
    ) -> ActionableThresholdStop | None:
        """Validate and evaluate one live or terminal sample immediately."""

        if self._terminal_seen:
            raise ThresholdEvaluationError("threshold terminal sample is invalid")
        _validate_samples((sample,), self._specs)
        if sample.timestamp_seconds < self._last_timestamp:
            raise ThresholdEvaluationError("threshold sample timestamp is invalid")
        if operation_attribution not in {
            "exact",
            "operation_attribution_unknown",
        }:
            raise ThresholdEvaluationError("operation attribution is invalid")
        if active_operation is not None and (
            not isinstance(active_operation, str)
            or not _OPERATION_PATTERN.fullmatch(active_operation)
        ):
            raise ThresholdEvaluationError("active operation is invalid")
        cancellation_started = (
            self._cancellation_started or sample.cancellation_started
        )
        effective_sample = MetricSample(
            sample.timestamp_seconds,
            sample.values,
            cancellation_started,
            sample.ownership_exclusive,
            sample.terminal,
        )
        for state in self._states:
            state.observe(
                effective_sample,
                self._sample_count,
                active_operation=active_operation,
                operation_attribution=operation_attribution,
            )
        self._sample_count += 1
        self._last_timestamp = float(sample.timestamp_seconds)
        self._cancellation_started = cancellation_started
        self._terminal_seen = sample.terminal
        self._select_actionable_stop()
        return self._actionable_stop

    def mark_cancellation_started(self, monotonic_offset_seconds: float) -> None:
        """Mark direct cancellation before any later samples are observed."""

        if (
            isinstance(monotonic_offset_seconds, bool)
            or not isinstance(monotonic_offset_seconds, (int, float))
            or not math.isfinite(monotonic_offset_seconds)
            or monotonic_offset_seconds < self._last_timestamp
        ):
            raise ThresholdEvaluationError("cancellation offset is invalid")
        self._cancellation_started = True
        self._last_timestamp = float(monotonic_offset_seconds)

    def finalize(self) -> IncrementalThresholdEvaluation:
        """Return one bounded deterministic evaluation without losing evidence."""

        metrics = tuple(self._incremental_result(state) for state in self._states)
        result = IncrementalThresholdEvaluation(
            metrics,
            (
                self._actionable_stop.metric_code
                if self._actionable_stop is not None
                else None
            ),
            self._sample_count,
        )
        encoded = json.dumps(
            result.to_payload(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        if len(encoded) > self._max_payload_bytes:
            raise ThresholdEvaluationError("threshold payload limit exceeded")
        return result

    def legacy_evaluation(self) -> ThresholdEvaluation:
        """Return the SCALE11-compatible projection from the same authority."""

        metrics = tuple(state.result() for state in self._states)
        return ThresholdEvaluation(
            metrics,
            _primary_stop(self._states),
            self._sample_count,
        )

    def _select_actionable_stop(self) -> None:
        if self._actionable_stop is not None:
            return
        category = _primary_stop(self._states)
        if category is None:
            return
        state = next(
            state for state in self._states if state.spec.category == category
        )
        assert state.first_crossing_timestamp_seconds is not None
        assert state.first_crossing_value is not None
        self._actionable_stop = ActionableThresholdStop(
            category,
            state.first_crossing_timestamp_seconds,
            state.first_crossing_value,
            state.first_crossing_active_operation,
        )

    @staticmethod
    def _incremental_result(
        state: _MetricState,
    ) -> IncrementalMetricEvaluation:
        if state.observed_sample_count == 0:
            availability = "unavailable"
        elif state.missing_sample_count:
            availability = "partially_available"
        else:
            availability = "available"
        return IncrementalMetricEvaluation(
            state.spec.category,
            state.spec.scope,
            state.spec.limit,
            state.first_crossing_timestamp_seconds,
            state.first_crossing_value,
            state.first_crossing_active_operation,
            state.maximum_pre_cancel_value,
            state.maximum_terminal_value,
            state.crossed_before_cancel,
            state.crossed_after_cancel,
            state.crossed_terminal,
            state.exclusive_attribution,
            state.counter_reset_or_wrap,
            state.sample_count,
            availability,
        )


__all__ = [
    "IncrementalThresholdMonitor",
]
