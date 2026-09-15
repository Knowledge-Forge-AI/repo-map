from __future__ import annotations

import json
from pathlib import Path

import pytest

import scale11_threshold_evaluator as scale11_threshold_evaluator

REPO_ROOT = Path(__file__).resolve().parents[5]


def load_tool_module():
    return scale11_threshold_evaluator


def _specs(tool):
    return (
        tool.MetricSpec("elapsed_seconds", limit=90, priority=0),
        tool.MetricSpec("temporary_bytes", limit=1_000, priority=1, counter=True),
        tool.MetricSpec("wal_bytes", limit=2_000, priority=2, counter=True),
    )


def _sample(tool, timestamp, values, **kwargs):
    return tool.MetricSample(timestamp_seconds=timestamp, values=values, **kwargs)


def test_no_crossing_retains_terminal_and_missing_sample_evidence() -> None:
    tool = load_tool_module()

    result = tool.evaluate_thresholds(
        _specs(tool),
        (
            _sample(
                tool,
                1.0,
                {"elapsed_seconds": 10, "temporary_bytes": 100},
            ),
            _sample(
                tool,
                2.0,
                {
                    "elapsed_seconds": 20,
                    "temporary_bytes": 200,
                    "wal_bytes": 300,
                },
                terminal=True,
            ),
        ),
    )

    assert result.primary_stop_category is None
    by_category = {metric.category: metric for metric in result.metrics}
    assert by_category["elapsed_seconds"].maximum_observed_value == 20
    assert by_category["elapsed_seconds"].terminal_sample_value == 20
    assert by_category["wal_bytes"].missing_sample_count == 1
    assert by_category["wal_bytes"].crossing_timing == "none"


def test_one_crossing_selects_pre_cancellation_primary_stop() -> None:
    tool = load_tool_module()

    result = tool.evaluate_thresholds(
        _specs(tool),
        (
            _sample(
                tool,
                1.0,
                {
                    "elapsed_seconds": 91,
                    "temporary_bytes": 10,
                    "wal_bytes": 20,
                },
            ),
            _sample(
                tool,
                2.0,
                {
                    "elapsed_seconds": 95,
                    "temporary_bytes": 20,
                    "wal_bytes": 40,
                },
                cancellation_started=True,
                terminal=True,
            ),
        ),
    )

    elapsed = result.metrics[0]
    assert result.primary_stop_category == "elapsed_seconds"
    assert elapsed.crossed is True
    assert elapsed.first_crossing_timestamp_seconds == 1.0
    assert elapsed.first_crossing_sample == 0
    assert elapsed.crossing_timing == "before_cancellation"
    assert elapsed.maximum_observed_value == 95
    assert elapsed.terminal_sample_value == 95


def test_simultaneous_crossings_are_all_preserved_before_priority_selection() -> None:
    tool = load_tool_module()
    specs = (
        tool.MetricSpec("temporary_bytes", limit=100, priority=5, counter=True),
        tool.MetricSpec("wal_bytes", limit=100, priority=2, counter=True),
    )

    result = tool.evaluate_thresholds(
        specs,
        (
            _sample(
                tool,
                3.0,
                {"temporary_bytes": 101, "wal_bytes": 101},
            ),
        ),
    )

    assert result.primary_stop_category == "wal_bytes"
    assert {metric.category for metric in result.metrics if metric.crossed} == {
        "temporary_bytes",
        "wal_bytes",
    }
    assert {metric.first_crossing_sample for metric in result.metrics} == {0}


def test_second_later_crossing_is_not_erased_by_first_stop_action() -> None:
    tool = load_tool_module()

    result = tool.evaluate_thresholds(
        _specs(tool),
        (
            _sample(
                tool,
                1.0,
                {
                    "elapsed_seconds": 91,
                    "temporary_bytes": 100,
                    "wal_bytes": 100,
                },
            ),
            _sample(
                tool,
                2.0,
                {
                    "elapsed_seconds": 92,
                    "temporary_bytes": 1_001,
                    "wal_bytes": 2_001,
                },
                cancellation_started=True,
            ),
            _sample(
                tool,
                3.0,
                {
                    "elapsed_seconds": 93,
                    "temporary_bytes": 1_002,
                    "wal_bytes": 2_002,
                },
                cancellation_started=True,
                terminal=True,
            ),
        ),
    )

    by_category = {metric.category: metric for metric in result.metrics}
    assert result.primary_stop_category == "elapsed_seconds"
    assert by_category["temporary_bytes"].crossed is True
    assert by_category["temporary_bytes"].crossing_timing == "after_cancellation"
    assert by_category["wal_bytes"].crossed is True
    assert by_category["wal_bytes"].crossing_timing == "after_cancellation"


def test_terminal_only_crossing_is_not_reported_as_a_cause() -> None:
    tool = load_tool_module()

    result = tool.evaluate_thresholds(
        _specs(tool),
        (
            _sample(
                tool,
                1.0,
                {
                    "elapsed_seconds": 80,
                    "temporary_bytes": 900,
                    "wal_bytes": 1_900,
                },
            ),
            _sample(
                tool,
                2.0,
                {
                    "elapsed_seconds": 80,
                    "temporary_bytes": 1_100,
                    "wal_bytes": 1_900,
                },
                cancellation_started=True,
                terminal=True,
            ),
        ),
    )

    temporary = result.metrics[1]
    assert result.primary_stop_category is None
    assert temporary.crossing_timing == "terminal_only"
    assert temporary.crossed_before_cancellation is False


def test_ownership_loss_and_counter_reset_remove_exclusive_attribution() -> None:
    tool = load_tool_module()

    result = tool.evaluate_thresholds(
        _specs(tool),
        (
            _sample(
                tool,
                1.0,
                {
                    "elapsed_seconds": 10,
                    "temporary_bytes": 900,
                    "wal_bytes": 1_900,
                },
            ),
            _sample(
                tool,
                2.0,
                {
                    "elapsed_seconds": 20,
                    "temporary_bytes": 100,
                    "wal_bytes": 2_100,
                },
                ownership_exclusive=False,
                terminal=True,
            ),
        ),
    )

    by_category = {metric.category: metric for metric in result.metrics}
    assert by_category["temporary_bytes"].counter_reset_or_wrap is True
    assert by_category["temporary_bytes"].ownership_exclusive is False
    assert by_category["wal_bytes"].ownership_exclusive is False
    assert by_category["wal_bytes"].crossed is True


def test_cancellation_between_samples_labels_later_crossing_without_causality() -> None:
    tool = load_tool_module()

    result = tool.evaluate_thresholds(
        _specs(tool),
        (
            _sample(
                tool,
                1.0,
                {
                    "elapsed_seconds": 89,
                    "temporary_bytes": 900,
                    "wal_bytes": 1_900,
                },
            ),
            _sample(
                tool,
                2.0,
                {
                    "elapsed_seconds": 91,
                    "temporary_bytes": 900,
                    "wal_bytes": 1_900,
                },
                cancellation_started=True,
            ),
            _sample(
                tool,
                3.0,
                {
                    "elapsed_seconds": 92,
                    "temporary_bytes": 900,
                    "wal_bytes": 1_900,
                },
                cancellation_started=True,
                terminal=True,
            ),
        ),
    )

    assert result.primary_stop_category is None
    assert result.metrics[0].crossing_timing == "after_cancellation"


@pytest.mark.parametrize(
    "build",
    [
        lambda tool: ((tool.MetricSpec("bad/category", 1, 0),), ()),
        lambda tool: ((tool.MetricSpec("metric", -1, 0),), ()),
        lambda tool: (
            (tool.MetricSpec("metric", 1, 0), tool.MetricSpec("metric", 2, 1)),
            (),
        ),
        lambda tool: (
            (tool.MetricSpec("metric", 1, 0),),
            (tool.MetricSample(0.0, {"unknown": 1}),),
        ),
        lambda tool: (
            (tool.MetricSpec("metric", 1, 0),),
            (tool.MetricSample(0.0, {"metric": True}),),
        ),
        lambda tool: (
            (tool.MetricSpec("metric", 1, 0),),
            (
                tool.MetricSample(2.0, {"metric": 0}),
                tool.MetricSample(1.0, {"metric": 0}),
            ),
        ),
    ],
)
def test_malformed_metric_input_fails_closed(build) -> None:
    tool = load_tool_module()
    specs, samples = build(tool)

    with pytest.raises(tool.ThresholdEvaluationError):
        tool.evaluate_thresholds(specs, samples)


def test_payload_is_deterministic_bounded_and_path_free() -> None:
    tool = load_tool_module()
    private_marker = "/private/not-public"
    specs = tuple(
        tool.MetricSpec(f"metric_{index:02d}", limit=index, priority=index)
        for index in range(16)
    )
    sample = tool.MetricSample(
        timestamp_seconds=1.0,
        values={spec.category: index for index, spec in enumerate(specs)},
        terminal=True,
    )

    first = tool.evaluate_thresholds(specs, (sample,)).to_payload()
    second = tool.evaluate_thresholds(specs, (sample,)).to_payload()
    encoded = json.dumps(first, sort_keys=True, separators=(",", ":"))

    assert first == second
    assert first["schema_version"] == 1
    assert len(encoded.encode("utf-8")) <= 65_536
    assert private_marker not in encoded
    for forbidden in (
        "path",
        "repository",
        "database",
        "credential",
        "connection",
        "command",
        "backend",
    ):
        assert forbidden not in encoded
