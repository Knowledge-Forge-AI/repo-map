from __future__ import annotations

from datetime import timedelta
from pathlib import Path
import psycopg
from typing import Any, Mapping, cast
import pytest

from repomap_kg.coordinator._control_types import JobClaim
from repomap_kg.coordinator.startup_recovery import StartupRecoveryReport, PublicationRouteChangedError, recover_startup


from repomap_test_support.startup_recovery_scenarios import (
    _harness, _req,
)


def test_startup_reconciliation_preserves_control_identity_without_capability() -> None:
    with _harness() as (store, _, _):
        epoch = store.acquire_singleton("instance-a", timedelta(seconds=30))
        submitted = store.submit(_req("synthetic-a", "recover"))
        store.submit(_req("synthetic-b", "queued"))
        claim = store.claim_next("instance-a", epoch, timedelta(seconds=30))
        assert claim is not None and claim.job_id == submitted.job_id
        for exp, nxt in (("claimed", "starting"), ("starting", "running")):
            assert store.compare_and_set_state(claim.job_id, expected_state=exp, new_state=nxt, attempt=claim.attempt, instance_id=claim.instance_id, fencing_epoch=claim.fencing_epoch)
        assert store.mark_reconciliation_required(claim, expected_state="running", category="publication_unknown")
        assert store.mark_attempt_terminated(claim, process_cleanup_proved=True, reconciler_instance_id="instance-a", reconciler_epoch=epoch)
        recovered = store.reconciliation_claims(1)
        assert recovered == (claim,)
        with pytest.raises(ValueError, match="reconciliation limit must be positive"): store.reconciliation_claims(0)


def test_control_store_cas_decision_table_primitives() -> None:
    with _harness() as (store, _, _):
        epoch = store.acquire_singleton("instance-a", timedelta(seconds=30))
        store.submit(_req("synthetic-dt", "dt-key"))
        claim = store.claim_next("instance-a", epoch, timedelta(seconds=30))
        assert claim is not None
        assert not store.compare_and_set_state(claim.job_id, expected_state="claimed", new_state="starting", attempt=claim.attempt, instance_id=claim.instance_id, fencing_epoch=epoch + 999)
        assert not store.compare_and_set_state(claim.job_id, expected_state="claimed", new_state="starting", attempt=claim.attempt, instance_id="wrong-instance", fencing_epoch=claim.fencing_epoch)
        for exp, nxt in (("claimed", "starting"), ("starting", "running")):
            assert store.compare_and_set_state(claim.job_id, expected_state=exp, new_state=nxt, attempt=claim.attempt, instance_id=claim.instance_id, fencing_epoch=claim.fencing_epoch)
        assert store.mark_reconciliation_required(claim, expected_state="running", category="publication_unknown") and store.status(claim.job_id).state == "reconciliation_required"
        with pytest.raises(ValueError, match="process cleanup proof is required"): store.mark_attempt_terminated(claim, process_cleanup_proved=False, reconciler_instance_id="instance-a", reconciler_epoch=epoch)
        assert store.mark_attempt_terminated(claim, process_cleanup_proved=True, reconciler_instance_id="instance-a", reconciler_epoch=epoch)
        claims = store.reconciliation_claims(1)
        assert len(claims) == 1 and claims[0].job_id == claim.job_id
        req = _req("synthetic-dt", "dt-key")
        store.record_publication_marker(claim, run_identity="run-1", source_generation=req.source_generation, config_generation=req.config_generation, extractor_generation=req.extractor_generation, canonicalizer_generation=req.canonicalizer_generation, outcome="committed")
        assert store.compare_and_set_state(claim.job_id, expected_state="reconciliation_required", new_state="succeeded", attempt=claim.attempt, instance_id=claim.instance_id, fencing_epoch=claim.fencing_epoch, publication_state="committed")
        assert store.status(claim.job_id).state == "succeeded"


def test_startup_recovery_with_publication_reader() -> None:
    claims = [JobClaim(f"job-{k}", f"g-{i}", 1, "inst-1", 1, graph_lease_fencing_epoch=91) for i, k in enumerate(("present", "absent", "conflicting", "route-changed", "unavailable"))]
    recorded: list[tuple[Any, Mapping[str, Any]]] = []

    class FakeStore:
        def prove_worker_fenced(self, claim: object, **kw: Any) -> None: return None
        def reconciliation_claims(self, limit: int) -> tuple[JobClaim, ...]: return tuple(claims[:limit])
        def record_publication_marker(self, claim: Any, **kw: Any) -> None: recorded.append((claim, kw))
        def reconcile_publication(self, claim: JobClaim, **kw: Any) -> str: return {"job-present": "succeeded", "job-absent": "queued", "job-conflicting": "quarantined"}.get(claim.job_id, "reconciliation_required")
        def acquire_singleton(self, instance_id: str, ttl: timedelta) -> int: return 1
        def stop_singleton(self, instance_id: str, fencing_epoch: int) -> bool: return True

    def reader(c: object) -> Mapping[str, object] | None:
        if not isinstance(c, JobClaim): return None
        gens = {"source_generation": "sg1:t", "config_generation": "cg1:t", "extractor_generation": "eg1:t", "canonicalizer_generation": "kg1:t"}
        routes = {"job-present": {"latest_run_identity": "r-present", **gens}, "job-conflicting": {"latest_run_identity": "r-conflict", **gens}}
        if c.job_id in routes: return routes[c.job_id]
        if c.job_id == "job-route-changed": raise PublicationRouteChangedError("route mismatch")
        if c.job_id == "job-unavailable": raise RuntimeError("storage unavailable")
        return None

    rep = recover_startup(FakeStore(), reader, instance_id="coord-rep", fencing_epoch=42, limit=10)
    assert (rep.scanned, rep.resolved, rep.pending, rep.route_changed, rep.unavailable) == (5, 3, 2, 1, 1) and len(recorded) == 2 and recorded[0][1]["run_identity"] == "r-present"



def _expired_refresh_claim(store, connect, request):
    epoch = store.acquire_singleton("legacy-owner", timedelta(seconds=30))
    submitted = store.submit(request)
    claim = store.claim_next("legacy-owner", epoch, timedelta(seconds=30))
    assert claim is not None and claim.job_id == submitted.job_id
    for before, after in (("claimed", "starting"), ("starting", "running")):
        assert store.compare_and_set_state(claim.job_id, expected_state=before, new_state=after,
            attempt=claim.attempt, instance_id=claim.instance_id, fencing_epoch=epoch)
    # Leave a crashed running attempt for startup's abandonment owner to retire.
    # Merely marking reconciliation_required does not record attempt completion.
    with connect() as connection:
        connection.execute("UPDATE coordinator_instances SET expires_at = now() - interval '1 second'")
        connection.execute("UPDATE graph_leases SET expires_at = now() - interval '1 second'")
    return claim


def test_quarantine_legacy_zero_epoch_and_replacement_scheduling() -> None:
    from repomap_kg.coordinator.configured_refresh import ConfiguredRefreshResolver
    from repomap_kg.coordinator.core import SyntheticCoordinator
    from repomap_test_support.startup_recovery_scenarios import (
        _refresh_harness, _make_refresh_fixture, _req_norm, _run_real_refresh_attempt,
    )
    with _refresh_harness() as (store, cap_dir, connect, postgres, graph_db):
        config, sg, cg, eg, kg = _make_refresh_fixture(postgres, cap_dir, graph_db)
        claim = _expired_refresh_claim(store, connect, _req_norm("legacy-zero", sg, cg, eg, kg))
        with connect() as connection:
            connection.execute("UPDATE job_attempts SET graph_lease_fencing_epoch = 0 WHERE job_id = %s", (claim.job_id,))
            connection.execute("UPDATE graph_leases SET graph_lease_fencing_epoch = 0 WHERE job_id = %s", (claim.job_id,))
        coordinator = SyntheticCoordinator(store, "replacement", lambda *_: {})
        coordinator.startup(coordinator.recover_startup)
        with connect() as connection:
            assert connection.execute(
                "SELECT finished_at IS NOT NULL FROM job_attempts WHERE job_id = %s",
                (claim.job_id,),
            ).fetchone() == (True,)
        try:
            assert cast(StartupRecoveryReport, coordinator.startup_recovery_report).pending == 1
            with connect() as connection:
                assert connection.execute("SELECT count(*) FROM graph_leases WHERE job_id = %s", (claim.job_id,)).fetchone() == (1,)
            resolver = ConfiguredRefreshResolver(config, Path(postgres.psql_command))
            store.set_durable_fence_callback(resolver.install_graph_publication_fence)
            report = coordinator.recover_startup()
            assert (report.resolved, report.pending) == (1, 0)
            status = store.status(claim.job_id)
            assert (status.state, status.publication_state, status.error_category) == ("quarantined", "commit_unknown", "legacy_zero_epoch")
            with connect() as connection:
                assert connection.execute("SELECT count(*) FROM graph_leases WHERE job_id = %s", (claim.job_id,)).fetchone() == (0,)
            with psycopg.connect(host=postgres.host, port=postgres.port, user=postgres.user,
                                 password=postgres.password, dbname=graph_db) as graph:
                fence = graph.execute("SELECT singleton_fencing_epoch, graph_lease_fencing_epoch FROM graph_publication_authority").fetchone()
                assert fence is not None
                assert fence[0] > claim.fencing_epoch and fence[1] > 0
            submitted = store.submit(_req_norm("legacy-replacement", sg, cg, eg, kg))
            replacement = store.claim_next("replacement", coordinator._require_started(), timedelta(seconds=30))
            assert replacement is not None and replacement.job_id == submitted.job_id
            assert replacement.graph_lease_fencing_epoch > 0
            cap2 = cap_dir / "replacement"
            cap2.mkdir(mode=0o700)
            result = _run_real_refresh_attempt(postgres, cap2, replacement, config, sg, cg, eg, kg)
            assert result["status"] == "succeeded"
        finally:
            coordinator.shutdown()


def test_publication_authority_rowlock_bounded_and_singleton_renewed() -> None:
    import time
    from repomap_kg.coordinator import _publication_phase
    from repomap_kg.coordinator.configured_refresh import ConfiguredRefreshResolver
    from repomap_kg.coordinator.core import SyntheticCoordinator
    from repomap_test_support.startup_recovery_scenarios import _refresh_harness, _make_refresh_fixture, _req_norm
    with _refresh_harness() as (store, cap_dir, connect, postgres, graph_db):
        config, sg, cg, eg, kg = _make_refresh_fixture(postgres, cap_dir, graph_db)
        claim = _expired_refresh_claim(store, connect, _req_norm("row-contention", sg, cg, eg, kg))
        _publication_phase.initialize(cap_dir, claim)
        coordinator = SyntheticCoordinator(store, "replacement", lambda *_: {},
            publication_reader=lambda c: {"publication_state": _publication_phase.publication_state(cap_dir, c)},
            publication_closer=lambda c, proof: _publication_phase.close_unpublished(cap_dir, c, proof=cast(_publication_phase.WorkerFencingProof, proof)))
        coordinator.startup(coordinator.recover_startup)
        resolver = ConfiguredRefreshResolver(config, Path(postgres.psql_command))
        epoch = coordinator._require_started()
        resolver.install_graph_publication_fence(claim, reconciler_instance_id="replacement",
            reconciler_epoch=epoch, prior_lease_epoch=claim.graph_lease_fencing_epoch)
        store.set_durable_fence_callback(resolver.install_graph_publication_fence)
        try:
            with connect() as connection:
                assert connection.execute(
                    "SELECT finished_at IS NOT NULL FROM job_attempts WHERE job_id = %s",
                    (claim.job_id,),
                ).fetchone() == (True,)
            with psycopg.connect(host=postgres.host, port=postgres.port, user=postgres.user,
                                 password=postgres.password, dbname=graph_db) as orphan:
                orphan.execute("SELECT 1 FROM graph_publication_authority FOR UPDATE")
                started = time.monotonic()
                assert coordinator.heartbeat() is True
                elapsed = time.monotonic() - started
                assert elapsed < 5
                report = cast(StartupRecoveryReport, coordinator.startup_recovery_report)
                assert report.pending == 1 and report.refused == 1 and not report.unexpected
                with connect() as connection:
                    active = connection.execute("SELECT expires_at > clock_timestamp() FROM coordinator_instances WHERE instance_id = 'replacement'").fetchone()
                    assert active == (True,)
                assert _publication_phase.publication_state(cap_dir, claim) == "commit_unknown"
                orphan.rollback()
            assert coordinator.heartbeat() is True
            report = cast(StartupRecoveryReport, coordinator.startup_recovery_report)
            assert (report.resolved, report.pending, report.refused, report.unexpected) == (1, 0, 0, ())
            assert store.status(claim.job_id).state == "queued"
        finally:
            coordinator.shutdown()
