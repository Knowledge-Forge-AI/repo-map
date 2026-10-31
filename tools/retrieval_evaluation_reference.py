"""Captured-projection reference adapter over S1 CapturedTextProjection (S3)."""

from __future__ import annotations

import json
import time

from common_lore_index.retrieval.projection_build import CapturedTextProjection
from common_lore_index.retrieval.projection_query import (
    CapturedTextQueryRequest,
    query_captured_text,
)
from common_lore_index.retrieval.publication_binding import (
    AcceptedPublicationReference,
    CorrespondenceRefusal,
)
from common_lore_index.retrieval.query_contracts import (
    CapabilityState,
    FallbackDisclosure,
    QueryEnvelope,
    QueryMode,
    QueryScope,
    unavailable_envelope,
)
from repomap_test_support.retrieval_evaluation_fixture import binding_id_for_alias
from retrieval_evaluation_accounting import ByteLayerAccounting
from retrieval_evaluation_grading import ExecutionState
from retrieval_evaluation_schema import EvaluationTask


def _outcome(
    state: ExecutionState, envelope: QueryEnvelope, elapsed_ns: int,
) -> tuple[ExecutionState, QueryEnvelope, int, ByteLayerAccounting]:
    return state, envelope, elapsed_ns, ByteLayerAccounting(
        observed_output_payload_bytes=len(json.dumps(envelope.to_dict(), sort_keys=True).encode("utf-8")),
        # This adapter queries an already built in-memory projection; setup owns artifact reads.
        artifact_store_bytes_read=0,
    )


def execute_projection_reference_task(
    task: EvaluationTask,
    projection: CapturedTextProjection,
    *,
    current_accepted: AcceptedPublicationReference,
) -> tuple[ExecutionState, QueryEnvelope, int, ByteLayerAccounting]:
    """Execute one evaluation task against CapturedTextProjection with advancement check."""
    requested_mode = QueryMode(task.requested_mode)
    selected_b_ids = tuple(
        sorted(binding_id_for_alias(a, task.graph_id) for a in task.selected_bindings)
    )
    scope = QueryScope(
        graph_id=task.graph_id,
        backend="captured_reference",
        publication_bundle_id=projection.publication_bundle_id,
        snapshot_manifest_id=projection.snapshot_manifest_id,
        selected_binding_ids=selected_b_ids,
        source_path_prefix=task.source_path_prefix,
    )

    plan = task.permitted_query_plan
    if (
        str(plan.get("workflow") or "") == "direct_handoff"
        or task.intended_match_surface == "direct_handoff"
        or requested_mode in {QueryMode.GRAPH_INVESTIGATION, QueryMode.SEMANTIC_DISCOVERY}
    ):
        return _outcome(
            ExecutionState.UNAVAILABLE,
            unavailable_envelope(
                requested_mode=requested_mode,
                scope=scope,
                reason="projection_reference_supports_captured_text_bodies_only",
            ),
            0,
        )

    if (
        set(task.selected_bindings).issubset({"feeds", "mailbox"})
        and task.intended_match_surface != "captured_text"
    ):
        return _outcome(
            ExecutionState.UNAVAILABLE,
            unavailable_envelope(
                requested_mode=requested_mode,
                scope=scope,
                reason="non_body_feed_or_mailbox_excluded_from_text_projection",
            ),
            0,
        )
    q_text = str(plan.get("query", ""))
    limit = int(plan.get("limit", 10))
    req = CapturedTextQueryRequest(
        query=q_text,
        selected_binding_ids=selected_b_ids,
        source_path_prefix=task.source_path_prefix,
        limit=limit,
        fallback=(FallbackDisclosure(
            caller_selected=True, from_mode=requested_mode, to_mode=QueryMode.LITERAL_CAPTURED_TEXT,
            reason_code="projection_reference_literal_body_scan",
        ) if requested_mode != QueryMode.LITERAL_CAPTURED_TEXT else None),
    )

    t0 = time.perf_counter_ns()
    try:
        env = query_captured_text(
            projection,
            req,
            current_accepted_reference=current_accepted,
        )
    except CorrespondenceRefusal as exc:
        elapsed = time.perf_counter_ns() - t0
        return _outcome(
            ExecutionState.FAILED,
            unavailable_envelope(
                requested_mode=requested_mode,
                scope=scope,
                reason=exc.code.value,
            ),
            elapsed,
        )
    elapsed = time.perf_counter_ns() - t0
    if env.capability_state == CapabilityState.REFUSED:
        exec_state = ExecutionState.REFUSED
    elif env.capability_state in {CapabilityState.UNAVAILABLE, CapabilityState.STALE}:
        exec_state = ExecutionState.UNAVAILABLE
    else:
        exec_state = ExecutionState.COMPLETED

    return _outcome(exec_state, env, elapsed)


__all__ = ["execute_projection_reference_task"]
