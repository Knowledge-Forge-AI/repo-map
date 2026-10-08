"""Read-only SQLite Local readiness for ``config-check``/``graphs --check-db`` (LOCAL6).

Real temporary SQLite databases. The probe distinguishes absent, current
(unpublished or published), unrecognized and unavailable stores; it never
creates the store directory, a database, a lock or an ``.init-*`` file, never
enters the writer paths, and leaves the main database bytes unchanged (an
existing WAL database may keep only its own ``-wal``/``-shm`` sidecars).
LOCAL8: an exact-behind (historical v1) database is ``schema-behind`` with its
accepted generation and is never migrated by the probe; a drifted one is
``unrecognized``.
"""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from repomap_kg.ops import local_readiness
from repomap_kg.ops.config_local import (
    SQLITE_DATABASE_SOURCE,
    SQLITE_GRAPH_DATABASE_DISPLAY,
    LocalSqliteConfig,
    load_graph_registry_config_home,
    local_graph_binding,
)
from repomap_kg.ops.local_readiness import probe_local_graph, probe_local_graphs
from repomap_kg.ops.local_refresh import initialize_local_graph
from repomap_kg.server import _ops_sanitization, sqlite_read_binding
from repomap_kg.storage.sqlite_local import connection, migrations
from repomap_kg.storage.sqlite_local.publisher import publish_generation
from repomap_kg.storage.sqlite_local.schema import DATABASE_BUSY, LocalStoreError
from repomap_test_support.host_read_store_config import fail_if_reached
from repomap_test_support.sqlite_local_fixtures import (
    generation_bundle,
    graph_toml,
    publication_for,
    write_sqlite_home,
)


def _config(tmp_path: Path, *, root: Path | None = None) -> LocalSqliteConfig:
    source = tmp_path / "src"
    source.mkdir(exist_ok=True)
    home = write_sqlite_home(
        tmp_path / "home",
        graph_toml("one", root or source) + graph_toml("two", source)
        + graph_toml("off", source, enabled=False),
    )
    config = load_graph_registry_config_home(home)
    assert isinstance(config, LocalSqliteConfig)
    return config


def _database(config: LocalSqliteConfig, graph_id: str) -> Path:
    return config.graph_store_root / f"{graph_id}.sqlite3"


def _publish_one(config: LocalSqliteConfig) -> None:
    bundle = generation_bundle(1)
    publication = replace(
        publication_for(bundle, "one"), binding=local_graph_binding(config.graphs[0])
    )
    publish_generation(_database(config, "one"), publication, bundle.families, expected_generation=0)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def no_writer(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("publisher_lock", "open_writer", "initialize_graph_database", "private_store_directory"):
        monkeypatch.setattr(connection, name, fail_if_reached)


def test_absent_store_is_not_initialized_and_nothing_is_created(tmp_path: Path, no_writer: None) -> None:
    config = _config(tmp_path)
    states = [item.to_jsonable() for item in probe_local_graphs(config)]
    assert [item["graph_id"] for item in states] == ["one", "two", "off"], states
    assert {item["state"] for item in states} == {"not-initialized"}, states
    assert {item["error"] for item in states} == {"graph-database-not-initialized"}, states
    assert not (config.control_root / "state").exists(), "a readiness probe created the store"


def test_initialized_unpublished_and_published_are_current(tmp_path: Path) -> None:
    config = _config(tmp_path)
    initialize_local_graph(config, "one")
    unpublished = probe_local_graph(config, config.graphs[0])
    assert (unpublished.state, unpublished.published, unpublished.accepted_generation) == (
        "current", False, None,
    ), unpublished
    _publish_one(config)
    published = probe_local_graph(config, config.graphs[0])
    assert published.to_jsonable() == {
        "graph_id": "one", "state": "current", "published": True,
        "accepted_generation": 1, "error": None,
    }, published
    other = probe_local_graph(config, config.graphs[1])
    assert other.state == "not-initialized", "an uninitialized graph is reported apart from a current one"


def test_published_probe_changes_only_sidecars(tmp_path: Path) -> None:
    config = _config(tmp_path)
    initialize_local_graph(config, "one")
    _publish_one(config)
    database = _database(config, "one")
    before_names = {path.name for path in database.parent.iterdir()}
    before = _digest(database)
    with pytest.MonkeyPatch.context() as patcher:
        for name in ("publisher_lock", "open_writer", "initialize_graph_database", "private_store_directory"):
            patcher.setattr(connection, name, fail_if_reached)
        assert probe_local_graph(config, config.graphs[0]).accepted_generation == 1
    assert _digest(database) == before, "the probe changed the main database bytes"
    added = {path.name for path in database.parent.iterdir()} - before_names
    assert added <= {"one.sqlite3-wal", "one.sqlite3-shm"}, added
    assert not list(database.parent.glob(".*.init-*")), "the probe left an init file"


@pytest.mark.parametrize("content", (b"", b"not a sqlite database\n" * 64))
def test_empty_or_foreign_file_is_unrecognized(tmp_path: Path, content: bytes, no_writer: None) -> None:
    config = _config(tmp_path)
    database = _database(config, "one")
    database.parent.mkdir(parents=True)
    database.write_bytes(content)
    readiness = probe_local_graph(config, config.graphs[0])
    assert (readiness.state, readiness.error) == ("unrecognized", "graph-database-unrecognized"), readiness
    assert database.read_bytes() == content, "the probe changed a foreign file"


def test_another_graphs_database_is_unrecognized_as_graph_mismatch(tmp_path: Path) -> None:
    config = _config(tmp_path)
    initialize_local_graph(config, "two")
    shutil.copyfile(_database(config, "two"), _database(config, "one"))
    readiness = probe_local_graph(config, config.graphs[0])
    assert (readiness.state, readiness.error) == ("unrecognized", "graph-database-graph-mismatch"), readiness


def test_busy_or_unavailable_store_is_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config(tmp_path)

    def busy(*_args: object, **_kwargs: object) -> object:
        raise LocalStoreError(DATABASE_BUSY)

    monkeypatch.setattr(local_readiness, "read_transaction", busy)
    readiness = probe_local_graph(config, config.graphs[0])
    assert (readiness.state, readiness.error) == ("unavailable", "graph-database-busy"), readiness


def test_store_overlapping_a_source_is_invalid_configuration(tmp_path: Path, no_writer: None) -> None:
    config = _config(tmp_path, root=tmp_path / "home")
    readiness = probe_local_graph(config, config.graphs[0])
    assert (readiness.state, readiness.error) == (
        "invalid-configuration", "sqlite-graph-store-overlaps-source",
    ), readiness
    assert probe_local_graph(config, config.graphs[1]).state == "not-initialized"


def test_display_constants_match_the_read_binding_convention() -> None:
    assert SQLITE_DATABASE_SOURCE == sqlite_read_binding.SQLITE_DATABASE_SOURCE
    assert SQLITE_GRAPH_DATABASE_DISPLAY == _ops_sanitization.GRAPH_DATABASE_DISPLAY


def test_exact_behind_database_is_schema_behind_and_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    with monkeypatch.context() as historical:
        historical.setattr(migrations, "MIGRATIONS", migrations.MIGRATIONS[:1])
        initialize_local_graph(config, "one")
        _publish_one(config)
    database = _database(config, "one")
    before = _digest(database)
    with pytest.MonkeyPatch.context() as patcher:
        for name in ("publisher_lock", "open_writer", "initialize_graph_database", "private_store_directory"):
            patcher.setattr(connection, name, fail_if_reached)
        readiness = probe_local_graph(config, config.graphs[0])
    assert readiness.to_jsonable() == {
        "graph_id": "one", "state": "schema-behind", "published": True,
        "accepted_generation": 1, "error": "graph-database-schema-behind",
    }, readiness
    assert "schema-behind" in local_readiness.READINESS_STATES
    assert _digest(database) == before, "the probe migrated or changed a behind database"
    writer = sqlite3.connect(database, autocommit=True)
    try:
        writer.execute("PRAGMA user_version = 2")  # v1 ledger with a v2 user_version: drift, not behind
    finally:
        writer.close()
    drifted = probe_local_graph(config, config.graphs[0])
    assert (drifted.state, drifted.error) == ("unrecognized", "graph-database-schema-drift"), drifted
