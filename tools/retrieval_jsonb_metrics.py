"""EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) plan extraction and cost/disposition accounting for W5 (ADR 0137)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math
from types import MappingProxyType
from typing import Any

from retrieval_jsonb_contracts import (
    GIN_OPS_INDEX,
    GIN_PATH_OPS_INDEX,
    _thaw_jsonable,
)
from retrieval_semantic_representation import (
    _require,
)


@dataclass(frozen=True)
class ExplainPlanSummary:
    """Extracted plan, buffer, timing, and index-usage summary from EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)."""

    variant: str
    workload_id: str
    planning_time_ms: float
    execution_time_ms: float
    total_cost: float
    actual_rows: int
    shared_hit_blocks: int
    shared_read_blocks: int
    temp_read_blocks: int
    temp_written_blocks: int
    plan_node_types: tuple[str, ...]
    index_names_used: tuple[str, ...]
    used_gin_index: bool
    used_seq_scan: bool
    raw_explain_json: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "variant": self.variant,
            "workload_id": self.workload_id,
            "planning_time_ms": self.planning_time_ms,
            "execution_time_ms": self.execution_time_ms,
            "total_cost": self.total_cost,
            "actual_rows": self.actual_rows,
            "shared_hit_blocks": self.shared_hit_blocks,
            "shared_read_blocks": self.shared_read_blocks,
            "temp_read_blocks": self.temp_read_blocks,
            "temp_written_blocks": self.temp_written_blocks,
            "plan_node_types": list(self.plan_node_types),
            "index_names_used": list(self.index_names_used),
            "used_gin_index": self.used_gin_index,
            "used_seq_scan": self.used_seq_scan,
            "raw_explain_json": _thaw_jsonable(self.raw_explain_json),
        }


def _freeze_explain_json(value: Any) -> Any:
    """Freeze PG plans under plan-specific work bounds, independent of receipt JSON.

    Plans nest a mapping and Plans array per executor level. Real accepted-run
    queries exceed the shallow publication/representation JSON limit.
    """
    remaining_items, remaining_bytes = 20000, 2 * 1024 * 1024

    def freeze(item: Any, depth: int) -> Any:
        nonlocal remaining_items, remaining_bytes
        remaining_items -= 1
        _require(depth <= 64 and remaining_items >= 0, "invalid_explain_json", "plan depth/item bound exceeded")
        if isinstance(item, Mapping):
            _require(len(item) <= remaining_items, "invalid_explain_json", "plan mapping bound exceeded")
            copied: dict[str, Any] = {}
            for key, child in item.items():
                _require(type(key) is str and bool(key), "invalid_explain_json", "plan key must be nonempty text")
                freeze(key, depth + 1)
                copied[key] = freeze(child, depth + 1)
            return MappingProxyType(copied)
        if type(item) in (list, tuple):
            _require(len(item) <= remaining_items, "invalid_explain_json", "plan sequence bound exceeded")
            return tuple(freeze(child, depth + 1) for child in item)
        if type(item) is str:
            encoded = item.encode('utf-8', errors='strict')
            remaining_bytes -= len(encoded)
            _require(len(encoded) <= 8192 and remaining_bytes >= 0 and '\x00' not in item,
                     "invalid_explain_json", "plan text bound exceeded")
            return item
        if item is None or type(item) in (bool, int):
            return item
        _require(type(item) is float and math.isfinite(item), "invalid_explain_json", "invalid plan scalar")
        return item

    return freeze(value, 0)


def summarize_explain_plan(
    variant: str, workload_id: str, explain_root: Mapping[str, Any] | Sequence[Any]
) -> ExplainPlanSummary:
    """Extract deterministic plan metrics, top-level + planning buffer counts, node types, and GIN usage."""
    top = explain_root[0] if isinstance(explain_root, Sequence) and explain_root else explain_root
    _require(
        isinstance(top, Mapping) and isinstance(top.get("Plan"), Mapping),
        "invalid_explain_json",
        "missing Plan object",
    )
    assert isinstance(top, Mapping)
    top = _freeze_explain_json(top)
    plan = top["Plan"]
    node_types: list[str] = []
    index_names: list[str] = []

    def walk(node: Mapping[str, Any]) -> None:
        if isinstance(node.get("Node Type"), str):
            node_types.append(str(node["Node Type"]))
        if isinstance(node.get("Index Name"), str):
            index_names.append(str(node["Index Name"]))
        for child in node.get("Plans") or ():
            if isinstance(child, Mapping):
                walk(child)

    walk(plan)
    raw_planning = top.get("Planning")
    planning_bufs: Mapping[str, Any] = raw_planning if isinstance(raw_planning, Mapping) else {}

    def _buf_total(key: str) -> int:
        return int(plan.get(key) or 0) + int(planning_bufs.get(key) or 0)

    return ExplainPlanSummary(
        variant,
        workload_id,
        round(float(top.get("Planning Time") or 0.0), 4),
        round(float(top.get("Execution Time") or 0.0), 4),
        round(float(plan.get("Total Cost") or 0.0), 4),
        int(plan.get("Actual Rows") or 0),
        _buf_total("Shared Hit Blocks"),
        _buf_total("Shared Read Blocks"),
        _buf_total("Temp Read Blocks"),
        _buf_total("Temp Written Blocks"),
        tuple(node_types),
        tuple(index_names),
        any(ix in {GIN_OPS_INDEX, GIN_PATH_OPS_INDEX} for ix in index_names),
        "Seq Scan" in node_types,
        top,
    )


def _derive_measured_disposition(
    *,
    equality_passed: bool,
    cleanup_verified: bool,
    projected_row_count: int,
    source_read_ms: float,
    projection_build_ms: float,
    projection_refresh_ms: float,
    variant_query_exec_ms: Mapping[str, float],
    index_accounting: Mapping[str, Any],
    explain_summaries: Mapping[str, Sequence[Mapping[str, Any]]],
) -> tuple[str, dict[str, Any]]:
    def _variant_ms(v: str) -> float:
        return round(
            sum(
                float(s.get("planning_time_ms", 0.0)) + float(s.get("execution_time_ms", 0.0))
                for s in explain_summaries.get(v, ())
            ),
            4,
        )

    total_index_build_ms = round(
        sum(
            float(v.get("index_build_ms") or 0.0) + float(v.get("explain_index_rebuild_ms") or 0.0)
            for v in index_accounting.values()
            if isinstance(v, Mapping)
        ),
        4,
    )
    max_total_bytes = max(
        (int(v.get("total_bytes") or 0) for v in index_accounting.values() if isinstance(v, Mapping)),
        default=0,
    )
    lifecycle_overhead_ms = round(projection_build_ms + projection_refresh_ms + total_index_build_ms, 4)
    if not equality_passed or not cleanup_verified:
        return "reject_failed_equality_or_cleanup", {
            "equality_passed": equality_passed,
            "cleanup_verified": cleanup_verified,
            "measurements_status": (
                "unavailable_equality_gate_failed" if not equality_passed else "unavailable_cleanup_failed"
            ),
            "projected_row_count": projected_row_count,
            "source_read_ms": source_read_ms,
            "projection_build_ms": projection_build_ms,
            "projection_refresh_ms": projection_refresh_ms,
            "total_index_build_ms": total_index_build_ms,
            "lifecycle_overhead_ms": lifecycle_overhead_ms,
            "variant_query_exec_ms": dict(variant_query_exec_ms),
            "max_projection_total_bytes": max_total_bytes,
            "relational_plan_exec_ms": None,
            "jsonb_gin_ops_plan_exec_ms": None,
            "jsonb_gin_path_ops_plan_exec_ms": None,
            "gin_index_used_plan_count": None,
        }

    rel_ms = _variant_ms("relational_baseline")
    gin_ops_ms = _variant_ms("jsonb_gin_ops")
    gin_path_ms = _variant_ms("jsonb_gin_path_ops")
    gin_used_count = sum(
        1
        for v in ("jsonb_gin_ops", "jsonb_gin_path_ops")
        for s in explain_summaries.get(v, ())
        if s.get("used_gin_index")
    )
    evidence: dict[str, Any] = {
        "equality_passed": True,
        "cleanup_verified": True,
        "measurements_status": "measured",
        "projected_row_count": projected_row_count,
        "source_read_ms": source_read_ms,
        "projection_build_ms": projection_build_ms,
        "projection_refresh_ms": projection_refresh_ms,
        "total_index_build_ms": total_index_build_ms,
        "lifecycle_overhead_ms": lifecycle_overhead_ms,
        "variant_query_exec_ms": dict(variant_query_exec_ms),
        "max_projection_total_bytes": max_total_bytes,
        "relational_plan_exec_ms": rel_ms,
        "jsonb_gin_ops_plan_exec_ms": gin_ops_ms,
        "jsonb_gin_path_ops_plan_exec_ms": gin_path_ms,
        "gin_index_used_plan_count": gin_used_count,
    }
    best_jsonb_ms = min(gin_ops_ms, gin_path_ms) if explain_summaries else rel_ms
    if max_total_bytes > 0 and lifecycle_overhead_ms >= max(rel_ms - best_jsonb_ms, 0.0):
        return "retain_relational_baseline", evidence
    return "evaluate_jsonb_if_net_positive", evidence


__all__ = [
    "ExplainPlanSummary",
    "_derive_measured_disposition",
    "summarize_explain_plan",
]
