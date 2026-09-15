from __future__ import annotations

from datetime import datetime, timezone

import pytest

from repomap_kg.storage.backend_ownership import (
    BackendActivity,
    BackendClassification,
    BackendIdentity,
    ConnectionRole,
    OwnedBackend,
    classify_backend_activity,
)
from repomap_kg.storage.backend_ownership_registry import BackendOwnershipRegistry
from repomap_kg.storage.backend_telemetry import (
    ConnectionTelemetryError,
    ConnectionTelemetryEvent,
    TelemetryEventKind,
)


def _start(second: int) -> datetime:
    return datetime(2026, 7, 15, 0, 3, second, tzinfo=timezone.utc)


def _identity(pid: int, second: int) -> BackendIdentity:
    return BackendIdentity(pid, _start(second))


def _event(
    kind: TelemetryEventKind,
    *,
    sequence: int = 1,
    generation: int = 1,
    role: ConnectionRole = ConnectionRole.DIRECT_STAGED_REFRESH,
    backend_pid: int | None = 1101,
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


@pytest.mark.parametrize(
    "construct",
    [
        lambda: BackendIdentity(0, _start(1)),
        lambda: BackendActivity(_identity(1102, 2), "", None),
        lambda: BackendActivity(_identity(1103, 3), "parallel worker", 0),
        lambda: OwnedBackend(
            0,
            1,
            ConnectionRole.DIRECT_STAGED_REFRESH,
            _identity(1104, 4),
        ),
        lambda: OwnedBackend(
            1,
            0,
            ConnectionRole.DIRECT_STAGED_REFRESH,
            _identity(1105, 5),
        ),
    ],
)
def test_ownership_values_reject_invalid_identity_and_lifecycle_values(construct) -> None:
    with pytest.raises(ValueError):
        construct()


def test_classifier_rejects_overlapping_direct_and_observer_identity() -> None:
    identity = _identity(1110, 6)
    owned = OwnedBackend(
        1,
        1,
        ConnectionRole.DIRECT_STAGED_REFRESH,
        identity,
    )

    with pytest.raises(ValueError, match="overlap"):
        classify_backend_activity(
            (BackendActivity(identity, "client backend", None),),
            (owned,),
            (identity,),
        )


def test_classifier_fails_closed_for_a_worker_with_duplicate_leader_pid() -> None:
    leader = _identity(1120, 7)
    reused_leader = _identity(1120, 8)
    worker = _identity(1121, 9)
    owned = OwnedBackend(
        1,
        1,
        ConnectionRole.DIRECT_STAGED_REFRESH,
        leader,
    )

    classified = classify_backend_activity(
        (
            BackendActivity(leader, "client backend", None),
            BackendActivity(reused_leader, "client backend", None),
            BackendActivity(worker, "parallel worker", 1120),
        ),
        (owned,),
        (),
    )

    assert classified[-1].classification is BackendClassification.UNKNOWN


def test_registry_rejects_invalid_order_and_mismatched_lifecycle_events() -> None:
    registry = BackendOwnershipRegistry()
    opened = _event(TelemetryEventKind.CONNECTION_OPENED)

    with pytest.raises(ConnectionTelemetryError, match="telemetry state"):
        registry.accept(_event(TelemetryEventKind.CONNECTION_REPLACED), ())

    registry.accept(opened, ())
    with pytest.raises(ConnectionTelemetryError, match="telemetry state"):
        registry.accept(opened, ())
    with pytest.raises(ConnectionTelemetryError, match="telemetry state"):
        registry.accept(
            _event(
                TelemetryEventKind.CONNECTION_READY,
                role=ConnectionRole.COMMIT_RECONCILIATION,
            ),
            (),
        )


def test_registry_removes_pending_failure_and_rejects_mismatched_close() -> None:
    identity = _identity(1101, 10)
    registry = BackendOwnershipRegistry()
    opened = _event(TelemetryEventKind.CONNECTION_OPENED)
    ready = _event(TelemetryEventKind.CONNECTION_READY)

    registry.accept(opened, ())
    registry.accept(
        _event(TelemetryEventKind.CONNECTION_FAILED),
        (),
    )
    registry.accept(opened, ())
    registry.accept(
        ready,
        (BackendActivity(identity, "client backend", None),),
        ready_identity=identity,
    )

    registry.accept(
        _event(
            TelemetryEventKind.CONNECTION_CLOSED,
            sequence=2,
            backend_pid=1102,
        ),
        (),
    )
    with pytest.raises(ConnectionTelemetryError, match="telemetry state"):
        registry.accept(
            _event(
                TelemetryEventKind.CONNECTION_CLOSED,
                backend_pid=1102,
            ),
            (),
        )

    assert len(registry.owned_backends) == 1
