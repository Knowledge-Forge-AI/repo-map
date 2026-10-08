"""Named canonical read-store seam for the four migrated MCP tools (READSTORE1)."""

from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

from repomap_kg.server.canonical_read_store import (
    CanonicalEdgeExplanationQuery,
    CanonicalEdgeQuery,
    CanonicalNeighborhoodQuery,
    CanonicalNodeQuery,
    CanonicalStorageQueries,
    PostgresCanonicalReadStore,
)
from repomap_kg.storage import (
    CanonicalEdgeExplanationRecord,
    CanonicalEdgeRecord,
    CanonicalNeighborhoodRecord,
    CanonicalNodeRecord,
    StorageSchemaError,
    identity_metadata_hash,
)
from repomap_test_support.host_read_store_config import (
    NO_FALLBACK_GUARDS,
    fail_if_reached as _fail,
    patched_guards as _patched,
    setup_owned_config as _setup_owned_config,
    setup_owned_home,
)
from repomap_test_support.mcp_server import McpServerTestSupport

NODE = CanonicalNodeRecord(
    canonical_key="python.module:pkg.a", graph_key_version=1, kind="python.module",
    display_name="pkg.a", confidence="extracted", conflict=False, metadata={},
    first_seen_run_id=1, last_seen_run_id=2,
)
EDGE = CanonicalEdgeRecord(
    source_key="python.module:pkg.a", edge_kind="imports", target_key="python.module:pkg.b",
    graph_key_version=1, identity_metadata={"alias": "b"},
    identity_metadata_hash=identity_metadata_hash({"alias": "b"}), metadata={},
    confidence="extracted", conflict=False, first_seen_run_id=1, last_seen_run_id=2,
)
EXPLANATION = CanonicalEdgeExplanationRecord(edge=EDGE, evidence=())
NEIGHBORHOOD = CanonicalNeighborhoodRecord(center=NODE, nodes=(NODE,), edges=(EDGE,))
TOOL_CALLS = (
    ("repomap_canonical_nodes", {"kind": "python.module", "limit": 1, "offset": 3}),
    ("repomap_canonical_edges", {"kind": "imports", "source_key": "python.module:pkg.a", "limit": 2}),
    ("repomap_explain_canonical_edge", {
        "source_key": "python.module:pkg.a", "kind": "imports",
        "target_key": "python.module:pkg.b", "identity_metadata": {"alias": "b"},
        "evidence_limit": 4, "evidence_offset": 1,
    }),
    ("repomap_canonical_neighborhood", {
        "node": "python.module:pkg.a", "direction": "out", "node_limit": 5,
        "node_offset": 1, "edge_limit": 6, "edge_offset": 2,
    }),
)
EXPECTED_QUERIES = (
    CanonicalNodeQuery("python.module", None, None, 1, 2, 3),
    CanonicalEdgeQuery("imports", "python.module:pkg.a", None, 1, 3, 0),
    CanonicalEdgeExplanationQuery(
        "python.module:pkg.a", "imports", "python.module:pkg.b",
        identity_metadata_hash({"alias": "b"}), 1, 5, 1,
    ),
    CanonicalNeighborhoodQuery("python.module:pkg.a", "out", 1, 1, 6, 1, 7, 2),
)
PRIVATE_ENV = ("PGPASSWORD", "REPOMAP_PG_PASSWORD", "REPOMAP_READ_STATUS_PASSWORD")


class FakeCanonicalReadStore:
    def __init__(self) -> None:
        self.queries: list[object] = []

    def canonical_nodes(self, query: CanonicalNodeQuery):
        self.queries.append(query)
        return (NODE,)

    def canonical_edges(self, query: CanonicalEdgeQuery):
        self.queries.append(query)
        return (EDGE,)

    def canonical_edge_explanation(self, query: CanonicalEdgeExplanationQuery):
        self.queries.append(query)
        return EXPLANATION

    def canonical_neighborhood(self, query: CanonicalNeighborhoodQuery):
        self.queries.append(query)
        return NEIGHBORHOOD


def _recording_queries(calls: list[tuple[tuple, dict]]) -> CanonicalStorageQueries:
    def make(result):
        def query(*args, **kwargs):
            calls.append((args, kwargs))
            return result
        return query
    return CanonicalStorageQueries(
        nodes=make((NODE,)), edges=make((EDGE,)),
        edge_explanation=make(EXPLANATION), neighborhood=make(NEIGHBORHOOD),
        storage_summary=make(None),
    )


class CanonicalReadStoreDispatchTests(McpServerTestSupport):
    def _call_all(self, *, schema_version: int) -> list[dict]:
        from repomap_kg.server.mcp import handle_tool_call

        return [
            handle_tool_call(name, {"project": "repo-map", "result_schema_version": schema_version, **args})
            for name, args in TOOL_CALLS
        ]

    def test_four_tools_dispatch_through_named_store_with_unchanged_results(self) -> None:
        env = self.patch_mcp_and_ops_config(self.write_empty_mcp_config(), self.write_visible_ops_config())
        for schema_version in (1, 0):
            fake = FakeCanonicalReadStore()
            connections: list[Any] = []

            def factory(connection, _fake=fake):
                connections.append(connection)
                return _fake

            with env, patch("repomap_kg.server.mcp.canonical_read_store", factory):
                seam_results = self._call_all(schema_version=schema_version)
            with env, patch.multiple(
                "repomap_kg.server.mcp",
                query_canonical_node_records=lambda *a, **k: (NODE,),
                query_canonical_edge_records=lambda *a, **k: (EDGE,),
                query_canonical_edge_explanation=lambda *a, **k: EXPLANATION,
                query_canonical_neighborhood=lambda *a, **k: NEIGHBORHOOD,
            ):
                adapter_results = self._call_all(schema_version=schema_version)

            self.assertEqual(tuple(fake.queries), EXPECTED_QUERIES)
            self.assertEqual(seam_results, adapter_results)
            for connection in connections:
                self.assertEqual(connection.selection.graph_id, "repo-map")
                self.assertEqual(connection.root_path, "/tmp/fixture")
        self.assertEqual(seam_results[0]["structuredContent"][0]["canonical_key"], NODE.canonical_key)

    def test_invalid_arguments_and_graphs_refuse_before_store_access(self) -> None:
        from repomap_kg.server.mcp import RepoMapMcpError, handle_tool_call

        a, b = "python.module:a", "python.module:b"
        edge_args = {"source_key": a, "kind": "imports", "target_key": b}
        cases = (
            ("repomap_canonical_nodes", {"limit": 201}, "limit must be between 1 and 200"),
            ("repomap_canonical_nodes", {"offset": -1}, "offset must be a non-negative integer"),
            ("repomap_canonical_nodes", {"result_schema_version": 2}, "result schema version must be 0 or 1"),
            ("repomap_canonical_nodes", {"graph_key_version": 2}, "unsupported graph key version"),
            ("repomap_canonical_nodes", {"sql": "SELECT 1"}, "unexpected argument(s): sql"),
            ("repomap_canonical_edges", {"source_key": "x"},
             "invalid source canonical key: canonical key must include a namespace separator"),
            ("repomap_explain_canonical_edge", {**edge_args, "identity_metadata": "x"},
             "identity_metadata must be a JSON object"),
            ("repomap_explain_canonical_edge", {"kind": "imports", "target_key": b},
             "missing required argument(s): source_key"),
            ("repomap_explain_canonical_edge", {**edge_args, "evidence_limit": 201},
             "limit must be between 1 and 200"),
            ("repomap_canonical_neighborhood", {"node": a, "direction": "sideways"},
             "direction must be one of both, in, out"),
            ("repomap_canonical_neighborhood", {"node": a, "depth": 9},
             "storage neighborhood only supports depth 1"),
            ("repomap_canonical_nodes", {"project": "missing"},
             "unknown legacy MCP project or graph-registry graph_id: missing"),
            ("repomap_canonical_nodes", {"project": "disabled"}, "graph 'disabled' is not enabled"),
            ("repomap_canonical_nodes", {"project": "hidden"}, "graph 'hidden' is not MCP-visible"),
        )
        env = self.patch_mcp_and_ops_config(self.write_empty_mcp_config(), self.write_visible_ops_config())
        with env, patch("repomap_kg.server.mcp.canonical_read_store", _fail), patch(
            "repomap_kg.server.canonical_read_store.readback_postgres_authority", _fail
        ):
            for name, args, expected in cases:
                with self.subTest(name=name, args=args), self.assertRaises(RepoMapMcpError) as raised:
                    handle_tool_call(name, {"project": "repo-map", **args})
                self.assertEqual(str(raised.exception), expected)


class PostgresCanonicalReadStoreAdapterTests(McpServerTestSupport):
    def _connection(self, graph_id: str, **env: str):
        """Resolve a configured target and return its PostgreSQL-bound connection."""
        from repomap_kg.server.mcp import storage_connection

        with patch.dict("os.environ", {"REPOMAP_MCP_CONFIG": str(self.write_empty_mcp_config()), **env}, clear=True):
            target: Any = storage_connection(project=graph_id)
        return target.stores.canonical_store(target.selection).connection

    def _setup_home(self) -> Path:
        return setup_owned_home(self)

    def test_setup_owned_home_reads_with_projected_read_status_role(self) -> None:
        from repomap_kg.runtime.database_role_contract import read_read_status_password

        home = self._setup_home()
        ambient = {"PGPASSWORD": "ambient-admin", "REPOMAP_PG_PASSWORD": "ambient-admin"}
        for graph_id, root, database in (
            ("host-one", "/public/host-one", "repomap_host_one"),
            ("host-multi", "graph:host-multi", "repomap_host_multi"),
        ):
            connection = self._connection(graph_id, REPOMAP_HOME=str(home), **ambient)
            calls: list[tuple[tuple, dict]] = []
            with patch.dict("os.environ", ambient, clear=True):
                store = PostgresCanonicalReadStore(connection, _recording_queries(calls))
                store.canonical_nodes(EXPECTED_QUERIES[0])
                store.canonical_neighborhood(EXPECTED_QUERIES[3])
                self.assertEqual(dict(os.environ), ambient)
            for args, kwargs in calls:
                self.assertEqual(args, (["-h", "127.0.0.1", "-p", "55439", "-U", "repomap_read_status", "-d", database],))
                self.assertEqual(kwargs["password"], read_read_status_password(home))
                self.assertEqual(kwargs["root_path"], root)
                self.assertEqual(kwargs["repository_identity"], f"repo1:{graph_id}")
                self.assertEqual(kwargs["psql_command"], "psql")
            self.assertEqual(calls[1][1]["node_limit"], 6)

    def test_custom_config_file_keeps_configured_authority(self) -> None:
        home = self._setup_home()
        credential = home / "reader.secret"
        credential.write_text("custom-secret\n", encoding="utf-8")
        credential.chmod(0o600)
        custom = home / "custom.toml"
        custom.write_text(_setup_owned_config().replace(
            'user = "repomap"\npassword_env = "REPOMAP_PG_PASSWORD"',
            f'user = "custom_reader"\npassword_file = "{credential}"',
        ), encoding="utf-8")
        # `--config F` is not setup-owned even when F lives in the home, so the
        # admin-shaped default keeps its explicit credential and no projection.
        config_file = home / "repomap.rpl.toml"
        cases: tuple[tuple[Path, dict[str, str], str, str], ...] = (
            (custom, {}, "custom_reader", "custom-secret"),
            (config_file, {"REPOMAP_PG_PASSWORD": "operator-secret"}, "repomap", "operator-secret"),
        )
        for path, env, user, password in cases:
            connection = self._connection("host-one", REPOMAP_OPS_CONFIG=str(path), **env)
            calls: list[tuple[tuple, dict]] = []
            with patch.dict("os.environ", env, clear=True):
                PostgresCanonicalReadStore(connection, _recording_queries(calls)).canonical_edges(
                    EXPECTED_QUERIES[1]
                )
            self.assertEqual(calls[0][0][0][calls[0][0][0].index("-U") + 1], user)
            self.assertEqual(calls[0][1]["password"], password)

    def test_compose_style_read_status_environment_is_equivalent(self) -> None:
        env = {"REPOMAP_READ_STATUS_PASSWORD": "compose-read-secret"}
        connection = self._connection(
            "repo-map", REPOMAP_OPS_CONFIG=str(self.write_container_internal_ops_config()), **env
        )
        calls: list[tuple[tuple, dict]] = []
        with patch.dict("os.environ", env, clear=True):
            PostgresCanonicalReadStore(connection, _recording_queries(calls)).canonical_edge_explanation(
                EXPECTED_QUERIES[2]
            )
        self.assertEqual(calls[0][0], (["-h", "postgres", "-p", "5432", "-U", "repomap_read_status", "-d", "repomap_repo_map"],))
        self.assertEqual(calls[0][1]["password"], "compose-read-secret")
        self.assertEqual(calls[0][1]["repository_identity"], "repo1:repo-map")

    def test_legacy_explicit_connection_call_is_unchanged(self) -> None:
        from repomap_kg.server.mcp_core import StorageConnection

        connection = StorageConnection(
            root_path="/tmp/legacy", pg_database="legacy_db", root_path_display="[explicit-root]",
            pg_host="db.internal", pg_port="6543", pg_user="reader", psql_command="/opt/bin/psql",
        )
        seam_calls: list[tuple[tuple, dict]] = []
        PostgresCanonicalReadStore(connection, _recording_queries(seam_calls)).canonical_nodes(
            EXPECTED_QUERIES[0]
        )
        self.assertEqual(seam_calls, [(
            (["-h", "db.internal", "-p", "6543", "-U", "reader", "-d", "legacy_db"],),
            {"psql_command": "/opt/bin/psql", "root_path": "/tmp/legacy", "kind": "python.module",
             "canonical_key": None, "path_prefix": None, "graph_key_version": 1, "limit": 2, "offset": 3},
        )])

    def test_host_failure_refuses_without_container_fallback_or_lifecycle(self) -> None:
        from repomap_kg.server.mcp import RepoMapMcpError, handle_tool_call

        unresolved = 'could not translate host name "postgres" to address'
        guards = NO_FALLBACK_GUARDS
        env = self.patch_mcp_and_ops_config(
            self.write_empty_mcp_config(), self.write_container_internal_ops_config()
        )
        for error, expected in ((StorageSchemaError(unresolved), unresolved), (OSError("psql missing"), "psql missing")):
            def failing(*_args, _error=error, **_kwargs):
                raise _error

            with env, patch("repomap_kg.server.mcp.query_canonical_node_records", failing):
                with _patched(guards), self.assertRaises(RepoMapMcpError) as raised:
                    handle_tool_call("repomap_canonical_nodes", {"project": "repo-map"})
            self.assertEqual(str(raised.exception), expected)

    def test_seam_import_boundary_and_pure_construction(self) -> None:
        import repomap_kg.server.canonical_read_store as module

        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        imported = {
            node.module if isinstance(node, ast.ImportFrom) else alias.name
            for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        forbidden = ("subprocess", "shutil", "repomap_kg.runtime.local", "repomap_kg.ops.refresh",
                     "repomap_kg.ops._refresh_psql", "repomap_kg.storage.staged_ingestion",
                     "repomap_kg.ops.direct_publication", "repomap_kg.graph.multi_source_pipeline",
                     "repomap_kg.coordinator")
        self.assertFalse({name for name in imported if name and name.startswith(forbidden)})
        connection = self._connection(
            "repo-map", REPOMAP_OPS_CONFIG=str(self.write_visible_ops_config())
        )
        with patch.object(module, "readback_postgres_authority", _fail):
            queries = CanonicalStorageQueries(nodes=_fail, edges=_fail, edge_explanation=_fail, neighborhood=_fail,
                                              storage_summary=_fail)
            store = PostgresCanonicalReadStore(connection, queries)
        self.assertIs(store.connection, connection)
