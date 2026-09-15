"""Bounded acknowledged event transport for SCALE12 child supervision."""

from __future__ import annotations

from dataclasses import dataclass
import json
import socket
import struct
import time
from typing import Final


SCHEMA_VERSION: Final = 1
MAX_FRAME_BYTES: Final = 65_536
_ACK: Final = b"\x06"
_HEADER_SIZE: Final = 4
_FRAME_CATEGORIES: Final = frozenset({"ready", "operation", "terminal"})


class Scale12TransportError(RuntimeError):
    """Raised when the SCALE12 event channel contract is violated."""

    def __init__(
        self,
        message: str,
        *,
        role: str = "scale12_event_transport",
        phase: str | None = None,
        return_classification: str | None = None,
        expected: str | None = None,
        observed: str | None = None,
    ) -> None:
        super().__init__(message)
        self.role = role
        self.phase = phase
        self.return_classification = return_classification
        self.expected = expected
        self.observed = observed
        self.add_note(str(self.structural_evidence()))

    def structural_evidence(self) -> dict[str, str | None]:
        return {
            "role": self.role,
            "phase": self.phase,
            "return_classification": self.return_classification,
            "expected": self.expected,
            "observed": self.observed,
        }


@dataclass(frozen=True)
class Scale12Frame:
    """One validated event-channel frame."""

    sequence: int
    category: str
    payload: dict[str, object]


class Scale12EventChannel:
    """Exchange strictly sequenced JSON frames with per-frame acknowledgement."""

    def __init__(
        self,
        connection: socket.socket,
        *,
        acknowledgement_timeout_seconds: float = 1.0,
    ) -> None:
        if acknowledgement_timeout_seconds <= 0:
            raise ValueError("acknowledgement timeout must be positive")
        self._connection = connection
        self._acknowledgement_timeout_seconds = acknowledgement_timeout_seconds
        self._send_sequence = 0
        self._receive_sequence = 0
        self._closed = False
        self._recv_buffer = bytearray()

    def send(self, category: str, payload: dict[str, object]) -> None:
        """Send one bounded frame and require its acknowledgement."""

        self._require_open()
        if category not in _FRAME_CATEGORIES:
            raise Scale12TransportError("frame category is invalid")
        if not isinstance(payload, dict):
            raise Scale12TransportError("frame payload must be an object")

        sequence = self._send_sequence + 1
        body = json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "frame_sequence": sequence,
                "frame_category": category,
                "payload": payload,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(body) > MAX_FRAME_BYTES:
            raise Scale12TransportError("frame size exceeds the channel limit")

        try:
            self._connection.sendall(struct.pack("!I", len(body)) + body)
            previous_timeout = self._connection.gettimeout()
            self._connection.settimeout(self._acknowledgement_timeout_seconds)
            try:
                acknowledgement = self._recv_ack()
            finally:
                self._connection.settimeout(previous_timeout)
        except socket.timeout as exc:
            raise TimeoutError("event acknowledgement timed out") from exc
        except OSError as exc:
            raise Scale12TransportError("event frame send failed") from exc
        if acknowledgement != _ACK:
            raise Scale12TransportError("event acknowledgement is invalid")
        self._send_sequence = sequence

    def receive(self, *, timeout_seconds: float) -> Scale12Frame:
        """Receive, validate, and acknowledge one frame."""

        self._require_open()
        if timeout_seconds <= 0:
            raise ValueError("receive timeout must be positive")
        previous_timeout = self._connection.gettimeout()
        deadline = time.monotonic() + timeout_seconds
        try:
            while len(self._recv_buffer) < _HEADER_SIZE:
                rem = deadline - time.monotonic()
                if rem <= 0:
                    raise TimeoutError("event frame receive timed out")
                self._connection.settimeout(max(0.001, rem))
                try:
                    chunk = self._connection.recv(4096)
                except socket.timeout as exc:
                    raise TimeoutError("event frame receive timed out") from exc
                if not chunk:
                    observed_bytes = len(self._recv_buffer)
                    raise Scale12TransportError(
                        "event channel reached early EOF",
                        role="scale12_event_transport",
                        phase="transport_receive",
                        expected="exact_4_bytes",
                        observed=f"early_eof_after_{observed_bytes}_bytes",
                    )
                self._recv_buffer.extend(chunk)

            (size,) = struct.unpack("!I", self._recv_buffer[:_HEADER_SIZE])
            if size < 1 or size > MAX_FRAME_BYTES:
                raise Scale12TransportError("frame size is invalid")
            target_len = _HEADER_SIZE + size

            while len(self._recv_buffer) < target_len:
                rem = deadline - time.monotonic()
                if rem <= 0:
                    raise TimeoutError("event frame receive timed out")
                self._connection.settimeout(max(0.001, rem))
                try:
                    chunk = self._connection.recv(min(4096, target_len - len(self._recv_buffer)))
                except socket.timeout as exc:
                    raise TimeoutError("event frame receive timed out") from exc
                if not chunk:
                    observed_payload = len(self._recv_buffer) - _HEADER_SIZE
                    raise Scale12TransportError(
                        "event channel reached early EOF",
                        role="scale12_event_transport",
                        phase="transport_receive",
                        expected=f"exact_{size}_bytes",
                        observed=f"early_eof_after_{observed_payload}_bytes",
                    )
                self._recv_buffer.extend(chunk)

            body = bytes(self._recv_buffer[_HEADER_SIZE:target_len])
            del self._recv_buffer[:target_len]
        finally:
            self._connection.settimeout(previous_timeout)

        frame = self._decode_frame(body)
        expected_sequence = self._receive_sequence + 1
        if frame.sequence != expected_sequence:
            raise Scale12TransportError("event frame sequence is invalid")
        try:
            self._connection.sendall(_ACK)
        except OSError as exc:
            raise Scale12TransportError("event acknowledgement send failed") from exc
        self._receive_sequence = frame.sequence
        return frame

    def close(self) -> None:
        """Close the channel. Repeated close calls are harmless."""

        if self._closed:
            return
        self._closed = True
        try:
            self._connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self._connection.close()

    def _decode_frame(self, body: bytes) -> Scale12Frame:
        try:
            decoded = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise Scale12TransportError("event frame is not valid JSON") from exc
        if not isinstance(decoded, dict):
            raise Scale12TransportError("event frame must be a JSON object")
        if set(decoded) != {
            "schema_version",
            "frame_sequence",
            "frame_category",
            "payload",
        }:
            raise Scale12TransportError("event frame fields are invalid")
        if decoded["schema_version"] != SCHEMA_VERSION:
            raise Scale12TransportError("event frame schema is invalid")
        sequence = decoded["frame_sequence"]
        if (
            not isinstance(sequence, int)
            or isinstance(sequence, bool)
            or sequence < 1
        ):
            raise Scale12TransportError("event frame sequence is invalid")
        category = decoded["frame_category"]
        if not isinstance(category, str) or category not in _FRAME_CATEGORIES:
            raise Scale12TransportError("event frame category is invalid")
        payload = decoded["payload"]
        if not isinstance(payload, dict):
            raise Scale12TransportError("event frame payload must be an object")
        return Scale12Frame(sequence, category, payload)

    def _recv_ack(self) -> bytes:
        if self._recv_buffer:
            ack = bytes(self._recv_buffer[:1])
            del self._recv_buffer[:1]
            return ack
        chunk = self._connection.recv(1)
        if not chunk:
            raise Scale12TransportError(
                "event channel reached early EOF",
                role="scale12_event_transport",
                phase="transport_receive",
                expected="exact_1_bytes",
                observed="early_eof_after_0_bytes",
            )
        return chunk

    def _require_open(self) -> None:
        if self._closed:
            raise Scale12TransportError(
                "event channel is closed",
                role="scale12_event_transport",
                phase="channel_state",
                expected="open_channel",
                observed="closed_channel",
            )
