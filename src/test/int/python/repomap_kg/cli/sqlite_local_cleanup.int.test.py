"""SQLite Local ``ops sqlite-cleanup`` over real refreshes, kills and restores (LOCAL9).

One disposable SQLite Local home per test. Every SQLite child runs through
the guarded launcher with the Psycopg family made genuinely unavailable,
recording shims for PostgreSQL, container and service executables,
socket/spawn denial, and a record of every directory the child fsyncs.

Attempts: two real refreshes leave two terminal graph-local attempts; by test
fixture authority one is aged past its expiry and one real attempt tree is
copied into the pre-LOCAL3 shared directory twice, once as an expired terminal
record and once as an unsettled one without a publication identity. A dry run
changes no byte, name or mode in the home and syncs nothing. ``--yes`` removes
exactly the expired graph-local and shared terminal attempts, keeps the
unexpired and the unsettled one byte-identical (reported as manual recovery),
leaves the database bytes and source-blind MCP reads unchanged, and syncs
exactly ``state/`` then the home.

Orphans: processes killed at the maintained init and restore fault points
leave real orphans. Beside an absent database the partial one is removed and
the recoverable ones are preserved; nothing is adopted and the target stays
absent. A restore killed after its link leaves a live database with a second
link; ``--yes`` then removes every now-stale orphan and only the orphan name of
the second link, and the database and MCP reads are unchanged.

This is containerized integration evidence (Linux sandbox), not a macOS host,
installed-wheel or power-loss qualification. No timing gate.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import stat
import subprocess
from pathlib import Path
from typing import Any

from repomap_test_support.sqlite_local_fixtures import graph_toml, write_shell_source, write_sqlite_home
from repomap_test_support.sqlite_local_harness import (
    LocalHarness,
    await_ready,
    initialize,
    remove_database,
    structured,
    temp_orphans,
    tool,
)

GRAPH = "vault"
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
    home = write_sqlite_home(tmp_path / "home", graph_toml(GRAPH, source))
    return home, source, LocalHarness(tmp_path / "scratch", block_psycopg=True)


def _database(home: Path) -> Path:
    return home / "state" / "sqlite-local" / "graphs" / f"{GRAPH}.sqlite3"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ok(completed: subprocess.CompletedProcess[str]) -> subprocess.CompletedProcess[str]:
    assert completed.returncode == 0, completed.stderr
    return completed


def _json(harness: LocalHarness, home: Path, *args: str, env: dict[str, str] | None = None) -> dict[str, Any]:
    completed = _ok(harness.run(*args, "--repo-map-home", str(home), "--json", extra_env=env))
    payload = json.loads(completed.stdout)
    assert isinstance(payload, dict)
    return payload


def _cleanup(harness: LocalHarness, home: Path, log: Path, *extra: str) -> dict[str, Any]:
    payload = _json(harness, home, "ops", "sqlite-cleanup", "--graph", GRAPH, *extra, env=harness.sync_env(log))
    text = json.dumps(payload)
    assert str(home) not in text and str(home.resolve()) not in text, text
    return payload


def _synced(log: Path) -> list[str]:
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def _tree(root: Path, *, skip: tuple[str, ...] = ()) -> dict[str, tuple[int, int, str]]:
    snapshot: dict[str, tuple[int, int, str]] = {}
    for path in sorted(root.rglob("*")):
        if path.name.endswith(skip):
            continue
        details = path.lstat()
        digest = _sha(path) if stat.S_ISREG(details.st_mode) else ""
        snapshot[str(path.relative_to(root))] = (stat.S_IFMT(details.st_mode), stat.S_IMODE(details.st_mode), digest)
    return snapshot


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


def _readiness(harness: LocalHarness, home: Path) -> tuple[str, int | None]:
    status = _json(harness, home, "ops", "graphs", "--check-db")["graphs"][0]["storage_status"]
    return status["state"], status["accepted_generation"]


def _assert_guarded(harness: LocalHarness) -> None:
    assert harness.forbidden_events() == [], harness.forbidden_events()
    assert harness.shim_invocations() == "", harness.shim_invocations()
    loaded = harness.imported_modules() & POSTGRES_IMPLEMENTATION
    assert not loaded, f"SQLite children loaded PostgreSQL implementation modules: {sorted(loaded)}"


def _rewrite_record(attempt: Path, change: dict[str, Any], *, drop: tuple[str, ...] = ()) -> None:
    """Fixture authority: replace one owner-only record exactly as the product would."""
    record = attempt / "portable-result.json"
    payload = json.loads(record.read_bytes())
    payload.update(change)
    for key in drop:
        payload.pop(key, None)
    temporary = attempt / ".fixture-record"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
    finally:
        os.close(descriptor)
    os.replace(temporary, record)


def test_attempt_cleanup_dry_run_and_current_durability(tmp_path: Path) -> None:
    home, source, harness = _setup(tmp_path)
    _ok(harness.run("ops", "sqlite-init", "--repo-map-home", str(home), "--graph", GRAPH))
    for generation in (1, 2):
        assert _json(harness, home, "ops", "refresh-graph", "--graph", GRAPH)["accepted_generation"] == generation
    publication = home / "state" / "portable-publication"
    graph_attempts = sorted((publication / "sqlite-local" / GRAPH / "attempts").iterdir())
    assert len(graph_attempts) == 2, graph_attempts
    records = [json.loads((path / "portable-result.json").read_bytes()) for path in graph_attempts]
    assert {record["retention_class"] for record in records} == {"terminal-accepted"}, records
    aged, fresh = graph_attempts
    _rewrite_record(aged, {"expires_at_epoch": 1_000})
    legacy = publication / "attempts"
    legacy.mkdir(mode=0o700)
    legacy_expired = legacy / ("e" * 64)
    legacy_unresolved = legacy / ("f" * 64)
    for copy in (legacy_expired, legacy_unresolved):
        shutil.copytree(fresh, copy, symlinks=True)
    _rewrite_record(legacy_expired, {"expires_at_epoch": 1_000}, drop=("sqlite_local_publication",))
    _rewrite_record(
        legacy_unresolved, {"retention_class": "publication-reconciliation"},
        drop=("sqlite_local_publication", "expires_at_epoch"),
    )
    unresolved_tree = _tree(legacy_unresolved)
    fresh_tree = _tree(fresh)
    shutil.move(source, tmp_path / "sources-away")
    database = _database(home)
    live = _sha(database)
    baseline = _mcp_state(harness, home)

    # 8: the dry run changes nothing and syncs nothing.
    live_sidecars = (f"{GRAPH}.sqlite3-wal", f"{GRAPH}.sqlite3-shm")
    before = _tree(home, skip=live_sidecars)
    log = tmp_path / "sync.log"
    dry = _cleanup(harness, home, log)
    assert _tree(home, skip=live_sidecars) == before, "a dry run changed the home"
    assert _synced(log) == [], _synced(log)
    assert (dry["result"], dry["refusal_count"]) == ("dry-run", 0), dry
    assert (dry["graph_attempts"]["expired_terminal_found"], dry["graph_attempts"]["retained_terminal"]) == (1, 1)
    assert dry["legacy_shared_attempts"] == {
        "expired_terminal_found": 1, "expired_terminal_removed": 0, "retained_terminal": 0,
        "unresolved_preserved": 1, "incomplete_preserved": 0, "unsafe": 0,
    }, dry

    # 2-4, 11: --yes removes only the expired terminal attempts and syncs state/ then the home.
    cleaned = _cleanup(harness, home, log, "--yes")
    assert (cleaned["result"], cleaned["changed"], cleaned["durability"]) == ("cleaned", True, "established"), cleaned
    assert cleaned["graph_attempts"]["expired_terminal_removed"] == 1
    assert cleaned["legacy_shared_attempts"]["expired_terminal_removed"] == 1
    assert cleaned["manual_recovery_required"] is True and "legacy-unresolved-attempt" in cleaned["warnings"]
    assert not aged.exists() and not legacy_expired.exists()
    assert _tree(fresh) == fresh_tree and _tree(legacy_unresolved) == unresolved_tree
    resolved = home.resolve()
    assert _synced(log) == [str(resolved / "state"), str(resolved)], _synced(log)

    # 1, 9: the database bytes and source-blind MCP reads are unchanged.
    assert _sha(database) == live
    assert _mcp_state(harness, home) == baseline
    again = _cleanup(harness, home, tmp_path / "sync-again.log", "--yes")
    assert (again["result"], again["changed"]) == ("cleaned", False) and legacy_unresolved.exists()
    _assert_guarded(harness)


def _killed_at(harness: LocalHarness, tmp_path: Path, point: str, *args: str) -> None:
    barrier = tmp_path / f"barrier-{point.replace(':', '-')}"
    process = harness.start(*args, extra_env=harness.paused_env(point, barrier))
    try:
        await_ready(barrier, process)
        os.kill(process.pid, signal.SIGKILL)
    finally:
        process.communicate()
    assert process.returncode == -signal.SIGKILL


def test_orphan_cleanup_beside_live_and_absent_database(tmp_path: Path) -> None:
    home, source, harness = _setup(tmp_path)
    _ok(harness.run("ops", "sqlite-init", "--repo-map-home", str(home), "--graph", GRAPH))
    assert _json(harness, home, "ops", "refresh-graph", "--graph", GRAPH)["accepted_generation"] == 1
    backup = tmp_path / "backup"
    _json(harness, home, "ops", "sqlite-backup", "--graph", GRAPH, "--output", str(backup))
    shutil.move(source, tmp_path / "sources-away")
    baseline = _mcp_state(harness, home)
    database = _database(home)
    remove_database(database)
    init = ("ops", "sqlite-init", "--repo-map-home", str(home), "--graph", GRAPH)
    restore = ("ops", "sqlite-restore", "--repo-map-home", str(home), "--graph", GRAPH, "--backup", str(backup))

    # 6-7: orphans beside an absent database.
    _killed_at(harness, tmp_path, "init:temporary-created", *init)
    partial = temp_orphans(database)
    assert [path.stat().st_size for path in partial] == [0], partial
    _killed_at(harness, tmp_path, "init:before-install", *init)
    _killed_at(harness, tmp_path, "restore:before-install", *restore)
    recoverable = [path for path in temp_orphans(database) if path not in partial]
    assert len(recoverable) == 2 and not os.path.lexists(database), temp_orphans(database)
    kept = {path: _sha(path) for path in recoverable}
    store = database.parent
    before = _tree(store)
    log = tmp_path / "sync.log"
    dry = _cleanup(harness, home, log)
    assert _tree(store) == before and _synced(log) == []
    assert (dry["final_database"], dry["orphans"]["partial_found"], dry["orphans"]["recoverable_preserved"]) == (
        "absent", 1, 2,
    ), dry
    absent = _cleanup(harness, home, log, "--yes")
    assert (absent["result"], absent["orphans"]["partial_removed"], absent["manual_recovery_required"]) == (
        "cleaned", 1, True,
    ), absent
    assert {"recoverable-orphan", "multiple-recoverable-orphans"} <= set(absent["warnings"]), absent
    assert not partial[0].exists() and {path: _sha(path) for path in recoverable} == kept
    assert not os.path.lexists(database), "cleanup never adopts an orphan"
    assert _readiness(harness, home) == ("not-initialized", None)

    # 5: a restore killed after its link leaves a live database with a second link.
    _killed_at(harness, tmp_path, "restore:installed", *restore)
    assert database.stat().st_nlink == 2
    assert _readiness(harness, home) == ("current", 1)
    live = (_sha(database), database.stat().st_ino)
    assert _mcp_state(harness, home) == baseline
    before = _tree(store, skip=(f"{GRAPH}.sqlite3-wal", f"{GRAPH}.sqlite3-shm"))
    stale = _cleanup(harness, home, tmp_path / "stale-dry.log")
    assert _tree(store, skip=(f"{GRAPH}.sqlite3-wal", f"{GRAPH}.sqlite3-shm")) == before
    assert (stale["final_database"], stale["orphans"]["stale_found"]) == ("current", 3), stale
    stale_log = tmp_path / "stale.log"
    removed = _cleanup(harness, home, stale_log, "--yes")
    assert (removed["result"], removed["orphans"]["stale_removed"]) == ("cleaned", 3), removed
    assert temp_orphans(database) == [] and (_sha(database), database.stat().st_ino) == live
    assert database.stat().st_nlink == 1
    resolved = home.resolve()
    assert _synced(stale_log) == [str(resolved / "state"), str(resolved)], _synced(stale_log)
    assert _mcp_state(harness, home) == baseline
    _assert_guarded(harness)
