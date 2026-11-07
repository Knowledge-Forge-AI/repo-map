"""Unit tests for W5 file-level retrieval grading, gold collapsing, and arm applicability (ADR 0137)."""

from __future__ import annotations

import pytest

from common_lore_index.graph.multi_source import graph_source_binding_id
from common_lore_index.retrieval.query_contracts import EvaluationLocator
from repomap_test_support.w5_semantic_support import (
    BIND_COMP,
    BIND_CORE,
    SNAP_COMP_G1,
    SNAP_CORE_G1,
    SNAP_CORE_G2,
    make_w5_calibration_task,
    make_w5_policy,
    make_w5_readback_adapter,
    make_w5_verified_pin,
)
from retrieval_evaluation_grading import ExecutionState, GradingState
from retrieval_evaluation_schema import GoldTarget
from retrieval_semantic_fusion import (
    AdmittedArmObservation,
    FileIdentityTuple,
    fuse_arm_observations_rrf,
)
from retrieval_semantic_grading import (
    assert_calibration_split_only,
    collapse_gold_targets_to_files,
    compute_file_level_ranking_metrics,
    evaluate_arm_task_applicability,
    grade_w5_task_slot,
    verify_and_project_returned_files,
)
from retrieval_semantic_representation import (
    RepresentationValidationError,
    verify_publication_provenance_from_adapter,
)


def test_held_out_split_is_rejected_at_w5_grading_boundary() -> None:
    """Verify held_out split tasks are rejected with held_out_execution_forbidden."""
    held_out_task = make_w5_calibration_task(task_id="w5-ho-01", split="held_out")
    pin = make_w5_verified_pin(generation=1)
    with pytest.raises(RepresentationValidationError) as exc_info:
        assert_calibration_split_only(held_out_task)
    assert exc_info.value.code == "held_out_execution_forbidden"

    with pytest.raises(RepresentationValidationError) as exc_info2:
        grade_w5_task_slot(held_out_task, arm_id="vector_only", verified_pin=pin)
    assert exc_info2.value.code == "held_out_execution_forbidden"


def test_evaluate_arm_task_applicability_predeclares_metadata_vs_body_and_handoff() -> None:
    """Metadata-only canonical-node-v1 vector arms are unavailable on body/captured_text and direct_handoff."""
    meta_task = make_w5_calibration_task(comparability_stratum="metadata", intended_match_surface="stored_metadata")
    body_task = make_w5_calibration_task(comparability_stratum="body", intended_match_surface="captured_text")
    handoff_task = make_w5_calibration_task(
        comparability_stratum="direct_handoff", intended_match_surface="stored_metadata", grading_rule="direct_handoff"
    )

    assert evaluate_arm_task_applicability("vector_only", meta_task).applicable is True
    dec_body = evaluate_arm_task_applicability("vector_only", body_task)
    assert dec_body.applicable is False
    assert dec_body.reason_code == "metadata_only_vector_body_stratum_unsupported"
    assert dec_body.default_execution_state == "unavailable"
    assert dec_body.default_grading_state == "ungraded"

    assert evaluate_arm_task_applicability("hybrid_rrf", body_task).applicable is True
    assert evaluate_arm_task_applicability("hybrid_rrf", handoff_task).applicable is False


def test_collapse_gold_targets_to_files_and_file_level_metrics_deduplication() -> None:
    """Multiple span gold targets in one file collapse to max grade and unique positive file denominator."""
    pin = make_w5_verified_pin(generation=1)
    gold_targets = (
        GoldTarget(
            locator=EvaluationLocator(binding_id=BIND_CORE, source_relative_path="pkg/pipeline.py", start_line=1, end_line=10),
            relevance_grade=1, rationale="span 1",
        ),
        GoldTarget(
            locator=EvaluationLocator(binding_id=BIND_CORE, source_relative_path="pkg/pipeline.py", start_line=20, end_line=40),
            relevance_grade=3, rationale="span 2 higher grade in same file",
        ),
        GoldTarget(
            locator=EvaluationLocator(binding_id=BIND_COMP, source_relative_path="scripts/deploy.sh", start_line=5, end_line=15),
            relevance_grade=2, rationale="second positive file",
        ),
    )
    collapsed = collapse_gold_targets_to_files(gold_targets)
    assert len(collapsed) == 2
    assert collapsed[0].binding_id == BIND_CORE
    assert collapsed[0].source_relative_path == "pkg/pipeline.py"
    assert collapsed[0].relevance_grade == 3
    assert collapsed[0].source_gold_count == 2
    assert collapsed[1].relevance_grade == 2

    returned = (
        FileIdentityTuple(BIND_CORE, SNAP_CORE_G1, "pkg/pipeline.py"),
        FileIdentityTuple(BIND_CORE, SNAP_CORE_G1, "pkg/pipeline.py"),
        FileIdentityTuple(BIND_COMP, SNAP_COMP_G1, "scripts/deploy.sh"),
    )
    metrics = compute_file_level_ranking_metrics(returned, gold_targets, verified_pin=pin)
    assert metrics["file_recall@1"] == 0.5
    assert metrics["file_mrr@1"] == 1.0
    assert metrics["file_recall@3"] == 1.0
    assert metrics["file_ndcg@3"] == 1.0


def test_verify_and_project_returned_files_enforces_snapshot_generation_scope_and_live_store() -> None:
    """Returned files with stale snapshot_id, wrong task generation, out-of-scope binding, or stale store are refused."""
    cell = make_w5_readback_adapter(run_id=1, generation=1)
    pin_g1 = verify_publication_provenance_from_adapter(cell, policy=make_w5_policy())
    task_g1 = make_w5_calibration_task(generation=1, selected_bindings=(BIND_CORE,))
    task_g2 = make_w5_calibration_task(generation=2, selected_bindings=(BIND_CORE,))

    with pytest.raises(RepresentationValidationError) as exc_gen:
        verify_and_project_returned_files(
            (FileIdentityTuple(BIND_CORE, SNAP_CORE_G1, "pkg/pipeline.py"),), verified_pin=pin_g1, task=task_g2,
        )
    assert exc_gen.value.code == "generation_mismatch"

    with pytest.raises(RepresentationValidationError) as exc_snap:
        verify_and_project_returned_files(
            (FileIdentityTuple(BIND_CORE, SNAP_CORE_G2, "pkg/pipeline.py"),), verified_pin=pin_g1, task=task_g1,
        )
    assert exc_snap.value.code == "snapshot_id_mismatch"

    with pytest.raises(RepresentationValidationError) as exc_scope:
        verify_and_project_returned_files(
            (FileIdentityTuple(BIND_COMP, SNAP_COMP_G1, "scripts/deploy.sh"),), verified_pin=pin_g1, task=task_g1,
        )
    assert exc_scope.value.code == "out_of_scope_binding"

    # Advancing live store invalidates pin at grading projection boundary
    cell.advance(run_id=2, generation=2)
    with pytest.raises(RepresentationValidationError) as exc_stale:
        verify_and_project_returned_files(
            (FileIdentityTuple(BIND_CORE, SNAP_CORE_G1, "pkg/pipeline.py"),), verified_pin=pin_g1, task=task_g1,
        )
    assert exc_stale.value.code == "stale_publication_receipt"


def test_grade_w5_task_slot_derives_fusion_result_states_and_prevents_incomplete_full_credit() -> None:
    """grade_w5_task_slot derives state from fusion_result, caps incomplete results at PARTIAL, and rejects override spoofing."""
    pin = make_w5_verified_pin(generation=1)
    body_task = make_w5_calibration_task(comparability_stratum="body", intended_match_surface="captured_text")
    unavail_slot = grade_w5_task_slot(
        body_task, arm_id="vector_only", verified_pin=pin,
        returned_files=(FileIdentityTuple(BIND_CORE, SNAP_CORE_G1, "pkg/pipeline.py"),),
    )
    assert unavail_slot.execution_state == ExecutionState.UNAVAILABLE
    assert unavail_slot.grading_state == GradingState.UNGRADED
    assert unavail_slot.metrics["file_recall@5"] == 0.0
    assert "recall@5" not in unavail_slot.metrics

    meta_task = make_w5_calibration_task(comparability_stratum="metadata", intended_match_surface="stored_metadata")
    span_loc = EvaluationLocator(binding_id=BIND_CORE, source_relative_path="pkg/pipeline.py", start_line=10, end_line=25)
    graded_slot = grade_w5_task_slot(
        meta_task, arm_id="hybrid_rrf", verified_pin=pin,
        returned_files=(FileIdentityTuple(BIND_CORE, SNAP_CORE_G1, "pkg/pipeline.py"),),
        span_locators=(span_loc,),
    )
    assert graded_slot.execution_state == ExecutionState.COMPLETED
    assert graded_slot.grading_state == GradingState.CORRECT
    assert graded_slot.metrics["file_recall@5"] == 1.0
    assert graded_slot.metrics["recall@5"] == 0.5

    # Incomplete/truncated fusion_result is automatically derived as capability_state="partial" and capped at PARTIAL
    f_pipe = FileIdentityTuple(BIND_CORE, SNAP_CORE_G1, "pkg/pipeline.py")
    trunc_arm = AdmittedArmObservation(
        arm_id="lex", mode="ranked_discovery", verified_pin=pin,
        raw_file_hits=((f_pipe, 1, "c1"),), incomplete=True, truncated=True,
    )
    trunc_fusion = fuse_arm_observations_rrf((trunc_arm,), expected_pin=pin)
    partial_slot = grade_w5_task_slot(meta_task, arm_id="hybrid_rrf", verified_pin=pin, fusion_result=trunc_fusion)
    assert partial_slot.execution_state == ExecutionState.COMPLETED
    assert partial_slot.capability_state == "partial"
    assert partial_slot.grading_state == GradingState.PARTIAL
    assert partial_slot.metrics["file_recall@5"] == 1.0

    # Conflicting caller override of capability_state or scope_complete against fusion_result is refused
    with pytest.raises(RepresentationValidationError) as exc_override:
        grade_w5_task_slot(
            meta_task, arm_id="hybrid_rrf", verified_pin=pin,
            fusion_result=trunc_fusion, capability_state="available",
        )
    assert exc_override.value.code == "grading_state_override_mismatch"

    # Absent-answer task with incomplete coverage cannot be graded CORRECT
    absent_task = make_w5_calibration_task(grading_rule="absent_answer", gold_targets=())
    empty_inc_arm = AdmittedArmObservation(
        arm_id="lex", mode="ranked_discovery", verified_pin=pin, raw_file_hits=(), incomplete=True,
    )
    empty_inc_fusion = fuse_arm_observations_rrf((empty_inc_arm,), expected_pin=pin)
    absent_slot = grade_w5_task_slot(absent_task, arm_id="hybrid_rrf", verified_pin=pin, fusion_result=empty_inc_fusion)
    assert absent_slot.grading_state == GradingState.INCORRECT
    assert absent_slot.absent_answer_correct is False

    # Refused fusion_result derives ExecutionState.REFUSED and grades safety_refusal tasks accurately
    refusal_task = make_w5_calibration_task(
        grading_rule="safety_refusal", expected_refusal_code="binding_privacy_not_authorized", gold_targets=(),
    )
    refused_arm = AdmittedArmObservation(
        arm_id="lex", mode="ranked_discovery", verified_pin=pin,
        execution_state=ExecutionState.REFUSED, refusal_code="binding_privacy_not_authorized",
    )
    refused_fusion = fuse_arm_observations_rrf((refused_arm,), expected_pin=pin)
    refusal_slot = grade_w5_task_slot(refusal_task, arm_id="hybrid_rrf", verified_pin=pin, fusion_result=refused_fusion)
    assert refusal_slot.execution_state == ExecutionState.REFUSED
    assert refusal_slot.grading_state == GradingState.NOT_APPLICABLE
    assert refusal_slot.capability_state == "refused"
    assert refusal_slot.safety_refusal_correct is True


def test_short_binding_alias_normalization_and_span_locator_verification() -> None:
    """Short binding aliases normalize when graph_id is supplied; out-of-scope span_locators raise RepresentationValidationError."""
    pin = make_w5_verified_pin(generation=1)
    short_target = GoldTarget(
        locator=EvaluationLocator(binding_id="core", source_relative_path="pkg/pipeline.py", start_line=1, end_line=5),
        relevance_grade=2, rationale="short alias target",
    )
    collapsed = collapse_gold_targets_to_files((short_target,), graph_id="w5-test-graph")
    assert collapsed[0].binding_id == graph_source_binding_id("w5-test-graph", "core")

    task_core_only = make_w5_calibration_task(selected_bindings=(BIND_CORE,))
    bad_span_loc = EvaluationLocator(binding_id=BIND_COMP, source_relative_path="scripts/deploy.sh", start_line=1, end_line=5)
    with pytest.raises(RepresentationValidationError) as exc_span:
        grade_w5_task_slot(
            task_core_only, arm_id="hybrid_rrf", verified_pin=pin,
            returned_files=(FileIdentityTuple(BIND_CORE, SNAP_CORE_G1, "pkg/pipeline.py"),),
            span_locators=(bad_span_loc,),
        )
    assert exc_span.value.code == "out_of_scope_binding"
