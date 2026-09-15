"""Independent, bounded threshold attribution for SCALE11 profiling."""

from __future__ import annotations

import json
from typing import Sequence

from scale11_threshold_incremental import (
    IncrementalThresholdMonitor as IncrementalThresholdMonitor,
    _MetricState as _MetricState,
    _primary_stop as _primary_stop,
)
from scale11_threshold_models import (
    ActionableThresholdStop as ActionableThresholdStop,
    IncrementalMetricEvaluation as IncrementalMetricEvaluation,
    IncrementalThresholdEvaluation as IncrementalThresholdEvaluation,
    MetricCrossing as MetricCrossing,
    MetricSample as MetricSample,
    MetricSpec as MetricSpec,
    ThresholdEvaluation as ThresholdEvaluation,
    ThresholdEvaluationError as ThresholdEvaluationError,
    _CATEGORY_PATTERN as _CATEGORY_PATTERN,
    _DEFAULT_PAYLOAD_LIMIT as _DEFAULT_PAYLOAD_LIMIT,
    _MAX_METRICS as _MAX_METRICS,
    _MAX_SAMPLES as _MAX_SAMPLES,
    _OPERATION_PATTERN as _OPERATION_PATTERN,
    _validate_samples as _validate_samples,
    _validate_specs as _validate_specs,
)

__all__ = [
    "ActionableThresholdStop",
    "IncrementalMetricEvaluation",
    "IncrementalThresholdEvaluation",
    "IncrementalThresholdMonitor",
    "MetricCrossing",
    "MetricSample",
    "MetricSpec",
    "ThresholdEvaluation",
    "ThresholdEvaluationError",
    "evaluate_thresholds",
]


def evaluate_thresholds(
    specs: Sequence[MetricSpec],
    samples: Sequence[MetricSample],
    *,
    max_payload_bytes: int = _DEFAULT_PAYLOAD_LIMIT,
) -> ThresholdEvaluation:
    """Evaluate every metric on every sample before selecting one stop cause."""

    checked_specs = _validate_specs(specs)
    checked_samples = _validate_samples(samples, checked_specs)
    if (
        isinstance(max_payload_bytes, bool)
        or not isinstance(max_payload_bytes, int)
        or not 1 <= max_payload_bytes <= _DEFAULT_PAYLOAD_LIMIT
    ):
        raise ThresholdEvaluationError("threshold payload limit is invalid")
    monitor = IncrementalThresholdMonitor(
        checked_specs,
        max_payload_bytes=max_payload_bytes,
    )
    for sample in checked_samples:
        monitor.observe(sample)
    result = monitor.legacy_evaluation()
    encoded = json.dumps(
        result.to_payload(), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    if len(encoded) > max_payload_bytes:
        raise ThresholdEvaluationError("threshold payload limit exceeded")
    return result
