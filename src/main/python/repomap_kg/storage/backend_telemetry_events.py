"""Versioned, bounded private-pipe events for PostgreSQL ownership telemetry."""

from __future__ import annotations

import fcntl
import json
import math
import os
import select
import stat
import struct
import time
from collections.abc import Callable
from typing import BinaryIO

from repomap_kg.storage.backend_ownership import ConnectionRole
from repomap_kg.storage.backend_connection_telemetry import BackendTelemetry
from repomap_kg.storage.backend_telemetry_contracts import (
    ConnectionTelemetryError,
    ConnectionTelemetryEvent,
    TelemetryEventKind,
)

__all__ = [
    "MAX_TELEMETRY_FRAME_BYTES",
    "DEFAULT_READY_ACK_TIMEOUT_SECONDS",
    "ConnectionTelemetryError",
    "ConnectionTelemetryEvent",
    "TelemetryEventKind",
    "frame_telemetry_event",
    "parse_telemetry_frame",
    "read_telemetry_event",
    "telemetry_from_inherited_fd",
    "telemetry_from_inherited_fds",
    "write_telemetry_ready_ack",
]

MAX_TELEMETRY_FRAME_BYTES = 512
DEFAULT_READY_ACK_TIMEOUT_SECONDS = 5.0
_FRAME_LENGTH = struct.Struct("!I")
_READY_ACK_FRAME = struct.Struct("!QI")
_PAYLOAD_FIELDS = frozenset(
    {
        "schema_version",
        "connection_sequence",
        "connection_generation",
        "connection_role",
        "backend_pid",
        "event",
        "monotonic_ns",
    }
)


def frame_telemetry_event(event: ConnectionTelemetryEvent) -> bytes:
    """Serialize one bounded versioned event for a private pipe."""

    payload = json.dumps(
        event.to_payload(),
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(payload) > MAX_TELEMETRY_FRAME_BYTES:
        raise ConnectionTelemetryError("backend telemetry frame is invalid")
    return _FRAME_LENGTH.pack(len(payload)) + payload


def parse_telemetry_frame(frame: bytes) -> ConnectionTelemetryEvent:
    """Parse exactly one bounded versioned private-pipe frame."""

    if len(frame) < _FRAME_LENGTH.size:
        raise ConnectionTelemetryError("backend telemetry frame is invalid")
    (payload_length,) = _FRAME_LENGTH.unpack(frame[: _FRAME_LENGTH.size])
    if (
        payload_length > MAX_TELEMETRY_FRAME_BYTES
        or len(frame) != _FRAME_LENGTH.size + payload_length
    ):
        raise ConnectionTelemetryError("backend telemetry frame is invalid")
    try:
        payload = json.loads(frame[_FRAME_LENGTH.size :].decode("utf-8"))
        return _event_from_payload(payload)
    except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ConnectionTelemetryError("backend telemetry frame is invalid") from error


def read_telemetry_event(
    stream: BinaryIO,
    *,
    readiness: Callable[[], None] | None = None,
) -> ConnectionTelemetryEvent | None:
    """Read one complete event from a private inherited pipe."""

    if readiness is not None:
        readiness()
    header = _read_exact(stream, _FRAME_LENGTH.size, allow_eof=True)
    if header is None:
        return None
    (payload_length,) = _FRAME_LENGTH.unpack(header)
    if payload_length > MAX_TELEMETRY_FRAME_BYTES:
        raise ConnectionTelemetryError("backend telemetry frame is invalid")
    payload = _read_exact(stream, payload_length, allow_eof=False)
    assert payload is not None
    return parse_telemetry_frame(header + payload)


def telemetry_from_inherited_fd(
    fd: int,
    *,
    monotonic_ns: Callable[[], int] = time.monotonic_ns,
) -> BackendTelemetry:
    """Create one-way audit telemetry for a private inherited FIFO."""

    return BackendTelemetry(
        _inherited_fd_sink(fd),
        monotonic_ns=monotonic_ns,
    )


def telemetry_from_inherited_fds(
    event_fd: int,
    acknowledgement_fd: int,
    *,
    ready_ack_timeout_seconds: float = DEFAULT_READY_ACK_TIMEOUT_SECONDS,
    monotonic_ns: Callable[[], int] = time.monotonic_ns,
) -> BackendTelemetry:
    """Create exact-attribution telemetry from private event and ack FIFOs."""

    return BackendTelemetry(
        _inherited_fd_sink(event_fd),
        ready_acknowledger=_inherited_ready_acknowledger(
            acknowledgement_fd,
            ready_ack_timeout_seconds,
        ),
        monotonic_ns=monotonic_ns,
    )


def write_telemetry_ready_ack(
    acknowledgement_fd: int,
    event: ConnectionTelemetryEvent,
) -> None:
    """Acknowledge one registered ready event through a private FIFO."""

    if event.event is not TelemetryEventKind.CONNECTION_READY:
        raise ConnectionTelemetryError("backend telemetry acknowledgement is invalid")
    fd = _validated_inherited_fifo(acknowledgement_fd, writable=True)
    try:
        frame = _READY_ACK_FRAME.pack(
            event.connection_sequence,
            event.connection_generation,
        )
    except struct.error as error:
        raise ConnectionTelemetryError(
            "backend telemetry acknowledgement is invalid"
        ) from error
    try:
        written = os.write(fd, frame)
    except OSError as error:
        raise ConnectionTelemetryError(
            "backend telemetry acknowledgement failed"
        ) from error
    if written != len(frame):
        raise ConnectionTelemetryError("backend telemetry acknowledgement failed")


def _inherited_fd_sink(
    fd: int,
) -> Callable[[ConnectionTelemetryEvent], None]:
    fd = _validated_inherited_fifo(fd, writable=True)

    def write_event(event: ConnectionTelemetryEvent) -> None:
        frame = frame_telemetry_event(event)
        try:
            written = os.write(fd, frame)
        except OSError as error:
            raise ConnectionTelemetryError(
                "backend telemetry channel failed"
            ) from error
        if written != len(frame):
            raise ConnectionTelemetryError("backend telemetry channel failed")

    return write_event


def _inherited_ready_acknowledger(
    fd: int,
    timeout_seconds: float,
) -> Callable[[ConnectionTelemetryEvent], None]:
    _validate_ready_ack_timeout(timeout_seconds)
    fd = _validated_inherited_fifo(fd, writable=False)

    def acknowledge(event: ConnectionTelemetryEvent) -> None:
        if event.event is not TelemetryEventKind.CONNECTION_READY:
            raise ConnectionTelemetryError("backend telemetry acknowledgement is invalid")
        payload = _read_ready_ack(fd, timeout_seconds)
        sequence, generation = _READY_ACK_FRAME.unpack(payload)
        if (
            sequence != event.connection_sequence
            or generation != event.connection_generation
        ):
            raise ConnectionTelemetryError("backend telemetry acknowledgement failed")

    return acknowledge


def _validated_inherited_fifo(fd: int, *, writable: bool) -> int:
    try:
        if isinstance(fd, bool) or not isinstance(fd, int) or fd < 0:
            raise ValueError
        if not stat.S_ISFIFO(os.fstat(fd).st_mode):
            raise ValueError
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        access_mode = flags & os.O_ACCMODE
        if writable and access_mode == os.O_RDONLY:
            raise ValueError
        if not writable and access_mode == os.O_WRONLY:
            raise ValueError
        if not writable:
            os.set_blocking(fd, False)
    except (OSError, ValueError) as error:
        raise ConnectionTelemetryError(
            "backend telemetry channel is unavailable"
        ) from error

    return fd


def _validate_ready_ack_timeout(timeout_seconds: float) -> None:
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
    ):
        raise ConnectionTelemetryError("backend telemetry acknowledgement is unavailable")


def _read_ready_ack(fd: int, timeout_seconds: float) -> bytes:
    deadline = time.monotonic() + timeout_seconds
    chunks: list[bytes] = []
    remaining = _READY_ACK_FRAME.size
    while remaining:
        wait_seconds = deadline - time.monotonic()
        if wait_seconds <= 0:
            raise ConnectionTelemetryError("backend telemetry acknowledgement failed")
        try:
            readable, _, _ = select.select((fd,), (), (), wait_seconds)
        except (OSError, ValueError) as error:
            raise ConnectionTelemetryError(
                "backend telemetry acknowledgement failed"
            ) from error
        if not readable:
            raise ConnectionTelemetryError("backend telemetry acknowledgement failed")
        try:
            chunk = os.read(fd, remaining)
        except BlockingIOError:
            continue
        except OSError as error:
            raise ConnectionTelemetryError(
                "backend telemetry acknowledgement failed"
            ) from error
        if not chunk:
            raise ConnectionTelemetryError("backend telemetry acknowledgement failed")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _event_from_payload(payload: object) -> ConnectionTelemetryEvent:
    if not isinstance(payload, dict) or set(payload) != _PAYLOAD_FIELDS:
        raise ValueError
    return ConnectionTelemetryEvent(
        schema_version=_payload_int(payload, "schema_version"),
        connection_sequence=_payload_int(payload, "connection_sequence"),
        connection_generation=_payload_int(payload, "connection_generation"),
        connection_role=ConnectionRole(_payload_str(payload, "connection_role")),
        backend_pid=_payload_optional_int(payload, "backend_pid"),
        event=TelemetryEventKind(_payload_str(payload, "event")),
        monotonic_ns=_payload_int(payload, "monotonic_ns"),
    )


def _payload_int(payload: dict[str, object], name: str) -> int:
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError
    return value


def _payload_optional_int(payload: dict[str, object], name: str) -> int | None:
    value = payload[name]
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError
    return value


def _payload_str(payload: dict[str, object], name: str) -> str:
    value = payload[name]
    if not isinstance(value, str):
        raise ValueError
    return value


def _read_exact(
    stream: BinaryIO,
    size: int,
    *,
    allow_eof: bool,
) -> bytes | None:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            if allow_eof and not chunks:
                return None
            raise ConnectionTelemetryError("backend telemetry frame is invalid")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)
