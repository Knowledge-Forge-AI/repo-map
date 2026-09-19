"""Unit tests for MCP search and readback with relocation-stable repository identity."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from repomap_kg.server.mcp import (
    RepoMapMcpError,
    repomap_neighborhood,
    repomap_project_summary,
    repomap_search_files,
    repomap_search_nodes,
    repomap_search_observations,
)
from repomap_kg.server.mcp_search_sql import build_mcp_search_sql
from repomap_kg.storage import StorageSchemaError
from repomap_kg.storage.graph_readback_sql import (
    build_canonical_node_search_sql,
    build_file_source_search_sql,
    build_repository_filter_sql,
)
from repomap_kg.storage.sql_canonical import (
    build_canonical_neighborhood_query_sql,
    build_canonical_storage_summary_query_sql,
)
from repomap_test_support.mcp_server import McpServerTestSupport


class McpSearchIdentityReadbackUnitTests(McpServerTestSupport):
    def test_build_repository_filter_sql_with_identity(self) -> None:
        sql = build_repository_filter_sql(
            root_path="/app/fixture",
            repository_identity="repo1:fixture",
        )
        self.assertIn("repositories.id = (SELECT id FROM repositories WHERE", sql)
        self.assertIn("repository_identity = 'repo1:fixture'", sql)
        self.assertIn("OR (repository_identity IS NULL AND root_path = '/app/fixture')", sql)
        self.assertIn("ORDER BY (repository_identity = 'repo1:fixture') DESC NULLS LAST, id LIMIT 1)", sql)

    def test_build_repository_filter_sql_without_identity(self) -> None:
        sql = build_repository_filter_sql(
            root_path="/app/fixture",
            repository_identity=None,
        )
        self.assertEqual(sql, "repositories.root_path = '/app/fixture'")

    def test_build_repository_filter_sql_invalid_identity(self) -> None:
        with self.assertRaises(StorageSchemaError):
            build_repository_filter_sql(
                root_path="/app/fixture",
                repository_identity="invalid identity with spaces",
            )
        with self.assertRaises(StorageSchemaError):
            build_repository_filter_sql(
                root_path="/app/fixture",
                repository_identity="repo1:bad;injection",
            )

    def test_node_and_file_search_sql_incorporates_identity_filter(self) -> None:
        node_sql = build_canonical_node_search_sql(
            root_path="/app/fixture",
            query="add",
            kind=None,
            limit=10,
            offset=0,
            repository_identity="repo1:fixture",
        )
        self.assertIn("repository_identity = 'repo1:fixture'", node_sql)
        self.assertIn("canonical_nodes.canonical_key", node_sql)

        file_sql = build_file_source_search_sql(
            root_path="/app/fixture",
            query="add",
            path=None,
            limit=10,
            offset=0,
            repository_identity="repo1:fixture",
        )
        self.assertIn("repository_identity = 'repo1:fixture'", file_sql)
        self.assertIn("files.path", file_sql)

    def test_mcp_search_observations_sql_incorporates_identity_filter(self) -> None:
        from repomap_kg.storage import sql_literal
        from repomap_kg.server._ops_search import like_escape, McpOpsError

        obs_sql = build_mcp_search_sql(
            root_path="/app/fixture",
            target="observations",
            query="add",
            kind=None,
            path=None,
            limit=10,
            offset=0,
            include_raw=False,
            node_search_sql=build_canonical_node_search_sql,
            file_search_sql=build_file_source_search_sql,
            sql_literal=sql_literal,
            like_escape=like_escape,
            error_type=McpOpsError,
            repository_identity="repo1:fixture",
        )
        self.assertIn("repository_identity = 'repo1:fixture'", obs_sql)
        self.assertIn("raw_observations", obs_sql)

    def test_canonical_storage_summary_and_neighborhood_sql_incorporate_identity_filter(self) -> None:
        summary_sql = build_canonical_storage_summary_query_sql(
            root_path="/app/fixture",
            repository_identity="repo1:fixture",
        )
        self.assertIn("repository_identity = 'repo1:fixture'", summary_sql)

        neighborhood_sql = build_canonical_neighborhood_query_sql(
            root_path="/app/fixture",
            node="func:add",
            repository_identity="repo1:fixture",
        )
        self.assertIn("repository_identity = 'repo1:fixture'", neighborhood_sql)

    def test_search_handlers_forward_repository_identity(self) -> None:
        config_path = self.write_ops_config(self.visible_ops_config())
        with (
            patch.dict("os.environ", {"REPOMAP_OPS_CONFIG": str(config_path)}, clear=True),
            patch("repomap_kg.server.ops.query_mcp_search") as mock_query,
        ):
            mock_query.return_value = {"results": [], "total": 0, "has_more": False}

            repomap_search_nodes(graph_id="repo-map", query="add")
            self.assertEqual(mock_query.call_args.kwargs["repository_identity"], "repo1:repo-map")

            repomap_search_files(graph_id="repo-map", query="add")
            self.assertEqual(mock_query.call_args.kwargs["repository_identity"], "repo1:repo-map")

            repomap_search_observations(graph_id="repo-map", query="add")
            self.assertEqual(mock_query.call_args.kwargs["repository_identity"], "repo1:repo-map")

    def test_summary_and_neighborhood_forward_repository_identity(self) -> None:
        config_path = self.write_ops_config(self.visible_ops_config())
        fake_summary = MagicMock(
            root_path="/tmp/fixture",
            repository_name="repo-map",
            latest_run_id=1,
            runs=1,
            files=1,
            raw_observations=1,
            canonical_nodes=1,
            canonical_edges=1,
            canonical_evidence=1,
        )
        fake_neighborhood = MagicMock(
            center=MagicMock(canonical_key="node:1"),
            nodes=(),
            edges=(),
        )
        with (
            patch.dict("os.environ", {"REPOMAP_OPS_CONFIG": str(config_path)}, clear=True),
            patch("repomap_kg.server.ops.query_configured_storage") as mock_storage,
        ):
            mock_storage.return_value = fake_summary
            repomap_project_summary(graph_id="repo-map")
            self.assertEqual(mock_storage.call_args.kwargs["repository_identity"], "repo1:repo-map")

            mock_storage.return_value = fake_neighborhood
            repomap_neighborhood(graph_id="repo-map", node="node:1")
            self.assertEqual(mock_storage.call_args.kwargs["repository_identity"], "repo1:repo-map")

    def test_schema_error_maps_to_public_mcp_error(self) -> None:
        config_path = self.write_ops_config(self.visible_ops_config())
        with (
            patch.dict("os.environ", {"REPOMAP_OPS_CONFIG": str(config_path)}, clear=True),
            patch(
                "repomap_kg.server.ops.McpOpsGraphContext.repository_identity",
                new_callable=lambda: "invalid:identity:shape",
            ),
        ):
            with self.assertRaises(RepoMapMcpError):
                repomap_search_nodes(graph_id="repo-map", query="add")

    def test_repository_filter_precedence_in_database(self) -> None:
        import sqlite3

        con = sqlite3.connect(":memory:")
        con.execute(
            "CREATE TABLE repositories ("
            "id INTEGER PRIMARY KEY, "
            "repository_identity TEXT, "
            "root_path TEXT)"
        )
        con.execute(
            "INSERT INTO repositories (id, repository_identity, root_path) VALUES "
            "(10, NULL, '/app/fixture'), "
            "(20, 'repo1:fixture', 'graph:fixture'), "
            "(30, 'repo1:other', '/app/fixture')"
        )
        sql = (
            "SELECT id FROM repositories WHERE "
            + build_repository_filter_sql(
                root_path="/app/fixture",
                repository_identity="repo1:fixture",
            )
        )
        # 1. Identity-bearing row preferred in unreconciled 2-row state
        rows = con.execute(sql).fetchall()
        self.assertEqual(rows, [(20,)])

        # 2. Pure legacy fallback when identity row does not exist
        con.execute("DELETE FROM repositories WHERE id = 20")
        rows = con.execute(sql).fetchall()
        self.assertEqual(rows, [(10,)])

        # 3. Fail-closed: unrelated identity at same physical root does not match
        con.execute("DELETE FROM repositories WHERE id = 10")
        rows = con.execute(sql).fetchall()
        self.assertEqual(rows, [])

    def test_language_summaries_forward_repository_identity(self) -> None:
        from repomap_kg.server.mcp import (
            repomap_js_framework_summary,
            repomap_nix_summary,
            repomap_openapi_summary,
            repomap_python_summary,
            repomap_terraform_summary,
        )
        from repomap_kg.storage import (
            JSFrameworkSummaryRecord,
            NixSummaryRecord,
            OpenAPISummaryRecord,
            PythonSummaryRecord,
            TerraformSummaryRecord,
        )

        config_path = self.write_ops_config(self.visible_ops_config())
        with (
            patch.dict("os.environ", {"REPOMAP_OPS_CONFIG": str(config_path)}, clear=True),
            patch("repomap_kg.server.ops.query_configured_storage") as mock_storage,
        ):
            mock_storage.return_value = MagicMock(spec=PythonSummaryRecord, to_dict=lambda: {"root_path": "/app/fixture"})
            repomap_python_summary(graph_id="repo-map")
            self.assertEqual(mock_storage.call_args.kwargs["repository_identity"], "repo1:repo-map")

            mock_storage.return_value = MagicMock(spec=TerraformSummaryRecord, to_dict=lambda: {"root_path": "/app/fixture"})
            repomap_terraform_summary(graph_id="repo-map")
            self.assertEqual(mock_storage.call_args.kwargs["repository_identity"], "repo1:repo-map")

            mock_storage.return_value = MagicMock(spec=OpenAPISummaryRecord, to_dict=lambda: {"root_path": "/app/fixture"})
            repomap_openapi_summary(graph_id="repo-map")
            self.assertEqual(mock_storage.call_args.kwargs["repository_identity"], "repo1:repo-map")

            mock_storage.return_value = MagicMock(spec=JSFrameworkSummaryRecord, to_dict=lambda: {"root_path": "/app/fixture"})
            repomap_js_framework_summary(graph_id="repo-map")
            self.assertEqual(mock_storage.call_args.kwargs["repository_identity"], "repo1:repo-map")

            mock_storage.return_value = MagicMock(spec=NixSummaryRecord, to_dict=lambda: {"root_path": "[root-path]"})
            repomap_nix_summary(graph_id="repo-map")
            self.assertEqual(mock_storage.call_args.kwargs["repository_identity"], "repo1:repo-map")

    def test_language_summaries_reject_invalid_identity_with_mcp_error(self) -> None:
        from repomap_kg.server.mcp import (
            repomap_js_framework_summary,
            repomap_nix_summary,
            repomap_openapi_summary,
            repomap_python_summary,
            repomap_terraform_summary,
        )

        config_path = self.write_ops_config(self.visible_ops_config())
        summary_callers = (
            repomap_python_summary,
            repomap_terraform_summary,
            repomap_openapi_summary,
            repomap_js_framework_summary,
            repomap_nix_summary,
        )
        with (
            patch.dict("os.environ", {"REPOMAP_OPS_CONFIG": str(config_path)}, clear=True),
            patch(
                "repomap_kg.server.ops.McpOpsGraphContext.repository_identity",
                new_callable=lambda: "invalid:identity:shape",
            ),
        ):
            for caller in summary_callers:
                with self.assertRaises(RepoMapMcpError):
                    caller(graph_id="repo-map")

    def test_language_summaries_sql_incorporate_identity_filter(self) -> None:
        from repomap_kg.storage import (
            build_js_framework_summary_query_sql,
            build_nix_summary_query_sql,
            build_openapi_summary_query_sql,
            build_python_summary_query_sql,
            build_terraform_summary_query_sql,
        )

        builders = (
            build_python_summary_query_sql,
            build_terraform_summary_query_sql,
            build_openapi_summary_query_sql,
            build_js_framework_summary_query_sql,
            build_nix_summary_query_sql,
        )
        for builder in builders:
            sql_with = builder("/app/fixture", repository_identity="repo1:fixture")
            self.assertIn("repository_identity = 'repo1:fixture'", sql_with)
            self.assertIn("repositories.id = (SELECT id FROM repositories WHERE", sql_with)
            sql_without = builder("/app/fixture", repository_identity=None)
            self.assertNotIn("repository_identity", sql_without)
            self.assertIn("repositories.root_path = '/app/fixture'", sql_without)

    def test_language_summaries_sqlite_empty_current_excludes_legacy(self) -> None:
        import sqlite3

        con = sqlite3.connect(":memory:")
        con.execute(
            "CREATE TABLE repositories ("
            "id INTEGER PRIMARY KEY, "
            "repository_identity TEXT, "
            "root_path TEXT)"
        )
        con.execute(
            "CREATE TABLE raw_observations ("
            "id INTEGER PRIMARY KEY, "
            "repository_id INTEGER, "
            "kind TEXT, "
            "payload_json TEXT)"
        )
        # Old legacy repository with observations
        con.execute("INSERT INTO repositories (id, repository_identity, root_path) VALUES (1, NULL, '/app/fixture')")
        con.execute("INSERT INTO raw_observations (id, repository_id, kind, payload_json) VALUES (1, 1, 'python.module', '{}')")
        # Current repository has valid identity, relocated or same root, but 0 observations
        con.execute("INSERT INTO repositories (id, repository_identity, root_path) VALUES (2, 'repo1:fixture', '/app/fixture')")

        predicate = build_repository_filter_sql(
            root_path="/app/fixture",
            repository_identity="repo1:fixture",
        )
        sql = f"SELECT id FROM repositories WHERE {predicate}"
        selected_repo = con.execute(sql).fetchall()
        self.assertEqual(selected_repo, [(2,)])

        obs_sql = f"SELECT COUNT(*) FROM raw_observations JOIN repositories ON repositories.id = raw_observations.repository_id WHERE {predicate}"
        obs_count = con.execute(obs_sql).fetchone()[0]
        self.assertEqual(obs_count, 0)

    def test_summary_root_value_redaction_consistency(self) -> None:
        from repomap_kg.server.ops import summary_root_value

        public_graph = MagicMock(privacy="public")
        private_graph = MagicMock(privacy="private-ops")
        self.assertEqual(
            summary_root_value("graph:fixture", public_graph),
            summary_root_value("/app/fixture", public_graph),
        )
        self.assertEqual(
            summary_root_value("graph:fixture-priv", private_graph),
            summary_root_value("/app/fixture-priv", private_graph),
        )
        self.assertEqual(summary_root_value("graph:fixture-priv", private_graph), "[private-root]")
        self.assertIsNone(summary_root_value(None, public_graph))
