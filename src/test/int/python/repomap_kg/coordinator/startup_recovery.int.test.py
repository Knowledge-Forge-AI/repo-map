from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
import hashlib
import os
from pathlib import Path
import secrets
import shutil
import signal
import tempfile
import threading
import time
from typing import Any, Mapping
import psycopg
import pytest

from repomap_kg.artifacts.store import FileSystemArtifactStore
from repomap_kg.coordinator import _publication_phase, normalize_request
from repomap_kg.coordinator._control_types import JobClaim
from repomap_kg.coordinator._portable_capability import create_portable_capability
from repomap_kg.coordinator._portable_worker_launch import run_portable_worker
from repomap_kg.coordinator.core import SyntheticCoordinator
from repomap_kg.coordinator.protocol import run_refresh_worker
from repomap_kg.coordinator.refresh_adapter import RefreshCapability, create_refresh_capability
from repomap_kg.coordinator.startup_recovery import PublicationRouteChangedError, StartupRecoveryReport, recover_startup
from repomap_kg.coordinator.storage import ControlStore, SingletonActiveError
from repomap_kg.graph.multi_source_pipeline import scan_multi_source_generations
from repomap_kg.ops.config import load_ops_config
from repomap_kg.ops.generations import canonicalizer_generation, configured_graph, extractor_generation
from repomap_kg.runtime.postgres_route import effective_postgres_route
from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_test_support.portable_worker_scenarios import coordinator_test_limits, create_test_sealed_capability
from repomap_test_support.postgres_harness import require_postgres_binaries, temporary_postgres


@contextmanager
def _harness():
    require_postgres_binaries()
    with temporary_postgres() as pg, tempfile.TemporaryDirectory() as cap_raw:
        connect = lambda: psycopg.connect(host=pg.host, port=pg.port, user=pg.user, dbname=pg.database, password=pg.password)
        store = ControlStore(connect)
        store.initialize_schema()
        cap_dir = Path(cap_raw)
        cap_dir.chmod(0o700)
        yield store, cap_dir, connect


@contextmanager
def _refresh_harness():
    require_postgres_binaries()
    with temporary_postgres() as pg, tempfile.TemporaryDirectory() as cap_raw:
        graph_db = f"repomap_graph_{secrets.token_hex(4)}"
        with psycopg.connect(host=pg.host, port=pg.port, user=pg.user, dbname=pg.database, password=pg.password, autocommit=True) as admin_conn:
            admin_conn.execute(f"CREATE DATABASE {graph_db}")
        apply_migrations(default_rdbms_root(), [a if a != pg.database else graph_db for a in pg.psql_args], psql_command=pg.psql_command)
        connect = lambda: psycopg.connect(host=pg.host, port=pg.port, user=pg.user, dbname=pg.database, password=pg.password)
        store = ControlStore(connect)
        store.initialize_schema()
        cap_dir = Path(cap_raw)
        cap_dir.chmod(0o700)
        try:
            yield store, cap_dir, connect, pg, graph_db
        finally:
            try:
                with psycopg.connect(host=pg.host, port=pg.port, user=pg.user, dbname=pg.database, password=pg.password, autocommit=True) as admin_conn:
                    admin_conn.execute(f"DROP DATABASE IF EXISTS {graph_db} WITH (FORCE)")
            except Exception: pass


def _search_path() -> tuple[Path, ...]:
    psql = shutil.which("psql"); assert psql is not None
    return (Path(psql).parent,)


def _make_refresh_fixture(postgres: Any, root: Path, graph_db: str, graph_id: str = "synthetic-g1") -> tuple[Path, str, str, str, str]:
    repo = root / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "README.md").write_text("# Test Repo\n", encoding="utf-8")
    cfg = root / "ops.toml"
    cfg.write_text(f'schema_version = 1\n[service]\nmode = "local"\nmcp_transport = "stdio"\nlog_level = "info"\n[postgres]\nhost = "{postgres.socket_dir}"\nport = {postgres.port}\ndatabase = "{graph_db}"\nuser = "{postgres.user}"\npassword_env = "REPOMAP_PG_PASSWORD"\n[[graphs]]\nid = "{graph_id}"\nname = "Synthetic Refresh"\nroot_path = "{repo}"\nrepository_name = "{graph_id}"\nprivacy = "public-dev"\nenabled = true\nmcp_visible = false\nextractor_profile = "default"\nrefresh_policy = "manual"\n[server_memory]\nenabled = false\npath = "disabled"\nmode = "read_only"\n', encoding="utf-8")
    conf = configured_graph(load_ops_config(cfg), graph_id)
    scan = scan_multi_source_generations(conf)
    return (cfg, scan.source_generation, scan.config_generation, extractor_generation(conf), canonicalizer_generation())


def _kill_on_ready(ready_path: Path) -> None:
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline:
        if ready_path.exists():
            try:
                for line in ready_path.read_text(encoding="utf-8").splitlines():
                    if line.startswith("pid="):
                        os.kill(int(line.split("=")[1]), signal.SIGKILL)
                        return
            except (OSError, ValueError): pass
        time.sleep(0.02)


def _run_real_refresh_attempt(postgres: Any, cap_dir: Path, claim: JobClaim, config_path: Path, source_gen: str, config_gen: str, ext_gen: str, can_gen: str, *, pause_env_var: str | None = None, pause_path: Path | None = None) -> dict[str, object]:
    route = effective_postgres_route(load_ops_config(config_path)); assert (route.host, route.port, route.kind) == (postgres.host, postgres.port, "configured")
    cap_path = create_refresh_capability(cap_dir, RefreshCapability(
        schema_version=1, job_id=claim.job_id, attempt=claim.attempt, graph_id=claim.graph_id, config_path=config_path,
        psql_path=Path(postgres.psql_command), postgres_user=postgres.user, postgres_host=route.host, postgres_port=route.port, postgres_route_kind=route.kind, postgres_password=postgres.password,
        executable_search_path=_search_path(), source_generation=source_gen, config_generation=config_gen,
        extractor_generation=ext_gen, canonicalizer_generation=can_gen, coordinator_instance_id=claim.instance_id,
        singleton_fencing_epoch=claim.fencing_epoch, graph_lease_fencing_epoch=claim.graph_lease_fencing_epoch,
    ))
    killer = None
    if pause_env_var and pause_path:
        pause_path.touch()
        killer = threading.Thread(target=_kill_on_ready, args=(Path(f"{pause_path}.ready"),), daemon=True)
        killer.start()
        os.environ[pause_env_var] = str(pause_path)
    try:
        res = run_refresh_worker(cap_path, {"job_id": claim.job_id, "attempt": claim.attempt}, coordinator_test_limits(), job_context={"graph_id": claim.graph_id, "source_generation": source_gen, "config_generation": config_gen})
        return {**res.terminal, "_termination_proved": res.waited and res.process_group_cleaned}
    finally:
        if pause_env_var: os.environ.pop(pause_env_var, None)
        if pause_path: pause_path.unlink(missing_ok=True)
        if killer: killer.join(timeout=3.0)


def _req(graph_id: str, key: str):
    h = hashlib.sha256(graph_id.encode()).hexdigest()
    return normalize_request({"schema_version": 1, "job_kind": "refresh_graph", "graph_id": graph_id, "request_id": f"request-{key}", "idempotency_key": key, "priority": "manual", "operation_options": {"reason": "operator-request"}}, source_generation=f"sg1:{h}", config_generation=f"cg1:{h}")


def _req_norm(key: str, sg: str, cg: str, eg: str, kg: str, graph_id: str = "synthetic-g1"):
    return normalize_request({"schema_version": 1, "job_kind": "refresh_graph", "graph_id": graph_id, "request_id": f"req-{key}", "idempotency_key": f"k-{key}", "priority": "manual", "operation_options": {"reason": "test"}}, source_generation=sg, config_generation=cg, extractor_generation=eg, canonicalizer_generation=kg)


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
        assert recovered[0].graph_lease_fencing_epoch == 0 and (replace(recovered[0], graph_lease_fencing_epoch=claim.graph_lease_fencing_epoch),) == (claim,)
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
    claims = [JobClaim(f"job-{k}", f"g-{i}", 1, "inst-1", 1) for i, k in enumerate(("present", "absent", "conflicting", "route-changed", "unavailable"))]
    recorded: list[tuple[Any, Mapping[str, Any]]] = []

    class FakeStore:
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
    with _refresh_harness() as (store, cap_dir, _, postgres, graph_db):
        config_p, sg, cg, eg, kg = _make_refresh_fixture(postgres, cap_dir, graph_db)
        claims: list[JobClaim] = []
        def worker(claim: JobClaim, _cancel: object) -> dict[str, object]:
            claims.append(claim)
            return _run_real_refresh_attempt(postgres, cap_dir, claim, config_p, sg, cg, eg, kg, pause_env_var="_REPOMAP_SYSTEM_TEST_PAUSE_PATH", pause_path=cap_dir / f"pause_pre_{claim.attempt}")

        coord = SyntheticCoordinator(store, "inst-1", worker, publication_reader=lambda c: {"publication_state": _publication_phase.publication_state(cap_dir, c, close_unpublished=True)}, publication_retirer=lambda c: _publication_phase.retire_evidence(cap_dir, c))
        coord.startup(lambda: None)
        try:
            sub = store.submit(_req_norm("pre-pub", sg, cg, eg, kg))
            assert coord.run_once() == "queued"
            assert (store.status(sub.job_id).state, store.status(sub.job_id).publication_state, store.status(sub.job_id).error_category) == ("queued", "not_started", "worker_crash")
            assert not _publication_phase._path(cap_dir, claims[0], "decision").exists() and not _publication_phase._path(cap_dir, claims[0], "initial").exists()
        finally:
            coord.shutdown()


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
    with _harness() as (store, cap_dir, connect):
        sub = store.submit(_req("synthetic-g1", "not-started-recovery"))
        epoch = store.acquire_singleton("inst-s", timedelta(seconds=30))
        claim = store.claim_next("inst-s", epoch, timedelta(seconds=30))
        assert claim is not None
        for exp, nxt in (("claimed", "starting"), ("starting", "running")):
            assert store.compare_and_set_state(claim.job_id, expected_state=exp, new_state=nxt, attempt=claim.attempt, instance_id=claim.instance_id, fencing_epoch=claim.fencing_epoch)
        store.mark_reconciliation_required(claim, expected_state="running", category="worker_crash")
        store.mark_attempt_terminated(claim, process_cleanup_proved=True, reconciler_instance_id="inst-s", reconciler_epoch=epoch)
        store.stop_singleton("inst-s", epoch)
        _publication_phase.initialize(cap_dir, claim)
        init_p = _publication_phase._path(cap_dir, claim, "initial")
        assert init_p.is_file()

        coord = SyntheticCoordinator(store, "inst-rec-ns", lambda _c, _x: {"status": "failed", "_termination_proved": True}, publication_reader=lambda c: {"publication_state": _publication_phase.publication_state(cap_dir, c, close_unpublished=True)}, publication_retirer=lambda c: _publication_phase.retire_evidence(cap_dir, c))
        coord.startup(coord.recover_startup)
        try:
            assert coord.startup_recovery_report is not None and getattr(coord.startup_recovery_report, "resolved") == 1 and store.status(sub.job_id).state == "queued" and not init_p.exists()
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
            return _run_real_refresh_attempt(postgres, cap_dir, claim, config_p, sg, cg, eg, kg, pause_env_var="_REPOMAP_SYSTEM_TEST_PAUSE_PATH" if pause_p else None, pause_path=pause_p)

        def monitored_retirer(claim: object) -> None:
            assert isinstance(claim, JobClaim)
            retired.append((claim.attempt, store.status(claim.job_id).state))
            _publication_phase.retire_evidence(cap_dir, claim)

        coord = SyntheticCoordinator(store, "inst-1", worker, publication_reader=lambda c: {"publication_state": _publication_phase.publication_state(cap_dir, c, close_unpublished=True)}, publication_retirer=monitored_retirer)
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
