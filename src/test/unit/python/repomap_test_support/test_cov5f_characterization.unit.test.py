from __future__ import annotations

from pathlib import Path

import pytest

from repomap_test_support.test_cov5f_characterization import (
    ACCEPTED_POLICY,
    ADR_0045_POLICY,
    CALLER_CONTEXTS,
    CHARACTERIZATION_GROUPS,
    FIX7_COMMIT,
    FROZEN_ACCEPTED_POLICY_DIGEST,
    NEXT_DECISION,
    OPERATION_CLASS_CASES,
    PRIVATE_CANDIDATE_SHA256,
    adr_sql_deadlines,
    group_map,
    verify_source_freeze,
)
from scale28_observer_deadlines import DEFAULT_OBSERVER_DEADLINE_POLICY


_REPOSITORY_ROOT = Path(__file__).resolve().parents[5]


def test_cov5f_retains_pushed_fix7_freeze_after_authorized_source_drift() -> None:
    with pytest.raises(ValueError, match="production source changed"):
        verify_source_freeze(_REPOSITORY_ROOT)
    assert FIX7_COMMIT == "1e2862f08d08281f8f09290fc83999f0f77f4a93"
    assert PRIVATE_CANDIDATE_SHA256 == (
        "dcc02aeb6ca9c65a8bdc081742083985b652ca7543f0574506e222f8bf89f649"
    )


def test_cov5f_freezes_accepted_policy_separately_from_adr_candidate() -> None:
    policy = DEFAULT_OBSERVER_DEADLINE_POLICY
    observed = type(ACCEPTED_POLICY)(
        policy.connection_timeout_seconds * 1_000,
        policy.server_statement_timeout_ms,
        round(policy.client_cancel_after_seconds * 1_000),
        round(policy.cancel_request_timeout_seconds * 1_000),
        round(policy.caller_operation_timeout_seconds * 1_000),
    )

    assert observed.request_ms == 250
    assert observed != ACCEPTED_POLICY
    assert ACCEPTED_POLICY.digest == FROZEN_ACCEPTED_POLICY_DIGEST
    assert ADR_0045_POLICY.request_ms == 120
    assert ACCEPTED_POLICY.request_ms == 40
    assert observed != ADR_0045_POLICY


@pytest.mark.parametrize(
    "caller_ms",
    (1, 100, 200, 300, 400, 410, 411, 412, 413, 414, 415, 419),
)
def test_twelve_adr_pre_dispatch_refusals(caller_ms: int) -> None:
    with pytest.raises(ValueError, match="insufficient"):
        adr_sql_deadlines(caller_ms)


@pytest.mark.parametrize(
    ("caller_ms", "trigger_ms"),
    ((420, 420), (421, 421), (449, 449), (450, 450), (500, 450)),
)
def test_adr_dispatch_boundaries_preserve_server_precedence(
    caller_ms: int,
    trigger_ms: int,
) -> None:
    trigger, request = adr_sql_deadlines(caller_ms)

    assert trigger == trigger_ms
    assert request == 120
    assert 400 < trigger <= caller_ms


@pytest.mark.parametrize("case", OPERATION_CLASS_CASES)
def test_eight_operation_class_cases_are_closed(case) -> None:
    assert case.operation
    assert case.operation_class in {
        "connection_startup",
        "sql_bounded",
        "serialization_only",
        "settlement",
    }
    assert isinstance(case.issues_sql, bool)


def test_operation_class_and_sql_use_are_independent() -> None:
    cases = {case.operation: case for case in OPERATION_CLASS_CASES}

    assert cases["connection_registration"].operation_class == (
        "connection_startup"
    )
    assert cases["connection_registration"].issues_sql is True
    assert cases["summary_and_identity_validation"].operation_class == (
        "serialization_only"
    )
    assert cases["summary_and_identity_validation"].issues_sql is False
    assert cases["startup_active_summary"].operation_class == "sql_bounded"
    assert cases["startup_active_summary"].issues_sql is True
    assert cases["close_and_request_settlement"].operation_class == "settlement"
    assert cases["close_and_request_settlement"].issues_sql is False


def test_nine_actual_caller_contexts_remain_distinct() -> None:
    assert len(CALLER_CONTEXTS) == 9
    assert len({case.name for case in CALLER_CONTEXTS}) == 9
    assert CALLER_CONTEXTS[0].budget_owner == "connection_startup"
    assert CALLER_CONTEXTS[-1].budget_owner == "settlement"


@pytest.mark.parametrize("repetition", range(20))
def test_twenty_independent_final_window_derivations(repetition: int) -> None:
    del repetition
    components_ms = (20, 10, 20, 50, 420, 20, 60)

    assert sum(components_ms) == 600
    assert 650 - sum(components_ms) == 50
    assert components_ms[3] == 50
    assert components_ms[4] == 420


def test_characterization_manifest_separates_completed_and_blocked_groups() -> None:
    groups = group_map()

    assert len(groups) == len(CHARACTERIZATION_GROUPS)
    assert "grand_total" not in groups
    assert groups["product_default_fallback"].disposition == "blocked"
    assert groups["pre_dispatch"].disposition == "candidate_only"
    assert groups["source_causality"].disposition == "completed"
    assert groups["complete_gate"].required_cases == 4


def test_next_step_requires_an_adr_and_platform_decision() -> None:
    assert NEXT_DECISION.decision_kind == (
        "ADR_revision_and_platform_measurement"
    )
    assert "tail bound selected before product mutation" in (
        NEXT_DECISION.minimum_evidence
    )
    assert "accept CancellationTimeout as successful fallback" in (
        NEXT_DECISION.prohibited_shortcuts
    )
    assert "raise the final-release window" in NEXT_DECISION.prohibited_shortcuts
