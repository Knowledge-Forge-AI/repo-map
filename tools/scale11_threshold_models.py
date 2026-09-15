"""Independent, bounded threshold models and validation for SCALE11 profiling."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Mapping, Sequence

_CATEGORY_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_OPERATION_PATTERN = re.compile(r"[a-z][a-z0-9_.]{0,127}\Z")
_MAX_METRICS = 32
_MAX_SAMPLES = 4_096
_DEFAULT_PAYLOAD_LIMIT = 65_536


class ThresholdEvaluationError(ValueError):
    """Raised when threshold input or output violates the closed contract."""


@dataclass(frozen=True)
class MetricSpec:
    """One sampled metric and its deterministic stop priority."""

    category: str
    limit: int
    priority: int
    counter: bool = False
    lower_bound: bool = False
    scope: str = "profile"


@dataclass(frozen=True)
class MetricSample:
    """One ordered sample across every configured metric."""

    timestamp_seconds: float
    values: Mapping[str, int | None]
    cancellation_started: bool = False
    ownership_exclusive: bool = True
    terminal: bool = False


@dataclass(frozen=True)
class MetricCrossing:
    """Complete retained evidence for one independently evaluated metric."""

    category: str
    limit: int
    crossed: bool
    first_crossing_timestamp_seconds: float | None
    first_crossing_sample: int | None
    first_crossing_value: int | None
    maximum_observed_value: int | None
    terminal_sample_value: int | None
    crossing_timing: str
    crossed_before_cancellation: bool
    ownership_exclusive: bool
    counter_reset_or_wrap: bool
    observed_sample_count: int
    missing_sample_count: int

    def to_payload(self) -> dict[str, object]:
        """Return the closed public-safe metric projection."""

        return {
            "category": self.category,
            "limit": self.limit,
            "crossed": self.crossed,
            "first_crossing_timestamp_seconds": (
                self.first_crossing_timestamp_seconds
            ),
            "first_crossing_sample": self.first_crossing_sample,
            "first_crossing_value": self.first_crossing_value,
            "maximum_observed_value": self.maximum_observed_value,
            "terminal_sample_value": self.terminal_sample_value,
            "crossing_timing": self.crossing_timing,
            "crossed_before_cancellation": self.crossed_before_cancellation,
            "ownership_exclusive": self.ownership_exclusive,
            "counter_reset_or_wrap": self.counter_reset_or_wrap,
            "observed_sample_count": self.observed_sample_count,
            "missing_sample_count": self.missing_sample_count,
        }


@dataclass(frozen=True)
class ThresholdEvaluation:
    """Bounded evaluation result after every crossing has been retained."""

    metrics: tuple[MetricCrossing, ...]
    primary_stop_category: str | None
    sample_count: int

    def to_payload(self) -> dict[str, object]:
        """Return the deterministic versioned result payload."""

        return {
            "schema_version": 1,
            "sample_count": self.sample_count,
            "primary_stop_category": self.primary_stop_category,
            "metrics": [metric.to_payload() for metric in self.metrics],
        }


@dataclass(frozen=True)
class ActionableThresholdStop:
    """Deterministic first live stop that may trigger direct cancellation."""

    metric_code: str
    monotonic_offset_seconds: float
    value: int
    active_operation: str | None


@dataclass(frozen=True)
class IncrementalMetricEvaluation:
    """Retained live and terminal evidence for one sampled metric."""

    metric_code: str
    scope: str
    limit: int
    first_crossing_monotonic_offset: float | None
    first_crossing_value: int | None
    first_crossing_active_operation: str | None
    maximum_pre_cancel_value: int | None
    maximum_terminal_value: int | None
    crossed_before_cancel: bool
    crossed_after_cancel: bool
    crossed_terminal: bool
    exclusive_attribution: bool
    counter_reset_or_wrap: bool
    sample_count: int
    availability: str

    def to_payload(self) -> dict[str, object]:
        """Return the closed public-safe incremental metric projection."""

        return {
            "metric_code": self.metric_code,
            "scope": self.scope,
            "limit": self.limit,
            "first_crossing_monotonic_offset": (
                self.first_crossing_monotonic_offset
            ),
            "first_crossing_value": self.first_crossing_value,
            "first_crossing_active_operation": (
                self.first_crossing_active_operation
            ),
            "maximum_pre_cancel_value": self.maximum_pre_cancel_value,
            "maximum_terminal_value": self.maximum_terminal_value,
            "crossed_before_cancel": self.crossed_before_cancel,
            "crossed_after_cancel": self.crossed_after_cancel,
            "crossed_terminal": self.crossed_terminal,
            "exclusive_attribution": self.exclusive_attribution,
            "counter_reset_or_wrap": self.counter_reset_or_wrap,
            "sample_count": self.sample_count,
            "availability": self.availability,
        }


@dataclass(frozen=True)
class IncrementalThresholdEvaluation:
    """Bounded final projection of the live threshold authority."""

    metrics: tuple[IncrementalMetricEvaluation, ...]
    primary_stop_category: str | None
    sample_count: int

    def to_payload(self) -> dict[str, object]:
        """Return the deterministic versioned live evaluation."""

        return {
            "schema_version": 1,
            "sample_count": self.sample_count,
            "primary_stop_category": self.primary_stop_category,
            "metrics": [metric.to_payload() for metric in self.metrics],
        }


def _validate_specs(specs: Sequence[MetricSpec]) -> tuple[MetricSpec, ...]:
    if not isinstance(specs, (tuple, list)) or not 1 <= len(specs) <= _MAX_METRICS:
        raise ThresholdEvaluationError("threshold metric count is invalid")
    checked = tuple(specs)
    categories: set[str] = set()
    for spec in checked:
        if not isinstance(spec, MetricSpec):
            raise ThresholdEvaluationError("threshold metric is invalid")
        if not isinstance(spec.category, str) or not _CATEGORY_PATTERN.fullmatch(
            spec.category
        ):
            raise ThresholdEvaluationError("threshold metric category is invalid")
        if spec.category in categories:
            raise ThresholdEvaluationError("threshold metric category is duplicated")
        categories.add(spec.category)
        if isinstance(spec.limit, bool) or not isinstance(spec.limit, int) or spec.limit < 0:
            raise ThresholdEvaluationError("threshold metric limit is invalid")
        if (
            isinstance(spec.priority, bool)
            or not isinstance(spec.priority, int)
            or not 0 <= spec.priority < _MAX_METRICS
        ):
            raise ThresholdEvaluationError("threshold metric priority is invalid")
        if not isinstance(spec.counter, bool):
            raise ThresholdEvaluationError("threshold counter flag is invalid")
        if not isinstance(spec.lower_bound, bool):
            raise ThresholdEvaluationError("threshold lower-bound flag is invalid")
        if not isinstance(spec.scope, str) or not _CATEGORY_PATTERN.fullmatch(
            spec.scope
        ):
            raise ThresholdEvaluationError("threshold metric scope is invalid")
    return checked


def _validate_samples(
    samples: Sequence[MetricSample],
    specs: tuple[MetricSpec, ...],
) -> tuple[MetricSample, ...]:
    if not isinstance(samples, (tuple, list)) or len(samples) > _MAX_SAMPLES:
        raise ThresholdEvaluationError("threshold sample count is invalid")
    checked = tuple(samples)
    categories = {spec.category for spec in specs}
    previous_timestamp = -math.inf
    cancellation_started = False
    terminal_seen = False
    for index, sample in enumerate(checked):
        if not isinstance(sample, MetricSample):
            raise ThresholdEvaluationError("threshold sample is invalid")
        timestamp = sample.timestamp_seconds
        if (
            isinstance(timestamp, bool)
            or not isinstance(timestamp, (int, float))
            or not math.isfinite(timestamp)
            or timestamp < 0
            or timestamp < previous_timestamp
        ):
            raise ThresholdEvaluationError("threshold sample timestamp is invalid")
        previous_timestamp = float(timestamp)
        if not isinstance(sample.values, Mapping):
            raise ThresholdEvaluationError("threshold sample values are invalid")
        if not set(sample.values) <= categories:
            raise ThresholdEvaluationError("threshold sample category is invalid")
        for value in sample.values.values():
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ThresholdEvaluationError("threshold sample value is invalid")
        for flag in (
            sample.cancellation_started,
            sample.ownership_exclusive,
            sample.terminal,
        ):
            if not isinstance(flag, bool):
                raise ThresholdEvaluationError("threshold sample flag is invalid")
        if cancellation_started and not sample.cancellation_started:
            raise ThresholdEvaluationError("threshold cancellation state regressed")
        cancellation_started = sample.cancellation_started
        if terminal_seen or (sample.terminal and index != len(checked) - 1):
            raise ThresholdEvaluationError("threshold terminal sample is invalid")
        terminal_seen = sample.terminal
    return checked


__all__ = [
    "ActionableThresholdStop",
    "IncrementalMetricEvaluation",
    "IncrementalThresholdEvaluation",
    "MetricCrossing",
    "MetricSample",
    "MetricSpec",
    "ThresholdEvaluation",
    "ThresholdEvaluationError",
]
