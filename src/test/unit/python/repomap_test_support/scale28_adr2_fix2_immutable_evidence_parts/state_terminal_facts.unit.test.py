"""State integrity and parent terminal facts validation unit tests."""

from __future__ import annotations

import pytest

from repomap_test_support.scale28_adr2_accepted_evidence import (
    ParentObservedTerminalFacts,
    validate_parent_terminal_facts,
)
from repomap_test_support.scale28_adr2_model_fixtures import (
    FRAME_RECEIVED_NS,
    fixture_accepted_protocol_state,
)

def test_state_rejects_adversarial_retained_receipt_mutation_before_use() -> None:
    state = fixture_accepted_protocol_state()
    receipt = state.accepted_receipt
    assert receipt is not None
    object.__setattr__(receipt.subordinate_cleanup, "open_readers", 1)

    with pytest.raises(ValueError, match="canonical|cleanup"):
        state.validate_checkpoint(
            "process_tree_settlement",
            parent_now_ns=FRAME_RECEIVED_NS + 300_000_000,
        )
    assert state.refused is True


def test_state_rejects_duplicate_receipt_without_mutable_digest_history() -> None:
    state = fixture_accepted_protocol_state()
    receipt = state.accepted_receipt
    assert receipt is not None

    with pytest.raises(ValueError, match="preparation receipt is duplicate"):
        state.accept_terminal_receipt(
            receipt.to_bytes(),
            parent_received_ns=FRAME_RECEIVED_NS + 300_000_000,
        )
    assert state.refused is True


def test_refused_generation_discards_all_accepted_evidence_and_origin() -> None:
    state = fixture_accepted_protocol_state()

    with pytest.raises(ValueError, match="preparation evidence is stale"):
        state.validate_checkpoint(
            "process_tree_settlement",
            parent_now_ns=FRAME_RECEIVED_NS + 2_000_000_000,
        )

    assert state.refused is True
    assert state.accepted_frame is None
    assert state.accepted_acknowledgement is None
    assert state.accepted_receipt is None
    assert state.accepted_evidence is None
    assert state.observation_frame_received_parent_ns is None
    assert state.completed_checkpoints == ()
    assert state.checkpoint_parent_times_ns == ()


def test_state_rejects_retained_canonical_byte_corruption_before_use() -> None:
    state = fixture_accepted_protocol_state()
    frame = state.accepted_frame
    assert frame is not None
    object.__setattr__(frame, "_canonical_bytes", frame.to_bytes() + b" ")

    with pytest.raises(ValueError, match="canonical|malformed"):
        state.validate_checkpoint(
            "process_tree_settlement",
            parent_now_ns=FRAME_RECEIVED_NS + 300_000_000,
        )
    assert state.refused is True


def test_receipt_v3_excludes_parent_owned_terminal_facts() -> None:
    state = fixture_accepted_protocol_state()
    receipt = state.accepted_receipt
    assert receipt is not None
    projection = receipt.to_mapping()

    assert projection["completion_state"] == "ready_to_exit"
    assert projection["expected_disposition"] == {
        "state": "normal_zero_exit_after_receipt_transmission",
        "exit_code": 0,
        "signal": None,
    }
    subordinate_cleanup = projection["subordinate_cleanup"]
    assert isinstance(subordinate_cleanup, dict)
    assert subordinate_cleanup["result_channel_excluded"] is True
    assert (
        subordinate_cleanup["result_channel_state"]
        == "open_for_terminal_receipt"
    )
    for parent_owned_field in (
        "worker_terminal",
        "actual_exit_code",
        "actual_signal",
        "process_tree_settled",
        "actual_descriptor_count",
    ):
        assert parent_owned_field not in projection


def _terminal_facts(
    *,
    exit_code: int = 0,
    signal: str | None = None,
    process_tree_settled: bool = True,
    active_observers: int = 1,
    descendants: int = 0,
    worker_connections: int = 0,
    readers: int = 0,
    threads: int = 0,
    descriptors_and_channels: int = 0,
) -> ParentObservedTerminalFacts:
    return ParentObservedTerminalFacts(
        exit_code=exit_code,
        signal=signal,
        process_tree_settled=process_tree_settled,
        active_observers=active_observers,
        descendants=descendants,
        worker_connections=worker_connections,
        readers=readers,
        threads=threads,
        descriptors_and_channels=descriptors_and_channels,
    )


def test_parent_independently_validates_actual_terminal_facts() -> None:
    receipt = fixture_accepted_protocol_state().accepted_receipt
    assert receipt is not None

    validate_parent_terminal_facts(receipt, _terminal_facts())
    for mutated in (
        _terminal_facts(exit_code=1),
        _terminal_facts(signal="SIGTERM", exit_code=0),
        _terminal_facts(process_tree_settled=False),
        _terminal_facts(active_observers=0),
        _terminal_facts(active_observers=2),
        _terminal_facts(descendants=1),
        _terminal_facts(worker_connections=1),
        _terminal_facts(readers=1),
        _terminal_facts(threads=1),
        _terminal_facts(descriptors_and_channels=1),
    ):
        with pytest.raises(ValueError, match="terminal facts are invalid"):
            validate_parent_terminal_facts(receipt, mutated)


def test_parent_terminal_validation_rejects_mutated_receipt_disposition() -> None:
    receipt = fixture_accepted_protocol_state().accepted_receipt
    assert receipt is not None
    object.__setattr__(receipt.expected_disposition, "exit_code", 1)

    with pytest.raises(ValueError, match="canonical|disposition"):
        validate_parent_terminal_facts(receipt, _terminal_facts(exit_code=1))
