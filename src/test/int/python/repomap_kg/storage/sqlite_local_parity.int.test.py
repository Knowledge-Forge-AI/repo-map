"""Same-input SQLite Local vs PostgreSQL parity over real stdio MCP (PRODUCT3-SQLITE-LOCAL1/LOCAL4).

Each fixture graph is captured once through the production portable path and
validated twice (the SQLite stage label and the PostgreSQL stage id do not
enter the bundle identity). The same validated input is published separately
by the SQLite publisher (with the PostgreSQL publisher and psycopg patched to
fail) and by the incumbent staged PostgreSQL publisher into a disposable
database, under matching configured ``graph:``/``repo1:``/repository-name
tuples, for two generations. The seventeen supported tools are then read
from both backends over stdio MCP and compared. The one-source graph is the
polyglot tree, so every summary family is asserted nonempty on SQLite before
it is compared (LOCAL4); the two-binding Nix graph carries overlapping
source-relative paths for observation and neighborhood identity.

Declared normalizations, and nothing else: run ids map to accepted-generation
ordinals per backend (asserted bijective); ``latest_run_started_at`` and
``latest_run_finished_at`` are dropped after asserting their UTC format;
``database_source`` is dropped after asserting each backend's own value.
Identities, provenance, evidence, counts, order, paging and refusals compare
exactly as parsed JSON values (PostgreSQL stores JSONB).
"""

from __future__ import annotations

import re
import shutil
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from repomap_kg.ops.config_local import LocalSqliteConfig, load_graph_registry_config_home, local_graph_binding
from repomap_kg.ops.local_refresh import LOCAL_STAGE_ID, initialize_local_graph
from repomap_kg.ops.portable_refresh import (
    capture_portable_candidate,
    portable_publication_binding,
    validate_portable_capture,
)
from repomap_kg.runtime.local import setup_local_runtime
from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_kg.storage.publication import RunPublicationReceipt
from repomap_kg.storage.sqlite_local import queries
from repomap_kg.storage.sqlite_local.connection import read_transaction
from repomap_kg.storage.sqlite_local.publisher import FAMILY_ORDER, LocalPublication, publish_generation
from repomap_kg.storage.staged_ingestion import run_staged_portable_refresh, stage_id_for_authority
from repomap_test_support.cli_in_process import FIXTURE_ROOT
from repomap_test_support.host_mcp_publication import RESTORE_LOGIN_SQL, provision_roles, role_secrets
from repomap_test_support.host_mcp_stdio import HostMcpHarness
from repomap_test_support.postgres_harness import require_postgres_binaries, temporary_postgres
from repomap_test_support.sqlite_local_fixtures import (
    SERVICE_TOML,
    graph_toml,
    multi_graph_toml,
    write_sqlite_home,
)
from repomap_test_support.sqlite_local_read_corpus import write_polyglot_source
from repomap_test_support.sqlite_local_harness import LocalHarness, initialize, structured, tool

ONE, MULTI = "sqlite-one", "sqlite-multi"
CONSTELLATION = FIXTURE_ROOT / "multi_source_nix_constellation"
RUN_KEYS = frozenset({"first_seen_run_id", "last_seen_run_id", "latest_run_id", "run_id"})
TIME_KEYS = frozenset({"latest_run_started_at", "latest_run_finished_at"})
UTC = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ\Z")
SOURCE = {"sqlite": "sqlite-graph-file", "postgres": "graph"}
C_COLLATIONS = frozenset({"C", "POSIX", "C.UTF-8", "C.utf8"})
CENTERS = {ONE: "file:root/flake.nix", MULTI: "file:entry/flake.nix"}
SUMMARIES = ("python", "terraform", "openapi", "js_framework", "nix")
HEADLINES = ("python_observations", "terraform_observations", "openapi_observations",
             "framework_observations", "nix_observations")
CALLS = 32


def _pg_fail(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("SQLite publication reached a PostgreSQL publisher or driver")


def _sources(root: Path, generation: int) -> dict[str, Path]:
    write_polyglot_source(root / "one")
    for alias in ("entry", "composition"):
        shutil.copytree(CONSTELLATION / alias, root / alias, dirs_exist_ok=True)
    if generation == 2:
        (root / "one" / "extra.sh").write_text("extra() {\n  helper\n}\n", encoding="utf-8")
        (root / "entry" / "modules" / "extra.nix").write_text("{ ... }: { }\n", encoding="utf-8")
    return {alias: root / alias for alias in ("one", "entry", "composition")}


def _graphs(sources: dict[str, Path], databases: dict[str, str] | None = None) -> str:
    one_extra = f'database = "{databases[ONE]}"\n' if databases else ""
    multi = multi_graph_toml(MULTI, (("entry", sources["entry"]), ("composition", sources["composition"])))
    if databases:
        multi = multi.replace('refresh_policy = "manual"\n', f'refresh_policy = "manual"\ndatabase = "{databases[MULTI]}"\n', 1)
    return graph_toml(ONE, sources["one"], extra=one_extra) + multi


def _write_pg_home(home: Path, port: int, databases: dict[str, str], sources: dict[str, Path]) -> None:
    setup_local_runtime(home)
    (home / "repomap.rpl.toml").write_text(
        "schema_version = 1\n" + SERVICE_TOML
        + '[runtime]\ncontainer_runtime = "docker"\nserver_host_port = 18080\nbind_host = "127.0.0.1"\n'
        + f'[runtime.postgres]\ndirect_host_port_enabled = true\nhost_port = {port}\nbind_host = "127.0.0.1"\n'
        + f'[postgres]\nhost = "postgres"\nport = 5432\ndatabase = "{databases[ONE]}"\nuser = "repomap"\n'
        + 'password_env = "REPOMAP_PG_PASSWORD"\n'
        + _graphs(sources, databases)
        + '[server_memory]\nenabled = false\npath = "./server-memory"\nmode = "read_only"\n',
        encoding="utf-8",
    )


def _normalize(value: Any, runs: dict[int, int], backend: str) -> Any:
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if key in TIME_KEYS:
                assert item is None or UTC.fullmatch(str(item)), (key, item)
            elif key == "database_source":
                assert item == SOURCE[backend], (backend, item)
            elif key in RUN_KEYS and item is not None:
                normalized[key] = runs[int(item)]
            else:
                normalized[key] = _normalize(item, runs, backend)
        return normalized
    if isinstance(value, list):
        return [_normalize(item, runs, backend) for item in value]
    return value


def _publish_generation(
    local: LocalSqliteConfig, dbs: dict[str, Any], generation: int, pg_runs: dict[str, dict[int, int]],
) -> dict[str, str]:
    bundles: dict[str, str] = {}
    for graph in local.graphs:
        capture = capture_portable_candidate(local, graph, authority=None)
        receipt, sqlite_input = validate_portable_capture(capture, stage_id=LOCAL_STAGE_ID)
        pg_stage = stage_id_for_authority(capture.authority)
        pg_receipt, pg_input = validate_portable_capture(capture, stage_id=pg_stage)
        try:
            assert sqlite_input.bundle_id == pg_input.bundle_id, "same input must yield one bundle id"
            spools = sqlite_input.family_spools
            assert spools is not None
            authority_receipt = capture.authority.receipt()
            publication = LocalPublication(
                binding=local_graph_binding(graph),
                repository_name=graph.repository_name,
                receipt=RunPublicationReceipt(
                    authority_receipt.attempt, authority_receipt.generations,
                    portable_publication_binding(capture, receipt, sqlite_input, stage_id=LOCAL_STAGE_ID),
                ).validate(),
                privacy=sqlite_input.privacy.value,
            )
            with patch("repomap_kg.storage.staged_ingestion.run_staged_portable_refresh", _pg_fail), \
                    patch("repomap_kg.ops.portable_refresh.run_staged_portable_refresh", _pg_fail), \
                    patch("psycopg.connect", _pg_fail):
                result = publish_generation(
                    local.graph_store_root / f"{graph.id}.sqlite3", publication,
                    {family: spools[family] for family in FAMILY_ORDER},
                    expected_generation=generation - 1,
                )
            assert result.generation == generation
            summary = run_staged_portable_refresh(
                dbs[graph.id].psql_args, pg_input, prepared_override=pg_input.to_prepared_stage_rows(),
                repository_name=graph.repository_name, root_path=f"graph:{graph.id}",
                authority=capture.authority,
                portable_binding=portable_publication_binding(capture, pg_receipt, pg_input, stage_id=pg_stage),
                repository_identity=f"repo1:{graph.id}",
            )
            pg_runs[graph.id][summary.run_id] = generation
            capture.mark_terminal(accepted=True)
            bundles[graph.id] = sqlite_input.bundle_id
        finally:
            sqlite_input.close()
            pg_input.close()
    return bundles


def _requests(local: LocalSqliteConfig) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = [initialize(1)]
    for base, graph in ((100, local.graphs[0]), (200, local.graphs[1])):
        with read_transaction(local.graph_store_root / f"{graph.id}.sqlite3", local_graph_binding(graph)) as connection:
            node = queries.canonical_nodes(connection, kind=None, canonical_key=None, path_prefix=None,
                                           graph_key_version=1, limit=1, offset=0)[0]
            edge = queries.canonical_edges(connection, kind=None, source_key=None, target_key=None,
                                           graph_key_version=1, limit=1, offset=0)[0]
        g, p = {"graph_id": graph.id}, {"project": graph.id}
        explain = {**p, "source_key": edge.source_key, "kind": edge.edge_kind, "target_key": edge.target_key,
                   "identity_metadata": edge.identity_metadata}
        file_query = "sh" if graph.id == ONE else "nix"
        calls: list[tuple[str, dict[str, Any]]] = [
            ("repomap_canonical_nodes", {**p, "limit": 3}),
            ("repomap_canonical_nodes", {**p, "limit": 3, "offset": 3}),
            ("repomap_canonical_nodes", {**p, "result_schema_version": 0}),
            ("repomap_canonical_nodes", {**p, "kind": node.kind}),
            ("repomap_canonical_edges", {**p}),
            ("repomap_canonical_edges", {**p, "limit": 1, "offset": 1}),
            ("repomap_canonical_edges", {**p, "source_key": edge.source_key}),
            ("repomap_explain_canonical_edge", explain),
            ("repomap_explain_canonical_edge", {**explain, "evidence_limit": 1, "evidence_offset": 1}),
            ("repomap_canonical_neighborhood", {**p, "node": edge.source_key}),
            ("repomap_canonical_neighborhood", {**p, "node": edge.target_key, "direction": "in", "node_limit": 1}),
            ("repomap_graph_status", g),
            ("repomap_refresh_status", g),
            ("repomap_project_summary", g),
            ("repomap_search_nodes", {**g, "query": "A", "limit": 2}),
            ("repomap_search_nodes", {**g, "query": "a", "limit": 2, "offset": 2}),
            ("repomap_search_files", {**g, "query": file_query}),
            ("repomap_search_files", {**g, "query": file_query, "limit": 1, "offset": 1}),
            ("repomap_status", p),
            ("repomap_search_observations", {**g, "query": "nix", "limit": 3}),
            ("repomap_search_observations", {**g, "query": "NIX", "limit": 3, "offset": 3, "include_raw": True}),
            ("repomap_search_observations", {**g, "query": "flake.nix", "kind": "file", "include_raw": True}),
            ("repomap_search_observations", {**g, "query": '": "', "limit": 2}),
            ("repomap_search_observations", {**g, "query": "g_a", "limit": 2, "offset": 1}),
            ("repomap_neighborhood", {**g, "node": CENTERS[graph.id]}),
            ("repomap_neighborhood", {**g, "node": CENTERS[graph.id], "direction": "in"}),
            ("repomap_neighborhood", {**g, "node": "file:absent.nix", "direction": "out"}),
            *((f"repomap_{family}_summary", g) for family in SUMMARIES),
        ]
        assert len(calls) == CALLS
        requests += [tool(base + index, name, arguments) for index, (name, arguments) in enumerate(calls, 1)]
    requests += [tool(902, "repomap_refresh_status", {})]
    return requests


def test_same_validated_input_reads_identically_from_sqlite_and_postgresql(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    require_postgres_binaries()
    for name in ("PGPASSWORD", "REPOMAP_PG_PASSWORD", "REPOMAP_READ_STATUS_PASSWORD", "REPOMAP_STORAGE_PG_CONNECTOR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("REPOMAP_STORAGE_READBACK_DRIVER", "psycopg")
    with temporary_postgres() as postgres:
        token = uuid.uuid4().hex[:10]
        names = {ONE: f"sqlite_parity_one_{token}", MULTI: f"sqlite_parity_multi_{token}"}
        try:
            for name in names.values():
                # Match the maintained Server Engine (compose --locale=C, release
                # cluster LC_COLLATE 'C'); the disposable cluster default is not C.
                postgres.psql_scalar(
                    f'CREATE DATABASE "{name}" WITH TEMPLATE template0 ENCODING \'UTF8\' '
                    "LC_COLLATE 'C' LC_CTYPE 'C';"
                )
            dbs = {graph: replace(postgres, database=name) for graph, name in names.items()}
            _prove(tmp_path, dbs, postgres)
        finally:
            postgres.psql_scalar(RESTORE_LOGIN_SQL)
            for name in names.values():
                postgres.psql_scalar(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _prove(tmp_path: Path, dbs: dict[str, Any], postgres: Any) -> None:
    for database in dbs.values():
        collation = database.psql_scalar("SELECT datcollate FROM pg_database WHERE datname = current_database();")
        assert collation in C_COLLATIONS, f"comparator collation is not byte-ordered: {collation}"
        apply_migrations(default_rdbms_root(), database.psql_args, psql_command=database.psql_command)
    sources = _sources(tmp_path / "sources", 1)
    sqlite_home = write_sqlite_home(tmp_path / "sqlite-home", _graphs(sources))
    pg_home = tmp_path / "pg-home"
    _write_pg_home(pg_home, postgres.port, {graph: db.database for graph, db in dbs.items()}, sources)
    local = load_graph_registry_config_home(sqlite_home)
    assert isinstance(local, LocalSqliteConfig)
    for graph in (ONE, MULTI):
        assert initialize_local_graph(local, graph)["result"] == "initialized"
    pg_runs: dict[str, dict[int, int]] = {ONE: {}, MULTI: {}}
    gen1 = _publish_generation(local, dbs, 1, pg_runs)
    secrets = role_secrets(pg_home)
    for database in dbs.values():
        provision_roles(postgres.user, database, secrets)
    _sources(tmp_path / "sources", 2)
    gen2 = _publish_generation(local, dbs, 2, pg_runs)
    assert gen1 != gen2
    assert all(len(set(runs)) == 2 and sorted(runs.values()) == [1, 2] for runs in pg_runs.values()), pg_runs
    shutil.rmtree(tmp_path / "sources")

    requests = _requests(local)
    sqlite = LocalHarness(tmp_path / "sqlite-mcp").mcp(sqlite_home, requests)
    pg = HostMcpHarness(tmp_path / "pg-mcp", pg_home).run(requests)
    assert pg.returncode == 0, pg.stderr
    # Nonempty before compared: a vacuous zero-vs-zero summary proves nothing.
    for index, headline in enumerate(HEADLINES):
        assert structured(sqlite, 100 + CALLS - 4 + index)["summary"][headline] > 0, headline
    assert structured(sqlite, 200 + CALLS)["summary"]["nix_observations"] > 0
    for base in (100, 200):
        assert structured(sqlite, base + 20)["results"] and structured(sqlite, base + 25)["result"]["edges"]
    flakes = [row["path"] for row in structured(sqlite, 222)["results"]]
    assert sorted(flakes) == ["composition/flake.nix"] * 2 + ["entry/flake.nix"] * 2, flakes  # both generations
    assert structured(sqlite, 227)["result"]["center"] is None
    compared = 0
    for base, graph in ((100, ONE), (200, MULTI)):
        for mid in range(base + 1, base + CALLS + 1):
            left = _normalize(structured(sqlite, mid), {1: 1, 2: 2}, "sqlite")
            right = _normalize(pg.structured(mid), pg_runs[graph], "postgres")
            assert left == right, (mid, left, right)
            compared += 1
    assert compared == 2 * CALLS
    assert structured(sqlite, 112)["storage"]["latest_run_id"] == 2
    assert structured(sqlite, 212)["storage"]["publication"]["publication_bundle_id"] == gen2[MULTI]
    everything = {row["graph_id"]: row for row in structured(sqlite, 902)["graphs"]}
    pg_everything = {row["graph_id"]: row for row in pg.structured(902)["graphs"]}
    for graph in (ONE, MULTI):
        assert _normalize(everything[graph], {1: 1, 2: 2}, "sqlite") == _normalize(
            pg_everything[graph], pg_runs[graph], "postgres"
        ), graph

    # FIX1 residual: multi-source status is positive under the supported tuple.
    multi_status = pg.structured(213)["graphs"][0]
    assert multi_status["repository_exists"] is True
    assert multi_status["publication"]["publication_bundle_id"] == gen2[MULTI]
    stored = dbs[MULTI].psql_scalar("SELECT name || '|' || repository_identity || '|' || root_path FROM repositories;")
    assert stored == f"[multi-source]|repo1:{MULTI}|graph:{MULTI}", stored
