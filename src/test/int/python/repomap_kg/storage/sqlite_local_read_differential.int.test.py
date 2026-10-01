"""Crafted-corpus differential: SQLite Local reads vs PostgreSQL query owners (LOCAL4).

One public-safe raw-observation corpus (``read_corpus_bundle``) is published by
the SQLite Local publisher and by the incumbent portable PostgreSQL publisher
into a disposable C-collation database under the same ``graph:`` root. The
five summary operations, the legacy storage summary, the configured
neighborhood and observation-search pages are then compared with the
maintained PostgreSQL owners: the ``query_*_summary`` functions,
``query_canonical_storage_summary``, ``query_canonical_neighborhood`` and the
MCP observation SQL (``build_mcp_search_sql``) through the JSON readback owner.

The corpus reaches predicate branches a tiny real tree does not: boolean
spellings, ``?`` on objects and arrays, ``LIKE`` wildcards, NULL operands under
``<>``/``NOT LIKE``, method case, tfvars paths, Nix sections/shapes/patterns,
and the ``jsonb::text`` spellings observation search matches. Only run ids
are normalized (PostgreSQL's single run maps to SQLite run 1); observation
rows are compared as exact JSON text, so key order and number spelling count.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import pytest

from repomap_kg.server._ops_search import build_mcp_search_sql
from repomap_kg.storage import (
    apply_migrations,
    default_rdbms_root,
    query_canonical_neighborhood,
    query_canonical_storage_summary,
    query_js_framework_summary,
    query_nix_summary,
    query_openapi_summary,
    query_python_summary,
    query_terraform_summary,
)
from repomap_kg.storage.readback_driver import READBACK_DRIVER_ENV, execute_json_readback
from repomap_kg.storage.sqlite_local import (
    api_summary_queries,
    investigation_queries,
    nix_summary_queries,
    queries,
    summary_queries,
)
from repomap_kg.storage.sqlite_local.connection import initialize_graph_database, read_transaction
from repomap_kg.storage.sqlite_local.publisher import publish_generation
from repomap_test_support.portable_publication_fixtures import publish_portable_bundle
from repomap_test_support.postgres_harness import require_postgres_binaries, temporary_postgres
from repomap_test_support.sqlite_local_fixtures import local_binding, publication_for
from repomap_test_support.sqlite_local_read_corpus import read_corpus_bundle

GRAPH = "read-corpus"
ROOT = f"graph:{GRAPH}"
C_COLLATIONS = frozenset({"C", "POSIX", "C.UTF-8", "C.utf8"})
HEADLINES = {"python": "python_observations", "terraform": "terraform_observations",
             "openapi": "openapi_observations", "js_framework": "framework_observations",
             "nix": "nix_observations"}
SUMMARIES: dict[str, tuple[Callable[..., Any], Callable[..., Any]]] = {
    "python": (query_python_summary, summary_queries.python_summary),
    "terraform": (query_terraform_summary, summary_queries.terraform_summary),
    "openapi": (query_openapi_summary, api_summary_queries.openapi_summary),
    "js_framework": (query_js_framework_summary, api_summary_queries.js_framework_summary),
    "nix": (query_nix_summary, nix_summary_queries.nix_summary),
}
# (query, kind, path, limit, offset, include_raw)
SEARCHES: tuple[tuple[str, str | None, str | None, int, int, bool], ...] = (
    ("#corpus:", None, None, 100, 0, False),
    ("#corpus:", None, None, 7, 7, True),
    ("CORPUS", None, None, 3, 68, False),
    ("tfvars", "terraform.file", None, 10, 0, True),
    ("corpus", "openapi.operation", "api.yaml", 2, 1, False),
    ('"b": 150, "c": "', None, None, 5, 0, True),
    ('"b":150', None, None, 5, 0, False),
    ('"e": 100000000000000000000', None, None, 5, 0, False),
    ("100% done_\\x", None, None, 5, 0, False),
    ("100%x", None, None, 5, 0, False),
    ("doneXx", None, None, 5, 0, False),
    ('\\"quoted\\"\\ttab', None, None, 5, 0, False),
    ('"quoted"', None, None, 5, 0, False),
    ("ÄRGER", None, None, 5, 0, False),
    ("ärger", None, None, 5, 0, False),
    ("Ünïcode", None, None, 5, 0, True),
    ('"program": null', None, None, 5, 0, False),
    ("repomap_kg", None, None, 5, 0, False),
    ("repomapXkg", None, None, 5, 0, False),
)


def _runs(value: Any, pg_run: int) -> Any:
    if isinstance(value, dict):
        return {key: (1 if key.endswith("run_id") and item == pg_run else _runs(item, pg_run))
                for key, item in value.items()}
    if isinstance(value, list):
        return [_runs(item, pg_run) for item in value]
    return value


def test_read_corpus_matches_postgresql_query_owners(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    require_postgres_binaries()
    for name in ("PGPASSWORD", "REPOMAP_PG_PASSWORD", "REPOMAP_STORAGE_PG_CONNECTOR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(READBACK_DRIVER_ENV, "psycopg")
    with temporary_postgres() as postgres:
        name = f"sqlite_differential_{uuid.uuid4().hex[:10]}"
        postgres.psql_scalar(
            f'CREATE DATABASE "{name}" WITH TEMPLATE template0 ENCODING \'UTF8\' '
            "LC_COLLATE 'C' LC_CTYPE 'C';"
        )
        try:
            database = replace(postgres, database=name)
            if getattr(database, "password", None) is not None:
                monkeypatch.setenv("PGPASSWORD", database.password)
            _prove(tmp_path, database)
        finally:
            postgres.psql_scalar(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _prove(tmp_path: Path, database: Any) -> None:
    collation = database.psql_scalar("SELECT datcollate || '|' || datctype FROM pg_database "
                                     "WHERE datname = current_database();")
    assert set(collation.split("|")) <= C_COLLATIONS, f"comparator is not byte-ordered C: {collation}"
    apply_migrations(default_rdbms_root(), database.psql_args, psql_command=database.psql_command)
    bundle = read_corpus_bundle(GRAPH)
    loaded = publish_portable_bundle(database.psql_args, bundle, repository_name=GRAPH, root_path=ROOT)
    pg_run = int(loaded.run_id)
    path = tmp_path / f"{GRAPH}.sqlite3"
    binding = local_binding(GRAPH)
    initialize_graph_database(path, binding, applied_at="2026-09-29T00:00:00Z")
    publish_generation(path, publication_for(bundle, GRAPH), bundle.families, expected_generation=0)
    pg = {"psql_command": database.psql_command}

    with read_transaction(path, binding) as connection:
        for family, (pg_owner, sqlite_owner) in SUMMARIES.items():
            expected = asdict(pg_owner(database.psql_args, root_path=ROOT, **pg))
            actual = asdict(sqlite_owner(connection, root_path=ROOT))
            assert actual[HEADLINES[family]] > 0, family  # never a zero-vs-zero comparison
            assert actual == expected, (family, actual, expected)

        expected_summary = _runs(asdict(query_canonical_storage_summary(
            database.psql_args, root_path=ROOT, **pg)), pg_run)
        actual_summary = asdict(investigation_queries.storage_summary(connection, root_path=ROOT))
        assert actual_summary == expected_summary and actual_summary["raw_observations"] > 0

        centers = [node.canonical_key for node in queries.canonical_nodes(
            connection, kind=None, canonical_key=None, path_prefix=None, graph_key_version=1,
            limit=None, offset=0)]
        compared_edges = 0
        for center in (*centers, "file:absent.nix"):
            for direction in ("both", "in", "out"):
                expected_around = _runs(asdict(query_canonical_neighborhood(
                    database.psql_args, root_path=ROOT, node=center, direction=direction, depth=1,
                    graph_key_version=1, **pg)), pg_run)
                actual_around = asdict(queries.canonical_neighborhood(
                    connection, node=center, direction=direction, depth=1, graph_key_version=1,
                    node_limit=None, node_offset=0, edge_limit=None, edge_offset=0))
                assert actual_around == expected_around, (center, direction)
                compared_edges += len(actual_around["edges"])
        assert compared_edges > 0

        nonempty = 0
        for query, kind, file_path, limit, offset, include_raw in SEARCHES:
            rows = execute_json_readback(
                build_mcp_search_sql(root_path=ROOT, target="observations", query=query, kind=kind,
                                     path=file_path, limit=limit, offset=offset, include_raw=include_raw),
                psql_args=database.psql_args, label="observation search differential",
                expected_shape="array", **pg,
            )
            assert isinstance(rows, list)
            expected_page = {"results": rows[:limit], "total": offset + len(rows[:limit]),
                             "has_more": len(rows) > limit}
            actual_page = investigation_queries.observation_search(
                connection, query=query, kind=kind, path=file_path, limit=limit, offset=offset,
                include_raw=include_raw)
            assert json.dumps(actual_page, ensure_ascii=False) == json.dumps(
                expected_page, ensure_ascii=False), (query, actual_page, expected_page)
            nonempty += bool(actual_page["results"])
        assert nonempty >= 12, nonempty
