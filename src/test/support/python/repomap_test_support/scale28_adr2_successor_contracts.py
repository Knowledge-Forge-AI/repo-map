"""Immutable SCALE28-FIX4 and TEST-COV5C qualification contracts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Scale28Fix4Contract:
    """Exact production-implementation scope unlocked only by Outcome A."""

    stalled_handshake_xfails_to_green: int = 10
    timeout_cancellation_xfails_to_green: int = 6
    configured_quarantines_to_green: int = 4
    all_adr2_fix1_freshness_tests: bool = True
    all_adr2_fix2_mutation_tests: bool = True
    all_adr2_fix2_bounded_ipc_tests: bool = True
    all_adr2_fix2_campaign_integrity_tests: bool = True
    receipt_schema_version: int = 3
    production_commits: int = 1
    protected_access: bool = False


@dataclass(frozen=True, slots=True)
class TestCov5CContract:
    """Independent qualification bar after SCALE28-FIX4."""

    mutation_resistance_black_box_cases: int = 50
    bounded_ipc_process_matrices: int = 30
    receipt_v3_terminal_claim_matrices: int = 20
    actual_configured_owning_area_executions: int = 40
    exact_category_fault_checks: int = 100
    bootstrap_fault_matrix_passes: int = 30
    postgres_timeout_hierarchy_passes: int = 50
    cross_authority_permutations: int = 500
    observation_frame_ack_matrix_passes: int = 30
    corrected_freshness_age_matrix_passes: int = 50
    stale_checkpoint_permutations: int = 100
    reacquisition_generations_per_case: int = 2
    formerly_quarantined_owning_paths: int = 4
    configured_mixed_campaigns: int = 15
    fresh_dress_rehearsals: int = 3
    prior_publication_failure_rehearsals: int = 1
    focused_black_box_selections: int = 10
    complete_repository_gates: int = 4
    selected_scope_expected_failures_remaining: int = 0
    cross_platform_process_refusal_coverage_required: bool = True
    exact_cleanup_required: bool = True
    independent_review_approval_required: bool = True

    def __post_init__(self) -> None:
        required = (
            self.cross_platform_process_refusal_coverage_required,
            self.exact_cleanup_required,
            self.independent_review_approval_required,
        )
        if any(value is not True for value in required):
            raise ValueError("TEST-COV5C mandatory qualification gate is disabled")
