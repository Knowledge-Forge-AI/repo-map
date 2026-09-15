from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Callable

from repomap_kg.coordinator._control_types import JobClaim
from repomap_kg.coordinator.startup_recovery import (
    PublicationRouteChangedError,
    recover_startup,
)


@dataclass(frozen=True)
class Claim(JobClaim):
    graph_id: str = "configured-refresh"
    attempt: int = 1
    instance_id: str = "stale-owner"
    fencing_epoch: int = 1
    source_generation: str = "sg1:source"
    config_generation: str = "cg1:route"
    extractor_generation: str = "eg1:extractor"
    canonicalizer_generation: str = "kg1:canonicalizer"


class Store:
    def __init__(self) -> None:
        self.claims: list[JobClaim] = [Claim("committed"), Claim("changed"), Claim("offline")]
        self.markers: list[tuple[str, dict[str, Any]]] = []
        self.reconciled: list[tuple[str, dict[str, Any]]] = []
        self.reconcile_publication: Callable[..., str] = self._reconcile_publication

    def reconciliation_claims(self, limit: int) -> tuple[JobClaim, ...]:
        assert limit == 3
        return tuple(self.claims)

    def record_publication_marker(self, claim: Any, **marker: Any) -> bool:
        self.markers.append((claim.job_id, marker))
        return True

    def _reconcile_publication(self, claim: Any, **owner: Any) -> str:
        self.reconciled.append((claim.job_id, owner))
        return "succeeded" if claim.job_id == "committed" else "reconciliation_required"

    def acquire_singleton(self, instance_id: str, ttl: timedelta) -> int:
        return 1

    def stop_singleton(self, instance_id: str, fencing_epoch: int) -> bool:
        return True


def test_startup_recovery_is_bounded_and_classifies_pending_evidence() -> None:
    store = Store()

    def read(claim):
        if claim.job_id == "changed":
            raise PublicationRouteChangedError("configured storage route changed")
        if claim.job_id == "offline":
            raise RuntimeError("graph read unavailable")
        return {
            "outcome": "committed",
            "graph_id": claim.graph_id,
            "latest_run_identity": "run-public-1",
            "source_generation": claim.source_generation,
            "config_generation": claim.config_generation,
            "extractor_generation": claim.extractor_generation,
            "canonicalizer_generation": claim.canonicalizer_generation,
        }

    report = recover_startup(
        store,
        read,
        instance_id="new-owner",
        fencing_epoch=2,
        limit=3,
    )

    assert report.scanned == 3
    assert report.resolved == 1
    assert report.pending == 2
    assert report.route_changed == 1
    assert report.unavailable == 1
    assert [job_id for job_id, _marker in store.markers] == ["committed"]
    assert all(
        owner == {"reconciler_instance_id": "new-owner", "reconciler_epoch": 2}
        for _job_id, owner in store.reconciled
    )


def test_startup_recovery_does_not_count_lost_ownership_as_resolved() -> None:
    store = Store()
    store.claims = [Claim("lost")]
    store.reconcile_publication = lambda _claim, **_owner: "ownership_lost"

    report = recover_startup(
        store,
        lambda _claim: None,
        instance_id="new-owner",
        fencing_epoch=2,
        limit=3,
    )

    assert report.resolved == 0
    assert report.pending == 1
