"""Deterministic retrieval task grading, quotation deduplication, and arm aggregation (S3)."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from common_lore_index.retrieval.query_contracts import (
    CapabilityState,
    EvaluationLocator,
    QueryEnvelope,
)
from retrieval_evaluation_accounting import (
    ByteLayerAccounting,
    TimingSummary,
)
from retrieval_evaluation_schema import (
    VALID_STRATA,
    EvaluationTask,
    GoldTarget,
)


class ExecutionState(StrEnum):
    """Five-value execution state separate from retrieval grading."""

    COMPLETED = "completed"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"
    REFUSED = "refused"
    NOT_RUN = "not_run"


class GradingState(StrEnum):
    """Five-value grading state; unavailable/ungraded/refused are never retrieval correct."""

    CORRECT = "correct"
    PARTIAL = "partial"
    INCORRECT = "incorrect"
    UNGRADED = "ungraded"
    NOT_APPLICABLE = "not_applicable"


def _locator_matches_gold(hit_loc: EvaluationLocator, gold_loc: EvaluationLocator) -> bool:
    if hit_loc.binding_id != gold_loc.binding_id:
        return False
    if hit_loc.source_relative_path != gold_loc.source_relative_path:
        return False
    if gold_loc.start_line is None or hit_loc.start_line is None:
        return True
    g_start = gold_loc.start_line
    g_end = gold_loc.end_line if gold_loc.end_line is not None else g_start
    h_start = hit_loc.start_line
    h_end = hit_loc.end_line if hit_loc.end_line is not None else h_start
    return not (h_end < g_start or h_start > g_end)


def compute_ranking_metrics(
    returned_locators: Sequence[EvaluationLocator],
    gold_targets: Sequence[GoldTarget],
    *,
    cutoffs: Sequence[int] = (1, 3, 5, 10),
) -> dict[str, float]:
    """Compute Recall@k, MRR@k, and nDCG@k with strict per-gold-target deduplication."""
    positive_gold = [g for g in gold_targets if g.relevance_grade > 0]
    metrics: dict[str, float] = {}
    if not positive_gold:
        for k in cutoffs:
            metrics[f"recall@{k}"] = 0.0
            metrics[f"mrr@{k}"] = 0.0
            metrics[f"ndcg@{k}"] = 0.0
        return metrics

    credited_gold_indices: set[int] = set()
    rank_gains: list[tuple[int, int]] = []  # (1-based rank, relevance_grade)

    for rank_idx, hit_loc in enumerate(returned_locators, start=1):
        best_gold_idx: int | None = None
        best_grade = 0
        for g_idx, gold in enumerate(positive_gold):
            if g_idx in credited_gold_indices:
                continue
            if _locator_matches_gold(hit_loc, gold.locator):
                if gold.relevance_grade > best_grade:
                    best_grade = gold.relevance_grade
                    best_gold_idx = g_idx
        if best_gold_idx is not None and best_grade > 0:
            credited_gold_indices.add(best_gold_idx)
            rank_gains.append((rank_idx, best_grade))

    ideal_grades = sorted((g.relevance_grade for g in positive_gold), reverse=True)
    total_positive = len(positive_gold)

    for k in cutoffs:
        hits_at_k = [(r, rel) for r, rel in rank_gains if r <= k]
        recall_k = len(hits_at_k) / total_positive
        mrr_k = 1.0 / hits_at_k[0][0] if hits_at_k else 0.0
        dcg_k = sum(((2**rel) - 1.0) / math.log2(r + 1.0) for r, rel in hits_at_k)
        idcg_k = sum(
            ((2**rel) - 1.0) / math.log2(idx + 2.0)
            for idx, rel in enumerate(ideal_grades[:k])
        )
        ndcg_k = (dcg_k / idcg_k) if idcg_k > 0.0 else 0.0
        metrics[f"recall@{k}"] = round(recall_k, 6)
        metrics[f"mrr@{k}"] = round(mrr_k, 6)
        metrics[f"ndcg@{k}"] = round(ndcg_k, 6)

    return metrics


@dataclass(frozen=True)
class GradedSlotRecord:
    """One preserved evaluation slot record for an (arm, backend, task) triple."""

    task_id: str
    family: str
    comparability_stratum: str
    grading_rule: str
    execution_state: ExecutionState
    grading_state: GradingState
    capability_state: str
    safety_refusal_correct: bool | None
    absent_answer_correct: bool | None
    metrics: Mapping[str, float]
    returned_hit_count: int
    timing: TimingSummary | None = None
    byte_accounting: ByteLayerAccounting | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "family": self.family,
            "comparability_stratum": self.comparability_stratum,
            "grading_rule": self.grading_rule,
            "execution_state": self.execution_state.value,
            "grading_state": self.grading_state.value,
            "capability_state": self.capability_state,
            "safety_refusal_correct": self.safety_refusal_correct,
            "absent_answer_correct": self.absent_answer_correct,
            "metrics": dict(self.metrics),
            "returned_hit_count": self.returned_hit_count,
            "timing": self.timing.to_dict() if self.timing is not None else None,
            "byte_accounting": (
                self.byte_accounting.to_dict()
                if self.byte_accounting is not None
                else None
            ),
        }


def grade_task_execution(
    task: EvaluationTask,
    *,
    execution_state: ExecutionState,
    envelope: QueryEnvelope,
    timing: TimingSummary | None = None,
    byte_accounting: ByteLayerAccounting | None = None,
) -> GradedSlotRecord:
    """Grade one task execution separating execution, retrieval, and safety refusal."""
    zero_metrics = compute_ranking_metrics((), task.gold_targets)
    hit_locators = tuple(h.locator for h in envelope.hits)

    if task.grading_rule == "safety_refusal":
        refused_cleanly = (
            execution_state == ExecutionState.REFUSED
            and len(hit_locators) == 0
            and envelope.capability_state == CapabilityState.REFUSED
            and bool(envelope.refusal_code)
            and (
                task.expected_refusal_code is None
                or envelope.refusal_code == task.expected_refusal_code
            )
        )
        return GradedSlotRecord(
            task_id=task.task_id,
            family=task.family,
            comparability_stratum=task.comparability_stratum,
            grading_rule=task.grading_rule,
            execution_state=execution_state,
            grading_state=GradingState.NOT_APPLICABLE,
            capability_state=envelope.capability_state.value,
            safety_refusal_correct=refused_cleanly,
            absent_answer_correct=None,
            metrics=zero_metrics,
            returned_hit_count=len(hit_locators),
            timing=timing,
            byte_accounting=byte_accounting,
        )

    if execution_state in {
        ExecutionState.UNAVAILABLE,
        ExecutionState.FAILED,
        ExecutionState.NOT_RUN,
        ExecutionState.REFUSED,
    }:
        return GradedSlotRecord(
            task_id=task.task_id,
            family=task.family,
            comparability_stratum=task.comparability_stratum,
            grading_rule=task.grading_rule,
            execution_state=execution_state,
            grading_state=GradingState.UNGRADED,
            capability_state=envelope.capability_state.value,
            safety_refusal_correct=None,
            absent_answer_correct=None,
            metrics=zero_metrics,
            returned_hit_count=len(hit_locators),
            timing=timing,
            byte_accounting=byte_accounting,
        )

    if task.grading_rule == "absent_answer":
        abstained_ok = (
            len(hit_locators) == 0
            and envelope.capability_state == CapabilityState.AVAILABLE
            and envelope.scope_complete
        )
        return GradedSlotRecord(
            task_id=task.task_id,
            family=task.family,
            comparability_stratum=task.comparability_stratum,
            grading_rule=task.grading_rule,
            execution_state=execution_state,
            grading_state=(
                GradingState.CORRECT if abstained_ok else GradingState.INCORRECT
            ),
            capability_state=envelope.capability_state.value,
            safety_refusal_correct=None,
            absent_answer_correct=abstained_ok,
            metrics=zero_metrics,
            returned_hit_count=len(hit_locators),
            timing=timing,
            byte_accounting=byte_accounting,
        )

    metrics = compute_ranking_metrics(hit_locators, task.gold_targets)
    rec5 = metrics["recall@5"]
    if rec5 >= 0.999999:
        g_state = GradingState.CORRECT
    elif rec5 > 0.0:
        g_state = GradingState.PARTIAL
    else:
        g_state = GradingState.INCORRECT

    return GradedSlotRecord(
        task_id=task.task_id,
        family=task.family,
        comparability_stratum=task.comparability_stratum,
        grading_rule=task.grading_rule,
        execution_state=execution_state,
        grading_state=g_state,
        capability_state=envelope.capability_state.value,
        safety_refusal_correct=None,
        absent_answer_correct=None,
        metrics=metrics,
        returned_hit_count=len(hit_locators),
        timing=timing,
        byte_accounting=byte_accounting,
    )


@dataclass(frozen=True)
class ArmSummary:
    """Fixed-denominator arm summary preserving unavailable/ungraded counts and strata."""

    arm_id: str
    backend: str
    whole_split_denominator: int
    supported_denominator: int
    graded_denominator: int
    unavailable_count: int
    refused_count: int
    failed_count: int
    safety_refusal_correct_count: int
    safety_refusal_total: int
    absent_answer_correct_count: int
    absent_answer_total: int
    strata: Mapping[str, Mapping[str, Any]]
    slots: tuple[GradedSlotRecord, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "arm_id": self.arm_id,
            "backend": self.backend,
            "whole_split_denominator": self.whole_split_denominator,
            "supported_denominator": self.supported_denominator,
            "graded_denominator": self.graded_denominator,
            "unavailable_count": self.unavailable_count,
            "refused_count": self.refused_count,
            "failed_count": self.failed_count,
            "safety_refusal_correct_count": self.safety_refusal_correct_count,
            "safety_refusal_total": self.safety_refusal_total,
            "absent_answer_correct_count": self.absent_answer_correct_count,
            "absent_answer_total": self.absent_answer_total,
            "strata": {k: dict(v) for k, v in self.strata.items()},
            "slots": [s.to_dict() for s in self.slots],
        }


def aggregate_arm_summary(
    arm_id: str,
    backend: str,
    slots: Sequence[GradedSlotRecord],
    *,
    expected_task_ids: Sequence[str],
) -> ArmSummary:
    """Aggregate one arm's slots with strict denominator and slot-completeness checks."""
    seen: set[str] = set()
    for slot in slots:
        if slot.task_id in seen:
            raise ValueError(f"duplicate slot task_id {slot.task_id!r} in arm {arm_id!r}")
        seen.add(slot.task_id)
    expected_set = set(expected_task_ids)
    if seen != expected_set or len(slots) != len(expected_task_ids):
        raise ValueError(
            f"missing or mismatched task slots in arm {arm_id!r}: "
            f"expected {len(expected_task_ids)}, got {len(slots)}"
        )

    whole_denom = len(expected_task_ids)
    unavail_count = sum(1 for s in slots if s.execution_state == ExecutionState.UNAVAILABLE)
    refused_count = sum(1 for s in slots if s.execution_state == ExecutionState.REFUSED)
    failed_count = sum(1 for s in slots if s.execution_state == ExecutionState.FAILED)
    supported_denom = whole_denom - unavail_count
    graded_slots = [
        s
        for s in slots
        if s.grading_state in {GradingState.CORRECT, GradingState.PARTIAL, GradingState.INCORRECT}
    ]
    safety_slots = [s for s in slots if s.grading_rule == "safety_refusal"]
    safety_ok = sum(1 for s in safety_slots if s.safety_refusal_correct is True)
    absent_slots = [s for s in slots if s.grading_rule == "absent_answer"]
    absent_ok = sum(1 for s in absent_slots if s.absent_answer_correct is True)

    strata_summary: dict[str, dict[str, Any]] = {}
    for stratum in sorted(VALID_STRATA):
        s_all = [s for s in slots if s.comparability_stratum == stratum]
        s_pos = [
            s
            for s in s_all
            if s.grading_rule in {"ranked_positive", "direct_handoff"}
            and s.grading_state in {GradingState.CORRECT, GradingState.PARTIAL, GradingState.INCORRECT}
        ]
        n_pos = len(s_pos)
        strata_summary[stratum] = {
            "slot_count": len(s_all),
            "graded_count": n_pos,
            "mean_recall_at_5": (
                round(sum(s.metrics["recall@5"] for s in s_pos) / n_pos, 6)
                if n_pos > 0
                else None
            ),
            "mean_mrr_at_5": (
                round(sum(s.metrics["mrr@5"] for s in s_pos) / n_pos, 6)
                if n_pos > 0
                else None
            ),
            "mean_ndcg_at_5": (
                round(sum(s.metrics["ndcg@5"] for s in s_pos) / n_pos, 6)
                if n_pos > 0
                else None
            ),
        }

    return ArmSummary(
        arm_id=arm_id,
        backend=backend,
        whole_split_denominator=whole_denom,
        supported_denominator=supported_denom,
        graded_denominator=len(graded_slots),
        unavailable_count=unavail_count,
        refused_count=refused_count,
        failed_count=failed_count,
        safety_refusal_correct_count=safety_ok,
        safety_refusal_total=len(safety_slots),
        absent_answer_correct_count=absent_ok,
        absent_answer_total=len(absent_slots),
        strata=strata_summary,
        slots=tuple(slots),
    )
