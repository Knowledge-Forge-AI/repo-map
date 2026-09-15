from __future__ import annotations

import pytest

from repomap_test_support.scale28_adr2_accepted_evidence import (
    AcceptedPreparationEvidence,
)
from repomap_test_support.scale28_adr2_frame_model import (
    ObservationExpectations,
    encode_observation_frame,
    validate_observation_frame,
)
from repomap_test_support.scale28_adr2_freshness_model import (
    ParentFreshnessAuthority,
    PreparationProtocolAuthority,
    PreparationProtocolState,
)
from repomap_test_support.scale28_adr2_model_fixtures import (
    FRAME_RECEIVED_NS,
    fixture_accepted_protocol_state,
    fixture_bindings,
    fixture_frame_payload,
    fixture_receipt_expectations,
    fixture_receipt_payload,
    fixture_observation_expectations,
)
from repomap_test_support.scale28_adr2_receipt_model import (
    encode_receipt,
    validate_preparation_receipt,
)


def _assert_discarded(state: PreparationProtocolState) -> None:
    assert state.refused is True
    assert state.accepted_frame is None
    assert state.accepted_acknowledgement is None
    assert state.accepted_receipt is None
    assert state.accepted_evidence is None
    assert state.observation_frame_received_parent_ns is None
    assert state.completed_checkpoints == ()
    assert state.checkpoint_parent_times_ns == ()


def test_public_retained_authority_validation_fails_closed() -> None:
    state = fixture_accepted_protocol_state()
    frame = state.accepted_frame
    assert frame is not None
    object.__setattr__(frame, "_canonical_bytes", frame.to_bytes() + b" ")

    with pytest.raises(ValueError, match="canonical|malformed"):
        state.validate_retained_authority()

    _assert_discarded(state)


def test_coherent_parent_freshness_authority_substitution_is_rejected() -> None:
    state = fixture_accepted_protocol_state()
    replacement = ParentFreshnessAuthority(
        FRAME_RECEIVED_NS + 1_000_000_000,
        1_450,
    )

    with pytest.raises(AttributeError, match="read-only"):
        state._parent_freshness_authority = replacement
    object.__setattr__(state, "_parent_freshness_authority", replacement)

    with pytest.raises(ValueError, match="freshness authority was substituted"):
        state.validate_checkpoint(
            "process_tree_settlement",
            parent_now_ns=FRAME_RECEIVED_NS + 1_500_000_000,
        )

    _assert_discarded(state)


def test_coherent_construction_authority_substitution_is_rejected() -> None:
    state = PreparationProtocolState(fixture_observation_expectations(), 1_450)
    foreign = PreparationProtocolAuthority(
        ObservationExpectations("b" * 32, 1, fixture_bindings()),
        1_450,
    )

    with pytest.raises(AttributeError, match="read-only"):
        setattr(state, "_authority", foreign)
    object.__setattr__(state, "_authority", foreign)

    with pytest.raises(ValueError, match="protocol authority was substituted"):
        state.validate_retained_authority()

    _assert_discarded(state)


def test_coherent_accepted_evidence_substitution_is_rejected() -> None:
    state = fixture_accepted_protocol_state()
    frame = state.accepted_frame
    acknowledgement = state.accepted_acknowledgement
    assert frame is not None
    assert acknowledgement is not None
    expectations = fixture_receipt_expectations(frame, acknowledgement)
    foreign_receipt = validate_preparation_receipt(
        encode_receipt(
            fixture_receipt_payload(
                frame=frame,
                acknowledgement=acknowledgement,
                result_completed_ns=31,
            )
        ),
        expectations,
    )
    foreign_evidence = AcceptedPreparationEvidence.from_values(
        expectations,
        foreign_receipt,
    )

    object.__setattr__(state, "_accepted_evidence", foreign_evidence)

    with pytest.raises(ValueError, match="evidence was substituted"):
        state.validate_retained_authority()

    _assert_discarded(state)


def test_coherent_accepted_frame_substitution_is_rejected_before_ack() -> None:
    expectations = fixture_observation_expectations()
    state = PreparationProtocolState(expectations, 1_450)
    original = encode_observation_frame(fixture_frame_payload())
    state.accept_observation_frame(
        original,
        parent_received_ns=FRAME_RECEIVED_NS,
    )
    foreign = validate_observation_frame(
        encode_observation_frame(fixture_frame_payload(completed_ns=21)),
        expectations,
    )

    object.__setattr__(state, "_accepted_frame", foreign)

    with pytest.raises(ValueError, match="frame was substituted"):
        state.validate_retained_authority()

    _assert_discarded(state)
