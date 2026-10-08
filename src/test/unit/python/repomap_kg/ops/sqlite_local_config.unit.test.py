"""SQLite Local home selection without PostgreSQL (REPOMAP-PRODUCT3-SQLITE-LOCAL1).

A ``[storage] backend = "sqlite"`` home parses with no ``[postgres]`` block,
credentials, client, coordinator or Docker; PostgreSQL homes keep their exact
meaning; PostgreSQL-only loaders refuse a SQLite home before deriving any
PostgreSQL setting; and each graph owns one database path outside its sources.
LOCAL2 (A1) fixes the backend by the first file in load order: no overlay can
switch a home between PostgreSQL and SQLite in either direction.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from repomap_kg.ops.config import load_ops_config, load_ops_config_home
from repomap_kg.ops.config_local import (
    LocalSqliteConfig,
    declared_storage_backend,
    load_graph_registry_config,
    load_graph_registry_config_home,
    local_graph_binding,
    sqlite_graph_database_path,
)
from repomap_kg.ops.config_records import OpsConfig, OpsConfigError
from repomap_kg.storage.sqlite_local.connection import graph_database_uri
from repomap_test_support.host_read_store_config import setup_owned_config
from repomap_test_support.sqlite_local_fixtures import (
    graph_toml,
    multi_graph_toml,
    sqlite_home_toml,
    write_sqlite_home,
)


def _codes(error: OpsConfigError) -> list[str]:
    return [diagnostic.code for diagnostic in error.diagnostics]


def test_sqlite_home_parses_without_postgres_settings(tmp_path: Path) -> None:
    home = write_sqlite_home(
        tmp_path / "home",
        graph_toml("one", tmp_path / "src")
        + multi_graph_toml("multi", (("alpha", tmp_path / "a"), ("beta", tmp_path / "b"))),
    )
    config = load_graph_registry_config_home(home)
    assert isinstance(config, LocalSqliteConfig), type(config)
    assert not hasattr(config, "postgres") and not hasattr(config, "runtime")
    assert [graph.id for graph in config.graphs] == ["one", "multi"]
    assert config.storage_backend == "sqlite"
    path = sqlite_graph_database_path(config, config.graphs[0])
    assert path == (home / "state" / "sqlite-local" / "graphs" / "one.sqlite3").resolve()
    assert local_graph_binding(config.graphs[1]).root_path == "graph:multi"
    assert local_graph_binding(config.graphs[1]).repository_identity == "repo1:multi"


def test_single_file_sqlite_config_uses_its_parent_as_control_root(tmp_path: Path) -> None:
    path = tmp_path / "repomap.toml"
    path.write_text(sqlite_home_toml(graph_toml("one", tmp_path / "src")), encoding="utf-8")
    config = load_graph_registry_config(path)
    assert isinstance(config, LocalSqliteConfig)
    assert config.graph_store_root == tmp_path / "state" / "sqlite-local" / "graphs"


def test_postgres_homes_are_unchanged_and_default_to_postgresql(tmp_path: Path) -> None:
    home = tmp_path / "pg"
    home.mkdir()
    (home / "repomap.rpl.toml").write_text(setup_owned_config(), encoding="utf-8")
    loaded = load_graph_registry_config_home(home)
    assert isinstance(loaded, OpsConfig) and loaded == load_ops_config_home(home)
    assert declared_storage_backend(repo_map_home=str(home), config_path=None) == "postgresql"
    explicit = setup_owned_config().replace(
        "schema_version = 1\n", 'schema_version = 1\n[storage]\nbackend = "postgresql"\n', 1
    )
    (home / "repomap.rpl.toml").write_text(explicit, encoding="utf-8")
    assert load_ops_config_home(home).postgres.database == "repomap"


def test_postgres_loaders_refuse_sqlite_home_before_postgres_parsing(tmp_path: Path) -> None:
    home = write_sqlite_home(tmp_path / "home", graph_toml("one", tmp_path / "src"))
    for load in (lambda: load_ops_config_home(home), lambda: load_ops_config(home)):
        with pytest.raises(OpsConfigError) as caught:
            load()
        assert _codes(caught.value) == ["sqlite-local-home-requires-local-command"]
        assert "missing-section" not in _codes(caught.value)
    assert declared_storage_backend(repo_map_home=str(home), config_path=None) == "sqlite"


@pytest.mark.parametrize(
    ("text", "code"),
    (
        ('[postgres]\nhost = "h"\nport = 5432\ndatabase = "d"\nuser = "u"\n',
         "sqlite-local-home-rejects-postgres-settings"),
        ('[runtime]\ncontainer_runtime = "docker"\n', "sqlite-local-home-rejects-postgres-settings"),
    ),
)
def test_sqlite_home_rejects_postgres_only_sections(tmp_path: Path, text: str, code: str) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / "repomap.rp.toml").write_text(
        sqlite_home_toml(text + graph_toml("one", tmp_path / "src")), encoding="utf-8"
    )
    with pytest.raises(OpsConfigError) as caught:
        load_graph_registry_config_home(home)
    assert code in _codes(caught.value), _codes(caught.value)


def test_sqlite_home_rejects_graph_database_and_unknown_backend(tmp_path: Path) -> None:
    home = write_sqlite_home(
        tmp_path / "home", graph_toml("one", tmp_path / "src", extra='database = "repomap_one"\n')
    )
    with pytest.raises(OpsConfigError) as caught:
        load_graph_registry_config_home(home)
    assert _codes(caught.value) == ["sqlite-local-graph-database-unsupported"]
    (home / "repomap.rp.toml").write_text(
        sqlite_home_toml(graph_toml("one", tmp_path / "src"), storage='[storage]\nbackend = "mysql"\n'),
        encoding="utf-8",
    )
    with pytest.raises(OpsConfigError) as caught:
        load_graph_registry_config_home(home)
    assert "unsupported-storage-backend" in _codes(caught.value), _codes(caught.value)


_SQLITE_STORAGE = '[storage]\nbackend = "sqlite"\n'
_PG_STORAGE = '[storage]\nbackend = "postgresql"\n'


def _explicit_pg() -> str:
    return setup_owned_config().replace("schema_version = 1\n", "schema_version = 1\n" + _PG_STORAGE, 1)


def _layered_home(tmp_path: Path, files: dict[str, str]) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    for name, text in files.items():
        (home / name).write_text(text, encoding="utf-8")
    return home


def _overlay(storage: str = "", body: str = "") -> str:
    return "schema_version = 1\n" + storage + body


# (LOCAL2 A1) The first file in load order (*.rp.toml, then *.rpl.toml, by
# name) fixes the backend: explicit [storage], or PostgreSQL when absent. A
# later file may omit [storage] or repeat the same backend; a later file with
# PostgreSQL-only sections and no [storage] declares PostgreSQL implicitly.
REFUSED_LAYERS = {
    "implicit-pg-base+sqlite-overlay": {
        "repomap.rpl.toml": setup_owned_config(), "zz-local.rpl.toml": _overlay(_SQLITE_STORAGE)},
    "setup-pg-home+sorts-first-sqlite": {
        "repomap.rpl.toml": setup_owned_config(), "00-local.rp.toml": _overlay(_SQLITE_STORAGE)},
    "explicit-pg-base+sqlite-overlay": {
        "repomap.rpl.toml": _explicit_pg(), "zz-local.rpl.toml": _overlay(_SQLITE_STORAGE)},
    "sqlite-base+pg-overlay": {
        "repomap.rp.toml": sqlite_home_toml(""), "zz-local.rpl.toml": _overlay(_PG_STORAGE)},
    "sqlite-base+pg-only-sections-overlay": {
        "repomap.rp.toml": sqlite_home_toml(""),
        "zz-local.rpl.toml": _overlay(body='[runtime]\ncontainer_runtime = "docker"\n')},
    "graph-only-first-rp+sqlite-second-rp": {
        "00-base.rp.toml": _overlay(body=graph_toml("one", "/public/one")),
        "10-x.rp.toml": _overlay(_SQLITE_STORAGE)},
}


@pytest.mark.parametrize("layers", list(REFUSED_LAYERS.values()), ids=list(REFUSED_LAYERS))
def test_overlay_can_never_switch_a_home_backend(tmp_path: Path, layers: dict[str, str]) -> None:
    home = _layered_home(tmp_path, layers)
    for load in (lambda: load_graph_registry_config_home(home), lambda: load_ops_config_home(home)):
        with pytest.raises(OpsConfigError) as caught:
            load()
        assert "storage-backend-conflict" in _codes(caught.value), _codes(caught.value)
    assert not (home / "state").exists()


def test_implicit_postgres_home_keeps_postgres_routing_under_a_sqlite_overlay(tmp_path: Path) -> None:
    home = _layered_home(tmp_path, REFUSED_LAYERS["implicit-pg-base+sqlite-overlay"])
    backend = declared_storage_backend(repo_map_home=str(home), config_path=None)
    assert backend == "postgresql", backend
    with pytest.raises(OpsConfigError) as caught:
        load_ops_config_home(home)
    conflict = next(item for item in caught.value.diagnostics if item.code == "storage-backend-conflict")
    assert conflict.path == "zz-local.rpl.toml:storage.backend", conflict
    assert "repomap.rpl.toml" in conflict.message and "no [storage] table" in conflict.message
    # LOCAL3: the code reaches CLI stderr, which prints messages without codes.
    assert conflict.message.startswith("storage-backend-conflict: "), conflict.message
    assert "storage-backend-conflict: " in str(caught.value), str(caught.value)


@pytest.mark.parametrize(
    "layers",
    (
        {"repomap.rpl.toml": setup_owned_config(), "zz-local.rpl.toml": _overlay(_PG_STORAGE)},
        {"repomap.rpl.toml": _explicit_pg(), "zz-local.rpl.toml": _overlay(_PG_STORAGE)},
        {"repomap.rpl.toml": _explicit_pg(), "zz-local.rpl.toml": _overlay()},
    ),
    ids=("implicit-pg+explicit-pg", "explicit-pg+explicit-pg", "explicit-pg+omitted"),
)
def test_same_backend_postgres_overlays_are_allowed(tmp_path: Path, layers: dict[str, str]) -> None:
    alone = tmp_path / "alone"
    alone.mkdir()
    (alone / "repomap.rpl.toml").write_text(layers["repomap.rpl.toml"], encoding="utf-8")
    layered = load_graph_registry_config_home(_layered_home(tmp_path, layers))
    assert isinstance(layered, OpsConfig), type(layered)
    baseline = load_ops_config_home(alone)
    assert (layered.postgres, layered.runtime, layered.graphs) == (
        baseline.postgres, baseline.runtime, baseline.graphs
    )


@pytest.mark.parametrize(
    ("layers", "enabled"),
    (
        ({"repomap.rp.toml": sqlite_home_toml(graph_toml("one", "/public/one")),
          "zz-local.rpl.toml": _overlay(_SQLITE_STORAGE)}, True),
        ({"repomap.rp.toml": sqlite_home_toml(graph_toml("one", "/public/one")),
          "zz-local.rpl.toml": _overlay(body='[[graphs]]\nid = "one"\nenabled = false\n')}, False),
        ({"repomap.rpl.toml": sqlite_home_toml(graph_toml("one", "/public/one"))}, True),
    ),
    ids=("sqlite+sqlite", "sqlite+omitted-storage-overlay", "rpl-only-sqlite"),
)
def test_sqlite_base_is_preserved_by_same_or_omitted_overlays(
    tmp_path: Path, layers: dict[str, str], enabled: bool
) -> None:
    home = _layered_home(tmp_path, layers)
    config = load_graph_registry_config_home(home)
    assert isinstance(config, LocalSqliteConfig), type(config)
    assert [(graph.id, graph.enabled) for graph in config.graphs] == [("one", enabled)]
    assert declared_storage_backend(repo_map_home=str(home), config_path=None) == "sqlite"


def test_invalid_overlay_backend_is_reported_with_its_source(tmp_path: Path) -> None:
    home = _layered_home(tmp_path, {
        "repomap.rpl.toml": setup_owned_config(),
        "zz-local.rpl.toml": _overlay('[storage]\nbackend = "mysql"\n'),
    })
    with pytest.raises(OpsConfigError) as caught:
        load_graph_registry_config_home(home)
    paths = {item.path for item in caught.value.diagnostics if item.code == "unsupported-storage-backend"}
    assert paths == {"zz-local.rpl.toml:storage.backend"}, caught.value.diagnostics


def test_legacy_single_file_postgres_config_is_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "repomap.toml"
    path.write_text(setup_owned_config(), encoding="utf-8")
    loaded = load_graph_registry_config(path)
    assert isinstance(loaded, OpsConfig) and loaded == load_ops_config(path)


def test_graph_store_overlapping_a_source_root_refuses(tmp_path: Path) -> None:
    overlapping = write_sqlite_home(tmp_path / "overlap", graph_toml("inner", tmp_path / "overlap"))
    local = load_graph_registry_config_home(overlapping)
    assert isinstance(local, LocalSqliteConfig)
    with pytest.raises(OpsConfigError) as caught:
        sqlite_graph_database_path(local, local.graphs[0])
    assert _codes(caught.value) == ["sqlite-graph-store-overlaps-source"]


@pytest.mark.parametrize("name", ("plain", "with space", "q?mark", "hash#tag", "pct%41"))
def test_file_uri_escapes_spaces_and_uri_special_characters(tmp_path: Path, name: str) -> None:
    path = tmp_path / name / "graph.sqlite3"
    uri = graph_database_uri(path, read_only=True)
    body, _, options = uri.rpartition("?")
    assert options == "mode=ro" and body.startswith("file:///")
    for character in (" ", "?", "#"):
        assert character not in body, uri
    if "%" in name:
        assert "%2541" in body, uri
