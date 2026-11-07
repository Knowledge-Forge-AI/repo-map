"""Execution-state and no-credit contracts for W5 multi-arm fusion."""

from __future__ import annotations

from repomap_test_support.w5_semantic_support import (
    BIND_CORE,
    SNAP_CORE_G1,
    make_w5_calibration_task,
    make_w5_verified_pin,
)
from retrieval_evaluation_grading import ExecutionState, GradingState
from retrieval_semantic_fusion import (
    AdmittedArmObservation,
    FileIdentityTuple,
    fuse_arm_observations_rrf,
)
from retrieval_semantic_grading import grade_w5_task_slot
from retrieval_semantic_representation import VerifiedPublicationPin


def _completed_arm(pin: VerifiedPublicationPin) -> AdmittedArmObservation:
    return AdmittedArmObservation(
        arm_id="lexical",
        mode="ranked_discovery",
        verified_pin=pin,
        raw_file_hits=((
            FileIdentityTuple(BIND_CORE, SNAP_CORE_G1, "pkg/pipeline.py"),
            1,
            "lexical:pipeline",
        ),),
    )


def test_failed_arm_preserves_reason_and_cannot_receive_or_grade_credit() -> None:
    pin = make_w5_verified_pin()
    failed = AdmittedArmObservation(
        arm_id="vector",
        mode="ranked_discovery",
        verified_pin=pin,
        execution_state=ExecutionState.FAILED,
        failure_reason="vector response transport failed",
    )
    result = fuse_arm_observations_rrf((_completed_arm(pin), failed), expected_pin=pin)
    assert result.execution_state == ExecutionState.FAILED
    assert result.failure_reason == "vector response transport failed"
    assert result.hits == ()
    assert result.credited_as_fused is False

    slot = grade_w5_task_slot(
        make_w5_calibration_task(),
        arm_id="hybrid_rrf",
        verified_pin=pin,
        fusion_result=result,
    )
    assert slot.execution_state == ExecutionState.FAILED
    assert slot.grading_state == GradingState.UNGRADED
    assert slot.capability_state == "failed"
    assert slot.returned_hit_count == 0
    assert slot.metrics["file_recall@5"] == 0.0


def test_not_run_arm_refuses_by_default_and_explicit_fallback_stays_degraded() -> None:
    pin = make_w5_verified_pin()
    not_run = AdmittedArmObservation(
        arm_id="vector",
        mode="ranked_discovery",
        verified_pin=pin,
        execution_state=ExecutionState.NOT_RUN,
        unavailable_reason="index_not_selected",
    )
    complete = _completed_arm(pin)

    refused = fuse_arm_observations_rrf((complete, not_run), expected_pin=pin)
    assert refused.execution_state == ExecutionState.NOT_RUN
    assert refused.unavailable_reason == "index_not_selected"
    assert refused.hits == ()
    assert refused.credited_as_fused is False

    fallback = fuse_arm_observations_rrf(
        (complete, not_run),
        expected_pin=pin,
        allow_explicit_single_arm_fallback=True,
    )
    assert fallback.execution_state == ExecutionState.NOT_RUN
    assert fallback.unavailable_reason == "index_not_selected"
    assert fallback.fallback_disclosed is True
    assert fallback.fallback_from_arms == ("vector",)
    assert fallback.credited_as_fused is False
    assert len(fallback.hits) == 1

    slot = grade_w5_task_slot(
        make_w5_calibration_task(),
        arm_id="hybrid_rrf",
        verified_pin=pin,
        fusion_result=fallback,
    )
    assert slot.execution_state == ExecutionState.NOT_RUN
    assert slot.grading_state == GradingState.UNGRADED
    assert slot.capability_state == "unavailable"
    assert slot.returned_hit_count == 1
    assert slot.metrics["file_recall@5"] == 0.0
