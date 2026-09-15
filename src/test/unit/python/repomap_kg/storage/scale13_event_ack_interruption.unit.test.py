from __future__ import annotations

import json
import socket
import struct
from threading import Event, Thread
from typing import cast

import pytest

from repomap_kg.storage.staging_event_transport import (
    StagingEventChannel,
    StagingEventFrame,
    StagingEventTransportError,
)
from repomap_kg.storage.staging_observability import StagingMeasurements


class _InterruptOnAcknowledgementChannel(StagingEventChannel):
    def __init__(self, connection: socket.socket, acknowledged: Event) -> None:
        super().__init__(connection)
        self._acknowledged = acknowledged
        self.acknowledgements_consumed = 0
        self._interrupt_once = True

    def _recv_exact(self, size: int, *, clean_eof: bool = False) -> bytes:
        if size == 1 and self._interrupt_once:
            assert self._acknowledged.wait(timeout=1.0)
            self._interrupt_once = False
            raise KeyboardInterrupt
        received = super()._recv_exact(size, clean_eof=clean_eof)
        if size == 1:
            self.acknowledgements_consumed += 1
        return received


class _WriteFailureConnection:
    def __init__(self, failure: BaseException) -> None:
        self.failure = failure
        self.timeout: float | None = None

    def gettimeout(self) -> float | None:
        return self.timeout

    def settimeout(self, timeout: float | None) -> None:
        self.timeout = timeout

    def sendall(self, _frame: bytes) -> None:
        raise self.failure


def test_scale13_acknowledged_phase_interrupt_uses_next_wire_sequence() -> None:
    _assert_started_interrupt_uses_next_wire_sequence("phase")


def test_scale13_acknowledged_operation_interrupt_uses_next_wire_sequence() -> None:
    _assert_started_interrupt_uses_next_wire_sequence("operation")


def test_scale13_local_rejections_do_not_consume_sequence() -> None:
    sender_socket, receiver_socket = socket.socketpair()
    sender = StagingEventChannel(sender_socket)
    receiver = StagingEventChannel(receiver_socket)
    frames: list[StagingEventFrame] = []
    errors: list[BaseException] = []

    with pytest.raises(StagingEventTransportError, match="payload"):
        sender.send("phase", [])  # type: ignore[arg-type]
    with pytest.raises(StagingEventTransportError, match="too large"):
        sender.send("phase", {"value": "x" * 20_000})

    thread = Thread(target=_receive_frames, args=(receiver, 3, frames, errors))
    thread.start()
    for value in range(3):
        sender.send("phase", {"value": value})
    thread.join(timeout=1.0)

    assert not thread.is_alive()
    assert not errors, str(errors[0])
    assert [frame.sequence for frame in frames] == [1, 2, 3]
    sender.close()
    receiver.close()


@pytest.mark.parametrize("failure", (KeyboardInterrupt(), OSError("write failed")))
def test_scale13_ambiguous_write_failure_poisons_outgoing_reuse(
    failure: BaseException,
) -> None:
    connection = _WriteFailureConnection(failure)
    channel = StagingEventChannel(cast(socket.socket, connection))

    expected = (
        KeyboardInterrupt
        if isinstance(failure, KeyboardInterrupt)
        else StagingEventTransportError
    )
    with pytest.raises(expected) as raised:
        channel.send("phase", {})
    if isinstance(failure, KeyboardInterrupt):
        assert raised.value is failure
    with pytest.raises(StagingEventTransportError, match="outgoing channel is broken"):
        channel.send("phase", {})


def test_scale13_acknowledgement_timeout_poisons_outgoing_reuse() -> None:
    sender_socket, receiver_socket = socket.socketpair()
    sender = StagingEventChannel(
        sender_socket,
        acknowledgement_timeout_seconds=0.01,
    )

    with pytest.raises(TimeoutError, match="acknowledgement timed out"):
        sender.send("phase", {})
    with pytest.raises(StagingEventTransportError, match="outgoing channel is broken"):
        sender.send("phase", {})
    sender.close()
    receiver_socket.close()


def test_scale13_invalid_acknowledgement_poisons_outgoing_reuse() -> None:
    sender_socket, receiver_socket = socket.socketpair()
    sender = StagingEventChannel(sender_socket)
    errors: list[BaseException] = []

    def send_invalid_acknowledgement() -> None:
        try:
            _receive_wire_frame(receiver_socket)
            receiver_socket.sendall(b"\x15")
        except BaseException as error:
            errors.append(error)

    thread = Thread(target=send_invalid_acknowledgement)
    thread.start()
    with pytest.raises(StagingEventTransportError, match="acknowledgement is invalid"):
        sender.send("phase", {})
    thread.join(timeout=1.0)

    assert not thread.is_alive()
    assert not errors, str(errors[0])
    with pytest.raises(StagingEventTransportError, match="outgoing channel is broken"):
        sender.send("phase", {})
    sender.close()
    receiver_socket.close()


def test_scale13_deferred_interrupt_with_timeout_re_raises_interrupt_and_poisons() -> None:
    sender_socket, receiver_socket = socket.socketpair()
    acknowledged = Event()
    sender = _InterruptOnAcknowledgementChannel(sender_socket, acknowledged)
    sender._acknowledgement_timeout_seconds = 0.05
    acknowledged.set()

    with pytest.raises(KeyboardInterrupt) as raised:
        sender.send("phase", {})
    assert isinstance(raised.value.__cause__, TimeoutError)
    assert "acknowledgement timed out" in str(raised.value.__cause__)
    with pytest.raises(StagingEventTransportError, match="outgoing channel is broken"):
        sender.send("phase", {})
    sender.close()
    receiver_socket.close()


class _InterruptAfterAckReadChannel(StagingEventChannel):
    def __init__(self, connection: socket.socket) -> None:
        super().__init__(connection)
        self.interrupt_triggered = False

    def _recv_exact(self, size: int, *, clean_eof: bool = False) -> bytes:
        received = super()._recv_exact(size, clean_eof=clean_eof)
        if size == 1 and not self.interrupt_triggered:
            self.interrupt_triggered = True
            raise KeyboardInterrupt("interrupt immediately after ack read")
        return received


def test_scale13_interruption_after_ack_read_poisons_channel_without_double_settle() -> None:
    sender_socket, receiver_socket = socket.socketpair()
    sender = _InterruptAfterAckReadChannel(sender_socket)
    sender._acknowledgement_timeout_seconds = 0.1
    receiver = StagingEventChannel(receiver_socket)

    thread = Thread(target=lambda: receiver.receive(timeout_seconds=1.0))
    thread.start()

    with pytest.raises(KeyboardInterrupt, match="interrupt immediately after ack read"):
        sender.send("phase", {})

    thread.join(timeout=1.0)
    assert not thread.is_alive()
    with pytest.raises(StagingEventTransportError, match="outgoing channel is broken"):
        sender.send("phase", {})
    sender.close()
    receiver.close()


@pytest.mark.parametrize("received_sequence", (1, 3))
def test_scale13_receiver_rejects_duplicate_and_gap_with_bounded_diagnostic(
    received_sequence: int,
) -> None:
    receiver_socket, sender_socket = socket.socketpair()
    receiver = StagingEventChannel(receiver_socket)
    sender_socket.settimeout(1.0)
    sender_socket.sendall(_wire_frame(1, {"event_category": "started"}))

    assert receiver.receive(timeout_seconds=1.0).sequence == 1
    assert sender_socket.recv(1) == b"\x06"
    sender_socket.sendall(
        _wire_frame(received_sequence, {"event_category": "bounded-marker"})
    )

    expected = f"staging event sequence is invalid: expected=2, received={received_sequence}"
    with pytest.raises(StagingEventTransportError) as raised:
        receiver.receive(timeout_seconds=1.0)
    assert str(raised.value) == expected
    assert "bounded-marker" not in str(raised.value)
    receiver.close()
    sender_socket.close()


def _assert_started_interrupt_uses_next_wire_sequence(lifecycle: str) -> None:
    sender_socket, receiver_socket = socket.socketpair()
    acknowledged = Event()
    sender = _InterruptOnAcknowledgementChannel(sender_socket, acknowledged)
    receiver = StagingEventChannel(receiver_socket)
    frames: list[StagingEventFrame] = []
    errors: list[BaseException] = []

    def receive_lifecycle() -> None:
        try:
            frames.append(receiver.receive(timeout_seconds=1.0))
            acknowledged.set()
            frames.append(receiver.receive(timeout_seconds=1.0))
        except BaseException as error:
            errors.append(error)

    thread = Thread(target=receive_lifecycle)
    thread.start()
    if lifecycle == "phase":
        measurements = StagingMeasurements(
            lambda _event: None,
            phase_sink=lambda event: sender.send("phase", event.to_payload()),
        )
        lifecycle_owner = measurements.phase("refresh.source_discovery")
    else:
        measurements = StagingMeasurements(
            lambda _event: None,
            operation_sink=lambda event: sender.send(
                "operation", event.to_payload()
            ),
        )
        lifecycle_owner = measurements.operation("receipt.finalize")

    with pytest.raises(KeyboardInterrupt):
        with lifecycle_owner:
            pytest.fail("lifecycle body must not start")
    thread.join(timeout=1.0)

    assert not thread.is_alive()
    assert not errors, str(errors[0])
    assert [frame.sequence for frame in frames] == [1, 2]
    assert sender.acknowledgements_consumed == 2
    assert [frame.payload["event_category"] for frame in frames] == [
        "started",
        "cancelled",
    ]
    sender.close()
    receiver.close()


def _receive_frames(
    receiver: StagingEventChannel,
    count: int,
    frames: list[StagingEventFrame],
    errors: list[BaseException],
) -> None:
    try:
        for _ in range(count):
            frames.append(receiver.receive(timeout_seconds=1.0))
    except BaseException as error:
        errors.append(error)


def _wire_frame(sequence: int, payload: dict[str, object]) -> bytes:
    body = json.dumps(
        {
            "schema_version": 1,
            "frame_sequence": sequence,
            "frame_category": "phase",
            "payload": payload,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return struct.pack("!I", len(body)) + body


def _receive_wire_frame(connection: socket.socket) -> bytes:
    connection.settimeout(1.0)
    header = _recv_exact(connection, 4)
    (size,) = struct.unpack("!I", header)
    return _recv_exact(connection, size)


def _recv_exact(connection: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = connection.recv(remaining)
        if not chunk:
            raise EOFError("test connection closed")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)
