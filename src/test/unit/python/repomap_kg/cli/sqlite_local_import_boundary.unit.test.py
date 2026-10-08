"""SQLite Local startup without the PostgreSQL driver (LOCAL6).

Guarded CLI children run with the Psycopg family made genuinely unavailable
(no stand-in module). A canary proves the blocker fails a real import that
succeeds without it, and a PostgreSQL-home command proves the blocker engages
on the real PostgreSQL path with the bounded ``postgresql-driver-unavailable``
exit. SQLite-only commands (including ``--version`` and, since LOCAL7, an
unpublished ``sqlite-backup``/``sqlite-restore`` round trip and, since LOCAL8,
a no-op and a real v1 -> v2 ``sqlite-upgrade``, and since LOCAL9 a dry-run
and a ``--yes`` ``sqlite-cleanup``) record no blocked import and never load the
PostgreSQL-implementation modules. ``coordinator.client`` is psycopg-free and
eagerly reachable, so it is information only; the coordinator refusal proof is
that ``coordinator.local_mode`` never loads. Direct ``refresh-graph`` and
``refresh-enabled`` under the blocker are owned by the containerized
operator-workflow integration owner (they launch the real worker).
"""

from __future__ import annotations

import inspect
import json
import subprocess
import sys
from pathlib import Path

import pytest

from repomap_kg import cli
from repomap_kg.cli import _postgres_facade
from repomap_kg.coordinator import local_mode
from repomap_kg.ops import refresh as ops_refresh
from repomap_test_support import sqlite_local_guard
from repomap_test_support.host_read_store_config import setup_owned_config
from repomap_test_support.sqlite_local_fixtures import graph_toml, write_shell_source, write_sqlite_home
from repomap_test_support.sqlite_local_harness import LocalHarness, initialize, remove_database, tool

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


def _home(tmp_path: Path) -> Path:
    source = write_shell_source(tmp_path / "src")
    return write_sqlite_home(tmp_path / "home", graph_toml("zulu", source) + graph_toml("mike", source, enabled=False))


def _assert_driver_free(harness: LocalHarness, completed: subprocess.CompletedProcess[str]) -> None:
    assert completed.returncode == 0, completed.stderr
    assert harness.forbidden_events() == [], harness.forbidden_events()
    loaded = harness.imported_modules() & POSTGRES_IMPLEMENTATION
    assert not loaded, f"SQLite-only child loaded PostgreSQL implementation modules: {sorted(loaded)}"


def test_canary_blocker_fails_a_real_psycopg_import(tmp_path: Path) -> None:
    harness = LocalHarness(tmp_path / "canary", block_psycopg=True)
    env = harness.environment()
    unblocked = subprocess.run(
        [sys.executable, "-c", "import psycopg"], env=env, capture_output=True, text=True, check=False
    )
    assert unblocked.returncode == 0, f"the driver must be installed for the canary: {unblocked.stderr}"
    code = (
        "import runpy, sys\n"
        f"guard = runpy.run_path({str(Path(sqlite_local_guard.__file__))!r})\n"
        "guard['_install_psycopg_blocker']()\n"
        "import psycopg\n"
    )
    blocked = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=False)
    assert blocked.returncode != 0 and "ModuleNotFoundError" in blocked.stderr, blocked.stderr
    kinds = {(event["kind"], event["detail"]) for event in harness.guard_events()}
    assert ("import-blocked", "psycopg") in kinds, kinds


def test_postgres_home_reports_the_bounded_missing_driver_error(tmp_path: Path) -> None:
    harness = LocalHarness(tmp_path / "pg-scratch", block_psycopg=True)
    home = tmp_path / "pg"
    home.mkdir()
    (home / "repomap.rpl.toml").write_text(setup_owned_config(), encoding="utf-8")
    completed = harness.run("ops", "config-check", "--repo-map-home", str(home), "--json")
    assert completed.returncode == 1, completed.stderr
    assert "postgresql-driver-unavailable" in completed.stderr, completed.stderr
    assert "Traceback" not in completed.stderr, completed.stderr
    assert any(event["kind"] == "import-blocked" for event in harness.guard_events()), harness.guard_events()


def test_help_and_local_status_commands_start_without_the_driver(tmp_path: Path) -> None:
    harness = LocalHarness(tmp_path / "scratch", block_psycopg=True)
    home = _home(tmp_path)
    _assert_driver_free(harness, harness.run("--help"))
    version = harness.run("--version")
    _assert_driver_free(harness, version)
    assert version.stdout.startswith("repomap-kg "), version.stdout
    for args in (
        ("ops", "config-check"),
        ("ops", "graphs"),
        ("ops", "config-check", "--check-db"),
        ("ops", "sqlite-init", "--graph", "zulu"),
        ("ops", "graphs", "--check-db"),
        ("ops", "refresh-preflight", "--graph", "zulu"),
        ("ops", "sqlite-backup", "--graph", "zulu", "--output", str(tmp_path / "backup")),
    ):
        completed = harness.run(*args, "--repo-map-home", str(home), "--json")
        _assert_driver_free(harness, completed)
        assert json.loads(completed.stdout), args
    remove_database(home / "state" / "sqlite-local" / "graphs" / "zulu.sqlite3")
    restored = harness.run(
        "ops", "sqlite-restore", "--repo-map-home", str(home), "--graph", "zulu",
        "--backup", str(tmp_path / "backup"), "--json",
    )
    _assert_driver_free(harness, restored)
    assert json.loads(restored.stdout)["result"] == "restored", restored.stdout
    upgrade = ("ops", "sqlite-upgrade", "--repo-map-home", str(home), "--graph", "zulu", "--json")
    noop = harness.run(*upgrade, "--backup-output", str(tmp_path / "unused"))
    _assert_driver_free(harness, noop)
    assert json.loads(noop.stdout)["result"] == "already-current", noop.stdout
    assert not (tmp_path / "unused").exists()
    remove_database(home / "state" / "sqlite-local" / "graphs" / "zulu.sqlite3")
    historical = harness.run(
        "ops", "sqlite-init", "--repo-map-home", str(home), "--graph", "zulu", extra_env=harness.ceiling_env(1)
    )
    _assert_driver_free(harness, historical)
    upgraded = harness.run(*upgrade, "--backup-output", str(tmp_path / "pre-upgrade"))
    _assert_driver_free(harness, upgraded)
    assert (json.loads(upgraded.stdout)["result"], json.loads(upgraded.stdout)["from_schema_version"]) == (
        "upgraded", 1,
    ), upgraded.stdout
    cleanup = ("ops", "sqlite-cleanup", "--repo-map-home", str(home), "--graph", "zulu", "--json")
    for extra, result in (((), "dry-run"), (("--yes",), "cleaned")):
        cleaned = harness.run(*cleanup, *extra)
        _assert_driver_free(harness, cleaned)
        assert json.loads(cleaned.stdout)["result"] == result, cleaned.stdout
    assert not (home / "state" / "sqlite-local" / "graphs" / "mike.sqlite3").exists()


def test_mcp_serve_reads_a_sqlite_home_without_the_driver(tmp_path: Path) -> None:
    harness = LocalHarness(tmp_path / "scratch", block_psycopg=True)
    home = _home(tmp_path)
    _assert_driver_free(harness, harness.run("ops", "sqlite-init", "--repo-map-home", str(home), "--graph", "zulu"))
    responses = harness.mcp(home, [initialize(), tool(2, "repomap_graph_status", {"graph_id": "zulu"})])
    assert responses[1]["result"]["serverInfo"]["name"] == "repomap-kg", responses[1]
    assert "result" in responses[2], responses[2]
    assert harness.forbidden_events() == [], harness.forbidden_events()
    assert not harness.imported_modules() & POSTGRES_IMPLEMENTATION, harness.imported_modules()


@pytest.mark.parametrize("key", ((), ("--idempotency-key", "local6-key")))
def test_coordinator_refusal_never_loads_the_coordinator(tmp_path: Path, key: tuple[str, ...]) -> None:
    harness = LocalHarness(tmp_path / "scratch", block_psycopg=True)
    home = _home(tmp_path)
    completed = harness.run(
        "ops", "refresh-graph", "--repo-map-home", str(home), "--graph", "zulu", "--mode", "coordinator", *key
    )
    assert completed.returncode == 1, completed.stderr
    assert "sqlite-local-refresh-rejects-coordinator-mode" in completed.stderr, completed.stderr
    assert harness.forbidden_events() == [], harness.forbidden_events()
    assert "repomap_kg.coordinator.local_mode" not in harness.imported_modules(), harness.imported_modules()
    assert not (home / "state").exists(), "coordinator refusal touched the store"


def test_facade_names_resolve_to_their_source_objects(monkeypatch: pytest.MonkeyPatch) -> None:
    main_module = inspect.getmodule(cli.main)
    assert main_module is not None and main_module.__name__ == "repomap_kg.cli.main"
    for name in sorted(_postgres_facade.POSTGRES_FACADE_NAMES):
        source = _postgres_facade.load_postgres_facade_name(name)
        assert getattr(cli, name) is source, name
        assert getattr(main_module, name) is source, name
        assert name in dir(cli) and name in dir(main_module), name
    assert cli.refresh_graph is ops_refresh.refresh_graph
    assert cli.run_coordinator_refresh is local_mode.run_coordinator_refresh
    assert cli.main is main_module.main
    with pytest.raises(AttributeError):
        getattr(cli, "not_a_facade_name")

    def double(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(cli, "refresh_graph", double)
    patched: object = cli.refresh_graph
    assert patched is double
    monkeypatch.undo()
    restored: object = cli.refresh_graph
    assert restored is ops_refresh.refresh_graph, "a facade patch leaked past undo"
