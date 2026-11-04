"""Compact fusion evidence and the query-to-fusion outcome boundary."""

from __future__ import annotations

import re

from retrieval_semantic_experiment_contracts import ExperimentRefusal
from retrieval_semantic_fusion import FileFusionResult


_REASON = re.compile(r"[a-z][a-z0-9_.-]{0,127}\Z")


def safe_operation_reason(value: object) -> str | None:
    if value is None:
        return None
    return value if type(value) is str and _REASON.fullmatch(value) else "operation_failed"


def query_and_fusion_outcome(
    query_state: str, query_reason: str | None, fused: FileFusionResult | None,
) -> tuple[str, str | None]:
    if fused is None:
        return query_state, query_reason
    if query_state != "completed":
        raise ExperimentRefusal("observed_operation_fusion_without_completed_query")
    return (
        fused.execution_state.value,
        fused.refusal_code or fused.unavailable_reason or fused.failure_reason,
    )


def fusion_work(fused: FileFusionResult) -> dict[str, object]:
    """Retain bounded work, preserving the accepted receipt's identity kind."""
    payload = fused.to_dict()
    return {
        key: payload[key] for key in (
            "policy_version", "representation_version", "rrf_k", "per_arm_raw_hit_counts",
            "per_arm_collapsed_file_counts", "pre_cap_fused_file_count",
            "work_candidates_inspected", "truncated", "partial_coverage",
            "fallback_disclosed", "fallback_from_arms", "incomplete_arms", "truncated_arms",
        )
    } | {
        "fusion_state": fused.execution_state.value,
        "fusion_reason": safe_operation_reason(
            fused.refusal_code or fused.unavailable_reason or fused.failure_reason,
        ),
        "provenance_identity": (
            fused.provenance.receipt_identity if fused.provenance is not None else None
        ),
    }


__all__ = ["fusion_work", "query_and_fusion_outcome", "safe_operation_reason"]
