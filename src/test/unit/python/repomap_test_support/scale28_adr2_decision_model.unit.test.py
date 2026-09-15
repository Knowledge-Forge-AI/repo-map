from __future__ import annotations

from dataclasses import replace
from typing import TypedDict

import pytest

from repomap_test_support.scale28_adr2_decision_model import (
    FreshnessDesign,
    PrototypeEvidence,
    StartupArchitecture,
    StartupAuthorityInputs,
    select_startup_authority,
)
from repomap_test_support.scale28_adr2_campaign_results import PROTOCOL_REVISION
from repomap_test_support.scale28_adr2_freshness_model import (
    derive_freshness_lease,
)


class _InputChanges(TypedDict, total=False):
    adr1_rejected_handoff_ms: int
    final_release_ceiling_ms: int
    stable_sample_count: int
    resource_result_settled: bool
    cleanup_complete: bool
    dynamic_tuning: bool
    public_configuration: bool
    blind_reconnect: bool
    observation_gap: bool
    scale29_requested: bool
    maximum_attempts: int
    preparation_attempt_ceiling_ms: int
    preparation_total_ceiling_ms: int
    transfer_reserve_ms: int
    freshness_lease_ms: int


def _evidence() -> PrototypeEvidence:
    return PrototypeEvidence(
        protocol_revision=PROTOCOL_REVISION,
        receipt_schema_version=3,
        immutable_canonical_authority=True,
        bounded_ipc_before_decode=True,
        observed_result_contract=True,
        source_hashes_match=True,
        selected_freshness_design=FreshnessDesign.PARENT_ACKNOWLEDGED_FRAME,
        rejected_freshness_design_category=(
            "unacknowledged_terminal_write_unbounded"
        ),
        cold_executions=20,
        loaded_executions=30,
        transient_executions=20,
        owning_area_counts=(
            ("SCALE14", 10),
            ("SCALE23", 10),
            ("SCALE28", 10),
            ("SCALE28-FIX1", 10),
        ),
        ordering_count=100,
        original_fault_count=180,
        original_fault_scenario_count=18,
        freshness_fault_count=120,
        freshness_fault_scenario_count=12,
        mutation_attack_count=100,
        mutation_family_count=10,
        bounded_ipc_fault_count=80,
        bounded_ipc_family_count=8,
        postgres_visible_count=10,
        postgres_settled_count=10,
        static_probe_count=2,
        preparation_max_ms=100,
        frame_to_receipt_max_ms=100,
        frame_to_release_max_ms=100,
        final_release_max_ms=10,
        total_observed_records=702,
        valid_observations_removed=0,
        cleanup_passed=True,
    )


def _inputs() -> StartupAuthorityInputs:
    return StartupAuthorityInputs(
        adr1_rejected_handoff_ms=5_850,
        operator_guard_ms=3_000,
        preparation_attempt_ceiling_ms=5_000,
        preparation_total_ceiling_ms=10_000,
        final_release_ceiling_ms=650,
        freshness_lease_ms=1_450,
        transfer_reserve_ms=100,
        maximum_attempts=2,
        stable_sample_count=2,
        resource_result_settled=True,
        cleanup_complete=True,
        dynamic_tuning=False,
        public_configuration=False,
        blind_reconnect=False,
        observation_gap=False,
        scale29_requested=False,
        evidence=_evidence(),
    )


def test_revision_four_evidence_accepts_corrected_hybrid_authority() -> None:
    decision = select_startup_authority(_inputs())

    assert decision.selected_architecture is StartupArchitecture.HYBRID
    assert (
        decision.selected_freshness_design
        is FreshnessDesign.PARENT_ACKNOWLEDGED_FRAME
    )
    assert decision.receipt_schema_version == 3
    assert decision.preparation_attempt_ceiling_ms == 5_000
    assert decision.preparation_total_ceiling_ms == 10_000
    assert decision.final_release_ceiling_ms == 650
    assert decision.freshness_lease_ms == 1_450
    assert decision.production_qualified is False
    assert decision.scale29_authorized is False


def test_exact_freshness_design_rejection_is_frozen() -> None:
    decision = select_startup_authority(_inputs())

    assert decision.freshness_design_rejection == (
        FreshnessDesign.ONE_RECEIPT_LAG,
        "unacknowledged_terminal_write_unbounded",
    )
    assert decision.static_rejections == (
        (
            StartupArchitecture.PROCESS_ISOLATED_FULL,
            "nontransferable_parent_authority",
        ),
        (
            StartupArchitecture.TWO_STAGE_IN_PROCESS,
            "in_process_resource_not_forcibly_settleable",
        ),
    )


def test_selected_lease_uses_revision_four_derivation_contract() -> None:
    derivation = derive_freshness_lease(
        frame_to_receipt_max_ms=100,
        frame_to_release_max_ms=100,
    )

    assert derivation.component_margin_ms == 30
    assert derivation.observation_to_receipt_budget_ms == 410
    assert derivation.freshness_component_bound_ms == 1_410
    assert derivation.measured_observation_to_release_bound_ms == 200
    assert derivation.selected_freshness_lease_ms == 1_450


def test_decision_rejects_evidence_that_derives_a_different_lease() -> None:
    changed_evidence = replace(_evidence(), frame_to_receipt_max_ms=450)

    with pytest.raises(ValueError, match="lease derivation changed"):
        replace(
            _inputs(),
            evidence=changed_evidence,
            freshness_lease_ms=1_500,
        )


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({"adr1_rejected_handoff_ms": 5_800}, "ADR1 rejection is required"),
        ({"final_release_ceiling_ms": 651}, "final release ceiling is invalid"),
        ({"stable_sample_count": 1}, "two stable ownership samples"),
        ({"resource_result_settled": False}, "settled resource result"),
        ({"cleanup_complete": False}, "cleanup is required"),
        ({"dynamic_tuning": True}, "dynamic tuning is forbidden"),
        ({"public_configuration": True}, "public configuration is forbidden"),
        ({"blind_reconnect": True}, "blind reconnect is forbidden"),
        ({"observation_gap": True}, "observation gap is forbidden"),
        ({"scale29_requested": True}, "SCALE29 remains prohibited"),
    ),
)
def test_non_negotiable_authorities_cannot_be_weakened(
    changes: _InputChanges,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        replace(_inputs(), **changes)


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({"maximum_attempts": 3}, "maximum attempts must be two"),
        ({"preparation_attempt_ceiling_ms": 5_001}, "attempt ceiling"),
        ({"preparation_total_ceiling_ms": 10_001}, "total preparation ceiling"),
        ({"transfer_reserve_ms": 101}, "transfer reserve"),
        ({"freshness_lease_ms": 1_400}, "freshness lease"),
    ),
)
def test_preparation_and_freshness_bounds_are_exact(
    changes: _InputChanges,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        replace(_inputs(), **changes)


def test_complete_campaign_counts_and_zero_removal_are_required() -> None:
    with pytest.raises(ValueError, match="campaign is incomplete"):
        replace(_evidence(), freshness_fault_count=119)
    with pytest.raises(ValueError, match="valid observation removal"):
        replace(_evidence(), valid_observations_removed=1)
    with pytest.raises(ValueError, match="prototype cleanup"):
        replace(_evidence(), cleanup_passed=False)
    with pytest.raises(ValueError, match="campaign is incomplete"):
        replace(_evidence(), total_observed_records=701)
    with pytest.raises(ValueError, match="authority evidence"):
        replace(_evidence(), source_hashes_match=False)


def test_state_machine_includes_frame_ack_receipt_and_final_checks() -> None:
    decision = select_startup_authority(_inputs())

    assert decision.state_machine == (
        "unprepared",
        "preparing",
        "observation_frame_received",
        "observation_frame_accepted",
        "observation_acknowledged",
        "preparation_result_received",
        "preparation_validated",
        "preparation_settled",
        "final_readiness_open",
        "transient_ownership_clear",
        "stable_sample_one",
        "stable_sample_two",
        "ready_to_release",
        "child_released",
    )
    assert decision.failure_states == ("refused", "settled")


def test_fix4_successor_contract_is_exact() -> None:
    decision = select_startup_authority(_inputs())

    assert decision.fix4_contract.stalled_handshake_xfails_to_green == 10
    assert decision.fix4_contract.timeout_cancellation_xfails_to_green == 6
    assert decision.fix4_contract.configured_quarantines_to_green == 4
    assert decision.fix4_contract.all_adr2_fix1_freshness_tests is True
    assert decision.fix4_contract.all_adr2_fix2_mutation_tests is True
    assert decision.fix4_contract.all_adr2_fix2_bounded_ipc_tests is True
    assert decision.fix4_contract.all_adr2_fix2_campaign_integrity_tests is True
    assert decision.fix4_contract.receipt_schema_version == 3
    assert decision.fix4_contract.production_commits == 1
    assert decision.fix4_contract.protected_access is False


def test_test_cov5c_adds_corrected_protocol_qualification() -> None:
    decision = select_startup_authority(_inputs())

    contract = decision.test_cov5c_contract
    assert contract.mutation_resistance_black_box_cases == 50
    assert contract.bounded_ipc_process_matrices == 30
    assert contract.receipt_v3_terminal_claim_matrices == 20
    assert contract.actual_configured_owning_area_executions == 40
    assert contract.exact_category_fault_checks == 100
    assert contract.observation_frame_ack_matrix_passes == 30
    assert contract.corrected_freshness_age_matrix_passes == 50
    assert contract.stale_checkpoint_permutations == 100
    assert contract.reacquisition_generations_per_case == 2
    assert contract.selected_scope_expected_failures_remaining == 0
    assert contract.cross_platform_process_refusal_coverage_required is True
    assert contract.exact_cleanup_required is True
    assert contract.independent_review_approval_required is True
    for field_name in (
        "cross_platform_process_refusal_coverage_required",
        "exact_cleanup_required",
        "independent_review_approval_required",
    ):
        with pytest.raises(
            ValueError,
            match="mandatory qualification gate is disabled",
        ):
            replace(contract, **{field_name: False})


def test_mutation_and_transport_matrices_are_frozen() -> None:
    decision = select_startup_authority(_inputs())

    assert len(decision.mutation_matrix) == 10
    assert len(decision.bounded_ipc_matrix) == 8
    assert "retained_canonical_authority" in decision.mutation_matrix
    assert "sender_exit_during_message" in decision.bounded_ipc_matrix
