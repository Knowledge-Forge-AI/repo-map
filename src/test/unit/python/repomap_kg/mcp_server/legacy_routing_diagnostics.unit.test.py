import json
from pathlib import Path
from unittest.mock import patch

from repomap_kg.storage import CanonicalStorageSummaryRecord
from repomap_test_support.mcp_server import McpServerTestSupport

class McpServerLegacyRoutingDiagnosticUnitTests(McpServerTestSupport):
    def test_live_ops2_legacy_project_tools_reject_hidden_and_disabled_graphs(self):
        from repomap_kg.server.mcp import RepoMapMcpError, repomap_canonical_nodes

        mcp_config_path = self.write_empty_mcp_config()
        ops_config_path = self.write_visible_ops_config()

        with self.patch_mcp_and_ops_config(mcp_config_path, ops_config_path):
            with patch("repomap_kg.server.mcp.query_canonical_node_records") as query:
                with self.assertRaisesRegex(RepoMapMcpError, "not enabled"):
                    repomap_canonical_nodes(project="disabled")
                with self.assertRaisesRegex(RepoMapMcpError, "not MCP-visible"):
                    repomap_canonical_nodes(project="hidden")

        query.assert_not_called()

    def test_live_ops2_unknown_project_diagnostic_mentions_legacy_vs_graph_registry(self):
        from repomap_kg.server.mcp import RepoMapMcpError, repomap_status

        mcp_config_path = self.write_empty_mcp_config()
        ops_config_path = self.write_visible_ops_config()

        with self.patch_mcp_and_ops_config(mcp_config_path, ops_config_path):
            with patch("repomap_kg.server.mcp.query_canonical_storage_summary") as query:
                with self.assertRaisesRegex(
                    RepoMapMcpError,
                    "unknown legacy MCP project or graph-registry graph_id",
                ) as caught:
                    repomap_status(project="missing")

        self.assertNotIn("/tmp/fixture", str(caught.exception))
        self.assertNotIn(str(Path.home() / "private-visible"), str(caught.exception))
        query.assert_not_called()

    def test_live_ops2_legacy_project_diagnostic_does_not_leak_private_roots(self):
        from repomap_kg.server.mcp import RepoMapMcpError, repomap_status

        mcp_config_path = self.write_empty_mcp_config()
        ops_config_path = self.write_visible_ops_config()
        private_root = str(Path.home() / "private-visible")
        home_name = Path.home().name

        with self.patch_mcp_and_ops_config(mcp_config_path, ops_config_path):
            with patch(
                "repomap_kg.server.mcp.query_canonical_storage_summary",
                return_value=CanonicalStorageSummaryRecord(
                    root_path=private_root,
                    repository_name="private-visible",
                    latest_run_id=22,
                    runs=2,
                    files=3,
                    raw_observations=13,
                    canonical_nodes=5,
                    canonical_edges=7,
                    canonical_evidence=11,
                ),
            ) as query:
                private_status = repomap_status(project="private-visible")
            with self.assertRaisesRegex(RepoMapMcpError, "not MCP-visible") as caught:
                repomap_status(project="hidden")

        self.assertEqual(private_status["root_path"], "[private-root]")
        self.assertNotIn(home_name, json.dumps(private_status, sort_keys=True))
        self.assertNotIn(private_root, str(caught.exception))
        self.assertNotIn(home_name, str(caught.exception))
        self.assertEqual(query.call_args.kwargs["root_path"], private_root)

    def test_live_ops2_legacy_project_schema_mentions_graph_registry_fallback(self):
        from repomap_kg.server.mcp import tool_input_schema

        project_schema = tool_input_schema("repomap_status")["properties"]["project"]

        self.assertIn("Legacy MCP project name", project_schema["description"])
        self.assertIn("graph-registry graph_id", project_schema["description"])
