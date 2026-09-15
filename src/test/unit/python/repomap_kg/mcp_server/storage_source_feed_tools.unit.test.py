import json
from typing import Any
from unittest.mock import patch

from repomap_kg.storage import (
    IngestedSourceRecord,
    SourceFeedItemRecord,
    SourceReferenceRecord,
    SourceRunRecord,
    SourceSummaryRecord,
)
from repomap_test_support.mcp_server import McpServerTestSupport

class McpServerStorageSourceFeedToolUnitTests(McpServerTestSupport):
    def test_source_feed_mcp_tools_are_read_only_and_project_scoped(self):
        from repomap_kg.server.mcp import (
            repomap_explain_source_feed_item,
            repomap_ingested_sources,
            repomap_source_feed_items,
            repomap_source_references,
            repomap_source_runs,
            repomap_source_summary,
        )

        config_path = self.write_mcp_config(
            {
                "default_project": "repo-map",
                "projects": {
                    "repo-map": {
                        "root_path": "/workspace/repo-map",
                        "pg_database": "repomap_repo_map",
                    },
                },
            }
        )
        item_key = (
            "feed.item:feed.channel%3Afeed.document%253Afile%25253Arss.xml%3Aself:item-1"
        )
        with patch.dict("os.environ", {"REPOMAP_MCP_CONFIG": str(config_path)}):
            with patch(
                "repomap_kg.server.mcp.query_ingested_source_records",
                return_value=(
                    IngestedSourceRecord(
                        source_id="example-news-feed",
                        source_type="feed.rss",
                        display_name="Example News Feed",
                        policy_status="allowed_with_limits",
                        latest_source_run_id="20260630T120000Z",
                        latest_artifact_id="abc123",
                        latest_artifact_path=".repomap/source-artifacts/example/rss.xml",
                        latest_acquired_at="2026-06-30T12:00:00Z",
                        feed_observation_count=8,
                        canonical_feed_item_count=2,
                    ),
                ),
            ) as sources_query:
                sources_payload = repomap_ingested_sources(source_type="feed.rss")
            with patch(
                "repomap_kg.server.mcp.query_source_summary",
                return_value=SourceSummaryRecord(
                    source_id="example-news-feed",
                    source_type="feed.rss",
                    display_name="Example News Feed",
                    policy_status="allowed_with_limits",
                    configured_url_summary="https://example.invalid/feed.xml",
                    latest_source_run_id="20260630T120000Z",
                    latest_artifact_id="abc123",
                    latest_artifact_path=".repomap/source-artifacts/example/rss.xml",
                    latest_acquired_at="2026-06-30T12:00:00Z",
                    feed_documents=1,
                    feed_channels=1,
                    feed_items=2,
                    feed_authors=1,
                    feed_categories=2,
                    link_references=2,
                    enclosure_references=1,
                    parse_errors=0,
                    known_limitations=("source metadata is inferred from RSS2 evidence",),
                ),
            ) as summary_query:
                summary_payload = repomap_source_summary(
                    source_id="example-news-feed",
                )
            with patch(
                "repomap_kg.server.mcp.query_source_run_records",
                return_value=(
                    SourceRunRecord(
                        source_run_id="20260630T120000Z",
                        acquired_at="2026-06-30T12:00:00Z",
                        artifact_id="abc123",
                        artifact_path=".repomap/source-artifacts/example/rss.xml",
                        artifact_byte_length=512,
                        artifact_sha256="0" * 64,
                        http_status=200,
                        content_type="application/rss+xml",
                        observation_count=8,
                        status_summary="ok",
                    ),
                ),
            ) as runs_query:
                runs_payload = repomap_source_runs(source_id="example-news-feed")
            with patch(
                "repomap_kg.server.mcp.query_source_feed_item_records",
                return_value=(
                    SourceFeedItemRecord(
                        item_key=item_key,
                        title="Release note",
                        published_at="2026-06-30T12:00:00Z",
                        updated_at=None,
                        identity_source="guid",
                        identity_strength="strong",
                        duplicate_identity=False,
                        link_targets=(),
                        authors=("Example Author",),
                        categories=("release",),
                        source_run_id="20260630T120000Z",
                        artifact_id="abc123",
                        artifact_path=".repomap/source-artifacts/example/rss.xml",
                    ),
                ),
            ) as items_query:
                items_payload = repomap_source_feed_items(
                    source_id="example-news-feed",
                )
            with patch(
                "repomap_kg.server.mcp.query_source_reference_records",
                return_value=(
                    SourceReferenceRecord(
                        source_item_key=item_key,
                        relation="references",
                        target_key="external.url:https%3A%2F%2Fexample.invalid%2Fitems%2F1",
                        target_display="https://example.invalid/items/1",
                        not_fetched=True,
                        media_type=None,
                        source_run_id="20260630T120000Z",
                        artifact_id="abc123",
                        artifact_path=".repomap/source-artifacts/example/rss.xml",
                    ),
                ),
            ) as references_query:
                references_payload = repomap_source_references(
                    source_id="example-news-feed",
                    target_kind="external.url",
                )
            with patch(
                "repomap_kg.server.mcp.query_source_feed_item_explanation",
                return_value={
                    "item": {"canonical_key": item_key, "kind": "feed.item"},
                    "source": {"source_id": "example-news-feed"},
                    "evidence": [],
                    "references": [],
                    "content_policy": "full feed bodies are not exposed",
                },
            ) as explain_query:
                explanation_payload = repomap_explain_source_feed_item(
                    item_key=item_key,
                )

        self.assertEqual(sources_payload[0]["source_id"], "example-news-feed")
        self.assertEqual(summary_payload["feed_items"], 2)
        self.assertEqual(runs_payload[0]["source_run_id"], "20260630T120000Z")
        self.assertEqual(items_payload[0]["item_key"], item_key)
        self.assertTrue(references_payload[0]["not_fetched"])
        self.assertEqual(explanation_payload["item"]["canonical_key"], item_key)
        self.assertEqual(sources_query.call_args.args[0], ["-d", "repomap_repo_map"])
        self.assertEqual(sources_query.call_args.kwargs["root_path"], "/workspace/repo-map")
        self.assertEqual(summary_query.call_args.kwargs["source_id"], "example-news-feed")
        self.assertEqual(runs_query.call_args.kwargs["source_id"], "example-news-feed")
        self.assertEqual(items_query.call_args.kwargs["source_id"], "example-news-feed")
        self.assertEqual(references_query.call_args.kwargs["target_kind"], "external.url")
        self.assertEqual(explain_query.call_args.kwargs["item_key"], item_key)

    def test_source_feed_mcp_empty_and_missing_results_are_bounded(self):
        from repomap_kg.server.mcp import (
            repomap_explain_source_feed_item,
            repomap_ingested_sources,
            repomap_source_feed_items,
            repomap_source_references,
            repomap_source_runs,
            repomap_source_summary,
        )

        private_root = "/Users/synthetic-user/private-repo"
        private_database = "synthetic_private_database"
        private_host = "synthetic-private-host.invalid"
        private_user = "synthetic-user"
        private_token = "synthetic-secret-token"
        connection_kwargs: dict[str, Any] = {
            "root_path": private_root,
            "pg_database": private_database,
            "pg_host": private_host,
            "pg_user": private_user,
        }
        missing_source_id = "synthetic-missing-source"
        item_key = (
            "feed.item:feed.channel%3Afeed.document%253Afile%25253Arss.xml%3Aself:item-1"
        )

        with patch(
            "repomap_kg.server.mcp.query_ingested_source_records",
            return_value=(),
        ) as sources_query:
            sources_payload = repomap_ingested_sources(
                **connection_kwargs,
                source_type="feed.rss",
            )
        with patch(
            "repomap_kg.server.mcp.query_source_summary",
            return_value=SourceSummaryRecord(
                source_id=missing_source_id,
                source_type="unknown",
                display_name=None,
                policy_status="unknown",
                configured_url_summary=None,
                latest_source_run_id=None,
                latest_artifact_id=None,
                latest_artifact_path=None,
                latest_acquired_at=None,
                feed_documents=0,
                feed_channels=0,
                feed_items=0,
                feed_authors=0,
                feed_categories=0,
                link_references=0,
                enclosure_references=0,
                parse_errors=0,
                known_limitations=("source metadata unavailable",),
            ),
        ) as summary_query:
            summary_payload = repomap_source_summary(
                **connection_kwargs,
                source_id=missing_source_id,
            )
        with patch(
            "repomap_kg.server.mcp.query_source_run_records",
            return_value=(),
        ) as runs_query:
            runs_payload = repomap_source_runs(
                **connection_kwargs,
                source_id=missing_source_id,
            )
        with patch(
            "repomap_kg.server.mcp.query_source_feed_item_records",
            return_value=(),
        ) as items_query:
            items_payload = repomap_source_feed_items(
                **connection_kwargs,
                source_id=missing_source_id,
            )
        with patch(
            "repomap_kg.server.mcp.query_source_reference_records",
            return_value=(),
        ) as references_query:
            references_payload = repomap_source_references(
                **connection_kwargs,
                source_id=missing_source_id,
            )
        with patch(
            "repomap_kg.server.mcp.query_source_feed_item_explanation",
            return_value={
                "item": None,
                "source": None,
                "evidence": [],
                "references": [],
                "content_policy": "full feed bodies are not exposed",
            },
        ) as explain_query:
            explanation_payload = repomap_explain_source_feed_item(
                **connection_kwargs,
                source_id=missing_source_id,
                item_key=item_key,
            )

        self.assertEqual(sources_payload, [])
        self.assertEqual(summary_payload["source_id"], missing_source_id)
        self.assertEqual(summary_payload["policy_status"], "unknown")
        self.assertEqual(summary_payload["feed_items"], 0)
        self.assertEqual(
            summary_payload["known_limitations"],
            ("source metadata unavailable",),
        )
        self.assertEqual(runs_payload, [])
        self.assertEqual(items_payload, [])
        self.assertEqual(references_payload, [])
        self.assertIsNone(explanation_payload["item"])
        self.assertEqual(
            explanation_payload["content_policy"],
            "full feed bodies are not exposed",
        )
        self.assertEqual(sources_query.call_args.kwargs["root_path"], private_root)
        self.assertEqual(summary_query.call_args.kwargs["source_id"], missing_source_id)
        self.assertEqual(runs_query.call_args.kwargs["source_id"], missing_source_id)
        self.assertEqual(items_query.call_args.kwargs["source_id"], missing_source_id)
        self.assertEqual(
            references_query.call_args.kwargs["source_id"],
            missing_source_id,
        )
        self.assertEqual(explain_query.call_args.kwargs["source_id"], missing_source_id)

        serialized = json.dumps(
            {
                "sources": sources_payload,
                "summary": summary_payload,
                "runs": runs_payload,
                "items": items_payload,
                "references": references_payload,
                "explanation": explanation_payload,
            },
            sort_keys=True,
        )
        for private_value in (
            private_root,
            private_database,
            private_host,
            private_user,
            private_token,
            "postgresql://synthetic-user:synthetic-secret@example.invalid/db",
        ):
            self.assertNotIn(private_value, serialized)
        self.assertNotIn("raw-private-source-snippet", serialized)

    def test_source_feed_mcp_tools_reject_arbitrary_url_inputs(self):
        from repomap_kg.server.mcp import RepoMapMcpError, tool_input_schema

        for name in (
            "repomap_ingested_sources",
            "repomap_source_summary",
            "repomap_source_runs",
            "repomap_source_feed_items",
            "repomap_explain_source_feed_item",
            "repomap_source_references",
        ):
            with self.subTest(tool=name):
                schema = tool_input_schema(name)
                self.assertNotIn("url", schema["properties"])
                self.assertNotIn("feed_url", schema["properties"])
                self.assertNotIn("config_path", schema["properties"])

        from repomap_kg.server.mcp import repomap_source_summary

        with self.assertRaisesRegex(RepoMapMcpError, "source_id must not be a URL"):
            repomap_source_summary(
                root_path="/tmp/fixture",
                pg_database="postgres",
                source_id="https://example.invalid/feed.xml",
            )
