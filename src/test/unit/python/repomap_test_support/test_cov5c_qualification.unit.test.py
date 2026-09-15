from __future__ import annotations

from functools import partial

from itertools import permutations
import json

import pytest

from repomap_test_support.test_cov5c_qualification import (
    REQUEST_ROUND_TRIP_REPEATS,
    REACQUISITION_FAILURES,
    RequestRoundTripStabilityCampaign,
    build_authority,
    build_evidence,
    build_expectations,
    run_request_round_trip_probe,
)
from scale28_preparation_authority import PreparationAuthorityError
from scale28_preparation_receipts import PreparationTerminalReceiptV3
from scale28_preparation_values import PreparationState


_FIRST_ATTEMPT_FAILURES = tuple(
    failure
    for failure in REACQUISITION_FAILURES
    if failure != "second_failure"
)
_REACQUISITION_CASES = tuple(
    pytest.param(
        first_failure,
        second_outcome,
        id=f"{first_failure}-then-{second_outcome}",
    )
    for first_failure in _FIRST_ATTEMPT_FAILURES
    for second_outcome in ("success", "second_failure")
)
_RELEASE_OPERATIONS = ("transient", "stable", "ready", "child")
_RELEASE_ORDERS = tuple(permutations(_RELEASE_OPERATIONS))
_VALID_RELEASE_ORDER = ("transient", "stable", "ready", "child")


@pytest.mark.parametrize("case_number", range(5))
def test_five_distinct_mutation_and_aliasing_operations(
    case_number: int,
) -> None:
    evidence = build_evidence()
    mutation = case_number % 5

    if mutation == 0:
        changed = bytearray(evidence.receipt_bytes)
        changed[(case_number * 17) % len(changed)] ^= 1
        with pytest.raises(ValueError):
            PreparationTerminalReceiptV3.from_bytes(
                bytes(changed),
                evidence.observation.expectations,
                evidence.observation,
                evidence.acknowledgement,
            )
    elif mutation == 1:
        changed = json.loads(evidence.receipt_bytes)
        changed["resource_baseline"]["backing_free_bytes"] += 1
        encoded = json.dumps(
            changed,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        with pytest.raises(ValueError, match="digest|evidence"):
            PreparationTerminalReceiptV3.from_bytes(
                encoded,
                evidence.observation.expectations,
                evidence.observation,
                evidence.acknowledgement,
            )
    elif mutation == 2:
        projected = evidence.observation.expectations.bindings
        projected["runtime_scope_digest"] = "0" * 64
        assert evidence.observation.expectations.runtime_scope_digest != "0" * 64
        evidence.assert_canonical()
    elif mutation == 3:
        replay_expectations = build_expectations(
            attempt=2,
            nonce="b" * 32,
        )
        with pytest.raises(ValueError, match="generation"):
            PreparationTerminalReceiptV3.from_bytes(
                evidence.receipt_bytes,
                replay_expectations,
                evidence.observation,
                evidence.acknowledgement,
            )
    else:
        with pytest.raises(ValueError, match="canonical"):
            PreparationTerminalReceiptV3.from_bytes(
                evidence.receipt_bytes + b" ",
                evidence.observation.expectations,
                evidence.observation,
                evidence.acknowledgement,
            )


@pytest.mark.parametrize("case_number", range(4))
def test_four_distinct_parent_freshness_release_boundaries(
    case_number: int,
) -> None:
    now = [1_000_000_000 + case_number]
    authority, _attempts = build_authority(
        lambda: now[0],
        freshness_lease_ms=100,
    )
    authority.prepare()
    authority.open_final_readiness()

    checkpoint = case_number % 4
    if checkpoint == 0:
        now[0] += 200_000_000
        operation = authority.mark_transient_ownership_clear
    else:
        authority.mark_transient_ownership_clear()
        if checkpoint == 1:
            now[0] += 200_000_000
            operation = authority.mark_stable_sample
        else:
            authority.mark_stable_sample()
            if checkpoint == 2:
                now[0] += 200_000_000
                operation = authority.mark_stable_sample
            else:
                authority.mark_stable_sample()
                now[0] += 200_000_000
                operation = authority.mark_ready_to_release

    with pytest.raises(PreparationAuthorityError, match="stale"):
        operation()
    assert authority.state is PreparationState.REFUSED


@pytest.mark.parametrize(
    ("first_failure", "second_outcome"),
    _REACQUISITION_CASES,
)
def test_twenty_distinct_reacquisition_combinations(
    first_failure: str,
    second_outcome: str,
) -> None:
    now = 2_000_000_000
    authority, attempts = build_authority(
        lambda: now,
        attempt_outcomes=(first_failure, second_outcome),
    )

    if second_outcome == "success":
        authority.prepare()
    else:
        with pytest.raises(PreparationAuthorityError, match="failed"):
            authority.prepare()

    assert [expectations.attempt for expectations in attempts] == [1, 2]
    assert attempts[0].run_nonce != attempts[1].run_nonce
    failures = authority.snapshot().attempt_failures
    assert failures[0] == REACQUISITION_FAILURES[first_failure]
    if second_outcome == "success":
        assert authority.accepted_evidence is not None
        assert authority.accepted_evidence.observation.expectations.attempt == 2
        assert len(failures) == 1
    else:
        assert authority.accepted_evidence is None
        assert failures[1] == REACQUISITION_FAILURES["second_failure"]
        assert len(failures) == 2
    assert len(attempts) == 2


@pytest.mark.parametrize(
    "release_order",
    tuple(
        pytest.param(order, id="-".join(order))
        for order in _RELEASE_ORDERS
    ),
)
def test_twenty_four_actual_release_order_permutations(
    release_order: tuple[str, ...],
) -> None:
    now = 3_000_000_000
    authority, _attempts = build_authority(lambda: now)

    authority.prepare()
    authority.open_final_readiness()
    operations = {
        "transient": authority.mark_transient_ownership_clear,
        "stable": lambda: authority.mark_stable_samples(now, now),
        "ready": authority.mark_ready_to_release,
        "child": authority.mark_child_released,
    }

    if release_order == _VALID_RELEASE_ORDER:
        for operation_name in release_order:
            operations[operation_name]()
        assert authority.state is PreparationState.CHILD_RELEASED
    else:
        with pytest.raises(PreparationAuthorityError):
            for operation_name in release_order:
                operations[operation_name]()
        assert authority.state is PreparationState.REFUSED


def test_request_round_trip_stability_has_one_truthful_operation_kind() -> None:
    campaign = RequestRoundTripStabilityCampaign()
    for case_number in range(REQUEST_ROUND_TRIP_REPEATS):
        campaign.observe(
            case_id=f"request-round-trip-{case_number:03d}",
            operation=partial(run_request_round_trip_probe, case_number),
        )

    records = campaign.finish()

    assert len(records) == REQUEST_ROUND_TRIP_REPEATS
    assert {
        record.operation_kind for record in records
    } == {"preparation_request_round_trip"}


def test_request_round_trip_stability_rejects_duplicates_and_incomplete_runs() -> None:
    campaign = RequestRoundTripStabilityCampaign()
    campaign.observe(
        case_id="request-round-trip-000",
        operation=lambda: run_request_round_trip_probe(0),
    )

    with pytest.raises(ValueError, match="duplicate"):
        campaign.observe(
            case_id="request-round-trip-000",
            operation=lambda: run_request_round_trip_probe(0),
        )
    with pytest.raises(ValueError, match="incomplete"):
        campaign.finish()
