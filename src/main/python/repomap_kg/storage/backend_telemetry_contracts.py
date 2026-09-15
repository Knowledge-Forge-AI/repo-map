"""Neutral records for source-controlled PostgreSQL connection telemetry."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from repomap_kg.storage.backend_ownership import ConnectionRole

__all__ = [
    "ConnectionTelemetryError",
    "ConnectionTelemetryEvent",
    "TelemetryEventKind",
    "make_telemetry_event",
]

_SCHEMA_VERSION = 1


class ConnectionTelemetryError(RuntimeError):
    """Raised when local ownership telemetry cannot be trusted."""


class TelemetryEventKind(str, Enum):
    """Closed lifecycle events for one source-controlled connection."""

    CONNECTION_OPENED = "connection_opened"
    CONNECTION_READY = "connection_ready"
    CONNECTION_CLOSED = "connection_closed"
    CONNECTION_FAILED = "connection_failed"
    CONNECTION_REPLACED = "connection_replaced"


@dataclass(frozen=True)
class ConnectionTelemetryEvent:
    """One versioned local-only connection lifecycle event."""

    schema_version: int
    connection_sequence: int
    connection_generation: int
    connection_role: ConnectionRole
    backend_pid: int | None
    event: TelemetryEventKind
    monotonic_ns: int

    def __post_init__(self) -> None:
        if self.schema_version != _SCHEMA_VERSION:
            raise ValueError("telemetry schema version is invalid")
        if self.connection_sequence <= 0:
            raise ValueError("telemetry connection sequence is invalid")
        if self.connection_generation <= 0:
            raise ValueError("telemetry connection generation is invalid")
        if self.backend_pid is not None and self.backend_pid <= 0:
            raise ValueError("telemetry backend PID is invalid")
        if (
            self.event is not TelemetryEventKind.CONNECTION_FAILED
            and self.backend_pid is None
        ):
            raise ValueError("telemetry backend PID is required")
        if self.monotonic_ns < 0:
            raise ValueError("telemetry timestamp is invalid")

    def to_payload(self) -> dict[str, int | str | None]:
        """Return the strict allowed-field payload for private transport."""

        return {
            "schema_version": self.schema_version,
            "connection_sequence": self.connection_sequence,
            "connection_generation": self.connection_generation,
            "connection_role": self.connection_role.value,
            "backend_pid": self.backend_pid,
            "event": self.event.value,
            "monotonic_ns": self.monotonic_ns,
        }


def make_telemetry_event(
    kind: TelemetryEventKind,
    *,
    sequence: int,
    generation: int,
    role: ConnectionRole,
    backend_pid: int | None,
    monotonic_ns: int,
) -> ConnectionTelemetryEvent:
    """Create one internal event with the only permitted field family."""

    return ConnectionTelemetryEvent(
        schema_version=_SCHEMA_VERSION,
        connection_sequence=sequence,
        connection_generation=generation,
        connection_role=role,
        backend_pid=backend_pid,
        event=kind,
        monotonic_ns=monotonic_ns,
    )
