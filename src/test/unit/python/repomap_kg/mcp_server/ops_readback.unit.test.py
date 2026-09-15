import json
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from repomap_kg.ops.config import load_ops_config
from repomap_kg.storage import (
    CanonicalNeighborhoodRecord,
    CanonicalNodeRecord,
    StorageSchemaError,
)
from repomap_test_support.mcp_server import McpServerTestSupport


class McpServerOpsReadbackUnitTests(McpServerTestSupport):
    def test_ops_mcp_refresh_status_reads_existing_storage_only(self):
        from repomap_kg.server.mcp import repomap_refresh_status
        from repomap_kg.ops.refresh import OpsRefreshGraphStatus

        config_path = self.write_visible_ops_config()
        with self.patch_ops_config(config_path):
            with patch(
                "repomap_kg.server.ops.query_refresh_status",
                return_value={
                    "repo-map": self.synthetic_refresh_status(
                        latest_run_status="success",
                        latest_run_finished_at=None,
                        latest_run_id=12,
                        raw_observations=9,
                        raw_observations_total=9,
                        latest_run_raw_observations=5,
                        canonical_nodes=8,
                        canonical_edges=7,
                    ),
                    "disabled": OpsRefreshGraphStatus(
                        graph_id="disabled",
                        repository_name="disabled",
                        privacy="private-memory",
                        enabled=False,
                        mcp_visible=True,
                        refresh_policy="manual",
                        root_path_display="~/disabled",
                        root_path_expanded="/Users/example/disabled",
                        repository_exists=False,
                    ),
                },
            ) as query:
                payload = repomap_refresh_status()

        self.assertEqual(payload["graph_count"], 1)
        self.assertEqual(payload["graphs"][0]["graph_id"], "repo-map")
        self.assertEqual(payload["graphs"][0]["raw_observations"], 9)
        self.assertEqual(payload["graphs"][0]["raw_observations_total"], 9)
        self.assertEqual(payload["graphs"][0]["latest_run_raw_observations"], 5)
        self.assert_read_only_payload(payload)
        self.assertTrue(payload["safety"]["no_refresh"])
        query.assert_called_once()

    def test_ops_mcp_refresh_status_leaves_default_psql_implicit(self):
        from repomap_kg.server.mcp import repomap_refresh_status

        config_path = self.write_ops_config(self.visible_ops_config())
        with patch.dict(
            "os.environ",
            {
                "REPOMAP_OPS_CONFIG": str(config_path),
                "REPOMAP_PSQL_COMMAND": "psql",
            },
            clear=True,
        ):
            with patch(
                "repomap_kg.server.ops.query_refresh_status",
                return_value={},
            ) as query:
                repomap_refresh_status(graph_id="repo-map")

        self.assertIsNone(query.call_args.kwargs["psql_command"])

    def test_ops_mcp_direct_search_uses_operational_json_readback(self):
        from repomap_kg.server.mcp import repomap_search_files

        config_path = self.write_ops_config(self.visible_ops_config())
        with patch.dict(
            "os.environ",
            {
                "REPOMAP_OPS_CONFIG": str(config_path),
                "REPOMAP_PSQL_COMMAND": "psql",
            },
            clear=True,
        ):
            with patch(
                "repomap_kg.server.ops.query_mcp_search",
                return_value={"results": [{"path": "src/main.py"}], "total": 1},
            ) as query:
                payload = repomap_search_files(graph_id="repo-map", query="main")

        self.assertEqual(payload["results"], [{"path": "src/main.py"}])
        self.assertEqual(query.call_args.kwargs["database"], "repomap_repo_map")
        self.assertIsNone(query.call_args.kwargs["psql_command"])
        self.assertEqual(query.call_args.kwargs["target"], "files")

    def test_ops_mcp_graph_status_and_neighborhood_use_stored_readback(self):
        from repomap_kg.server.mcp import repomap_graph_status, repomap_neighborhood

        config_path = self.write_visible_ops_config()
        neighborhood = CanonicalNeighborhoodRecord(
            center=CanonicalNodeRecord(
                canonical_key="python.module:pkg.app",
                graph_key_version=1,
                kind="python.module",
                display_name="pkg.app",
                confidence="extracted",
                conflict=False,
                metadata={
                    "api_key": "mcp-ops4-fake-token",
                    "source_root": "/tmp/fixture",
                },
                first_seen_run_id=1,
                last_seen_run_id=2,
            ),
            nodes=(),
            edges=(),
        )
        with self.patch_ops_config(config_path):
            with patch(
                "repomap_kg.server.ops.query_refresh_status",
                return_value={
                    "repo-map": self.synthetic_refresh_status(
                        latest_run_status="success",
                        latest_run_finished_at=None,
                        raw_observations=4,
                        raw_observations_total=4,
                        latest_run_raw_observations=2,
                        canonical_nodes=3,
                        canonical_edges=2,
                    )
                },
            ):
                status = repomap_graph_status(graph_id="repo-map")
            with patch(
                "repomap_kg.server.ops.query_canonical_neighborhood",
                return_value=neighborhood,
            ) as query:
                payload = repomap_neighborhood(
                    graph_id="repo-map",
                    node="python.module:pkg.app",
                    direction="both",
                    depth=1,
                )

        self.assertEqual(status["storage"]["raw_observations"], 4)
        self.assertEqual(status["storage"]["raw_observations_total"], 4)
        self.assertEqual(status["storage"]["latest_run_raw_observations"], 2)
        self.assertEqual(status["graph"]["database"], "[graph-database]")
        self.assert_read_only_payload(status)
        self.assertEqual(
            payload["result"]["center"]["canonical_key"],
            "python.module:pkg.app",
        )
        self.assertNotIn("mcp-ops4-fake-token", json.dumps(payload, sort_keys=True))
        self.assertNotIn("/tmp/fixture", json.dumps(payload, sort_keys=True))
        self.assertEqual(
            payload["result"]["center"]["metadata"]["source_root"],
            "[private-path]",
        )
        self.assertEqual(query.call_args.kwargs["node"], "python.module:pkg.app")
        self.assertIn("repomap_repo_map", query.call_args.args[0])

    def test_ops_mcp_helper_validation_and_sql_are_bounded(self):
        from repomap_kg.server.ops import (
            McpOpsError,
            build_mcp_search_sql,
            like_escape,
            psql_command_from_environment,
            validate_limit,
            validate_offset,
            validate_query,
        )

        self.assertEqual(validate_limit(500), 100)
        self.assertEqual(validate_offset(cast(Any, "3")), 3)
        self.assertEqual(validate_query("  pkg  "), "pkg")
        self.assertEqual(like_escape(r"%pkg_app"), r"\%pkg\_app")
        with patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(psql_command_from_environment())
        with patch.dict("os.environ", {"REPOMAP_PSQL_COMMAND": "psql"}, clear=True):
            self.assertIsNone(psql_command_from_environment())
        with self.assertRaisesRegex(McpOpsError, "query is required"):
            validate_query("")
        with self.assertRaisesRegex(McpOpsError, "positive integer"):
            validate_limit(0)
        with self.assertRaisesRegex(McpOpsError, "non-negative"):
            validate_offset(-1)
        with patch.dict("os.environ", {"REPOMAP_PSQL_COMMAND": "bad psql"}):
            with self.assertRaisesRegex(McpOpsError, "whitespace"):
                psql_command_from_environment()
        with patch.dict("os.environ", {"REPOMAP_PSQL_COMMAND": "/bin/echo"}):
            with self.assertRaisesRegex(McpOpsError, "psql executable"):
                psql_command_from_environment()

        nodes_sql = build_mcp_search_sql(
            root_path="/tmp/fixture",
            target="nodes",
            query="pkg",
            kind="python.module",
            path=None,
            limit=20,
            offset=0,
            include_raw=False,
        )
        observations_sql = build_mcp_search_sql(
            root_path="/tmp/fixture",
            target="observations",
            query="python.import",
            kind="python.import",
            path="pkg/app.py",
            limit=20,
            offset=2,
            include_raw=True,
        )
        files_sql = build_mcp_search_sql(
            root_path="/tmp/fixture",
            target="files",
            query="README",
            kind=None,
            path="README.md",
            limit=5,
            offset=0,
            include_raw=False,
        )
        self.assertIn("FROM canonical_nodes", nodes_sql)
        self.assertIn("canonical_nodes.kind = 'python.module'", nodes_sql)
        self.assertIn("raw_observations.payload_json AS payload", observations_sql)
        self.assertIn("raw_observations.path = 'pkg/app.py'", observations_sql)
        self.assertIn("FROM files", files_sql)
        with self.assertRaisesRegex(McpOpsError, "search target"):
            build_mcp_search_sql(
                root_path="/tmp/fixture",
                target="edges",
                query="pkg",
                kind=None,
                path=None,
                limit=1,
                offset=0,
                include_raw=False,
            )

    def test_ops_mcp_missing_config_unknown_graph_and_search_parse_are_safe(self):
        from repomap_kg.server.mcp import RepoMapMcpError, repomap_list_graphs
        from repomap_kg.server.ops import query_mcp_search

        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(RepoMapMcpError, "REPOMAP_HOME"):
                repomap_list_graphs()

        config_path = self.write_ops_config(self.visible_ops_config())
        config = load_ops_config(config_path)
        with patch.dict("os.environ", {"REPOMAP_OPS_CONFIG": str(config_path)}):
            from repomap_kg.server.mcp import repomap_project_summary

            with self.assertRaisesRegex(RepoMapMcpError, "unknown graph_id"):
                repomap_project_summary(graph_id="missing")

        with patch(
            "repomap_kg.server.ops.execute_ops_json_readback",
            return_value=[{"path": "one"}, {"path": "two"}],
        ) as execute:
            payload = query_mcp_search(
                config,
                database="repomap",
                root_path="/tmp/fixture",
                target="files",
                query="path",
                limit=1,
                offset=5,
                psql_command="/usr/bin/psql",
            )

        self.assertEqual(payload["results"], [{"path": "one"}])
        self.assertEqual(payload["total"], 6)
        self.assertTrue(payload["has_more"])
        self.assertEqual(execute.call_args.kwargs["database"], "repomap")
        self.assertEqual(execute.call_args.kwargs["psql_command"], "/usr/bin/psql")

        with patch(
            "repomap_kg.server.ops.execute_ops_json_readback",
            side_effect=StorageSchemaError("files MCP search returned non-array JSON"),
        ):
            with self.assertRaises(StorageSchemaError):
                query_mcp_search(
                    config,
                    database="repomap",
                    root_path="/tmp/fixture",
                    target="files",
                    query="path",
                    limit=1,
                    psql_command="psql",
                )

    def test_server_memory_mcp_tools_read_configured_jsonl_only(self):
        from repomap_kg.server.mcp import (
            handle_jsonrpc_message,
            repomap_server_memory_search,
            repomap_server_memory_summary,
        )

        fixture = (
            Path(__file__).resolve().parents[4]
            / "fixtures"
            / "server_memory"
            / "basic"
            / "memory.jsonl"
        )
        config_path = self.write_ops_config(self.server_memory_ops_config(fixture))

        with patch.dict("os.environ", {"REPOMAP_OPS_CONFIG": str(config_path)}):
            summary = repomap_server_memory_summary()
            search = repomap_server_memory_search(query="RepoMap", limit=1)
            jsonrpc = handle_jsonrpc_message(
                {
                    "jsonrpc": "2.0",
                    "id": 45,
                    "method": "tools/call",
                    "params": {
                        "name": "repomap_server_memory_search",
                        "arguments": {"query": "RepoMap", "limit": 1},
                    },
                }
            )

        self.assertTrue(summary["read_only"])
        self.assertEqual(summary["summary"]["entry_count"], 3)
        self.assertTrue(summary["safety"]["server_memory_mutated"] is False)
        self.assertEqual(search["result_count"], 1)
        assert isinstance(jsonrpc, dict)
        assert isinstance(jsonrpc["result"], dict)
        self.assertEqual(
            jsonrpc["result"]["structuredContent"]["result_count"],
            1,
        )
        serialized = json.dumps({"summary": summary, "search": search}, sort_keys=True)
        self.assertNotIn("raw_payload", serialized)
        self.assertNotIn("observations", serialized)

    def test_server_memory_mcp_disabled_config_returns_safe_diagnostic(self):
        from repomap_kg.server.mcp import repomap_server_memory_summary

        config_path = self.write_ops_config(self.visible_ops_config())

        with patch.dict("os.environ", {"REPOMAP_OPS_CONFIG": str(config_path)}):
            payload = repomap_server_memory_summary()

        self.assertFalse(payload["enabled"])
        self.assertEqual(
            [diagnostic["code"] for diagnostic in payload["diagnostics"]],
            ["server-memory-disabled"],
        )
