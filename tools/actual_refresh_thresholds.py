"""Threshold construction helpers for actual-refresh supervision."""

from __future__ import annotations

import math

from scale11_threshold_evaluator import MetricSpec
from scale14_resource_sampling import threshold_specs as resource_threshold_specs
from scale14_supervisor_contracts import ProtectedLaunchLimits


def threshold_specs(limits: ProtectedLaunchLimits) -> tuple[MetricSpec, ...]:
    """Build the elapsed-time and resource limits for one protected launch."""

    elapsed = (
        MetricSpec(
            "attempt_elapsed_seconds", limits.attempt_seconds, 0, scope="attempt"
        ),
        MetricSpec("phase_elapsed_seconds", limits.phase_seconds, 1, scope="phase"),
        MetricSpec(
            "operation_elapsed_seconds", limits.operation_seconds, 2, scope="operation"
        ),
        MetricSpec(
            "final_transaction_elapsed_seconds",
            limits.final_transaction_seconds,
            3,
            scope="final_transaction",
        ),
    )
    resources = tuple(
        MetricSpec(
            spec.category,
            spec.limit,
            index + 10,
            spec.counter,
            spec.lower_bound,
            spec.scope,
        )
        for index, spec in enumerate(resource_threshold_specs())
        if spec.category != "elapsed_seconds"
    )
    return (*elapsed, *resources)


def seconds(value_ns: int | None) -> int | None:
    """Round a nanosecond duration upward to whole seconds."""

    return None if value_ns is None else math.ceil(value_ns / 1_000_000_000)


__all__ = ["seconds", "threshold_specs"]
