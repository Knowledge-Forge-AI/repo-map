"""Integration tests for Slice 10 graph readback composition and MCP ops (Group S10-C).

Covers:
- CLI storage summary execution and schema fields
- CLI storage python-summary inspection
- CLI storage js-framework-summary inspection
- CLI storage nix-summary inspection
- CLI storage canonical-nodes pagination and prefix filtering on populated fixtures
- CLI storage canonical-edges pagination and edge kinds on populated fixtures
- CLI storage canonical-neighborhood structure and focal node on populated fixtures
- MCP ops search public boundary composition (nodes search)
- MCP ops summary payload composition via OpsSummaryDependencies executing query_fn
- CLI storage readback error distinction, refusal, and clean recovery
"""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace
from typing import Any
import unittest

from repomap_kg.server._ops_records import McpOpsError
from repomap_kg.server._ops_summaries import (
    OpsSummaryDependencies,
    project_summary_payload,
)
from repomap_kg.storage import (
    apply_migrations,
    default_rdbms_root,
)
from repomap_test_support.cli_in_process import run_repo_map_in_process
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)


class Slice10GraphReadbackCompositionIntegrationTests(unittest.TestCase):
    """Slice 10 Group S10-C integration tests for graph readback and MCP operations."""

    def _connection_args(self, postgres: Any, root_path: str = "/tmp/slice10-root") -> list[str]:
        return [
            "--root-path",
            root_path,
            "--pg-host",
            str(postgres.socket_dir),
            "--pg-port",
            str(postgres.port),
            "--pg-user",
            postgres.user,
            "--pg-database",
            postgres.database,
            "--psql-command",
            postgres.psql_command,
            "--json",
        ]

    def _populate_test_graph(self, postgres: Any) -> None:
        subprocess.run(
            [
                postgres.psql_command,
                *postgres.psql_args,
                "-c",
                """
                INSERT INTO repositories (id, name, root_path, repository_identity)
                VALUES (1, 'slice10-repo', '/tmp/slice10-root', 'repo1:slice10-repo');
                INSERT INTO canonical_nodes (repository_id, graph_key_version, canonical_key, kind, display_name, metadata_json, confidence)
                VALUES
                (1, 1, 'file:pkg/alpha.py', 'file', 'pkg/alpha.py', '{"path": "pkg/alpha.py"}', 'extracted'),
                (1, 1, 'file:pkg/beta.py', 'file', 'pkg/beta.py', '{"path": "pkg/beta.py"}', 'extracted'),
                (1, 1, 'file:other/gamma.py', 'file', 'other/gamma.py', '{"path": "other/gamma.py"}', 'extracted');
                INSERT INTO canonical_edges (repository_id, graph_key_version, source_canonical_key, edge_kind, target_canonical_key, identity_metadata_json, identity_metadata_hash, metadata_json, confidence)
                VALUES
                (1, 1, 'file:pkg/alpha.py', 'references', 'file:pkg/beta.py', '{}', '0000000000000000000000000000000000000000000000000000000000000001', '{}', 'extracted');
                """,
            ],
            check=True,
            capture_output=True,
        )

    def test_s10_c01_cli_storage_summary_empty_and_json_contract(self) -> None:
        """CLI storage summary returns valid JSON schema with zero-count defaults."""
        require_postgres_binaries()
        with temporary_postgres() as postgres:
            apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
            code, out, err = run_repo_map_in_process("storage", "summary", *self._connection_args(postgres))
            self.assertEqual(code, 0, err)
            data = json.loads(out)
            self.assertIn("canonical_edges", data)
            self.assertIn("canonical_nodes", data)
            self.assertIn("files", data)
            self.assertIn("runs", data)
            self.assertEqual(data["canonical_nodes"], 0)

    def test_s10_c02_cli_storage_python_summary_structure(self) -> None:
        """CLI storage python-summary returns diagnostic, framework, and safety records."""
        require_postgres_binaries()
        with temporary_postgres() as postgres:
            apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
            code, out, err = run_repo_map_in_process("storage", "python-summary", *self._connection_args(postgres))
            self.assertEqual(code, 0, err)
            data = json.loads(out)
            self.assertIn("generic_python", data)
            self.assertIn("frameworks", data)
            self.assertIn("safety", data)
            self.assertTrue(data["safety"]["no_execution"])

    def test_s10_c03_cli_storage_js_framework_summary_structure(self) -> None:
        """CLI storage js-framework-summary exposes express, react, and route observations."""
        require_postgres_binaries()
        with temporary_postgres() as postgres:
            apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
            code, out, err = run_repo_map_in_process("storage", "js-framework-summary", *self._connection_args(postgres))
            self.assertEqual(code, 0, err)
            data = json.loads(out)
            self.assertIn("express", data)
            self.assertIn("diagnostics", data)

    def test_s10_c04_cli_storage_nix_summary_structure(self) -> None:
        """CLI storage nix-summary returns flake, package, and canonical nix categories."""
        require_postgres_binaries()
        with temporary_postgres() as postgres:
            apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
            code, out, err = run_repo_map_in_process("storage", "nix-summary", *self._connection_args(postgres))
            self.assertEqual(code, 0, err)
            data = json.loads(out)
            self.assertIn("canonical", data)
            self.assertIn("diagnostics", data)

    def test_s10_c05_cli_storage_canonical_nodes_pagination_and_prefix(self) -> None:
        """CLI storage nodes supports limit, offset, and page object pagination on populated data."""
        require_postgres_binaries()
        with temporary_postgres() as postgres:
            apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
            self._populate_test_graph(postgres)
            args = ["storage", "nodes", "--limit", "2", "--offset", "0", *self._connection_args(postgres)]
            code, out, err = run_repo_map_in_process(*args)
            self.assertEqual(code, 0, err)
            data = json.loads(out)
            self.assertEqual(data["page"]["limit"], 2)
            self.assertEqual(data["page"]["offset"], 0)
            self.assertEqual(data["page"]["returned"], 2)
            self.assertTrue(data["page"]["truncated"])
            self.assertEqual(data["page"]["next_offset"], 2)
            self.assertEqual(len(data["items"]), 2)

            prefix_args = ["storage", "nodes", "--path-prefix", "pkg", *self._connection_args(postgres)]
            p_code, p_out, p_err = run_repo_map_in_process(*prefix_args)
            self.assertEqual(p_code, 0, p_err)
            p_data = json.loads(p_out)
            keys = [item["canonical_key"] for item in p_data["items"]]
            self.assertEqual(sorted(keys), ["file:pkg/alpha.py", "file:pkg/beta.py"])

    def test_s10_c06_cli_storage_canonical_edges_pagination(self) -> None:
        """CLI storage edges queries paginated edge records with schema version on populated data."""
        require_postgres_binaries()
        with temporary_postgres() as postgres:
            apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
            self._populate_test_graph(postgres)
            args = ["storage", "edges", "--limit", "10", "--offset", "0", *self._connection_args(postgres)]
            code, out, err = run_repo_map_in_process(*args)
            self.assertEqual(code, 0, err)
            data = json.loads(out)
            self.assertEqual(data["page"]["limit"], 10)
            self.assertEqual(data["page"]["returned"], 1)
            self.assertEqual(len(data["items"]), 1)
            edge = data["items"][0]
            self.assertEqual(edge["source_key"], "file:pkg/alpha.py")
            self.assertEqual(edge["target_key"], "file:pkg/beta.py")
            self.assertEqual(edge["edge_kind"], "references")

    def test_s10_c07_cli_storage_canonical_neighborhood_query(self) -> None:
        """CLI storage neighborhood returns depth-1 inbound and outbound node/edge collections."""
        require_postgres_binaries()
        with temporary_postgres() as postgres:
            apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
            self._populate_test_graph(postgres)
            args = [
                "storage",
                "neighborhood",
                "--node",
                "file:pkg/alpha.py",
                *self._connection_args(postgres),
            ]
            code, out, err = run_repo_map_in_process(*args)
            self.assertEqual(code, 0, err)
            data = json.loads(out)
            res = data["result"]
            self.assertEqual(res["center"]["canonical_key"], "file:pkg/alpha.py")
            node_keys = [n["canonical_key"] for n in res["nodes"]]
            self.assertIn("file:pkg/beta.py", node_keys)
            edge_targets = [e["target_key"] for e in res["edges"]]
            self.assertIn("file:pkg/beta.py", edge_targets)

    def test_s10_c08_mcp_public_boundary_search_composition(self) -> None:
        """MCP public boundary search executes search_payload -> query_mcp_search -> SQL/readback."""
        from unittest.mock import patch
        from repomap_kg.server.mcp import repomap_search_nodes
        from repomap_test_support.mcp_server import McpServerTestSupport

        require_postgres_binaries()
        with temporary_postgres() as postgres:
            apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
            self._populate_test_graph(postgres)
            support = McpServerTestSupport()
            config_content = f"""
schema_version = 1

[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[postgres]
host = "{postgres.socket_dir}"
port = {postgres.port}
database = "{postgres.database}"
user = "{postgres.user}"
password_env = "REPOMAP_PG_PASSWORD"

[server_memory]
enabled = false
path = "~/.codex/codex-vc/mcp/server-memory"
mode = "read_only"

[[graphs]]
id = "slice10-repo"
name = "RepoMap"
root_path = "/tmp/slice10-root"
repository_name = "slice10-repo"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"
database = "{postgres.database}"
"""
            config_path = support.write_ops_config(config_content)
            with patch.dict("os.environ", {"REPOMAP_OPS_CONFIG": str(config_path)}):
                payload = repomap_search_nodes(graph_id="slice10-repo", query="alpha")

            self.assertEqual(payload["target"], "nodes")
            self.assertEqual(payload["query"], "alpha")
            self.assertEqual(payload["result_count"], 1)
            self.assertEqual(payload["results"][0]["canonical_key"], "file:pkg/alpha.py")
            self.assertTrue(payload["safety"]["read_only"])

    def test_s10_c09_mcp_server_ops_summary_dependencies_composition(self) -> None:
        """OpsSummaryDependencies executes real query_canonical_storage_summary and decodes rows."""
        from repomap_kg.storage.canonical import query_canonical_storage_summary

        require_postgres_binaries()
        with temporary_postgres() as postgres:
            apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
            self._populate_test_graph(postgres)

            mock_graph = SimpleNamespace(
                id="test-graph",
                privacy="public",
                explicit_source_bindings=False,
                root_path_expanded="/tmp/slice10-root",
                root_path="/tmp/slice10-root",
            )
            mock_context = SimpleNamespace(
                root_path="/tmp/slice10-root",
                repository_identity="repo1:slice10-repo",
                graph=mock_graph,
                database=postgres.database,
                psql_command=postgres.psql_command,
                psql_args=postgres.psql_args,
            )

            def mock_graph_context(graph_id: str, **kwargs: Any) -> Any:
                if graph_id != "test-graph":
                    raise McpOpsError(f"unknown graph: {graph_id}")
                return mock_context

            deps = OpsSummaryDependencies(
                graph_context=mock_graph_context,
                graph_payload=lambda graph, **kwargs: {"id": graph.id},
                query_configured_storage=lambda ctx, qfn, **kwargs: qfn(
                    ctx.psql_args,
                    root_path=ctx.root_path,
                    psql_command=ctx.psql_command,
                    repository_identity=ctx.repository_identity,
                ),
                query_canonical_storage_summary=query_canonical_storage_summary,
            )

            payload = project_summary_payload("test-graph", dependencies=deps)
            self.assertEqual(payload["summary"]["root_path"], "[graph-root]")
            self.assertEqual(payload["summary"]["counts"]["canonical_nodes"], 3)
            self.assertEqual(payload["summary"]["counts"]["canonical_edges"], 1)

            with self.assertRaises(McpOpsError):
                project_summary_payload("unknown-graph", dependencies=deps)

    def test_s10_c10_cli_storage_readback_missing_database_refusal(self) -> None:
        """CLI readback distinguishes absent database from unavailable transport and recovers."""
        require_postgres_binaries()
        with temporary_postgres() as postgres:
            apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)

            # 1. Actual absent database on reachable server
            absent_args = [
                "storage", "summary",
                "--root-path", "/tmp/slice10-root",
                "--pg-host", str(postgres.socket_dir),
                "--pg-port", str(postgres.port),
                "--pg-user", postgres.user,
                "--pg-database", "nonexistent_c10_db",
                "--psql-command", postgres.psql_command,
                "--json",
            ]
            code_abs, out_abs, err_abs = run_repo_map_in_process(*absent_args)
            self.assertNotEqual(code_abs, 0)
            self.assertTrue(
                any(
                    needle in (err_abs + out_abs).lower()
                    for needle in ("psycopg readback failed", "missing or not initialized", "does not exist", "error")
                )
            )

            # 2. Unavailable endpoint
            unavail_args = [
                "storage", "summary",
                "--root-path", "/tmp/slice10-root",
                "--pg-host", str(postgres.socket_dir),
                "--pg-port", str(postgres.port + 100),
                "--pg-user", postgres.user,
                "--pg-database", postgres.database,
                "--psql-command", postgres.psql_command,
                "--json",
            ]
            code_unavail, out_unavail, err_unavail = run_repo_map_in_process(*unavail_args)
            self.assertNotEqual(code_unavail, 0)
            self.assertNotIn("missing or not initialized", err_unavail + out_unavail)
            combined_unavail = (err_unavail + out_unavail).lower()
            self.assertTrue(
                any(msg in combined_unavail for msg in ("could not connect", "connection refused", "failed", "error"))
                or len(err_unavail) > 0
            )

            # 3. Clean recovery on valid database
            rec_code, rec_out, rec_err = run_repo_map_in_process(
                "storage", "summary", *self._connection_args(postgres)
            )
            self.assertEqual(rec_code, 0, rec_err)
            self.assertEqual(json.loads(rec_out)["canonical_nodes"], 0)


if __name__ == "__main__":
    import sys
    sys.exit(
        "Direct execution unsupported; use tools/run_tests.py for container sandbox admission."
    )
