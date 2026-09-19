"""Configured MCP identity routing and compatibility (ADR 0068)."""

from unittest.mock import MagicMock, patch

from repomap_test_support.mcp_server import McpServerTestSupport


class ConfiguredStorageIdentityTests(McpServerTestSupport):
    def test_storage_connection_configured_identity_forwarding_and_kwargs_merging(self) -> None:
        from repomap_kg.server.mcp_core import StorageConnection
        from repomap_kg.server.ops import graph_context

        config_path = self.write_ops_config(self.visible_ops_config())
        with patch.dict("os.environ", {"REPOMAP_OPS_CONFIG": str(config_path)}, clear=True):
            context = graph_context("repo-map")

        legacy_connection = StorageConnection(
            root_path="/tmp/legacy",
            pg_database="repomap",
            root_path_display="[explicit-root]",
            ops_context=None,
        )
        self.assertIsNone(legacy_connection.repository_identity)

        configured_connection = StorageConnection(
            root_path=context.root_path,
            pg_database=context.database,
            root_path_display="[graph-root]",
            ops_context=context,
        )
        self.assertEqual(configured_connection.repository_identity, "repo1:repo-map")

        mock_storage = MagicMock(return_value="readback_result")
        with patch("repomap_kg.server.mcp_core.query_configured_storage", mock_storage):
            result = configured_connection.query_storage(
                MagicMock(),
                root_path=configured_connection.root_path,
            )
            self.assertEqual(result, "readback_result")
            self.assertEqual(mock_storage.call_args.kwargs["repository_identity"], "repo1:repo-map")
            self.assertEqual(mock_storage.call_args.kwargs["root_path"], "/tmp/fixture")

            result_override = configured_connection.query_storage(
                MagicMock(),
                root_path=configured_connection.root_path,
                repository_identity="conflicting-caller-val",
            )
            self.assertEqual(result_override, "readback_result")
            self.assertEqual(mock_storage.call_args.kwargs["repository_identity"], "repo1:repo-map")

        legacy_mock = MagicMock(return_value="legacy_result")
        result_legacy = legacy_connection.query_storage(
            legacy_mock,
            root_path=legacy_connection.root_path,
        )
        self.assertEqual(result_legacy, "legacy_result")
        self.assertNotIn("repository_identity", legacy_mock.call_args.kwargs)
        self.assertEqual(legacy_mock.call_args.kwargs["root_path"], "/tmp/legacy")

    def test_all_eleven_exposed_tools_forward_configured_identity(self) -> None:
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
            IngestedSourceRecord,
            SourceFeedItemRecord,
            SourceReferenceRecord,
            SourceRunRecord,
            SourceSummaryRecord,
            identity_metadata_hash,
        )

        config_path = self.write_ops_config(self.visible_ops_config())
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
        edge_explanation = CanonicalEdgeExplanationRecord(
            edge=edge,
            evidence=(),
        )
        neighborhood = CanonicalNeighborhoodRecord(
            center=node,
            nodes=(),
            edges=(),
        )
        status_summary = CanonicalStorageSummaryRecord(
            root_path="/tmp/fixture",
            repository_name="fixture",
            latest_run_id=1,
            runs=1,
            files=1,
            raw_observations=1,
            canonical_nodes=1,
            canonical_edges=1,
            canonical_evidence=1,
        )
        ingested_source = IngestedSourceRecord(
            source_id="example-feed",
            source_type="feed.rss",
            display_name="Example Feed",
            policy_status="allowed_with_limits",
            latest_source_run_id="20260630T120000Z",
            latest_artifact_id="abc123",
            latest_artifact_path="rss.xml",
            latest_acquired_at="2026-06-30T12:00:00Z",
            feed_observation_count=1,
            canonical_feed_item_count=1,
        )
        src_summary = SourceSummaryRecord(
            source_id="example-feed",
            source_type="feed.rss",
            display_name="Example Feed",
            policy_status="allowed_with_limits",
            configured_url_summary="https://example.invalid/feed.xml",
            latest_source_run_id="20260630T120000Z",
            latest_artifact_id="abc123",
            latest_artifact_path="rss.xml",
            latest_acquired_at="2026-06-30T12:00:00Z",
            feed_documents=1,
            feed_channels=1,
            feed_items=1,
            feed_authors=1,
            feed_categories=1,
            link_references=1,
            enclosure_references=1,
            parse_errors=0,
            known_limitations=(),
        )
        source_run = SourceRunRecord(
            source_run_id="20260630T120000Z",
            acquired_at="2026-06-30T12:00:00Z",
            artifact_id="abc123",
            artifact_path="rss.xml",
            artifact_byte_length=512,
            artifact_sha256="0" * 64,
            http_status=200,
            content_type="application/rss+xml",
            observation_count=1,
            status_summary="ok",
        )
        feed_item = SourceFeedItemRecord(
            item_key="feed.item:example:1",
            title="Item 1",
            published_at=None,
            updated_at=None,
            identity_source=None,
            identity_strength=None,
            duplicate_identity=False,
            link_targets=(),
            authors=(),
            categories=(),
            source_run_id="20260630T120000Z",
            artifact_id="abc123",
            artifact_path="rss.xml",
        )
        source_ref = SourceReferenceRecord(
            source_item_key="feed.item:example:1",
            relation="targets",
            target_key="python.module:repomap_kg.cli",
            target_display="cli",
            not_fetched=False,
            media_type=None,
            source_run_id="20260630T120000Z",
            artifact_id="abc123",
            artifact_path="rss.xml",
        )

        with (
            patch.dict("os.environ", {"REPOMAP_OPS_CONFIG": str(config_path)}, clear=True),
            patch("repomap_kg.server.mcp.query_canonical_storage_summary", return_value=status_summary) as mock_status,
            patch("repomap_kg.server.mcp.query_canonical_node_records", return_value=(node,)) as mock_nodes,
            patch("repomap_kg.server.mcp.query_canonical_edge_records", return_value=(edge,)) as mock_edges,
            patch("repomap_kg.server.mcp.query_canonical_edge_explanation", return_value=edge_explanation) as mock_explain_edge,
            patch("repomap_kg.server.mcp.query_canonical_neighborhood", return_value=neighborhood) as mock_neighborhood,
            patch("repomap_kg.server.mcp.query_ingested_source_records", return_value=(ingested_source,)) as mock_sources,
            patch("repomap_kg.server.mcp.query_source_summary", return_value=src_summary) as mock_source_summary,
            patch("repomap_kg.server.mcp.query_source_run_records", return_value=(source_run,)) as mock_source_runs,
            patch("repomap_kg.server.mcp.query_source_feed_item_records", return_value=(feed_item,)) as mock_feed_items,
            patch("repomap_kg.server.mcp.query_source_feed_item_explanation", return_value={"item_key": "feed.item:example:1"}) as mock_explain_feed,
            patch("repomap_kg.server.mcp.query_source_reference_records", return_value=(source_ref,)) as mock_source_refs,
        ):
            # 1. status
            repomap_status(project="repo-map")
            self.assertEqual(mock_status.call_args.kwargs["repository_identity"], "repo1:repo-map")

            # 2. canonical nodes
            repomap_canonical_nodes(project="repo-map", kind="python.module")
            self.assertEqual(mock_nodes.call_args.kwargs["repository_identity"], "repo1:repo-map")

            # 3. canonical edges
            repomap_canonical_edges(project="repo-map", kind="imports")
            self.assertEqual(mock_edges.call_args.kwargs["repository_identity"], "repo1:repo-map")

            # 4. canonical explain
            repomap_explain_canonical_edge(
                project="repo-map",
                source_key="python.module:repomap_kg.cli",
                kind="imports",
                target_key="python.module:repomap_kg.storage",
                identity_metadata={},
            )
            self.assertEqual(mock_explain_edge.call_args.kwargs["repository_identity"], "repo1:repo-map")

            # 5. canonical neighborhood
            repomap_canonical_neighborhood(project="repo-map", node="python.module:repomap_kg.cli")
            self.assertEqual(mock_neighborhood.call_args.kwargs["repository_identity"], "repo1:repo-map")

            # 6. ingested sources
            repomap_ingested_sources(project="repo-map")
            self.assertEqual(mock_sources.call_args.kwargs["repository_identity"], "repo1:repo-map")

            # 7. source summary
            repomap_source_summary(project="repo-map", source_id="example-feed")
            self.assertEqual(mock_source_summary.call_args.kwargs["repository_identity"], "repo1:repo-map")

            # 8. source runs
            repomap_source_runs(project="repo-map", source_id="example-feed")
            self.assertEqual(mock_source_runs.call_args.kwargs["repository_identity"], "repo1:repo-map")

            # 9. source feed items
            repomap_source_feed_items(project="repo-map", source_id="example-feed")
            self.assertEqual(mock_feed_items.call_args.kwargs["repository_identity"], "repo1:repo-map")

            # 10. explain source feed item
            repomap_explain_source_feed_item(project="repo-map", item_key="feed.item:example:1")
            self.assertEqual(mock_explain_feed.call_args.kwargs["repository_identity"], "repo1:repo-map")

            # 11. source references
            repomap_source_references(project="repo-map", source_id="example-feed")
            self.assertEqual(mock_source_refs.call_args.kwargs["repository_identity"], "repo1:repo-map")

    def test_configured_status_repository_name_from_row_and_root_display_marker(self) -> None:
        from repomap_kg.server.mcp import repomap_status
        from repomap_kg.storage import CanonicalStorageSummaryRecord

        config_path = self.write_ops_config(self.visible_ops_config())
        with (
            patch.dict("os.environ", {"REPOMAP_OPS_CONFIG": str(config_path)}, clear=True),
            patch("repomap_kg.server.mcp.query_canonical_storage_summary") as mock_summary,
        ):
            # 1. Public graph: repository_name comes from selected current row; root stays display marker
            mock_summary.return_value = CanonicalStorageSummaryRecord(
                root_path="/relocated/actual/storage/path",
                repository_name="relocated-current-name",
                latest_run_id=42,
                runs=3,
                files=10,
                raw_observations=50,
                canonical_nodes=20,
                canonical_edges=30,
                canonical_evidence=40,
            )
            payload_public = repomap_status(project="repo-map")
            self.assertEqual(payload_public["repository_name"], "relocated-current-name")
            self.assertEqual(payload_public["root_path"], "[graph-root]")
            self.assertEqual(payload_public["project"], "repo-map")
            self.assertEqual(mock_summary.call_args.kwargs["repository_identity"], "repo1:repo-map")

            # 2. Private graph: repository_name comes from row, root stays [private-root]
            mock_summary.return_value = CanonicalStorageSummaryRecord(
                root_path="/private/actual/storage/path",
                repository_name="private-current-name",
                latest_run_id=43,
                runs=2,
                files=5,
                raw_observations=20,
                canonical_nodes=10,
                canonical_edges=15,
                canonical_evidence=25,
            )
            payload_private = repomap_status(project="private-visible")
            self.assertEqual(payload_private["repository_name"], "private-current-name")
            self.assertEqual(payload_private["root_path"], "[private-root]")
            self.assertEqual(payload_private["project"], "private-visible")
            self.assertEqual(mock_summary.call_args.kwargs["repository_identity"], "repo1:private-visible")
