from __future__ import annotations

from unittest.mock import patch

from repomap_kg.ops.config import load_ops_config
from repomap_kg.server.ops import (
    build_mcp_search_sql,
    query_mcp_search,
)
from repomap_kg.storage import StorageSchemaError

from repomap_test_support.mcp_server import McpServerTestSupport


class McpSearchReadbackUnitTests(McpServerTestSupport):
    def test_psycopg108_query_uses_exact_operational_array_adapter(self):
        config_path = self.write_ops_config(self.visible_ops_config())
        config = load_ops_config(config_path)
        rows = [{"path": "one"}, {"path": "two"}]

        with patch(
            "repomap_kg.server.ops.execute_ops_json_readback",
            return_value=rows,
            create=True,
        ) as execute:
            payload = query_mcp_search(
                config,
                database="repomap_repo_map",
                root_path="/tmp/fixture",
                target="files",
                query="path",
                limit=1,
                offset=5,
                psql_command="/usr/local/bin/psql",
            )

        self.assertEqual(payload["results"], [{"path": "one"}])
        self.assertEqual(payload["total"], 6)
        self.assertTrue(payload["has_more"])
        execute.assert_called_once_with(
            config,
            database="repomap_repo_map",
            sql=build_mcp_search_sql(
                root_path="/tmp/fixture",
                target="files",
                query="path",
                kind=None,
                path=None,
                limit=1,
                offset=5,
                include_raw=False,
            ),
            label="files MCP search",
            expected_shape="array",
            mode="host_then_container",
            psql_command="/usr/local/bin/psql",
        )

    def test_psycopg108_search_payload_bypasses_generic_wrapper(self):
        from repomap_kg.server.mcp import repomap_search_files

        config_path = self.write_ops_config(self.visible_ops_config())
        with (
            patch.dict(
                "os.environ",
                {"REPOMAP_OPS_CONFIG": str(config_path)},
                clear=True,
            ),
            patch(
                "repomap_kg.server.ops.query_configured_storage",
                side_effect=AssertionError("generic wrapper used for search"),
            ),
            patch(
                "repomap_kg.server.ops.query_mcp_search",
                return_value={
                    "results": [{"path": "src/main.py"}],
                    "total": 1,
                    "has_more": False,
                },
            ) as query,
        ):
            payload = repomap_search_files(graph_id="repo-map", query="main")

        self.assertEqual(payload["results"], [{"path": "src/main.py"}])
        self.assertEqual(query.call_args.args[0].config_path, str(config_path))
        self.assertEqual(query.call_args.kwargs["database"], "repomap_repo_map")
        self.assertEqual(query.call_args.kwargs["root_path"], "/tmp/fixture")
        self.assertIsNone(query.call_args.kwargs["psql_command"])

    def test_psycopg108_validation_precedes_search_database_access(self):
        from repomap_kg.server.mcp import RepoMapMcpError, repomap_search_files

        config_path = self.write_ops_config(self.visible_ops_config())
        with (
            patch.dict(
                "os.environ",
                {"REPOMAP_OPS_CONFIG": str(config_path)},
                clear=True,
            ),
            patch(
                "repomap_kg.server.ops.query_mcp_search",
                side_effect=AssertionError("database accessed"),
            ) as query,
        ):
            with self.assertRaises(RepoMapMcpError):
                repomap_search_files(graph_id="missing", query="main")
            with self.assertRaises(RepoMapMcpError):
                repomap_search_files(graph_id="repo-map", query=" ")

        query.assert_not_called()

    def test_psycopg108_adapter_failure_remains_public_mcp_error(self):
        from repomap_kg.server.mcp import RepoMapMcpError, repomap_search_files

        config_path = self.write_ops_config(self.visible_ops_config())
        with (
            patch.dict(
                "os.environ",
                {"REPOMAP_OPS_CONFIG": str(config_path)},
                clear=True,
            ),
            patch(
                "repomap_kg.server.ops.execute_ops_json_readback",
                side_effect=StorageSchemaError("bounded search failure"),
                create=True,
            ),
        ):
            with self.assertRaisesRegex(RepoMapMcpError, "bounded search failure"):
                repomap_search_files(graph_id="repo-map", query="main")

    def test_psycopg108_moves_no_other_configured_callback(self):
        import inspect

        from repomap_kg.server import ops

        search_source = inspect.getsource(ops.search_payload)
        query_source = inspect.getsource(ops.query_mcp_search)
        project_source = inspect.getsource(ops.project_summary_payload)
        summary_source = inspect.getsource(ops.summary_payload)
        neighborhood_source = inspect.getsource(ops.neighborhood_payload)

        self.assertNotIn("query_configured_storage", search_source)
        self.assertIn("execute_ops_json_readback", query_source)
        self.assertNotIn("run_psql", query_source)
        self.assertNotIn("parse_psql_json", query_source)
        for source in (project_source, summary_source, neighborhood_source):
            self.assertIn("query_configured_storage", source)
