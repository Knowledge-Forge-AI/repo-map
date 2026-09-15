"""Pre-allocation-bounded one-shot IPC for startup preparation."""

from __future__ import annotations

from dataclasses import dataclass
from multiprocessing.connection import Connection
import os
import select
import struct
import time


@dataclass(frozen=True, slots=True)
class BoundedMessageSpec:
    message_kind: str
    maximum_bytes: int

    def __post_init__(self) -> None:
        if not self.message_kind or self.maximum_bytes < 1:
            raise ValueError("preparation IPC specification is invalid")


OBSERVATION_MESSAGE = BoundedMessageSpec("observation_frame", 4_096)
ACKNOWLEDGEMENT_MESSAGE = BoundedMessageSpec(
    "observation_acknowledgement",
    2_048,
)
RECEIPT_MESSAGE = BoundedMessageSpec("terminal_receipt", 65_536)
FAILURE_MESSAGE = BoundedMessageSpec("preparation_failure", 2_048)
READINESS_MESSAGE = BoundedMessageSpec("worker_readiness", 256)


class PreparationIpcError(RuntimeError):
    """One privacy-safe fail-closed transport result."""

    def __init__(self, category: str, boundary: str, message_kind: str) -> None:
        self.category = category
        self.boundary = boundary
        self.message_kind = message_kind
        super().__init__(f"{message_kind}: {category} at {boundary}")


def send_one_bounded(
    connection: Connection,
    payload: bytes,
    spec: BoundedMessageSpec,
) -> None:
    """Send one admitted message and close the one-shot sender."""

    try:
        if (
            not isinstance(payload, bytes)
            or not payload
            or len(payload) > spec.maximum_bytes
        ):
            raise PreparationIpcError(
                "message_overflow",
                "transport_sender",
                spec.message_kind,
            )
        connection.send_bytes(payload)
    finally:
        connection.close()


def receive_one_bounded(
    connection: Connection,
    spec: BoundedMessageSpec,
    *,
    timeout_seconds: float,
    settlement_timeout_seconds: float,
) -> bytes:
    """Receive exactly one bounded message and require sender EOF."""

    if (
        connection.closed
        or timeout_seconds <= 0
        or settlement_timeout_seconds <= 0
    ):
        _fail(connection, spec, "transport_configuration_invalid", "preflight")
    if os.name == "posix":
        payload = _receive_posix(
            connection,
            spec,
            deadline=time.monotonic() + timeout_seconds,
        )
        _require_posix_eof(
            connection,
            spec,
            deadline=time.monotonic() + settlement_timeout_seconds,
        )
    else:  # pragma: no cover - native Windows runner
        if not connection.poll(timeout_seconds):
            _fail(connection, spec, "message_timeout", "transport_poll")
        try:
            payload = connection.recv_bytes(maxlength=spec.maximum_bytes)
        except (EOFError, OSError) as error:
            _fail(
                connection,
                spec,
                "sender_exit_during_message",
                "transport_frame",
                cause=error,
            )
        if not connection.poll(settlement_timeout_seconds):
            _fail(
                connection,
                spec,
                "message_channel_not_closed",
                "transport_settlement",
            )
        try:
            connection.recv_bytes(maxlength=spec.maximum_bytes)
        except EOFError:
            connection.close()
        else:
            _fail(
                connection,
                spec,
                "unexpected_second_message",
                "transport_sequence",
            )
    if not payload:
        _fail(connection, spec, "zero_length_message", "transport_body")
    return payload


def _receive_posix(
    connection: Connection,
    spec: BoundedMessageSpec,
    *,
    deadline: float,
) -> bytes:
    header = _read_exact(connection, spec, 4, deadline, initial=True)
    declared_length = struct.unpack("!i", header)[0]
    if declared_length == -1:
        extended = _read_exact(connection, spec, 8, deadline, initial=False)
        declared_length = struct.unpack("!Q", extended)[0]
    elif declared_length < 0:
        _fail(connection, spec, "message_header_invalid", "transport_header")
    if declared_length > spec.maximum_bytes:
        _fail(connection, spec, "message_overflow", "transport_header")
    return _read_exact(
        connection,
        spec,
        declared_length,
        deadline,
        initial=False,
    )


def _read_exact(
    connection: Connection,
    spec: BoundedMessageSpec,
    byte_count: int,
    deadline: float,
    *,
    initial: bool,
) -> bytes:
    result = bytearray()
    while len(result) < byte_count:
        if not _wait_readable(connection, spec, deadline):
            boundary = "transport_poll" if initial and not result else "transport_frame"
            _fail(connection, spec, "message_timeout", boundary)
        try:
            chunk = os.read(connection.fileno(), byte_count - len(result))
        except (OSError, ValueError) as error:
            _fail(
                connection,
                spec,
                "receiver_closed",
                "transport_frame",
                cause=error,
            )
        if not chunk:
            category = (
                "sender_exit_before_message"
                if initial and not result
                else "sender_exit_during_message"
            )
            _fail(connection, spec, category, "transport_frame")
        result.extend(chunk)
    return bytes(result)


def _require_posix_eof(
    connection: Connection,
    spec: BoundedMessageSpec,
    *,
    deadline: float,
) -> None:
    header = bytearray()
    while len(header) < 4:
        if not _wait_readable(connection, spec, deadline):
            category = (
                "unexpected_partial_second_message"
                if header
                else "message_channel_not_closed"
            )
            _fail(connection, spec, category, "transport_settlement")
        try:
            chunk = os.read(connection.fileno(), 4 - len(header))
        except (OSError, ValueError) as error:
            _fail(
                connection,
                spec,
                "receiver_closed",
                "transport_settlement",
                cause=error,
            )
        if not chunk:
            if header:
                _fail(
                    connection,
                    spec,
                    "unexpected_partial_second_message",
                    "transport_frame",
                )
            connection.close()
            return
        header.extend(chunk)
    _fail(
        connection,
        spec,
        "unexpected_second_message",
        "transport_sequence",
    )


def _wait_readable(
    connection: Connection,
    spec: BoundedMessageSpec,
    deadline: float,
) -> bool:
    try:
        readable, _, _ = select.select(
            [connection.fileno()],
            [],
            [],
            max(0.0, deadline - time.monotonic()),
        )
    except (OSError, ValueError) as error:
        _fail(
            connection,
            spec,
            "receiver_closed",
            "transport_poll",
            cause=error,
        )
    return bool(readable)


def _fail(
    connection: Connection,
    spec: BoundedMessageSpec,
    category: str,
    boundary: str,
    *,
    cause: BaseException | None = None,
) -> None:
    try:
        connection.close()
    finally:
        error = PreparationIpcError(category, boundary, spec.message_kind)
        if cause is None:
            raise error
        raise error from cause


__all__ = [
    "ACKNOWLEDGEMENT_MESSAGE",
    "BoundedMessageSpec",
    "FAILURE_MESSAGE",
    "OBSERVATION_MESSAGE",
    "PreparationIpcError",
    "READINESS_MESSAGE",
    "RECEIPT_MESSAGE",
    "receive_one_bounded",
    "send_one_bounded",
]
