from __future__ import annotations

from itertools import islice, permutations

import pytest

from repomap_test_support.test_cov5b_decision_model import (
    AuthorityEvent,
    DeadlineEnvelope,
    DecisionOption,
    decision_acceptance_requirements,
    project_source_order,
    qualify_envelope,
)


def test_deadline_envelope_rejects_non_strict_or_under_reserved_order() -> None:
    with pytest.raises(ValueError, match="deadline envelope is invalid"):
        DeadlineEnvelope(400, 400, 20, 460, 10)
    with pytest.raises(ValueError, match="deadline envelope is invalid"):
        DeadlineEnvelope(400, 405, 20, 460, 10)
    with pytest.raises(ValueError, match="deadline envelope is invalid"):
        DeadlineEnvelope(400, 430, 20, 455, 10)


@pytest.mark.parametrize(
    ("envelope", "expected_reason"),
    (
        (
            DeadlineEnvelope(350, 400, 20, 460, 20),
            "configured_sql_exceeds_server_budget",
        ),
        (
            DeadlineEnvelope(400, 440, 20, 480, 10),
            "configured_sql_exceeds_server_budget",
        ),
        (
            DeadlineEnvelope(450, 470, 10, 490, 5),
            "stable_ownership_exceeds_handoff_ceiling",
        ),
    ),
)
def test_observed_in_ceiling_variants_do_not_satisfy_both_authorities(
    envelope: DeadlineEnvelope,
    expected_reason: str,
) -> None:
    result = qualify_envelope(
        envelope,
        handoff_ceiling_ms=500,
        configured_sql_lower_bound_ms=401,
        transient_settlement_ms=50,
    )

    assert result.accepted is False
    assert expected_reason in result.reasons


def test_near_maximum_variant_has_a_990_ms_two_sample_floor() -> None:
    envelope = DeadlineEnvelope(450, 470, 10, 490, 5)

    below = qualify_envelope(
        envelope,
        handoff_ceiling_ms=989,
        configured_sql_lower_bound_ms=401,
        transient_settlement_ms=50,
    )
    floor = qualify_envelope(
        envelope,
        handoff_ceiling_ms=990,
        configured_sql_lower_bound_ms=401,
        transient_settlement_ms=50,
    )

    assert below.accepted is False
    assert floor.accepted is True
    assert floor.minimum_handoff_ms == 990


def test_five_hundred_observation_orders_preserve_source_causality() -> None:
    names = (
        "connection_timeout",
        "server_timeout",
        "client_cancellation",
        "cancellation_limitation",
        "ambient_client",
        "unknown_ownership",
        "threshold",
        "resource_reader",
        "telemetry_eof",
        "event_eof",
        "child_terminal",
        "local_close",
        "fresh_terminal_observer",
    )
    source_events = tuple(
        AuthorityEvent(name, source_sequence)
        for source_sequence, name in enumerate(names, start=1)
    )

    observed = 0
    for observation_order in islice(permutations(names), 500):
        assert project_source_order(source_events, observation_order) == names
        observed += 1

    assert observed == 500


@pytest.mark.parametrize(
    "option",
    (DecisionOption.CEILING_INCREASE, DecisionOption.ISOLATED_AUTHORITY),
)
def test_operator_options_have_complete_acceptance_suites(
    option: DecisionOption,
) -> None:
    requirements = decision_acceptance_requirements(option)

    assert "bounded_bootstrap_fault_matrix" in requirements
    assert "real_timeout_hierarchy" in requirements
    assert "five_hundred_source_order_permutations" in requirements
    assert "four_owning_configured_paths" in requirements
    assert "fifteen_mixed_campaigns" in requirements
    assert "three_fresh_public_rehearsals" in requirements
    assert "prior_publication_failure_rehearsal" in requirements
    assert "four_complete_repository_gates" in requirements
    assert "exact_cleanup" in requirements
    if option is DecisionOption.CEILING_INCREASE:
        assert "authorized_handoff_ceiling" in requirements
        assert "configured_tail_latency_budget" in requirements
    else:
        assert "bounded_worker_lifetime" in requirements
        assert "atomic_release_ownership_contract" in requirements
