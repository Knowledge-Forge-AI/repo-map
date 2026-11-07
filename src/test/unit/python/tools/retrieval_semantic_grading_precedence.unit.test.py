"""A real refusal remains visible even when an arm cannot answer the task."""
from __future__ import annotations

import pytest

from repomap_test_support.w5_semantic_support import (
    make_w5_calibration_task, make_w5_verified_pin,
)
from retrieval_evaluation_grading import ExecutionState, GradingState
from retrieval_semantic_grading import (
    W5_FILE_GRADING_POLICY_V1, W5_FILE_GRADING_POLICY_V2, grade_w5_task_slot,
)
from retrieval_semantic_representation import RepresentationValidationError


@pytest.mark.parametrize("arm", ["vector_only", "hybrid_rrf", "lexical_only"])
@pytest.mark.parametrize("exposure", ["supported", "unsupported"])
def test_current_grading_keeps_clean_refusal_ahead_of_applicability(
    arm: str, exposure: str,
) -> None:
    task = make_w5_calibration_task(
        comparability_stratum="body", intended_match_surface="captured_text",
        grading_rule="safety_refusal", expected_refusal_code="binding_privacy_not_authorized",
        comparator_exposure={arm: exposure},
    )
    slot = grade_w5_task_slot(
        task, arm_id=arm, verified_pin=make_w5_verified_pin(),
        execution_state=ExecutionState.REFUSED, capability_state="refused",
        refusal_code="binding_privacy_not_authorized", scope_complete=False,
        grading_policy_version=W5_FILE_GRADING_POLICY_V2,
    )
    assert slot.execution_state == ExecutionState.REFUSED
    assert slot.capability_state == "refused"
    assert slot.grading_state == GradingState.NOT_APPLICABLE
    assert slot.safety_refusal_correct is True
    assert slot.returned_hit_count == 0


def test_explicit_legacy_policy_preserves_historical_applicability_order() -> None:
    task = make_w5_calibration_task(
        comparability_stratum="body", intended_match_surface="captured_text",
        grading_rule="safety_refusal", expected_refusal_code="binding_privacy_not_authorized",
    )
    slot = grade_w5_task_slot(
        task, arm_id="vector_only", verified_pin=make_w5_verified_pin(),
        execution_state=ExecutionState.REFUSED, capability_state="refused",
        refusal_code="binding_privacy_not_authorized", scope_complete=False,
        grading_policy_version=W5_FILE_GRADING_POLICY_V1,
    )
    assert slot.execution_state == ExecutionState.UNAVAILABLE
    assert slot.safety_refusal_correct is None


@pytest.mark.parametrize("code", [None, "unknown_selected_binding", "different_refusal"])
def test_wrong_or_absent_reason_never_earns_safety_credit(code: str | None) -> None:
    task = make_w5_calibration_task(
        comparability_stratum="body", intended_match_surface="captured_text",
        grading_rule="safety_refusal", expected_refusal_code="binding_privacy_not_authorized",
    )
    slot = grade_w5_task_slot(
        task, arm_id="vector_only", verified_pin=make_w5_verified_pin(),
        execution_state=ExecutionState.REFUSED, capability_state="refused",
        refusal_code=code, scope_complete=False,
    )
    assert slot.execution_state == ExecutionState.REFUSED
    assert slot.safety_refusal_correct is False


def test_unsupported_without_a_refusal_stays_unattested() -> None:
    task = make_w5_calibration_task(
        comparability_stratum="body", intended_match_surface="captured_text",
        grading_rule="safety_refusal", expected_refusal_code="binding_privacy_not_authorized",
    )
    slot = grade_w5_task_slot(
        task, arm_id="vector_only", verified_pin=make_w5_verified_pin(),
        execution_state=ExecutionState.UNAVAILABLE, capability_state="unavailable",
    )
    assert slot.execution_state == ExecutionState.UNAVAILABLE
    assert slot.safety_refusal_correct is None


def test_unknown_grading_policy_is_not_silently_selected() -> None:
    with pytest.raises(RepresentationValidationError, match="invalid_grading_policy_version"):
        grade_w5_task_slot(
            make_w5_calibration_task(), arm_id="vector_only",
            verified_pin=make_w5_verified_pin(), grading_policy_version="future-policy",
        )
