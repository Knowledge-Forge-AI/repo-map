from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from repomap_test_support.scale28_adr2_frame_model import (
    ObservationExpectations,
    encode_observation_acknowledgement,
    encode_observation_frame,
    resource_baseline_digest,
    validate_observation_acknowledgement,
    validate_observation_frame,
)
from repomap_test_support.scale28_adr2_freshness_model import (
    PreparationProtocolState,
)
from repomap_test_support.scale28_adr2_model_fixtures import (
    FRAME_RECEIVED_NS,
    fixture_accepted_protocol_state,
    fixture_bindings,
    fixture_frame_and_acknowledgement,
    fixture_observation_expectations,
    fixture_receipt_expectations,
    fixture_receipt_payload,
    fixture_resource_baseline,
)
from repomap_test_support.scale28_adr2_receipt_model import (
    encode_receipt,
    validate_preparation_receipt,
)
from repomap_test_support.scale28_adr2_accepted_evidence import (
    AcceptedPreparationEvidence,
)
from repomap_test_support.scale28_adr2_bounded_ipc import BoundedIpcMessage


def test_attempt_expectations_copy_every_caller_owned_binding() -> None:
    bindings = fixture_bindings()
    expectations = ObservationExpectations("a" * 32, 1, bindings)

    for field_name in tuple(bindings):
        bindings[field_name] = "f" * 64

    assert expectations.bindings == fixture_bindings()
    projection = expectations.bindings
    projection["runtime_scope_digest"] = "0" * 64
    assert expectations.runtime_scope_digest == fixture_bindings()[
        "runtime_scope_digest"
    ]
    with pytest.raises(FrozenInstanceError):
        setattr(expectations, 'run_nonce', 'b' * 32)
    with pytest.raises(FrozenInstanceError):
        setattr(expectations, 'attempt', 2)


def test_frame_and_ack_encoding_do_not_retain_caller_mappings() -> None:
    frame_payload = fixture_frame_and_acknowledgement()[0].to_mapping()
    frame_payload.pop("frame_digest")
    frame_bytes = encode_observation_frame(frame_payload)
    frame_payload.clear()

    frame, acknowledgement, _, _ = fixture_frame_and_acknowledgement()
    ack_payload = acknowledgement.to_mapping()
    ack_payload.pop("ack_digest")
    acknowledgement_bytes = encode_observation_acknowledgement(ack_payload)
    ack_payload["observation_frame_digest"] = "f" * 64

    assert frame_bytes == frame.to_bytes()
    assert acknowledgement_bytes == acknowledgement.to_bytes()


def test_accepted_frame_and_acknowledgement_are_frozen_exact_values() -> None:
    frame, acknowledgement, frame_bytes, acknowledgement_bytes = (
        fixture_frame_and_acknowledgement()
    )

    with pytest.raises(FrozenInstanceError):
        setattr(frame, 'resource_baseline_digest', 'f' * 64)
    with pytest.raises(FrozenInstanceError):
        setattr(acknowledgement, 'ack_digest', 'f' * 64)

    assert frame.to_bytes() == frame_bytes
    assert acknowledgement.to_bytes() == acknowledgement_bytes
    frame_projection = frame.to_mapping()
    acknowledgement_projection = acknowledgement.to_mapping()
    frame_projection["resource_baseline_digest"] = "f" * 64
    acknowledgement_projection["ack_digest"] = "f" * 64
    frame.assert_canonical(fixture_observation_expectations())
    acknowledgement.assert_canonical(
        fixture_observation_expectations(),
        frame,
    )


def test_receipt_expectations_reject_adversarial_frame_substitution() -> None:
    frame, acknowledgement, _, _ = fixture_frame_and_acknowledgement()
    changed_baseline = fixture_resource_baseline()
    free_bytes = changed_baseline["backing_free_bytes"]
    assert isinstance(free_bytes, int)
    changed_baseline["backing_free_bytes"] = free_bytes - 1
    object.__setattr__(
        frame,
        "resource_baseline_digest",
        resource_baseline_digest(changed_baseline),
    )

    with pytest.raises(ValueError, match="canonical|frame"):
        fixture_receipt_expectations(frame, acknowledgement)


def test_receipt_expectations_reject_adversarial_ack_substitution() -> None:
    frame, acknowledgement, _, _ = fixture_frame_and_acknowledgement()
    object.__setattr__(acknowledgement, "ack_digest", "f" * 64)

    with pytest.raises(ValueError, match="canonical|digest"):
        fixture_receipt_expectations(frame, acknowledgement)


def test_accepted_evidence_rejects_receipt_from_another_attempt() -> None:
    frame, acknowledgement, _, _ = fixture_frame_and_acknowledgement()
    current = fixture_receipt_expectations(frame, acknowledgement)
    foreign = fixture_observation_expectations(
        run_nonce="b" * 32,
        attempt=2,
        bindings=fixture_bindings("foreign"),
    )
    baseline = fixture_resource_baseline()
    foreign_frame_payload = {
        "schema_version": 1,
        "frame_kind": "startup_preparation_observation",
        **foreign.to_mapping(),
        "resource_baseline_digest": resource_baseline_digest(baseline),
        "observation_started_ns": 10,
        "observation_completed_ns": 20,
        "frame_sequence": 1,
    }
    foreign_frame = validate_observation_frame(
        encode_observation_frame(foreign_frame_payload),
        foreign,
    )
    foreign_acknowledgement = validate_observation_acknowledgement(
        encode_observation_acknowledgement(
            {
                "schema_version": 1,
                "ack_kind": "startup_preparation_observation_ack",
                "run_nonce": foreign.run_nonce,
                "attempt": foreign.attempt,
                "frame_sequence": 1,
                "observation_frame_digest": foreign_frame.frame_digest,
                "category": "accepted",
            }
        ),
        foreign,
        accepted_frame=foreign_frame,
    )
    foreign_payload = fixture_receipt_payload(
        frame=foreign_frame,
        acknowledgement=foreign_acknowledgement,
        baseline=baseline,
    )
    foreign_payload.update(foreign.to_mapping())
    foreign_receipt = validate_preparation_receipt(
        encode_receipt(foreign_payload),
        type(current)(
            foreign,
            foreign_frame,
            foreign_acknowledgement,
        ),
    )

    with pytest.raises(ValueError, match="preparation receipt run is invalid"):
        AcceptedPreparationEvidence.from_values(current, foreign_receipt)


def test_receipt_copies_nested_baseline_and_returns_detached_projection() -> None:
    frame, acknowledgement, _, _ = fixture_frame_and_acknowledgement()
    baseline = fixture_resource_baseline()
    encoded = encode_receipt(
        fixture_receipt_payload(
            frame=frame,
            acknowledgement=acknowledgement,
            baseline=baseline,
        )
    )
    receipt = validate_preparation_receipt(
        encoded,
        fixture_receipt_expectations(frame, acknowledgement),
    )

    baseline["backing_free_bytes"] = 1
    projection = receipt.to_mapping()
    projection_baseline = projection["resource_baseline"]
    assert isinstance(projection_baseline, dict)
    projection_baseline["backing_free_bytes"] = 2
    projection_cleanup = projection["subordinate_cleanup"]
    assert isinstance(projection_cleanup, dict)
    projection_cleanup["open_readers"] = 1

    assert receipt.resource_baseline.backing_free_bytes == 4_000_000_000
    assert receipt.subordinate_cleanup.open_readers == 0
    assert receipt.to_bytes() == encoded
    receipt.assert_canonical()


def test_state_exposes_only_frozen_values_and_detached_projections() -> None:
    frame, _, frame_bytes, _ = fixture_frame_and_acknowledgement()
    state = PreparationProtocolState(fixture_observation_expectations(), 1_450)
    returned = state.accept_observation_frame(
        frame_bytes,
        parent_received_ns=FRAME_RECEIVED_NS,
    )

    with pytest.raises(FrozenInstanceError):
        setattr(returned, 'resource_baseline_digest', 'f' * 64)
    returned_projection = returned.to_mapping()
    returned_projection["resource_baseline_digest"] = "f" * 64

    assert state.accepted_frame == frame
    state.validate_retained_authority()


def test_raw_canonical_and_transport_bytes_are_excluded_from_repr() -> None:
    state = fixture_accepted_protocol_state()
    evidence = state.accepted_evidence
    assert evidence is not None
    evidence_repr = repr(evidence)
    for raw_bytes in (
        evidence.observation_bytes,
        evidence.acknowledgement_bytes,
        evidence.resource_baseline_bytes,
        evidence.receipt_bytes,
    ):
        assert repr(raw_bytes) not in evidence_repr

    state_repr = repr(state)
    assert repr(state._authority_bytes) not in state_repr
    assert state._accepted_frame_bytes is not None
    assert repr(state._accepted_frame_bytes) not in state_repr
    assert state._accepted_acknowledgement_bytes is not None
    assert repr(state._accepted_acknowledgement_bytes) not in state_repr
    assert state._accepted_evidence_bytes is not None
    assert repr(state._accepted_evidence_bytes) not in state_repr
    assert state._parent_freshness_authority_bytes is not None
    assert repr(state._parent_freshness_authority_bytes) not in state_repr

    message = BoundedIpcMessage("observation_frame", b"private-payload", 15)
    assert "private-payload" not in repr(message)


def test_freshness_lease_and_parent_origin_are_immutable_authority() -> None:
    state = PreparationProtocolState(fixture_observation_expectations(), 1_450)
    with pytest.raises(AttributeError):
        setattr(state, 'freshness_lease_ms', 10000)

    _, _, frame_bytes, _ = fixture_frame_and_acknowledgement()
    state.accept_observation_frame(
        frame_bytes,
        parent_received_ns=FRAME_RECEIVED_NS,
    )
    authority = state._parent_freshness_authority
    assert authority is not None
    object.__setattr__(
        authority,
        "observation_frame_received_parent_ns",
        FRAME_RECEIVED_NS + 1_000_000_000,
    )
    with pytest.raises(ValueError, match="parent freshness authority changed"):
        state.validate_retained_authority()
    assert state.refused is True
    assert state.accepted_frame is None
    assert state.observation_frame_received_parent_ns is None
