from __future__ import annotations

from dataclasses import replace

import pytest

from repomap_test_support.scale28_adr1_decision_model import (
    EvidenceSizedHandoffInputs,
    EvidenceSizedHandoffOutcome,
    derive_evidence_sized_handoff,
)


def _fixed_inputs() -> EvidenceSizedHandoffInputs:
    return EvidenceSizedHandoffInputs(
        connection_bootstrap_max_ms=60,
        sql_tail_ms=111,
        resource_local_overhead_max_ms=4_144,
        resource_settlement_max_ms=280,
        event_readiness_max_ms=1,
        transient_clear_max_ms=5,
        complete_handoff_max_ms=4_524,
        scheduling_and_ipc_margin_ms=100,
        modeled_floor_ms=990,
        operator_guard_ms=3_000,
        cold_handoffs=30,
        loaded_handoffs=60,
        transient_settlements=30,
        owning_area_counts=(
            ("SCALE14", 15),
            ("SCALE23", 15),
            ("SCALE28", 15),
            ("SCALE28-FIX1", 15),
        ),
        valid_outliers_removed=0,
        stable_sample_count=2,
        resource_statement_count=2,
        dynamic_tuning=False,
    )


def test_frozen_campaign_reproduces_the_outcome_b_derivation() -> None:
    result = derive_evidence_sized_handoff(_fixed_inputs())

    assert result.connection_establishment_budget_ms == 90
    assert result.server_statement_timeout_ms == 150
    assert result.client_cancellation_trigger_ms == 170
    assert result.cancellation_request_timeout_ms == 20
    assert result.caller_operation_deadline_ms == 190
    assert result.observer_settlement_deadline_ms == 190
    assert result.resource_local_budget_ms == 4_570
    assert result.resource_settlement_budget_ms == 310
    assert result.event_readiness_budget_ms == 20
    assert result.transient_settlement_budget_ms == 50
    assert result.component_sum_ms == 5_810
    assert result.measured_handoff_bound_ms == 4_624
    assert result.selected_handoff_ceiling_ms == 5_850
    assert result.outcome is EvidenceSizedHandoffOutcome.OPERATOR_GUARD_EXCEEDED


def test_old_ceiling_and_modeled_floor_are_not_the_frozen_candidate() -> None:
    result = derive_evidence_sized_handoff(_fixed_inputs())

    assert result.modeled_floor_ms == 990
    assert result.is_frozen_candidate(500) is False
    assert result.is_frozen_candidate(990) is False
    assert result.is_frozen_candidate(5_850) is True
    assert result.is_authorized_candidate(5_850) is False


def test_valid_observations_cannot_be_silently_removed() -> None:
    with pytest.raises(ValueError, match="valid observation removal is forbidden"):
        replace(_fixed_inputs(), valid_outliers_removed=1)


def test_component_change_invalidates_the_existing_derivation() -> None:
    inputs = _fixed_inputs()
    result = derive_evidence_sized_handoff(inputs)
    changed = replace(inputs, resource_local_overhead_max_ms=4_145)

    assert result.matches_inputs(inputs) is True
    assert result.matches_inputs(changed) is False
    recomputed = derive_evidence_sized_handoff(changed)
    assert recomputed.matches_inputs(changed) is True
    assert recomputed.input_signature != result.input_signature


def test_stable_samples_and_dynamic_tuning_cannot_weaken_the_model() -> None:
    with pytest.raises(ValueError, match="two stable ownership samples are required"):
        replace(_fixed_inputs(), stable_sample_count=1)
    with pytest.raises(ValueError, match="dynamic tuning is forbidden"):
        replace(_fixed_inputs(), dynamic_tuning=True)


def test_guard_rejects_option_one_and_selects_the_bounded_successor() -> None:
    result = derive_evidence_sized_handoff(_fixed_inputs())

    assert result.selected_handoff_ceiling_ms > result.operator_guard_ms
    assert result.option_one_authorized is False
    assert result.production_value_authorized is False
    assert (
        result.mandatory_successor
        == "bounded_revised_or_process_isolated_startup_authority"
    )
    assert result.scale29_authorized is False
