"""Recovery reports preserve uncertainty across atomic closure and lost renewal."""
from dataclasses import replace
from typing import Callable

import pytest

from repomap_kg.coordinator._control_types import JobClaim
from repomap_kg.coordinator._restart_fencing import StaleDurableAuthorityError
from repomap_kg.coordinator.core import SyntheticCoordinator
from repomap_kg.coordinator.startup_recovery import (
    PublicationRouteChangedError, StartupRecoveryReport, recover_startup,
)
from repomap_test_support.coordinator_core_fakes import FakeStore, terminal


class ClosureStore(FakeStore):
    def __init__(self, outcome: bool | Exception) -> None:
        super().__init__()
        self.claims = tuple(
            JobClaim(f"job-{i}", "graph-fixture", 1, "owner-old", 1, "automatic", "sg1", "cg1", graph_lease_fencing_epoch=2)
            for i in range(3)
        )
        self.outcome = outcome
        self.closed: list[tuple[str, str, int]] = []
        self.reconciled: list[tuple[str, bool]] = []
        self.reconcile_result = "reconciliation_required"

    def reconciliation_claims(self, limit: int) -> tuple[JobClaim, ...]:
        return self.claims[:limit]

    def close_unpublished_reconciliation(
        self, claim: JobClaim, *, reconciler_instance_id: str,
        reconciler_epoch: int, file_closer: Callable[[object, object], bool],
    ) -> bool:
        self.closed.append((claim.job_id, reconciler_instance_id, reconciler_epoch))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome

    def _reconcile_publication(
        self, claim: JobClaim, *, reconciler_instance_id: str | None = None,
        reconciler_epoch: int | None = None, **kwargs: object,
    ) -> str:
        self.reconciled.append((claim.job_id, kwargs.get("unpublished_proved") is True))
        return "queued" if kwargs.get("unpublished_proved") else "reconciliation_required"


@pytest.mark.parametrize("closure,refused,changed,unexpected", [
    (False, 1, 0, ()),
    (PublicationRouteChangedError("route changed"), 0, 1, ()),
    (StaleDurableAuthorityError("stale authority"), 1, 0, ()),
    (KeyError("fixture confidential payload"), 0, 0, ("KeyError",)),
])
def test_atomic_closure_refusal_keeps_reconciliation_pending(closure, refused, changed, unexpected):
    store = ClosureStore(closure)
    report = recover_startup(
        store, lambda _claim: {"publication_state": "commit_unknown"},
        instance_id="owner-new", fencing_epoch=3, limit=1,
        publication_closer=lambda _claim, _proof: True,
    )
    assert report == StartupRecoveryReport(1, 0, 1, changed, 0, refused=refused, unexpected=unexpected)
    assert store.closed == [("job-0", "owner-new", 3)]
    assert store.reconciled == [("job-0", False)]


def test_atomic_closure_proof_allows_queue_and_retirement_without_second_read():
    store = ClosureStore(True)
    reads: list[object] = []
    retired: list[object] = []

    def read(claim):
        reads.append(claim)
        return {"publication_state": "commit_unknown"}

    report = recover_startup(
        store, read, instance_id="owner-new", fencing_epoch=3, limit=1,
        publication_closer=lambda _claim, _proof: True,
        publication_retirer=retired.append,
    )
    assert report == StartupRecoveryReport(1, 1, 0, 0, 0)
    assert reads == retired == [store.claims[0]]
    assert store.reconciled == [("job-0", True)]


@pytest.mark.parametrize("renewals,expected_work", [([False], 0), ([True, False], 1)])
def test_lost_singleton_counts_remaining_claims_and_stops_new_closure(renewals, expected_work):
    store = ClosureStore(True)
    values = iter(renewals)
    retired: list[object] = []
    report = recover_startup(
        store, lambda _claim: None, instance_id="owner-new", fencing_epoch=3, limit=3,
        publication_closer=lambda _claim, _proof: True,
        publication_retirer=retired.append, renew_singleton=lambda: next(values),
    )
    assert report.scanned == 3
    assert report.resolved == expected_work
    assert report.pending == 3 - expected_work
    assert report.refused == 1
    assert len(store.closed) == len(store.reconciled) == len(retired) == expected_work


class AbandonedFailureStore(FakeStore):
    def recover_abandoned_attempts(self, instance_id: str, epoch: int, limit: int) -> int:
        raise OSError("abandoned recovery unavailable")


def test_abandoned_recovery_failure_releases_startup_ownership_before_accepting_jobs():
    store = AbandonedFailureStore()
    coordinator = SyntheticCoordinator(store, "owner-new", lambda *_: terminal())
    with pytest.raises(OSError, match="abandoned recovery unavailable"):
        coordinator.startup(lambda: None)
    assert ("stop", "owner-new", 1) in store.calls
    with pytest.raises(RuntimeError):
        coordinator.run_once()
    assert all(call[0] != "claim" for call in store.calls)


class LegacyStore(ClosureStore):
    def __init__(self, outcome: bool | Exception) -> None:
        super().__init__(outcome)
        self.claims = (replace(self.claims[0], graph_lease_fencing_epoch=0),)

    def quarantine_legacy_attempt(
        self, claim: JobClaim, *, reconciler_instance_id: str, reconciler_epoch: int,
    ) -> bool:
        self.closed.append((claim.job_id, reconciler_instance_id, reconciler_epoch))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


@pytest.mark.parametrize("quarantine,refused,changed", [
    (False, 1, 0), (PublicationRouteChangedError("route changed"), 0, 1),
])
def test_legacy_quarantine_refusal_cannot_enter_current_epoch_closure(quarantine, refused, changed):
    store = LegacyStore(quarantine)
    report = recover_startup(
        store, lambda _claim: pytest.fail("legacy attempt must not read current publication"),
        instance_id="owner-new", fencing_epoch=3, limit=1,
        publication_closer=lambda _claim, _proof: pytest.fail("legacy attempt must not close current files"),
        renew_singleton=lambda: True,
    )
    assert report == StartupRecoveryReport(1, 0, 1, changed, 0, refused=refused)
    assert store.closed == [("job-0", "owner-new", 3)]
    assert store.reconciled == []
