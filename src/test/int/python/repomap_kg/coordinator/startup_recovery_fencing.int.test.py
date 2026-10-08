from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import cast
import psycopg

from repomap_kg.coordinator import _publication_phase
from repomap_kg.coordinator.core import SyntheticCoordinator
from repomap_kg.coordinator.startup_recovery import StartupRecoveryReport


from repomap_test_support.startup_recovery_scenarios import (
    _harness, _make_refresh_fixture, _refresh_harness, _req, _req_norm,
    _run_real_refresh_attempt,
)


def test_connected_startup_recovery_refuses_closure_when_worker_lease_not_fenced() -> None:
    with _harness() as (store, cap_dir, connect):
        sub = store.submit(_req("synthetic-g1", "unfenced-recovery"))
        epoch = store.acquire_singleton("inst-live", timedelta(seconds=300))
        claim = store.claim_next("inst-live", epoch, timedelta(seconds=300))
        assert claim is not None
        for exp, nxt in (("claimed", "starting"), ("starting", "running")):
            assert store.compare_and_set_state(
                claim.job_id, expected_state=exp, new_state=nxt,
                attempt=claim.attempt, instance_id=claim.instance_id, fencing_epoch=claim.fencing_epoch
            )
        store.mark_reconciliation_required(claim, expected_state="running", category="worker_crash")
        # Notice: mark_attempt_terminated is deliberately NOT called!
        # Lease is still active and finished_at is NULL.
        store.stop_singleton("inst-live", epoch)
        _publication_phase.initialize(cap_dir, claim)
        init_p = _publication_phase._path(cap_dir, claim, "initial")
        dec_p = _publication_phase._path(cap_dir, claim, "decision")
        assert init_p.is_file() and not dec_p.exists()

        coord = SyntheticCoordinator(
            store,
            "inst-rec-unfenced",
            lambda _c, _x: {"status": "failed", "_termination_proved": True},
            publication_reader=lambda c: {"publication_state": _publication_phase.publication_state(cap_dir, c)},
            publication_retirer=lambda c: _publication_phase.retire_evidence(cap_dir, c),
            publication_closer=lambda c, proof: _publication_phase.close_unpublished(cap_dir, c, proof=cast(_publication_phase.WorkerFencingProof, proof)),
        )
        coord.startup(coord.recover_startup)
        try:
            assert coord.startup_recovery_report is not None
            assert cast(StartupRecoveryReport, coord.startup_recovery_report).resolved == 0
            assert cast(StartupRecoveryReport, coord.startup_recovery_report).pending == 1
            # Job must remain reconciliation_required and commit_unknown because worker cannot be proved fenced
            status = store.status(sub.job_id)
            assert status.state == "reconciliation_required"
            assert status.publication_state == "commit_unknown"
            # Decision file must NOT have been written; initial remains
            assert not dec_p.exists()
            assert init_p.is_file()
        finally:
            coord.shutdown()


def test_connected_startup_recovery_closes_superseded_fenced_dead_attempt() -> None:
    with _refresh_harness() as (store, cap_dir, connect, postgres, graph_db):
        config, sg, cg, eg, kg = _make_refresh_fixture(postgres, cap_dir, graph_db)
        sub = store.submit(_req_norm("superseded-crashed", sg, cg, eg, kg))
        epoch = store.acquire_singleton("inst-prior", timedelta(seconds=30))
        claim = store.claim_next("inst-prior", epoch, timedelta(seconds=30))
        assert claim is not None
        for before, after in (("claimed", "starting"), ("starting", "running")):
            assert store.compare_and_set_state(claim.job_id, expected_state=before, new_state=after,
                attempt=claim.attempt, instance_id=claim.instance_id, fencing_epoch=claim.fencing_epoch)
        checkpoint: dict[str, object] = {}
        interrupted = _run_real_refresh_attempt(
            postgres, cap_dir, claim, config, sg, cg, eg, kg,
            pause_env_var="_REPOMAP_SYSTEM_TEST_STAGED_PAUSE_PATH", pause_path=cap_dir / "paused-stage",
            launch_registrar=store.register_supervisor_launch, checkpoint=checkpoint,
        )
        assert interrupted["publication_state"] == "commit_unknown" and interrupted["_termination_proved"] is True
        with connect() as connection:
            assert connection.execute("SELECT finished_at FROM job_attempts WHERE job_id = %s", (sub.job_id,)).fetchone() == (None,)
            # Hard crash: no terminal/reap/abandonment API is called by the old coordinator.
            connection.execute("UPDATE coordinator_instances SET expires_at = now() - interval '1 second'")
            connection.execute("UPDATE graph_leases SET expires_at = now() - interval '1 second' WHERE job_id = %s", (sub.job_id,))
        coord = SyntheticCoordinator(store, "inst-new-owner", lambda *_: {},
            publication_reader=lambda c: {"publication_state": _publication_phase.publication_state(cap_dir, c)},
            publication_closer=lambda c, proof: _publication_phase.close_unpublished(cap_dir, c, proof=cast(_publication_phase.WorkerFencingProof, proof)))
        coord.startup(coord.recover_startup)
        try:
            assert cast(StartupRecoveryReport, coord.startup_recovery_report).pending == 1
            assert store.status(sub.job_id).publication_state == "commit_unknown"
            with connect() as connection:
                assert connection.execute("SELECT finished_at IS NOT NULL FROM job_attempts WHERE job_id = %s", (sub.job_id,)).fetchone() == (True,)
            # The timestamp stamped by startup still has not authorized closure.
            from repomap_kg.coordinator.configured_refresh import ConfiguredRefreshResolver
            resolver = ConfiguredRefreshResolver(config, Path(postgres.psql_command))
            store.set_durable_fence_callback(resolver.install_graph_publication_fence)
            report = coord.recover_startup()
            assert (report.resolved, report.pending) == (1, 0)
            assert (store.status(sub.job_id).state, store.status(sub.job_id).publication_state) == ("queued", "not_started")
            with connect() as connection:
                assert connection.execute("SELECT publication_state FROM job_attempts WHERE job_id = %s", (sub.job_id,)).fetchone() == ("not_started",)
            # Resume the real validated handoff retained at interruption, so
            # the assertion exercises the final durable publication fence.
            from repomap_kg.storage.staged_ingestion import IngestionAuthority
            from repomap_kg.storage.authority import OperationId, JobId, AttemptNumber
            from repomap_kg.storage.publication import publication_receipt_from_mapping
            from repomap_kg.storage.publication_fencing import PublicationHandoff
            from repomap_kg.storage.staging_merge import MergeContext
            from repomap_kg.storage.staged_publication import execute_final_transaction, existing_stage_state
            import pytest

            authority = IngestionAuthority(
                operation_id=OperationId(claim.job_id), job_id=JobId(claim.job_id),
                attempt=AttemptNumber(claim.attempt), execution_mode="coordinator",
                source_generation=sg, config_generation=cg, extractor_generation=eg,
                canonicalizer_generation=kg, coordinator_instance_id=claim.instance_id,
                singleton_fencing_epoch=claim.fencing_epoch, graph_lease_fencing_epoch=claim.graph_lease_fencing_epoch,
            )
            assert isinstance(checkpoint["repository_id"], int) and not isinstance(checkpoint["repository_id"], bool)
            assert isinstance(checkpoint["stage_id"], str)
            assert isinstance(checkpoint["run_id"], int) and not isinstance(checkpoint["run_id"], bool)
            receipt = publication_receipt_from_mapping(checkpoint["receipt"])
            assert receipt is not None
            owner = authority.owner(checkpoint["repository_id"])
            handoff = PublicationHandoff(
                MergeContext(checkpoint["stage_id"], owner, checkpoint["run_id"]),
                receipt,
            ).validate()
            with psycopg.connect(
                host=postgres.host, port=postgres.port, user=postgres.user,
                dbname=graph_db, password=postgres.password,
            ) as graph_connection:
                assert existing_stage_state(graph_connection, checkpoint["stage_id"], owner) == "validated"
                with pytest.raises(psycopg.errors.RaiseException, match="SCALE5 stale publication fence") as refusal:
                    execute_final_transaction(graph_connection, handoff)
                assert refusal.value.sqlstate == "P0001"
                graph_connection.rollback()
                repository = graph_connection.execute(
                    "SELECT id FROM repositories WHERE repository_identity = %s",
                    ("repo1:synthetic-g1",),
                ).fetchone()
                assert repository is not None
                # Authority recorded replacement reconciler fence with the same claim attempt,
                # NOT the stale coordinator instance or superseded singleton epoch.
                auth_row = graph_connection.execute(
                    "SELECT singleton_fencing_epoch, coordinator_instance_id, attempt "
                    "FROM graph_publication_authority WHERE repository_id = %s",
                    (repository[0],),
                ).fetchone()
                assert auth_row is not None
                assert auth_row[0] > claim.fencing_epoch
                assert auth_row[1] == "inst-new-owner"
                assert auth_row[1] != claim.instance_id
                assert auth_row[2] == claim.attempt
                # Verify complete rollback: no partial publication was committed by stale attempt
                assert graph_connection.execute("SELECT count(*) FROM files").fetchone() == (0,)
                assert graph_connection.execute("SELECT count(*) FROM canonical_nodes").fetchone() == (0,)
                assert graph_connection.execute(
                    "SELECT count(*) FROM runs WHERE status = 'complete'"
                ).fetchone() == (0,)

            from repomap_test_support.startup_recovery_scenarios import _assert_retry_waiting_and_advance
            _assert_retry_waiting_and_advance(store, connect, claim, "inst-new-owner", coord._require_started())
            # Replacement attempt claims the eligible job, executes, and publishes cleanly
            claim2 = store.claim_next("inst-new-owner", coord._require_started(), timedelta(seconds=30))
            assert claim2 is not None
            assert claim2.attempt == 2
            assert claim2.instance_id == "inst-new-owner"
            assert claim2.fencing_epoch > claim.fencing_epoch
            assert claim2.graph_lease_fencing_epoch > claim.graph_lease_fencing_epoch
            cap2_dir = Path(cap_dir) / "cap2"
            cap2_dir.mkdir(parents=True, exist_ok=True)
            cap2_dir.chmod(0o700)
            res2 = _run_real_refresh_attempt(postgres, cap2_dir, claim2, config, sg, cg, eg, kg)
            assert res2.get("status") == "succeeded"
        finally:
            coord.shutdown()


def test_connected_startup_recovery_refuses_closure_when_graph_lease_is_active() -> None:
    with _harness() as (store, cap_dir, connect):
        sub = store.submit(_req("synthetic-g1", "active-lease-recovery"))
        epoch = store.acquire_singleton("inst-prior", timedelta(seconds=30))
        claim = store.claim_next("inst-prior", epoch, timedelta(seconds=30))
        assert claim is not None
        for exp, nxt in (("claimed", "starting"), ("starting", "running")):
            assert store.compare_and_set_state(
                claim.job_id, expected_state=exp, new_state=nxt,
                attempt=claim.attempt, instance_id=claim.instance_id, fencing_epoch=claim.fencing_epoch
            )
        store.mark_reconciliation_required(claim, expected_state="running", category="worker_crash")
        # Keep graph lease active and unexpired, stop prior singleton
        store.stop_singleton("inst-prior", epoch)
        _publication_phase.initialize(cap_dir, claim)
        init_p = _publication_phase._path(cap_dir, claim, "initial")
        assert init_p.is_file()

        fence_calls = []
        def record_fence(*a, **k):
            fence_calls.append(a)
            return True
        store.set_durable_fence_callback(record_fence)
        coord = SyntheticCoordinator(
            store,
            "inst-new-owner",
            lambda _c, _x: {"status": "failed", "_termination_proved": True},
            publication_reader=lambda c: {"publication_state": _publication_phase.publication_state(cap_dir, c)},
            publication_retirer=lambda c: _publication_phase.retire_evidence(cap_dir, c),
            publication_closer=lambda c, proof: _publication_phase.close_unpublished(cap_dir, c, proof=cast(_publication_phase.WorkerFencingProof, proof)),
        )
        coord.startup(coord.recover_startup)
        try:
            assert coord.startup_recovery_report is not None
            assert cast(StartupRecoveryReport, coord.startup_recovery_report).resolved == 0
            assert cast(StartupRecoveryReport, coord.startup_recovery_report).pending == 1
            assert store.status(sub.job_id).state == "reconciliation_required"
            assert store.status(sub.job_id).publication_state == "commit_unknown"
            assert init_p.is_file()
            assert fence_calls == []
        finally:
            coord.shutdown()


def test_connected_startup_recovery_contention_preserves_singleton_liveness() -> None:
    import time
    with _refresh_harness() as (store, cap_dir, connect, postgres, graph_db):
        config, sg, cg, eg, kg = _make_refresh_fixture(postgres, cap_dir, graph_db)
        sub = store.submit(_req_norm("contention-crashed", sg, cg, eg, kg))
        epoch = store.acquire_singleton("inst-prior", timedelta(seconds=30))
        claim = store.claim_next("inst-prior", epoch, timedelta(seconds=30))
        assert claim is not None
        for before, after in (("claimed", "starting"), ("starting", "running")):
            store.compare_and_set_state(claim.job_id, expected_state=before, new_state=after,
                attempt=claim.attempt, instance_id=claim.instance_id, fencing_epoch=claim.fencing_epoch)
        _publication_phase.initialize(cap_dir, claim)
        with connect() as connection:
            connection.execute("UPDATE coordinator_instances SET expires_at = now() - interval '1 second'")
            connection.execute("UPDATE graph_leases SET expires_at = now() - interval '1 second' WHERE job_id = %s", (sub.job_id,))

        from repomap_kg.coordinator.configured_refresh import ConfiguredRefreshResolver
        resolver = ConfiguredRefreshResolver(config, Path(postgres.psql_command))
        store.set_durable_fence_callback(resolver.install_graph_publication_fence)

        coord = SyntheticCoordinator(store, "inst-new-contention", lambda *_: {},
            publication_reader=lambda c: {"publication_state": _publication_phase.publication_state(cap_dir, c)},
            publication_closer=lambda c, proof: _publication_phase.close_unpublished(cap_dir, c, proof=cast(_publication_phase.WorkerFencingProof, proof)))
        try:
            # Establish contention before startup attempts its first closure.
            with psycopg.connect(host=postgres.host, port=postgres.port, user=postgres.user,
                                 dbname=graph_db, password=postgres.password) as lock_conn:
                lock_conn.execute("BEGIN;")
                lock_conn.execute("LOCK TABLE repositories IN ACCESS EXCLUSIVE MODE;")

                started = time.monotonic()
                coord.startup(coord.recover_startup)
                report = cast(StartupRecoveryReport, coord.startup_recovery_report)
                assert (report.pending, report.refused, report.unexpected) == (1, 1, ())
                assert coord.heartbeat() is True  # Coordinator singleton remains alive
                assert time.monotonic() - started < 5
                assert store.status(sub.job_id).state == "reconciliation_required"
                assert _publication_phase.publication_state(cap_dir, claim) == "commit_unknown"
                lock_conn.rollback()
            assert coord.heartbeat() is True
            report = cast(StartupRecoveryReport, coord.startup_recovery_report)
            assert (report.resolved, report.pending, report.refused, report.unexpected) == (1, 0, 0, ())
            assert store.status(sub.job_id).state == "queued"
        finally:
            coord.shutdown()


def test_legacy_zero_epoch_without_storage_fence_remains_uncertain() -> None:
    with _harness() as (store, cap_dir, connect):
        sub = store.submit(_req("synthetic-g1", "zero-epoch-legacy"))
        epoch = store.acquire_singleton("inst-prior", timedelta(seconds=30))
        claim = store.claim_next("inst-prior", epoch, timedelta(seconds=30))
        assert claim is not None
        for exp, nxt in (("claimed", "starting"), ("starting", "running")):
            store.compare_and_set_state(
                claim.job_id, expected_state=exp, new_state=nxt,
                attempt=claim.attempt, instance_id=claim.instance_id, fencing_epoch=claim.fencing_epoch
            )
        store.mark_reconciliation_required(claim, expected_state="running", category="worker_crash")
        store.stop_singleton("inst-prior", epoch)
        # Simulate legacy record by setting graph_lease_fencing_epoch to 0
        with connect() as connection:
            connection.execute(
                "UPDATE job_attempts SET graph_lease_fencing_epoch = 0 WHERE job_id = %s AND attempt = %s",
                (claim.job_id, claim.attempt),
            )
            connection.execute(
                "UPDATE graph_leases SET graph_lease_fencing_epoch = 0 WHERE job_id = %s AND attempt = %s",
                (claim.job_id, claim.attempt),
            )
        coord = SyntheticCoordinator(
            store,
            "inst-recovery-zero-epoch",
            lambda _c, _x: {"status": "failed", "_termination_proved": True},
            publication_reader=lambda c: {"publication_state": "commit_unknown"},
            publication_retirer=lambda c: (),
            publication_closer=lambda c, p: False,
        )
        coord.startup(coord.recover_startup)
        try:
            assert coord.startup_recovery_report is not None
            report = cast(StartupRecoveryReport, coord.startup_recovery_report)
            assert (report.resolved, report.pending) == (0, 1)
            status = store.status(sub.job_id)
            assert status.state == "reconciliation_required"
            assert status.publication_state == "commit_unknown"
            with connect() as connection:
                assert connection.execute("SELECT 1 FROM graph_leases WHERE graph_id = %s", (claim.graph_id,)).fetchone() == (1,)
        finally:
            coord.shutdown()
