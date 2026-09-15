import subprocess
import unittest
import json
import os
from unittest.mock import patch

from repomap_kg.storage import (
    build_ingested_source_query_sql,
    build_source_feed_item_query_sql,
    build_source_reference_query_sql,
    build_source_run_query_sql,
    build_source_summary_query_sql,
    ingested_source_record_from_storage_payload,
    source_feed_item_record_from_storage_payload,
    source_reference_record_from_storage_payload,
    source_run_record_from_storage_payload,
    source_summary_from_storage_payload,
    query_ingested_source_records,
    query_source_feed_item_records,
    query_source_reference_records,
    query_source_run_records,
    query_source_summary,
)
from repomap_kg.storage.readback_driver import PG_CONNECTOR_ENV, READBACK_DRIVER_ENV

class StorageSourceFeedHelperUnitTests(unittest.TestCase):
    def test_build_source_feed_queries_use_read_only_metadata_filters(self):
        sources_sql = build_ingested_source_query_sql(
            "/tmp/fixture",
            source_type="feed.rss",
            policy_status="allowed_with_limits",
            limit=10,
        )
        self.assertIn("raw_observations", sources_sql)
        self.assertIn("source_id_configured", sources_sql)
        self.assertIn("source_type = 'feed.rss'", sources_sql)
        self.assertIn("source_policy_status = 'allowed_with_limits'", sources_sql)
        self.assertIn("LIMIT 10", sources_sql)
        self.assertNotIn("INSERT ", sources_sql.upper())
        self.assertNotIn("UPDATE ", sources_sql.upper())

        summary_sql = build_source_summary_query_sql(
            "/tmp/fixture",
            source_id="example-news-feed",
        )
        self.assertIn("canonical_nodes.kind = 'feed.item'", summary_sql)
        self.assertIn("source_id_configured = 'example-news-feed'", summary_sql)

        runs_sql = build_source_run_query_sql(
            "/tmp/fixture",
            source_id="example-news-feed",
            limit=5,
        )
        self.assertIn("source_run_id", runs_sql)
        self.assertIn("ORDER BY source_acquired_at DESC", runs_sql)

        items_sql = build_source_feed_item_query_sql(
            "/tmp/fixture",
            source_id="example-news-feed",
            source_run_id="20260630T120000Z",
            limit=25,
        )
        self.assertIn("feed.item", items_sql)
        self.assertIn("source_run_id = '20260630T120000Z'", items_sql)
        self.assertIn("canonical_nodes.canonical_key", items_sql)
        self.assertIn("LIMIT 25) item_rows", items_sql)

        references_sql = build_source_reference_query_sql(
            "/tmp/fixture",
            source_id="example-news-feed",
            target_kind="external.url",
            limit=25,
        )
        self.assertIn("canonical_edges.edge_kind = 'references'", references_sql)
        self.assertIn("external.url", references_sql)
        self.assertIn("LIMIT 25) reference_rows", references_sql)
    def test_source_feed_payload_parsers_preserve_safe_summary_fields(self):
        source = ingested_source_record_from_storage_payload(
            {
                "source_id": "example-news-feed",
                "source_type": "feed.rss",
                "display_name": "Example News Feed",
                "policy_status": "allowed_with_limits",
                "latest_source_run_id": "20260630T120000Z",
                "latest_artifact_id": "abc123",
                "latest_artifact_path": ".repomap/source-artifacts/example/rss.xml",
                "latest_acquired_at": "2026-06-30T12:00:00Z",
                "feed_observation_count": 8,
                "canonical_feed_item_count": 2,
            }
        )
        self.assertEqual(source.source_id, "example-news-feed")
        self.assertEqual(source.canonical_feed_item_count, 2)

        summary = source_summary_from_storage_payload(
            {
                "source_id": "example-news-feed",
                "source_type": "feed.rss",
                "display_name": "Example News Feed",
                "policy_status": "allowed_with_limits",
                "configured_url_summary": "https://example.invalid/feed.xml",
                "latest_source_run_id": "20260630T120000Z",
                "latest_artifact_id": "abc123",
                "latest_artifact_path": ".repomap/source-artifacts/example/rss.xml",
                "latest_acquired_at": "2026-06-30T12:00:00Z",
                "feed_documents": 1,
                "feed_channels": 1,
                "feed_items": 2,
                "feed_authors": 1,
                "feed_categories": 2,
                "link_references": 2,
                "enclosure_references": 1,
                "parse_errors": 0,
                "known_limitations": ["source metadata is inferred from RSS2 evidence"],
            }
        )
        self.assertEqual(summary.feed_items, 2)
        self.assertEqual(
            summary.known_limitations[0],
            "source metadata is inferred from RSS2 evidence",
        )

        run = source_run_record_from_storage_payload(
            {
                "source_run_id": "20260630T120000Z",
                "acquired_at": "2026-06-30T12:00:00Z",
                "artifact_id": "abc123",
                "artifact_path": ".repomap/source-artifacts/example/rss.xml",
                "artifact_byte_length": 512,
                "artifact_sha256": "0" * 64,
                "http_status": 200,
                "content_type": "application/rss+xml",
                "observation_count": 8,
                "status_summary": "ok",
            }
        )
        self.assertEqual(run.artifact_byte_length, 512)

        item_key = (
            "feed.item:feed.channel%3Afeed.document%253Afile%25253Arss.xml%3Aself:item-1"
        )
        item = source_feed_item_record_from_storage_payload(
            {
                "item_key": item_key,
                "title": "Release note",
                "published_at": "2026-06-30T12:00:00Z",
                "updated_at": None,
                "identity_source": "guid",
                "identity_strength": "strong",
                "duplicate_identity": False,
                "link_targets": ["external.url:https%3A%2F%2Fexample.invalid%2Fitems%2F1"],
                "authors": ["Example Author"],
                "categories": ["release"],
                "source_run_id": "20260630T120000Z",
                "artifact_id": "abc123",
                "artifact_path": ".repomap/source-artifacts/example/rss.xml",
            }
        )
        self.assertEqual(item.identity_strength, "strong")
        self.assertEqual(
            item.link_targets,
            ("external.url:https%3A%2F%2Fexample.invalid%2Fitems%2F1",),
        )

        reference = source_reference_record_from_storage_payload(
            {
                "source_item_key": item.item_key,
                "relation": "references",
                "target_key": "external.url:https%3A%2F%2Fexample.invalid%2Fitems%2F1",
                "target_display": "https://example.invalid/items/1",
                "not_fetched": True,
                "media_type": "text/html",
                "source_run_id": "20260630T120000Z",
                "artifact_id": "abc123",
                "artifact_path": ".repomap/source-artifacts/example/rss.xml",
            }
        )
        self.assertTrue(reference.not_fetched)
    def test_query_source_feed_helpers_parse_psql_json(self):
        item_key = (
            "feed.item:feed.channel%3Afeed.document%253Afile%25253Arss.xml%3Aself:item-1"
        )
        payloads = [
            json.dumps(
                [
                    {
                        "source_id": "example-news-feed",
                        "source_type": "feed.rss",
                        "display_name": "Example News Feed",
                        "policy_status": "allowed_with_limits",
                        "latest_source_run_id": "20260630T120000Z",
                        "latest_artifact_id": "abc123",
                        "latest_artifact_path": ".repomap/source-artifacts/example/rss.xml",
                        "latest_acquired_at": "2026-06-30T12:00:00Z",
                        "feed_observation_count": 8,
                        "canonical_feed_item_count": 2,
                    }
                ]
            ),
            json.dumps(
                {
                    "source_id": "example-news-feed",
                    "source_type": "feed.rss",
                    "display_name": "Example News Feed",
                    "policy_status": "allowed_with_limits",
                    "configured_url_summary": "https://example.invalid/feed.xml",
                    "latest_source_run_id": "20260630T120000Z",
                    "latest_artifact_id": "abc123",
                    "latest_artifact_path": ".repomap/source-artifacts/example/rss.xml",
                    "latest_acquired_at": "2026-06-30T12:00:00Z",
                    "feed_documents": 1,
                    "feed_channels": 1,
                    "feed_items": 2,
                    "feed_authors": 0,
                    "feed_categories": 0,
                    "link_references": 1,
                    "enclosure_references": 0,
                    "parse_errors": 0,
                    "known_limitations": [],
                }
            ),
            json.dumps(
                [
                    {
                        "source_run_id": "20260630T120000Z",
                        "acquired_at": "2026-06-30T12:00:00Z",
                        "artifact_id": "abc123",
                        "artifact_path": ".repomap/source-artifacts/example/rss.xml",
                        "artifact_byte_length": 512,
                        "artifact_sha256": "0" * 64,
                        "http_status": 200,
                        "content_type": "application/rss+xml",
                        "observation_count": 8,
                        "status_summary": "ok",
                    }
                ]
            ),
            json.dumps(
                [
                    {
                        "item_key": item_key,
                        "title": "Release note",
                        "published_at": "2026-06-30T12:00:00Z",
                        "updated_at": None,
                        "identity_source": "guid",
                        "identity_strength": "strong",
                        "duplicate_identity": False,
                        "link_targets": [],
                        "authors": [],
                        "categories": [],
                        "source_run_id": "20260630T120000Z",
                        "artifact_id": "abc123",
                        "artifact_path": ".repomap/source-artifacts/example/rss.xml",
                    }
                ]
            ),
            json.dumps(
                [
                    {
                        "source_item_key": item_key,
                        "relation": "references",
                        "target_key": "external.url:https%3A%2F%2Fexample.invalid%2Fitems%2F1",
                        "target_display": "https://example.invalid/items/1",
                        "not_fetched": True,
                        "media_type": None,
                        "source_run_id": "20260630T120000Z",
                        "artifact_id": "abc123",
                        "artifact_path": ".repomap/source-artifacts/example/rss.xml",
                    }
                ]
            ),
        ]
        with (
            patch.dict(
                os.environ,
                {
                    PG_CONNECTOR_ENV: "psql",
                    READBACK_DRIVER_ENV: "psql",
                },
            ),
            patch("repomap_kg.storage.subprocess.run") as run,
        ):
            run.side_effect = [
                subprocess.CompletedProcess(["psql"], 0, stdout=f"{payload}\n")
                for payload in payloads
            ]
            sources = query_ingested_source_records(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
            )
            summary = query_source_summary(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
                source_id="example-news-feed",
            )
            runs = query_source_run_records(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
                source_id="example-news-feed",
            )
            items = query_source_feed_item_records(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
                source_id="example-news-feed",
            )
            references = query_source_reference_records(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
                source_id="example-news-feed",
            )

        self.assertEqual(sources[0].source_id, "example-news-feed")
        self.assertEqual(summary.feed_items, 2)
        self.assertEqual(runs[0].source_run_id, "20260630T120000Z")
        self.assertEqual(items[0].item_key, item_key)
        self.assertEqual(references[0].relation, "references")
        for call in run.call_args_list:
            sql = call.kwargs["input"]
            self.assertNotIn("INSERT ", sql.upper())
            self.assertNotIn("UPDATE ", sql.upper())
