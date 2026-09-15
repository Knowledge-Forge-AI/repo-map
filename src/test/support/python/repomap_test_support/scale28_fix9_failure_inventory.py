"""Public-safe inventory of the fourteen reconstructed FIX8 gate failures."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PrimaryCandidate(StrEnum):
    """Closed attribution classes required by the FIX9 protocol."""

    OBSERVER_MECHANISM_FAILURE = "observer_mechanism_failure"
    STRUCTURED_OWNERSHIP_CONTROL_RESULT = (
        "structured_ownership_control_result"
    )
    PRE_DISPATCH_BUDGET_REFUSAL = "pre_dispatch_budget_refusal"
    SESSION_LIFECYCLE_OR_OPERATION_CLASS_MISMATCH = (
        "session_lifecycle_or_operation_class_mismatch"
    )
    TERMINAL_READBACK_OR_CLOSE_SETTLEMENT_DEFECT = (
        "terminal_readback_or_close_settlement_defect"
    )
    RUNTIME_QUALIFICATION_REFUSAL = "runtime_qualification_refusal"
    EVENT_OR_TELEMETRY_FAILURE = "event_or_telemetry_failure"
    UNCLASSIFIED = "unclassified"


@dataclass(frozen=True, slots=True)
class FormerFailureCase:
    """One executable former failure and its public-safe attribution."""

    case_id: str
    node_id: str
    owning_area: str
    semantic_case: str
    primary_candidate: PrimaryCandidate
    source_category: str
    outer_category: str
    sql_dispatched: bool
    validation_ran: bool
    fresh_terminal_readback: bool
    cleanup_expected: str


def _case(
    number: int,
    node_id: str,
    owning_area: str,
    semantic_case: str,
    primary_candidate: PrimaryCandidate,
    source_category: str,
    outer_category: str,
    *,
    sql_dispatched: bool = True,
    validation_ran: bool = True,
    fresh_terminal_readback: bool = True,
    cleanup_expected: str = "exact",
) -> FormerFailureCase:
    return FormerFailureCase(
        f"fix8-gate1-{number:02d}",
        node_id,
        owning_area,
        semantic_case,
        primary_candidate,
        source_category,
        outer_category,
        sql_dispatched,
        validation_ran,
        fresh_terminal_readback,
        cleanup_expected,
    )


FORMER_FAILURES = (
    _case(
        1,
        "src/test/int/python/repomap_kg/storage/"
        "scale14_protected_launch_controls.int.test.py::"
        "test_scale15_real_storage_terminal_authority_campaigns",
        "SCALE14",
        "terminal authority campaigns",
        PrimaryCandidate.TERMINAL_READBACK_OR_CLOSE_SETTLEMENT_DEFECT,
        "backend_quiescence_timeout",
        "backend_quiescence_timeout",
    ),
    _case(
        2,
        "src/test/int/python/repomap_kg/storage/"
        "scale23_backend_telemetry_lifetime.int.test.py::"
        "test_scale23_direct_child_backend_telemetry_lifetime_campaign",
        "SCALE23",
        "direct-child telemetry lifetime",
        PrimaryCandidate.TERMINAL_READBACK_OR_CLOSE_SETTLEMENT_DEFECT,
        "backend_quiescence_timeout",
        "backend_quiescence_timeout",
    ),
    _case(
        3,
        "src/test/int/python/repomap_kg/storage/"
        "scale23_backend_telemetry_lifetime.int.test.py::"
        "test_scale23_direct_child_acknowledgement_failure_fails_closed",
        "SCALE23",
        "acknowledgement failure",
        PrimaryCandidate.EVENT_OR_TELEMETRY_FAILURE,
        "backend_telemetry_failed",
        "backend_telemetry_failed",
    ),
    _case(
        4,
        "src/test/int/python/repomap_kg/storage/"
        "scale28_backend_observer_lifetime.int.test.py::"
        "test_scale28_twenty_long_extraction_observer_campaigns",
        "SCALE28",
        "long extraction observer lifetime",
        PrimaryCandidate.TERMINAL_READBACK_OR_CLOSE_SETTLEMENT_DEFECT,
        "backend_quiescence_timeout",
        "backend_quiescence_timeout",
    ),
    _case(
        5,
        "src/test/int/python/repomap_kg/storage/"
        "scale28_backend_observer_lifetime.int.test.py::"
        "test_scale28_ten_mixed_observer_success_and_failure_campaigns",
        "SCALE28",
        "mixed observer campaigns",
        PrimaryCandidate.TERMINAL_READBACK_OR_CLOSE_SETTLEMENT_DEFECT,
        "backend_quiescence_timeout",
        "backend_quiescence_timeout",
    ),
    _case(
        6,
        "src/test/int/python/repomap_kg/storage/"
        "scale28_backend_observer_lifetime.int.test.py::"
        "test_scale28_hybrid_prior_publication_preserves_source_owned_failure",
        "hybrid/FIX9",
        "prior publication preservation",
        PrimaryCandidate.TERMINAL_READBACK_OR_CLOSE_SETTLEMENT_DEFECT,
        "backend_quiescence_timeout",
        "backend_quiescence_timeout",
    ),
    _case(
        7,
        "src/test/int/python/repomap_kg/storage/"
        "scale28_fix6_candidate_selection.int.test.py::"
        "test_c120_420_candidate_real_characterization_cohorts",
        "SCALE28-FIX1",
        "independent request publication",
        PrimaryCandidate.SESSION_LIFECYCLE_OR_OPERATION_CLASS_MISMATCH,
        "client_cancel_fallback",
        "backend_observer_failed",
    ),
    _case(
        8,
        "src/test/int/python/repomap_kg/storage/"
        "test_cov5d_observer_cancellation.int.test.py::"
        "test_thirty_successful_client_fallbacks_with_decision_support_policy",
        "SCALE28-FIX1",
        "decision-support fallback settlement",
        PrimaryCandidate.SESSION_LIFECYCLE_OR_OPERATION_CLASS_MISMATCH,
        "client_cancel_fallback",
        "backend_observer_failed",
    ),
    _case(
        9,
        "src/test/int/python/repomap_kg/storage/"
        "test_cov5d_observer_cancellation.int.test.py::"
        "test_twenty_predecessor_default_results_remain_historical_evidence",
        "SCALE28-FIX1",
        "predecessor default evidence",
        PrimaryCandidate.SESSION_LIFECYCLE_OR_OPERATION_CLASS_MISMATCH,
        "client_cancel_fallback",
        "backend_observer_failed",
    ),
    _case(
        10,
        "src/test/int/python/repomap_kg/storage/"
        "test_cov5e_product_default_characterization.int.test.py::"
        "test_actual_product_default_under_quiet_and_unrelated_contention[quiet]",
        "SCALE28-FIX1",
        "quiet product-default settlement",
        PrimaryCandidate.SESSION_LIFECYCLE_OR_OPERATION_CLASS_MISMATCH,
        "client_cancel_fallback",
        "backend_observer_failed",
    ),
    _case(
        11,
        "src/test/int/python/repomap_kg/storage/"
        "test_cov5e_product_default_characterization.int.test.py::"
        "test_actual_product_default_under_quiet_and_unrelated_contention"
        "[bounded_contention]",
        "SCALE28-FIX1",
        "contended product-default settlement",
        PrimaryCandidate.SESSION_LIFECYCLE_OR_OPERATION_CLASS_MISMATCH,
        "client_cancel_fallback",
        "backend_observer_failed",
    ),
    _case(
        12,
        "src/test/int/python/repomap_kg/storage/"
        "test_cov5f_product_default_characterization.int.test.py::"
        "test_cov5f_thirty_product_default_fallback_outcomes_are_bounded",
        "SCALE28-FIX1",
        "bounded product-default settlement",
        PrimaryCandidate.SESSION_LIFECYCLE_OR_OPERATION_CLASS_MISMATCH,
        "client_cancel_fallback",
        "backend_observer_failed",
    ),
    _case(
        13,
        "src/test/int/python/repomap_kg/storage/"
        "test_cov5g_r1_configured_characterization.int.test.py::"
        "test_cov5g_r1_two_cohort_configured_cancellation_request_tail",
        "SCALE28-FIX1",
        "rejected predecessor timing protocol",
        PrimaryCandidate.RUNTIME_QUALIFICATION_REFUSAL,
        "runtime_qualification_refusal",
        "runtime_qualification_refusal",
        sql_dispatched=False,
        validation_ran=False,
        fresh_terminal_readback=False,
        cleanup_expected="not_started",
    ),
    _case(
        14,
        "src/test/int/python/repomap_kg/storage/"
        "test_cov5g_r1_process_containment.int.test.py::"
        "test_cov5g_r1_twenty_process_containment_feasibility_cases",
        "hybrid/FIX9",
        "spawn-safe process containment",
        PrimaryCandidate.PRE_DISPATCH_BUDGET_REFUSAL,
        "observer_budget_insufficient",
        "observer_budget_insufficient",
        sql_dispatched=False,
        validation_ran=False,
        fresh_terminal_readback=False,
    ),
)
