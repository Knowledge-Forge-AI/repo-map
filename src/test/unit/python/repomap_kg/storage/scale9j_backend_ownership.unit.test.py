from __future__ import annotations

from datetime import datetime, timezone
import os
import struct
from types import SimpleNamespace

import pytest

from repomap_kg.storage.backend_ownership import (
    BackendActivity,
    BackendClassification,
    BackendIdentity,
    ConnectionRole,
    OwnedBackend,
    classify_backend_activity,
    public_backend_summary,
)
from repomap_kg.storage.backend_telemetry import (
    MAX_TELEMETRY_FRAME_BYTES,
    BackendOwnershipRegistry,
    BackendTelemetry,
    ConnectionTelemetryError,
    ConnectionTelemetryEvent,
    TelemetryEventKind,
    frame_telemetry_event,
    parse_telemetry_frame,
    read_telemetry_event,
    telemetry_from_inherited_fd,
)


def _start(second: int) -> datetime:
    return datetime(2026, 7, 15, 0, 0, second, tzinfo=timezone.utc)


def _owned(
    identity: BackendIdentity,
    *,
    sequence: int = 1,
    generation: int = 1,
    role: ConnectionRole = ConnectionRole.DIRECT_STAGED_REFRESH,
) -> OwnedBackend:
    return OwnedBackend(
        connection_sequence=sequence,
        connection_generation=generation,
        connection_role=role,
        identity=identity,
    )


def test_classifies_exact_owned_client_and_parallel_worker() -> None:
    leader = BackendIdentity(101, _start(1))
    worker = BackendIdentity(102, _start(2))

    classified = classify_backend_activity(
        (
            BackendActivity(leader, "client backend", None),
            BackendActivity(worker, "parallel worker", 101),
        ),
        (_owned(leader),),
        (),
    )

    assert [row.classification for row in classified] == [
        BackendClassification.DIRECT_OWNED_CLIENT,
        BackendClassification.DIRECT_OWNED_PARALLEL_WORKER,
    ]


def test_classifies_multiple_owned_connections_with_closed_roles() -> None:
    refresh = BackendIdentity(201, _start(3))
    reconciliation = BackendIdentity(202, _start(4))

    classified = classify_backend_activity(
        (
            BackendActivity(refresh, "client backend", None),
            BackendActivity(reconciliation, "client backend", None),
        ),
        (
            _owned(refresh),
            _owned(
                reconciliation,
                sequence=2,
                role=ConnectionRole.COMMIT_RECONCILIATION,
            ),
        ),
        (),
    )

    assert [row.classification for row in classified] == [
        BackendClassification.DIRECT_OWNED_CLIENT,
        BackendClassification.DIRECT_OWNED_CLIENT,
    ]


def test_classifies_only_exact_observer_identity_as_observer() -> None:
    observer = BackendIdentity(301, _start(5))
    reused_pid = BackendIdentity(301, _start(6))

    classified = classify_backend_activity(
        (
            BackendActivity(observer, "client backend", None),
            BackendActivity(reused_pid, "client backend", None),
        ),
        (),
        (observer,),
    )

    assert [row.classification for row in classified] == [
        BackendClassification.OBSERVER,
        BackendClassification.AMBIENT_CLIENT,
    ]


def test_fails_closed_for_ambient_and_unprovable_parallel_work() -> None:
    ambient = BackendIdentity(401, _start(7))
    unrelated_leader = BackendIdentity(402, _start(8))
    unrelated_worker = BackendIdentity(403, _start(9))
    absent_leader_worker = BackendIdentity(404, _start(10))

    classified = classify_backend_activity(
        (
            BackendActivity(ambient, "client backend", None),
            BackendActivity(unrelated_leader, "client backend", None),
            BackendActivity(unrelated_worker, "parallel worker", 402),
            BackendActivity(absent_leader_worker, "parallel worker", 999),
        ),
        (),
        (),
    )

    assert [row.classification for row in classified] == [
        BackendClassification.AMBIENT_CLIENT,
        BackendClassification.AMBIENT_CLIENT,
        BackendClassification.UNKNOWN,
        BackendClassification.UNKNOWN,
    ]


def test_does_not_transfer_owned_identity_after_pid_reuse() -> None:
    prior = BackendIdentity(501, _start(11))
    reused = BackendIdentity(501, _start(12))

    classified = classify_backend_activity(
        (BackendActivity(reused, "client backend", None),),
        (_owned(prior),),
        (),
    )

    assert classified[0].classification is BackendClassification.AMBIENT_CLIENT


def test_classifies_postgresql_internal_activity_without_counting_it_as_client() -> None:
    internal = BackendIdentity(601, _start(13))

    classified = classify_backend_activity(
        (BackendActivity(internal, "background writer", None),),
        (),
        (),
    )

    assert classified[0].classification is BackendClassification.POSTGRES_INTERNAL


def test_public_projection_contains_only_bounded_category_counts() -> None:
    direct = BackendIdentity(701, _start(14))
    ambient = BackendIdentity(702, _start(15))
    classified = classify_backend_activity(
        (
            BackendActivity(direct, "client backend", None),
            BackendActivity(ambient, "client backend", None),
        ),
        (_owned(direct),),
        (),
    )

    summary = public_backend_summary(classified)

    assert summary == {
        "ambient_client": 1,
        "direct_owned_client": 1,
    }
    assert "701" not in repr(summary)
    assert "702" not in repr(summary)


class _FakeConnection:
    def __init__(self, backend_pid: int) -> None:
        self.info = SimpleNamespace(backend_pid=backend_pid)
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


def _event(
    kind: TelemetryEventKind,
    *,
    sequence: int = 1,
    generation: int = 1,
    role: ConnectionRole = ConnectionRole.DIRECT_STAGED_REFRESH,
    backend_pid: int | None = 801,
) -> ConnectionTelemetryEvent:
    return ConnectionTelemetryEvent(
        schema_version=1,
        connection_sequence=sequence,
        connection_generation=generation,
        connection_role=role,
        backend_pid=backend_pid,
        event=kind,
        monotonic_ns=123,
    )


def test_frames_only_allowed_local_fields_and_round_trip() -> None:
    event = _event(TelemetryEventKind.CONNECTION_READY)

    decoded = parse_telemetry_frame(frame_telemetry_event(event))

    assert decoded == event
    assert set(decoded.to_payload()) == {
        "schema_version",
        "connection_sequence",
        "connection_generation",
        "connection_role",
        "backend_pid",
        "event",
        "monotonic_ns",
    }
    assert "repository" not in decoded.to_payload()
    assert "query" not in decoded.to_payload()


def test_rejects_malformed_and_oversized_telemetry_frames() -> None:
    with pytest.raises(ConnectionTelemetryError, match="telemetry frame"):
        parse_telemetry_frame(b"\x00\x00\x00\x04{}")
    with pytest.raises(ConnectionTelemetryError, match="telemetry frame"):
        parse_telemetry_frame(
            struct.pack("!I", MAX_TELEMETRY_FRAME_BYTES + 1)
        )


def test_tracks_open_ready_close_and_reconnect_generation() -> None:
    events: list[ConnectionTelemetryEvent] = []
    telemetry = BackendTelemetry(events.append, monotonic_ns=lambda: 123)
    first_raw = _FakeConnection(811)
    first = telemetry.track(
        first_raw,
        ConnectionRole.DIRECT_STAGED_REFRESH,
    )

    first.close()
    second = telemetry.track(
        _FakeConnection(812),
        ConnectionRole.DIRECT_STAGED_REFRESH,
    )

    assert first_raw.close_calls == 1
    assert [
        event.event
        for event in events
    ] == [
        TelemetryEventKind.CONNECTION_OPENED,
        TelemetryEventKind.CONNECTION_READY,
        TelemetryEventKind.CONNECTION_CLOSED,
        TelemetryEventKind.CONNECTION_REPLACED,
        TelemetryEventKind.CONNECTION_OPENED,
        TelemetryEventKind.CONNECTION_READY,
    ]
    assert events[0].connection_generation == 1
    assert events[3].connection_generation == 2
    assert events[-1].backend_pid == 812
    second.close()


def test_tracks_concurrent_same_role_connections_without_replacement() -> None:
    events: list[ConnectionTelemetryEvent] = []
    telemetry = BackendTelemetry(events.append, monotonic_ns=lambda: 123)

    first = telemetry.track(
        _FakeConnection(815),
        ConnectionRole.DIRECT_STAGED_REFRESH,
    )
    second = telemetry.track(
        _FakeConnection(816),
        ConnectionRole.DIRECT_STAGED_REFRESH,
    )

    assert TelemetryEventKind.CONNECTION_REPLACED not in {
        event.event for event in events
    }
    first.close()
    second.close()


def test_telemetry_failure_closes_connection_before_source_sql() -> None:
    raw = _FakeConnection(821)

    def fail(_event: ConnectionTelemetryEvent) -> None:
        raise OSError("channel is unavailable")

    telemetry = BackendTelemetry(fail, monotonic_ns=lambda: 123)

    with pytest.raises(ConnectionTelemetryError, match="telemetry"):
        telemetry.track(raw, ConnectionRole.DIRECT_STAGED_REFRESH)

    assert raw.close_calls == 1


def test_reads_versioned_events_from_a_private_inherited_pipe() -> None:
    read_fd, write_fd = os.pipe()
    try:
        telemetry = telemetry_from_inherited_fd(write_fd, monotonic_ns=lambda: 123)
        telemetry.track(
            _FakeConnection(826),
            ConnectionRole.DIRECT_STAGED_REFRESH,
        )
        with os.fdopen(read_fd, "rb", closefd=False) as stream:
            opened = read_telemetry_event(stream)
            ready = read_telemetry_event(stream)
    finally:
        os.close(read_fd)
        os.close(write_fd)

    assert opened is not None
    assert opened.event is TelemetryEventKind.CONNECTION_OPENED
    assert ready is not None
    assert ready.event is TelemetryEventKind.CONNECTION_READY


def test_registry_handles_multiple_connections_and_ignores_stale_close() -> None:
    first_identity = BackendIdentity(831, _start(16))
    second_identity = BackendIdentity(832, _start(17))
    registry = BackendOwnershipRegistry()
    first_opened = _event(
        TelemetryEventKind.CONNECTION_OPENED,
        backend_pid=831,
    )
    first_ready = _event(
        TelemetryEventKind.CONNECTION_READY,
        backend_pid=831,
    )
    second_opened = _event(
        TelemetryEventKind.CONNECTION_OPENED,
        sequence=2,
        generation=2,
        role=ConnectionRole.COMMIT_RECONCILIATION,
        backend_pid=832,
    )
    second_ready = _event(
        TelemetryEventKind.CONNECTION_READY,
        sequence=2,
        generation=2,
        role=ConnectionRole.COMMIT_RECONCILIATION,
        backend_pid=832,
    )

    registry.accept(
        first_opened,
        (BackendActivity(first_identity, "client backend", None),),
    )
    registry.accept(
        first_ready,
        (BackendActivity(first_identity, "client backend", None),),
        ready_identity=first_identity,
    )
    registry.accept(
        second_opened,
        (BackendActivity(second_identity, "client backend", None),),
    )
    registry.accept(
        second_ready,
        (BackendActivity(second_identity, "client backend", None),),
        ready_identity=second_identity,
    )
    registry.accept(
        _event(TelemetryEventKind.CONNECTION_CLOSED, backend_pid=831),
        (BackendActivity(second_identity, "client backend", None),),
    )

    assert registry.owned_backends == (
        OwnedBackend(
            connection_sequence=2,
            connection_generation=2,
            connection_role=ConnectionRole.COMMIT_RECONCILIATION,
            identity=second_identity,
        ),
    )
