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
    graph_lease_fencing_epoch: int = 91
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

    def prove_worker_fenced(
        self, claim: Any, *, reconciler_instance_id: str, reconciler_epoch: int
    ) -> Any:
        return None


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


def test_startup_recovery_retires_evidence_on_resolved_outcomes() -> None:
    store = Store()
    store.claims = [Claim("succeeded"), Claim("queued"), Claim("failed")]
    retired_claims: list[str] = []

    def mock_reconcile(claim, **_owner):
        return claim.job_id

    store.reconcile_publication = mock_reconcile

    report = recover_startup(
        store,
        lambda _claim: None,
        instance_id="new-owner",
        fencing_epoch=2,
        limit=3,
        publication_retirer=lambda claim: retired_claims.append(getattr(claim, "job_id", "")),
    )

    assert report.resolved == 3
    assert report.residuals == 0
    assert retired_claims == ["succeeded", "queued", "failed"]


def test_startup_recovery_preserves_evidence_on_reconciliation_required_or_quarantine() -> None:
    store = Store()
    store.claims = [Claim("quarantined"), Claim("reconciliation_required"), Claim("lost")]
    retired_claims: list[str] = []

    def mock_reconcile(claim, **_owner):
        if claim.job_id == "lost":
            return "ownership_lost"
        return claim.job_id

    store.reconcile_publication = mock_reconcile

    report = recover_startup(
        store,
        lambda _claim: None,
        instance_id="new-owner",
        fencing_epoch=2,
        limit=3,
        publication_retirer=lambda claim: retired_claims.append(getattr(claim, "job_id", "")),
    )

    assert report.resolved == 1  # quarantined is considered resolved terminal state
    assert report.pending == 2
    assert retired_claims == []  # But neither quarantined, nor rec_req, nor lost should be retired!


def test_startup_recovery_surfaces_residual_when_retirement_refused() -> None:
    store = Store()
    store.claims = [Claim("succeeded")]

    store.reconcile_publication = lambda _claim, **_owner: "succeeded"

    def refusing_retirer(_claim):
        raise ValueError("corrupted publication evidence")

    report = recover_startup(
        store,
        lambda _claim: None,
        instance_id="new-owner",
        fencing_epoch=2,
        limit=3,
        publication_retirer=refusing_retirer,
    )

    assert report.resolved == 1
    assert report.residuals == 1


def test_startup_recovery_with_publication_closer_and_store_fencing_proof() -> None:
    store = Store()
    claim = Claim("un-published-job")
    store.claims = [claim]
    proof_mock = object()
    closed_claims: list[tuple[Any, Any]] = []

    def mock_prove(cl, *, reconciler_instance_id, reconciler_epoch):
        assert reconciler_instance_id == "new-owner" and reconciler_epoch == 2
        return proof_mock

    setattr(store, "prove_worker_fenced", mock_prove)

    def mock_closer(cl, proof):
        assert proof is proof_mock
        closed_claims.append((cl, proof))
        return True

    state_holder = {"read": False}

    def mock_reader(cl):
        if state_holder["read"]:
            return {"publication_state": "not_started"}
        state_holder["read"] = True
        return None

    def mock_reconcile(cl, **kw):
        assert kw.get("unpublished_proved") is True
        return "queued"

    store.reconcile_publication = mock_reconcile

    report = recover_startup(
        store,
        mock_reader,
        instance_id="new-owner",
        fencing_epoch=2,
        limit=3,
        publication_closer=mock_closer,
    )

    assert report.resolved == 1
    assert report.pending == 0
    assert len(closed_claims) == 1


def test_startup_recovery_refuses_closure_when_store_fencing_returns_none() -> None:
    store = Store()
    claim = Claim("unfenced-job")
    store.claims = [claim]
    closer_called: list[object] = []

    def mock_prove(cl, *, reconciler_instance_id, reconciler_epoch):
        # Worker or lease is not fenced!
        return None

    setattr(store, "prove_worker_fenced", mock_prove)

    def mock_closer(cl, proof):
        closer_called.append(cl)
        return True

    def mock_reconcile(cl, **kw):
        assert "unpublished_proved" not in kw or kw["unpublished_proved"] is False
        return "reconciliation_required"

    store.reconcile_publication = mock_reconcile

    report = recover_startup(
        store,
        lambda cl: None,
        instance_id="new-owner",
        fencing_epoch=2,
        limit=3,
        publication_closer=mock_closer,
    )

    assert report.resolved == 0
    assert report.pending == 1
    assert closer_called == []


def test_startup_recovery_observable_refusal_and_unexpected_diagnostics() -> None:
    store = Store()
    claim1 = Claim("refused-job")
    claim2 = Claim("unexpected-job")
    store.claims = [claim1, claim2]

    from repomap_kg.coordinator._restart_fencing import StaleDurableAuthorityError

    def mock_prove(cl, *, reconciler_instance_id, reconciler_epoch):
        if cl.job_id == "refused-job":
            raise StaleDurableAuthorityError("stale authority refusal")
        if cl.job_id == "unexpected-job":
            raise OSError("unexpected disk failure")
        return None

    setattr(store, "prove_worker_fenced", mock_prove)

    def mock_reconcile(cl, **kw):
        return "reconciliation_required"

    store.reconcile_publication = mock_reconcile

    report = recover_startup(
        store,
        lambda cl: None,
        instance_id="new-owner",
        fencing_epoch=2,
        limit=3,
        publication_closer=lambda *a: True,
    )

    assert report.scanned == 2
    assert report.resolved == 0
    assert report.pending == 2
    assert report.refused == 1
    assert len(report.unexpected) == 1
    assert report.unexpected == ("OSError",)


def test_startup_recovery_zero_epoch_schedulability_and_file_uncertainty() -> None:
    store = Store()
    claim = Claim("legacy-zero", graph_lease_fencing_epoch=0)
    store.claims = [claim]
    quarantined: list[tuple[Any, str, int]] = []
    closer_called: list[object] = []

    def forbidden_closer(*args):
        closer_called.append(args)
        return True

    def mock_quarantine(cl, *, reconciler_instance_id, reconciler_epoch):
        quarantined.append((cl, reconciler_instance_id, reconciler_epoch))
        return True

    setattr(store, "quarantine_legacy_attempt", mock_quarantine)

    report = recover_startup(
        store,
        lambda cl: None,
        instance_id="new-owner",
        fencing_epoch=2,
        limit=3,
        publication_closer=forbidden_closer,
        publication_retirer=lambda cl: closer_called.append(cl),
    )

    assert report.resolved == 1
    assert report.pending == 0
    assert len(quarantined) == 1
    assert quarantined[0][1] == "new-owner" and quarantined[0][2] == 2
    assert closer_called == []


def test_startup_recovery_unexpected_schema_diagnostics_sanitized() -> None:
    store = Store()
    claim1 = Claim("schema-err", graph_lease_fencing_epoch=0)
    claim2 = Claim("contention", graph_lease_fencing_epoch=0)
    store.claims = [claim1, claim2]

    from psycopg.errors import LockNotAvailable

    def mock_quarantine(cl, *, reconciler_instance_id, reconciler_epoch):
        if cl.job_id == "schema-err":
            raise RuntimeError("missing table at postgresql://user:pass@host/db")
        if cl.job_id == "contention":
            raise LockNotAvailable("lock timeout")
        return False

    setattr(store, "quarantine_legacy_attempt", mock_quarantine)

    report = recover_startup(
        store,
        lambda cl: None,
        instance_id="new-owner",
        fencing_epoch=2,
        limit=3,
    )

    assert report.scanned == 2
    assert report.resolved == 0
    assert report.pending == 2
    assert report.refused == 1
    assert len(report.unexpected) == 1
    assert report.unexpected[0] == "RuntimeError"


def test_startup_recovery_renews_singleton_before_and_after_each_item() -> None:
    store = Store()
    store.claims = [Claim("item-1"), Claim("item-2")]
    renew_events: list[str] = []

    def renew() -> bool:
        renew_events.append("renew")
        return True

    report = recover_startup(
        store,
        lambda cl: None,
        instance_id="new-owner",
        fencing_epoch=2,
        limit=3,
        renew_singleton=renew,
    )

    assert report.scanned == 2
    assert len(renew_events) == 4
