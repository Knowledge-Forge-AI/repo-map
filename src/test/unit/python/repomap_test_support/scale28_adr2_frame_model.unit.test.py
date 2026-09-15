from __future__ import annotations

import hashlib
import json

import pytest

from repomap_test_support.scale28_adr2_frame_model import (
    MAX_OBSERVATION_ACK_BYTES,
    MAX_OBSERVATION_FRAME_BYTES,
    MAX_SIGNED_INT,
    ObservationExpectations,
    PreparationObservation,
    encode_observation_acknowledgement,
    encode_observation_frame,
    resource_baseline_digest,
    validate_observation_acknowledgement,
    validate_observation_frame,
)


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("ascii")).hexdigest()


def _bindings(prefix: str = "current") -> dict[str, str]:
    return {
        field: _digest(f"{prefix}:{field}")
        for field in (
            "runtime_scope_digest",
            "topology_digest",
            "pgdata_generation_digest",
            "configuration_generation_digest",
            "observer_generation_digest",
        )
    }


def _baseline() -> dict[str, object]:
    return {
        "schema_version": 1,
        "client_peak_rss_bytes": 64_000_000,
        "postgresql_container_rss_upper_bound": 96_000_000,
        "temporary_byte_upper_bound_delta": 0,
        "wal_upper_bound_delta": 4_096,
        "allocated_delta_bytes": 8_192,
        "backing_free_bytes": 4_000_000_000,
        "pgdata_reader_elapsed_ns": 1_000_000,
        "availability": "available",
    }


def _expectations() -> ObservationExpectations:
    return ObservationExpectations(
        run_nonce="a" * 32,
        attempt=1,
        bindings=_bindings(),
    )


def _frame_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "frame_kind": "startup_preparation_observation",
        "run_nonce": "a" * 32,
        "attempt": 1,
        **_bindings(),
        "resource_baseline_digest": resource_baseline_digest(_baseline()),
        "observation_started_ns": 10,
        "observation_completed_ns": 20,
        "frame_sequence": 1,
    }


def _accepted_frame() -> PreparationObservation:
    return validate_observation_frame(
        encode_observation_frame(_frame_payload()),
        _expectations(),
    )


def _ack_payload(
    frame: PreparationObservation | None = None,
) -> dict[str, object]:
    accepted = frame or _accepted_frame()
    return {
        "schema_version": 1,
        "ack_kind": "startup_preparation_observation_ack",
        "run_nonce": "a" * 32,
        "attempt": 1,
        "frame_sequence": 1,
        "observation_frame_digest": accepted["frame_digest"],
        "category": "accepted",
    }


def test_observation_frame_accepts_exact_canonical_bound_scope() -> None:
    encoded = encode_observation_frame(_frame_payload())
    frame = validate_observation_frame(encoded, _expectations())

    assert encoded == json.dumps(
        frame.to_mapping(),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    assert len(encoded) <= MAX_OBSERVATION_FRAME_BYTES
    assert frame["frame_sequence"] == 1
    assert frame["resource_baseline_digest"] == resource_baseline_digest(_baseline())


@pytest.mark.parametrize("field", tuple(_frame_payload()))
def test_observation_frame_rejects_every_missing_field(field: str) -> None:
    payload = _frame_payload()
    payload.pop(field)

    with pytest.raises(ValueError, match="observation frame fields are invalid"):
        encode_observation_frame(payload)


def test_observation_frame_rejects_extra_and_unknown_fields() -> None:
    payload = _frame_payload()
    payload["unknown"] = "value"

    with pytest.raises(ValueError, match="observation frame fields are invalid"):
        encode_observation_frame(payload)


@pytest.mark.parametrize(
    "encoded",
    (
        b"",
        b"{",
        b"\xff",
        b'{"schema_version":1,"schema_version":1}',
    ),
)
def test_observation_frame_rejects_malformed_and_duplicate_json(encoded: bytes) -> None:
    with pytest.raises(ValueError):
        validate_observation_frame(encoded, _expectations())


def test_observation_frame_rejects_truncated_trailing_and_oversized_bytes() -> None:
    encoded = encode_observation_frame(_frame_payload())

    for changed in (
        encoded[:-1],
        encoded + b" ",
        b"x" * (MAX_OBSERVATION_FRAME_BYTES + 1),
    ):
        with pytest.raises(ValueError):
            validate_observation_frame(changed, _expectations())


def test_observation_frame_rejects_noncanonical_and_changed_digest() -> None:
    encoded = encode_observation_frame(_frame_payload())
    decoded = json.loads(encoded)
    noncanonical = json.dumps(decoded, indent=1, sort_keys=True).encode("ascii")
    with pytest.raises(ValueError, match="not canonical"):
        validate_observation_frame(noncanonical, _expectations())

    decoded["observation_completed_ns"] += 1
    changed = json.dumps(
        decoded,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    with pytest.raises(ValueError, match="frame digest is invalid"):
        validate_observation_frame(changed, _expectations())


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("schema_version", True, "numeric value"),
        ("attempt", True, "numeric value"),
        ("frame_sequence", True, "numeric value"),
        ("observation_completed_ns", MAX_SIGNED_INT + 1, "numeric value"),
        ("schema_version", 2, "schema is unsupported"),
        ("attempt", 3, "attempt number is invalid"),
        ("frame_sequence", 2, "sequence is invalid"),
        ("frame_kind", "other", "kind is invalid"),
    ),
)
def test_observation_frame_rejects_closed_numeric_and_enum_values(
    field: str,
    value: object,
    message: str,
) -> None:
    payload = _frame_payload()
    payload[field] = value

    with pytest.raises(ValueError, match=message):
        encode_observation_frame(payload)


def test_observation_frame_rejects_reversed_worker_local_clock() -> None:
    payload = _frame_payload()
    payload["observation_started_ns"] = 21

    with pytest.raises(ValueError, match="clock is invalid"):
        encode_observation_frame(payload)


@pytest.mark.parametrize(
    "expectations",
    (
        ObservationExpectations("b" * 32, 1, _bindings()),
        ObservationExpectations("a" * 32, 2, _bindings()),
        ObservationExpectations("a" * 32, 1, _bindings("other")),
    ),
)
def test_observation_frame_rejects_wrong_run_attempt_scope_or_generation(
    expectations: ObservationExpectations,
) -> None:
    encoded = encode_observation_frame(_frame_payload())

    with pytest.raises(ValueError):
        validate_observation_frame(encoded, expectations)


def test_observation_acknowledgement_accepts_exact_frame_digest() -> None:
    frame = _accepted_frame()
    encoded = encode_observation_acknowledgement(_ack_payload(frame))
    acknowledgement = validate_observation_acknowledgement(
        encoded,
        _expectations(),
        accepted_frame=frame,
    )

    assert acknowledgement["category"] == "accepted"
    assert acknowledgement["observation_frame_digest"] == frame["frame_digest"]
    assert len(encoded) <= MAX_OBSERVATION_ACK_BYTES


@pytest.mark.parametrize("field", tuple(_ack_payload()))
def test_observation_acknowledgement_rejects_every_missing_field(field: str) -> None:
    payload = _ack_payload()
    payload.pop(field)

    with pytest.raises(ValueError, match="acknowledgement fields are invalid"):
        encode_observation_acknowledgement(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("schema_version", 2),
        ("ack_kind", "other"),
        ("run_nonce", "b" * 32),
        ("attempt", 2),
        ("frame_sequence", 2),
        ("observation_frame_digest", "0" * 64),
        ("category", "rejected"),
    ),
)
def test_observation_acknowledgement_rejects_wrong_or_stale_binding(
    field: str,
    value: object,
) -> None:
    frame = _accepted_frame()
    payload = _ack_payload(frame)
    payload[field] = value

    if field in {"run_nonce", "attempt", "observation_frame_digest"}:
        encoded = encode_observation_acknowledgement(payload)
        with pytest.raises(ValueError):
            validate_observation_acknowledgement(
                encoded,
                _expectations(),
                accepted_frame=frame,
            )
    else:
        with pytest.raises(ValueError):
            encode_observation_acknowledgement(payload)


def test_observation_acknowledgement_rejects_tampering_and_oversize() -> None:
    frame = _accepted_frame()
    encoded = encode_observation_acknowledgement(_ack_payload(frame))
    changed = bytearray(encoded)
    changed[-2] = ord("0") if changed[-2] != ord("0") else ord("1")

    for candidate in (
        bytes(changed),
        b"x" * (MAX_OBSERVATION_ACK_BYTES + 1),
    ):
        with pytest.raises(ValueError):
            validate_observation_acknowledgement(
                candidate,
                _expectations(),
                accepted_frame=frame,
            )
