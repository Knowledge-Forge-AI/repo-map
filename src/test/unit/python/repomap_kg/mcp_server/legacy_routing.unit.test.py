from unittest.mock import patch

from repomap_kg.storage import (
    CanonicalEdgeRecord,
    CanonicalNodeRecord,
    CanonicalStorageSummaryRecord,
    identity_metadata_hash,
)
from repomap_test_support.mcp_server import McpServerTestSupport


class McpServerLegacyRoutingUnitTests(McpServerTestSupport):
    def test_status_uses_default_project_from_config(self):
        from repomap_kg.server.mcp import repomap_status

        config_path = self.write_mcp_config(
            {
                "default_project": "repo-map",
                "projects": {
                    "repo-map": {
                        "root_path": "/workspace/repo-map",
                        "pg_database": "repomap_repo_map",
                        "pg_host": "/tmp/pg",
                        "pg_port": "55432",
                        "pg_user": "repo_map",
                    },
                },
            }
        )

        with patch.dict("os.environ", {"REPOMAP_MCP_CONFIG": str(config_path)}):
            with patch(
                "repomap_kg.server.mcp.query_canonical_storage_summary",
                return_value=CanonicalStorageSummaryRecord(
                    root_path="/workspace/repo-map",
                    repository_name="repo-map",
                    latest_run_id=22,
                    runs=2,
                    files=3,
                    raw_observations=13,
                    canonical_nodes=5,
                    canonical_edges=7,
                    canonical_evidence=11,
                ),
            ) as query:
                payload = repomap_status()

        self.assertEqual(payload["project"], "repo-map")
        self.assertEqual(payload["repository_name"], "repo-map")
        self.assertEqual(
            query.call_args.args[0],
            ["-h", "/tmp/pg", "-p", "55432", "-U", "repo_map", "-d", "repomap_repo_map"],
        )
        self.assertEqual(query.call_args.kwargs["root_path"], "/workspace/repo-map")

    def test_canonical_nodes_resolves_named_project_config(self):
        from repomap_kg.server.mcp import repomap_canonical_nodes

        config_path = self.write_mcp_config(
            {
                "projects": {
                    "repo-map": {
                        "root_path": "/workspace/repo-map",
                        "pg_database": "repomap_repo_map",
                    },
                },
            }
        )
        record = CanonicalNodeRecord(
            canonical_key="python.module:repomap_kg.cli",
            graph_key_version=1,
            kind="python.module",
            display_name="repomap_kg.cli",
            confidence="extracted",
            conflict=False,
            metadata={},
            first_seen_run_id=1,
            last_seen_run_id=2,
        )
        with patch.dict("os.environ", {"REPOMAP_MCP_CONFIG": str(config_path)}):
            with patch(
                "repomap_kg.server.mcp.query_canonical_node_records",
                return_value=(record,),
            ) as query:
                payload = repomap_canonical_nodes(
                    project="repo-map",
                    kind="python.module",
                )

        assert isinstance(payload, dict)
        self.assertEqual(
            payload["items"][0]["canonical_key"],
            "python.module:repomap_kg.cli",
        )
        self.assertEqual(query.call_args.args[0], ["-d", "repomap_repo_map"])
        self.assertEqual(query.call_args.kwargs["root_path"], "/workspace/repo-map")

    def test_live_ops2_legacy_project_resolution_prefers_legacy_config(self):
        from repomap_kg.server.mcp import repomap_canonical_nodes

        mcp_config_path = self.write_mcp_config(
            {
                "projects": {
                    "repo-map": {
                        "root_path": "/legacy/repo-map",
                        "pg_database": "legacy_repo_map",
                    },
                },
            }
        )
        ops_config_path = self.write_visible_ops_config()
        record = CanonicalNodeRecord(
            canonical_key="python.module:repomap_kg.cli",
            graph_key_version=1,
            kind="python.module",
            display_name="repomap_kg.cli",
            confidence="extracted",
            conflict=False,
            metadata={},
            first_seen_run_id=1,
            last_seen_run_id=2,
        )

        with self.patch_mcp_and_ops_config(mcp_config_path, ops_config_path):
            with patch(
                "repomap_kg.server.mcp.query_canonical_node_records",
                return_value=(record,),
            ) as query:
                payload = repomap_canonical_nodes(
                    project="repo-map",
                    kind="python.module",
                )

        assert isinstance(payload, dict)
        self.assertEqual(
            payload["items"][0]["canonical_key"],
            "python.module:repomap_kg.cli",
        )
        self.assertEqual(query.call_args.args[0], ["-d", "legacy_repo_map"])
        self.assertEqual(query.call_args.kwargs["root_path"], "/legacy/repo-map")

    def test_live_ops2_legacy_project_tools_resolve_graph_registry_graphs(self):
        from repomap_kg.server.mcp import (
            repomap_canonical_edges,
            repomap_canonical_nodes,
            repomap_status,
        )

        mcp_config_path = self.write_empty_mcp_config()
        ops_config_path = self.write_visible_ops_config()
        node = CanonicalNodeRecord(
            canonical_key="python.module:repomap_kg.cli",
            graph_key_version=1,
            kind="python.module",
            display_name="repomap_kg.cli",
            confidence="extracted",
            conflict=False,
            metadata={},
            first_seen_run_id=1,
            last_seen_run_id=2,
        )
        edge = CanonicalEdgeRecord(
            source_key="python.module:repomap_kg.cli",
            edge_kind="imports",
            target_key="python.module:repomap_kg.storage",
            graph_key_version=1,
            identity_metadata={},
            identity_metadata_hash=identity_metadata_hash({}),
            metadata={},
            confidence="extracted",
            conflict=False,
            first_seen_run_id=1,
            last_seen_run_id=2,
        )

        with self.patch_mcp_and_ops_config(mcp_config_path, ops_config_path):
            with (
                patch(
                    "repomap_kg.server.mcp.query_canonical_storage_summary",
                    return_value=CanonicalStorageSummaryRecord(
                        root_path="/tmp/fixture",
                        repository_name="fixture",
                        latest_run_id=22,
                        runs=2,
                        files=3,
                        raw_observations=13,
                        canonical_nodes=5,
                        canonical_edges=7,
                        canonical_evidence=11,
                    ),
                ) as status_query,
                patch(
                    "repomap_kg.server.mcp.query_canonical_node_records",
                    return_value=(node,),
                ) as node_query,
                patch(
                    "repomap_kg.server.mcp.query_canonical_edge_records",
                    return_value=(edge,),
                ) as edge_query,
            ):
                status = repomap_status(project="repo-map")
                nodes = repomap_canonical_nodes(
                    project="repo-map",
                    kind="python.module",
                )
                edges = repomap_canonical_edges(
                    project="repo-map",
                    kind="imports",
                )

        expected_psql_args = [
            "-h",
            "127.0.0.1",
            "-p",
            "5432",
            "-U",
            "repo_map",
            "-d",
            "repomap_repo_map",
        ]
        self.assertEqual(status["project"], "repo-map")
        self.assertEqual(status["root_path"], "[graph-root]")
        assert isinstance(nodes, dict)
        assert isinstance(edges, dict)
        self.assertEqual(
            nodes["items"][0]["canonical_key"],
            "python.module:repomap_kg.cli",
        )
        self.assertEqual(edges["items"][0]["edge_kind"], "imports")
        self.assertEqual(status_query.call_args.args[0], expected_psql_args)
        self.assertEqual(node_query.call_args.args[0], expected_psql_args)
        self.assertEqual(edge_query.call_args.args[0], expected_psql_args)
        self.assertEqual(status_query.call_args.kwargs["root_path"], "/tmp/fixture")
        self.assertEqual(node_query.call_args.kwargs["root_path"], "/tmp/fixture")
        self.assertEqual(edge_query.call_args.kwargs["root_path"], "/tmp/fixture")
