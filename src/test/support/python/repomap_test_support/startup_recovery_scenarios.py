from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Callable
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import tempfile
import threading
import time
from typing import Any
import psycopg

from repomap_kg.coordinator import normalize_request
from repomap_kg.coordinator._control_types import JobClaim
from repomap_kg.coordinator.protocol import run_refresh_worker
from repomap_kg.coordinator.refresh_adapter import RefreshCapability, create_refresh_capability
from repomap_kg.coordinator.storage import ControlStore
from repomap_kg.graph.multi_source_pipeline import scan_multi_source_generations
from repomap_kg.ops.config import load_ops_config
from repomap_kg.ops.generations import canonicalizer_generation, configured_graph, extractor_generation
from repomap_kg.runtime.postgres_route import effective_postgres_route
from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_test_support.portable_worker_scenarios import coordinator_test_limits
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
    # The fixture owns its credential independently of the caller environment.
    credential = root / "postgres-password"
    fd = os.open(credential, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(postgres.password)
    cfg.write_text(f'schema_version = 1\n[service]\nmode = "local"\nmcp_transport = "stdio"\nlog_level = "info"\n[postgres]\nhost = "{postgres.socket_dir}"\nport = {postgres.port}\ndatabase = "{graph_db}"\nuser = "{postgres.user}"\npassword_file = "postgres-password"\n[[graphs]]\nid = "{graph_id}"\nname = "Synthetic Refresh"\nroot_path = "{repo}"\nrepository_name = "{graph_id}"\nprivacy = "public-dev"\nenabled = true\nmcp_visible = false\nextractor_profile = "default"\nrefresh_policy = "manual"\n[server_memory]\nenabled = false\npath = "disabled"\nmode = "read_only"\n', encoding="utf-8")
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


def _run_real_refresh_attempt(postgres: Any, cap_dir: Path, claim: JobClaim, config_path: Path, source_gen: str, config_gen: str, ext_gen: str, can_gen: str, *, pause_env_var: str | None = None, pause_path: Path | None = None, fencing_prover: Any = None, launch_registrar: Any = None, checkpoint: dict[str, object] | None = None) -> dict[str, object]:
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
        res = run_refresh_worker(cap_path, {"job_id": claim.job_id, "attempt": claim.attempt}, coordinator_test_limits(), job_context={"graph_id": claim.graph_id, "source_generation": source_gen, "config_generation": config_gen}, fencing_prover=fencing_prover, launch_registrar=launch_registrar or getattr(getattr(fencing_prover, "__self__", None), "register_supervisor_launch", None))
        if checkpoint is not None and pause_path is not None:
            for line in Path(f"{pause_path}.ready").read_text().splitlines():
                if line.startswith("handoff="):
                    checkpoint.update(json.loads(line.split("=", 1)[1]))
            assert checkpoint, "real worker did not reach its validated publication checkpoint"
        category = "protocol" if res.protocol_error else (
            "worker_timeout" if res.process_timed_out or res.heartbeat_timed_out else (
                "worker_crash" if res.synthesized_terminal else res.terminal.get("error_category", "publication_unknown")
            )
        )
        return {**res.terminal, "_termination_proved": res.waited and res.process_group_cleaned, "_error_category": category}
    finally:
        if pause_env_var: os.environ.pop(pause_env_var, None)
        if pause_path: pause_path.unlink(missing_ok=True)
        if killer: killer.join(timeout=3.0)


def _req(graph_id: str, key: str):
    h = hashlib.sha256(graph_id.encode()).hexdigest()
    return normalize_request({"schema_version": 1, "job_kind": "refresh_graph", "graph_id": graph_id, "request_id": f"request-{key}", "idempotency_key": key, "priority": "manual", "operation_options": {"reason": "operator-request"}}, source_generation=f"sg1:{h}", config_generation=f"cg1:{h}")


def _req_norm(key: str, sg: str, cg: str, eg: str, kg: str, graph_id: str = "synthetic-g1"):
    return normalize_request({"schema_version": 1, "job_kind": "refresh_graph", "graph_id": graph_id, "request_id": f"req-{key}", "idempotency_key": f"k-{key}", "priority": "manual", "operation_options": {"reason": "test"}}, source_generation=sg, config_generation=cg, extractor_generation=eg, canonicalizer_generation=kg)


def _assert_retry_waiting_and_advance(
    store: ControlStore, connect: Callable[[], psycopg.Connection], claim: JobClaim,
    instance_id: str, epoch: int,
) -> None:
    """Prove the recorded retry delay and advance the existing SQL eligibility seam."""
    assert store.status(claim.job_id).state == "queued"
    with connect() as connection:
        assert connection.execute(
            "SELECT next_eligible_at - updated_at FROM jobs WHERE job_id = %s",
            (claim.job_id,),
        ).fetchone() == (timedelta(seconds=1),)
        assert connection.execute(
            "SELECT is_current, finished_at IS NOT NULL FROM job_attempts "
            "WHERE job_id = %s AND attempt = %s", (claim.job_id, claim.attempt),
        ).fetchone() == (False, True)
        assert connection.execute(
            "SELECT count(*) FROM graph_leases WHERE job_id = %s", (claim.job_id,),
        ).fetchone() == (0,)
        # Freeze eligibility ahead of the wall clock so the refusal is deterministic,
        # even when other assertions took longer than the recorded one-second delay.
        connection.execute(
            "UPDATE jobs SET next_eligible_at = now() + interval '1 day' WHERE job_id = %s",
            (claim.job_id,),
        )
    assert store.claim_next(instance_id, epoch, timedelta(seconds=30)) is None
    with connect() as connection:
        connection.execute(
            "UPDATE jobs SET next_eligible_at = now() - interval '1 second' WHERE job_id = %s",
            (claim.job_id,),
        )
