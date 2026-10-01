"""SQLite Local graph locking across real processes and mixed operations (LOCAL10).

One disposable SQLite Local home per test. Lock children run the product
lock owner directly under the harness environment, synchronized by pipes: a
held graph lock refuses another process (mutation and dry-run probe alike),
another graph stays independent, and the operating system releases the lock
on normal exit, on SIGKILL, and never hands it to a child spawned under it.

Mixed operations run as guarded CLI children with the Psycopg family made
unavailable: a backup paused under its lock at ``backup:snapshot-complete``
makes refresh, upgrade, init and cleanup (dry run and ``--yes``) refuse
``graph-publication-in-progress``, and a restore paused at
``restore:before-install`` into an absent database makes init and cleanup
refuse. After release both finish, cleanup and refresh proceed, and MCP reads
return the same accepted state.

This is containerized integration evidence for the POSIX backend on the Linux
sandbox kernel. It is not native Windows, installed-wheel or timing evidence.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
from pathlib import Path
from typing import Any

from repomap_test_support.sqlite_local_fixtures import graph_toml, write_shell_source, write_sqlite_home
from repomap_test_support.sqlite_local_harness import (
    LocalHarness,
    await_ready,
    initialize,
    release,
    remove_database,
    structured,
    tool,
)
from repomap_test_support.sqlite_local_lock_children import (
    HOLD_AND_SPAWN,
    attempt,
    release_holder,
    start_holder,
)

GRAPH = "vault"
IN_PROGRESS = "graph-publication-in-progress"
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


def _setup(tmp_path: Path) -> tuple[Path, LocalHarness]:
    source = write_shell_source(tmp_path / "sources" / GRAPH)
    home = write_sqlite_home(tmp_path / "home", graph_toml(GRAPH, source) + graph_toml("other", source))
    return home, LocalHarness(tmp_path / "scratch", block_psycopg=True)


def _database(home: Path, graph: str = GRAPH) -> Path:
    return home / "state" / "sqlite-local" / "graphs" / f"{graph}.sqlite3"


def _json(harness: LocalHarness, home: Path, *args: str) -> dict[str, Any]:
    completed = harness.run(*args, "--repo-map-home", str(home), "--json")
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert isinstance(payload, dict)
    return payload


def _refused(harness: LocalHarness, home: Path, *args: str) -> None:
    completed = harness.run(*args, "--repo-map-home", str(home))
    assert completed.returncode == 1 and IN_PROGRESS in completed.stderr, (args, completed.stderr)
    assert str(home) not in completed.stderr, completed.stderr


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


def _paused(harness: LocalHarness, tmp_path: Path, point: str, *args: str) -> tuple[subprocess.Popen[str], Path]:
    barrier = tmp_path / f"barrier-{point.replace(':', '-')}"
    process = harness.start(*args, "--json", extra_env=harness.paused_env(point, barrier))
    await_ready(barrier, process)
    return process, barrier


def _released(process: subprocess.Popen[str], barrier: Path) -> dict[str, Any]:
    release(barrier)
    stdout, stderr = process.communicate(timeout=300)
    assert process.returncode == 0, stderr
    payload = json.loads(stdout)
    assert isinstance(payload, dict)
    return payload


def test_graph_lock_is_interprocess_and_released_by_exit_and_kill(tmp_path: Path) -> None:
    home, harness = _setup(tmp_path)
    for graph in (GRAPH, "other"):
        assert _json(harness, home, "ops", "sqlite-init", "--graph", graph)["result"] == "initialized"
    env = harness.environment()
    one, two = _database(home), _database(home, "other")

    holder, ready = start_holder(one, env)
    assert ready == "ready"
    assert attempt(one, env) == IN_PROGRESS
    assert attempt(one, env, "probe") == IN_PROGRESS
    assert attempt(two, env) == "acquired", "another graph's lock is independent"
    assert release_holder(holder) == 0
    assert attempt(one, env) == "acquired" and attempt(one, env, "probe") == "probed"

    killed, _ = start_holder(one, env)
    assert attempt(one, env) == IN_PROGRESS
    killed.send_signal(signal.SIGKILL)
    killed.communicate(timeout=120)
    assert killed.returncode == -signal.SIGKILL
    assert attempt(one, env) == "acquired", "the OS released the killed holder's lock"

    keep_read, keep_write = os.pipe()
    try:
        spawner, ready = start_holder(one, env, HOLD_AND_SPAWN, keep_open=keep_read)
        grandchild = int(ready.split()[1])
        assert attempt(one, env) == IN_PROGRESS
        assert release_holder(spawner) == 0
        os.kill(grandchild, 0)
        assert attempt(one, env) == "acquired", "a child spawned under the lock does not keep it"
    finally:
        os.close(keep_write)
        os.close(keep_read)
    assert harness.forbidden_events() == [], harness.forbidden_events()


def test_mixed_operations_serialize_on_one_graph_lock(tmp_path: Path) -> None:
    home, harness = _setup(tmp_path)
    assert _json(harness, home, "ops", "sqlite-init", "--graph", GRAPH)["result"] == "initialized"
    assert _json(harness, home, "ops", "refresh-graph", "--graph", GRAPH)["accepted_generation"] == 1
    baseline = _mcp_state(harness, home)
    graph = ("--graph", GRAPH)

    backup = tmp_path / "backup"
    process, barrier = _paused(
        harness, tmp_path, "backup:snapshot-complete",
        "ops", "sqlite-backup", "--repo-map-home", str(home), *graph, "--output", str(backup),
    )
    try:
        _refused(harness, home, "ops", "refresh-graph", *graph)
        _refused(harness, home, "ops", "sqlite-upgrade", *graph, "--backup-output", str(tmp_path / "upgrade"))
        _refused(harness, home, "ops", "sqlite-init", *graph)
        _refused(harness, home, "ops", "sqlite-cleanup", *graph)
        _refused(harness, home, "ops", "sqlite-cleanup", *graph, "--yes")
        assert _mcp_state(harness, home) == baseline, "reads never take the graph lock"
    finally:
        created = _released(process, barrier)
    assert (created["result"], created["accepted_generation"]) == ("created", 1), created
    assert not (tmp_path / "upgrade").exists()

    remove_database(_database(home))
    process, barrier = _paused(
        harness, tmp_path, "restore:before-install",
        "ops", "sqlite-restore", "--repo-map-home", str(home), *graph, "--backup", str(backup),
    )
    try:
        _refused(harness, home, "ops", "sqlite-init", *graph)
        _refused(harness, home, "ops", "sqlite-cleanup", *graph, "--yes")
        assert not os.path.lexists(_database(home)), "a refused init never created the database"
    finally:
        restored = _released(process, barrier)
    assert (restored["result"], restored["accepted_generation"]) == ("restored", 1), restored

    assert _mcp_state(harness, home) == baseline
    assert _json(harness, home, "ops", "sqlite-cleanup", *graph, "--yes")["result"] == "cleaned"
    assert _json(harness, home, "ops", "refresh-graph", *graph)["accepted_generation"] == 2
    assert harness.forbidden_events() == [], harness.forbidden_events()
    assert harness.shim_invocations() == "", harness.shim_invocations()
    loaded = harness.imported_modules() & POSTGRES_IMPLEMENTATION
    assert not loaded, f"SQLite children loaded PostgreSQL implementation modules: {sorted(loaded)}"
