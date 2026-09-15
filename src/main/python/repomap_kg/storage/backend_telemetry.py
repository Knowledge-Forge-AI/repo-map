"""Public facade for bounded local PostgreSQL ownership telemetry."""

from repomap_kg.storage.backend_connection_telemetry import BackendTelemetry
from repomap_kg.storage.backend_ownership_registry import BackendOwnershipRegistry
from repomap_kg.storage.backend_telemetry_events import (
    DEFAULT_READY_ACK_TIMEOUT_SECONDS,
    MAX_TELEMETRY_FRAME_BYTES,
    ConnectionTelemetryError,
    ConnectionTelemetryEvent,
    TelemetryEventKind,
    frame_telemetry_event,
    parse_telemetry_frame,
    read_telemetry_event,
    telemetry_from_inherited_fd,
    telemetry_from_inherited_fds,
    write_telemetry_ready_ack,
)

__all__ = [
    "DEFAULT_READY_ACK_TIMEOUT_SECONDS",
    "MAX_TELEMETRY_FRAME_BYTES",
    "BackendOwnershipRegistry",
    "BackendTelemetry",
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
