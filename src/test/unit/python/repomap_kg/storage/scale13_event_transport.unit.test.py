from __future__ import annotations

import json
import socket
import struct
from threading import Event, Thread

import pytest

from repomap_kg.storage.staging_event_transport import (
    StagingEventChannel,
    StagingEventTransportError,
    staging_event_channel_from_inherited_fd,
)


def test_scale13_event_channel_acknowledges_strict_bounded_frames() -> None:
    left, right = socket.socketpair()
    sender = StagingEventChannel(left)
    receiver = StagingEventChannel(right)
    errors: list[BaseException] = []

    def send() -> None:
        try:
            sender.send("phase", {"phase_code": "refresh.source_discovery"})
        except BaseException as error:
            errors.append(error)

    thread = Thread(target=send)
    thread.start()
    frame = receiver.receive(timeout_seconds=1.0)
    thread.join(timeout=1.0)

    assert errors == []
    assert not thread.is_alive()
    assert frame.sequence == 1
    assert frame.category == "phase"
    assert frame.payload == {"phase_code": "refresh.source_discovery"}
    sender.close()
    receiver.close()


def test_scale13_event_channel_rejects_invalid_bounds_and_payloads() -> None:
    left, right = socket.socketpair()
    channel = StagingEventChannel(left)

    with pytest.raises(ValueError, match="receive timeout"):
        channel.receive(timeout_seconds=0)
    with pytest.raises(StagingEventTransportError, match="payload"):
        channel.send("phase", [])  # type: ignore[arg-type]
    with pytest.raises(StagingEventTransportError, match="too large"):
        channel.send("phase", {"value": "x" * 20_000})

    channel.close()
    channel.close()
    with pytest.raises(StagingEventTransportError, match="closed"):
        channel.send("phase", {})
    right.close()


@pytest.mark.parametrize(
    "body",
    (
        b"not-json",
        json.dumps({"schema_version": 1}).encode(),
        json.dumps(
            {
                "schema_version": 2,
                "frame_sequence": 1,
                "frame_category": "phase",
                "payload": {},
            }
        ).encode(),
        json.dumps(
            {
                "schema_version": 1,
                "frame_sequence": True,
                "frame_category": "phase",
                "payload": {},
            }
        ).encode(),
        json.dumps(
            {
                "schema_version": 1,
                "frame_sequence": 1,
                "frame_category": "stdout",
                "payload": {},
            }
        ).encode(),
        json.dumps(
            {
                "schema_version": 1,
                "frame_sequence": 1,
                "frame_category": "phase",
                "payload": [],
            }
        ).encode(),
    ),
)
def test_scale13_event_channel_rejects_malformed_frames(body: bytes) -> None:
    left, right = socket.socketpair()
    channel = StagingEventChannel(left)

    with pytest.raises(StagingEventTransportError, match="invalid"):
        channel._decode_frame(body)

    channel.close()
    right.close()


def test_scale13_event_channel_rejects_invalid_wire_size() -> None:
    left, right = socket.socketpair()
    channel = StagingEventChannel(left)
    right.sendall(struct.pack("!I", 0))

    with pytest.raises(StagingEventTransportError, match="size"):
        channel.receive(timeout_seconds=1.0)

    channel.close()
    right.close()


@pytest.mark.parametrize("descriptor", (True, -1))
def test_scale13_event_channel_rejects_invalid_inherited_descriptor(
    descriptor,
) -> None:
    with pytest.raises(StagingEventTransportError, match="descriptor"):
        staging_event_channel_from_inherited_fd(descriptor)


def test_scale13_event_channel_rejects_unknown_categories() -> None:
    left, right = socket.socketpair()
    channel = StagingEventChannel(left)
    with pytest.raises(StagingEventTransportError, match="category"):
        channel.send("stdout", {})
    channel.close()
    right.close()


def test_scale13_event_channel_reports_clean_eof_between_frames() -> None:
    left, right = socket.socketpair()
    receiver = StagingEventChannel(left)
    right.close()

    with pytest.raises(EOFError, match="closed"):
        receiver.receive(timeout_seconds=1.0)

    receiver.close()


def test_scale13_event_channel_reports_receive_readiness_before_data() -> None:
    left, right = socket.socketpair()
    sender = StagingEventChannel(left)
    receiver = StagingEventChannel(right)
    ready = Event()
    frames = []
    errors: list[BaseException] = []

    def receive() -> None:
        try:
            frames.append(
                receiver.receive(timeout_seconds=1.0, readiness=ready.set)
            )
        except BaseException as error:
            errors.append(error)

    thread = Thread(target=receive)
    thread.start()
    assert ready.wait(0.2)

    sender.send("authority", {"event_category": "bound"})
    thread.join(timeout=1.0)

    assert errors == []
    assert len(frames) == 1
    sender.close()
    receiver.close()


def test_scale16_authority_frame_is_validated_before_acknowledgement() -> None:
    left, right = socket.socketpair()
    sender = StagingEventChannel(left, acknowledgement_timeout_seconds=0.05)
    receiver = StagingEventChannel(right)
    errors: list[BaseException] = []

    def send() -> None:
        try:
            sender.send("authority", {"event_category": "bound"})
        except BaseException as error:
            errors.append(error)

    thread = Thread(target=send)
    thread.start()
    with pytest.raises(ValueError, match="semantic rejection"):
        receiver.receive(
            timeout_seconds=1.0,
            validator=lambda _frame: (_ for _ in ()).throw(
                ValueError("semantic rejection")
            ),
        )
    thread.join(timeout=1.0)

    assert len(errors) == 1
    assert isinstance(errors[0], TimeoutError)
    sender.close()
    receiver.close()


def test_scale16_valid_authority_frame_is_acknowledged_once() -> None:
    left, right = socket.socketpair()
    sender = StagingEventChannel(left)
    receiver = StagingEventChannel(right)
    accepted = []
    errors: list[BaseException] = []

    thread = Thread(
        target=lambda: _send_frame(sender, errors),
    )
    thread.start()
    frame = receiver.receive(
        timeout_seconds=1.0,
        validator=lambda value: accepted.append(value),
    )
    thread.join(timeout=1.0)

    assert errors == []
    assert accepted == [frame]
    assert frame.category == "authority"
    sender.close()
    receiver.close()


def _send_frame(channel: StagingEventChannel, errors: list[BaseException]) -> None:
    try:
        channel.send("authority", {"event_category": "bound"})
    except BaseException as error:
        errors.append(error)
