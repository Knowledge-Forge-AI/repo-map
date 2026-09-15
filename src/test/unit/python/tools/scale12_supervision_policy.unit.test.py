from __future__ import annotations

import math

from repomap_test_support.scale12_supervision_policy import (
    OperationArmedElapsedMonitor,
    attribution_qualification_monitor,
)
from scale11_threshold_evaluator import (
    IncrementalThresholdMonitor,
    MetricSample,
    MetricSpec,
)
from scale12_resource_sampling import GIB, Scale12ResourceSampler, threshold_specs


def test_full_campaign_monitor_selects_low_host_floor_before_operation() -> None:
    monitor = IncrementalThresholdMonitor(threshold_specs())

    stop = monitor.observe(
        MetricSample(
            0.25,
            {
                "elapsed_seconds": 1,
                "client_peak_rss_bytes": 1,
                "host_free_bytes": 14 * GIB,
            },
        ),
        active_operation=None,
    )

    assert stop is not None
    assert stop.metric_code == "host_free_bytes"
    assert stop.active_operation is None


def test_raw_elapsed_monitor_can_cross_before_target_operation() -> None:
    monitor = IncrementalThresholdMonitor(
        (MetricSpec("elapsed_seconds", 1, 0),)
    )

    stop = monitor.observe(
        MetricSample(1.01, {"elapsed_seconds": 2}), active_operation=None
    )

    assert stop is not None
    assert stop.metric_code == "elapsed_seconds"
    assert stop.active_operation is None


def test_attribution_policy_excludes_host_floor_without_weakening_campaign() -> None:
    monitor = attribution_qualification_monitor()

    assert monitor.metric_codes == frozenset(
        {"elapsed_seconds", "client_peak_rss_bytes"}
    )
    assert "host_free_bytes" not in monitor.metric_codes
    assert {
        spec.category: spec.limit for spec in threshold_specs()
    }["host_free_bytes"] == 20 * GIB
    resource_sample = Scale12ResourceSampler(
        {
            "client_peak_rss_bytes": lambda: 1,
            "host_free_bytes": lambda: 1,
        },
        cadence_ns=1,
    ).capture()
    assert resource_sample is not None
    values = {
        code: value
        for code, value in resource_sample.values.items()
        if code in monitor.metric_codes
    }
    values["elapsed_seconds"] = 1

    assert monitor.observe(MetricSample(0.25, values)) is None


def test_elapsed_policy_arms_on_target_without_rebasing_timestamps() -> None:
    monitor = OperationArmedElapsedMonitor("merge.files", delay_seconds=1)

    assert monitor.metric_codes == frozenset({"elapsed_seconds"})
    assert (
        monitor.observe(
            MetricSample(2.0, {"elapsed_seconds": 2}), active_operation=None
        )
        is None
    )
    assert (
        monitor.observe(
            MetricSample(4.25, {"elapsed_seconds": 5}),
            active_operation="prepare.stage",
        )
        is None
    )
    assert (
        monitor.observe(
            MetricSample(5.0, {"elapsed_seconds": 5}),
            active_operation="merge.files",
        )
        is None
    )
    assert (
        monitor.observe(
            MetricSample(6.0, {"elapsed_seconds": 6}),
            active_operation="merge.files",
        )
        is None
    )

    stop = monitor.observe(
        MetricSample(6.01, {"elapsed_seconds": 7}),
        active_operation="merge.files",
    )

    assert stop is not None
    assert stop.active_operation == "merge.files"
    assert math.isclose(stop.monotonic_offset_seconds, 6.01)
    monitor.mark_cancellation_started(6.02)
    monitor.observe(
        MetricSample(
            6.03,
            {"elapsed_seconds": 7},
            cancellation_started=True,
            terminal=True,
        ),
        active_operation=None,
    )
    assert monitor.finalize().primary_stop_category == "elapsed_seconds"
