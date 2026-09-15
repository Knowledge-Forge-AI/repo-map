from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from repomap_kg.storage.backend_observer import (
    BackendObservationError,
    BackendOwnershipObserver,
    current_backend_identity,
    read_backend_activity,
)
from repomap_kg.storage.backend_ownership import (
    BackendActivity,
    BackendIdentity,
    ConnectionRole,
)
from repomap_kg.storage.backend_ownership_registry import BackendOwnershipRegistry
from repomap_kg.storage.backend_telemetry import (
    BackendTelemetry,
    ConnectionTelemetryError,
    ConnectionTelemetryEvent,
    TelemetryEventKind,
)


def _start(second: int) -> datetime:
    return datetime(2026, 7, 15, 0, 2, second, tzinfo=timezone.utc)


def _event(
    kind: TelemetryEventKind,
    *,
    backend_pid: int = 951,
) -> ConnectionTelemetryEvent:
    return ConnectionTelemetryEvent(
        schema_version=1,
        connection_sequence=1,
        connection_generation=1,
        connection_role=ConnectionRole.DIRECT_STAGED_REFRESH,
        backend_pid=backend_pid,
        event=kind,
        monotonic_ns=123,
    )


class _Result:
    def __init__(self, rows: tuple[tuple[object, ...], ...]) -> None:
        self._rows = rows

    def fetchall(self) -> tuple[tuple[object, ...], ...]:
        return self._rows

    def fetchone(self) -> tuple[object, ...] | None:
        return self._rows[0] if self._rows else None


class _ObserverConnection:
    def __init__(
        self,
        identity: BackendIdentity,
        activities: list[BackendActivity],
    ) -> None:
        self.autocommit = True
        self.identity = identity
        self.activities = activities
        self.calls: list[str] = []
        self.execute: Callable[[str], _Result] = self._execute

    def _execute(self, sql: str) -> _Result:
        self.calls.append(sql)
        if "WHERE pid = pg_backend_pid()" in sql:
            return _Result(
                (
                    (
                        self.identity.backend_pid,
                        self.identity.backend_start,
                        "client backend",
                        None,
                    ),
                )
            )
        return _Result(
            tuple(
                (
                    activity.identity.backend_pid,
                    activity.identity.backend_start,
                    activity.backend_type,
                    activity.leader_pid,
                )
                for activity in self.activities
            )
        )


class _SourceConnection:
    def __init__(self, backend_pid: int) -> None:
        self.info = SimpleNamespace(backend_pid=backend_pid)
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_owner_sink_binds_ready_identity_while_source_is_live() -> None:
    observer_identity = BackendIdentity(950, _start(1))
    source_identity = BackendIdentity(951, _start(2))
    observer_connection = _ObserverConnection(
        observer_identity,
        [
            BackendActivity(observer_identity, "client backend", None),
            BackendActivity(source_identity, "client backend", None),
        ],
    )
    observer = BackendOwnershipObserver()
    observer.register_connection(observer_connection)
    source_connection = _SourceConnection(951)
    events: list[ConnectionTelemetryEvent] = []
    telemetry = BackendTelemetry(
        events.append,
        ownership_sink=observer.event_sink(observer_connection),
        monotonic_ns=lambda: 123,
    )

    tracked = telemetry.track(
        source_connection,
        ConnectionRole.DIRECT_STAGED_REFRESH,
    )

    assert observer.owned_backends[0].identity == source_identity
    assert [event.event for event in events] == [
        TelemetryEventKind.CONNECTION_OPENED,
        TelemetryEventKind.CONNECTION_READY,
    ]
    tracked.close()
    assert observer.owned_backends == ()


def test_closed_source_cannot_admit_a_reused_pid_as_ready() -> None:
    observer_identity = BackendIdentity(960, _start(3))
    original_identity = BackendIdentity(961, _start(4))
    reused_identity = BackendIdentity(961, _start(5))
    observer_connection = _ObserverConnection(
        observer_identity,
        [
            BackendActivity(observer_identity, "client backend", None),
            BackendActivity(original_identity, "client backend", None),
        ],
    )
    observer = BackendOwnershipObserver()
    observer.register_connection(observer_connection)
    source_connection = _SourceConnection(961)

    observer.accept_event(
        _event(TelemetryEventKind.CONNECTION_OPENED, backend_pid=961),
        observer_connection,
        source_connection,
    )
    source_connection.close()
    observer_connection.activities = [
        BackendActivity(observer_identity, "client backend", None),
        BackendActivity(reused_identity, "client backend", None),
    ]

    with pytest.raises(BackendObservationError, match="source connection"):
        observer.accept_event(
            _event(TelemetryEventKind.CONNECTION_READY, backend_pid=961),
            observer_connection,
            source_connection,
        )

    assert observer.owned_backends == ()


def test_registry_requires_the_exact_ready_identity_from_live_observation() -> None:
    original_identity = BackendIdentity(970, _start(6))
    reused_identity = BackendIdentity(970, _start(7))
    registry = BackendOwnershipRegistry()
    opened = _event(TelemetryEventKind.CONNECTION_OPENED, backend_pid=970)
    ready = _event(TelemetryEventKind.CONNECTION_READY, backend_pid=970)

    registry.accept(opened, ())
    with pytest.raises(ConnectionTelemetryError, match="backend identity"):
        registry.accept(
            ready,
            (BackendActivity(reused_identity, "client backend", None),),
        )
    with pytest.raises(ConnectionTelemetryError, match="backend identity"):
        registry.accept(
            ready,
            (BackendActivity(reused_identity, "client backend", None),),
            ready_identity=original_identity,
        )

    assert registry.owned_backends == ()


def test_observer_rejects_an_unbound_or_changed_observer_connection() -> None:
    identity = BackendIdentity(980, _start(8))
    observer_connection = _ObserverConnection(
        identity,
        [BackendActivity(identity, "client backend", None)],
    )
    other_connection = _ObserverConnection(
        identity,
        [BackendActivity(identity, "client backend", None)],
    )
    observer = BackendOwnershipObserver()
    observer.register_connection(observer_connection)

    with pytest.raises(BackendObservationError, match="observer connection"):
        observer.classify(other_connection)

    changed_identity = BackendIdentity(980, _start(9))
    observer_connection.identity = changed_identity
    observer_connection.activities = [
        BackendActivity(changed_identity, "client backend", None)
    ]
    with pytest.raises(BackendObservationError, match="observer connection"):
        observer.classify(observer_connection)


def test_summary_validates_identity_from_one_activity_snapshot() -> None:
    identity = BackendIdentity(981, _start(9))
    observer_connection = _ObserverConnection(
        identity,
        [BackendActivity(identity, "client backend", None)],
    )
    observer = BackendOwnershipObserver()
    observer.register_connection(observer_connection)

    assert observer.public_summary(observer_connection) == {"observer": 1}
    assert len(observer_connection.calls) == 2


def test_read_backend_activity_rejects_malformed_rows() -> None:
    identity = BackendIdentity(990, _start(10))
    connection = _ObserverConnection(
        identity,
        [BackendActivity(identity, "client backend", None)],
    )
    connection.activities = []
    connection.execute = lambda _sql: _Result(
        ((True, _start(10), "client backend", None),)
    )

    with pytest.raises(BackendObservationError, match="backend activity"):
        read_backend_activity(connection)


def test_current_backend_identity_rejects_a_non_client_backend() -> None:
    identity = BackendIdentity(991, _start(11))
    connection = _ObserverConnection(
        identity,
        [BackendActivity(identity, "client backend", None)],
    )

    def execute(_sql: str) -> _Result:
        return _Result(((991, _start(11), "background writer", None),))

    connection.execute = execute
    with pytest.raises(BackendObservationError, match="backend identity"):
        current_backend_identity(connection)
