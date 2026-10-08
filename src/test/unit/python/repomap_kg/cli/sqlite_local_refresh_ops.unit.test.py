"""SQLite Local ``refresh-preflight``, ``refresh-enabled`` routing and coordinator refusal (LOCAL6).

Preflight reuses the maintained owner with real source scans and never opens
a database or launches a worker. ``refresh-enabled`` routes to the Local
aggregation, never to the PostgreSQL owner or maintenance admission.
``refresh-graph --mode coordinator`` on a SQLite home is refused after backend
selection and before config parse, database open, capture, worker launch or
any coordinator call, with or without an idempotency key.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from repomap_kg import cli
from repomap_kg.cli import _ops_sqlite_dispatch
from repomap_kg.ops import local_refresh, local_refresh_enabled, portable_refresh
from repomap_kg.ops.local_refresh import LocalRefreshError, LocalRefreshResult
from repomap_kg.storage.sqlite_local import connection
from repomap_test_support.cli_in_process import run_repo_map_in_process
from repomap_test_support.host_read_store_config import fail_if_reached, setup_owned_config
from repomap_test_support.sqlite_local_fixtures import (
    graph_toml,
    multi_graph_toml,
    write_shell_source,
    write_sqlite_home,
)

PG_NAMES = (
    "refresh_enabled_graphs",
    "refresh_graph",
    "preflight_graph",
    "maintenance_activity_for_home",
    "run_coordinator_refresh",
    "load_ops_config_home",
)


@pytest.fixture
def pg_tripwires() -> Iterator[None]:
    patches = [patch.object(cli, name, fail_if_reached) for name in PG_NAMES]
    for item in patches:
        item.start()
    try:
        yield
    finally:
        for item in patches:
            item.stop()


def _home(tmp_path: Path) -> Path:
    one = write_shell_source(tmp_path / "src-one")
    left = write_shell_source(tmp_path / "src-left")
    right = write_shell_source(tmp_path / "src-right")
    return write_sqlite_home(
        tmp_path / "home",
        graph_toml("zulu", one)
        + multi_graph_toml("alpha", [("left", left), ("right", right)]).replace(
            "mcp_visible = true", "mcp_visible = false"
        )
        + graph_toml("vault", one, privacy="private-ops")
        + graph_toml("off", one, enabled=False),
    )


def _cli(*args: str) -> tuple[int, str, str]:
    with patch.object(connection, "read_transaction", fail_if_reached), patch.object(
        local_refresh, "capture_portable_candidate", fail_if_reached
    ), patch.object(portable_refresh, "run_portable_worker", fail_if_reached):
        return run_repo_map_in_process(*args)


def _preflight(home: Path, graph: str) -> tuple[int, dict[str, Any], str]:
    code, stdout, stderr = _cli("ops", "refresh-preflight", "--repo-map-home", str(home), "--graph", graph, "--json")
    return code, (json.loads(stdout) if stdout.strip() else {}), stderr


@pytest.mark.parametrize(
    ("graph", "root_display", "files"),
    (("zulu", None, 2), ("alpha", "[multi-source]", 4), ("vault", "[private-root]", 2)),
)
def test_preflight_scans_sources_without_storage(
    tmp_path: Path, graph: str, root_display: str | None, files: int, pg_tripwires: None
) -> None:
    home = _home(tmp_path)
    code, payload, stderr = _preflight(home, graph)
    assert code == 0 and payload["result"] == "success", stderr
    row = payload["graph"]
    assert row["files_included"] == files, row
    assert row["database"] == "[graph-database]", row
    if root_display is not None:
        assert row["root_path_display"] == root_display, row
    assert payload["safety"]["storage_written"] is False, payload["safety"]
    assert not (home / "state").exists(), "preflight created the SQLite store"


@pytest.mark.parametrize(("graph", "text"), (("off", "is disabled"), ("nope", "is not configured")))
def test_preflight_refuses_disabled_and_unknown_graphs(
    tmp_path: Path, graph: str, text: str, pg_tripwires: None
) -> None:
    code, _, stderr = _preflight(_home(tmp_path), graph)
    assert code == 1 and text in stderr, stderr


def _result(graph_id: str, generation: int, *, reconciled: bool = False) -> LocalRefreshResult:
    return LocalRefreshResult(
        graph_id, generation, generation, None, {"publication_bundle_id": f"bundle1:{graph_id}"},
        {"files": 2}, reconciled=reconciled,
    )


def test_refresh_enabled_routes_to_the_local_aggregation(tmp_path: Path, pg_tripwires: None) -> None:
    home = _home(tmp_path)
    calls: list[str] = []

    def refresh(_config: object, graph_id: str) -> LocalRefreshResult:
        calls.append(graph_id)
        return _result(graph_id, 1, reconciled=graph_id == "alpha")

    with patch.object(local_refresh_enabled, "refresh_local_graph", refresh):
        code, stdout, stderr = _cli("ops", "refresh-enabled", "--repo-map-home", str(home), "--json")
    assert code == 0, stderr
    assert calls == ["zulu", "alpha", "vault"], calls
    payload = json.loads(stdout)
    assert payload["result"] == "success" and payload["storage_backend"] == "sqlite", payload
    assert [row["graph_id"] for row in payload["graphs"]] == calls
    assert "NOTE: sqlite-local-attempt-reconciled" in stderr and "(graph alpha)" in stderr, stderr


def test_refresh_enabled_mixed_result_exits_nonzero(tmp_path: Path, pg_tripwires: None) -> None:
    home = _home(tmp_path)

    def refresh(_config: object, graph_id: str) -> LocalRefreshResult:
        if graph_id == "alpha":
            raise LocalRefreshError("graph 'alpha' source root is unavailable")
        return _result(graph_id, 2)

    with patch.object(local_refresh_enabled, "refresh_local_graph", refresh):
        code, stdout, stderr = _cli("ops", "refresh-enabled", "--repo-map-home", str(home))
    assert code == 1, stderr
    assert "result=partial" in stdout and "alpha | failure | - | refresh-rejected" in stdout, stdout


def test_refresh_enabled_refuses_psql_command(tmp_path: Path, pg_tripwires: None) -> None:
    home = _home(tmp_path)
    with patch.object(local_refresh_enabled, "refresh_local_graph", fail_if_reached):
        code, _, stderr = _cli("ops", "refresh-enabled", "--repo-map-home", str(home), "--psql-command", "psql")
    assert code == 1 and "sqlite-local-refresh-rejects-psql-command" in stderr, stderr


@pytest.mark.parametrize("key", ((), ("--idempotency-key", "local6-key")))
@pytest.mark.parametrize("selector", ("home", "file"))
def test_coordinator_mode_is_refused_before_any_side_effect(
    tmp_path: Path, key: tuple[str, ...], selector: str, pg_tripwires: None
) -> None:
    home = _home(tmp_path)
    target = ("--repo-map-home", str(home)) if selector == "home" else ("--config", str(home / "repomap.rp.toml"))
    with patch.object(_ops_sqlite_dispatch, "load_graph_registry_config_home", fail_if_reached), patch.object(
        _ops_sqlite_dispatch, "load_graph_registry_config", fail_if_reached
    ), patch.object(_ops_sqlite_dispatch, "refresh_local_graph", fail_if_reached), patch.object(
        connection, "publisher_lock", fail_if_reached
    ), patch.object(sqlite3, "connect", fail_if_reached):
        code, stdout, stderr = _cli(
            "ops", "refresh-graph", *target, "--graph", "zulu", "--mode", "coordinator", *key
        )
    assert code == 1 and stdout == "", stdout
    assert "sqlite-local-refresh-rejects-coordinator-mode" in stderr, stderr
    assert not (home / "state").exists(), "coordinator refusal touched the store"


def test_postgres_coordinator_refusal_order_is_unchanged(tmp_path: Path) -> None:
    home = tmp_path / "pg"
    home.mkdir()
    (home / "repomap.rpl.toml").write_text(setup_owned_config(), encoding="utf-8")
    with patch.object(cli, "run_coordinator_refresh", fail_if_reached):
        code, _, stderr = run_repo_map_in_process(
            "ops", "refresh-graph", "--repo-map-home", str(home), "--graph", "host-one", "--mode", "coordinator"
        )
    assert code == 1 and "coordinator_requires_idempotency_key" in stderr, stderr
