"""Behavioral integration tests for Product5 fencing and supervisor registration contracts."""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg.rows import dict_row
from repomap_kg.coordinator import _publication_phase
from repomap_kg.coordinator._control_types import JobClaim
from repomap_kg.coordinator._restart_fencing import (
    StaleDurableAuthorityError,
)
from repomap_kg.coordinator._supervisor_fencing import (
    register_worker_launch,
    release_unlaunched_registration,
)
from repomap_kg.coordinator._supervisor_registration import (
    FencingContentionError,
    in_process_currency_context,
    lock_and_validate_current_durable,
    persist_supervisor_registration,
    validate_supervisor_registration,
)
from repomap_kg.coordinator.configured_refresh import ConfiguredRefreshResolver
from repomap_kg.coordinator.refresh_adapter import (
    RefreshCapability,
    create_refresh_capability,
)
from repomap_kg.ops.config import load_ops_config
from repomap_kg.runtime.postgres_route import effective_postgres_route
from repomap_test_support.startup_recovery_scenarios import (
    _harness,
    _make_refresh_fixture,
    _refresh_harness,
    _req,
    _req_norm,
    _run_real_refresh_attempt,
    _search_path,
)


def _to_running(store: Any, claim: JobClaim, epoch: int) -> None:
    for exp, nxt in (("claimed", "starting"), ("starting", "running")):
        assert store.compare_and_set_state(
            claim.job_id, expected_state=exp, new_state=nxt,
            attempt=claim.attempt, instance_id=claim.instance_id, fencing_epoch=epoch,
        )


def test_supervisor_launch_command_and_identity_validation() -> None:
    with _refresh_harness() as (store, cap_dir, connect, postgres, graph_db):
        config, sg, cg, eg, kg = _make_refresh_fixture(postgres, cap_dir, graph_db)
        store.submit(_req_norm("launch-val", sg, cg, eg, kg))
        epoch = store.acquire_singleton("inst-launch-val", timedelta(seconds=300))
        claim = store.claim_next("inst-launch-val", epoch, timedelta(seconds=300))
        assert claim is not None
        _to_running(store, claim, epoch)

        route = effective_postgres_route(load_ops_config(config))
        capability = RefreshCapability(
            schema_version=1, job_id=claim.job_id, attempt=claim.attempt, graph_id=claim.graph_id,
            config_path=config, psql_path=Path(postgres.psql_command), postgres_user=postgres.user,
            postgres_host=route.host, postgres_port=route.port, postgres_route_kind=route.kind,
            postgres_password=postgres.password, executable_search_path=_search_path(),
            source_generation=sg, config_generation=cg, extractor_generation=eg, canonicalizer_generation=kg,
            coordinator_instance_id=claim.instance_id, singleton_fencing_epoch=epoch,
            graph_lease_fencing_epoch=claim.graph_lease_fencing_epoch,
        )
        sealed = create_refresh_capability(cap_dir, capability)
        valid_argv = (
            sys.executable, "-m", "repomap_kg.coordinator.refresh_worker",
            "--capability", str(sealed), "--job-id", claim.job_id, "--attempt", str(claim.attempt),
        )

        # 1. Invalid command argv length or alternate module
        bad_argv = (sys.executable, "-m", "wrong.module", "--capability", str(sealed))
        with pytest.raises(PermissionError, match="alternate worker executable or command"):
            register_worker_launch(capability, bad_argv)

        # 2. Identity mismatch in argv
        mismatch_argv = (
            sys.executable, "-m", "repomap_kg.coordinator.refresh_worker",
            "--capability", str(sealed), "--job-id", "wrong-job", "--attempt", str(claim.attempt),
        )
        with pytest.raises(PermissionError, match="identity mismatch"):
            register_worker_launch(capability, mismatch_argv)

        # 3. Tampered sealed capability file content
        original_bytes = sealed.read_bytes()
        payload = json.loads(original_bytes)
        payload["job_id"] = "different-job"
        sealed.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(PermissionError, match="sealed capability does not match launch authority"):
            register_worker_launch(capability, valid_argv)
        sealed.write_bytes(original_bytes)

        # 4. Valid launch registration and duplicate prevention
        ticket = register_worker_launch(capability, valid_argv)
        assert len(ticket.registration_digest) == 64
        with pytest.raises(PermissionError, match="attempt already has a live launch registration"):
            register_worker_launch(capability, valid_argv)

        # 5. Release unlaunched registration allows re-registration
        release_unlaunched_registration(ticket)
        ticket2 = register_worker_launch(capability, valid_argv)
        assert ticket2.token != ticket.token

        # 6. Bind durable launch identity mismatch refusal vs valid persistence
        mismatched_cap = RefreshCapability(
            schema_version=1, job_id="other-job", attempt=claim.attempt, graph_id=claim.graph_id,
            config_path=config, psql_path=Path(postgres.psql_command), postgres_user=postgres.user,
            postgres_host=route.host, postgres_port=route.port, postgres_route_kind=route.kind,
            postgres_password=postgres.password, executable_search_path=_search_path(),
            source_generation=sg, config_generation=cg, extractor_generation=eg, canonicalizer_generation=kg,
            coordinator_instance_id=claim.instance_id, singleton_fencing_epoch=epoch,
            graph_lease_fencing_epoch=claim.graph_lease_fencing_epoch,
        )
        with pytest.raises(PermissionError, match="durable registration requires the exact unlaunched capability"):
            store.register_supervisor_launch(ticket2, mismatched_cap)

        store.register_supervisor_launch(ticket2, capability)
        with connect() as conn:
            row = conn.execute(
                "SELECT supervisor_registration_digest, supervisor_registration_consumed FROM job_attempts WHERE job_id = %s AND attempt = %s",
                (claim.job_id, claim.attempt),
            ).fetchone()
            assert row == (ticket2.registration_digest, False)

        release_unlaunched_registration(ticket2)
        sealed.unlink(missing_ok=True)
        store.stop_singleton("inst-launch-val", epoch)


def test_durable_closure_and_fencing_proof_refusals_and_success() -> None:
    with _refresh_harness() as (store, cap_dir, connect, postgres, graph_db):
        config, sg, cg, eg, kg = _make_refresh_fixture(postgres, cap_dir, graph_db, graph_id="synthetic-proof")
        resolver = ConfiguredRefreshResolver(config, Path(postgres.psql_command))
        real_fence = lambda cl, **kw: resolver.install_graph_publication_fence(cl, **kw)
        sub = store.submit(_req_norm("proof-key", sg, cg, eg, kg, graph_id="synthetic-proof"))
        epoch1 = store.acquire_singleton("inst-p1", timedelta(seconds=300))
        claim = store.claim_next("inst-p1", epoch1, timedelta(seconds=300))
        assert claim is not None
        _to_running(store, claim, epoch1)
        assert store.mark_reconciliation_required(claim, expected_state="running", category="worker_crash")
        assert store.mark_attempt_terminated(claim, process_cleanup_proved=True)
        with connect() as conn:
            conn.execute("UPDATE graph_leases SET expires_at = now() - interval '1 second' WHERE job_id = %s", (sub.job_id,))
        store.stop_singleton("inst-p1", epoch1)

        epoch2 = store.acquire_singleton("inst-p2", timedelta(seconds=300))
        assert epoch2 > epoch1

        _publication_phase.initialize(cap_dir, claim)
        closer = lambda cl, proof: _publication_phase.close_unpublished(cap_dir, cl, proof=proof)
        # Unavailable graph fencing cannot produce authority or alter either plane.
        assert store.prove_worker_fenced(claim, reconciler_instance_id="inst-p2", reconciler_epoch=epoch2) is None
        assert not store.close_unpublished_reconciliation(claim, reconciler_instance_id="inst-p2", reconciler_epoch=epoch2, file_closer=closer)
        store.set_durable_fence_callback(real_fence)
        assert store.prove_worker_fenced(claim, reconciler_instance_id="inst-p2", reconciler_epoch=epoch1) is None
        identity_proof = store.prove_worker_fenced(claim, reconciler_instance_id="inst-p2", reconciler_epoch=epoch2)
        assert identity_proof is not None
        other = replace(claim, job_id="different-job")
        with pytest.raises(ValueError, match="identity mismatch"):
            identity_proof.open_closure_context(other)
        with pytest.raises(PermissionError, match="consumed"):
            identity_proof.open_closure_context(claim)
        assert store.status(claim.job_id).publication_state == "commit_unknown"

        # A refused external fence consumes the proof without guessing rollback.
        store.set_durable_fence_callback(lambda *args, **kw: False)
        proof = store.prove_worker_fenced(claim, reconciler_instance_id="inst-p2", reconciler_epoch=epoch2)
        assert proof is not None
        assert not closer(claim, proof)
        with pytest.raises(PermissionError, match="consumed"):
            proof.open_closure_context(claim)
        assert store.status(claim.job_id).publication_state == "commit_unknown"

        store.set_durable_fence_callback(real_fence)
        assert not store.close_unpublished_reconciliation(claim, reconciler_instance_id="inst-p2", reconciler_epoch=epoch2, file_closer=lambda *_: False)
        assert store.status(claim.job_id).publication_state == "commit_unknown"
        assert store.close_unpublished_reconciliation(claim, reconciler_instance_id="inst-p2", reconciler_epoch=epoch2, file_closer=closer)
        with connect() as conn:
            assert conn.execute("SELECT publication_state FROM jobs WHERE job_id = %s", (claim.job_id,)).fetchone() == ("not_started",)
            assert conn.execute("SELECT publication_state, supervisor_registration_digest FROM job_attempts WHERE job_id = %s", (claim.job_id,)).fetchone() == ("not_started", None)
        assert _publication_phase.publication_state(cap_dir, claim) == "not_started"
        with psycopg.connect(host=postgres.host, port=postgres.port, user=postgres.user, dbname=graph_db, password=postgres.password) as gconn:
            assert gconn.execute("SELECT singleton_fencing_epoch, coordinator_instance_id FROM graph_publication_authority").fetchone() == (epoch2, "inst-p2")

        with connect() as conn: conn.execute("UPDATE jobs SET state = 'queued' WHERE job_id = %s", (claim.job_id,))
        with pytest.raises(StaleDurableAuthorityError):
            store.close_unpublished_reconciliation(claim, reconciler_instance_id="inst-p2", reconciler_epoch=epoch2, file_closer=closer)
        store.stop_singleton("inst-p2", epoch2)


def test_supervisor_currency_lock_validation_and_contention() -> None:
    with _harness() as (store, _, connect):
        store.submit(_req("synthetic-curr-lock", "curr-lock-key"))
        epoch = store.acquire_singleton("inst-live-curr", timedelta(seconds=300))
        claim = store.claim_next("inst-live-curr", epoch, timedelta(seconds=300))
        assert claim is not None
        _to_running(store, claim, epoch)

        # 1. lock_and_validate_current_durable conditions
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                assert lock_and_validate_current_durable(cur, claim, reconciler_instance_id="other-inst", reconciler_epoch=epoch, restart=False) is None
                assert lock_and_validate_current_durable(cur, claim, reconciler_instance_id=claim.instance_id, reconciler_epoch=epoch + 1, restart=False) is None
                mismatched_claim = JobClaim(
                    claim.job_id, claim.graph_id, claim.attempt, claim.instance_id, claim.fencing_epoch,
                    source_generation="sg1:wrong-sg", config_generation=claim.config_generation,
                    extractor_generation=claim.extractor_generation, canonicalizer_generation=claim.canonicalizer_generation,
                    graph_lease_fencing_epoch=claim.graph_lease_fencing_epoch,
                )
                assert lock_and_validate_current_durable(cur, mismatched_claim, reconciler_instance_id=claim.instance_id, reconciler_epoch=epoch, restart=False) is None
                row = lock_and_validate_current_durable(cur, claim, reconciler_instance_id=claim.instance_id, reconciler_epoch=epoch, restart=False)
                assert row is not None and row["job_id"] == claim.job_id

        # 2. persist_supervisor_registration validation and double-persist refusal
        with pytest.raises(PermissionError, match="invalid supervisor registration digest"): persist_supervisor_registration(connect, claim, "not-a-hex-digest")
        with pytest.raises(PermissionError, match="invalid supervisor registration digest"): persist_supervisor_registration(connect, claim, "abc123")

        valid_digest = "a" * 64
        persist_supervisor_registration(connect, claim, valid_digest)
        for stale in (
            replace(claim, job_id="missing-job"),
            replace(claim, graph_id="different-graph"),
            replace(claim, source_generation="sg1:different"),
            replace(claim, graph_lease_fencing_epoch=0),
            replace(claim, graph_lease_fencing_epoch=claim.graph_lease_fencing_epoch + 1),
        ):
            with pytest.raises(StaleDurableAuthorityError, match="turned over"):
                validate_supervisor_registration(connect, stale, valid_digest)
        with connect() as conn:
            assert conn.execute("SELECT supervisor_registration_digest, supervisor_registration_consumed FROM job_attempts WHERE job_id = %s", (claim.job_id,)).fetchone() == (valid_digest, False)
        with pytest.raises(PermissionError, match="already exists or was consumed"):
            persist_supervisor_registration(connect, claim, "b" * 64)

        # 3. in_process_currency_context consumption and replay refusal
        with pytest.raises(StaleDurableAuthorityError, match="durable launch registration is required"):
            with in_process_currency_context(connect, claim, "short"): pass
        with pytest.raises(StaleDurableAuthorityError, match="turned over"):
            with in_process_currency_context(connect, claim, "c" * 64): pass

        with in_process_currency_context(connect, claim, valid_digest) as locked_conn:
            assert locked_conn is not None

        with pytest.raises(StaleDurableAuthorityError, match="turned over"):
            with in_process_currency_context(connect, claim, valid_digest): pass

        # 4. Rowlock contention: FencingContentionError under held lock
        store.submit(_req("synthetic-curr-lock-2", "curr-lock-key-2"))
        claim2 = store.claim_next("inst-live-curr", epoch, timedelta(seconds=300))
        assert claim2 is not None
        assert store.compare_and_set_state(claim2.job_id, expected_state="claimed", new_state="starting", attempt=claim2.attempt, instance_id=claim2.instance_id, fencing_epoch=epoch)

        with connect() as blocker_conn:
            blocker_conn.execute("BEGIN;")
            blocker_conn.execute("SELECT 1 FROM coordinator_instances WHERE instance_id = %s FOR UPDATE;", (claim2.instance_id,))
            with pytest.raises(FencingContentionError, match="durable lock contention"):
                validate_supervisor_registration(connect, claim2, "d" * 64)
            blocker_conn.rollback()

        store.stop_singleton("inst-live-curr", epoch)


def test_quarantine_legacy_attempt_boundary_conditions() -> None:
    with _refresh_harness() as (store, cap_dir, connect, postgres, graph_db):
        config, sg, cg, eg, kg = _make_refresh_fixture(postgres, cap_dir, graph_db, graph_id="synthetic-leg")
        resolver = ConfiguredRefreshResolver(config, Path(postgres.psql_command))
        real_fence = lambda cl, **kw: resolver.install_graph_publication_fence(cl, **kw)
        req = replace(_req_norm("legacy-key", sg, cg, eg, kg, graph_id="synthetic-leg"), priority="automatic")
        store.coalesce_automatic(req, requester="watcher")
        epoch1 = store.acquire_singleton("inst-leg-prior", timedelta(seconds=300))
        claim = store.claim_next("inst-leg-prior", epoch1, timedelta(seconds=300))
        assert claim is not None
        with connect() as conn:
            assert conn.execute("SELECT running_job_id FROM coalescing_state WHERE graph_id = %s", (claim.graph_id,)).fetchone() == (claim.job_id,)
        _to_running(store, claim, epoch1)
        assert store.mark_reconciliation_required(claim, expected_state="running", category="worker_crash")
        assert store.mark_attempt_terminated(claim, process_cleanup_proved=True)
        store.stop_singleton("inst-leg-prior", epoch1)

        epoch2 = store.acquire_singleton("inst-leg-rec", timedelta(seconds=300))
        assert epoch2 > epoch1

        # Refusal when graph_lease_fencing_epoch is NOT zero
        store.set_durable_fence_callback(real_fence)
        assert store.quarantine_legacy_attempt(claim, reconciler_instance_id="inst-leg-rec", reconciler_epoch=epoch2) is False

        with connect() as conn:
            conn.execute("UPDATE job_attempts SET graph_lease_fencing_epoch = 0 WHERE job_id = %s", (claim.job_id,))
            conn.execute("UPDATE graph_leases SET graph_lease_fencing_epoch = 0, expires_at = now() - interval '1 second' WHERE job_id = %s", (claim.job_id,))
        legacy_claim = JobClaim(
            claim.job_id, claim.graph_id, claim.attempt, claim.instance_id, claim.fencing_epoch,
            priority_class=claim.priority_class, source_generation=claim.source_generation,
            config_generation=claim.config_generation, extractor_generation=claim.extractor_generation,
            canonicalizer_generation=claim.canonicalizer_generation, graph_lease_fencing_epoch=0,
        )

        store.set_durable_fence_callback(None)
        assert store.quarantine_legacy_attempt(legacy_claim, reconciler_instance_id="inst-leg-rec", reconciler_epoch=epoch2) is False
        store.set_durable_fence_callback(real_fence)
        assert store.quarantine_legacy_attempt(legacy_claim, reconciler_instance_id="inst-leg-rec", reconciler_epoch=epoch1) is False
        store.set_durable_fence_callback(lambda *args, **kw: False)
        assert store.quarantine_legacy_attempt(legacy_claim, reconciler_instance_id="inst-leg-rec", reconciler_epoch=epoch2) is False
        store.set_durable_fence_callback(real_fence)

        assert store.quarantine_legacy_attempt(
            legacy_claim, reconciler_instance_id="inst-leg-rec", reconciler_epoch=epoch2,
        ) is True

        with connect() as conn:
            assert conn.execute(
                "SELECT state, publication_state, error_category, finished_at IS NOT NULL FROM jobs WHERE job_id = %s",
                (claim.job_id,),
            ).fetchone() == ("quarantined", "commit_unknown", "legacy_zero_epoch", True)
            assert conn.execute("SELECT is_current, result_category FROM job_attempts WHERE job_id = %s", (claim.job_id,)).fetchone() == (False, "legacy_zero_epoch")
            assert conn.execute("SELECT count(*) FROM graph_leases WHERE job_id = %s", (claim.job_id,)).fetchone() == (0,)
            assert conn.execute("SELECT running_job_id FROM coalescing_state WHERE graph_id = %s", (claim.graph_id,)).fetchone() == (None,)

        with psycopg.connect(host=postgres.host, port=postgres.port, user=postgres.user, dbname=graph_db, password=postgres.password) as gconn:
            row = gconn.execute("SELECT graph_lease_fencing_epoch, coordinator_instance_id FROM graph_publication_authority").fetchone()
            assert row is not None and row[0] > 0 and row[1] == "inst-leg-rec"

        store.stop_singleton("inst-leg-rec", epoch2)


def test_registered_child_supervision_and_fencing_proof() -> None:
    with _refresh_harness() as (store, cap_dir, connect, postgres, graph_db):
        config, sg, cg, eg, kg = _make_refresh_fixture(postgres, cap_dir, graph_db, graph_id="synthetic-child")
        store.submit(_req_norm("child-supervision", sg, cg, eg, kg, graph_id="synthetic-child"))
        epoch = store.acquire_singleton("inst-child", timedelta(seconds=300))
        claim = store.claim_next("inst-child", epoch, timedelta(seconds=300))
        assert claim is not None
        _to_running(store, claim, epoch)

        route = effective_postgres_route(load_ops_config(config))
        capability = RefreshCapability(
            schema_version=1, job_id=claim.job_id, attempt=claim.attempt, graph_id=claim.graph_id,
            config_path=config, psql_path=Path(postgres.psql_command), postgres_user=postgres.user,
            postgres_host=route.host, postgres_port=route.port, postgres_route_kind=route.kind,
            postgres_password=postgres.password, executable_search_path=_search_path(),
            source_generation=sg, config_generation=cg, extractor_generation=eg, canonicalizer_generation=kg,
            coordinator_instance_id=claim.instance_id, singleton_fencing_epoch=epoch,
            graph_lease_fencing_epoch=claim.graph_lease_fencing_epoch,
        )

        checkpoint: dict[str, object] = {}
        interrupted = _run_real_refresh_attempt(
            postgres, cap_dir, claim, config, sg, cg, eg, kg,
            pause_env_var="_REPOMAP_SYSTEM_TEST_STAGED_PAUSE_PATH",
            pause_path=cap_dir / "paused-stage",
            launch_registrar=store.register_supervisor_launch,
            fencing_prover=store.in_process_fencing_proof,
            checkpoint=checkpoint,
        )

        assert interrupted["_termination_proved"] is True
        assert interrupted["_error_category"] == "worker_crash"
        assert interrupted["publication_state"] == "not_started"
        assert _publication_phase.publication_state(cap_dir, claim) == "not_started"

        with connect() as conn:
            assert conn.execute(
                "SELECT supervisor_registration_consumed FROM job_attempts WHERE job_id = %s AND attempt = %s",
                (claim.job_id, claim.attempt),
            ).fetchone() == (True,)

        with pytest.raises(PermissionError, match="no real reaped process registration"):
            store.in_process_fencing_proof(object(), capability)

        store.stop_singleton("inst-child", epoch)
