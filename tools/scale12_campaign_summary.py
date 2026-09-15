"""Bounded public-safe summary projection for the SCALE12 campaign."""

from __future__ import annotations

from typing import Mapping


def summarize_campaign(payload: Mapping[str, object]) -> dict[str, object]:
    """Collapse one raw campaign payload into bounded public-safe evidence."""

    runs = payload["runs"]
    assert isinstance(runs, list)
    completed = [run for run in runs if run["profile_summary"] is not None]
    targeted: dict[str, list[float]] = {}
    resource_maxima: dict[str, int] = {}
    resource_availability: dict[str, set[str]] = {}
    for run in runs:
        summary = run["profile_summary"]
        if run["stage"] == "C-targeted" and summary is not None:
            key = str(summary["work_items"])
            targeted.setdefault(key, []).append(float(summary["elapsed_seconds"]))
        for metric in run["threshold_evaluation"]["metrics"]:
            code = metric["metric_code"]
            resource_availability.setdefault(code, set()).add(
                metric["availability"]
            )
            candidates = (
                metric["maximum_pre_cancel_value"],
                metric["maximum_terminal_value"],
            )
            values = [value for value in candidates if value is not None]
            if values:
                resource_maxima[code] = max(
                    resource_maxima.get(code, 0), *values
                )
    max_operation_seconds = max(
        (
            max(run["operation_max_duration_seconds"].values(), default=0.0)
            for run in runs
        ),
        default=0.0,
    )
    return {
        "schema_version": 1,
        "result": payload["result"],
        "run_count": len(runs),
        "completed_run_count": len(completed),
        "cancelled_run_count": len(runs) - len(completed),
        "operation_code_count": payload["operation_code_count"],
        "stage_run_counts": {
            stage: sum(run["stage"].startswith(stage) for run in runs)
            for stage in "ABCD"
        },
        "delayed_stop_operations": [
            run["primary_stop_active_operation"]
            for run in runs
            if run["stage"] == "B-delayed"
        ],
        "targeted_elapsed_seconds": {
            key: {"minimum": min(values), "maximum": max(values)}
            for key, values in sorted(targeted.items(), key=lambda item: int(item[0]))
        },
        "maximum_operation_duration_seconds": max_operation_seconds,
        "instrumentation_median_overhead_percent": payload[
            "instrumentation_median_overhead_percent"
        ],
        "resource_maxima": dict(sorted(resource_maxima.items())),
        "resource_availability": {
            code: sorted(values)
            for code, values in sorted(resource_availability.items())
        },
    }
