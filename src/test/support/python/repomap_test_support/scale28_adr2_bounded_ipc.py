"""Bounded process-channel receives for SCALE28-ADR2-FIX2 qualification."""

from __future__ import annotations

from dataclasses import dataclass, field
from multiprocessing.connection import Connection
import os
import select
import struct
import time
from typing import Callable, NoReturn, Protocol, TypeVar

from repomap_test_support.scale28_adr2_frame_model import (
    MAX_OBSERVATION_ACK_BYTES,
    MAX_OBSERVATION_FRAME_BYTES,
)
from repomap_test_support.scale28_adr2_receipt_model import MAX_RECEIPT_BYTES
import repomap_test_support.scale28_adr2_scenarios as _adr2_scenarios

process_close_without_send = _adr2_scenarios.process_close_without_send
process_send_delayed_second_message = _adr2_scenarios.process_send_delayed_second_message
process_send_messages = _adr2_scenarios.process_send_messages
process_send_raw_frame = _adr2_scenarios.process_send_raw_frame
process_wait_for_ack_after_parent_close = _adr2_scenarios.process_wait_for_ack_after_parent_close
process_wait_for_ack_timeout = _adr2_scenarios.process_wait_for_ack_timeout


@dataclass(frozen=True, slots=True)
class BoundedIpcMessageSpec:
    """One fixed process-message kind and its pre-allocation byte ceiling."""

    message_kind: str
    maximum_bytes: int

    def __post_init__(self) -> None:
        if not self.message_kind or self.maximum_bytes < 1:
            raise ValueError("bounded IPC message specification is invalid")


OBSERVATION_MESSAGE = BoundedIpcMessageSpec(
    "observation_frame",
    MAX_OBSERVATION_FRAME_BYTES,
)
ACKNOWLEDGEMENT_MESSAGE = BoundedIpcMessageSpec(
    "observation_acknowledgement",
    MAX_OBSERVATION_ACK_BYTES,
)
RECEIPT_MESSAGE = BoundedIpcMessageSpec(
    "terminal_receipt",
    MAX_RECEIPT_BYTES,
)


@dataclass(frozen=True, slots=True)
class BoundedIpcMessage:
    """One message admitted by the transport byte ceiling."""

    message_kind: str
    payload: bytes = field(repr=False)
    byte_count: int


class BoundedIpcFailure(RuntimeError):
    """One exact fail-closed process-channel boundary result."""

    def __init__(
        self,
        *,
        category: str,
        source_boundary: str,
        message_kind: str,
    ) -> None:
        self.category = category
        self.source_boundary = source_boundary
        self.message_kind = message_kind
        super().__init__(f"{message_kind}: {category} at {source_boundary}")


Decoded = TypeVar("Decoded")


class EventSetter(Protocol):
    def set(self) -> None: ...


def receive_bounded_message(
    connection: Connection,
    spec: BoundedIpcMessageSpec,
    *,
    timeout_seconds: float,
    channel_settlement_timeout_seconds: float = 1.0,
) -> BoundedIpcMessage:
    """Receive exactly one bounded message from a closing one-shot channel."""

    if connection.closed:
        _fail_closed(connection, spec, "receiver_closed", "receiver_preflight")
    if timeout_seconds < 0 or channel_settlement_timeout_seconds < 0:
        _fail_closed(connection, spec, "transport_configuration_invalid", "receiver_preflight")
    if not supports_deadline_bounded_connection_receive():
        _fail_closed(
            connection,
            spec,
            "transport_unsupported",
            "receiver_preflight",
        )
    payload = _receive_connection_frame(
        connection,
        spec,
        deadline=time.monotonic() + timeout_seconds,
    )

    if not payload:
        _fail_closed(connection, spec, "zero_length_message", "transport_body")
    if len(payload) > spec.maximum_bytes:
        _fail_closed(connection, spec, "message_overflow", "transport_header")
    _require_one_shot_channel_completion(
        connection,
        spec,
        timeout_seconds=channel_settlement_timeout_seconds,
    )
    return BoundedIpcMessage(spec.message_kind, payload, len(payload))


def receive_bounded_and_decode(
    connection: Connection,
    spec: BoundedIpcMessageSpec,
    decoder: Callable[[bytes], Decoded],
    *,
    timeout_seconds: float,
    channel_settlement_timeout_seconds: float = 1.0,
) -> Decoded:
    """Invoke application decoding only after bounded transport admission."""

    message = receive_bounded_message(
        connection,
        spec,
        timeout_seconds=timeout_seconds,
        channel_settlement_timeout_seconds=channel_settlement_timeout_seconds,
    )
    try:
        return decoder(message.payload)
    except BaseException:
        connection.close()
        raise


def supports_raw_connection_fault_injection() -> bool:
    """Return whether fixed-header partial-message probes are supported."""

    return os.name == "posix"


def supports_deadline_bounded_connection_receive() -> bool:
    """Return whether fixed-header reads can enforce a whole-frame deadline."""

    return os.name == "posix"


def write_raw_connection_frame(
    connection: Connection,
    *,
    declared_length: int,
    body: bytes,
    header_bytes: int = 4,
) -> None:
    """Inject a CPython Connection frame for private process fault tests."""

    if not supports_raw_connection_fault_injection():
        raise RuntimeError("raw Connection fault injection is unsupported")
    if declared_length < 0 or declared_length > 0x7FFFFFFF:
        raise ValueError("raw Connection frame length is invalid")
    if header_bytes < 0 or header_bytes > 4:
        raise ValueError("raw Connection header length is invalid")
    header = struct.pack("!i", declared_length)
    os.write(connection.fileno(), header[:header_bytes] + body)


def process_hold_partial_frame(
    connection: Connection,
    declared_length: int,
    body: bytes,
    header_bytes: int,
    ready_event: EventSetter,
    hold_seconds: float,
) -> None:
    """Hold a deliberately partial frame open past the receiver deadline."""

    try:
        write_raw_connection_frame(
            connection,
            declared_length=declared_length,
            body=body,
            header_bytes=header_bytes,
        )
        ready_event.set()
        time.sleep(hold_seconds)
    finally:
        connection.close()


def _require_one_shot_channel_completion(
    connection: Connection,
    spec: BoundedIpcMessageSpec,
    *,
    timeout_seconds: float,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    header = bytearray()
    while len(header) < 4:
        if not _wait_for_readable(connection, spec, deadline):
            if header:
                _fail_closed(
                    connection,
                    spec,
                    "unexpected_partial_second_message",
                    "transport_frame",
                )
            _fail_closed(
                connection,
                spec,
                "message_channel_not_closed",
                "transport_settlement",
            )
        chunk = _read_connection_bytes(
            connection,
            spec,
            4 - len(header),
            category="unexpected_partial_second_message",
            boundary="transport_frame",
        )
        if not chunk:
            if header:
                _fail_closed(
                    connection,
                    spec,
                    "unexpected_partial_second_message",
                    "transport_frame",
                )
            connection.close()
            return
        header.extend(chunk)
    _fail_closed(
        connection,
        spec,
        "unexpected_second_message",
        "transport_sequence",
    )


def _receive_connection_frame(
    connection: Connection,
    spec: BoundedIpcMessageSpec,
    *,
    deadline: float,
) -> bytes:
    header = _read_exact_frame_part(
        connection,
        spec,
        4,
        deadline,
        initial_header=True,
    )
    declared_length = struct.unpack("!i", header)[0]
    if declared_length == -1:
        extended = _read_exact_frame_part(
            connection,
            spec,
            8,
            deadline,
            initial_header=False,
        )
        declared_length = struct.unpack("!Q", extended)[0]
    elif declared_length < 0:
        _fail_closed(
            connection,
            spec,
            "message_header_invalid",
            "transport_header",
        )
    if declared_length > spec.maximum_bytes:
        _fail_closed(connection, spec, "message_overflow", "transport_header")
    return _read_exact_frame_part(
        connection,
        spec,
        declared_length,
        deadline,
        initial_header=False,
    )


def _read_exact_frame_part(
    connection: Connection,
    spec: BoundedIpcMessageSpec,
    byte_count: int,
    deadline: float,
    *,
    initial_header: bool,
) -> bytes:
    received = bytearray()
    while len(received) < byte_count:
        if not _wait_for_readable(connection, spec, deadline):
            boundary = (
                "transport_poll"
                if initial_header and not received
                else "transport_frame"
            )
            _fail_closed(connection, spec, "message_timeout", boundary)
        chunk = _read_connection_bytes(
            connection,
            spec,
            byte_count - len(received),
            category="sender_exit_during_message",
            boundary="transport_frame",
        )
        if not chunk:
            if initial_header and not received:
                _fail_closed(
                    connection,
                    spec,
                    "sender_exit_before_message",
                    "transport_header",
                )
            _fail_closed(
                connection,
                spec,
                "sender_exit_during_message",
                "transport_frame",
            )
        received.extend(chunk)
    return bytes(received)


def _wait_for_readable(
    connection: Connection,
    spec: BoundedIpcMessageSpec,
    deadline: float,
) -> bool:
    remaining = max(0.0, deadline - time.monotonic())
    try:
        readable, _, _ = select.select([connection.fileno()], [], [], remaining)
    except (OSError, ValueError) as error:
        _fail_closed(
            connection,
            spec,
            "receiver_closed",
            "transport_poll",
            cause=error,
        )
    return bool(readable)


def _read_connection_bytes(
    connection: Connection,
    spec: BoundedIpcMessageSpec,
    byte_count: int,
    *,
    category: str,
    boundary: str,
) -> bytes:
    try:
        return os.read(connection.fileno(), byte_count)
    except (OSError, ValueError) as error:
        _fail_closed(connection, spec, category, boundary, cause=error)


def _fail_closed(
    connection: Connection,
    spec: BoundedIpcMessageSpec,
    category: str,
    source_boundary: str,
    *,
    cause: BaseException | None = None,
) -> NoReturn:
    try:
        connection.close()
    finally:
        failure = BoundedIpcFailure(
            category=category,
            source_boundary=source_boundary,
            message_kind=spec.message_kind,
        )
        if cause is None:
            raise failure
        raise failure from cause
