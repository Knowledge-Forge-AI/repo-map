"""PREPARE1/PREPARE2 Linux-harness exercise of the host MCP native qualification runner.

The runner's own ``execute_run`` builds its fresh fixture (two published graphs
plus a hidden one) in harness PostgreSQL databases, computes independent
oracles, launches the ``repomap-kg`` console through its direct-``Popen``
boundary for main, restart and outage sessions, cleans up, and writes the
redacted evidence ZIP and receipt. This proves fixture and stdio mechanics with
real PostgreSQL and real MCP serialization only: the console is the
runner-provisioned wrapper (a form the native mode refuses), the backend is the
harness cluster rather than an owned container, and the outage is
``ALLOW_CONNECTIONS false`` rather than a stopped container. It is NOT native
macOS acceptance.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
from typing import Any
import uuid
import zipfile

import pytest

from repomap_kg.graph.multi_source_pipeline import capture_multi_source_candidate
from repomap_kg.ops.config import build_graph_storage_status_sql
from repomap_kg.ops.direct_publication import publish_observation_generation
from repomap_kg.ops.refresh_sql import build_graph_summary_sql, build_refresh_status_sql
from repomap_kg.runtime.database_roles import READ_STATUS_ROLE
from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_test_support.postgres_harness import require_postgres_binaries, temporary_postgres
from smoke.host_mcp_native_checks import STATUS_COUNTS
from smoke.host_mcp_native_evidence import EvidenceWriter
from smoke.host_mcp_native_fixture import configured_publication, stage_native_config, stored_repository_facts
from smoke.host_mcp_native_launch import ALLOWED_CHILD_KEYS, console_entrypoint
from smoke.host_mcp_native_run import RunContext, execute_run
from smoke.host_mcp_native_scenario import run_scenario

PHASE = "REPOMAP-PRODUCT2-HOST-MCP-NATIVE1-PREPARE1"
EXPECTED_REFUSALS = 9


class HarnessDatabaseBackend:
    """Test-only seam: databases in the runner-owned harness cluster, never an owned container."""

    kind = "linux-harness-databases"

    def __init__(self, postgres: Any) -> None:
        self.postgres, self.names = postgres, list[str]()

    def describe(self) -> dict[str, Any]:
        return {"kind": self.kind, "cluster": "runner-owned harness PostgreSQL (not owned by this run)",
                "port": self.postgres.port}

    def manual_cleanup(self) -> str:
        return "harness-owned cluster; the runner drops only this run's databases"

    def start(self) -> Any:
        return self.postgres

    def create_database(self, name: str) -> Any:
        self.names.append(name)
        return self.postgres.create_database(name)

    def route_evidence(self) -> dict[str, Any]:
        return {"kind": self.kind, "port": self.postgres.port}

    def stop_for_outage(self) -> dict[str, Any]:
        for name in self.names:
            self.postgres.psql_scalar(f'ALTER DATABASE "{name}" ALLOW_CONNECTIONS false;')
        listed = ", ".join(f"'{name}'" for name in self.names)
        self.postgres.psql_scalar(f"SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity "
                                  f"WHERE datname IN ({listed}) AND pid <> pg_backend_pid();")
        return {"seam": "ALLOW_CONNECTIONS false", "databases": list(self.names)}

    def outage_active(self) -> bool:
        listed = ", ".join(f"'{name}'" for name in self.names)
        return self.postgres.psql_scalar(
            f"SELECT bool_and(NOT datallowconn) FROM pg_database WHERE datname IN ({listed});") == "t"

    def cleanup(self) -> list[dict[str, Any]]:
        steps = []
        for name in self.names:
            self.postgres.psql_scalar(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')
            steps.append({"step": f"drop-{name}", "ok": True})
        return steps


def _console() -> Path:
    beside = Path(sys.executable).with_name("repomap-kg")
    provisioned = shutil.which("repomap-kg")
    return beside if beside.is_file() else Path(provisioned or beside)


def test_runner_exercises_fixture_and_stdio_mechanics_in_the_linux_harness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    require_postgres_binaries()
    for name in ("REPOMAP_PG_PASSWORD", "REPOMAP_READ_STATUS_PASSWORD", "REPOMAP_STORAGE_PG_CONNECTOR"):
        monkeypatch.delenv(name, raising=False)
    console = console_entrypoint(_console())
    run_id = f"linux-{uuid.uuid4().hex[:8]}"
    outbox = tmp_path / "out box"
    work = (tmp_path / "work").resolve()
    work.mkdir(mode=0o700)
    with temporary_postgres() as postgres:
        monkeypatch.delenv("PGPASSWORD", raising=False)  # the runner's pgpass path is what reaches psycopg
        backend = HarnessDatabaseBackend(postgres)
        context = RunContext(run_id=run_id, work=work, parent_bin=Path(sys.executable).parent,
                             evidence=EvidenceWriter(outbox / PHASE / run_id, run_id=run_id, phase=PHASE))
        code = execute_run(context, backend, console, qualification_class="linux-harness-exercise",
                           scenario=run_scenario, test_extra_path=(str(Path(sys.executable).parent),))
        remaining = postgres.psql_scalar("SELECT count(*) FROM pg_database WHERE datname IN ("
                                         + ", ".join(f"'{name}'" for name in backend.names) + ");")
        read_backends = postgres.psql_scalar(
            f"SELECT count(*) FROM pg_stat_activity WHERE usename = '{READ_STATUS_ROLE}';")
        admin_password = postgres.password
    run_dir = outbox / PHASE / run_id
    receipt = json.loads((run_dir / "receipt.json").read_text(encoding="utf-8"))
    zip_bytes = (run_dir / "evidence.zip").read_bytes()
    with zipfile.ZipFile(run_dir / "evidence.zip") as archive:
        members = {name.split("/", 1)[1]: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(members["MANIFEST.json"])
    summary, checks = manifest["summary"], manifest["summary"].get("checks", {})
    failed = {name: ok for name, ok in checks.items() if not ok}
    main = json.loads(members["session-main.json"])
    statuses = main["classification"]["messages"]
    diagnostic = {"failed": failed, "session": main["classification"]["session"],
                  "messages": {mid: status for mid, status in statuses.items() if not status.endswith("_ok")},
                  "stderr": main["stderr_tail"][-1500:], "error": summary.get("error")}
    if diagnostic["messages"]:
        mid = next(iter(diagnostic["messages"]))
        diagnostic["response"] = json.dumps(main["responses"].get(mid))[:3000]
        diagnostic["expected"] = json.dumps(json.loads(members["oracle.json"])["messages"][mid])[:3000]
    assert code == 0 and receipt["outcome"] == "completed_pending_manager_review", diagnostic
    assert receipt["qualification_class"] == "linux-harness-exercise" and "not Product step 3" in receipt["attests"]
    assert receipt["zip"]["sha256"] == hashlib.sha256(zip_bytes).hexdigest()
    assert console.native_refusal(Path("/checkout")) is not None, "the harness console must not pass as native"

    for required in ("route_agrees", "only_setup_fetch", "sources_absent_before_mcp", "session_main",
                     "session_restart", "session_outage", "chain_catalog_is_27_tools", "chain_catalog_sha256_pinned",
                     "chain_files_are_source_qualified", "write_denied_host-multi", "write_denied_host-feed",
                     "read_role_backends_ended_main", "read_role_backends_ended_restart", "restart_fresh_process",
                     "state_unchanged", "sources_still_absent", "outage_still_in_effect", "no_shim_invocations",
                     "chain_multi_graph_status_matches_stored", "chain_multi_refresh_status_matches_stored",
                     "chain_all_visible_status_matches_stored", "chain_multi_status_agrees_with_summary",
                     "chain_multi_stored_name_is_configured"):
        assert checks.get(required) is True, (required, {name: ok for name, ok in checks.items() if not ok})
    assert list(statuses.values()).count("expected_refusal_ok") == EXPECTED_REFUSALS
    assert {oracle_mid: statuses[oracle_mid] for oracle_mid in ("33", "34", "35", "36", "37")} == dict.fromkeys(
        ("33", "34", "35", "36", "37"), "positive_ok")
    assert set(statuses.values()) == {"protocol_ok", "positive_ok", "expected_refusal_ok"}
    assert main["exec_env_keys"] == list(ALLOWED_CHILD_KEYS) and " " in Path(main["cwd"]).name
    assert main["argv"][1:4] == ["mcp", "serve", "--repo-map-home"] and main["exit"] == 0
    outage = json.loads(members["session-outage.json"])
    assert outage["classification"]["ok"] and outage["exit"] == 0
    assert json.loads(members["session-restart.json"])["pid"] != main["pid"]
    oracle = json.loads(members["oracle.json"])["messages"]
    assert {oracle[mid]["tool"] for mid in ("20", "30", "40")} == {
        "repomap_canonical_nodes", "repomap_search_nodes", "repomap_ingested_sources"}

    assert remaining == "0" and read_backends == "0" and not work.exists()
    assert json.loads(members["cleanup.json"])["steps"][-1] == {"step": "remove-work-root", "ok": True,
                                                                "path": str(work)}
    owner_file = (run_dir / "OWNER.json").read_bytes()  # durable recovery record written before backend start
    owner_entry = manifest["members"]["OWNER.json"]
    assert hashlib.sha256(owner_file).hexdigest() == owner_entry["early_file_sha256"] == owner_entry.get(
        "original_sha256", owner_entry["recorded_sha256"])
    assert admin_password.encode() not in owner_file and json.loads(owner_file)["work_root"] == str(work)
    assert summary["signals"] == [] and summary["signal_timing"] == "none"
    blobs = b"".join(members.values())
    assert admin_password.encode() not in blobs
    assert re.search(rb"PASSWORD=(?!\[REDACTED\])\S", blobs) is None
    assert manifest["secret_values_registered"] >= 4
    stream = getattr(sys, "__stdout__", None)
    if stream is not None:
        stream.write("HOST_MCP_NATIVE_RUNNER_EVIDENCE=" + json.dumps({
            "receipt": receipt, "checks": checks, "catalog": summary.get("catalog"), "pids": summary.get("pids"),
            "console_form": console.form, "message_statuses": statuses,
            "outage_statuses": outage["classification"]["messages"],
            "stored_status": summary.get("chain", {}).get("stored_status")}, sort_keys=True) + "\n")
        stream.flush()


def test_status_owners_select_the_configured_repository_name(tmp_path: Path) -> None:
    """FIX1 attribution on one tiny multi-source publication, with fixture-admin SQL as the oracle.

    The HOST1 fixture tuple (stored name ``host-multi``) leaves a populated
    identity row that every name-selected status owner reports absent. A
    supported re-publication under the configured tuple renames that same row
    and the owners then report the identity row's run and counts; a stale-name
    decoy repository in the same database is never selected, and a genuinely
    unpublished graph stays absent.
    """
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        database = postgres.create_database(f"native_status_{uuid.uuid4().hex[:8]}")
        try:
            apply_migrations(default_rdbms_root(), database.psql_args, psql_command=database.psql_command)
            work = tmp_path / "work"
            work.mkdir(mode=0o700)
            _, _, graphs = stage_native_config(work, postgres.port, database.database, "native_status_feed_unused")
            multi = graphs["host-multi"]
            observations = capture_multi_source_candidate(multi).observations

            def publish(**repository: str) -> None:
                publish_observation_generation(database.psql_args, observations, psql_command=database.psql_command,
                                               **repository)

            def owners() -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
                refresh = json.loads(database.psql_scalar(build_refresh_status_sql(
                    [(multi.id, multi.repository_name), ("host-absent", "host-absent")])))["graphs"]
                storage = json.loads(database.psql_scalar(build_graph_storage_status_sql([multi.repository_name])))
                summary = json.loads(database.psql_scalar(build_graph_summary_sql(multi.repository_name)))
                return {row["graph_id"]: row for row in refresh}, storage["graphs"], summary

            publish(repository_name="host-multi", root_path="graph:host-multi", repository_identity="repo1:host-multi")
            host1 = stored_repository_facts(database, "host-multi")
            assert host1["repository_rows"] == 1 and host1["name"] == "host-multi", host1
            assert host1["latest_run_status"] == "complete" and all(host1[name] > 0 for name in STATUS_COUNTS), host1
            refresh, storage, summary = owners()
            assert len(refresh) == 2 and len(storage) == 1, (refresh, storage)
            for row in (refresh["host-multi"], storage[0], summary):  # the exact false predicate
                assert row["repository_exists"] is False and row.get("latest_run_id") is None, row
                assert all(row[name] == 0 for name in STATUS_COUNTS), row

            publish(**configured_publication(multi))
            publish(repository_name="host-multi", root_path="graph:host-multi-decoy",
                    repository_identity="repo1:host-multi-decoy")
            facts, decoy = (stored_repository_facts(database, graph_id)
                            for graph_id in ("host-multi", "host-multi-decoy"))
            assert facts["repository_rows"] == 1 and facts["name"] == multi.repository_name == "[multi-source]"
            assert facts["latest_run_id"] > host1["latest_run_id"] and decoy["latest_run_id"] > facts["latest_run_id"]
            refresh, storage, summary = owners()
            assert len(refresh) == 2 and len(storage) == 1, (refresh, storage)
            for row in (refresh["host-multi"], storage[0], summary):
                assert row["repository_exists"] is True, row
                assert {name: row[name] for name in STATUS_COUNTS} == {name: facts[name] for name in STATUS_COUNTS}
            for row in (refresh["host-multi"], summary):
                assert (row["latest_run_id"], row["latest_run_status"]) == (facts["latest_run_id"], "complete"), row
            absent = refresh["host-absent"]
            assert absent["repository_exists"] is False and absent["latest_run_id"] is None, absent
            assert all(absent[name] == 0 for name in STATUS_COUNTS) and absent["publication"] is None, absent
        finally:
            postgres.psql_scalar(f'DROP DATABASE IF EXISTS "{database.database}" WITH (FORCE);')
