"""Unit tests for baseline-derived future criteria proposal and unresolved limitation handling (S3)."""

from __future__ import annotations

import pytest

from retrieval_evaluation_criteria import (
    FutureCriteriaProposal,
    derive_future_criteria_proposal,
)


def _sample_baseline_report() -> dict[str, object]:
    return {
        "schema_version": "cloe-retrieval-baseline-report-v1",
        "attempt_id": "calibration-attempt-1",
        "execution_purpose": "retained_calibration",
        "status": "completed",
        "phase_id": "REPOMAP-CLOE-RETRIEVAL1",
        "split": "calibration",
        "freeze_sha256": "sha256:" + "1" * 64,
        "catalog_sha256": "sha256:" + "2" * 64,
        "policy_digest": "sha256:" + "3" * 64,
        "arms": {
            "native_tools_baseline": {
                "arm_id": "native_tools_baseline",
                "backend": "native_filesystem",
                "whole_split_denominator": 24,
                "supported_denominator": 21,
                "graded_denominator": 18,
                "unavailable_count": 3,
                "refused_count": 2,
                "safety_refusal_correct_count": 2,
                "safety_refusal_total": 2,
                "strata": {
                    "body": {"slot_count": 10, "graded_count": 8, "mean_recall_at_5": 0.78, "mean_mrr_at_5": 0.72, "mean_ndcg_at_5": 0.75},
                    "metadata": {"slot_count": 8, "graded_count": 7, "mean_recall_at_5": 0.64, "mean_mrr_at_5": 0.60, "mean_ndcg_at_5": 0.62},
                    "graph_topology": {"slot_count": 4, "graded_count": 0, "mean_recall_at_5": None, "mean_mrr_at_5": None, "mean_ndcg_at_5": None},
                    "direct_handoff": {"slot_count": 2, "graded_count": 2, "mean_recall_at_5": 1.0, "mean_mrr_at_5": 1.0, "mean_ndcg_at_5": 1.0},
                },
            },
            "current_graph_baseline:sqlite": {
                "arm_id": "current_graph_baseline:sqlite",
                "backend": "sqlite",
                "whole_split_denominator": 24,
                "supported_denominator": 16,
                "graded_denominator": 14,
                "unavailable_count": 8,
                "refused_count": 2,
                "safety_refusal_correct_count": 2,
                "safety_refusal_total": 2,
                "strata": {
                    "body": {"slot_count": 10, "graded_count": 0, "mean_recall_at_5": None, "mean_mrr_at_5": None, "mean_ndcg_at_5": None},
                    "metadata": {"slot_count": 8, "graded_count": 8, "mean_recall_at_5": 0.85, "mean_mrr_at_5": 0.81, "mean_ndcg_at_5": 0.83},
                    "graph_topology": {"slot_count": 4, "graded_count": 4, "mean_recall_at_5": 0.90, "mean_mrr_at_5": 0.88, "mean_ndcg_at_5": 0.89},
                    "direct_handoff": {"slot_count": 2, "graded_count": 2, "mean_recall_at_5": 1.0, "mean_mrr_at_5": 1.0, "mean_ndcg_at_5": 1.0},
                },
            },
            "current_graph_baseline:postgresql": {
                "arm_id": "current_graph_baseline:postgresql",
                "backend": "postgresql",
                "whole_split_denominator": 24,
                "supported_denominator": 11,
                "graded_denominator": 9,
                "unavailable_count": 13,
                "refused_count": 2,
                "safety_refusal_correct_count": 2,
                "safety_refusal_total": 2,
                "strata": {
                    "body": {"slot_count": 10, "graded_count": 0, "mean_recall_at_5": None, "mean_mrr_at_5": None, "mean_ndcg_at_5": None},
                    "metadata": {"slot_count": 8, "graded_count": 5, "mean_recall_at_5": 0.70, "mean_mrr_at_5": 0.65, "mean_ndcg_at_5": 0.67},
                    "graph_topology": {"slot_count": 4, "graded_count": 4, "mean_recall_at_5": 0.90, "mean_mrr_at_5": 0.88, "mean_ndcg_at_5": 0.89},
                    "direct_handoff": {"slot_count": 2, "graded_count": 0, "mean_recall_at_5": None, "mean_mrr_at_5": None, "mean_ndcg_at_5": None},
                },
            },
            "captured_projection_reference:sqlite": {
                "arm_id": "captured_projection_reference:sqlite",
                "backend": "sqlite",
                "whole_split_denominator": 24,
                "supported_denominator": 10,
                "graded_denominator": 8,
                "unavailable_count": 14,
                "refused_count": 2,
                "safety_refusal_correct_count": 2,
                "safety_refusal_total": 2,
                "strata": {
                    "body": {"slot_count": 10, "graded_count": 8, "mean_recall_at_5": 0.88, "mean_mrr_at_5": 0.84, "mean_ndcg_at_5": 0.86},
                    "metadata": {"slot_count": 8, "graded_count": 0, "mean_recall_at_5": None, "mean_mrr_at_5": None, "mean_ndcg_at_5": None},
                    "graph_topology": {"slot_count": 4, "graded_count": 0, "mean_recall_at_5": None, "mean_mrr_at_5": None, "mean_ndcg_at_5": None},
                    "direct_handoff": {"slot_count": 2, "graded_count": 0, "mean_recall_at_5": None, "mean_mrr_at_5": None, "mean_ndcg_at_5": None},
                },
            },
            "captured_projection_reference:postgresql": {
                "arm_id": "captured_projection_reference:postgresql",
                "backend": "postgresql",
                "whole_split_denominator": 24,
                "supported_denominator": 10,
                "graded_denominator": 8,
                "unavailable_count": 14,
                "refused_count": 2,
                "safety_refusal_correct_count": 2,
                "safety_refusal_total": 2,
                "strata": {
                    "body": {"slot_count": 10, "graded_count": 8, "mean_recall_at_5": 0.88, "mean_mrr_at_5": 0.84, "mean_ndcg_at_5": 0.86},
                    "metadata": {"slot_count": 8, "graded_count": 0, "mean_recall_at_5": None, "mean_mrr_at_5": None, "mean_ndcg_at_5": None},
                    "graph_topology": {"slot_count": 4, "graded_count": 0, "mean_recall_at_5": None, "mean_mrr_at_5": None, "mean_ndcg_at_5": None},
                    "direct_handoff": {"slot_count": 2, "graded_count": 0, "mean_recall_at_5": None, "mean_mrr_at_5": None, "mean_ndcg_at_5": None},
                },
            },
        },
    }


def test_derive_future_criteria_binds_observed_baseline_and_records_unresolved_limitations() -> None:
    """Criteria derivation binds baseline digests, separates invariant/quality/cost, and records unresolved token cost."""
    report = _sample_baseline_report()
    proposal = derive_future_criteria_proposal(
        report,
        freeze_sha256="sha256:" + "1" * 64,
        catalog_sha256="sha256:" + "2" * 64,
        policy_digest="sha256:" + "3" * 64,
    )
    assert proposal.status == "proposed_for_parent_review"
    assert proposal.baseline_attempt_id == "calibration-attempt-1"
    assert len(proposal.invariant_requirements) >= 4
    assert len(proposal.quality_requirements) >= 3
    assert proposal.quality_requirements[0]["observed_current_graph_sqlite"] is None
    assert proposal.quality_requirements[2]["observed_native_baseline"] is None
    assert proposal.quality_requirements[0]["proposed_floor"] is None
    assert proposal.quality_requirements[0]["proposed_floor_by_arm"] == {
        "native_tools_baseline": 0.78, "captured_projection_reference:sqlite": 0.88,
        "captured_projection_reference:postgresql": 0.88,
    }
    assert proposal.quality_requirements[2]["proposed_floor"] is None
    assert len(proposal.cost_requirements) >= 2
    assert len(proposal.unresolved_limitations) >= 2
    assert any("token" in lim.lower() or "agent" in lim.lower() for lim in proposal.unresolved_limitations)
    assert FutureCriteriaProposal.from_mapping(proposal.to_dict()) == proposal

    with pytest.raises(ValueError, match="freeze_sha256"):
        derive_future_criteria_proposal(
            report,
            freeze_sha256="sha256:" + "9" * 64,
            catalog_sha256="sha256:" + "2" * 64,
            policy_digest="sha256:" + "3" * 64,
        )


def test_committed_mixed_v1_baseline_artifacts_match_freeze_and_catalog() -> None:
    """Committed mixed-v1 baseline attempt declaration, report, and criteria proposal match freeze and catalog."""
    import json

    from repomap_test_support.retrieval_evaluation_canaries import assert_canary_free
    from repomap_test_support.retrieval_evaluation_fixture import MIXED_V1_FIXTURE_ROOT
    from retrieval_evaluation_harness import _compute_candidate_closure_digests
    from retrieval_evaluation_schema import (
        AttemptDeclaration,
        load_freeze_manifest,
        load_task_catalog,
    )

    catalog = load_task_catalog(MIXED_V1_FIXTURE_ROOT / "tasks" / "catalog-v1.json")
    freeze = load_freeze_manifest(MIXED_V1_FIXTURE_ROOT / "freeze-v1.json")
    baseline_dir = MIXED_V1_FIXTURE_ROOT / "baseline"

    decl_raw = json.loads(
        (baseline_dir / "attempt-declaration-7.json").read_text(encoding="utf-8")
    )
    decl = AttemptDeclaration.from_mapping(decl_raw)
    assert decl.attempt_id == "calibration-attempt-7"
    assert decl.split == "calibration"
    assert decl.freeze_sha256 == freeze.freeze_digest()
    assert decl.catalog_sha256 == catalog.catalog_digest()
    assert len(decl.ordered_task_ids) == 24
    assert decl.runner_profile["execution_purpose"] == "retained_calibration"
    assert dict(decl.candidate_closure_digests) == _compute_candidate_closure_digests(
        MIXED_V1_FIXTURE_ROOT.parents[4]
    )
    assert_canary_free(decl_raw)

    report = json.loads(
        (baseline_dir / "calibration-attempt-7.json").read_text(encoding="utf-8")
    )
    assert report["attempt_id"] == "calibration-attempt-7"
    assert report["split"] == "calibration"
    assert report["held_out_executed"] is False
    assert report["freeze_sha256"] == freeze.freeze_digest()
    assert report["catalog_sha256"] == catalog.catalog_digest()
    assert report["policy_digest"] == freeze.policy_digest
    assert_canary_free(report)

    prop_raw = json.loads(
        (baseline_dir / "criteria-proposal-v1.json").read_text(encoding="utf-8")
    )
    prop = FutureCriteriaProposal.from_mapping(prop_raw)
    assert prop.baseline_attempt_id == "calibration-attempt-7"
    assert prop.status == "proposed_for_parent_review"
    assert prop.freeze_sha256 == freeze.freeze_digest()
    assert prop.catalog_sha256 == catalog.catalog_digest()
    assert_canary_free(prop_raw)
