from __future__ import annotations

import json

import pytest

from repomap_test_support.scale28_adr2_frame_model import (
    MAX_SIGNED_INT,
    OBSERVATION_TRANSFER_RESERVE_NS,
)
from repomap_test_support.scale28_adr2_model_fixtures import (
    fixture_frame_and_acknowledgement,
    fixture_receipt_expectations,
    fixture_receipt_payload,
)
from repomap_test_support.scale28_adr2_receipt_model import (
    MAX_RECEIPT_BYTES,
    encode_receipt,
    validate_preparation_receipt,
)


def test_terminal_receipt_accepts_exact_version_three_binding_once() -> None:
    frame, acknowledgement, _, _ = fixture_frame_and_acknowledgement()
    encoded = encode_receipt(
        fixture_receipt_payload(
            frame=frame,
            acknowledgement=acknowledgement,
        )
    )
    receipt = validate_preparation_receipt(
        encoded,
        fixture_receipt_expectations(frame, acknowledgement),
    )

    assert receipt["schema_version"] == 3
    assert receipt["observation_frame_digest"] == frame["frame_digest"]
    assert receipt["observation_ack_digest"] == acknowledgement["ack_digest"]
    assert receipt["completion_state"] == "ready_to_exit"
    cleanup = receipt["subordinate_cleanup"]
    assert isinstance(cleanup, dict)
    assert cleanup["open_threads"] == 0
    assert (
        cleanup["result_channel_state"]
        == "open_for_terminal_receipt"
    )
    assert cleanup["result_channel_excluded"] is True
    assert len(encoded) <= MAX_RECEIPT_BYTES


@pytest.mark.parametrize("field", tuple(fixture_receipt_payload()))
def test_terminal_receipt_rejects_every_missing_field(field: str) -> None:
    payload = fixture_receipt_payload()
    payload.pop(field)

    with pytest.raises(ValueError, match="receipt fields are invalid"):
        encode_receipt(payload)


def test_terminal_receipt_rejects_extra_and_unknown_fields() -> None:
    payload = fixture_receipt_payload()
    payload["unknown"] = "value"

    with pytest.raises(ValueError, match="receipt fields are invalid"):
        encode_receipt(payload)


def test_terminal_receipt_rejects_non_lowercase_run_nonce() -> None:
    payload = fixture_receipt_payload()
    payload["run_nonce"] = "A" * 32

    with pytest.raises(ValueError, match="attempt run nonce is invalid"):
        encode_receipt(payload)


def test_terminal_receipt_rejects_malformed_duplicate_and_noncanonical_json() -> None:
    frame, acknowledgement, _, _ = fixture_frame_and_acknowledgement()
    expectations = fixture_receipt_expectations(frame, acknowledgement)
    encoded = encode_receipt(fixture_receipt_payload())
    duplicate = encoded.replace(
        b'"attempt":1',
        b'"attempt":1,"attempt":1',
    )
    noncanonical = json.dumps(json.loads(encoded), indent=1, sort_keys=True).encode(
        "ascii"
    )

    for candidate in (
        b"",
        b"{",
        b"\xff",
        duplicate,
        noncanonical,
        encoded[:-1],
        encoded + b" ",
        b"x" * (MAX_RECEIPT_BYTES + 1),
    ):
        with pytest.raises(ValueError):
            validate_preparation_receipt(candidate, expectations)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("schema_version", 1, "schema is unsupported"),
        ("schema_version", 2, "schema is unsupported"),
        ("schema_version", True, "numeric value"),
        ("attempt", True, "numeric value"),
        ("result_completed_ns", MAX_SIGNED_INT + 1, "numeric value"),
        ("completion_state", "complete", "completion state is invalid"),
        ("category", "partial", "category is invalid"),
    ),
)
def test_terminal_receipt_rejects_closed_schema_numeric_and_state_values(
    field: str,
    value: object,
    message: str,
) -> None:
    payload = fixture_receipt_payload()
    payload[field] = value

    with pytest.raises(ValueError, match=message):
        encode_receipt(payload)


@pytest.mark.parametrize(
    ("started", "completed", "acknowledged", "result", "message"),
    (
        (21, 20, 22, 23, "clock is invalid"),
        (10, 20, 19, 23, "clock is invalid"),
        (10, 20, 22, 21, "clock is invalid"),
        (
            10,
            20,
            20 + OBSERVATION_TRANSFER_RESERVE_NS + 1,
            20 + OBSERVATION_TRANSFER_RESERVE_NS + 2,
            "acknowledgement timed out",
        ),
    ),
)
def test_terminal_receipt_rejects_invalid_worker_local_order_or_ack_interval(
    started: int,
    completed: int,
    acknowledged: int,
    result: int,
    message: str,
) -> None:
    payload = fixture_receipt_payload()
    payload["observation_started_ns"] = started
    payload["observation_completed_ns"] = completed
    payload["observation_acknowledged_ns"] = acknowledged
    payload["result_completed_ns"] = result

    with pytest.raises(ValueError, match=message):
        encode_receipt(payload)


@pytest.mark.parametrize(
    ("section", "field", "value", "message"),
    (
        ("subordinate_cleanup", "open_readers", 1, "cleanup is incomplete"),
        ("subordinate_cleanup", "open_connections", 1, "cleanup is incomplete"),
        ("subordinate_cleanup", "open_descendants", 1, "cleanup is incomplete"),
        ("subordinate_cleanup", "open_descriptors", 1, "cleanup is incomplete"),
        ("subordinate_cleanup", "open_threads", 1, "cleanup is incomplete"),
        (
            "subordinate_cleanup",
            "result_channel_state",
            "closed",
            "result channel claim is invalid",
        ),
        (
            "subordinate_cleanup",
            "result_channel_excluded",
            False,
            "result channel claim is invalid",
        ),
        ("expected_disposition", "exit_code", 1, "disposition is invalid"),
        ("expected_disposition", "signal", "SIGTERM", "disposition is invalid"),
        ("expected_disposition", "state", "exited", "disposition is invalid"),
    ),
)
def test_terminal_receipt_rejects_incomplete_cleanup_or_process_claim(
    section: str,
    field: str,
    value: object,
    message: str,
) -> None:
    payload = fixture_receipt_payload()
    section_value = payload[section]
    assert isinstance(section_value, dict)
    nested = dict(section_value)
    nested[field] = value
    payload[section] = nested

    with pytest.raises(ValueError, match=message):
        encode_receipt(payload)


def test_terminal_receipt_rejects_wrong_frame_ack_baseline_and_observation() -> None:
    frame, acknowledgement, _, _ = fixture_frame_and_acknowledgement()
    expectations = fixture_receipt_expectations(frame, acknowledgement)
    changes = (
        ("observation_frame_digest", "0" * 64, "receipt frame is invalid"),
        ("observation_ack_digest", "0" * 64, "acknowledgement is invalid"),
        ("observation_completed_ns", 21, "observation is invalid"),
    )

    for field, value, message in changes:
        payload = fixture_receipt_payload(
            frame=frame,
            acknowledgement=acknowledgement,
        )
        payload[field] = value
        encoded = encode_receipt(payload)
        with pytest.raises(ValueError, match=message):
            validate_preparation_receipt(encoded, expectations)

    payload = fixture_receipt_payload(
        frame=frame,
        acknowledgement=acknowledgement,
    )
    payload["resource_baseline_digest"] = "0" * 64
    with pytest.raises(ValueError, match="baseline is invalid"):
        encode_receipt(payload)


def test_terminal_receipt_rejects_changed_payload_bytes() -> None:
    frame, acknowledgement, _, _ = fixture_frame_and_acknowledgement()
    expectations = fixture_receipt_expectations(frame, acknowledgement)
    encoded = encode_receipt(fixture_receipt_payload())
    validate_preparation_receipt(encoded, expectations)

    changed = bytearray(encoded)
    changed[-2] = ord("0") if changed[-2] != ord("0") else ord("1")
    with pytest.raises(ValueError):
        validate_preparation_receipt(bytes(changed), expectations)
