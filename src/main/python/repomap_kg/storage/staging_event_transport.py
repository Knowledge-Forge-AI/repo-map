"""Acknowledged private transport for staged refresh measurement events."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
import json
import socket
import struct
from time import monotonic
from typing import Callable


__all__ = (
    "StagingEventChannel",
    "StagingEventFrame",
    "StagingEventTransportError",
    "staging_event_channel_from_inherited_fd",
)

_SCHEMA_VERSION = 1
_MAX_FRAME_BYTES = 16_384
_HEADER_SIZE = 4
_ACK = b"\x06"
_FRAME_CATEGORIES = frozenset({"authority", "measurement", "operation", "phase"})


class StagingEventTransportError(RuntimeError):
    """The private staging event channel violated its bounded contract."""


class _SendState(Enum):
    IDLE = auto()
    SEQUENCE_RESERVED = auto()
    WRITE_IN_PROGRESS = auto()
    ACK_PENDING = auto()
    BROKEN = auto()


@dataclass(frozen=True)
class StagingEventFrame:
    """One strictly sequenced private staging event frame."""

    sequence: int
    category: str
    payload: dict[str, object]


class StagingEventChannel:
    """Exchange bounded JSON frames with per-frame acknowledgement."""

    def __init__(
        self,
        connection: socket.socket,
        *,
        acknowledgement_timeout_seconds: float = 2.0,
    ) -> None:
        if acknowledgement_timeout_seconds <= 0:
            raise ValueError("staging event acknowledgement timeout is invalid")
        self._connection = connection
        self._acknowledgement_timeout_seconds = acknowledgement_timeout_seconds
        self._send_sequence = 0
        self._send_state = _SendState.IDLE
        self._receive_sequence = 0
        self._closed = False

    def send(self, category: str, payload: dict[str, object]) -> None:
        """Send one event frame and require its acknowledgement."""

        self._require_sendable()
        if category not in _FRAME_CATEGORIES:
            raise StagingEventTransportError("staging event category is invalid")
        if not isinstance(payload, dict):
            raise StagingEventTransportError("staging event payload is invalid")
        sequence = self._send_sequence + 1
        body = json.dumps(
            {
                "schema_version": _SCHEMA_VERSION,
                "frame_sequence": sequence,
                "frame_category": category,
                "payload": payload,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(body) > _MAX_FRAME_BYTES:
            raise StagingEventTransportError("staging event frame is too large")
        wire_frame = struct.pack("!I", len(body)) + body
        previous_timeout = self._connection.gettimeout()
        try:
            self._send_state = _SendState.SEQUENCE_RESERVED
            self._send_sequence = sequence
            self._send_state = _SendState.WRITE_IN_PROGRESS
            try:
                self._connection.sendall(wire_frame)
            except BaseException as error:
                self._send_state = _SendState.BROKEN
                if isinstance(error, OSError):
                    raise StagingEventTransportError(
                        "staging event send failed"
                    ) from error
                raise
            self._settle_acknowledgement()
        except BaseException:
            if self._send_state is not _SendState.IDLE:
                self._send_state = _SendState.BROKEN
            raise
        finally:
            try:
                self._connection.settimeout(previous_timeout)
            except OSError as error:
                if self._send_state is not _SendState.BROKEN:
                    self._send_state = _SendState.BROKEN
                    raise StagingEventTransportError(
                        "staging event send failed"
                    ) from error

    def receive(
        self,
        *,
        timeout_seconds: float,
        validator: Callable[[StagingEventFrame], None] | None = None,
        readiness: Callable[[], None] | None = None,
    ) -> StagingEventFrame:
        """Receive, validate, and acknowledge one frame."""

        self._require_open()
        if timeout_seconds <= 0:
            raise ValueError("staging event receive timeout is invalid")
        previous_timeout = self._connection.gettimeout()
        self._connection.settimeout(timeout_seconds)
        try:
            if readiness is not None:
                readiness()
            header = self._recv_exact(_HEADER_SIZE, clean_eof=True)
            (size,) = struct.unpack("!I", header)
            if not 1 <= size <= _MAX_FRAME_BYTES:
                raise StagingEventTransportError("staging event frame size is invalid")
            body = self._recv_exact(size)
        except socket.timeout as error:
            raise TimeoutError("staging event receive timed out") from error
        finally:
            self._connection.settimeout(previous_timeout)
        frame = self._decode_frame(body)
        expected_sequence = self._receive_sequence + 1
        if frame.sequence != expected_sequence:
            raise StagingEventTransportError(
                "staging event sequence is invalid: "
                f"expected={expected_sequence}, received={frame.sequence}"
            )
        if validator is not None:
            validator(frame)
        try:
            self._connection.sendall(_ACK)
        except OSError as error:
            raise StagingEventTransportError(
                "staging event acknowledgement failed"
            ) from error
        self._receive_sequence = frame.sequence
        return frame

    def close(self) -> None:
        """Close the channel; repeated calls are harmless."""

        if self._closed:
            return
        self._closed = True
        try:
            self._connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self._connection.close()

    def _decode_frame(self, body: bytes) -> StagingEventFrame:
        try:
            decoded = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise StagingEventTransportError(
                "staging event frame is invalid"
            ) from error
        if not isinstance(decoded, dict) or set(decoded) != {
            "schema_version",
            "frame_sequence",
            "frame_category",
            "payload",
        }:
            raise StagingEventTransportError("staging event frame fields are invalid")
        if decoded["schema_version"] != _SCHEMA_VERSION:
            raise StagingEventTransportError("staging event schema is invalid")
        sequence = decoded["frame_sequence"]
        category = decoded["frame_category"]
        payload = decoded["payload"]
        if (
            not isinstance(sequence, int)
            or isinstance(sequence, bool)
            or sequence < 1
        ):
            raise StagingEventTransportError("staging event sequence is invalid")
        if category not in _FRAME_CATEGORIES:
            raise StagingEventTransportError("staging event category is invalid")
        if not isinstance(payload, dict):
            raise StagingEventTransportError("staging event payload is invalid")
        return StagingEventFrame(sequence, category, payload)

    def _recv_exact(self, size: int, *, clean_eof: bool = False) -> bytes:
        chunks: list[bytes] = []
        remaining = size
        while remaining:
            chunk = self._connection.recv(remaining)
            if not chunk:
                if clean_eof and remaining == size:
                    raise EOFError("staging event channel closed")
                raise StagingEventTransportError(
                    "staging event channel reached early EOF"
                )
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _settle_acknowledgement(self) -> None:
        self._send_state = _SendState.ACK_PENDING
        deadline = monotonic() + self._acknowledgement_timeout_seconds
        deferred_interrupt: KeyboardInterrupt | None = None
        try:
            while True:
                remaining_seconds = deadline - monotonic()
                if remaining_seconds <= 0:
                    raise TimeoutError(
                        "staging event acknowledgement timed out"
                    )
                try:
                    self._connection.settimeout(remaining_seconds)
                    acknowledgement = self._recv_exact(1)
                except KeyboardInterrupt as error:
                    if deferred_interrupt is None:
                        deferred_interrupt = error
                    continue
                except socket.timeout as error:
                    raise TimeoutError(
                        "staging event acknowledgement timed out"
                    ) from error
                except OSError as error:
                    raise StagingEventTransportError(
                        "staging event acknowledgement failed"
                    ) from error
                if acknowledgement != _ACK:
                    raise StagingEventTransportError(
                        "staging event acknowledgement is invalid"
                    )
                self._send_state = _SendState.IDLE
                break
        except BaseException as error:
            self._send_state = _SendState.BROKEN
            if isinstance(error, KeyboardInterrupt):
                raise
            if deferred_interrupt is not None:
                raise deferred_interrupt from error
            raise
        finally:
            if self._send_state is _SendState.ACK_PENDING:
                self._send_state = _SendState.BROKEN
        if deferred_interrupt is not None:
            raise deferred_interrupt

    def _require_open(self) -> None:
        if self._closed:
            raise StagingEventTransportError("staging event channel is closed")

    def _require_sendable(self) -> None:
        self._require_open()
        if self._send_state is _SendState.BROKEN:
            raise StagingEventTransportError(
                "staging event outgoing channel is broken"
            )
        if self._send_state is not _SendState.IDLE:
            raise StagingEventTransportError(
                "staging event send transaction is active"
            )


def staging_event_channel_from_inherited_fd(fd: int) -> StagingEventChannel:
    """Adopt one inherited connected socket without exposing it publicly."""

    if isinstance(fd, bool) or not isinstance(fd, int) or fd < 0:
        raise StagingEventTransportError("staging event descriptor is invalid")
    try:
        connection = socket.socket(fileno=fd)
    except OSError as error:
        raise StagingEventTransportError(
            "staging event descriptor is unavailable"
        ) from error
    return StagingEventChannel(connection)
