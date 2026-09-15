from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import socket
import struct

import pytest

from scale12_event_transport import (
    MAX_FRAME_BYTES,
    Scale12EventChannel,
    Scale12TransportError,
)


def _pair() -> tuple[Scale12EventChannel, Scale12EventChannel]:
    left, right = socket.socketpair()
    return Scale12EventChannel(left), Scale12EventChannel(right)


def _raw_frame(sequence: int, payload: object) -> bytes:
    encoded = json.dumps(
        {
            "schema_version": 1,
            "frame_sequence": sequence,
            "frame_category": "operation",
            "payload": payload,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return struct.pack("!I", len(encoded)) + encoded


def test_scale12_transport_round_trips_one_acknowledged_frame() -> None:
    sender, receiver = _pair()
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            sender.send,
            "operation",
            {"operation_code": "merge.files"},
        )
        frame = receiver.receive(timeout_seconds=1.0)
        future.result(timeout=1.0)
    sender.close()
    receiver.close()

    assert frame.sequence == 1
    assert frame.category == "operation"
    assert frame.payload == {"operation_code": "merge.files"}


def test_scale12_transport_rejects_oversized_payload_before_send() -> None:
    sender, receiver = _pair()
    with pytest.raises(Scale12TransportError, match="frame size"):
        sender.send("terminal", {"value": "x" * MAX_FRAME_BYTES})
    sender.close()
    receiver.close()


@pytest.mark.parametrize(
    ("encoded", "message"),
    (
        (b"not-json", "JSON"),
        (json.dumps([]).encode(), "object"),
        (
            json.dumps(
                {
                    "schema_version": 2,
                    "frame_sequence": 1,
                    "frame_category": "operation",
                    "payload": {},
                }
            ).encode(),
            "schema",
        ),
    ),
)
def test_scale12_transport_rejects_malformed_frames(
    encoded: bytes,
    message: str,
) -> None:
    raw_sender, raw_receiver = socket.socketpair()
    receiver = Scale12EventChannel(raw_receiver)
    raw_sender.sendall(struct.pack("!I", len(encoded)) + encoded)

    with pytest.raises(Scale12TransportError, match=message):
        receiver.receive(timeout_seconds=1.0)

    raw_sender.close()
    receiver.close()


def test_scale12_transport_rejects_duplicate_frame_sequence() -> None:
    raw_sender, raw_receiver = socket.socketpair()
    receiver = Scale12EventChannel(raw_receiver)
    raw_sender.sendall(_raw_frame(1, {}))
    receiver.receive(timeout_seconds=1.0)
    assert raw_sender.recv(1) == b"\x06"
    raw_sender.sendall(_raw_frame(1, {}))

    with pytest.raises(Scale12TransportError, match="sequence"):
        receiver.receive(timeout_seconds=1.0)

    raw_sender.close()
    receiver.close()


def test_scale12_transport_reports_early_eof_and_timeout() -> None:
    sender, receiver = _pair()
    with pytest.raises(TimeoutError):
        receiver.receive(timeout_seconds=0.01)
    sender.close()
    with pytest.raises(Scale12TransportError, match="EOF") as exc_info:
        receiver.receive(timeout_seconds=1.0)
    evidence = exc_info.value.structural_evidence()
    assert evidence["role"] == "scale12_event_transport"
    assert evidence["phase"] == "transport_receive"
    assert evidence["expected"] == "exact_4_bytes"
    assert evidence["observed"] == "early_eof_after_0_bytes"
    receiver.close()


def test_scale12_transport_early_eof_during_payload() -> None:
    raw_sender, raw_receiver = socket.socketpair()
    receiver = Scale12EventChannel(raw_receiver)
    raw_sender.sendall(struct.pack("!I", 100) + b"partial_payload")
    raw_sender.close()
    with pytest.raises(Scale12TransportError, match="EOF") as exc_info:
        receiver.receive(timeout_seconds=1.0)
    evidence = exc_info.value.structural_evidence()
    assert evidence["role"] == "scale12_event_transport"
    assert evidence["phase"] == "transport_receive"
    assert evidence["expected"] == "exact_100_bytes"
    assert evidence["observed"] == "early_eof_after_15_bytes"
    receiver.close()


def test_scale12_transport_early_eof_during_ack() -> None:
    raw_sender, raw_receiver = socket.socketpair()
    sender = Scale12EventChannel(raw_sender)

    def _close_receiver_after_frame() -> None:
        header = raw_receiver.recv(4)
        if len(header) == 4:
            length = struct.unpack("!I", header)[0]
            _ = raw_receiver.recv(length)
        raw_receiver.close()

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_close_receiver_after_frame)
        with pytest.raises(Scale12TransportError, match="EOF") as exc_info:
            sender.send("operation", {"operation_code": "merge.files"})
        future.result(timeout=1.0)
    evidence = exc_info.value.structural_evidence()
    assert evidence["role"] == "scale12_event_transport"
    assert evidence["phase"] == "transport_receive"
    assert evidence["expected"] == "exact_1_bytes"
    assert evidence["observed"] == "early_eof_after_0_bytes"
    sender.close()


def test_scale12_transport_refuses_send_after_close() -> None:
    sender, receiver = _pair()
    sender.close()
    with pytest.raises(Scale12TransportError, match="closed") as exc_info:
        sender.send("ready", {})
    evidence = exc_info.value.structural_evidence()
    assert evidence["role"] == "scale12_event_transport"
    assert evidence["phase"] == "channel_state"
    assert evidence["expected"] == "open_channel"
    assert evidence["observed"] == "closed_channel"
    receiver.close()


def test_scale12_transport_buffers_partial_frame_across_timeouts() -> None:
    raw_sender, raw_receiver = socket.socketpair()
    receiver = Scale12EventChannel(raw_receiver)
    frame_bytes = _raw_frame(1, {"step": "partial_buffering"})

    # Send first 2 bytes of header
    raw_sender.sendall(frame_bytes[:2])
    with pytest.raises(TimeoutError):
        receiver.receive(timeout_seconds=0.01)

    # Send rest of header and partial body
    raw_sender.sendall(frame_bytes[2:10])
    with pytest.raises(TimeoutError):
        receiver.receive(timeout_seconds=0.01)

    # Send remaining body
    raw_sender.sendall(frame_bytes[10:])
    frame = receiver.receive(timeout_seconds=1.0)
    assert frame.sequence == 1
    assert frame.payload == {"step": "partial_buffering"}
    assert raw_sender.recv(1) == b"\x06"
    raw_sender.close()
    receiver.close()

