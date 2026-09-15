"""Public-safe fixtures for SCALE28-ADR2-FIX1 unit models."""

from __future__ import annotations

import hashlib

from .scale28_adr2_frame_model import (
    ObservationExpectations,
    PreparationObservation,
    PreparationObservationAcknowledgement,
    encode_observation_acknowledgement,
    encode_observation_frame,
    resource_baseline_digest,
    validate_observation_acknowledgement,
    validate_observation_frame,
)
from .scale28_adr2_freshness_model import PreparationProtocolState
from .scale28_adr2_receipt_model import ReceiptExpectations, encode_receipt


FRAME_RECEIVED_NS = 2_000_000_000
FRESHNESS_LEASE_MS = 1_450
STALE_PARENT_NOW_NS = (
    FRAME_RECEIVED_NS + (FRESHNESS_LEASE_MS - 100) * 1_000_000
)


def fixture_digest(label: str) -> str:
    """Return one deterministic public-safe fixture digest."""

    return hashlib.sha256(label.encode("ascii")).hexdigest()


def fixture_bindings(prefix: str = "current") -> dict[str, str]:
    """Return exact scope and generation fixture bindings."""

    return {
        field: fixture_digest(f"{prefix}:{field}")
        for field in (
            "runtime_scope_digest",
            "topology_digest",
            "pgdata_generation_digest",
            "configuration_generation_digest",
            "observer_generation_digest",
        )
    }


def fixture_resource_baseline(
    *,
    backing_free_bytes: int = 4_000_000_000,
) -> dict[str, object]:
    """Return one complete one-baseline-freeze resource fixture."""

    return {
        "schema_version": 1,
        "client_peak_rss_bytes": 64_000_000,
        "postgresql_container_rss_upper_bound": 96_000_000,
        "temporary_byte_upper_bound_delta": 0,
        "wal_upper_bound_delta": 4_096,
        "allocated_delta_bytes": 8_192,
        "backing_free_bytes": backing_free_bytes,
        "pgdata_reader_elapsed_ns": 1_000_000,
        "availability": "available",
    }


def fixture_observation_expectations(
    *,
    run_nonce: str = "a" * 32,
    attempt: int = 1,
    bindings: dict[str, str] | None = None,
) -> ObservationExpectations:
    """Return one exact attempt expectation fixture."""

    return ObservationExpectations(
        run_nonce=run_nonce,
        attempt=attempt,
        bindings=bindings or fixture_bindings(),
    )


def fixture_frame_payload(
    *,
    baseline: dict[str, object] | None = None,
    completed_ns: int = 20,
) -> dict[str, object]:
    """Return one observation-frame payload before its digest is added."""

    return {
        "schema_version": 1,
        "frame_kind": "startup_preparation_observation",
        "run_nonce": "a" * 32,
        "attempt": 1,
        **fixture_bindings(),
        "resource_baseline_digest": resource_baseline_digest(
            baseline or fixture_resource_baseline()
        ),
        "observation_started_ns": 10,
        "observation_completed_ns": completed_ns,
        "frame_sequence": 1,
    }


def fixture_frame_and_acknowledgement() -> tuple[
    PreparationObservation,
    PreparationObservationAcknowledgement,
    bytes,
    bytes,
]:
    """Return validated frame and ACK objects with their canonical bytes."""

    frame_bytes = encode_observation_frame(fixture_frame_payload())
    frame = validate_observation_frame(
        frame_bytes,
        fixture_observation_expectations(),
    )
    acknowledgement_bytes = encode_observation_acknowledgement(
        {
            "schema_version": 1,
            "ack_kind": "startup_preparation_observation_ack",
            "run_nonce": "a" * 32,
            "attempt": 1,
            "frame_sequence": 1,
            "observation_frame_digest": frame["frame_digest"],
            "category": "accepted",
        }
    )
    acknowledgement = validate_observation_acknowledgement(
        acknowledgement_bytes,
        fixture_observation_expectations(),
        accepted_frame=frame,
    )
    return frame, acknowledgement, frame_bytes, acknowledgement_bytes


def fixture_receipt_payload(
    *,
    frame: PreparationObservation | None = None,
    acknowledgement: PreparationObservationAcknowledgement | None = None,
    baseline: dict[str, object] | None = None,
    result_completed_ns: int = 30,
) -> dict[str, object]:
    """Return one version-3 terminal receipt payload."""

    accepted_frame, accepted_acknowledgement, _, _ = (
        fixture_frame_and_acknowledgement()
    )
    frame = frame or accepted_frame
    acknowledgement = acknowledgement or accepted_acknowledgement
    baseline = baseline or fixture_resource_baseline()
    return {
        "schema_version": 3,
        "run_nonce": "a" * 32,
        "attempt": 1,
        **fixture_bindings(),
        "resource_baseline": baseline,
        "resource_baseline_digest": resource_baseline_digest(baseline),
        "observation_frame_digest": frame.frame_digest,
        "observation_ack_digest": acknowledgement.ack_digest,
        "observation_started_ns": frame.observation_started_ns,
        "observation_completed_ns": frame.observation_completed_ns,
        "observation_acknowledged_ns": frame.observation_completed_ns + 1,
        "result_completed_ns": result_completed_ns,
        "subordinate_cleanup": {
            "state": "subordinates_settled",
            "open_readers": 0,
            "open_connections": 0,
            "open_descendants": 0,
            "open_descriptors": 0,
            "open_threads": 0,
            "result_channel_state": "open_for_terminal_receipt",
            "result_channel_excluded": True,
        },
        "completion_state": "ready_to_exit",
        "expected_disposition": {
            "state": "normal_zero_exit_after_receipt_transmission",
            "exit_code": 0,
            "signal": None,
        },
        "category": "complete",
    }


def fixture_receipt_expectations(
    frame: PreparationObservation,
    acknowledgement: PreparationObservationAcknowledgement,
) -> ReceiptExpectations:
    """Return receipt expectations bound to one frame and ACK."""

    return ReceiptExpectations(
        observation_expectations=fixture_observation_expectations(),
        accepted_frame=frame,
        accepted_acknowledgement=acknowledgement,
    )


def fixture_accepted_protocol_state(
    *,
    receipt_parent_ns: int = FRAME_RECEIVED_NS + 200_000_000,
) -> PreparationProtocolState:
    """Return a state through fresh terminal-receipt acceptance."""

    frame, _, frame_bytes, acknowledgement_bytes = (
        fixture_frame_and_acknowledgement()
    )
    state = PreparationProtocolState(
        fixture_observation_expectations(),
        FRESHNESS_LEASE_MS,
    )
    state.accept_observation_frame(
        frame_bytes,
        parent_received_ns=FRAME_RECEIVED_NS,
    )
    acknowledgement = state.accept_observation_acknowledgement(
        acknowledgement_bytes
    )
    state.accept_terminal_receipt(
        encode_receipt(
            fixture_receipt_payload(
                frame=frame,
                acknowledgement=acknowledgement,
            )
        ),
        parent_received_ns=receipt_parent_ns,
    )
    return state
