"""Classify bounded PostgreSQL backend activity by exact local ownership."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

__all__ = [
    "BackendActivity",
    "BackendClassification",
    "BackendIdentity",
    "ClassifiedBackend",
    "ConnectionRole",
    "OwnedBackend",
    "classify_backend_activity",
    "public_backend_summary",
]


class ConnectionRole(str, Enum):
    """Closed source-controlled connection roles for direct staged refresh."""

    DIRECT_MAINTENANCE_ADMISSION = "direct_maintenance_admission"
    DIRECT_STAGED_REFRESH = "direct_staged_refresh"
    COMMIT_RECONCILIATION = "commit_reconciliation"


@dataclass(frozen=True)
class BackendIdentity:
    """Exact PostgreSQL backend identity for one observed server lifetime."""

    backend_pid: int
    backend_start: datetime

    def __post_init__(self) -> None:
        if self.backend_pid <= 0:
            raise ValueError("backend PID must be positive")


@dataclass(frozen=True)
class BackendActivity:
    """Bounded pg_stat_activity projection for a single PostgreSQL backend."""

    identity: BackendIdentity
    backend_type: str
    leader_pid: int | None

    def __post_init__(self) -> None:
        if not self.backend_type:
            raise ValueError("backend type is required")
        if self.leader_pid is not None and self.leader_pid <= 0:
            raise ValueError("parallel leader PID must be positive")


@dataclass(frozen=True)
class OwnedBackend:
    """One active direct connection registered through local telemetry."""

    connection_sequence: int
    connection_generation: int
    connection_role: ConnectionRole
    identity: BackendIdentity

    def __post_init__(self) -> None:
        if self.connection_sequence <= 0:
            raise ValueError("connection sequence must be positive")
        if self.connection_generation <= 0:
            raise ValueError("connection generation must be positive")


class BackendClassification(str, Enum):
    """Closed ownership categories for local observer decisions."""

    DIRECT_OWNED_CLIENT = "direct_owned_client"
    DIRECT_OWNED_PARALLEL_WORKER = "direct_owned_parallel_worker"
    OBSERVER = "observer"
    POSTGRES_INTERNAL = "postgres_internal"
    AMBIENT_CLIENT = "ambient_client"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ClassifiedBackend:
    """Local-only activity classification for a PostgreSQL backend."""

    activity: BackendActivity
    classification: BackendClassification


def classify_backend_activity(
    activities: Collection[BackendActivity],
    owned: Collection[OwnedBackend],
    observers: Collection[BackendIdentity],
) -> tuple[ClassifiedBackend, ...]:
    """Classify a bounded activity snapshot without inferring ownership."""

    owned_identities = {entry.identity for entry in owned}
    observer_identities = set(observers)
    if owned_identities & observer_identities:
        raise ValueError("owned and observer backend identities overlap")

    activities_by_pid: dict[int, list[BackendActivity]] = defaultdict(list)
    for activity in activities:
        activities_by_pid[activity.identity.backend_pid].append(activity)

    direct_clients = {
        activity.identity
        for activity in activities
        if activity.backend_type == "client backend"
        and activity.identity in owned_identities
    }
    return tuple(
        ClassifiedBackend(
            activity=activity,
            classification=_classify_activity(
                activity,
                direct_clients=direct_clients,
                owned_identities=owned_identities,
                observer_identities=observer_identities,
                activities_by_pid=activities_by_pid,
            ),
        )
        for activity in activities
    )


def public_backend_summary(
    classified: Collection[ClassifiedBackend],
) -> dict[str, int]:
    """Return the public-safe category-count projection of local activity."""

    counts = Counter(entry.classification.value for entry in classified)
    return {category: counts[category] for category in sorted(counts)}


def _classify_activity(
    activity: BackendActivity,
    *,
    direct_clients: set[BackendIdentity],
    owned_identities: set[BackendIdentity],
    observer_identities: set[BackendIdentity],
    activities_by_pid: dict[int, list[BackendActivity]],
) -> BackendClassification:
    if activity.backend_type == "client backend":
        if activity.identity in owned_identities:
            return BackendClassification.DIRECT_OWNED_CLIENT
        if activity.identity in observer_identities:
            return BackendClassification.OBSERVER
        return BackendClassification.AMBIENT_CLIENT
    if activity.backend_type != "parallel worker":
        return BackendClassification.POSTGRES_INTERNAL
    if activity.leader_pid is None:
        return BackendClassification.UNKNOWN
    leaders = activities_by_pid.get(activity.leader_pid, [])
    if len(leaders) != 1:
        return BackendClassification.UNKNOWN
    leader = leaders[0]
    if leader.identity in direct_clients:
        return BackendClassification.DIRECT_OWNED_PARALLEL_WORKER
    return BackendClassification.UNKNOWN
