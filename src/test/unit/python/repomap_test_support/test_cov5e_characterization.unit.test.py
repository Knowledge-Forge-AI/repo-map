from __future__ import annotations

from pathlib import Path

import pytest

import scale14_backend_monitor
from repomap_test_support.test_cov5d_qualification import SEMANTIC_GROUPS
from repomap_test_support.test_cov5e_characterization import (
    ACCEPTED_PRODUCT_TUPLE,
    CALLER_CONTEXTS,
    CANDIDATE_C120_420,
    COV5E_SEMANTIC_MANIFEST,
    FINAL_RELEASE_CAP_MS,
    FIX7_ACCEPTANCE_SUITE,
    FROZEN_POLICY_DIGEST,
    FROZEN_SOURCE_MANIFEST_DIGEST,
    MINIMIZED_COMPRESSED_CALLER_MS,
    REQUIRED_SAMPLE_GAP_MS,
    build_contract_comparison,
    current_policy_deadlines,
    final_release_envelope,
    source_manifest_digest,
    verify_source_manifest,
)
from scale28_observer_deadlines import DEFAULT_OBSERVER_DEADLINE_POLICY


_REPOSITORY_ROOT = Path(__file__).resolve().parents[5]
_EXPECTED_CALLER_CONTEXTS = (
    "registration",
    "identity_validation",
    "startup_summary",
    "active_summary",
    "event_application",
    "resource_read",
    "ownership_sample_one",
    "ownership_sample_two",
    "local_terminal_settlement",
)
_EXPECTED_FIX7_GROUPS = {
    "product_default_fallback": 30,
    "server_timeout": 20,
    "cancellation_timeout": 20,
    "cancellation_transport_failure": 20,
    "three_party_close": 50,
    "close_under_use": 100,
    "source_causality": 200,
    "terminal_claim": 18,
    "reacquisition": 36,
    "actual_caller_context": 9,
    "actual_owning_path": 50,
    "quiet_baseline": 1,
    "bounded_contention": 1,
    "mixed_campaign": 15,
    "fresh_public_rehearsal": 3,
    "prior_publication_cancellation": 1,
    "focused_selection": 10,
    "complete_repository_gate": 4,
}


def test_product_source_has_authorized_successor_drift_from_entry_freeze() -> None:
    with pytest.raises(ValueError, match="production source changed"):
        verify_source_manifest(_REPOSITORY_ROOT)
    assert source_manifest_digest() == FROZEN_SOURCE_MANIFEST_DIGEST

    policy = DEFAULT_OBSERVER_DEADLINE_POLICY
    actual = (
        policy.connection_timeout_seconds * 1_000,
        policy.server_statement_timeout_ms,
        round(policy.client_cancel_after_seconds * 1_000),
        round(policy.cancel_request_timeout_seconds * 1_000),
        round(policy.caller_operation_timeout_seconds * 1_000),
        round(scale14_backend_monitor._OWNERSHIP_HANDOFF_SECONDS * 1_000),
    )

    assert actual == (2_000, 400, 450, 250, 500, 600)
    assert actual != ACCEPTED_PRODUCT_TUPLE.as_tuple()
    assert ACCEPTED_PRODUCT_TUPLE.digest == FROZEN_POLICY_DIGEST
    assert FROZEN_POLICY_DIGEST == (
        "8b0c48f00399956a777d337b28449dc50304519bfb84b7bcae496bf1c14a11c0"
    )


def test_actual_caller_context_manifest_is_explicit_and_nonduplicated() -> None:
    assert tuple(context.name for context in CALLER_CONTEXTS) == (
        _EXPECTED_CALLER_CONTEXTS
    )
    assert len({context.boundary for context in CALLER_CONTEXTS}) == 9
    assert CALLER_CONTEXTS[0].budget_kind == "connection"
    assert all(
        context.maximum_budget_ms <= FINAL_RELEASE_CAP_MS
        for context in CALLER_CONTEXTS[1:]
    )
    assert {
        context.name
        for context in CALLER_CONTEXTS
        if context.remaining_budget
    } == {
        "startup_summary",
        "active_summary",
        "ownership_sample_one",
        "ownership_sample_two",
        "local_terminal_settlement",
    }


def test_fix12_separates_corrected_short_caller_from_historical_compression() -> None:
    trigger_ms, request_ms = current_policy_deadlines(
        ACCEPTED_PRODUCT_TUPLE,
        MINIMIZED_COMPRESSED_CALLER_MS,
    )

    assert MINIMIZED_COMPRESSED_CALLER_MS == 440
    assert (trigger_ms, request_ms) == (400, 40)
    assert trigger_ms <= ACCEPTED_PRODUCT_TUPLE.server_statement_ms
    assert request_ms < CANDIDATE_C120_420.request_bound_ms

    product_trigger, product_request = (
        DEFAULT_OBSERVER_DEADLINE_POLICY.operation_deadlines(
            MINIMIZED_COMPRESSED_CALLER_MS / 1_000
        )
    )
    assert product_trigger * 1_000 == pytest.approx(440)
    assert product_request * 1_000 == pytest.approx(250)


def test_candidate_isolated_hierarchy_exceeds_final_release_envelope() -> None:
    envelope = final_release_envelope(
        CANDIDATE_C120_420,
        sample_gap_ms=REQUIRED_SAMPLE_GAP_MS,
        cap_ms=FINAL_RELEASE_CAP_MS,
    )

    assert CANDIDATE_C120_420.server_statement_ms < (
        CANDIDATE_C120_420.client_trigger_ms
    )
    assert CANDIDATE_C120_420.request_bound_ms == 120
    assert envelope.required_ms == 620
    assert envelope.available_ms == 600
    assert envelope.deficit_ms == 20
    assert envelope.fits is False


def test_two_hundred_millisecond_request_cannot_fit_the_retained_cap() -> None:
    minimum_strict_trigger_ms = (
        ACCEPTED_PRODUCT_TUPLE.server_statement_ms + 1
    )
    minimum_without_settlement_margin_ms = minimum_strict_trigger_ms + 200

    assert minimum_without_settlement_margin_ms == 601
    assert minimum_without_settlement_margin_ms > FINAL_RELEASE_CAP_MS


def test_accepted_candidate_and_required_contract_have_one_exact_gap() -> None:
    comparison = build_contract_comparison()

    assert comparison.accepted_tree == (
        "request_settlement_safe_but_request_bound_unqualified"
    )
    assert comparison.candidate_tree == (
        "isolated_fallback_reliable_but_configured_callers_rejected"
    )
    assert comparison.required_contract == (
        "reliable_request_bound_with_strict_server_precedence_in_every_caller"
    )
    assert comparison.remaining_gap == (
        "complete_final_release_caller_budget_model_and_fitting_default_tuple"
    )
    comparison.validate()


def test_cov5e_manifest_retains_and_extends_predecessor_groups() -> None:
    group_ids = tuple(group.group_id for group in COV5E_SEMANTIC_MANIFEST)

    assert group_ids[: len(SEMANTIC_GROUPS)] == SEMANTIC_GROUPS
    assert group_ids[len(SEMANTIC_GROUPS) :] == (
        "three_party_request_settlement",
        "caller_budget_contract",
    )
    assert len(group_ids) == len(set(group_ids))
    assert "grand_total" not in group_ids
    assert {
        group.group_id: group.required_cases
        for group in COV5E_SEMANTIC_MANIFEST
        if group.required_cases is not None
    }["three_party_request_settlement"] == 50


def test_fix7_acceptance_suite_is_exact_and_group_scoped() -> None:
    observed = {
        group.group_id: group.required_cases
        for group in FIX7_ACCEPTANCE_SUITE
    }

    assert observed == _EXPECTED_FIX7_GROUPS
    assert len(observed) == len(FIX7_ACCEPTANCE_SUITE)
    assert all(group.acceptance_authority for group in FIX7_ACCEPTANCE_SUITE)
    assert "grand_total" not in observed
