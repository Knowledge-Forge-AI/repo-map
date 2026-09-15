from __future__ import annotations

import pytest

from repomap_test_support.scale28_adr2_frame_model import (
    OBSERVATION_TRANSFER_RESERVE_NS,
    encode_observation_frame,
)
from repomap_test_support.scale28_adr2_freshness_model import (
    ParentFreshnessAuthority,
    PreparationProtocolState,
)
from repomap_test_support.scale28_adr2_immutable_values import MAX_SIGNED_INT
from repomap_test_support.scale28_adr2_model_fixtures import (
    FRAME_RECEIVED_NS,
    FRESHNESS_LEASE_MS,
    STALE_PARENT_NOW_NS,
    fixture_accepted_protocol_state,
    fixture_frame_and_acknowledgement,
    fixture_frame_payload,
    fixture_observation_expectations,
    fixture_receipt_payload,
)
from repomap_test_support.scale28_adr2_receipt_model import (
    encode_receipt,
)


def test_delayed_result_created_four_seconds_after_observation_is_stale() -> None:
    frame, acknowledgement, _, _ = fixture_frame_and_acknowledgement()
    receipt = encode_receipt(
        fixture_receipt_payload(
            frame=frame,
            acknowledgement=acknowledgement,
            result_completed_ns=4_000_000_020,
        )
    )
    state = PreparationProtocolState(fixture_observation_expectations(), FRESHNESS_LEASE_MS)
    state.accept_observation_frame(
        encode_observation_frame(fixture_frame_payload()),
        parent_received_ns=FRAME_RECEIVED_NS,
    )
    state.accept_observation_acknowledgement(fixture_frame_and_acknowledgement()[3])

    with pytest.raises(ValueError, match="preparation evidence is stale"):
        state.accept_terminal_receipt(
            receipt,
            parent_received_ns=FRAME_RECEIVED_NS + 4_000_000_000,
        )
    assert state.refused is True


def test_worker_local_lag_just_inside_parent_bound_is_accepted() -> None:
    frame, acknowledgement, _, _ = fixture_frame_and_acknowledgement()
    receipt = encode_receipt(
        fixture_receipt_payload(
            frame=frame,
            acknowledgement=acknowledgement,
            result_completed_ns=410_000_020,
        )
    )
    state = PreparationProtocolState(fixture_observation_expectations(), FRESHNESS_LEASE_MS)
    state.accept_observation_frame(
        encode_observation_frame(fixture_frame_payload()),
        parent_received_ns=FRAME_RECEIVED_NS,
    )
    state.accept_observation_acknowledgement(fixture_frame_and_acknowledgement()[3])

    accepted = state.accept_terminal_receipt(
        receipt,
        parent_received_ns=STALE_PARENT_NOW_NS - 1,
    )
    assert accepted["category"] == "complete"


@pytest.mark.parametrize("gap", ("result_creation", "result_encoding", "pipe_write"))
def test_worker_lag_or_transfer_gap_cannot_underestimate_age(gap: str) -> None:
    frame, acknowledgement, _, _ = fixture_frame_and_acknowledgement()
    receipt = encode_receipt(
        fixture_receipt_payload(
            frame=frame,
            acknowledgement=acknowledgement,
            result_completed_ns=410_000_020,
        )
    )
    state = PreparationProtocolState(fixture_observation_expectations(), FRESHNESS_LEASE_MS)
    state.accept_observation_frame(
        encode_observation_frame(fixture_frame_payload()),
        parent_received_ns=FRAME_RECEIVED_NS,
    )
    state.accept_observation_acknowledgement(fixture_frame_and_acknowledgement()[3])

    with pytest.raises(ValueError, match="preparation evidence is stale"):
        state.accept_terminal_receipt(receipt, parent_received_ns=STALE_PARENT_NOW_NS)
    assert gap in {"result_creation", "result_encoding", "pipe_write"}


def test_parent_origin_uses_only_parent_monotonic_time_and_transfer_reserve() -> None:
    authority = ParentFreshnessAuthority(FRAME_RECEIVED_NS, FRESHNESS_LEASE_MS)

    assert authority.conservative_origin_ns() == (
        FRAME_RECEIVED_NS - OBSERVATION_TRANSFER_RESERVE_NS
    )
    assert authority.validate_age_ns(FRAME_RECEIVED_NS) == (
        OBSERVATION_TRANSFER_RESERVE_NS
    )
    with pytest.raises(ValueError, match="stale"):
        authority.validate_age_ns(STALE_PARENT_NOW_NS)
    with pytest.raises(ValueError, match="underflows"):
        ParentFreshnessAuthority(1, FRESHNESS_LEASE_MS).conservative_origin_ns()
    with pytest.raises(ValueError, match="clock is invalid"):
        authority.validate_age_ns(1)


def test_stale_before_sample_one_is_rejected() -> None:
    state = fixture_accepted_protocol_state()
    state.validate_checkpoint(
        "process_tree_settlement",
        parent_now_ns=FRAME_RECEIVED_NS + 300_000_000,
    )

    with pytest.raises(ValueError, match="stale"):
        state.validate_checkpoint(
            "before_stable_sample_one",
            parent_now_ns=STALE_PARENT_NOW_NS,
        )


def test_fresh_at_sample_one_but_stale_before_sample_two_is_rejected() -> None:
    state = fixture_accepted_protocol_state()
    state.validate_checkpoint(
        "process_tree_settlement",
        parent_now_ns=FRAME_RECEIVED_NS + 300_000_000,
    )
    state.validate_checkpoint(
        "before_stable_sample_one",
        parent_now_ns=STALE_PARENT_NOW_NS - 1,
    )

    with pytest.raises(ValueError, match="stale"):
        state.validate_checkpoint(
            "before_stable_sample_two",
            parent_now_ns=STALE_PARENT_NOW_NS,
        )


def test_fresh_at_sample_two_but_stale_immediately_before_release_is_rejected() -> None:
    state = fixture_accepted_protocol_state()
    for checkpoint in (
        "process_tree_settlement",
        "before_stable_sample_one",
        "before_stable_sample_two",
    ):
        state.validate_checkpoint(checkpoint, parent_now_ns=STALE_PARENT_NOW_NS - 1)

    with pytest.raises(ValueError, match="stale"):
        state.validate_checkpoint(
            "immediately_before_release",
            parent_now_ns=STALE_PARENT_NOW_NS,
        )


def test_sample_two_and_release_checks_cannot_be_reordered() -> None:
    state = fixture_accepted_protocol_state()
    state.validate_checkpoint(
        "process_tree_settlement",
        parent_now_ns=FRAME_RECEIVED_NS + 300_000_000,
    )

    with pytest.raises(ValueError, match="checkpoint order"):
        state.validate_checkpoint(
            "before_stable_sample_two",
            parent_now_ns=FRAME_RECEIVED_NS + 400_000_000,
        )


def test_parent_checkpoint_clock_cannot_move_backward() -> None:
    state = fixture_accepted_protocol_state()

    with pytest.raises(ValueError, match="parent freshness clock is invalid"):
        state.validate_checkpoint(
            "process_tree_settlement",
            parent_now_ns=FRAME_RECEIVED_NS + 100_000_000,
        )
    assert state.refused is True


@pytest.mark.parametrize("invalid_now", (-1, True, MAX_SIGNED_INT + 1))
def test_invalid_checkpoint_timestamp_refuses_and_discards_authority(
    invalid_now: int,
) -> None:
    state = fixture_accepted_protocol_state()

    with pytest.raises(ValueError, match="protocol numeric value is invalid"):
        state.validate_checkpoint(
            "process_tree_settlement",
            parent_now_ns=invalid_now,
        )

    assert state.refused is True
    assert state.accepted_frame is None
    assert state.accepted_acknowledgement is None
    assert state.accepted_receipt is None
    assert state.accepted_evidence is None
    assert state.observation_frame_received_parent_ns is None
    assert state.completed_checkpoints == ()
    assert state.checkpoint_parent_times_ns == ()


def test_refusal_flag_is_read_only() -> None:
    state = fixture_accepted_protocol_state()

    with pytest.raises(AttributeError):
        setattr(state, 'refused', False)


def test_external_transport_refusal_discards_the_complete_generation() -> None:
    state = fixture_accepted_protocol_state()

    state.refuse_external_transport_failure()

    assert state.refused is True
    assert state.accepted_frame is None
    assert state.accepted_acknowledgement is None
    assert state.accepted_receipt is None
    assert state.accepted_evidence is None
    assert state.observation_frame_received_parent_ns is None
    assert state.completed_checkpoints == ()
    assert state.checkpoint_parent_times_ns == ()
