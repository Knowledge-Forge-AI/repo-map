"""Read bounded PostgreSQL backend facts for local ownership attribution."""

from __future__ import annotations

from collections.abc import Callable, Collection
from dataclasses import replace
from datetime import datetime
from typing import Any

from repomap_kg.storage.backend_ownership import (
    BackendActivity,
    BackendIdentity,
    ClassifiedBackend,
    OwnedBackend,
    classify_backend_activity,
    public_backend_summary,
)
from repomap_kg.storage.backend_telemetry import (
    BackendOwnershipRegistry,
    ConnectionTelemetryEvent,
    TelemetryEventKind,
    write_telemetry_ready_ack,
)

__all__ = [
    "MAX_OBSERVER_CONNECTIONS",
    "BackendObservationError",
    "BackendOwnershipObserver",
    "current_backend_identity",
    "read_backend_activity",
]

MAX_OBSERVER_CONNECTIONS = 1
_ACTIVITY_SQL = (
    "SELECT pid, backend_start, backend_type, leader_pid "
    "FROM pg_stat_activity ORDER BY pid"
)
_CURRENT_ACTIVITY_SQL = (
    "SELECT pid, backend_start, backend_type, leader_pid "
    "FROM pg_stat_activity WHERE pid = pg_backend_pid()"
)


class BackendObservationError(RuntimeError):
    """Raised when a bounded local observer cannot establish exact identity."""

    observer_identity_changed: bool = False


class BackendOwnershipObserver:
    """Own one bounded observer set and classify snapshots without SQL payloads."""

    def __init__(self, registry: BackendOwnershipRegistry | None = None) -> None:
        self._registry = registry or BackendOwnershipRegistry()
        self._observer_identities: list[BackendIdentity] = []
        self._observer_connection: Any | None = None

    @property
    def observer_identities(self) -> tuple[BackendIdentity, ...]:
        """Return exactly registered observer identities in insertion order."""

        return tuple(self._observer_identities)

    @property
    def owned_backends(self) -> tuple[OwnedBackend, ...]:
        """Return exact direct-owned identities currently registered."""

        return self._registry.owned_backends

    def register_observer(self, identity: BackendIdentity) -> None:
        """Register one exact observer backend without using heuristic identity."""

        if identity in self._observer_identities:
            return
        if len(self._observer_identities) >= MAX_OBSERVER_CONNECTIONS:
            raise BackendObservationError("observer limit exceeded")
        self._observer_identities.append(identity)

    def register_connection(self, connection: Any) -> BackendIdentity:
        """Read and register the caller's exact observer backend identity."""

        _require_autocommit_observer_connection(connection)
        identity = current_backend_identity(connection)
        if self._observer_connection is None:
            self.register_observer(identity)
            self._observer_connection = connection
        elif (
            connection is not self._observer_connection
            or identity not in self._observer_identities
        ):
            raise BackendObservationError("observer connection is unavailable")
        return identity

    def event_sink(
        self,
        connection: Any,
    ) -> Callable[[ConnectionTelemetryEvent, Any | None], None]:
        """Bind a synchronous source-liveness callback to one observer backend."""

        self._require_registered_connection(connection)

        def accept(
            event: ConnectionTelemetryEvent,
            source_connection: Any | None,
        ) -> None:
            self.accept_event(event, connection, source_connection)

        return accept

    def accept_event(
        self,
        event: ConnectionTelemetryEvent,
        connection: Any,
        source_connection: Any | None,
    ) -> None:
        """Acknowledge a lifecycle event through the bound observer connection."""

        self._require_registered_connection(connection)
        if event.event is TelemetryEventKind.CONNECTION_OPENED:
            _require_live_source_connection(source_connection, event)
            self._registry.accept(event, ())
            return
        if event.event is TelemetryEventKind.CONNECTION_READY:
            _require_live_source_connection(source_connection, event)
            activities = read_backend_activity(connection)
            ready_identity = _ready_identity(event, activities)
            self._registry.accept(
                event,
                activities,
                ready_identity=ready_identity,
            )
            return
        self._registry.accept(event, ())

    def consume_pipe_event(
        self,
        event: ConnectionTelemetryEvent,
        connection: Any,
        acknowledgement_fd: int,
    ) -> None:
        """Register a private-pipe event before acknowledging a ready source."""

        self._require_registered_connection(connection)
        if event.event is TelemetryEventKind.CONNECTION_OPENED:
            self._registry.accept(event, ())
            return
        if event.event is TelemetryEventKind.CONNECTION_READY:
            activities = read_backend_activity(connection)
            ready_identity = _ready_identity(event, activities)
            self._registry.accept(
                event,
                activities,
                ready_identity=ready_identity,
            )
            try:
                write_telemetry_ready_ack(acknowledgement_fd, event)
            except Exception:
                self._registry.accept(
                    replace(event, event=TelemetryEventKind.CONNECTION_FAILED),
                    (),
                )
                raise
            return
        self._registry.accept(event, ())

    def classify(self, connection: Any) -> tuple[ClassifiedBackend, ...]:
        """Classify a current fixed PostgreSQL activity projection."""

        _require_autocommit_observer_connection(connection)
        if connection is not self._observer_connection:
            raise BackendObservationError("observer connection is unavailable")
        activities = read_backend_activity(connection)
        if not any(
            activity.identity in self._observer_identities
            for activity in activities
        ):
            error = BackendObservationError("observer connection is unavailable")
            error.observer_identity_changed = True
            raise error
        return classify_backend_activity(
            activities,
            self._registry.owned_backends,
            self._observer_identities,
        )

    def public_summary(self, connection: Any) -> dict[str, int]:
        """Return category counts only for a public-safe observer projection."""

        return public_backend_summary(self.classify(connection))

    def _require_registered_connection(self, connection: Any) -> None:
        _require_autocommit_observer_connection(connection)
        if connection is not self._observer_connection:
            raise BackendObservationError("observer connection is unavailable")
        current_identity = current_backend_identity(connection)
        if current_identity not in self._observer_identities:
            error = BackendObservationError("observer connection is unavailable")
            error.observer_identity_changed = True
            raise error


def read_backend_activity(connection: Any) -> tuple[BackendActivity, ...]:
    """Read only PID, lifecycle, type, and leader identity from PostgreSQL."""

    try:
        rows = connection.execute(_ACTIVITY_SQL).fetchall()
        return tuple(_activity_from_row(row) for row in rows)
    except (AttributeError, TypeError, ValueError) as error:
        raise BackendObservationError("backend activity is unavailable") from error


def current_backend_identity(connection: Any) -> BackendIdentity:
    """Read the observer's own exact PID and backend_start identity."""

    try:
        row = connection.execute(_CURRENT_ACTIVITY_SQL).fetchone()
        activity = _activity_from_row(row)
    except (AttributeError, TypeError, ValueError) as error:
        raise BackendObservationError("backend identity is unavailable") from error
    if activity.backend_type != "client backend":
        raise BackendObservationError("backend identity is unavailable")
    return activity.identity


def _require_autocommit_observer_connection(connection: Any) -> None:
    """Require a state-free observer connection with fresh activity snapshots."""

    try:
        autocommit = connection.autocommit
    except AttributeError as error:
        raise BackendObservationError("observer connection is unavailable") from error
    if autocommit is not True:
        raise BackendObservationError("observer connection is unavailable")


def _require_live_source_connection(
    connection: Any | None,
    event: ConnectionTelemetryEvent,
) -> None:
    if connection is None:
        raise BackendObservationError("source connection is unavailable")
    try:
        backend_pid = connection.info.backend_pid
        closed = connection.closed
    except AttributeError as error:
        raise BackendObservationError("source connection is unavailable") from error
    if (
        isinstance(backend_pid, bool)
        or not isinstance(backend_pid, int)
        or backend_pid != event.backend_pid
        or closed is not False
    ):
        raise BackendObservationError("source connection is unavailable")


def _ready_identity(
    event: ConnectionTelemetryEvent,
    activities: Collection[BackendActivity],
) -> BackendIdentity:
    matches = [
        activity.identity
        for activity in activities
        if activity.backend_type == "client backend"
        and activity.identity.backend_pid == event.backend_pid
    ]
    if len(matches) != 1:
        raise BackendObservationError("backend identity is unavailable")
    return matches[0]


def _activity_from_row(row: object) -> BackendActivity:
    if not isinstance(row, tuple) or len(row) != 4:
        raise ValueError
    backend_pid, backend_start, backend_type, leader_pid = row
    if isinstance(backend_pid, bool) or not isinstance(backend_pid, int):
        raise ValueError
    if not isinstance(backend_start, datetime):
        raise ValueError
    if not isinstance(backend_type, str):
        raise ValueError
    if leader_pid is not None and (
        isinstance(leader_pid, bool) or not isinstance(leader_pid, int)
    ):
        raise ValueError
    return BackendActivity(
        identity=BackendIdentity(backend_pid, backend_start),
        backend_type=backend_type,
        leader_pid=leader_pid,
    )
