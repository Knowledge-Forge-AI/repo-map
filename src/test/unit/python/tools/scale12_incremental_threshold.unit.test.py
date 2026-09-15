from __future__ import annotations

import json

import pytest

from scale11_threshold_evaluator import (
    IncrementalThresholdMonitor,
    MetricSample,
    MetricSpec,
    ThresholdEvaluationError,
)


def _specs() -> tuple[MetricSpec, ...]:
    return (
        MetricSpec("elapsed_seconds", 10, 0),
        MetricSpec("temporary_bytes", 100, 1, counter=True),
        MetricSpec("host_free_bytes", 20, 2, lower_bound=True),
    )


def _sample(offset: float, values: dict[str, int | None], **kwargs) -> MetricSample:
    return MetricSample(offset, values, **kwargs)


def test_incremental_monitor_returns_active_operation_stop_immediately() -> None:
    monitor = IncrementalThresholdMonitor(_specs())

    stop = monitor.observe(
        _sample(11.0, {"elapsed_seconds": 11}),
        active_operation="merge.files",
    )

    assert stop is not None
    assert stop.metric_code == "elapsed_seconds"
    assert stop.monotonic_offset_seconds == 11.0
    assert stop.active_operation == "merge.files"
    assert monitor.actionable_stop == stop


def test_incremental_monitor_preserves_simultaneous_and_later_crossings() -> None:
    monitor = IncrementalThresholdMonitor(_specs())
    stop = monitor.observe(
        _sample(
            11.0,
            {
                "elapsed_seconds": 11,
                "temporary_bytes": 101,
                "host_free_bytes": 30,
            },
        ),
        active_operation="merge.files",
    )
    monitor.mark_cancellation_started(11.1)
    monitor.observe(
        _sample(
            12.0,
            {
                "elapsed_seconds": 12,
                "temporary_bytes": 102,
                "host_free_bytes": 19,
            },
        ),
        active_operation="cleanup.stage",
    )

    result = monitor.finalize()
    metrics = {metric.metric_code: metric for metric in result.metrics}

    assert stop is not None and stop.metric_code == "elapsed_seconds"
    assert metrics["elapsed_seconds"].crossed_before_cancel is True
    assert metrics["temporary_bytes"].crossed_before_cancel is True
    assert metrics["host_free_bytes"].crossed_after_cancel is True
    assert metrics["temporary_bytes"].maximum_pre_cancel_value == 101


def test_incremental_monitor_keeps_terminal_crossing_noncausal() -> None:
    monitor = IncrementalThresholdMonitor(_specs())
    monitor.observe(
        _sample(
            1.0,
            {
                "elapsed_seconds": 1,
                "temporary_bytes": 90,
                "host_free_bytes": 30,
            },
        )
    )
    monitor.observe(
        _sample(
            2.0,
            {
                "elapsed_seconds": 2,
                "temporary_bytes": 110,
                "host_free_bytes": 30,
            },
            terminal=True,
        )
    )

    result = monitor.finalize()
    temporary = result.metrics[1]

    assert result.primary_stop_category is None
    assert temporary.crossed_terminal is True
    assert temporary.maximum_terminal_value == 110
    assert temporary.crossed_before_cancel is False


def test_incremental_monitor_marks_ownership_loss_reset_and_availability() -> None:
    monitor = IncrementalThresholdMonitor(_specs())
    monitor.observe(
        _sample(
            1.0,
            {
                "elapsed_seconds": 1,
                "temporary_bytes": 90,
            },
        ),
        active_operation="merge.files",
    )
    monitor.observe(
        _sample(
            2.0,
            {
                "elapsed_seconds": 2,
                "temporary_bytes": 10,
            },
            ownership_exclusive=False,
        ),
        active_operation="merge.files",
        operation_attribution="operation_attribution_unknown",
    )

    metrics = {metric.metric_code: metric for metric in monitor.finalize().metrics}

    assert metrics["temporary_bytes"].counter_reset_or_wrap is True
    assert metrics["temporary_bytes"].exclusive_attribution is False
    assert metrics["host_free_bytes"].availability == "unavailable"
    assert metrics["host_free_bytes"].sample_count == 2


def test_incremental_monitor_refuses_malformed_or_post_terminal_samples() -> None:
    monitor = IncrementalThresholdMonitor(_specs())
    with pytest.raises(ThresholdEvaluationError):
        monitor.observe(_sample(1.0, {"unknown": 1}))

    complete = IncrementalThresholdMonitor(_specs())
    complete.observe(_sample(1.0, {}, terminal=True))
    with pytest.raises(ThresholdEvaluationError, match="terminal"):
        complete.observe(_sample(2.0, {}))


def test_incremental_monitor_final_output_is_deterministic_and_bounded() -> None:
    monitor = IncrementalThresholdMonitor(_specs(), max_payload_bytes=1_048_576)
    monitor.observe(
        _sample(1.0, {"elapsed_seconds": 11}),
        active_operation="guard.publication_prepare",
    )

    result = monitor.finalize()
    first = json.dumps(result.to_payload(), sort_keys=True, separators=(",", ":"))
    second = json.dumps(result.to_payload(), sort_keys=True, separators=(",", ":"))

    assert first == second
    assert len(first.encode("utf-8")) <= 1_048_576
    assert "guard.publication_prepare" in first
    for forbidden in ("path", "database", "backend", "sql", "payload"):
        assert forbidden not in first.lower()
