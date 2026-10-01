"""SQLite Local ``ops config-check`` and ``ops graphs`` through the CLI (LOCAL6).

Both commands share the PostgreSQL envelope and add only SQLite storage keys;
PostgreSQL keys are absent. Without ``--check-db`` nothing opens a database
or reads a graph root; with it, per-graph state comes from the one read-only
readiness owner and no store is created. PostgreSQL loaders, probes and
admission are tripwired; a PostgreSQL home falls through unchanged.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from repomap_kg import cli
from repomap_kg.cli import _ops_sqlite_dispatch
from repomap_kg.ops import local_readiness
from repomap_kg.ops.config_local import LocalSqliteConfig, load_graph_registry_config_home, local_graph_binding
from repomap_kg.ops.local_refresh import initialize_local_graph
from repomap_kg.storage.sqlite_local.publisher import publish_generation
from repomap_test_support.cli_in_process import run_repo_map_in_process
from repomap_test_support.host_read_store_config import fail_if_reached, setup_owned_config
from repomap_test_support.sqlite_local_fixtures import (
    generation_bundle,
    graph_toml,
    publication_for,
    sqlite_home_toml,
    write_sqlite_home,
)

PG_NAMES = (
    "check_ops_postgres_status",
    "check_ops_graph_storage_status",
    "load_ops_config_home",
    "load_ops_config",
    "maintenance_activity_for_home",
    "run_coordinator_refresh",
)
PG_KEYS = {"postgres", "runtime", "postgres_status"}


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
    source = tmp_path / "src"
    source.mkdir()
    return write_sqlite_home(
        tmp_path / "home",
        graph_toml("zulu", source)
        + graph_toml("vault", tmp_path / "never-created", privacy="private-ops", visible=False)
        + graph_toml("off", source, enabled=False),
    )


def _json(*args: str) -> dict[str, Any]:
    code, stdout, stderr = run_repo_map_in_process(*args, "--json")
    assert code == 0, stderr
    payload = json.loads(stdout)
    assert isinstance(payload, dict)
    return payload


def _publish_zulu(home: Path) -> None:
    config = load_graph_registry_config_home(home)
    assert isinstance(config, LocalSqliteConfig)
    initialize_local_graph(config, "zulu")
    bundle = generation_bundle(1)
    publication = replace(publication_for(bundle, "zulu"), binding=local_graph_binding(config.graphs[0]))
    publish_generation(
        config.graph_store_root / "zulu.sqlite3", publication, bundle.families, expected_generation=0
    )


def test_config_check_base_form_opens_nothing_and_invents_no_postgres(
    tmp_path: Path, pg_tripwires: None
) -> None:
    home = _home(tmp_path)
    with patch.object(local_readiness, "read_transaction", fail_if_reached):
        payload = _json("ops", "config-check", "--repo-map-home", str(home))
    assert payload["valid"] is True and payload["storage"] == {"backend": "sqlite"}, payload
    assert payload["storage_status"] == {"backend": "sqlite", "db_checked": False}, payload
    assert not PG_KEYS & set(payload), "SQLite config-check invented PostgreSQL keys"
    assert payload["config_path"] == payload["config_home"] == "[local-config]"
    assert [graph["id"] for graph in payload["graphs"]] == ["zulu", "vault", "off"]
    assert payload["graph_counts"] == {"total": 3, "enabled": 2, "private_enabled": 1}
    # Public graph roots are displayed by the shared contract; home, config and
    # database paths never are.
    assert str(home) not in json.dumps(payload), "a home or database path leaked into config-check"
    assert not (home / "state").exists(), "config-check created the store"


def test_check_db_reports_states_without_creating_then_after_publication(
    tmp_path: Path, pg_tripwires: None
) -> None:
    home = _home(tmp_path)
    before = _json("ops", "config-check", "--repo-map-home", str(home), "--check-db")["storage_status"]
    assert before["db_checked"] is True and before["state_counts"] == {"not-initialized": 3}, before
    assert not (home / "state").exists(), "--check-db created the store"
    _publish_zulu(home)
    after = _json("ops", "config-check", "--repo-map-home", str(home), "--check-db")["storage_status"]
    assert [(item["graph_id"], item["state"], item["accepted_generation"]) for item in after["graphs"]] == [
        ("zulu", "current", 1), ("vault", "not-initialized", None), ("off", "not-initialized", None),
    ], after
    assert str(home) not in json.dumps(after), "a home or database path leaked into storage status"


def test_graphs_projects_redacted_sqlite_rows_in_configuration_order(
    tmp_path: Path, pg_tripwires: None
) -> None:
    home = _home(tmp_path)
    with patch.object(local_readiness, "read_transaction", fail_if_reached):
        unchecked = _json("ops", "graphs", "--repo-map-home", str(home))
    assert unchecked["db_checked"] is False and unchecked["storage"] == {"backend": "sqlite"}
    rows = {row["id"]: row for row in unchecked["graphs"]}
    assert list(rows) == ["zulu", "vault", "off"]
    assert rows["zulu"]["database"] == "[graph-database]"
    assert rows["vault"]["database"] == "[private-database]"
    assert rows["vault"]["root_path_display"] == "[private-root]"
    assert {row["database_source"] for row in rows.values()} == {"sqlite-graph-file"}
    assert {row["storage_status"] for row in rows.values()} == {None}
    assert rows["zulu"]["root_path_checked"] is False
    _publish_zulu(home)
    checked = _json("ops", "graphs", "--repo-map-home", str(home), "--check-db")
    states = [row["storage_status"]["state"] for row in checked["graphs"]]
    assert checked["db_checked"] is True and states == ["current", "not-initialized", "not-initialized"]
    assert str(home) not in json.dumps(checked), "a home or database path leaked into graphs"
    assert str(tmp_path / "never-created") not in json.dumps(checked), "a private root leaked"


def test_tables_name_the_sqlite_backend(tmp_path: Path, pg_tripwires: None) -> None:
    home = _home(tmp_path)
    _publish_zulu(home)
    code, stdout, stderr = run_repo_map_in_process("ops", "graphs", "--repo-map-home", str(home), "--check-db")
    assert code == 0 and "storage=sqlite" in stdout and "current(generation=1)" in stdout, stderr + stdout
    code, stdout, stderr = run_repo_map_in_process("ops", "config-check", "--repo-map-home", str(home))
    assert code == 0 and "storage: backend=sqlite db_checked=false" in stdout, stderr + stdout
    assert "postgres:" not in stdout and "runtime:" not in stdout, stdout


@pytest.mark.parametrize("command", ("config-check", "graphs"))
def test_psql_command_is_refused_before_config_parse(
    tmp_path: Path, command: str, pg_tripwires: None
) -> None:
    home = _home(tmp_path)
    with patch.object(_ops_sqlite_dispatch, "load_graph_registry_config_home", fail_if_reached):
        code, _, stderr = run_repo_map_in_process(
            "ops", command, "--repo-map-home", str(home), "--psql-command", "psql"
        )
    assert code == 1 and "sqlite-local-rejects-psql-command" in stderr, stderr


@pytest.mark.parametrize("command", ("config-check", "graphs"))
def test_sqlite_home_config_errors_are_reported_directly(
    tmp_path: Path, command: str, pg_tripwires: None
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / "repomap.rp.toml").write_text(
        sqlite_home_toml('[postgres]\nhost = "h"\n' + graph_toml("one", tmp_path)), encoding="utf-8"
    )
    code, _, stderr = run_repo_map_in_process("ops", command, "--repo-map-home", str(home))
    assert code == 1 and "PostgreSQL-only and are not allowed" in stderr, stderr
    assert "requires-local-command" not in stderr, stderr


def test_postgres_home_keeps_the_postgres_projection(tmp_path: Path) -> None:
    home = tmp_path / "pg"
    home.mkdir()
    (home / "repomap.rpl.toml").write_text(setup_owned_config(), encoding="utf-8")
    with patch.object(_ops_sqlite_dispatch, "probe_local_graphs", fail_if_reached):
        payload = _json("ops", "config-check", "--repo-map-home", str(home))
    assert PG_KEYS <= set(payload) and "storage" not in payload, sorted(payload)
    assert payload["postgres_status"]["db_checked"] is False
