from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import cast
import psycopg
import pytest

from repomap_kg.artifacts.store import FileSystemArtifactStore
from repomap_kg.coordinator import _publication_phase
from repomap_kg.coordinator._control_types import JobClaim
from repomap_kg.coordinator._portable_capability import create_portable_capability
from repomap_kg.coordinator._portable_worker_launch import run_portable_worker
from repomap_kg.coordinator.core import SyntheticCoordinator
from repomap_kg.coordinator.startup_recovery import StartupRecoveryReport
from repomap_kg.coordinator.storage import SingletonActiveError
from repomap_test_support.portable_worker_scenarios import coordinator_test_limits, create_test_sealed_capability


from repomap_test_support.startup_recovery_scenarios import (
    _harness, _refresh_harness, _make_refresh_fixture, _run_real_refresh_attempt, _req, _req_norm,
)


def test_startup_recovery_lifecycle_with_durable_rejected_attempt_and_crash_recovery() -> None:
    with _harness() as (store, _, connect):
        captured: list[JobClaim] = []
        def fail_w(c: JobClaim, _: object) -> dict[str, object]:
            captured.append(c); return {"status": "failed", "publication_state": "commit_unknown", "error_category": "publication_unknown", "_termination_proved": True}

        p = SyntheticCoordinator(store, "coord-p", fail_w, singleton_ttl=timedelta(seconds=30))
        p.startup(lambda: None)
        try:
            sub = store.submit(_req("synthetic-recovery", "recovery-key"))
            with pytest.raises(SingletonActiveError, match="singleton is active"):
                store.acquire_singleton("coord-contender", timedelta(seconds=30))
            assert p.run_once() == "reconciliation_required" and store.status(sub.job_id).state == "reconciliation_required"
        finally:
            p.shutdown()
        claim = captured[0]
        store.record_publication_marker(claim, run_identity="run-recovered", source_generation=claim.source_generation, config_generation=claim.config_generation, extractor_generation=claim.extractor_generation, canonicalizer_generation=claim.canonicalizer_generation, outcome="committed")
        r = SyntheticCoordinator(store, "coord-r", lambda _c, _x: {"status": "failed", "_termination_proved": True}, singleton_ttl=timedelta(seconds=30))
        r.startup(r.recover_startup)
        try:
            assert isinstance(r.startup_recovery_report, StartupRecoveryReport) and (r.startup_recovery_report.scanned, r.startup_recovery_report.resolved, r.startup_recovery_report.pending) == (1, 1, 0)
            assert (store.status(sub.job_id).state, store.status(sub.job_id).publication_state, store.status(sub.job_id).error_category) == ("succeeded", "committed", None)
            with connect() as conn:
                assert conn.execute("SELECT count(*) FROM graph_leases WHERE job_id = %s", (sub.job_id,)).fetchone() == (0,) and conn.execute("SELECT is_current, finished_at IS NOT NULL, result_category FROM job_attempts WHERE job_id = %s", (sub.job_id,)).fetchone() == (False, True, None)
        finally:
            r.shutdown()


def test_connected_portable_mismatch_yields_contract_validation() -> None:
    with _harness() as (store, cap_dir, connect):
        art_store = FileSystemArtifactStore(cap_dir / "store")
        (cap_dir / "store").mkdir(0o700, parents=True, exist_ok=True); (cap_dir / "work").mkdir(0o700, parents=True, exist_ok=True)
        prev_sub = store.submit(_req("synthetic-g1", "prev-req"))
        epoch = store.acquire_singleton("inst-init", timedelta(seconds=30))
        claim_prev = store.claim_next("inst-init", epoch, timedelta(seconds=30)); assert claim_prev is not None
        store.record_publication_marker(claim_prev, run_identity="run-prev", source_generation=claim_prev.source_generation, config_generation=claim_prev.config_generation, extractor_generation=claim_prev.extractor_generation, canonicalizer_generation=claim_prev.canonicalizer_generation, outcome="committed")
        with connect() as conn: conn.execute("UPDATE jobs SET state = 'succeeded', publication_state = 'committed', finished_at = now() WHERE job_id = %s", (claim_prev.job_id,))
        store.release_graph_lease(claim_prev.graph_id, claim_prev.job_id, claim_prev.attempt, claim_prev.instance_id, claim_prev.fencing_epoch, reconciler_instance_id="inst-init", reconciler_epoch=epoch)
        store.stop_singleton("inst-init", epoch)

        def mismatch_worker(claim: JobClaim, _cancel: object) -> dict[str, object]:
            _publication_phase.initialize(cap_dir, claim)
            cap = replace(create_test_sealed_capability(cap_dir / "src", art_store, cap_dir / "work", job_id=claim.job_id, attempt=claim.attempt), max_bundle_bytes=100)
            res = run_portable_worker(create_portable_capability(cap_dir, cap), {"job_id": claim.job_id, "attempt": claim.attempt}, coordinator_test_limits())
            return {**res.terminal, "_termination_proved": res.waited and res.process_group_cleaned}

        coord = SyntheticCoordinator(store, "inst-1", mismatch_worker, publication_reader=lambda c: {"publication_state": _publication_phase.publication_state(cap_dir, c)}, publication_retirer=lambda c: _publication_phase.retire_evidence(cap_dir, c))
        coord.startup(lambda: None)
        try:
            sub = store.submit(_req("synthetic-g1", "mismatch-req"))
            assert coord.run_once() == "failed" and (store.status(sub.job_id).state, store.status(sub.job_id).error_category, store.status(sub.job_id).attempt) == ("failed", "contract_validation", 1)
            with connect() as conn:
                assert conn.execute("SELECT outcome FROM synthetic_publication_markers WHERE job_id = %s", (prev_sub.job_id,)).fetchone() == ("committed",)
            assert not _publication_phase._path(cap_dir, JobClaim(sub.job_id, "synthetic-g1", 1, "inst-1", 1), "initial").exists()
        finally:
            coord.shutdown()


def test_connected_interruption_before_publication_start_proof_yields_not_started() -> None:
    with _refresh_harness() as (store, cap_dir, connect, postgres, graph_db):
        config_p, sg, cg, eg, kg = _make_refresh_fixture(postgres, cap_dir, graph_db)
        claims: list[JobClaim] = []
        def worker(claim: JobClaim, _cancel: object) -> dict[str, object]:
            claims.append(claim)
            return _run_real_refresh_attempt(
                postgres,
                cap_dir,
                claim,
                config_p,
                sg,
                cg,
                eg,
                kg,
                pause_env_var="_REPOMAP_SYSTEM_TEST_PAUSE_PATH",
                pause_path=cap_dir / f"pause_pre_{claim.attempt}",
            )

        coord = SyntheticCoordinator(
            store,
            "inst-1",
            worker,
            publication_reader=lambda c: {"publication_state": _publication_phase.publication_state(cap_dir, c)},
            publication_retirer=lambda c: _publication_phase.retire_evidence(cap_dir, c),
            publication_closer=lambda c, proof: _publication_phase.close_unpublished(cap_dir, c, proof=cast(_publication_phase.WorkerFencingProof, proof)),
        )
        coord.startup(lambda: None)
        try:
            sub = store.submit(_req_norm("pre-pub", sg, cg, eg, kg))
            # 1. Hard-crash interruption before publication start enters reconciliation_required
            assert coord.run_once() == "reconciliation_required"
            # Attempt is marked finished, but publication_state remains commit_unknown, state reconciliation_required
            job_status = store.status(sub.job_id)
            assert (job_status.state, job_status.publication_state, job_status.error_category) == (
                "reconciliation_required",
                "commit_unknown",
                "worker_crash",
            )
            init_p = _publication_phase._path(cap_dir, claims[0], "initial")
            dec_p = _publication_phase._path(cap_dir, claims[0], "decision")
            assert init_p.is_file() and not dec_p.exists()
        finally:
            coord.shutdown()

        # 2. Closure refused until real durable fence is established
        coord_unfenced = SyntheticCoordinator(
            store,
            "inst-2-unfenced",
            worker,
            publication_reader=lambda c: {"publication_state": _publication_phase.publication_state(cap_dir, c)},
            publication_retirer=lambda c: _publication_phase.retire_evidence(cap_dir, c),
            publication_closer=lambda c, proof: _publication_phase.close_unpublished(cap_dir, c, proof=cast(_publication_phase.WorkerFencingProof, proof)),
        )
        coord_unfenced.startup(coord_unfenced.recover_startup)
        try:
            assert coord_unfenced.startup_recovery_report is not None
            assert getattr(coord_unfenced.startup_recovery_report, "resolved") == 0
            assert getattr(coord_unfenced.startup_recovery_report, "pending") == 1
            assert store.status(sub.job_id).state == "reconciliation_required"
            assert store.status(sub.job_id).publication_state == "commit_unknown"
        finally:
            coord_unfenced.shutdown()

        with connect() as connection:
            connection.execute("UPDATE graph_leases SET expires_at = now() - interval '1 second' WHERE job_id = %s", (sub.job_id,))

        # 3. Real configured resolver wires durable fence installation before file gate decision and requeues
        from repomap_kg.coordinator.configured_refresh import ConfiguredRefreshResolver

        resolver = ConfiguredRefreshResolver(config_p, Path(postgres.psql_command))
        store.set_durable_fence_callback(
            lambda claim, **kwargs: resolver.install_graph_publication_fence(claim, **kwargs)
        )

        reader_spy_calls: list[dict[str, object]] = []
        closer_spy_calls: list[tuple[JobClaim, str, _publication_phase.WorkerFencingProof]] = []

        def reader_spy(c: object) -> dict[str, object]:
            st = _publication_phase.publication_state(cap_dir, c)
            reader_spy_calls.append({"claim": c, "state": st})
            return {"publication_state": st}

        def closer_spy(c: object, proof: object) -> bool:
            capability = cast(_publication_phase.WorkerFencingProof, proof)
            closer_spy_calls.append((cast(JobClaim, c), capability.proof_kind, capability))
            return _publication_phase.close_unpublished(cap_dir, c, proof=capability)

        coord2 = SyntheticCoordinator(
            store,
            "inst-2",
            worker,
            publication_reader=reader_spy,
            publication_retirer=lambda c: _publication_phase.retire_evidence(cap_dir, c),
            publication_closer=closer_spy,
        )
        coord2.startup(coord2.recover_startup)
        try:
            assert coord2.startup_recovery_report is not None
            assert getattr(coord2.startup_recovery_report, "resolved") == 1
            assert getattr(coord2.startup_recovery_report, "pending") == 0
            # Reader saw commit_unknown on startup entry under reconciliation_required
            assert len(reader_spy_calls) >= 1
            assert reader_spy_calls[0]["state"] == "commit_unknown"
            # Closer called with authoritative store_fenced proof
            assert len(closer_spy_calls) == 1
            assert closer_spy_calls[0][1] == "store_fenced"
            with pytest.raises(PermissionError, match="consumed or invalidated"):
                _ = closer_spy_calls[0][2].proof_kind
            # Final state transitioned to queued / not_started
            final_status = store.status(sub.job_id)
            assert (final_status.state, final_status.publication_state, final_status.error_category) == (
                "queued",
                "not_started",
                "transient",
            )
            # Durable publication fence is established in graph DB
            with psycopg.connect(
                host=postgres.socket_dir,
                port=postgres.port,
                user=postgres.user,
                dbname=graph_db,
                password=postgres.password,
            ) as graph_conn:
                with graph_conn.cursor() as cur:
                    cur.execute(
                        "SELECT coordinator_instance_id, singleton_fencing_epoch FROM graph_publication_authority"
                    )
                    auth_row = cur.fetchone()
                    assert auth_row is not None
                    assert auth_row[0] == "inst-2"
            # Both files retired
            assert not init_p.exists() and not dec_p.exists()
        finally:
            coord2.shutdown()


def test_connected_interruption_after_publication_start_proof_reconciles_commit_unknown() -> None:
    with _refresh_harness() as (store, cap_dir, _, postgres, graph_db):
        config_p, sg, cg, eg, kg = _make_refresh_fixture(postgres, cap_dir, graph_db)
        claims: list[JobClaim] = []
        def worker(claim: JobClaim, _cancel: object) -> dict[str, object]:
            claims.append(claim)
            return _run_real_refresh_attempt(postgres, cap_dir, claim, config_p, sg, cg, eg, kg, pause_env_var="_REPOMAP_SYSTEM_TEST_POST_PUBLICATION_PAUSE_PATH", pause_path=cap_dir / f"pause_post_{claim.attempt}")

        coord = SyntheticCoordinator(store, "inst-1", worker, publication_reader=lambda c: {"publication_state": _publication_phase.publication_state(cap_dir, c)}, publication_retirer=lambda c: _publication_phase.retire_evidence(cap_dir, c))
        coord.startup(lambda: None)
        try:
            sub = store.submit(_req_norm("post-pub", sg, cg, eg, kg))
            assert coord.run_once() == "reconciliation_required"
            assert (store.status(sub.job_id).state, store.status(sub.job_id).publication_state) == ("reconciliation_required", "commit_unknown")
            init_p, dec_p = _publication_phase._path(cap_dir, claims[0], "initial"), _publication_phase._path(cap_dir, claims[0], "decision")
            assert init_p.is_file() and dec_p.is_file()
        finally:
            coord.shutdown()

        coord2 = SyntheticCoordinator(store, "inst-2", lambda _c, _x: {"status": "failed", "_termination_proved": True}, publication_reader=lambda c: {"publication_state": _publication_phase.publication_state(cap_dir, c)}, publication_retirer=lambda c: _publication_phase.retire_evidence(cap_dir, c))
        coord2.startup(coord2.recover_startup)
        try:
            assert coord2.startup_recovery_report is not None and getattr(coord2.startup_recovery_report, "resolved") == 0 and getattr(coord2.startup_recovery_report, "pending") == 1 and store.status(sub.job_id).state == "reconciliation_required" and init_p.is_file() and dec_p.is_file()
        finally:
            coord2.shutdown()


def test_connected_startup_recovery_consumes_retained_evidence() -> None:
    with _refresh_harness() as (store, cap_dir, _, postgres, graph_db):
        config_p, sg, cg, eg, kg = _make_refresh_fixture(postgres, cap_dir, graph_db)
        claims: list[JobClaim] = []
        def worker(claim: JobClaim, _cancel: object) -> dict[str, object]:
            claims.append(claim)
            return _run_real_refresh_attempt(postgres, cap_dir, claim, config_p, sg, cg, eg, kg, pause_env_var="_REPOMAP_SYSTEM_TEST_POST_PUBLICATION_PAUSE_PATH", pause_path=cap_dir / f"pause_post_{claim.attempt}")

        c1 = SyntheticCoordinator(store, "inst-1", worker, publication_reader=lambda c: {"publication_state": _publication_phase.publication_state(cap_dir, c)}, publication_retirer=lambda c: _publication_phase.retire_evidence(cap_dir, c))
        c1.startup(lambda: None)
        try:
            sub = store.submit(_req_norm("rec-pub", sg, cg, eg, kg))
            assert c1.run_once() == "reconciliation_required"
        finally:
            c1.shutdown()

        claim = claims[0]
        init_p, dec_p = _publication_phase._path(cap_dir, claim, "initial"), _publication_phase._path(cap_dir, claim, "decision")
        assert init_p.is_file() and dec_p.is_file()
        store.record_publication_marker(claim, run_identity="run-rec-1", source_generation=claim.source_generation, config_generation=claim.config_generation, extractor_generation=claim.extractor_generation, canonicalizer_generation=claim.canonicalizer_generation, outcome="committed")
        c2 = SyntheticCoordinator(
            store, "inst-2", lambda _c, _x: {"status": "failed", "_termination_proved": True},
            publication_reader=lambda c: {"latest_run_identity": "run-rec-1", "source_generation": getattr(c, "source_generation", ""), "config_generation": getattr(c, "config_generation", ""), "extractor_generation": getattr(c, "extractor_generation", ""), "canonicalizer_generation": getattr(c, "canonicalizer_generation", "")},
            publication_retirer=lambda c: _publication_phase.retire_evidence(cap_dir, c),
        )
        c2.startup(c2.recover_startup)
        try:
            assert isinstance(c2.startup_recovery_report, StartupRecoveryReport) and c2.startup_recovery_report.resolved == 1
            assert (store.status(sub.job_id).state, store.status(sub.job_id).publication_state) == ("succeeded", "committed") and not init_p.exists() and not dec_p.exists()
        finally:
            c2.shutdown()


def test_connected_startup_recovery_resolves_retained_not_started_proof() -> None:
    with _refresh_harness() as (store, cap_dir, connect, postgres, graph_db):
        config, sg, cg, eg, kg = _make_refresh_fixture(postgres, cap_dir, graph_db)
        sub = store.submit(_req_norm("not-started-recovery", sg, cg, eg, kg))
        epoch = store.acquire_singleton("inst-s", timedelta(seconds=30))
        claim = store.claim_next("inst-s", epoch, timedelta(seconds=30))
        assert claim is not None
        for before, after in (("claimed", "starting"), ("starting", "running")):
            assert store.compare_and_set_state(claim.job_id, expected_state=before, new_state=after,
                attempt=claim.attempt, instance_id=claim.instance_id, fencing_epoch=claim.fencing_epoch)
        result = _run_real_refresh_attempt(
            postgres, cap_dir, claim, config, sg, cg, eg, kg,
            pause_env_var="_REPOMAP_SYSTEM_TEST_PAUSE_PATH", pause_path=cap_dir / "pause-reaped",
            fencing_prover=store.in_process_fencing_proof,
        )
        assert result["_termination_proved"] is True and result["publication_state"] == "not_started"
        assert _publication_phase.publication_state(cap_dir, claim) == "not_started"
        with connect() as connection:
            registered = connection.execute(
                "SELECT supervisor_registration_digest IS NOT NULL, supervisor_registration_consumed "
                "FROM job_attempts WHERE job_id = %s AND attempt = %s", (claim.job_id, claim.attempt),
            ).fetchone()
            assert registered == (True, True)
        assert store.mark_reconciliation_required(claim, expected_state="running", category="worker_crash", publication_state="not_started")
        assert store.mark_attempt_terminated(claim, process_cleanup_proved=True)
        assert store.stop_singleton("inst-s", epoch)
        init_p = _publication_phase._path(cap_dir, claim, "initial")
        assert init_p.is_file()
        observed = []

        def reader(c):
            state = _publication_phase.publication_state(cap_dir, c)
            observed.append(state)
            return {"publication_state": state}

        coord = SyntheticCoordinator(store, "inst-rec-ns", lambda *_: {}, publication_reader=reader,
            publication_retirer=lambda c: _publication_phase.retire_evidence(cap_dir, c))
        coord.startup(coord.recover_startup)
        try:
            assert cast(StartupRecoveryReport, coord.startup_recovery_report).resolved == 1
            assert observed == ["not_started"]
            assert store.status(sub.job_id).state == "queued" and not init_p.exists()
        finally:
            coord.shutdown()


def test_connected_retry_path_retires_prior_attempt_evidence_after_durable_queue_transition() -> None:
    with _refresh_harness() as (store, cap_dir, connect, postgres, graph_db):
        config_p, sg, cg, eg, kg = _make_refresh_fixture(postgres, cap_dir, graph_db)
        claims: list[JobClaim] = []
        retired: list[tuple[int, str]] = []

        def worker(claim: JobClaim, _cancel: object) -> dict[str, object]:
            claims.append(claim)
            pause_p = cap_dir / "pause_pre_retry" if claim.attempt == 1 else None
            return _run_real_refresh_attempt(postgres, cap_dir, claim, config_p, sg, cg, eg, kg, pause_env_var="_REPOMAP_SYSTEM_TEST_PAUSE_PATH" if pause_p else None, pause_path=pause_p, fencing_prover=store.in_process_fencing_proof)

        def monitored_retirer(claim: object) -> None:
            assert isinstance(claim, JobClaim)
            retired.append((claim.attempt, store.status(claim.job_id).state))
            _publication_phase.retire_evidence(cap_dir, claim)

        coord = SyntheticCoordinator(
            store,
            "inst-1",
            worker,
            publication_reader=lambda c: {"publication_state": _publication_phase.publication_state(cap_dir, c)},
            publication_retirer=monitored_retirer,
            publication_closer=lambda c, proof: _publication_phase.close_unpublished(cap_dir, c, proof=cast(_publication_phase.WorkerFencingProof, proof)),
        )
        coord.startup(lambda: None)
        try:
            sub = store.submit(_req_norm("retry", sg, cg, eg, kg))
            assert coord.run_once() == "queued" and store.status(sub.job_id).state == "queued" and retired == [(1, "queued")] and not _publication_phase._path(cap_dir, claims[0], "initial").exists()
            with connect() as conn: conn.execute("UPDATE jobs SET next_eligible_at = now() - interval '1s' WHERE job_id = %s", (sub.job_id,))
            assert coord.run_once() == "succeeded" and len(claims) == 2 and claims[0] != claims[1] and (claims[0].attempt, claims[1].attempt) == (1, 2)
            assert (store.status(sub.job_id).state, store.status(sub.job_id).publication_state) == ("succeeded", "committed") and retired == [(1, "queued"), (2, "succeeded")]
        finally:
            coord.shutdown()


def test_connected_terminal_cleanup_removes_safe_evidence_and_refuses_unsafe() -> None:
    with _harness() as (store, cap_dir, connect):
        with connect() as conn:
            for jid, offset in (("job-unsafe", 200), ("job-safe", 100)):
                conn.execute("INSERT INTO jobs (job_id, schema_version, job_kind, graph_id, request_id, requester, idempotency_digest, request_fingerprint, priority_class, priority_value, source_generation, config_generation, extractor_generation, canonicalizer_generation, state, publication_state, finished_at) VALUES (%s, 1, 'refresh_graph', 'synthetic-g1', %s, 'test', encode(sha256(%s::bytea), 'hex'), encode(sha256(%s::bytea), 'hex'), 'manual', 10, 'sg1:v1', 'cg1:v1', 'eg1:v1', 'kg1:v1', 'succeeded', 'committed', now() - make_interval(secs => %s))", (jid, f"req-{jid}", jid.encode(), jid.encode(), offset))
                conn.execute("INSERT INTO job_attempts (job_id, attempt, coordinator_instance_id, fencing_epoch, source_generation, config_generation, extractor_generation, canonicalizer_generation, publication_state, finished_at) VALUES (%s, 1, 'inst-clean', 1, 'sg1:v1', 'cg1:v1', 'eg1:v1', 'kg1:v1', 'committed', now() - make_interval(secs => %s))", (jid, offset))
        safe, unsafe = (JobClaim(jid, "synthetic-g1", 1, "inst-clean", 1, source_generation="sg1:v1", config_generation="cg1:v1", extractor_generation="eg1:v1", canonicalizer_generation="kg1:v1") for jid in ("job-safe", "job-unsafe"))
        for cl in (safe, unsafe):
            _publication_phase.initialize(cap_dir, cl)
            _publication_phase.before_publication(cap_dir, cl)
        safe_init = _publication_phase._path(cap_dir, safe, "initial")
        unsafe_init = _publication_phase._path(cap_dir, unsafe, "initial")
        unsafe_init.chmod(0o777)

        report = store.cleanup_terminal(timedelta(seconds=50), limit=1, dry_run=False, publication_retirer=lambda c: _publication_phase.retire_evidence(cap_dir, c))
        assert report.deleted_job_ids == ("job-safe",) and report.residual_count == 1 and report.residuals == ("job-unsafe:1:validation_error",) and not safe_init.exists() and unsafe_init.exists()
        with connect() as conn:
            assert conn.execute("SELECT count(*) FROM jobs WHERE job_id = 'job-safe'").fetchone() == (0,) and conn.execute("SELECT count(*) FROM jobs WHERE job_id = 'job-unsafe'").fetchone() == (1,)
