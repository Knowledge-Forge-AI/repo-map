"""Per-arm W4 observations with truthful backend and locator provenance."""

from __future__ import annotations

import time
from typing import Any

from common_lore_index.retrieval.context_assembly import ContextReadPort, build_compact_context
from common_lore_index.retrieval.context_budget import serialize_compact_json
from common_lore_index.retrieval.context_contracts import ContextRequest
from common_lore_index.server.context_read_sqlite import SqliteContextReadAdapter
from retrieval_evaluation_context_catalog import ContextEvaluationTask
from retrieval_evaluation_context_grading import grade_graph_packet, grade_native_envelope
from retrieval_evaluation_context_native import (
    ContextNativeView,
    execute_context_native_task,
)


def _run_arm_observation(
    arm: str,
    task: ContextEvaluationTask,
    *,
    sqlite_adapter: SqliteContextReadAdapter,
    postgres_adapter: ContextReadPort | None,
    native_view: ContextNativeView | None = None,
) -> dict[str, Any]:
    if arm == "native_tools_baseline":
        if native_view is None:
            return {
                "status": "unavailable", "unavailable_reason": "native_view_required",
                "gold_locator_rank": None, "returned_keys": [],
                "canonical_identity_claimed": False, "ambiguity_preserved": None,
                "duplicate_path_identity_preserved": None, "actual_bytes": None,
                "budget_bytes": None, "budget_compliant": None,
                "admitted_item_count": None, "admitted_neighbor_count": None,
                "omission_counts": {}, "sql_statements_executed": None,
                "seed_expansions_executed": None, "sqlite_progress_callbacks": None,
                "sqlite_vm_steps_estimate": None, "source_files_opened": None,
                "native_source_bytes": None, "elapsed_ms": 0,
            }
        state, envelope, elapsed_ns, byte_accounting = execute_context_native_task(
            task,
            native_view,
            graph_id=sqlite_adapter.graph_id,
            selected_binding_ids=tuple(
                sorted({binding_id for binding_id, _ in native_view.path_to_binding.values()})
            ),
        )
        native_paths = {
            hit.locator.binding_id
            for hit in envelope.hits
            if hit.locator.source_relative_path == "shared/README.md"
        }
        return {
            "status": "completed" if state == "completed" else envelope.capability_state.value,
            "unavailable_reason": envelope.unavailable_reason,
            "gold_locator_rank": grade_native_envelope(task, envelope),
            "returned_keys": [], "canonical_identity_claimed": False,
            "ambiguity_preserved": None,
            "duplicate_path_identity_preserved": (
                len(native_paths) >= 2 if task.expect_duplicate_path else None
            ),
            "actual_bytes": None, "budget_bytes": None, "budget_compliant": None,
            "admitted_item_count": None, "admitted_neighbor_count": None,
            "omission_counts": {}, "sql_statements_executed": None,
            "seed_expansions_executed": None, "sqlite_progress_callbacks": None,
            "sqlite_vm_steps_estimate": None, "source_files_opened": None,
            "native_source_bytes": byte_accounting.internal_source_io_bytes,
            "native_stdout_bytes": byte_accounting.observed_output_payload_bytes,
            "elapsed_ms": max(0, int(elapsed_ns / 1_000_000)),
        }

    t0 = time.monotonic()
    if arm in ("current_graph_navigation_sqlite", "current_graph_navigation_postgres"):
        is_pg = arm.endswith("_postgres")
        adapter: ContextReadPort | None = postgres_adapter if is_pg else sqlite_adapter
        if adapter is None:
            return {"status": "unavailable", "unavailable_reason": "postgres_adapter_required", "gold_locator_rank": None}
        pkt = build_compact_context(
            ContextRequest(
                graph_id=adapter.graph_id, mode="current_literal_enumeration", query=task.query,
                canonical_key=task.canonical_key, intent=None, budget_bytes=65536,
                max_items=16, expand_depth=0,
            ),
            adapter,
        )
    else:
        is_pg = arm.endswith("_postgres")
        adapter = postgres_adapter if is_pg else sqlite_adapter
        if adapter is None:
            return {"status": "unavailable", "unavailable_reason": "postgres_adapter_required", "gold_locator_rank": None}
        exp = task.expand_depth if arm.startswith("compact_context_") else 0
        b_bytes = task.budget_bytes if arm.startswith("compact_context_") else 65536
        pkt = build_compact_context(
            ContextRequest(
                graph_id=adapter.graph_id, mode=task.mode, query=task.query,
                canonical_key=task.canonical_key, intent=task.intent,
                kinds=(task.kind,) if task.kind else (), budget_bytes=b_bytes,
                max_items=16, expand_depth=exp,
            ),
            adapter,
        )

    raw = serialize_compact_json(pkt)
    elapsed_ms = max(0, int((time.monotonic() - t0) * 1000))
    items = pkt.get("items") or []
    neighbors = pkt.get("neighbors") or []
    returned_keys = [str(it["canonical_key"]) for it in (*items, *neighbors)]
    amb_status = ((pkt.get("ordering") or {}).get("ambiguity") or {}).get("status")
    amb_preserved = (amb_status == "ambiguous") if task.expect_ambiguous else True
    all_locs = [loc for it in (*items, *neighbors) for loc in (it.get("locations") or [])]
    distinct_bindings_for_dup = {
        str(loc["source_binding_id"])
        for loc in all_locs
        if loc.get("source_relative_path") == "shared/README.md"
    }
    dup_preserved = (len(distinct_bindings_for_dup) >= 2) if task.expect_duplicate_path else True
    wl = pkt.get("work_ledger") or {}
    req_budget = int((pkt.get("request") or {}).get("budget_bytes", task.budget_bytes))
    actual_bytes = wl.get("actual_bytes")
    return {
        "status": pkt["status"], "unavailable_reason": pkt.get("unavailable_reason"),
        "gold_locator_rank": grade_graph_packet(task, pkt),
        "returned_keys": returned_keys, "canonical_identity_claimed": True,
        "ambiguity_preserved": amb_preserved,
        "duplicate_path_identity_preserved": dup_preserved,
        "actual_bytes": int(actual_bytes) if isinstance(actual_bytes, int) else None,
        "budget_bytes": req_budget,
        "budget_compliant": len(raw) == int(actual_bytes) <= req_budget if isinstance(actual_bytes, int) else None,
        "admitted_item_count": len(items), "admitted_neighbor_count": len(neighbors),
        "omission_counts": dict(pkt.get("omission_counts") or {}),
        "sql_statements_executed": wl.get("sql_statements_executed"),
        "seed_expansions_executed": wl.get("seed_expansions_executed"),
        "sqlite_progress_callbacks": wl.get("sqlite_progress_callbacks"),
        "sqlite_vm_steps_estimate": wl.get("sqlite_vm_steps_estimate"),
        "source_files_opened": int((pkt.get("freshness") or {}).get("files_checked", 0)),
        "native_source_bytes": None, "elapsed_ms": elapsed_ms,
    }


__all__ = ["_run_arm_observation"]
