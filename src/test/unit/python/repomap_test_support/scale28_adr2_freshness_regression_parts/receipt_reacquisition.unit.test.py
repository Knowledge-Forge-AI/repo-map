"""Receipt lifecycle and reacquisition freshness regression tests."""

from __future__ import annotations

from dataclasses import replace

import pytest

from repomap_test_support.scale28_adr2_frame_model import (
    OBSERVATION_TRANSFER_RESERVE_NS,
    encode_observation_acknowledgement,
    encode_observation_frame,
)
from repomap_test_support.scale28_adr2_freshness_model import (
    AttemptGeneration,
    PreparationProtocolState,
    validate_reacquisition,
)
from repomap_test_support.scale28_adr2_model_fixtures import (
    FRAME_RECEIVED_NS,
    FRESHNESS_LEASE_MS,
    fixture_digest,
    fixture_frame_and_acknowledgement,
    fixture_frame_payload,
    fixture_observation_expectations,
    fixture_receipt_expectations,
    fixture_receipt_payload,
    fixture_resource_baseline,
)
from repomap_test_support.scale28_adr2_receipt_model import (
    encode_receipt,
    validate_preparation_receipt,
)

def test_changed_resource_baseline_after_frame_is_rejected() -> None:
    frame, acknowledgement, _, _ = fixture_frame_and_acknowledgement()
    changed = fixture_resource_baseline(backing_free_bytes=3_999_999_999)
    receipt = encode_receipt(
        fixture_receipt_payload(
            frame=frame,
            acknowledgement=acknowledgement,
            baseline=changed,
        )
    )

    with pytest.raises(ValueError, match="receipt baseline is invalid"):
        validate_preparation_receipt(
            receipt,
            fixture_receipt_expectations(frame, acknowledgement),
        )


def test_terminal_receipt_observation_must_equal_completion_event() -> None:
    frame, acknowledgement, _, _ = fixture_frame_and_acknowledgement()
    payload = fixture_receipt_payload(frame=frame, acknowledgement=acknowledgement)
    payload["observation_completed_ns"] = 21
    receipt = encode_receipt(payload)

    with pytest.raises(ValueError, match="receipt observation is invalid"):
        validate_preparation_receipt(
            receipt,
            fixture_receipt_expectations(frame, acknowledgement),
        )


@pytest.mark.parametrize("field", ("run_nonce", "attempt", "runtime_scope_digest"))
def test_terminal_receipt_rejects_wrong_run_attempt_scope_or_generation(
    field: str,
) -> None:
    frame, acknowledgement, _, _ = fixture_frame_and_acknowledgement()
    payload = fixture_receipt_payload(frame=frame, acknowledgement=acknowledgement)
    payload[field] = "b" * 32 if field == "run_nonce" else 2
    if field == "runtime_scope_digest":
        payload[field] = "b" * 64
    receipt = encode_receipt(payload)

    with pytest.raises(ValueError):
        validate_preparation_receipt(
            receipt,
            fixture_receipt_expectations(frame, acknowledgement),
        )


def test_missing_duplicate_changed_and_late_completion_events_are_rejected() -> None:
    frame, _, frame_bytes, _ = fixture_frame_and_acknowledgement()
    receipt = encode_receipt(fixture_receipt_payload())
    missing = PreparationProtocolState(fixture_observation_expectations(), FRESHNESS_LEASE_MS)
    with pytest.raises(ValueError, match="observation frame is missing"):
        missing.accept_terminal_receipt(receipt, parent_received_ns=FRAME_RECEIVED_NS)
    with pytest.raises(ValueError, match="attempt is refused"):
        missing.accept_observation_frame(
            frame_bytes,
            parent_received_ns=FRAME_RECEIVED_NS,
        )

    for duplicate in (
        frame_bytes,
        encode_observation_frame(fixture_frame_payload(completed_ns=21)),
    ):
        state = PreparationProtocolState(fixture_observation_expectations(), FRESHNESS_LEASE_MS)
        state.accept_observation_frame(
            frame_bytes,
            parent_received_ns=FRAME_RECEIVED_NS,
        )
        with pytest.raises(ValueError, match="observation frame is duplicate"):
            state.accept_observation_frame(
                duplicate,
                parent_received_ns=FRAME_RECEIVED_NS + 1,
            )
    assert frame["frame_sequence"] == 1


def test_missing_wrong_duplicate_and_timed_out_acknowledgements_are_rejected() -> None:
    frame, _, frame_bytes, ack_bytes = fixture_frame_and_acknowledgement()
    receipt = encode_receipt(fixture_receipt_payload())
    missing = PreparationProtocolState(fixture_observation_expectations(), FRESHNESS_LEASE_MS)
    missing.accept_observation_frame(frame_bytes, parent_received_ns=FRAME_RECEIVED_NS)
    with pytest.raises(ValueError, match="acknowledgement is missing"):
        missing.accept_terminal_receipt(receipt, parent_received_ns=FRAME_RECEIVED_NS)

    wrong_payload = {
        "schema_version": 1,
        "ack_kind": "startup_preparation_observation_ack",
        "run_nonce": "a" * 32,
        "attempt": 1,
        "frame_sequence": 1,
        "observation_frame_digest": "0" * 64,
        "category": "accepted",
    }
    wrong = PreparationProtocolState(fixture_observation_expectations(), FRESHNESS_LEASE_MS)
    wrong.accept_observation_frame(frame_bytes, parent_received_ns=FRAME_RECEIVED_NS)
    with pytest.raises(ValueError, match="acknowledgement frame is invalid"):
        wrong.accept_observation_acknowledgement(
            encode_observation_acknowledgement(wrong_payload)
        )

    duplicate = PreparationProtocolState(fixture_observation_expectations(), FRESHNESS_LEASE_MS)
    duplicate.accept_observation_frame(frame_bytes, parent_received_ns=FRAME_RECEIVED_NS)
    duplicate.accept_observation_acknowledgement(ack_bytes)
    with pytest.raises(ValueError, match="acknowledgement is duplicate"):
        duplicate.accept_observation_acknowledgement(ack_bytes)

    payload = fixture_receipt_payload(frame=frame)
    completed_ns = frame["observation_completed_ns"]
    assert isinstance(completed_ns, int)
    payload["observation_acknowledged_ns"] = (
        completed_ns + OBSERVATION_TRANSFER_RESERVE_NS + 1
    )
    payload["result_completed_ns"] = payload["observation_acknowledged_ns"]
    with pytest.raises(ValueError, match="acknowledgement timed out"):
        encode_receipt(payload)


def test_version_one_receipt_is_superseded_and_rejected() -> None:
    payload = fixture_receipt_payload()
    payload["schema_version"] = 1

    with pytest.raises(ValueError, match="schema is unsupported"):
        encode_receipt(payload)


def _generation(prefix: str, attempt: int) -> AttemptGeneration:
    return AttemptGeneration(
        run_nonce=("a" if attempt == 1 else "b") * 32,
        attempt=attempt,
        worker_identity_digest=fixture_digest(f"{prefix}:worker"),
        frame_sequence_generation_digest=fixture_digest(f"{prefix}:sequence"),
        resource_baseline_digest=fixture_digest(f"{prefix}:baseline"),
        observation_frame_digest=fixture_digest(f"{prefix}:frame"),
        observation_ack_digest=fixture_digest(f"{prefix}:ack"),
        receipt_digest=fixture_digest(f"{prefix}:receipt"),
        parent_observation_timestamp_ns=attempt,
        state_machine_generation_digest=fixture_digest(f"{prefix}:state"),
    )


def test_reacquisition_requires_new_generation_for_every_evidence_identity() -> None:
    first = _generation("first", 1)
    second = _generation("second", 2)
    validate_reacquisition(first, second)

    for field in (
        "run_nonce",
        "worker_identity_digest",
        "frame_sequence_generation_digest",
        "resource_baseline_digest",
        "observation_frame_digest",
        "observation_ack_digest",
        "receipt_digest",
        "parent_observation_timestamp_ns",
        "state_machine_generation_digest",
    ):
        reused = replace(second, **{field: getattr(first, field)})
        with pytest.raises(ValueError, match="reused preparation evidence"):
            validate_reacquisition(first, reused)

    with pytest.raises(ValueError, match="run nonce is invalid"):
        validate_reacquisition(first, replace(second, run_nonce="G" * 32))
    with pytest.raises(ValueError, match="digest is invalid"):
        validate_reacquisition(
            first,
            replace(second, observation_ack_digest="0" * 63),
        )
