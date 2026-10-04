"""SQLite Local backup/export and no-clobber restore round trip (LOCAL7).

One disposable SQLite Local home with one private graph. Every SQLite child
runs through the guarded launcher with the Psycopg family made genuinely
unavailable, recording shims for PostgreSQL, container and service
executables, and socket/spawn denial. The real CLI publishes generation 1,
backs it up, publishes a semantically different generation 2, proves the
backup unchanged, removes the sources and (by test-fixture authority) the live
database, restores the backup into the absent target, reads generation 1
through ``ops graphs --check-db`` and stdio MCP with no sources, and after the
test restores the sources refreshes normally from the restored state. The
artifact is exactly two files; the manifest holds no path, source root, secret
or payload token while the database keeps the accepted private payload.
Tampered, incompatible and incomplete artifacts are refused before the target
exists; an existing target is never replaced; a restore killed before its
link leaves the target absent; a backup killed before its manifest is never
restorable and never changes the live database; and a backup contending with a
paused writer is refused immediately under the current lock contract.

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

from repomap_test_support.sqlite_local_fixtures import graph_toml, write_shell_source, write_sqlite_home
from repomap_test_support.sqlite_local_harness import (
    LocalHarness,
    await_ready,
    initialize,
    kill_paused_child,
    release,
    remove_database,
    structured,
    tool,
)

GRAPH = "vault"
TOKEN = "zzlocal7payloadtoken"
CONFIG_SECRET = "zzlocal7configsecretvalue"
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


def _setup(tmp_path: Path) -> tuple[Path, Path, LocalHarness]:
    source = write_shell_source(tmp_path / "sources" / GRAPH)
    (source / "token.sh").write_text(f"{TOKEN}() {{\n  echo private\n}}\n", encoding="utf-8")
    home = write_sqlite_home(tmp_path / "home", graph_toml(GRAPH, source, privacy="private-ops"))
    (home / "operator.env").write_text(f"REPOMAP_EXTRA={CONFIG_SECRET}\n", encoding="utf-8")
    return home, source, LocalHarness(tmp_path / "scratch", block_psycopg=True)


def _database(home: Path) -> Path:
    return home / "state" / "sqlite-local" / "graphs" / f"{GRAPH}.sqlite3"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _files(directory: Path) -> dict[str, str]:
    return {path.name: _sha(path) for path in sorted(directory.iterdir())}


def _ok(completed: subprocess.CompletedProcess[str]) -> subprocess.CompletedProcess[str]:
    assert completed.returncode == 0, completed.stderr
    return completed


def _json(harness: LocalHarness, home: Path, *args: str) -> dict[str, Any]:
    payload = json.loads(_ok(harness.run(*args, "--repo-map-home", str(home), "--json")).stdout)
    assert isinstance(payload, dict)
    return payload


def _refused(harness: LocalHarness, home: Path, *args: str) -> str:
    completed = harness.run(*args, "--repo-map-home", str(home))
    assert completed.returncode == 1, completed.stdout
    assert "[redacted-path]" not in completed.stderr, completed.stderr
    return completed.stderr.strip()


def _backup(harness: LocalHarness, home: Path, output: Path) -> dict[str, Any]:
    return _json(harness, home, "ops", "sqlite-backup", "--graph", GRAPH, "--output", str(output))


def _restore(harness: LocalHarness, home: Path, backup: Path) -> dict[str, Any]:
    return _json(harness, home, "ops", "sqlite-restore", "--graph", GRAPH, "--backup", str(backup))


def _readiness(harness: LocalHarness, home: Path) -> tuple[str, int | None]:
    status = _json(harness, home, "ops", "graphs", "--check-db")["graphs"][0]["storage_status"]
    return status["state"], status["accepted_generation"]


def _mcp_state(harness: LocalHarness, home: Path) -> tuple[dict[str, Any], list[str]]:
    responses = harness.mcp(
        home,
        [
            initialize(),
            tool(2, "repomap_graph_status", {"graph_id": GRAPH}),
            tool(3, "repomap_canonical_nodes", {"project": GRAPH, "limit": 50}),
        ],
    )
    nodes = sorted(str(item["canonical_key"]) for item in structured(responses, 3)["items"])
    return structured(responses, 2)["storage"], nodes


def _assert_guarded(harness: LocalHarness) -> None:
    assert harness.forbidden_events() == [], harness.forbidden_events()
    assert harness.shim_invocations() == "", harness.shim_invocations()
    loaded = harness.imported_modules() & POSTGRES_IMPLEMENTATION
    assert not loaded, f"SQLite children loaded PostgreSQL implementation modules: {sorted(loaded)}"


def test_backup_restore_round_trip_preserves_the_exact_accepted_publication(tmp_path: Path) -> None:
    home, source, harness = _setup(tmp_path)
    backups = tmp_path / "backups"
    backups.mkdir()
    _ok(harness.run("ops", "sqlite-init", "--repo-map-home", str(home), "--graph", GRAPH))

    # 1-2: generation 1, then backup A bound to it.
    first = _json(harness, home, "ops", "refresh-graph", "--graph", GRAPH)
    assert first["accepted_generation"] == 1, first
    bundle_a = first["publication"]["publication_bundle_id"]
    status_a, nodes_a = _mcp_state(harness, home)
    created = _backup(harness, home, backups / "a")
    assert (created["accepted_generation"], created["publication_bundle_id"]) == (1, bundle_a), created
    manifest = json.loads((backups / "a" / "manifest.json").read_bytes())
    assert (manifest["publication"]["generation"], manifest["publication"]["publication_bundle_id"]) == (1, bundle_a)
    artifact = _files(backups / "a")
    assert sorted(artifact) == ["graph.sqlite3", "manifest.json"]
    assert artifact["graph.sqlite3"] == created["database_sha256"] == manifest["database"]["sha256"]

    # D7: the manifest is path-, secret- and payload-free; the database keeps the private payload.
    text = (backups / "a" / "manifest.json").read_text(encoding="utf-8")
    for forbidden in (str(tmp_path), str(home), str(source), str(backups), CONFIG_SECRET, TOKEN, "postgres"):
        assert forbidden not in text, forbidden
    database_bytes = (backups / "a" / "graph.sqlite3").read_bytes()
    assert TOKEN.encode() in database_bytes and CONFIG_SECRET.encode() not in database_bytes
    assert str(home).encode() not in database_bytes and str(source).encode() not in database_bytes

    # 3-4: a semantically different generation 2; backup A is unchanged.
    (source / "extra.sh").write_text("extra_fn() {\n  echo extra\n}\n", encoding="utf-8")
    second = _json(harness, home, "ops", "refresh-graph", "--graph", GRAPH)
    assert second["accepted_generation"] == 2 and second["publication"]["publication_bundle_id"] != bundle_a
    assert _files(backups / "a") == artifact
    assert _mcp_state(harness, home)[1] != nodes_a, "generation 2 must differ semantically"

    # 5-7: sources unavailable, live database removed by fixture authority, restore A.
    shutil.move(source, tmp_path / "sources-away")
    remove_database(_database(home))
    assert _readiness(harness, home) == ("not-initialized", None)
    restored = _restore(harness, home, backups / "a")
    assert (restored["accepted_generation"], restored["publication_bundle_id"]) == (1, bundle_a), restored
    assert _files(backups / "a") == artifact, "restore changed the backup"

    # 8: normal Local status and MCP reads show generation 1 without sources.
    assert _readiness(harness, home) == ("current", 1)
    status, nodes = _mcp_state(harness, home)
    assert nodes == nodes_a
    assert status["latest_run_id"] == 1 and status["publication"] == status_a["publication"], status

    # 9: after the test restores the sources, refresh advances normally.
    shutil.move(tmp_path / "sources-away", source)
    advanced = _json(harness, home, "ops", "refresh-graph", "--graph", GRAPH)
    assert (advanced["accepted_generation"], advanced["previous_run_id"]) == (2, 1), advanced
    assert advanced["publication"]["publication_bundle_id"] != bundle_a
    assert _files(backups / "a") == artifact
    _assert_guarded(harness)


def _rewrite(manifest: Path, change: Any) -> None:
    payload = json.loads(manifest.read_bytes())
    change(payload)
    manifest.write_bytes(json.dumps(payload).encode())


def _variant(original: Path, name: str) -> Path:
    copy = original.with_name(name)
    shutil.copytree(original, copy)
    return copy


def test_tampered_incompatible_and_existing_targets_are_refused(tmp_path: Path) -> None:
    home, _, harness = _setup(tmp_path)
    _ok(harness.run("ops", "sqlite-init", "--repo-map-home", str(home), "--graph", GRAPH))
    _json(harness, home, "ops", "refresh-graph", "--graph", GRAPH)
    good = tmp_path / "good"
    _backup(harness, home, good)

    # Existing target: never replaced.
    live = _database(home)
    before = (_sha(live), live.stat().st_ino)
    assert "sqlite-restore-target-exists" in _refused(
        harness, home, "ops", "sqlite-restore", "--graph", GRAPH, "--backup", str(good)
    )
    assert (_sha(live), live.stat().st_ino) == before
    remove_database(live)

    tampered_db = _variant(good, "tampered-db")
    data = bytearray((tampered_db / "graph.sqlite3").read_bytes())
    data[len(data) // 2] ^= 0x01
    (tampered_db / "graph.sqlite3").write_bytes(bytes(data))
    tampered_generation = _variant(good, "tampered-generation")
    _rewrite(tampered_generation / "manifest.json", lambda p: p["publication"].update(generation=2))
    tampered_bundle = _variant(good, "tampered-bundle")
    _rewrite(tampered_bundle / "manifest.json", lambda p: p["publication"].update(publication_bundle_id="bundle1:x"))
    future_schema = _variant(good, "future-schema")
    _rewrite(future_schema / "manifest.json", lambda p: p["sqlite"].update(user_version=3))
    foreign = _variant(good, "foreign-application")
    database = foreign / "graph.sqlite3"
    writer = sqlite3.connect(database)
    try:
        writer.execute("PRAGMA application_id = 7")
    finally:
        writer.close()
    for suffix in ("-wal", "-shm"):
        database.with_name(database.name + suffix).unlink(missing_ok=True)
    _rewrite(foreign / "manifest.json", lambda p: p["database"].update(sha256=_sha(database)))
    incomplete = _variant(good, "incomplete")
    (incomplete / "manifest.json").unlink()
    expected = {
        tampered_db: "sqlite-backup-artifact-invalid: database-digest-mismatch",
        tampered_generation: "sqlite-backup-artifact-invalid: publication-mismatch",
        tampered_bundle: "sqlite-backup-artifact-invalid: publication-mismatch",
        future_schema: "sqlite-backup-artifact-invalid: schema-unsupported",
        foreign: "sqlite-backup-artifact-invalid: graph-database-unrecognized",
        incomplete: "sqlite-backup-incomplete: no completed manifest",
    }
    for backup, message in expected.items():
        stderr = _refused(harness, home, "ops", "sqlite-restore", "--graph", GRAPH, "--backup", str(backup))
        assert stderr == f"ERROR: {message}", (backup.name, stderr)
        assert not os.path.lexists(live), backup.name

    # A restore killed before its link leaves the target absent; a rerun succeeds.
    barrier = tmp_path / "restore-barrier"
    killed = harness.start(
        "ops", "sqlite-restore", "--repo-map-home", str(home), "--graph", GRAPH, "--backup", str(good),
        extra_env=harness.paused_env("restore:before-install", barrier, abrupt=True),
    )
    try:
        await_ready(barrier, killed)
        kill_paused_child(killed)
    finally:
        killed.communicate()
    assert killed.returncode == -signal.SIGKILL
    assert not os.path.lexists(live)
    assert _readiness(harness, home) == ("not-initialized", None)
    assert _restore(harness, home, good)["accepted_generation"] == 1
    assert _readiness(harness, home) == ("current", 1)
    _assert_guarded(harness)


def test_interrupted_or_contending_backup_never_claims_success(tmp_path: Path) -> None:
    home, _, harness = _setup(tmp_path)
    _ok(harness.run("ops", "sqlite-init", "--repo-map-home", str(home), "--graph", GRAPH))
    _json(harness, home, "ops", "refresh-graph", "--graph", GRAPH)
    live = _database(home)
    accepted = _sha(live)

    # Killed before the manifest link: incomplete, never restorable, live file untouched.
    barrier = tmp_path / "backup-barrier"
    output = tmp_path / "killed"
    killed = harness.start(
        "ops", "sqlite-backup", "--repo-map-home", str(home), "--graph", GRAPH, "--output", str(output),
        extra_env=harness.paused_env("backup:before-manifest-link", barrier, abrupt=True),
    )
    try:
        await_ready(barrier, killed)
        kill_paused_child(killed)
    finally:
        killed.communicate()
    assert killed.returncode == -signal.SIGKILL
    assert "manifest.json" not in os.listdir(output)
    assert _sha(live) == accepted
    stderr = _refused(harness, home, "ops", "sqlite-restore", "--graph", GRAPH, "--backup", str(output))
    assert stderr == "ERROR: sqlite-backup-incomplete: no completed manifest", stderr
    assert "sqlite-backup-target-exists" in _refused(
        harness, home, "ops", "sqlite-backup", "--graph", GRAPH, "--output", str(output)
    ), "a partial backup directory must never be replaced"
    assert _sha(live) == accepted

    # A backup contending with a paused writer is refused immediately.
    holder_barrier = tmp_path / "writer-barrier"
    holder = harness.start(
        "ops", "refresh-graph", "--repo-map-home", str(home), "--graph", GRAPH,
        extra_env=harness.paused_env("before_commit", holder_barrier),
    )
    try:
        await_ready(holder_barrier, holder)
        held = _sha(live)
        stderr = _refused(
            harness, home, "ops", "sqlite-backup", "--graph", GRAPH, "--output", str(tmp_path / "contended")
        )
        assert stderr == "ERROR: graph-publication-in-progress", stderr
        assert not (tmp_path / "contended").exists()
        assert _sha(live) == held
        release(holder_barrier)
        _, holder_stderr = holder.communicate(timeout=240)
        assert holder.returncode == 0, holder_stderr
    finally:
        if holder.poll() is None:
            kill_paused_child(holder)
            holder.communicate()
    after = _backup(harness, home, tmp_path / "after-writer")
    assert after["accepted_generation"] == 2, after
    _assert_guarded(harness)
