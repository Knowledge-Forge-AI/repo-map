"""File-level retrieval grading and arm applicability for W5 (ADR 0137)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from common_lore_index.retrieval.query_contracts import EvaluationLocator
from retrieval_evaluation_grading import (
    ArmSummary,
    ExecutionState,
    GradedSlotRecord,
    GradingState,
    aggregate_arm_summary,
    compute_ranking_metrics,
)
from retrieval_evaluation_schema import EvaluationTask
from retrieval_semantic_arm_validation import _pins_match
from retrieval_semantic_file_projection import (
    DEFAULT_CUTOFFS,
    CollapsedFileGoldTarget,
    _verify_span_locators,
    assert_calibration_split_only,
    collapse_gold_targets_to_files,
    compute_file_level_ranking_metrics,
    verify_and_project_returned_files,
)
from retrieval_semantic_fusion import FileFusionResult
from retrieval_semantic_representation import (
    CANONICAL_NODE_REPRESENTATION_VERSION,
    VerifiedPublicationPin,
    _require,
    _validate_representation_string,
)

METADATA_ONLY_VECTOR_ARMS: frozenset[str] = frozenset(
    {"vector_only", "canonical_node_v1_vector", "semantic_vector_only"}
)
HYBRID_RRF_ARMS: frozenset[str] = frozenset(
    {"hybrid_rrf", "lexical_plus_vector_rrf", "fts5_plus_vector_rrf", "trgm_plus_vector_rrf"}
)
LEXICAL_BASELINE_ARMS: frozenset[str] = frozenset(
    {"lexical_only", "fts5_bm25", "pg_trgm_lexical", "postgres_lexical", "sqlite_fts5"}
)


@dataclass(frozen=True)
class ArmApplicabilityDecision:
    """Predeclared applicability of an evaluation arm to a frozen task."""

    arm_id: str
    task_id: str
    applicable: bool
    reason_code: str
    default_execution_state: str
    default_grading_state: str
    default_capability_state: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "arm_id": self.arm_id,
            "task_id": self.task_id,
            "applicable": self.applicable,
            "reason_code": self.reason_code,
            "default_execution_state": self.default_execution_state,
            "default_grading_state": self.default_grading_state,
            "default_capability_state": self.default_capability_state,
        }


def evaluate_arm_task_applicability(
    arm_id: str,
    task: EvaluationTask | Any,
    *,
    representation_version: str = CANONICAL_NODE_REPRESENTATION_VERSION,
) -> ArmApplicabilityDecision:
    """Determine predeclared arm applicability from task stratum, match surface, and grading rule."""
    assert_calibration_split_only(task)
    norm_arm = _validate_representation_string(arm_id, "arm_id")
    task_id = _validate_representation_string(getattr(task, "task_id", ""), "task_id")
    stratum = str(getattr(task, "comparability_stratum", ""))
    surface = str(getattr(task, "intended_match_surface", ""))
    rule = str(getattr(task, "grading_rule", ""))
    exposure_map = getattr(task, "comparator_exposure", {}) or {}
    explicit_exposure = exposure_map.get(norm_arm) if isinstance(exposure_map, Mapping) else None

    if explicit_exposure in {"unsupported", "unavailable", "not_applicable"}:
        return ArmApplicabilityDecision(
            norm_arm, task_id, False, "comparator_exposure_unsupported",
            str(ExecutionState.UNAVAILABLE.value), str(GradingState.UNGRADED.value), "unsupported_mode",
        )
    if rule == "direct_handoff" or stratum in {"direct_handoff", "graph_topology"}:
        return ArmApplicabilityDecision(
            norm_arm, task_id, False, f"stratum_{stratum}_not_applicable_for_ranked_retrieval",
            str(ExecutionState.UNAVAILABLE.value), str(GradingState.UNGRADED.value), "unsupported_mode",
        )
    is_meta_vector = norm_arm in METADATA_ONLY_VECTOR_ARMS or (
        representation_version == CANONICAL_NODE_REPRESENTATION_VERSION
        and "vector" in norm_arm and "rrf" not in norm_arm and "hybrid" not in norm_arm
    )
    if is_meta_vector and (stratum == "body" or surface == "captured_text"):
        return ArmApplicabilityDecision(
            norm_arm, task_id, False, "metadata_only_vector_body_stratum_unsupported",
            str(ExecutionState.UNAVAILABLE.value), str(GradingState.UNGRADED.value), "unsupported_mode",
        )
    return ArmApplicabilityDecision(
        norm_arm, task_id, True, "applicable",
        str(ExecutionState.COMPLETED.value), str(GradingState.CORRECT.value), "available",
    )


def _derive_slot_execution_state(
    fusion_result: FileFusionResult | None,
    execution_state: ExecutionState | None,
    capability_state: str | None,
    refusal_code: str | None,
    scope_complete: bool | None,
    verified_pin: VerifiedPublicationPin,
) -> tuple[ExecutionState, str, str | None, bool]:
    if fusion_result is not None:
        if fusion_result.provenance is not None:
            mismatch = _pins_match(verified_pin, fusion_result.provenance)
            _require(
                mismatch is None,
                mismatch or "fusion_provenance_mismatch",
                "fusion_result provenance disagrees with verified_pin",
            )
            fusion_result.provenance.revalidate_current()
        d_exec, d_ref = fusion_result.execution_state, fusion_result.refusal_code
        d_inc = bool(
            fusion_result.truncated or fusion_result.partial_coverage
            or fusion_result.incomplete_arms or fusion_result.truncated_arms or fusion_result.fallback_disclosed
        )
        d_scope_ok = (d_exec == ExecutionState.COMPLETED) and not d_inc
        d_cap = (
            "refused" if d_exec == ExecutionState.REFUSED
            else ("unavailable" if d_exec in {ExecutionState.UNAVAILABLE, ExecutionState.NOT_RUN}
                  else ("failed" if d_exec == ExecutionState.FAILED else ("partial" if d_inc else "available")))
        )
        _require(execution_state in (None, d_exec), "grading_state_override_mismatch", "caller execution_state conflicts with fusion_result")
        _require(refusal_code in (None, d_ref), "grading_state_override_mismatch", "caller refusal_code conflicts with fusion_result")
        _require(capability_state in (None, d_cap), "grading_state_override_mismatch", "caller capability_state conflicts with fusion_result")
        _require(scope_complete in (None, d_scope_ok), "grading_state_override_mismatch", "caller scope_complete conflicts with fusion_result")
        return d_exec, d_cap, d_ref, d_scope_ok
    eff_exec = execution_state if execution_state is not None else ExecutionState.COMPLETED
    eff_scope_ok = (eff_exec == ExecutionState.COMPLETED) and (
        True if scope_complete is None else bool(scope_complete)
    )
    d_cap = (
        "refused" if eff_exec == ExecutionState.REFUSED
        else ("unavailable" if eff_exec in {ExecutionState.UNAVAILABLE, ExecutionState.NOT_RUN}
              else ("failed" if eff_exec == ExecutionState.FAILED else ("available" if eff_scope_ok else "partial")))
    )
    if capability_state is not None:
        _require(
            not (not eff_scope_ok and capability_state == "available")
            and not (eff_exec != ExecutionState.COMPLETED and capability_state in {"available", "partial"})
            and not (eff_exec == ExecutionState.COMPLETED and capability_state in {"refused", "failed", "unavailable"}),
            "grading_state_override_mismatch",
            "caller capability_state conflicts with execution_state or scope_complete",
        )
        d_cap = capability_state
    return eff_exec, d_cap, refusal_code, eff_scope_ok


def grade_w5_task_slot(
    task: EvaluationTask | Any,
    *,
    arm_id: str,
    verified_pin: VerifiedPublicationPin,
    returned_files: Sequence[Any] = (),
    fusion_result: FileFusionResult | None = None,
    execution_state: ExecutionState | None = None,
    capability_state: str | None = None,
    refusal_code: str | None = None,
    scope_complete: bool | None = None,
    span_locators: Sequence[EvaluationLocator | Any] | None = None,
    cutoffs: Sequence[int] = DEFAULT_CUTOFFS,
    private_markers: Sequence[str] = (),
    grading_granularity: str = "file",
) -> GradedSlotRecord:
    """Grade one calibration task slot with predeclared applicability and dual span/file metrics."""
    _require(isinstance(verified_pin, VerifiedPublicationPin), "unverified_publication_pin", "VerifiedPublicationPin required")
    verified_pin.revalidate_current()
    assert_calibration_split_only(task)
    _require(getattr(task, "graph_id", None) == verified_pin.graph_id, "graph_id_mismatch", "task graph_id mismatch")
    _require(getattr(task, "generation", None) == verified_pin.generation, "generation_mismatch", "task generation mismatch")
    _require(grading_granularity in {"file", "span"}, "invalid_grading_granularity", f"unsupported granularity {grading_granularity!r}")
    _require(not (fusion_result is not None and bool(returned_files)), "conflicting_grading_inputs", "pass either returned_files or fusion_result")
    applicability = evaluate_arm_task_applicability(arm_id, task)
    items: Sequence[Any] = fusion_result.hits if fusion_result is not None else returned_files
    zero_all = {
        m: 0.0
        for k in cutoffs
        for m in (f"file_recall@{k}", f"file_mrr@{k}", f"file_ndcg@{k}")
    }
    if span_locators is not None:
        zero_all.update(
            {
                m: 0.0
                for k in cutoffs
                for m in (f"recall@{k}", f"mrr@{k}", f"ndcg@{k}")
            }
        )
    _require(
        grading_granularity != "span" or span_locators is not None,
        "span_locators_required",
        "span grading requires explicit span_locators",
    )
    measured_span_locators = () if span_locators is None else span_locators
    if not applicability.applicable:
        return GradedSlotRecord(
            task_id=task.task_id, family=task.family, comparability_stratum=task.comparability_stratum,
            grading_rule=task.grading_rule, execution_state=ExecutionState.UNAVAILABLE,
            grading_state=GradingState.UNGRADED, capability_state=applicability.default_capability_state,
            safety_refusal_correct=None, absent_answer_correct=None, metrics=zero_all, returned_hit_count=len(items),
        )
    eff_exec, eff_cap, eff_refusal, eff_scope_ok = _derive_slot_execution_state(
        fusion_result, execution_state, capability_state, refusal_code, scope_complete, verified_pin
    )
    if eff_exec == ExecutionState.UNAVAILABLE:
        return GradedSlotRecord(
            task_id=task.task_id, family=task.family, comparability_stratum=task.comparability_stratum,
            grading_rule=task.grading_rule, execution_state=ExecutionState.UNAVAILABLE,
            grading_state=GradingState.UNGRADED, capability_state=eff_cap,
            safety_refusal_correct=None, absent_answer_correct=None, metrics=zero_all, returned_hit_count=len(items),
        )
    if task.grading_rule == "safety_refusal":
        refused_ok = (
            eff_exec == ExecutionState.REFUSED and len(items) == 0 and eff_cap == "refused"
            and bool(eff_refusal) and (task.expected_refusal_code is None or eff_refusal == task.expected_refusal_code)
        )
        return GradedSlotRecord(
            task_id=task.task_id, family=task.family, comparability_stratum=task.comparability_stratum,
            grading_rule=task.grading_rule, execution_state=eff_exec, grading_state=GradingState.NOT_APPLICABLE,
            capability_state=eff_cap, safety_refusal_correct=refused_ok, absent_answer_correct=None,
            metrics=zero_all, returned_hit_count=len(items),
        )
    if eff_exec in {ExecutionState.FAILED, ExecutionState.NOT_RUN, ExecutionState.REFUSED}:
        return GradedSlotRecord(
            task_id=task.task_id, family=task.family, comparability_stratum=task.comparability_stratum,
            grading_rule=task.grading_rule, execution_state=eff_exec, grading_state=GradingState.UNGRADED,
            capability_state=eff_cap, safety_refusal_correct=None, absent_answer_correct=None,
            metrics=zero_all, returned_hit_count=len(items),
        )
    projected = verify_and_project_returned_files(
        items, verified_pin=verified_pin, task=task, private_markers=private_markers
    )
    _verify_span_locators(
        measured_span_locators,
        verified_pin=verified_pin,
        task=task,
        private_markers=private_markers,
    )
    is_complete_coverage = eff_exec == ExecutionState.COMPLETED and eff_scope_ok and eff_cap == "available"
    if task.grading_rule == "absent_answer":
        abstained_ok = len(projected) == 0 and is_complete_coverage
        return GradedSlotRecord(
            task_id=task.task_id, family=task.family, comparability_stratum=task.comparability_stratum,
            grading_rule=task.grading_rule, execution_state=eff_exec,
            grading_state=GradingState.CORRECT if abstained_ok else GradingState.INCORRECT,
            capability_state=eff_cap, safety_refusal_correct=None, absent_answer_correct=abstained_ok,
            metrics=zero_all, returned_hit_count=len(projected),
        )
    span_metrics: dict[str, float] = (
        compute_ranking_metrics(
            measured_span_locators, task.gold_targets, cutoffs=cutoffs
        )
        if span_locators is not None
        else {}
    )
    file_metrics = compute_file_level_ranking_metrics(
        items, task.gold_targets, verified_pin=verified_pin, task=task, cutoffs=cutoffs, private_markers=private_markers
    )
    rec5 = span_metrics["recall@5"] if grading_granularity == "span" else file_metrics["file_recall@5"]
    g_state = (
        GradingState.INCORRECT if rec5 <= 0.0
        else (GradingState.CORRECT if rec5 >= 0.999999 and is_complete_coverage else GradingState.PARTIAL)
    )
    return GradedSlotRecord(
        task_id=task.task_id, family=task.family, comparability_stratum=task.comparability_stratum,
        grading_rule=task.grading_rule, execution_state=eff_exec, grading_state=g_state,
        capability_state=eff_cap, safety_refusal_correct=None, absent_answer_correct=None,
        metrics={**span_metrics, **file_metrics}, returned_hit_count=len(projected),
    )


__all__ = [
    "DEFAULT_CUTOFFS", "HYBRID_RRF_ARMS", "LEXICAL_BASELINE_ARMS", "METADATA_ONLY_VECTOR_ARMS",
    "ArmApplicabilityDecision", "ArmSummary", "CollapsedFileGoldTarget", "aggregate_arm_summary",
    "assert_calibration_split_only", "collapse_gold_targets_to_files",
    "compute_file_level_ranking_metrics", "evaluate_arm_task_applicability",
    "grade_w5_task_slot", "verify_and_project_returned_files",
]
