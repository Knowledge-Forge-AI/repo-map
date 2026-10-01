"""SQLite Local backup-first v1 -> v2 migration and its rollback artifact (LOCAL8).

Disposable SQLite Local homes with one private graph. Every SQLite child runs
through the guarded launcher with the Psycopg family made genuinely
unavailable, recording shims and socket/spawn denial. A genuine v1 database is
created and published by children running as historical code
(``REPOMAP_TEST_SQLITE_SCHEMA_CEILING=1``: the catalog's preserved v1 prefix,
never a hand-edited ``user_version``); its raw ledger and physical schema equal
the literals pinned from the LOCAL7 checkpoint. Current code classifies it
``schema-behind`` and refuses ordinary reads, refresh and init;
``ops sqlite-upgrade`` writes a verified v1 backup, migrates to exact v2 with
the accepted generation and bundle unchanged, and source-blind MCP reads equal
the v1 baseline. The v1 backup restores into a second absent home as
exact-behind and an explicit upgrade there reaches the same v2 semantic
state. Drift, future, collision, a paused-then-killed upgrade and lock
contention are refused or rolled back without mutating the live v1 database.

This is containerized integration evidence (Linux sandbox), not a macOS host,
installed-wheel or power-loss qualification.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

from repomap_kg.storage.sqlite_local.migrations import schema_objects_digest
from repomap_test_support.sqlite_local_fixtures import graph_toml, write_shell_source, write_sqlite_home
from repomap_test_support.sqlite_local_harness import (
    LocalHarness,
    await_ready,
    initialize,
    refusal,
    release,
    structured,
    tool,
)

GRAPH = "vault"
TOKEN = "zzlocal8payloadtoken"
V1_CHECKSUM = "sha256:7f5b6045f0a46e699d42e8d8e90d51141c5db909b1eecfb3718a69df4825321d"
V1_PHYSICAL_DIGEST = "4ae049c21fffd346e70f74698efebb4717538aa64f7e3bbc040fe5d96c2ea10c"
V2_ROW = ("sqlite-local-v2-observation-path-index",
          "sha256:b5518fac02fde45a2a986995e4cf284840ccbee44092a5492c45f04651107489")
V2_PHYSICAL_DIGEST = "06f2cd0e35bd77d7dbc14ec894637c4b7b4b1605f25416b0d1922b7f9ccf4afe"
INDEX = "idx_raw_observations_path_run"
POSTGRES_IMPLEMENTATION = {
    "repomap_kg.coordinator.local_mode",
    "repomap_kg.coordinator.local_lifecycle",
    "repomap_kg.service_package.api",
    "repomap_kg.storage.staged_ingestion",
    "repomap_kg.runtime.maintenance",
    "repomap_kg.runtime.release_cluster",
    "repomap_kg.ops.refresh",
    "psycopg",
}


def _home(tmp_path: Path, name: str, source: Path) -> Path:
    return write_sqlite_home(tmp_path / name, graph_toml(GRAPH, source, privacy="private-ops"))


def _database(home: Path) -> Path:
    return home / "state" / "sqlite-local" / "graphs" / f"{GRAPH}.sqlite3"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _files(directory: Path) -> dict[str, str]:
    return {path.name: _sha(path) for path in sorted(directory.iterdir())}


def _ok(completed: subprocess.CompletedProcess[str]) -> subprocess.CompletedProcess[str]:
    assert completed.returncode == 0, completed.stderr
    return completed


def _json(harness: LocalHarness, home: Path, *args: str, env: dict[str, str] | None = None) -> dict[str, Any]:
    completed = _ok(harness.run(*args, "--repo-map-home", str(home), "--json", extra_env=env))
    payload = json.loads(completed.stdout)
    assert isinstance(payload, dict) and str(home) not in completed.stdout, completed.stdout
    return payload


def _refused(harness: LocalHarness, home: Path, *args: str, env: dict[str, str] | None = None) -> str:
    completed = harness.run(*args, "--repo-map-home", str(home), extra_env=env)
    assert completed.returncode == 1, completed.stdout
    assert "[redacted-path]" not in completed.stderr and str(home) not in completed.stderr, completed.stderr
    return completed.stderr.strip()


def _upgrade(harness: LocalHarness, home: Path, output: Path) -> dict[str, Any]:
    return _json(harness, home, "ops", "sqlite-upgrade", "--graph", GRAPH, "--backup-output", str(output))


def _readiness(harness: LocalHarness, home: Path) -> tuple[str, int | None]:
    status = _json(harness, home, "ops", "graphs", "--check-db")["graphs"][0]["storage_status"]
    return status["state"], status["accepted_generation"]


def _raw(path: Path) -> dict[str, Any]:
    """Ledger, user_version, index presence, physical digest and accepted identity of a closed file."""
    reader = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True)
    try:
        return {
            "ledger": reader.execute(
                "SELECT version, name, checksum FROM local_schema_migrations ORDER BY version").fetchall(),
            "user_version": reader.execute("PRAGMA user_version").fetchone()[0],
            "index": reader.execute(f"SELECT count(*) FROM sqlite_schema WHERE name = '{INDEX}'").fetchone()[0],
            "digest": schema_objects_digest(reader),
            "accepted": reader.execute(
                "SELECT a.generation, r.publication_bundle_id FROM accepted_publication a "
                "JOIN runs r ON r.id = a.run_id").fetchone(),
        }
    finally:
        reader.close()


def _v1_raw(generation: int, bundle: str) -> dict[str, Any]:
    return {"ledger": [(1, "sqlite-local-v1", V1_CHECKSUM)], "user_version": 1, "index": 0,
            "digest": V1_PHYSICAL_DIGEST, "accepted": (generation, bundle)}


def _v2_raw(generation: int, bundle: str) -> dict[str, Any]:
    return {"ledger": [(1, "sqlite-local-v1", V1_CHECKSUM), (2, *V2_ROW)], "user_version": 2, "index": 1,
            "digest": V2_PHYSICAL_DIGEST, "accepted": (generation, bundle)}


def _mcp_reads(harness: LocalHarness, home: Path, paths: list[str], env: dict[str, str] | None = None) -> dict[str, Any]:
    requests = [
        initialize(),
        tool(2, "repomap_graph_status", {"graph_id": GRAPH}),
        tool(3, "repomap_canonical_nodes", {"project": GRAPH, "limit": 50}),
        tool(4, "repomap_search_observations", {"graph_id": GRAPH, "query": ".", "limit": 100, "include_raw": True}),
        *(tool(10 + index, "repomap_search_observations",
               {"graph_id": GRAPH, "query": ".", "path": path, "limit": 100}) for index, path in enumerate(paths)),
    ]
    responses = harness.mcp(home, requests, extra_env=env)
    storage = structured(responses, 2)["storage"]
    return {
        "publication": storage["publication"],
        "latest_run_id": storage["latest_run_id"],
        "nodes": sorted(str(item["canonical_key"]) for item in structured(responses, 3)["items"]),
        "observations": structured(responses, 4),
        **{f"path:{path}": structured(responses, 10 + index) for index, path in enumerate(paths)},
    }


def _assert_guarded(harness: LocalHarness) -> None:
    assert harness.forbidden_events() == [], harness.forbidden_events()
    assert harness.shim_invocations() == "", harness.shim_invocations()
    loaded = harness.imported_modules() & POSTGRES_IMPLEMENTATION
    assert not loaded, f"SQLite children loaded PostgreSQL implementation modules: {sorted(loaded)}"


def _no_paths(text: str, *roots: Path) -> None:
    for root in roots:
        assert str(root) not in text, root


def test_v1_backup_upgrade_restore_round_trip(tmp_path: Path) -> None:
    source = write_shell_source(tmp_path / "sources" / GRAPH)
    (source / "token.sh").write_text(f"{TOKEN}() {{\n  echo private\n}}\n", encoding="utf-8")
    home = _home(tmp_path, "home", source)
    second_home = _home(tmp_path, "second-home", source)
    harness = LocalHarness(tmp_path / "scratch", block_psycopg=True)
    v1 = harness.ceiling_env(1)
    live = _database(home)

    # 1: a genuine v1 database created and published (two generations) by historical code.
    _ok(harness.run("ops", "sqlite-init", "--repo-map-home", str(home), "--graph", GRAPH, extra_env=v1))
    _json(harness, home, "ops", "refresh-graph", "--graph", GRAPH, env=v1)
    (source / "extra.sh").write_text("extra_fn() {\n  echo extra\n}\n", encoding="utf-8")
    second = _json(harness, home, "ops", "refresh-graph", "--graph", GRAPH, env=v1)
    bundle = second["publication"]["publication_bundle_id"]
    assert second["accepted_generation"] == 2, second
    assert _raw(live) == _v1_raw(2, bundle), "the historical database must be exactly the checkpoint v1 schema"
    unfiltered = harness.mcp(home, [initialize(), tool(2, "repomap_search_observations",
                                                        {"graph_id": GRAPH, "query": ".", "limit": 100})], extra_env=v1)
    paths = sorted({row["path"] for row in structured(unfiltered, 2)["results"]})
    assert len(paths) >= 3, paths
    baseline = _mcp_reads(harness, home, paths, env=v1)
    assert baseline["observations"]["results"] and baseline["nodes"], baseline

    # 2: current code classifies it exact-behind and refuses ordinary reads, refresh and init.
    behind_sha = _sha(live)
    assert _readiness(harness, home) == ("schema-behind", 2)
    responses = harness.mcp(home, [initialize(), tool(2, "repomap_search_observations", {"graph_id": GRAPH, "query": "."})])
    assert refusal(responses, 2).startswith("graph-database-schema-behind"), refusal(responses, 2)
    for args in (("ops", "refresh-graph", "--graph", GRAPH), ("ops", "sqlite-init", "--graph", GRAPH)):
        assert "graph-database-schema-behind" in _refused(harness, home, *args), args
    assert _sha(live) == behind_sha

    # 3-5: explicit upgrade; the backup is the exact v1 rollback artifact.
    backups = tmp_path / "backups"
    backups.mkdir()
    upgraded = _upgrade(harness, home, backups / "pre-upgrade")
    assert (upgraded["result"], upgraded["from_schema_version"], upgraded["schema_version"]) == ("upgraded", 1, 2)
    assert (upgraded["accepted_generation"], upgraded["publication_bundle_id"]) == (2, bundle), upgraded
    artifact = _files(backups / "pre-upgrade")
    assert sorted(artifact) == ["graph.sqlite3", "manifest.json"]
    assert artifact["graph.sqlite3"] == upgraded["backup_database_sha256"]
    manifest_text = (backups / "pre-upgrade" / "manifest.json").read_text(encoding="utf-8")
    _no_paths(manifest_text, tmp_path)
    assert TOKEN not in manifest_text
    manifest = json.loads(manifest_text)
    assert manifest["sqlite"] == {"application_id": 0x52504D31, "user_version": 1,
                                  "schema_name": "sqlite-local-v1", "schema_checksum": V1_CHECKSUM}, manifest
    assert (manifest["publication"]["generation"], manifest["publication"]["publication_bundle_id"]) == (2, bundle)
    assert _raw(backups / "pre-upgrade" / "graph.sqlite3") == _v1_raw(2, bundle)

    # 6: the live database is exact v2 with the same accepted publication.
    assert _raw(live) == _v2_raw(2, bundle)
    assert _readiness(harness, home) == ("current", 2)

    # 7: source-blind reads after the upgrade equal the v1 baseline.
    shutil.move(source, tmp_path / "sources-away")
    assert _mcp_reads(harness, home, paths) == baseline

    # 8: a rerun is already-current: no backup, no reapply.
    upgraded_sha = _sha(live)
    again = _upgrade(harness, home, backups / "pre-upgrade")
    assert (again["result"], again["backup_created"]) == ("already-current", False), again
    assert _files(backups / "pre-upgrade") == artifact and _sha(live) == upgraded_sha

    # 9: the v1 backup restores into a second absent home exact-behind, never migrated.
    restored = _json(harness, second_home, "ops", "sqlite-restore", "--graph", GRAPH,
                     "--backup", str(backups / "pre-upgrade"))
    assert (restored["schema_version"], restored["schema_state"], restored["accepted_generation"]) == (1, "behind", 2)
    assert _raw(_database(second_home)) == _v1_raw(2, bundle)
    assert _readiness(harness, second_home) == ("schema-behind", 2)
    responses = harness.mcp(second_home, [initialize(), tool(2, "repomap_canonical_nodes", {"project": GRAPH})])
    assert refusal(responses, 2).startswith("graph-database-schema-behind"), refusal(responses, 2)
    assert _files(backups / "pre-upgrade") == artifact, "restore changed the backup"

    # 10: an explicit upgrade of the restored home reaches the same v2 semantic state.
    again_upgraded = _upgrade(harness, second_home, backups / "restored-pre-upgrade")
    assert (again_upgraded["result"], again_upgraded["publication_bundle_id"]) == ("upgraded", bundle)
    assert _raw(_database(second_home)) == _v2_raw(2, bundle)
    assert _mcp_reads(harness, second_home, paths) == baseline
    _assert_guarded(harness)


def _checkpointed(path: Path, statement: str | None = None) -> None:
    writer = sqlite3.connect(path, autocommit=True)
    try:
        if statement is not None:
            writer.execute(statement)
        writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        writer.close()
    for suffix in ("-wal", "-shm"):
        path.with_name(path.name + suffix).unlink(missing_ok=True)


def test_upgrade_refusals_faults_and_contention(tmp_path: Path) -> None:
    source = write_shell_source(tmp_path / "sources" / GRAPH)
    home = _home(tmp_path, "home", source)
    restore_home = _home(tmp_path, "restore-home", source)
    harness = LocalHarness(tmp_path / "scratch", block_psycopg=True)
    v1 = harness.ceiling_env(1)
    live = _database(home)
    _ok(harness.run("ops", "sqlite-init", "--repo-map-home", str(home), "--graph", GRAPH, extra_env=v1))
    bundle = _json(harness, home, "ops", "refresh-graph", "--graph", GRAPH, env=v1)["publication"]["publication_bundle_id"]
    _checkpointed(live)
    pristine = live.read_bytes()

    # Drift and future: refused before any backup; the live bytes never change.
    cases = {
        "UPDATE local_schema_migrations SET checksum = 'sha256:0'": "graph-database-schema-drift",
        "DROP INDEX idx_raw_observations_kind": "graph-database-schema-drift",
        f"CREATE INDEX {INDEX} ON raw_observations(path, run_id DESC, ordinal)": "graph-database-schema-drift",
        "PRAGMA user_version = 3": "graph-database-schema-unsupported",
        "INSERT INTO local_schema_migrations VALUES (3, 'future', 'sha256:f', 't')": "graph-database-schema-unsupported",
    }
    for index, (statement, code) in enumerate(cases.items()):
        live.write_bytes(pristine)
        _checkpointed(live, statement)
        mutated = _sha(live)
        output = tmp_path / f"refused-{index}"
        message = _refused(harness, home, "ops", "sqlite-upgrade", "--graph", GRAPH, "--backup-output", str(output))
        assert message == f"ERROR: {code}", (statement, message)
        assert not output.exists() and _sha(live) == mutated, statement
    live.write_bytes(pristine)
    assert _raw(live) == _v1_raw(1, bundle)

    # Backup output collision: no backup, no migration.
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "keep").write_text("x", encoding="utf-8")
    message = _refused(harness, home, "ops", "sqlite-upgrade", "--graph", GRAPH, "--backup-output", str(occupied))
    assert message == "ERROR: sqlite-backup-target-exists: output directory is not empty", message
    assert os.listdir(occupied) == ["keep"] and live.read_bytes() == pristine

    # Paused after the verified backup, before COMMIT: contenders are refused; a kill leaves exact v1.
    barrier = tmp_path / "upgrade-barrier"
    paused = harness.start(
        "ops", "sqlite-upgrade", "--repo-map-home", str(home), "--graph", GRAPH,
        "--backup-output", str(tmp_path / "killed-backup"),
        extra_env=harness.paused_env("upgrade:before-commit", barrier),
    )
    try:
        await_ready(barrier, paused)
        message = _refused(harness, home, "ops", "sqlite-upgrade", "--graph", GRAPH,
                           "--backup-output", str(tmp_path / "contender"))
        assert message == "ERROR: graph-publication-in-progress", message
        assert not (tmp_path / "contender").exists()
        message = _refused(harness, home, "ops", "refresh-graph", "--graph", GRAPH, env=v1)
        assert message == "ERROR: graph-publication-in-progress", message
        os.kill(paused.pid, signal.SIGKILL)
    finally:
        if paused.poll() is None:
            release(barrier)
        paused.communicate()
    assert paused.returncode == -signal.SIGKILL
    assert _readiness(harness, home) == ("schema-behind", 1)
    _checkpointed(live)
    assert _raw(live) == _v1_raw(1, bundle), "a killed pre-COMMIT upgrade must leave exact v1"
    assert _raw(tmp_path / "killed-backup" / "graph.sqlite3") == _v1_raw(1, bundle)
    restored = _json(harness, restore_home, "ops", "sqlite-restore", "--graph", GRAPH,
                     "--backup", str(tmp_path / "killed-backup"))
    assert (restored["schema_state"], restored["accepted_generation"]) == ("behind", 1), restored

    # A rerun with a new output completes the upgrade.
    rerun = _upgrade(harness, home, tmp_path / "rerun-backup")
    assert (rerun["result"], rerun["accepted_generation"], rerun["publication_bundle_id"]) == ("upgraded", 1, bundle)
    assert _raw(live) == _v2_raw(1, bundle)
    _assert_guarded(harness)
