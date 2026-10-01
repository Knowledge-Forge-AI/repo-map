"""SQLite Local ``ops sqlite-cleanup`` routing, exit codes and path-free output (LOCAL9).

In-process CLI over temporary SQLite homes. A PostgreSQL home refuses
``sqlite-local-home-required`` before any action; an unknown graph refuses
without a payload. The dry run (the default) and a clean ``--yes`` exit 0; a
``refused`` or ``incomplete`` cleanup prints its payload and exits 1. The JSON
and text outcomes carry no path. No PostgreSQL command, source capture or
worker is ever reached.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from repomap_kg import cli
from repomap_kg.cli.main import build_parser
from repomap_kg.ops import local_refresh, portable_refresh
from repomap_kg.ops.config_local import LocalSqliteConfig, load_graph_registry_config_home
from repomap_kg.storage.sqlite_local import durability
from repomap_kg.storage.sqlite_local.durability import DURABILITY_UNAVAILABLE
from repomap_kg.storage.sqlite_local.schema import LocalStoreError
from repomap_test_support.cli_in_process import run_repo_map_in_process
from repomap_test_support.host_read_store_config import fail_if_reached, setup_owned_config
from repomap_test_support.sqlite_local_fixtures import graph_toml, write_shell_source, write_sqlite_home

PG_NAMES = ("refresh_graph", "refresh_enabled_graphs", "load_ops_config_home", "maintenance_activity_for_home")
CLEANUP_KEYS = {
    "command", "storage_backend", "graph_id", "result", "dry_run", "changed", "final_database",
    "graph_attempts", "legacy_shared_attempts", "orphans", "durability", "manual_recovery_required",
    "warning_count", "warnings", "refusal_count", "refusals", "failures",
}


@pytest.fixture(autouse=True)
def _source_blind() -> Iterator[None]:
    patches = [patch.object(cli, name, fail_if_reached) for name in PG_NAMES] + [
        patch.object(local_refresh, "capture_portable_candidate", fail_if_reached),
        patch.object(portable_refresh, "run_portable_worker", fail_if_reached),
    ]
    for item in patches:
        item.start()
    try:
        yield
    finally:
        for item in patches:
            item.stop()


def _home(tmp_path: Path) -> Path:
    home = write_sqlite_home(tmp_path / "home", graph_toml("zulu", write_shell_source(tmp_path / "src")))
    config = load_graph_registry_config_home(home)
    assert isinstance(config, LocalSqliteConfig)
    assert local_refresh.initialize_local_graph(config, "zulu")["result"] == "initialized"
    return home


def _orphan(home: Path, name: str = ".zulu.sqlite3.init-0123456789abcdef") -> Path:
    path = home / "state" / "sqlite-local" / "graphs" / name
    path.write_bytes(b"")
    path.chmod(0o600)
    return path


def _run(home: Path, *args: str) -> tuple[int, str, str]:
    return run_repo_map_in_process("ops", "sqlite-cleanup", "--repo-map-home", str(home), "--graph", "zulu", *args)


def test_parser_defaults_to_a_dry_run() -> None:
    parser = build_parser()
    dry = parser.parse_args(["ops", "sqlite-cleanup", "--repo-map-home", "h", "--graph", "g"])
    assert (dry.ops_command, dry.graph, dry.yes, dry.json) == ("sqlite-cleanup", "g", False, False)
    execute = parser.parse_args(["ops", "sqlite-cleanup", "--graph", "g", "--yes", "--json"])
    assert (execute.yes, execute.json) == (True, True)


def test_dry_run_then_yes_exit_zero_with_path_free_output(tmp_path: Path) -> None:
    home = _home(tmp_path)
    orphan = _orphan(home)
    code, stdout, stderr = _run(home, "--json")
    assert (code, stderr) == (0, ""), stderr
    dry = json.loads(stdout)
    assert set(dry) == CLEANUP_KEYS and str(tmp_path) not in stdout and orphan.name not in stdout, dry
    assert (dry["result"], dry["orphans"]["stale_found"]) == ("dry-run", 1) and orphan.exists()
    code, stdout, _ = _run(home)
    assert (code, stdout.strip()) == (
        0, "sqlite-cleanup zulu: dry-run (removed 0, durability not-attempted, warnings 0, refusals 0)",
    )
    code, stdout, stderr = _run(home, "--yes")
    assert (code, stdout.strip()) == (
        0, "sqlite-cleanup zulu: cleaned (removed 1, durability established, warnings 0, refusals 0)",
    ), stderr
    assert not orphan.exists()


def test_refused_and_incomplete_cleanups_exit_one_with_their_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _home(tmp_path)
    unsafe = _orphan(home)
    unsafe.chmod(0o644)
    code, stdout, stderr = _run(home, "--yes", "--json")
    refused = json.loads(stdout)
    assert (code, refused["result"], refused["refusals"], stderr) == (1, "refused", ["unsafe-orphan"], ""), refused
    assert unsafe.exists() and str(tmp_path) not in stdout
    unsafe.chmod(0o600)

    def unavailable(_path: Path) -> None:
        raise LocalStoreError(DURABILITY_UNAVAILABLE, "directory sync is not supported")

    monkeypatch.setattr(durability, "fsync_directory", unavailable)
    code, stdout, _ = _run(home, "--yes")
    assert (code, stdout.strip()) == (
        1, "sqlite-cleanup zulu: incomplete (removed 1, durability local-durability-unavailable, "
        "warnings 0, refusals 0)",
    )
    assert not unsafe.exists()


def test_postgres_home_and_unknown_graph_refuse_before_any_action(tmp_path: Path) -> None:
    pg = tmp_path / "pg"
    pg.mkdir()
    (pg / "repomap.rpl.toml").write_text(setup_owned_config(), encoding="utf-8")
    before = sorted(path.name for path in pg.rglob("*"))
    code, stdout, stderr = run_repo_map_in_process(
        "ops", "sqlite-cleanup", "--repo-map-home", str(pg), "--graph", "host-one", "--yes"
    )
    assert (code, stdout) == (1, "") and "sqlite-local-home-required" in stderr, stderr
    assert sorted(path.name for path in pg.rglob("*")) == before
    home = _home(tmp_path)
    code, stdout, stderr = run_repo_map_in_process(
        "ops", "sqlite-cleanup", "--repo-map-home", str(home), "--graph", "nope", "--yes"
    )
    assert (code, stdout, stderr.strip()) == (1, "", "ERROR: unknown graph_id: nope")


def test_layout_refusal_is_a_bounded_error_without_a_payload(tmp_path: Path) -> None:
    home = _home(tmp_path)
    graphs = home / "state" / "sqlite-local" / "graphs"
    moved = tmp_path / "moved-graphs"
    graphs.rename(moved)
    graphs.symlink_to(moved)
    before = sorted(os.listdir(moved))
    code, stdout, stderr = _run(home, "--yes", "--json")
    assert (code, stdout) == (1, "")
    assert stderr.strip() == "ERROR: sqlite-cleanup-layout-invalid: a Local state level is not a private directory"
    assert sorted(os.listdir(moved)) == before
