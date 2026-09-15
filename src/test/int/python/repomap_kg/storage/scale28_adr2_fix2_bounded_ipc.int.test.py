from __future__ import annotations

from multiprocessing import get_context
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
import time

import pytest

import repomap_test_support.scale28_adr2_bounded_ipc as bounded_ipc_transport
from repomap_test_support.scale28_adr2_bounded_ipc import (
    ACKNOWLEDGEMENT_MESSAGE, OBSERVATION_MESSAGE, RECEIPT_MESSAGE,
    BoundedIpcFailure, BoundedIpcMessageSpec, process_close_without_send,
    process_hold_partial_frame, process_send_messages, process_send_raw_frame,
    process_wait_for_ack_after_parent_close, receive_bounded_and_decode,
    receive_bounded_message, supports_raw_connection_fault_injection,
    write_raw_connection_frame,
)
from repomap_test_support.scale28_adr2_frame_model import (
    validate_observation_frame,
)
from repomap_test_support.scale28_adr2_immutable_values import (
    canonical_protocol_bytes,
    structural_digest,
)
from repomap_test_support.scale28_adr2_model_fixtures import (
    fixture_frame_and_acknowledgement,
    fixture_observation_expectations,
    fixture_receipt_expectations,
    fixture_receipt_payload,
)
from repomap_test_support.scale28_adr2_receipt_model import (
    encode_receipt,
    validate_preparation_receipt,
)


MESSAGE_SPECS = (
    OBSERVATION_MESSAGE,
    ACKNOWLEDGEMENT_MESSAGE,
    RECEIPT_MESSAGE,
)


def _start_sender(
    payloads: tuple[bytes, ...],
) -> tuple[Connection, BaseProcess]:
    context = get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(
        target=process_send_messages,
        args=(sender, payloads),
    )
    process.start()
    sender.close()
    return receiver, process


def _settle_process(
    process: BaseProcess,
    *,
    expected_exit_code: int = 0,
) -> None:
    process.join(3.0)
    assert process.is_alive() is False
    assert process.exitcode == expected_exit_code
    process.close()


@pytest.mark.parametrize("spec", MESSAGE_SPECS)
@pytest.mark.parametrize("size_kind", ("small", "exact_limit"))
def test_bounded_receive_accepts_small_and_exact_limit_messages(
    spec: BoundedIpcMessageSpec,
    size_kind: str,
) -> None:
    size = 17 if size_kind == "small" else spec.maximum_bytes
    receiver, process = _start_sender((b"x" * size,))
    try:
        message = receive_bounded_message(
            receiver,
            spec,
            timeout_seconds=1.0,
        )
        assert message.message_kind == spec.message_kind
        assert message.byte_count == size
        assert message.payload == b"x" * size
    finally:
        receiver.close()
        _settle_process(process)


@pytest.mark.parametrize("spec", MESSAGE_SPECS)
def test_bounded_receive_rejects_zero_length_message(
    spec: BoundedIpcMessageSpec,
) -> None:
    receiver, process = _start_sender((b"",))
    try:
        with pytest.raises(BoundedIpcFailure) as captured:
            receive_bounded_message(receiver, spec, timeout_seconds=1.0)
        assert captured.value.category == "zero_length_message"
        assert captured.value.source_boundary == "transport_body"
        assert receiver.closed is True
    finally:
        receiver.close()
        _settle_process(process)


@pytest.mark.parametrize("spec", MESSAGE_SPECS)
def test_overflow_is_rejected_before_application_decode(
    spec: BoundedIpcMessageSpec,
) -> None:
    receiver, process = _start_sender((b"x" * (spec.maximum_bytes + 1),))
    decoder_calls: list[int] = []
    try:
        with pytest.raises(BoundedIpcFailure) as captured:
            receive_bounded_and_decode(
                receiver,
                spec,
                lambda payload: decoder_calls.append(len(payload)),
                timeout_seconds=1.0,
            )
        assert captured.value.category == "message_overflow"
        assert captured.value.source_boundary == "transport_header"
        assert decoder_calls == []
        assert receiver.closed is True
    finally:
        receiver.close()
        _settle_process(process)


def test_very_large_declared_length_is_rejected_without_body() -> None:
    if not supports_raw_connection_fault_injection():
        context = get_context("spawn")
        receiver, sender = context.Pipe(duplex=False)
        try:
            with pytest.raises(RuntimeError, match="unsupported"):
                write_raw_connection_frame(
                    sender,
                    declared_length=10_000_000,
                    body=b"",
                )
        finally:
            receiver.close()
            sender.close()
        return

    context = get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(
        target=process_send_raw_frame,
        args=(sender, 10_000_000, b"", 4),
    )
    process.start()
    sender.close()
    try:
        with pytest.raises(BoundedIpcFailure) as captured:
            receive_bounded_message(
                receiver,
                OBSERVATION_MESSAGE,
                timeout_seconds=1.0,
            )
        assert captured.value.category == "message_overflow"
        assert captured.value.source_boundary == "transport_header"
    finally:
        receiver.close()
        _settle_process(process)


@pytest.mark.parametrize(
    ("spec", "header_bytes", "body", "expected_boundary"),
    (
        (OBSERVATION_MESSAGE, 2, b"", "transport_frame"),
        (OBSERVATION_MESSAGE, 4, b"partial", "transport_frame"),
        (RECEIPT_MESSAGE, 2, b"", "transport_frame"),
        (RECEIPT_MESSAGE, 4, b"partial", "transport_frame"),
    ),
)
def test_partial_header_and_body_fail_closed(
    spec: BoundedIpcMessageSpec,
    header_bytes: int,
    body: bytes,
    expected_boundary: str,
) -> None:
    if not supports_raw_connection_fault_injection():
        return
    context = get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(
        target=process_send_raw_frame,
        args=(sender, 100, body, header_bytes),
    )
    process.start()
    sender.close()
    try:
        with pytest.raises(BoundedIpcFailure) as captured:
            receive_bounded_message(receiver, spec, timeout_seconds=1.0)
        assert captured.value.category == "sender_exit_during_message"
        assert captured.value.source_boundary == expected_boundary
        assert receiver.closed is True
    finally:
        receiver.close()
        _settle_process(process)


@pytest.mark.parametrize(
    ("header_bytes", "body"),
    ((2, b""), (4, b"x")),
)
def test_held_open_partial_frame_obeys_whole_frame_deadline(
    header_bytes: int,
    body: bytes,
) -> None:
    if not supports_raw_connection_fault_injection():
        return
    context = get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    ready = context.Event()
    process = context.Process(
        target=process_hold_partial_frame,
        args=(sender, 100, body, header_bytes, ready, 0.5),
    )
    process.start()
    sender.close()
    assert ready.wait(1.0)
    started = time.monotonic()
    try:
        with pytest.raises(BoundedIpcFailure) as captured:
            receive_bounded_message(
                receiver,
                OBSERVATION_MESSAGE,
                timeout_seconds=0.02,
            )
        assert captured.value.category == "message_timeout"
        assert captured.value.source_boundary == "transport_frame"
        assert time.monotonic() - started < 0.25
        assert receiver.closed is True
    finally:
        receiver.close()
        _settle_process(process)


@pytest.mark.parametrize("spec", (OBSERVATION_MESSAGE, RECEIPT_MESSAGE))
@pytest.mark.parametrize("changed", (False, True))
def test_unexpected_identical_or_changed_second_message_is_rejected(
    spec: BoundedIpcMessageSpec,
    changed: bool,
) -> None:
    second = b"second" if changed else b"first"
    receiver, process = _start_sender((b"first", second))
    try:
        with pytest.raises(BoundedIpcFailure) as captured:
            receive_bounded_message(receiver, spec, timeout_seconds=1.0)
        assert captured.value.category == "unexpected_second_message"
        assert captured.value.source_boundary == "transport_sequence"
        assert receiver.closed is True
    finally:
        receiver.close()
        _settle_process(process)


@pytest.mark.parametrize(
    ("field_name", "replacement", "expected_message"),
    (
        ("frame_kind", "terminal_receipt", "observation frame kind is invalid"),
        ("frame_sequence", 2, "observation frame sequence is invalid"),
        ("attempt", 2, "observation frame run is invalid"),
        ("run_nonce", "b" * 32, "observation frame run is invalid"),
    ),
)
def test_application_frame_faults_close_actual_process_channel(
    field_name: str,
    replacement: object,
    expected_message: str,
) -> None:
    frame, _, _, _ = fixture_frame_and_acknowledgement()
    changed = frame.to_mapping()
    changed[field_name] = replacement
    changed["frame_digest"] = structural_digest(changed, "frame_digest")
    receiver, process = _start_sender((canonical_protocol_bytes(changed),))
    try:
        with pytest.raises(ValueError, match=f"^{expected_message}$"):
            receive_bounded_and_decode(
                receiver, OBSERVATION_MESSAGE,
                lambda payload: validate_observation_frame(payload, fixture_observation_expectations()),
                timeout_seconds=1.0,
            )
        assert receiver.closed is True
    finally:
        receiver.close()
        _settle_process(process)


def test_trailing_frame_data_closes_actual_process_channel() -> None:
    frame, _, _, _ = fixture_frame_and_acknowledgement()
    receiver, process = _start_sender((frame.to_bytes() + b" ",))
    try:
        with pytest.raises(ValueError, match="^observation frame is not canonical$"):
            receive_bounded_and_decode(
                receiver, OBSERVATION_MESSAGE,
                lambda payload: validate_observation_frame(payload, fixture_observation_expectations()),
                timeout_seconds=1.0,
            )
        assert receiver.closed is True
    finally:
        receiver.close()
        _settle_process(process)


def test_trailing_receipt_data_closes_actual_process_channel() -> None:
    frame, acknowledgement, _, _ = fixture_frame_and_acknowledgement()
    receipt = encode_receipt(fixture_receipt_payload(frame=frame, acknowledgement=acknowledgement))
    expectations = fixture_receipt_expectations(frame, acknowledgement)
    receiver, process = _start_sender((receipt + b" ",))
    try:
        with pytest.raises(ValueError, match="^preparation receipt is not canonical$"):
            receive_bounded_and_decode(
                receiver, RECEIPT_MESSAGE,
                lambda payload: validate_preparation_receipt(payload, expectations),
                timeout_seconds=1.0,
            )
        assert receiver.closed is True
    finally:
        receiver.close()
        _settle_process(process)


def test_sender_exit_before_message_is_classified() -> None:
    context = get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=process_close_without_send, args=(sender,))
    process.start()
    sender.close()
    try:
        with pytest.raises(BoundedIpcFailure) as captured:
            receive_bounded_message(receiver, OBSERVATION_MESSAGE, timeout_seconds=1.0)
        assert captured.value.category == "sender_exit_before_message"
        assert captured.value.source_boundary == "transport_header"
    finally:
        receiver.close()
        _settle_process(process)


def test_receiver_local_close_is_classified_without_poll_or_receive() -> None:
    context = get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    receiver.close()
    sender.close()

    with pytest.raises(BoundedIpcFailure) as captured:
        receive_bounded_message(receiver, OBSERVATION_MESSAGE, timeout_seconds=0.0)
    assert captured.value.category == "receiver_closed"
    assert captured.value.source_boundary == "receiver_preflight"


def test_unsupported_platform_refuses_before_transport_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    monkeypatch.setattr(
        bounded_ipc_transport, "supports_deadline_bounded_connection_receive", lambda: False,
    )
    try:
        with pytest.raises(BoundedIpcFailure) as captured:
            receive_bounded_message(receiver, OBSERVATION_MESSAGE, timeout_seconds=0.0)
        assert captured.value.category == "transport_unsupported"
        assert captured.value.source_boundary == "receiver_preflight"
        assert receiver.closed is True
    finally:
        receiver.close()
        sender.close()


def test_acknowledgement_timeout_closes_the_attempt_channel() -> None:
    context = get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    try:
        with pytest.raises(BoundedIpcFailure) as captured:
            receive_bounded_message(receiver, ACKNOWLEDGEMENT_MESSAGE, timeout_seconds=0.01)
        assert captured.value.category == "message_timeout"
        assert captured.value.source_boundary == "transport_poll"
        assert receiver.closed is True
    finally:
        receiver.close()
        sender.close()


def test_worker_waiting_for_ack_observes_parent_channel_close() -> None:
    context = get_context("spawn")
    worker_receiver, parent_sender = context.Pipe(duplex=False)
    process = context.Process(target=process_wait_for_ack_after_parent_close, args=(worker_receiver,))
    process.start()
    worker_receiver.close()
    parent_sender.close()
    _settle_process(process, expected_exit_code=42)
