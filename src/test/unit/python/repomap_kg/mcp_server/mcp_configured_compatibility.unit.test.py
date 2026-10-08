"""Configured MCP identity routing and compatibility (ADR 0068)."""

from unittest.mock import MagicMock, patch

from repomap_test_support.mcp_server import McpServerTestSupport


class ConfiguredStorageIdentityTests(McpServerTestSupport):
    def test_all_eleven_exposed_tools_legacy_calls_omit_identity_keyword(self) -> None:
        from repomap_kg.server.mcp import (
            repomap_canonical_edges,
            repomap_canonical_neighborhood,
            repomap_canonical_nodes,
            repomap_explain_canonical_edge,
            repomap_explain_source_feed_item,
            repomap_ingested_sources,
            repomap_source_feed_items,
            repomap_source_references,
            repomap_source_runs,
            repomap_source_summary,
            repomap_status,
        )
        from repomap_kg.storage import (
            CanonicalEdgeExplanationRecord,
            CanonicalEdgeRecord,
            CanonicalNeighborhoodRecord,
            CanonicalNodeRecord,
            CanonicalStorageSummaryRecord,
            SourceSummaryRecord,
            identity_metadata_hash,
        )

        mcp_config_path = self.write_mcp_config(
            {
                "projects": {
                    "legacy-proj": {
                        "root_path": "/workspace/legacy",
                        "pg_database": "repomap_legacy",
                    },
                },
            }
        )
        node = CanonicalNodeRecord(
            canonical_key="python.module:cli", graph_key_version=1, kind="python.module",
            display_name="cli", confidence="extracted", conflict=False, metadata={},
            first_seen_run_id=1, last_seen_run_id=1,
        )
        edge = CanonicalEdgeRecord(
            source_key="python.module:a", edge_kind="imports", target_key="python.module:b",
            graph_key_version=1, identity_metadata={}, identity_metadata_hash=identity_metadata_hash({}),
            metadata={}, confidence="extracted", conflict=False, first_seen_run_id=1, last_seen_run_id=1,
        )
        status_summary = CanonicalStorageSummaryRecord(
            root_path="/workspace/legacy", repository_name="legacy", latest_run_id=1,
            runs=1, files=1, raw_observations=1, canonical_nodes=1, canonical_edges=1, canonical_evidence=1,
        )

        with (
            patch.dict("os.environ", {"REPOMAP_MCP_CONFIG": str(mcp_config_path)}, clear=True),
            patch("repomap_kg.server.mcp.query_canonical_storage_summary", return_value=status_summary) as mock_status,
            patch("repomap_kg.server.mcp.query_canonical_node_records", return_value=(node,)) as mock_nodes,
            patch("repomap_kg.server.mcp.query_canonical_edge_records", return_value=(edge,)) as mock_edges,
            patch("repomap_kg.server.mcp.query_canonical_edge_explanation", return_value=CanonicalEdgeExplanationRecord(edge=edge, evidence=())) as mock_explain_edge,
            patch("repomap_kg.server.mcp.query_canonical_neighborhood", return_value=CanonicalNeighborhoodRecord(center=node, nodes=(), edges=())) as mock_neighborhood,
            patch("repomap_kg.server.mcp.query_ingested_source_records", return_value=()) as mock_sources,
            patch("repomap_kg.server.mcp.query_source_summary", return_value=MagicMock(spec=SourceSummaryRecord, to_dict=lambda: {})) as mock_source_summary,
            patch("repomap_kg.server.mcp.query_source_run_records", return_value=()) as mock_source_runs,
            patch("repomap_kg.server.mcp.query_source_feed_item_records", return_value=()) as mock_feed_items,
            patch("repomap_kg.server.mcp.query_source_feed_item_explanation", return_value={"item_key": "feed.item:example:1"}) as mock_explain_feed,
            patch("repomap_kg.server.mcp.query_source_reference_records", return_value=()) as mock_source_refs,
        ):
            repomap_status(project="legacy-proj")
            self.assertNotIn("repository_identity", mock_status.call_args.kwargs)

            repomap_canonical_nodes(project="legacy-proj", kind="python.module")
            self.assertNotIn("repository_identity", mock_nodes.call_args.kwargs)

            repomap_canonical_edges(project="legacy-proj", kind="imports")
            self.assertNotIn("repository_identity", mock_edges.call_args.kwargs)

            repomap_explain_canonical_edge(
                project="legacy-proj", source_key="python.module:a", kind="imports",
                target_key="python.module:b", identity_metadata={},
            )
            self.assertNotIn("repository_identity", mock_explain_edge.call_args.kwargs)

            repomap_canonical_neighborhood(project="legacy-proj", node="python.module:a")
            self.assertNotIn("repository_identity", mock_neighborhood.call_args.kwargs)

            repomap_ingested_sources(project="legacy-proj")
            self.assertNotIn("repository_identity", mock_sources.call_args.kwargs)

            repomap_source_summary(project="legacy-proj", source_id="example-feed")
            self.assertNotIn("repository_identity", mock_source_summary.call_args.kwargs)

            repomap_source_runs(project="legacy-proj", source_id="example-feed")
            self.assertNotIn("repository_identity", mock_source_runs.call_args.kwargs)

            repomap_source_feed_items(project="legacy-proj", source_id="example-feed")
            self.assertNotIn("repository_identity", mock_feed_items.call_args.kwargs)

            repomap_explain_source_feed_item(project="legacy-proj", item_key="feed.item:example:1")
            self.assertNotIn("repository_identity", mock_explain_feed.call_args.kwargs)

            repomap_source_references(project="legacy-proj", source_id="example-feed")
            self.assertNotIn("repository_identity", mock_source_refs.call_args.kwargs)

            # Test explicit connection calls also omit repository_identity
            repomap_status(root_path="/tmp/explicit", pg_database="postgres")
            self.assertNotIn("repository_identity", mock_status.call_args.kwargs)

            repomap_canonical_nodes(root_path="/tmp/explicit", pg_database="postgres", kind="python.module")
            self.assertNotIn("repository_identity", mock_nodes.call_args.kwargs)

            repomap_canonical_edges(root_path="/tmp/explicit", pg_database="postgres", kind="imports")
            self.assertNotIn("repository_identity", mock_edges.call_args.kwargs)

            repomap_explain_canonical_edge(
                root_path="/tmp/explicit", pg_database="postgres", source_key="python.module:a",
                kind="imports", target_key="python.module:b", identity_metadata={},
            )
            self.assertNotIn("repository_identity", mock_explain_edge.call_args.kwargs)

            repomap_canonical_neighborhood(root_path="/tmp/explicit", pg_database="postgres", node="python.module:a")
            self.assertNotIn("repository_identity", mock_neighborhood.call_args.kwargs)

            repomap_ingested_sources(root_path="/tmp/explicit", pg_database="postgres")
            self.assertNotIn("repository_identity", mock_sources.call_args.kwargs)

            repomap_source_summary(root_path="/tmp/explicit", pg_database="postgres", source_id="example-feed")
            self.assertNotIn("repository_identity", mock_source_summary.call_args.kwargs)

            repomap_source_runs(root_path="/tmp/explicit", pg_database="postgres", source_id="example-feed")
            self.assertNotIn("repository_identity", mock_source_runs.call_args.kwargs)

            repomap_source_feed_items(root_path="/tmp/explicit", pg_database="postgres", source_id="example-feed")
            self.assertNotIn("repository_identity", mock_feed_items.call_args.kwargs)

            repomap_explain_source_feed_item(root_path="/tmp/explicit", pg_database="postgres", item_key="feed.item:example:1")
            self.assertNotIn("repository_identity", mock_explain_feed.call_args.kwargs)

            repomap_source_references(root_path="/tmp/explicit", pg_database="postgres", source_id="example-feed")
            self.assertNotIn("repository_identity", mock_source_refs.call_args.kwargs)

    def test_configured_portable_graph_routing_and_redaction(self) -> None:
        from repomap_kg.server.mcp import repomap_status
        from repomap_kg.storage import CanonicalStorageSummaryRecord

        portable_ops_config = (
            self.visible_ops_config()
            + """
[[graphs]]
id = "portable-graph"
name = "Portable Repo"
enabled = true
mcp_visible = true
refresh_policy = "manual"
database = "repomap_portable"

[[graphs.source_bindings]]
schema_version = 1
source_definition_id = "src1:portable"
alias = "portable-alias"
revision = 1
kind = "folder"
root_path = "/tmp/portable-src"
repository_name = "portable"
logical_root = "portable"
privacy = "public-dev"
evidence_retention = "inherit"
extractor_profile = "default"
resolution_policy = "isolated"
role = "source"
enabled = true

[[graphs]]
id = "portable-private-graph"
name = "Portable Private Repo"
enabled = true
mcp_visible = true
refresh_policy = "manual"
database = "repomap_portable_priv"

[[graphs.source_bindings]]
schema_version = 1
source_definition_id = "src1:portable-priv"
alias = "portable-priv-alias"
revision = 1
kind = "folder"
root_path = "/tmp/portable-priv-src"
repository_name = "portable-priv"
logical_root = "portable-priv"
privacy = "private-ops"
evidence_retention = "inherit"
extractor_profile = "default"
resolution_policy = "isolated"
role = "source"
enabled = true
"""
        )
        config_path = self.write_ops_config(portable_ops_config)
        with (
            patch.dict("os.environ", {"REPOMAP_OPS_CONFIG": str(config_path)}, clear=True),
            patch("repomap_kg.server.mcp.query_canonical_storage_summary") as mock_summary,
        ):
            mock_summary.return_value = CanonicalStorageSummaryRecord(
                root_path="/storage/portable",
                repository_name="portable-row",
                latest_run_id=10,
                runs=1,
                files=2,
                raw_observations=5,
                canonical_nodes=3,
                canonical_edges=4,
                canonical_evidence=5,
            )
            # 1. Public portable graph: root_path sent to query is "graph:portable-graph", returned payload root is "[graph-root]"
            payload = repomap_status(project="portable-graph")
            self.assertEqual(mock_summary.call_args.kwargs["root_path"], "graph:portable-graph")
            self.assertEqual(mock_summary.call_args.kwargs["repository_identity"], "repo1:portable-graph")
            self.assertEqual(payload["root_path"], "[graph-root]")
            self.assertEqual(payload["repository_name"], "portable-row")

            # 2. Private portable graph: root_path sent to query is "graph:portable-private-graph", returned payload root is "[private-root]"
            mock_summary.return_value = CanonicalStorageSummaryRecord(
                root_path="/storage/portable-priv",
                repository_name="portable-priv-row",
                latest_run_id=11,
                runs=1,
                files=2,
                raw_observations=5,
                canonical_nodes=3,
                canonical_edges=4,
                canonical_evidence=5,
            )
            payload_priv = repomap_status(project="portable-private-graph")
            self.assertEqual(mock_summary.call_args.kwargs["root_path"], "graph:portable-private-graph")
            self.assertEqual(mock_summary.call_args.kwargs["repository_identity"], "repo1:portable-private-graph")
            self.assertEqual(payload_priv["root_path"], "[private-root]")
            self.assertEqual(payload_priv["repository_name"], "portable-priv-row")

    def test_public_tool_schemas_preserved_for_all_eleven_tools(self) -> None:
        from repomap_kg.server.mcp import (
            tool_definitions,
            tool_input_schema,
            validate_tool_call_arguments,
        )

        eleven_tools = (
            "repomap_status",
            "repomap_canonical_nodes",
            "repomap_canonical_edges",
            "repomap_explain_canonical_edge",
            "repomap_canonical_neighborhood",
            "repomap_ingested_sources",
            "repomap_source_summary",
            "repomap_source_runs",
            "repomap_source_feed_items",
            "repomap_explain_source_feed_item",
            "repomap_source_references",
        )
        definitions_by_name = {tool["name"]: tool for tool in tool_definitions()}
        for tool_name in eleven_tools:
            self.assertIn(tool_name, definitions_by_name)
            schema = tool_input_schema(tool_name)
            self.assertEqual(schema["type"], "object")
            properties = schema["properties"]
            self.assertIn("project", properties)
            self.assertIn("root_path", properties)

        validate_tool_call_arguments("repomap_status", {"project": "repo-map"})
        validate_tool_call_arguments("repomap_canonical_nodes", {"project": "repo-map", "kind": "python.module"})
        validate_tool_call_arguments(
            "repomap_canonical_edges", {"project": "repo-map", "kind": "imports"}
        )
        validate_tool_call_arguments(
            "repomap_explain_canonical_edge",
            {
                "project": "repo-map",
                "source_key": "python.module:a",
                "kind": "imports",
                "target_key": "python.module:b",
            },
        )
        validate_tool_call_arguments(
            "repomap_canonical_neighborhood", {"project": "repo-map", "node": "python.module:a"}
        )
        validate_tool_call_arguments("repomap_ingested_sources", {"project": "repo-map"})
        validate_tool_call_arguments("repomap_source_summary", {"project": "repo-map", "source_id": "src-1"})
        validate_tool_call_arguments("repomap_source_runs", {"project": "repo-map", "source_id": "src-1"})
        validate_tool_call_arguments("repomap_source_feed_items", {"project": "repo-map", "source_id": "src-1"})
        validate_tool_call_arguments(
            "repomap_explain_source_feed_item",
            {"project": "repo-map", "item_key": "feed.item:example:1"},
        )
        validate_tool_call_arguments("repomap_source_references", {"project": "repo-map", "source_id": "src-1"})
