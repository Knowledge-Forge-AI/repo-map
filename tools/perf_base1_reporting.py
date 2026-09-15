"""Reporting and equivalence verification for PERF-BASE1 campaign."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
import json
import statistics
from typing import SupportsIndex, SupportsInt

from repomap_test_support.performance_baseline import (
    overhead_summary,
    require_output_equivalence,
    spool_threshold_decision,
)


def coerce_int(value: object) -> int:
    """Accurately convert supported JSON scalar numeric or int-compatible values to int."""
    if isinstance(value, (int, float, str, bytes, bytearray)):
        return int(value)
    if isinstance(value, (SupportsInt, SupportsIndex)):
        return int(value)
    raise TypeError(f"cannot convert {type(value).__name__} to int")


def build_campaign_report(
    *,
    workload: Mapping[str, object],
    admissions: Sequence[Mapping[str, object]],
    small: Sequence[Mapping[str, object]],
    overhead_runs: Sequence[Mapping[str, object]],
    representative: Sequence[Mapping[str, object]],
    queries: Sequence[Mapping[str, object]],
    connection: Mapping[str, object],
    elapsed_seconds: float,
) -> dict[str, object]:
    """Compile the canonical PERF-BASE1 baseline report payload."""
    disabled = [
        coerce_int(item["total_wall_ns"])
        for item in overhead_runs
        if not item["instrumented"]
    ]
    enabled = [
        coerce_int(item["total_wall_ns"])
        for item in overhead_runs
        if item["instrumented"]
    ]
    overhead = overhead_summary(disabled, enabled)
    if not overhead["accepted"]:
        overhead["interpretation"] = "not_accepted"

    require_equivalent_results(representative)
    if len({item["structural_digest"] for item in representative}) != 1:
        raise RuntimeError("PERF-BASE1 representative digest differs")
    if (
        len(
            {
                json.dumps(item["family_counts"], sort_keys=True)
                for item in representative
            }
        )
        != 1
    ):
        raise RuntimeError("PERF-BASE1 family counts differ")

    median_spool = int(
        statistics.median(
            coerce_int(item["spool_elapsed_ns"]) for item in representative
        )
    )
    median_pre_final = int(
        statistics.median(
            coerce_int(item["pre_final_elapsed_ns"]) for item in representative
        )
    )
    median_total = int(
        statistics.median(
            coerce_int(item["total_wall_ns"]) for item in representative
        )
    )
    decision = spool_threshold_decision(
        spool_ns=median_spool,
        pre_final_ns=median_pre_final,
        total_refresh_ns=median_total,
    )
    stages = median_stages(representative)
    bottleneck_stages = {
        code: value
        for code, value in stages.items()
        if code not in {"refresh.total", "staging.pre_final_commit"}
    }
    bottlenecks = sorted(
        bottleneck_stages.items(), key=lambda item: item[1], reverse=True
    )[:3]
    return {
        "schema": "repomap-performance-baseline-v1",
        "environment": {
            "readback_driver": "psycopg",
            "server_time": "unobserved",
        },
        "workload": workload,
        "host_admission": admissions,
        "instrumentation_version": 1,
        "small_correctness": small,
        "overhead_measurements": overhead_runs,
        "overhead_summary": overhead,
        "representative_runs": representative,
        "median_stage_wall_ns": stages,
        "stage_reconciliation": (
            "passed"
            if all(
                item.get("stage_reconciliation") == "passed"
                for item in representative
            )
            else "failed"
        ),
        "query_samples": queries,
        "connection_setup_samples": connection,
        "decision_calculations": decision,
        "top_bottlenecks": bottlenecks,
        "limitations": [
            "server timing is unobserved",
            "process CPU excludes subprocesses and PostgreSQL",
            "COPY fuses client replay and server ingest and is excluded from spool authorization",
            "published-state digest does not independently prove client byte-stream identity",
        ],
        "elapsed_seconds": elapsed_seconds,
    }


def median_stages(
    results: Sequence[Mapping[str, object]],
) -> dict[str, int]:
    """Calculate median wall time in nanoseconds across observed phase spans."""
    if not results:
        raise ValueError("PERF-BASE1 run results cannot be empty for median stages")
    phase_dicts: list[Mapping[str, object]] = []
    for item in results:
        if "phase_wall_ns" not in item:
            raise KeyError("PERF-BASE1 run result missing required 'phase_wall_ns' field")
        phases = item["phase_wall_ns"]
        if not isinstance(phases, Mapping):
            raise TypeError("PERF-BASE1 run result 'phase_wall_ns' must be a mapping")
        phase_dicts.append(phases)
    codes = set.intersection(*(set(p.keys()) for p in phase_dicts))
    return {
        code: int(statistics.median(coerce_int(p[code]) for p in phase_dicts))
        for code in sorted(codes)
    }


def jsonable(value: object) -> object:
    """Recursively convert dataclasses and tuples to JSON-serializable structures."""
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, tuple):
        return [jsonable(item) for item in value]
    return value


def require_small_equivalence(
    results: Sequence[Mapping[str, object]],
) -> None:
    """Assert exactly two small-workload runs produced identical outputs."""
    if len(results) != 2:
        raise RuntimeError("PERF-BASE1 small equivalence set is incomplete")
    require_equivalent_results(results)


def require_equivalent_results(
    results: Sequence[Mapping[str, object]],
) -> None:
    """Assert multiple run outputs produced identical digest and family counts."""
    if not results:
        raise RuntimeError("PERF-BASE1 equivalence set is incomplete")
    keys = (
        "source_input_digest",
        "configuration_digest",
        "extractor_digest",
        "structural_digest",
        "family_counts",
        "publication_state",
    )
    expected = {key: results[0][key] for key in keys}
    for result in results[1:]:
        require_output_equivalence(
            expected,
            {key: result[key] for key in keys},
        )


_report = build_campaign_report
_jsonable = jsonable
_median_stages = median_stages
_require_small_equivalence = require_small_equivalence
_require_equivalent_results = require_equivalent_results

__all__ = (
    "_jsonable",
    "_median_stages",
    "_report",
    "_require_equivalent_results",
    "_require_small_equivalence",
    "build_campaign_report",
    "coerce_int",
    "jsonable",
    "median_stages",
    "require_equivalent_results",
    "require_small_equivalence",
)
