"""Unit tests for deterministic grading, duplicate-quotation deduplication, and cost accounting (S3)."""

from __future__ import annotations

from typing import Any, cast

import pytest

from common_lore_index.retrieval.query_contracts import (
    CapabilityState,
    DEFAULT_ORDERING_POLICY_VERSION,
    EvaluationLocator,
    MatchSurface,
    QUERY_CONTRACT_VERSION,
    QueryEnvelope,
    QueryHit,
    QueryMode,
    QueryScope,
    refused_envelope,
    unavailable_envelope,
)
from retrieval_evaluation_accounting import (
    compute_external_agent_cost,
    summarize_timing_samples,
)
from retrieval_evaluation_grading import (
    ExecutionState,
    GradingState,
    aggregate_arm_summary,
    compute_ranking_metrics,
    grade_task_execution,
)
from retrieval_evaluation_schema import EvaluationTask, GoldTarget


def _sample_task(
    task_id: str = "cal-01",
    *,
    grading_rule: str = "ranked_positive",
    expected_capability_state: str = "available",
    expected_refusal_code: str | None = None,
) -> EvaluationTask:
    gold_targets = (
        (
            GoldTarget(
                locator=EvaluationLocator("bind1:core", "pkg/pipeline.py", 10, 20),
                relevance_grade=3,
                rationale="primary symbol",
            ),
            GoldTarget(
                locator=EvaluationLocator(
                    "bind1:companion", "docs/architecture.md", 1, 15
                ),
                relevance_grade=2,
                rationale="supporting doc",
            ),
        )
        if grading_rule == "ranked_positive"
        else ()
    )
    return EvaluationTask(
        task_id=task_id,
        family="exact_symbol_and_partial_name",
        split="calibration",
        question="Find pipeline stage runner",
        permitted_query_plan={"query": "run_pipeline_stage", "limit": 10},
        graph_id="mixed-v1",
        generation=1,
        selected_bindings=("core", "companion"),
        source_path_prefix=None,
        requested_mode="literal_captured_text",
        intended_match_surface="captured_text",
        comparability_stratum="body",
        comparator_exposure={
            "native": "authorized_bodies",
            "graph": "metadata",
            "reference": "projected_bodies",
        },
        gold_targets=gold_targets,
        expected_capability_state=expected_capability_state,
        expected_refusal_code=expected_refusal_code,
        grading_rule=grading_rule,
    ).validate()


def test_duplicate_quotations_cannot_create_duplicate_ndcg_or_recall_gain() -> None:
    """Repeated hits on the same gold target count at most once at their earliest rank."""
    gold = (
        GoldTarget(
            EvaluationLocator("bind1:core", "pkg/pipeline.py", 10, 20), 3, "primary"
        ),
        GoldTarget(
            EvaluationLocator("bind1:companion", "docs/architecture.md", 1, 15),
            2,
            "secondary",
        ),
    )
    loc1_a = EvaluationLocator("bind1:core", "pkg/pipeline.py", 12, 12)
    loc1_b = EvaluationLocator("bind1:core", "pkg/pipeline.py", 15, 16)
    loc1_c = EvaluationLocator("bind1:core", "pkg/pipeline.py", 18, 19)

    single_hit_metrics = compute_ranking_metrics((loc1_a,), gold, cutoffs=(1, 3, 5))
    repeated_hit_metrics = compute_ranking_metrics(
        (loc1_a, loc1_b, loc1_c), gold, cutoffs=(1, 3, 5)
    )

    assert repeated_hit_metrics["recall@3"] == single_hit_metrics["recall@3"] == 0.5
    assert repeated_hit_metrics["mrr@3"] == single_hit_metrics["mrr@3"] == 1.0
    assert repeated_hit_metrics["ndcg@3"] == single_hit_metrics["ndcg@3"]
    assert repeated_hit_metrics["ndcg@3"] < 1.0


def test_safety_refusal_and_unavailable_states_never_counted_as_retrieval_correct() -> (
    None
):
    """Safety refusals are graded separately; unavailable/failed/ungraded slots are never correct."""
    scope = QueryScope(graph_id="mixed-v1", backend="postgresql")
    pos_task = _sample_task("cal-01", grading_rule="ranked_positive")
    unavail_env = unavailable_envelope(
        requested_mode=QueryMode.RANKED_DISCOVERY,
        scope=scope,
        reason="backend_unsupported",
    )
    unavail_slot = grade_task_execution(
        pos_task,
        execution_state=ExecutionState.UNAVAILABLE,
        envelope=unavail_env,
    )
    assert unavail_slot.grading_state == GradingState.UNGRADED
    assert unavail_slot.safety_refusal_correct is None
    assert unavail_slot.metrics["recall@5"] == 0.0

    refusal_task = _sample_task(
        "cal-02",
        grading_rule="safety_refusal",
        expected_capability_state="refused",
        expected_refusal_code="binding_privacy_not_authorized",
    )
    ref_env = refused_envelope(
        requested_mode=QueryMode.LITERAL_CAPTURED_TEXT,
        scope=scope,
        refusal_code="binding_privacy_not_authorized",
    )
    ref_slot = grade_task_execution(
        refusal_task,
        execution_state=ExecutionState.REFUSED,
        envelope=ref_env,
    )
    assert ref_slot.safety_refusal_correct is True
    assert ref_slot.grading_state == GradingState.NOT_APPLICABLE

    # A completed 0-hit execution on a safety_refusal task is NOT a valid safety refusal
    empty_avail_env = QueryEnvelope(
        contract_version=QUERY_CONTRACT_VERSION,
        requested_mode=QueryMode.LITERAL_CAPTURED_TEXT,
        effective_mode=QueryMode.LITERAL_CAPTURED_TEXT,
        match_surface=MatchSurface.CAPTURED_TEXT,
        scope=scope,
        ordering_policy_version=DEFAULT_ORDERING_POLICY_VERSION,
        capability_state=CapabilityState.AVAILABLE,
        hits=(),
        scope_complete=True,
    ).validate()
    false_ref_slot = grade_task_execution(
        refusal_task,
        execution_state=ExecutionState.COMPLETED,
        envelope=empty_avail_env,
    )
    assert false_ref_slot.safety_refusal_correct is False
    assert false_ref_slot.grading_state == GradingState.NOT_APPLICABLE


def test_fixed_split_denominators_and_missing_or_duplicate_slot_refusal() -> None:
    """Aggregation preserves fixed split denominators and refuses missing or duplicate task records."""
    scope = QueryScope(graph_id="mixed-v1", backend="sqlite")
    t1 = _sample_task("cal-01")
    t2 = _sample_task("cal-02")
    hit = QueryHit(
        locator=EvaluationLocator("bind1:core", "pkg/pipeline.py", 10, 20),
        match_surface=MatchSurface.CAPTURED_TEXT,
        rank=1,
        score=1.0,
    )
    env1 = QueryEnvelope(
        contract_version=QUERY_CONTRACT_VERSION,
        requested_mode=QueryMode.LITERAL_CAPTURED_TEXT,
        effective_mode=QueryMode.LITERAL_CAPTURED_TEXT,
        match_surface=MatchSurface.CAPTURED_TEXT,
        scope=scope,
        ordering_policy_version=DEFAULT_ORDERING_POLICY_VERSION,
        capability_state=CapabilityState.AVAILABLE,
        hits=(hit,),
        scope_complete=True,
    ).validate()
    unavail_env = unavailable_envelope(
        requested_mode=QueryMode.RANKED_DISCOVERY,
        scope=scope,
        reason="backend_unsupported",
    )
    r1 = grade_task_execution(
        t1, execution_state=ExecutionState.COMPLETED, envelope=env1
    )
    r2 = grade_task_execution(
        t2, execution_state=ExecutionState.UNAVAILABLE, envelope=unavail_env
    )

    summary = aggregate_arm_summary(
        "current_graph_baseline:sqlite",
        "sqlite",
        (r1, r2),
        expected_task_ids=("cal-01", "cal-02"),
    )
    assert summary.whole_split_denominator == 2
    assert summary.supported_denominator == 1
    assert summary.graded_denominator == 1
    assert summary.unavailable_count == 1
    assert summary.strata["body"]["graded_count"] == 1
    assert summary.strata["body"]["mean_recall_at_5"] == 0.5
    assert summary.strata["graph_topology"]["graded_count"] == 0
    assert summary.strata["graph_topology"]["mean_recall_at_5"] is None
    assert summary.strata["graph_topology"]["mean_mrr_at_5"] is None
    assert summary.strata["graph_topology"]["mean_ndcg_at_5"] is None

    with pytest.raises(ValueError, match="missing or mismatched"):
        aggregate_arm_summary(
            "current_graph_baseline:sqlite",
            "sqlite",
            (r1,),
            expected_task_ids=("cal-01", "cal-02"),
        )
    with pytest.raises(ValueError, match="duplicate"):
        aggregate_arm_summary(
            "current_graph_baseline:sqlite",
            "sqlite",
            (r1, r1),
            expected_task_ids=("cal-01", "cal-02"),
        )


def test_timing_and_external_agent_cost_accounting_rules() -> None:
    """3-sample timing leaves p95 None; external cost includes failed spend and handles zero success."""
    timing = summarize_timing_samples((120_000, 100_000, 140_000))
    assert timing.sample_count == 3
    assert timing.median_ns == 120_000
    assert timing.p95_ns is None

    zero_succ = compute_external_agent_cost(
        (
            {
                "task_id": "cal-01",
                "succeeded": False,
                "tokens_spent": 500,
                "cost_usd": 0.015,
            },
            {
                "task_id": "cal-02",
                "succeeded": False,
                "tokens_spent": 700,
                "cost_usd": 0.021,
            },
        )
    )
    assert zero_succ.total_tokens_spent == 1200
    assert zero_succ.failed_attempt_tokens_spent == 1200
    assert zero_succ.successful_task_count == 0
    assert zero_succ.zero_success is True
    assert zero_succ.tokens_per_successful_task is None
    assert zero_succ.cost_per_successful_task_usd is None

    with pytest.raises(ValueError, match="unknown spend"):
        compute_external_agent_cost(
            (
                {
                    "task_id": "cal-01",
                    "succeeded": True,
                    "tokens_spent": None,
                    "cost_usd": 0.01,
                },
            )
        )
    for bad_cost in (float("nan"), float("inf"), -0.01, True):
        with pytest.raises(ValueError, match="unknown spend"):
            compute_external_agent_cost(
                (
                    {
                        "task_id": "cal-01",
                        "succeeded": True,
                        "tokens_spent": 10,
                        "cost_usd": bad_cost,
                    },
                )
            )
    for bad_sample in ((True, 100), (-5, 100), (1.5, 100)):
        with pytest.raises(ValueError):
            summarize_timing_samples(cast(Any, bad_sample))

    # Duplicate successful attempts for the same task_id count as 1 distinct successful task
    dedup_succ = compute_external_agent_cost(
        (
            {
                "task_id": "cal-01",
                "succeeded": True,
                "tokens_spent": 100,
                "cost_usd": 0.01,
            },
            {
                "task_id": "cal-01",
                "succeeded": True,
                "tokens_spent": 150,
                "cost_usd": 0.015,
            },
        )
    )
    assert dedup_succ.total_attempts == 2
    assert dedup_succ.successful_task_count == 1
    assert dedup_succ.tokens_per_successful_task == 250.0

    # Mixing anonymous attempts with identified tasks cannot establish a distinct-task denominator.
    with pytest.raises(ValueError, match="task_id coverage must be uniform"):
        compute_external_agent_cost((
            {"task_id": "cal-01", "succeeded": True, "tokens_spent": 100, "cost_usd": 0.01},
            {"succeeded": True, "tokens_spent": 200, "cost_usd": 0.02},
        ))
    anonymous = compute_external_agent_cost((
        {"succeeded": True, "tokens_spent": 200, "cost_usd": 0.02},
    ))
    assert anonymous.success_denominator_kind == "successful_attempts_without_task_identity"
    assert dedup_succ.success_denominator_kind == "distinct_task_ids"
