"""Stateful exact ownership registration for local telemetry observers."""

from __future__ import annotations

from collections.abc import Collection

from repomap_kg.storage.backend_ownership import (
    BackendActivity,
    BackendIdentity,
    OwnedBackend,
)
from repomap_kg.storage.backend_telemetry_events import (
    ConnectionTelemetryError,
    ConnectionTelemetryEvent,
    TelemetryEventKind,
)

__all__ = ["BackendOwnershipRegistry"]


class BackendOwnershipRegistry:
    """Track exact active direct identities from an event/activity sequence."""

    def __init__(self) -> None:
        self._pending: dict[tuple[int, int], ConnectionTelemetryEvent] = {}
        self._owned: dict[tuple[int, int], OwnedBackend] = {}

    @property
    def owned_backends(self) -> tuple[OwnedBackend, ...]:
        """Return active direct identities in deterministic local order."""

        return tuple(self._owned[key] for key in sorted(self._owned))

    def accept(
        self,
        event: ConnectionTelemetryEvent,
        activities: Collection[BackendActivity],
        *,
        ready_identity: BackendIdentity | None = None,
    ) -> None:
        """Apply one lifecycle event using the current bounded activity view."""

        key = (event.connection_sequence, event.connection_generation)
        if event.event is TelemetryEventKind.CONNECTION_REPLACED:
            if event.connection_generation <= 1:
                raise ConnectionTelemetryError("backend telemetry state is invalid")
            return
        if event.event is TelemetryEventKind.CONNECTION_OPENED:
            if key in self._pending or key in self._owned:
                raise ConnectionTelemetryError("backend telemetry state is invalid")
            self._pending[key] = event
            return
        if event.event is TelemetryEventKind.CONNECTION_READY:
            opened = self._pending.get(key)
            if opened is None or not _same_connection(opened, event):
                raise ConnectionTelemetryError("backend telemetry state is invalid")
            activity = _exact_client_activity(event, activities, ready_identity)
            self._owned[key] = OwnedBackend(
                connection_sequence=event.connection_sequence,
                connection_generation=event.connection_generation,
                connection_role=event.connection_role,
                identity=activity.identity,
            )
            del self._pending[key]
            return
        if event.event is TelemetryEventKind.CONNECTION_CLOSED:
            owned = self._owned.get(key)
            if owned is None:
                return
            if (
                owned.connection_role is not event.connection_role
                or owned.identity.backend_pid != event.backend_pid
            ):
                raise ConnectionTelemetryError("backend telemetry state is invalid")
            del self._owned[key]
            return
        self._pending.pop(key, None)
        self._owned.pop(key, None)


def _same_connection(
    first: ConnectionTelemetryEvent,
    second: ConnectionTelemetryEvent,
) -> bool:
    return (
        first.connection_role is second.connection_role
        and first.backend_pid == second.backend_pid
    )


def _exact_client_activity(
    event: ConnectionTelemetryEvent,
    activities: Collection[BackendActivity],
    ready_identity: BackendIdentity | None,
) -> BackendActivity:
    if ready_identity is None or ready_identity.backend_pid != event.backend_pid:
        raise ConnectionTelemetryError("backend identity is unavailable")
    matches = [
        activity
        for activity in activities
        if activity.backend_type == "client backend"
        and activity.identity == ready_identity
    ]
    if len(matches) != 1:
        raise ConnectionTelemetryError("backend identity is unavailable")
    return matches[0]
