"""Recovery classification cannot replace durable graph publication fencing."""
from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from repomap_kg.coordinator import _publication_phase as phase
from repomap_kg.coordinator._control_types import JobClaim
from repomap_kg.coordinator._restart_fencing import (
    StaleDurableAuthorityError, build_store_fencing_proof, execute_durable_closure,
)
from repomap_kg.coordinator.startup_recovery import PublicationRouteChangedError
from repomap_test_support.fencing_control_fakes import FencingControl


def claim() -> JobClaim:
    return JobClaim("job-crashed", "graph-fixture", 1, "prior", 3, graph_lease_fencing_epoch=91)


def test_newly_stamped_abandonment_does_not_authorize_closure(tmp_path) -> None:
    prior = claim()
    control = FencingControl(prior, restart=True)
    phase.initialize(tmp_path, prior)
    assert control.attempt["finished_at"] == "newly-stamped"
    assert build_store_fencing_proof(control.connect, prior, reconciler_instance_id="replacement",
                                    reconciler_epoch=4) is None
    assert not execute_durable_closure(
        control.connect, prior, reconciler_instance_id="replacement", reconciler_epoch=4,
        fence_callback=None, file_closer=lambda c, p: phase.close_unpublished(tmp_path, c, proof=p),
    )
    assert phase.publication_state(tmp_path, prior) == "commit_unknown"


@pytest.mark.parametrize("invalid", ["lease_active", "lease_owner", "lease_epoch", "missing_epoch", "stale_singleton"])
def test_restart_proof_refuses_unfenced_or_mismatched_lease(invalid) -> None:
    prior = claim()
    control = FencingControl(prior, restart=True)
    if invalid == "lease_active":
        control.lease["lease_active"] = True
        # Larger replacement epochs never make active-old-lease refusal vacuous.
        control.epoch = 100
    elif invalid == "lease_owner":
        control.lease["coordinator_instance_id"] = "different"
    elif invalid == "lease_epoch":
        control.lease["graph_lease_fencing_epoch"] = 92
    elif invalid == "missing_epoch":
        prior = replace(prior, graph_lease_fencing_epoch=0)
        control.attempt["graph_lease_fencing_epoch"] = 0
    else:
        control.active = False
    assert build_store_fencing_proof(
        control.connect, prior, reconciler_instance_id="replacement", reconciler_epoch=control.epoch,
        fence_callback=lambda *a, **k: True,
    ) is None


@pytest.mark.parametrize("verified", [False, None])
def test_unverified_storage_fence_cannot_close(verified, tmp_path) -> None:
    prior = claim()
    control = FencingControl(prior, restart=True)
    phase.initialize(tmp_path, prior)
    with pytest.raises(StaleDurableAuthorityError, match="not verified"):
        execute_durable_closure(
            control.connect, prior, reconciler_instance_id="replacement", reconciler_epoch=4,
            fence_callback=lambda *a, **k: verified,
            file_closer=lambda c, p: phase.close_unpublished(tmp_path, c, proof=p),
        )
    assert phase.publication_state(tmp_path, prior) == "commit_unknown"


def test_storage_fence_precedes_decision_and_persisted_closure(tmp_path) -> None:
    prior = claim()
    control = FencingControl(prior, restart=True)
    phase.initialize(tmp_path, prior)
    decision = phase._path(tmp_path, prior, "decision")
    calls: list[str] = []

    def fence(c: JobClaim, **authority: Any) -> bool:
        assert not decision.exists()
        assert c == prior
        assert authority == dict(reconciler_instance_id="replacement", reconciler_epoch=4, prior_lease_epoch=91)
        calls.append("durable_graph_fence")
        return True

    def close(c: JobClaim, proof: phase.WorkerFencingProof) -> bool:
        assert calls == ["durable_graph_fence"]
        assert proof.proof_kind == "store_fenced"
        return phase.close_unpublished(tmp_path, c, proof=proof)

    assert execute_durable_closure(
        control.connect, prior, reconciler_instance_id="replacement", reconciler_epoch=4,
        fence_callback=fence, file_closer=close,
    )
    assert control.committed
    assert phase.publication_state(tmp_path, prior) == "not_started"
    assert any("FROM graph_leases" in query and "FOR UPDATE" in query for query, _ in control.executions)
    with pytest.raises(FileExistsError):
        phase.before_publication(tmp_path, prior)


def test_started_decision_refuses_control_closure_even_after_fence(tmp_path) -> None:
    prior = claim()
    control = FencingControl(prior, restart=True)
    phase.initialize(tmp_path, prior)
    phase.before_publication(tmp_path, prior)
    assert not execute_durable_closure(
        control.connect, prior, reconciler_instance_id="replacement", reconciler_epoch=4,
        fence_callback=lambda *a, **k: True,
        file_closer=lambda c, p: phase.close_unpublished(tmp_path, c, proof=p),
    )
    assert control.rolled_back
    assert not any(query.startswith("UPDATE") for query, _ in control.executions)
    assert phase.publication_state(tmp_path, prior) == "commit_unknown"


def test_store_proof_revalidates_after_singleton_turnover(tmp_path) -> None:
    prior = claim()
    control = FencingControl(prior, restart=True)
    phase.initialize(tmp_path, prior)
    proof = build_store_fencing_proof(control.connect, prior, reconciler_instance_id="replacement",
                                     reconciler_epoch=4, fence_callback=lambda *a, **k: True)
    assert proof is not None
    control.epoch = 5
    assert not phase.close_unpublished(tmp_path, prior, proof=proof)
    assert phase.publication_state(tmp_path, prior) == "commit_unknown"


def test_route_change_is_preserved_for_recovery_classification() -> None:
    prior = claim()
    control = FencingControl(prior, restart=True)

    def changed(*args: Any, **kwargs: Any) -> bool:
        raise PublicationRouteChangedError("route changed")

    with pytest.raises(PublicationRouteChangedError):
        execute_durable_closure(
            control.connect, prior, reconciler_instance_id="replacement", reconciler_epoch=4,
            fence_callback=changed, file_closer=lambda *a: True,
        )


@pytest.mark.parametrize("renewed", [True, False])
def test_pending_restart_reconciliation_retries_after_successful_heartbeat(renewed) -> None:
    from types import SimpleNamespace
    from unittest.mock import Mock
    from repomap_kg.coordinator.core import SyntheticCoordinator

    store = Mock()
    store.heartbeat_singleton.return_value = renewed
    coordinator = SyntheticCoordinator(store, "replacement", lambda *a: {})
    coordinator._epoch = 4
    coordinator._startup_recovery_report = SimpleNamespace(pending=1)
    retry = Mock(return_value=SimpleNamespace(pending=0))
    setattr(coordinator, "recover_startup", retry)
    assert coordinator.heartbeat() is renewed
    assert retry.call_count == int(renewed)
    coordinator._executor.shutdown()


def test_contention_lock_not_available_refuses_closure_safely(tmp_path) -> None:
    from psycopg.errors import LockNotAvailable

    prior = claim()
    control = FencingControl(prior, restart=True)
    phase.initialize(tmp_path, prior)

    def contending_fence(*args: Any, **kwargs: Any) -> bool:
        raise LockNotAvailable("lock timeout expired under lock contention")

    # execute_durable_closure catches LockNotAvailable and returns False, preserving singleton liveness
    assert execute_durable_closure(
        control.connect, prior, reconciler_instance_id="replacement", reconciler_epoch=4,
        fence_callback=contending_fence, file_closer=lambda *a: True,
    ) is False
    assert phase.publication_state(tmp_path, prior) == "commit_unknown"


def test_contention_query_canceled_refuses_closure_safely(tmp_path) -> None:
    from psycopg.errors import QueryCanceled

    prior = claim()
    control = FencingControl(prior, restart=True)
    phase.initialize(tmp_path, prior)

    def contending_fence(*args: Any, **kwargs: Any) -> bool:
        raise QueryCanceled("statement timeout expired under lock contention")

    assert execute_durable_closure(
        control.connect, prior, reconciler_instance_id="replacement", reconciler_epoch=4,
        fence_callback=contending_fence, file_closer=lambda *a: True,
    ) is False
    assert phase.publication_state(tmp_path, prior) == "commit_unknown"


def test_quarantine_legacy_attempt_fence_before_release() -> None:
    from repomap_kg.coordinator._restart_fencing import quarantine_legacy_attempt

    legacy = replace(claim(), graph_lease_fencing_epoch=0)
    control = FencingControl(legacy, restart=True)
    control.attempt["graph_lease_fencing_epoch"] = 0
    control.lease["graph_lease_fencing_epoch"] = 0

    order: list[str] = []

    def fence_cb(c: JobClaim, **kw: Any) -> bool:
        assert c == legacy
        assert kw["prior_lease_epoch"] == 0
        assert kw["replacement_lease_epoch"] > 0
        assert not any("DELETE FROM graph_leases" in q for q, _ in control.executions)
        assert not any("quarantined" in q for q, _ in control.executions)
        order.append("fence_installed")
        return True

    assert quarantine_legacy_attempt(
        control.connect,
        legacy,
        reconciler_instance_id="replacement",
        reconciler_epoch=4,
        fence_callback=fence_cb,
    ) is True
    assert order == ["fence_installed"]
    assert control.committed
    assert any("UPDATE jobs SET state = 'quarantined'" in q and "commit_unknown" in q for q, _ in control.executions)
    assert any("DELETE FROM graph_leases" in q for q, _ in control.executions)


def test_quarantine_legacy_attempt_unavailable_fence_preserves() -> None:
    from repomap_kg.coordinator._restart_fencing import quarantine_legacy_attempt

    legacy = replace(claim(), graph_lease_fencing_epoch=0)
    control = FencingControl(legacy, restart=True)
    control.attempt["graph_lease_fencing_epoch"] = 0
    control.lease["graph_lease_fencing_epoch"] = 0

    assert quarantine_legacy_attempt(
        control.connect,
        legacy,
        reconciler_instance_id="replacement",
        reconciler_epoch=4,
        fence_callback=None,
    ) is False
    assert not control.committed
    assert not any("DELETE FROM graph_leases" in q for q, _ in control.executions)


@pytest.mark.parametrize(
    "invalid",
    ["claim_positive", "attempt_positive", "lease_positive", "stale_replacement_epoch", "lease_active"],
)
def test_quarantine_legacy_attempt_zeroexact_validation(invalid: str) -> None:
    from repomap_kg.coordinator._restart_fencing import quarantine_legacy_attempt

    legacy = replace(claim(), graph_lease_fencing_epoch=0)
    control = FencingControl(legacy, restart=True)
    control.attempt["graph_lease_fencing_epoch"] = 0
    control.lease["graph_lease_fencing_epoch"] = 0
    reconciler_epoch = 4

    if invalid == "claim_positive":
        legacy = replace(legacy, graph_lease_fencing_epoch=1)
    elif invalid == "attempt_positive":
        control.attempt["graph_lease_fencing_epoch"] = 1
    elif invalid == "lease_positive":
        control.lease["graph_lease_fencing_epoch"] = 1
    elif invalid == "stale_replacement_epoch":
        reconciler_epoch = 3  # Not > claim's fencing_epoch (3)
    elif invalid == "lease_active":
        control.lease["lease_active"] = True

    assert quarantine_legacy_attempt(
        control.connect,
        legacy,
        reconciler_instance_id="replacement",
        reconciler_epoch=reconciler_epoch,
        fence_callback=lambda *a, **k: True,
    ) is False
    assert not control.committed
