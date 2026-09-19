"""PostgreSQL identity and fallback integration owner for FIX17-R2 / ADR 0068.

Covers ten identity-aware surfaces using the canonical disposable container harness:
1. Canonical nodes search       6. Python storage summary
2. Raw observations search      7. Terraform storage summary
3. File sources search          8. OpenAPI storage summary
4. Project summary              9. JS framework storage summary
5. Canonical neighborhood       10. Nix storage summary
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
import os
from typing import Any

import pytest

from repomap_kg.server.mcp_search_sql import build_mcp_search_sql
from repomap_kg.storage import apply_migrations, default_rdbms_root, run_psql
from repomap_kg.storage._sql_summaries_domains import (
    build_openapi_summary_query_sql,
    build_terraform_summary_query_sql,
)
from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.graph_readback_sql import (
    build_canonical_node_search_sql,
    build_file_source_search_sql,
    build_repository_filter_sql,
    escape_readback_like_pattern,
)
from repomap_kg.storage.readback_driver import execute_json_readback
from repomap_kg.storage.sql_canonical import (
    build_canonical_neighborhood_query_sql,
    build_canonical_storage_summary_query_sql,
)
from repomap_kg.storage.sql_core import sql_literal
from repomap_kg.storage.sql_summaries import build_js_framework_summary_query_sql
from repomap_kg.storage.sql_summaries_nix import build_nix_summary_query_sql
from repomap_kg.storage.sql_summaries_python import build_python_summary_query_sql
from repomap_test_support.postgres_container_config import PostgresContainerDatabase
from repomap_test_support.postgres_harness import active_or_new_postgres_session

pytestmark = [pytest.mark.int]

LANGUAGE_SUMMARIES = (
    (build_python_summary_query_sql, "python_observations"),
    (build_terraform_summary_query_sql, "terraform_observations"),
    (build_openapi_summary_query_sql, "openapi_observations"),
    (build_js_framework_summary_query_sql, "framework_observations"),
    (build_nix_summary_query_sql, "nix_observations"),
)


@contextmanager
def _disposable_database() -> Iterator[PostgresContainerDatabase]:
    session, owned_context = active_or_new_postgres_session()
    prior_password = os.environ.get("PGPASSWORD")
    try:
        database = session.database()
        if database.password is not None:
            os.environ["PGPASSWORD"] = str(database.password)
        yield database
    finally:
        if prior_password is None:
            os.environ.pop("PGPASSWORD", None)
        else:
            os.environ["PGPASSWORD"] = prior_password
        if owned_context is not None:
            owned_context.__exit__(None, None, None)


def _build_summary_sql(
    builder_func: Callable[..., str],
    *,
    root_path: str,
    repository_identity: str | None = None,
) -> str:
    return builder_func(root_path, repository_identity=repository_identity)


def _setup_fixtures(database: PostgresContainerDatabase) -> None:
    apply_migrations(
        default_rdbms_root(),
        database.psql_args,
        psql_command=database.psql_command,
    )
    sql = """
INSERT INTO repositories (id, name, root_path, repository_identity) VALUES
    (10, 'alpha_legacy', '/workspace/alpha', NULL),
    (20, 'alpha_current', 'graph:alpha_portable', 'repo1:alpha'),
    (30, 'beta_unrelated', '/workspace/unrelated_root', 'repo1:beta'),
    (40, 'empty_current', 'graph:empty', 'repo1:empty'),
    (41, 'empty_legacy', '/workspace/empty', NULL),
    (100, 'tie_first', '/workspace/tie', NULL),
    (200, 'tie_second', '/workspace/tie-second', NULL),
    (400, 'relocated_current', '/old/stored/path', 'repo1:relocated'),
    (500, 'high_legacy', '/workspace/inverse', NULL),
    (5, 'low_current', 'graph:inverse', 'repo1:inverse');

INSERT INTO runs (id, repository_id, status) VALUES
    (1, 10, 'complete'), (2, 20, 'complete'), (3, 41, 'complete'), (4, 100, 'complete'),
    (5, 200, 'complete'), (6, 400, 'complete'), (7, 500, 'complete'), (8, 5, 'complete'),
    (9, 30, 'complete');

INSERT INTO files (id, repository_id, path, language, role) VALUES
    (1, 10, 'src/legacy.py', 'python', 'source'),
    (2, 20, 'src/curr.py', 'python', 'source'),
    (3, 41, 'src/empty_legacy.py', 'python', 'source'),
    (4, 400, 'src/relocated.py', 'python', 'source'),
    (5, 500, 'src/high_legacy.py', 'python', 'source'),
    (6, 5, 'src/low_curr.py', 'python', 'source');

INSERT INTO canonical_nodes (id, repository_id, graph_key_version, canonical_key, kind, display_name, confidence) VALUES
    (1, 10, 1, 'node:legacy_center', 'python.module', 'legacy_mod', 'extracted'),
    (2, 20, 1, 'node:curr_center', 'python.module', 'curr_mod', 'extracted'),
    (3, 20, 1, 'node:curr_neighbor', 'python.function', 'curr_func', 'extracted'),
    (4, 20, 1, 'config:curr_doc', 'config.document', 'curr_conf', 'extracted'),
    (5, 20, 1, 'js:curr_route', 'js.route', 'curr_route', 'extracted'),
    (6, 20, 1, 'nix:curr_pkg', 'nix.package', 'curr_pkg', 'extracted'),
    (7, 41, 1, 'node:empty_legacy', 'python.module', 'empty_legacy_mod', 'extracted'),
    (8, 400, 1, 'node:relocated_center', 'python.module', 'relocated_mod', 'extracted'),
    (9, 500, 1, 'node:high_legacy', 'python.module', 'high_legacy_mod', 'extracted'),
    (10, 5, 1, 'node:low_curr', 'python.module', 'low_curr_mod', 'extracted');

INSERT INTO canonical_edges (id, repository_id, graph_key_version, source_canonical_key, edge_kind, target_canonical_key, identity_metadata_hash, confidence) VALUES
    (1, 20, 1, 'node:curr_center', 'references', 'node:curr_neighbor', repeat('1', 64), 'extracted');

INSERT INTO raw_observations (id, repository_id, run_id, ordinal, schema_version, kind, source_id, path, payload_json, payload_hash) VALUES
    (1, 10, 1, 0, 1, 'obs:legacy', 'src_legacy', 'src/legacy.py', '{"metadata":{}}'::jsonb, repeat('a', 64)),
    (2, 20, 2, 0, 1, 'obs:curr', 'src_curr', 'src/curr.py', '{"metadata":{}}'::jsonb, repeat('b', 64)),
    (3, 20, 2, 1, 1, 'python.reference', 'src_curr', 'src/curr.py', '{"metadata":{}}'::jsonb, repeat('c', 64)),
    (4, 20, 2, 2, 1, 'terraform.file', 'src_curr', 'main.tf', '{"metadata":{}}'::jsonb, repeat('d', 64)),
    (5, 20, 2, 3, 1, 'openapi.document', 'src_curr', 'api.yaml', '{"metadata":{"spec_family":"openapi3"}}'::jsonb, repeat('e', 64)),
    (6, 20, 2, 4, 1, 'express.app', 'src_curr', 'app.js', '{"metadata":{}}'::jsonb, repeat('f', 64)),
    (7, 20, 2, 5, 1, 'nix.app', 'src_curr', 'flake.nix', '{"metadata":{}}'::jsonb, repeat('0', 64)),
    (8, 41, 3, 0, 1, 'obs:empty_legacy', 'src_empty', 'src/empty_legacy.py', '{"metadata":{}}'::jsonb, repeat('1', 64)),
    (9, 500, 7, 0, 1, 'obs:high_legacy', 'src_high', 'src/high_legacy.py', '{"metadata":{}}'::jsonb, repeat('2', 64)),
    (10, 5, 8, 0, 1, 'obs:low_curr', 'src_low', 'src/low_curr.py', '{"metadata":{}}'::jsonb, repeat('3', 64));

INSERT INTO raw_observations
    (id, repository_id, run_id, ordinal, schema_version, kind, source_id, path, payload_json, payload_hash)
SELECT 1000 + row_number() OVER (), r.repository_id, r.id, 10 + k.ordinal * 2 + n, 1,
       k.kind, 'fixture', 'fixture.txt', '{}'::jsonb, repeat('4', 64)
FROM runs r CROSS JOIN (VALUES (1, 'python.reference'), (2, 'terraform.file'),
    (3, 'openapi.document'), (4, 'express.app'), (5, 'nix.app')) k(ordinal, kind)
CROSS JOIN generate_series(0, 1) n WHERE r.repository_id != 20;
"""
    run_psql([database.psql_command, *database.psql_args, "-X", "-v", "ON_ERROR_STOP=1"], input_text=sql)


def _object_rows(payload: object) -> list[dict[str, Any]]:
    assert isinstance(payload, list)
    rows: list[dict[str, Any]] = []
    for row in payload:
        assert isinstance(row, dict)
        assert all(isinstance(key, str) for key in row)
        rows.append(row)
    return rows


def _read_nodes(database: PostgresContainerDatabase, root: str, identity: str | None) -> list[dict[str, Any]]:
    sql = build_canonical_node_search_sql(root_path=root, query="", kind=None, limit=10, offset=0, repository_identity=identity)
    return _object_rows(execute_json_readback(sql, psql_args=database.psql_args, psql_command=database.psql_command, label="nodes", expected_shape="array"))


def _read_observations(database: PostgresContainerDatabase, root: str, identity: str | None) -> list[dict[str, Any]]:
    sql = build_mcp_search_sql(
        root_path=root, target="observations", query="", limit=10, offset=0, include_raw=True,
        node_search_sql=build_canonical_node_search_sql, file_search_sql=build_file_source_search_sql,
        sql_literal=sql_literal, like_escape=escape_readback_like_pattern, error_type=Exception, repository_identity=identity,
    )
    return _object_rows(execute_json_readback(sql, psql_args=database.psql_args, psql_command=database.psql_command, label="obs", expected_shape="array"))


def _read_files(database: PostgresContainerDatabase, root: str, identity: str | None) -> list[dict[str, Any]]:
    sql = build_file_source_search_sql(root_path=root, query="", path=None, limit=10, offset=0, repository_identity=identity)
    return _object_rows(execute_json_readback(sql, psql_args=database.psql_args, psql_command=database.psql_command, label="files", expected_shape="array"))


def _read_summary(
    database: PostgresContainerDatabase, builder_fn: Callable[..., str], *, root_path: str, identity: str | None, label: str,
) -> dict[str, Any]:
    sql = _build_summary_sql(builder_fn, root_path=root_path, repository_identity=identity)
    payload = execute_json_readback(sql, psql_args=database.psql_args, psql_command=database.psql_command, label=label, expected_shape="object")
    assert isinstance(payload, dict)
    return payload


def test_all_ten_identity_aware_surfaces_readback_and_precedence() -> None:
    with _disposable_database() as database:
        _setup_fixtures(database)
        root, identity = "/workspace/alpha", "repo1:alpha"

        # 1. Canonical nodes surface
        nodes = _read_nodes(database, root, identity)
        node_keys = [n["canonical_key"] for n in nodes]
        assert "node:curr_center" in node_keys and "node:legacy_center" not in node_keys

        # 2. Raw observations surface
        obs = _read_observations(database, root, identity)
        obs_kinds = [o["kind"] for o in obs]
        assert "obs:curr" in obs_kinds and "obs:legacy" not in obs_kinds

        # 3. Files surface
        files = _read_files(database, root, identity)
        file_paths = [f["path"] for f in files]
        assert "src/curr.py" in file_paths and "src/legacy.py" not in file_paths

        # 4. Project summary surface
        proj = _read_summary(database, build_canonical_storage_summary_query_sql, root_path=root, identity=identity, label="project")
        assert proj["repository_name"] == "alpha_current" and proj["latest_run_id"] == 2

        # 5. Canonical neighborhood surface
        nh_sql = build_canonical_neighborhood_query_sql(root, node="node:curr_center", repository_identity=identity)
        nh = execute_json_readback(nh_sql, psql_args=database.psql_args, psql_command=database.psql_command, label="nh", expected_shape="object")
        assert isinstance(nh, dict)
        assert nh["center"]["canonical_key"] == "node:curr_center"
        assert any(e["target_canonical_key"] == "node:curr_neighbor" for e in nh.get("edges", []))

        # 6-10. Five language summaries
        for builder, count_key in LANGUAGE_SUMMARIES:
            summary = _read_summary(database, builder, root_path=root, identity=identity, label=count_key)
            assert summary["repository_name"] == "alpha_current"
            assert summary[count_key] == 1

        # Conflicting ID order inversion: identity row (id=5) wins over legacy row (id=500)
        inv_proj = _read_summary(database, build_canonical_storage_summary_query_sql, root_path="/workspace/inverse", identity="repo1:inverse", label="inv")
        assert inv_proj["repository_name"] == "low_current"


def test_postgres_nulls_last_and_deterministic_lowest_id_fallback() -> None:
    with _disposable_database() as database:
        _setup_fixtures(database)

        # Duplicate roots are prohibited in the migrated schema. Relax only this
        # disposable fixture to characterize deterministic handling of damaged data.
        database.psql_scalar("ALTER TABLE repositories DROP CONSTRAINT repositories_root_path_key;")
        database.psql_scalar("UPDATE repositories SET root_path = '/workspace/tie' WHERE id = 200;")
        # Fallback to lowest ID among legacy rows: tie_first (100) vs tie_second (200)
        proj_tie = _read_summary(database, build_canonical_storage_summary_query_sql, root_path="/workspace/tie", identity="repo1:missing", label="tie")
        assert proj_tie["repository_name"] == "tie_first"
        for builder, count_key in LANGUAGE_SUMMARIES:
            summary = _read_summary(database, builder, root_path="/workspace/tie", identity="repo1:missing", label=count_key)
            assert summary["repository_name"] == "tie_first"
            assert summary[count_key] == 2

        # Direct PostgreSQL ordering verification for NULLS LAST
        raw_order_sql = (
            "SELECT id FROM repositories WHERE id IN (10, 20) "
            "ORDER BY (repository_identity = 'repo1:alpha') DESC NULLS LAST, id LIMIT 1;"
        )
        assert database.psql_scalar(raw_order_sql) == "20"


def test_unrelated_identity_exclusion_and_relocation() -> None:
    with _disposable_database() as database:
        _setup_fixtures(database)

        # Unrelated identity sharing root: excluded when querying for different identity
        assert _read_nodes(database, "/workspace/unrelated_root", "repo1:other_missing") == []
        unrelated_proj = _read_summary(
            database, build_canonical_storage_summary_query_sql,
            root_path="/workspace/unrelated_root", identity="repo1:other_missing", label="unrelated"
        )
        assert unrelated_proj["repository_name"] is None

        # Relocated repository: queried with new path, matches stable identity
        reloc_proj = _read_summary(
            database, build_canonical_storage_summary_query_sql,
            root_path="/new/relocated/path", identity="repo1:relocated", label="relocated"
        )
        assert reloc_proj["repository_name"] == "relocated_current"
        for builder, count_key in LANGUAGE_SUMMARIES:
            unrelated = _read_summary(database, builder, root_path="/workspace/unrelated_root", identity="repo1:missing", label=count_key)
            assert unrelated["repository_name"] is None and unrelated[count_key] == 0
            relocated = _read_summary(database, builder, root_path="/new/relocated/path", identity="repo1:relocated", label=count_key)
            assert relocated["repository_name"] == "relocated_current"
            assert relocated[count_key] == 2


def test_empty_current_data_does_not_fallback() -> None:
    with _disposable_database() as database:
        _setup_fixtures(database)
        root, identity = "/workspace/empty", "repo1:empty"

        assert _read_nodes(database, root, identity) == []
        assert _read_files(database, root, identity) == []
        assert _read_observations(database, root, identity) == []

        proj = _read_summary(database, build_canonical_storage_summary_query_sql, root_path=root, identity=identity, label="empty")
        assert proj["repository_name"] == "empty_current"
        assert proj["canonical_nodes"] == 0 and proj["files"] == 0
        for builder, count_key in LANGUAGE_SUMMARIES:
            summary = _read_summary(database, builder, root_path=root, identity=identity, label=count_key)
            assert summary["repository_name"] == "empty_current"
            assert summary[count_key] == 0


def test_requested_root_payload_invariance_and_redaction() -> None:
    with _disposable_database() as database:
        _setup_fixtures(database)
        req_root, identity = "/requested/custom/path", "repo1:relocated"

        proj = _read_summary(database, build_canonical_storage_summary_query_sql, root_path=req_root, identity=identity, label="proj")
        assert proj["root_path"] == req_root

        for builder, label in (
            (build_python_summary_query_sql, "py"),
            (build_terraform_summary_query_sql, "tf"),
            (build_openapi_summary_query_sql, "oa"),
            (build_js_framework_summary_query_sql, "js"),
        ):
            summary = _read_summary(database, builder, root_path=req_root, identity=identity, label=label)
            assert summary["root_path"] == req_root

        nix_sum = _read_summary(database, build_nix_summary_query_sql, root_path=req_root, identity=identity, label="nix")
        assert nix_sum["root_path"] == "[root-path]"


def test_generated_sql_predicates_and_identity_validation() -> None:
    root, identity = "/workspace/alpha", "repo1:alpha"

    # Predicates incorporate DESC NULLS LAST and ascending id tie breaker
    node_sql = build_canonical_node_search_sql(root_path=root, query="", kind=None, limit=5, offset=0, repository_identity=identity)
    assert f"repository_identity = {sql_literal(identity)}" in node_sql
    assert "DESC NULLS LAST, id LIMIT 1" in node_sql

    file_sql = build_file_source_search_sql(root_path=root, query="", path=None, limit=5, offset=0, repository_identity=identity)
    assert f"repository_identity = {sql_literal(identity)}" in file_sql

    obs_sql = build_mcp_search_sql(
        root_path=root, target="observations", query="", limit=5, offset=0, include_raw=False,
        node_search_sql=build_canonical_node_search_sql, file_search_sql=build_file_source_search_sql,
        sql_literal=sql_literal, like_escape=escape_readback_like_pattern, error_type=Exception,
        repository_identity=identity,
    )
    assert f"repository_identity = {sql_literal(identity)}" in obs_sql

    proj_sql = build_canonical_storage_summary_query_sql(root, repository_identity=identity)
    assert f"repository_identity = {sql_literal(identity)}" in proj_sql

    nh_sql = build_canonical_neighborhood_query_sql(root, node="node:1", repository_identity=identity)
    assert f"repository_identity = {sql_literal(identity)}" in nh_sql

    for builder in (
        build_python_summary_query_sql,
        build_terraform_summary_query_sql,
        build_openapi_summary_query_sql,
        build_js_framework_summary_query_sql,
        build_nix_summary_query_sql,
    ):
        sql = _build_summary_sql(builder, root_path=root, repository_identity=identity)
        assert f"repository_identity = {sql_literal(identity)}" in sql
        assert "DESC NULLS LAST, id LIMIT 1" in sql

        # Historical root-only baseline without identity
        sql_no_id = _build_summary_sql(builder, root_path=root, repository_identity=None)
        assert f"repositories.root_path = {sql_literal(root)}" in sql_no_id

    # Schema errors on invalid repository identities
    for bad_id in ("bad with spaces", "repo1:bad;injection", "invalid_prefix:foo"):
        with pytest.raises(StorageSchemaError):
            build_repository_filter_sql(root, repository_identity=bad_id)
