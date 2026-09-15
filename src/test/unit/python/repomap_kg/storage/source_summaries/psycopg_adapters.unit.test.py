import unittest
from unittest.mock import patch

from repomap_kg.storage import (
    build_ingested_source_query_sql,
    build_source_run_query_sql,
    build_source_summary_query_sql,
    query_ingested_source_records,
    query_source_run_records,
    query_source_summary,
)

class StorageSourcePsycopgAdapterUnitTests(unittest.TestCase):
    def test_psycopg31_query_source_summary_uses_json_readback_adapter(self):
        payload = {
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
        captured = {}

        def fake_execute_json_readback(
            sql,
            *,
            psql_args,
            psql_command,
            label,
            expected_shape,
        ):
            captured.update(
                {
                    "sql": sql,
                    "psql_args": tuple(psql_args),
                    "psql_command": psql_command,
                    "label": label,
                    "expected_shape": expected_shape,
                }
            )
            return payload

        with (
            patch(
                "repomap_kg.storage.source_readback.execute_json_readback",
                side_effect=fake_execute_json_readback,
            ) as execute_json_readback,
            patch(
                "repomap_kg.storage.readback_driver.run_psql",
                side_effect=AssertionError("source summary must use the adapter"),
            ),
        ):
            summary = query_source_summary(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
                source_id="example-news-feed",
                psql_command="custom-psql",
            )

        self.assertEqual(execute_json_readback.call_count, 1)
        self.assertEqual(
            captured,
            {
                "sql": build_source_summary_query_sql(
                    "/tmp/fixture",
                    source_id="example-news-feed",
                ),
                "psql_args": ("-d", "postgres"),
                "psql_command": "custom-psql",
                "label": "source summary",
                "expected_shape": "object",
            },
        )
        self.assertEqual(summary.source_id, "example-news-feed")
        self.assertEqual(summary.source_type, "feed.rss")
        self.assertEqual(summary.display_name, "Example News Feed")
        self.assertEqual(summary.policy_status, "allowed_with_limits")
        self.assertEqual(summary.feed_items, 2)
    def test_psycopg33_query_ingested_source_records_uses_json_readback_adapter(self):
        payload = [
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
        captured = {}

        def fake_execute_json_readback(
            sql,
            *,
            psql_args,
            psql_command,
            label,
            expected_shape,
        ):
            captured.update(
                {
                    "sql": sql,
                    "psql_args": tuple(psql_args),
                    "psql_command": psql_command,
                    "label": label,
                    "expected_shape": expected_shape,
                }
            )
            return payload

        with (
            patch(
                "repomap_kg.storage.source_readback.execute_json_readback",
                side_effect=fake_execute_json_readback,
            ) as execute_json_readback,
            patch(
                "repomap_kg.storage.readback_driver.run_psql",
                side_effect=AssertionError("ingested sources must use the adapter"),
            ),
        ):
            records = query_ingested_source_records(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
                source_type="feed.rss",
                policy_status="allowed_with_limits",
                limit=7,
                psql_command="custom-psql",
            )

        self.assertEqual(execute_json_readback.call_count, 1)
        self.assertEqual(
            captured,
            {
                "sql": build_ingested_source_query_sql(
                    "/tmp/fixture",
                    source_type="feed.rss",
                    policy_status="allowed_with_limits",
                    limit=7,
                ),
                "psql_args": ("-d", "postgres"),
                "psql_command": "custom-psql",
                "label": "ingested source records",
                "expected_shape": "array",
            },
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].source_id, "example-news-feed")
        self.assertEqual(records[0].source_type, "feed.rss")
        self.assertEqual(records[0].display_name, "Example News Feed")
        self.assertEqual(records[0].policy_status, "allowed_with_limits")
        self.assertEqual(records[0].feed_observation_count, 8)
        self.assertEqual(records[0].canonical_feed_item_count, 2)
    def test_psycopg35_query_source_run_records_uses_json_readback_adapter(self):
        payload = [
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
        captured = {}

        def fake_execute_json_readback(
            sql,
            *,
            psql_args,
            psql_command,
            label,
            expected_shape,
        ):
            captured.update(
                {
                    "sql": sql,
                    "psql_args": tuple(psql_args),
                    "psql_command": psql_command,
                    "label": label,
                    "expected_shape": expected_shape,
                }
            )
            return payload

        with (
            patch(
                "repomap_kg.storage.source_readback.execute_json_readback",
                side_effect=fake_execute_json_readback,
            ) as execute_json_readback,
            patch(
                "repomap_kg.storage.readback_driver.run_psql",
                side_effect=AssertionError("source runs must use the adapter"),
            ),
        ):
            records = query_source_run_records(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
                source_id="example-news-feed",
                limit=5,
                psql_command="custom-psql",
            )

        self.assertEqual(execute_json_readback.call_count, 1)
        self.assertEqual(
            captured,
            {
                "sql": build_source_run_query_sql(
                    "/tmp/fixture",
                    source_id="example-news-feed",
                    limit=5,
                ),
                "psql_args": ("-d", "postgres"),
                "psql_command": "custom-psql",
                "label": "source run records",
                "expected_shape": "array",
            },
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].source_run_id, "20260630T120000Z")
        self.assertEqual(records[0].artifact_byte_length, 512)
        self.assertEqual(records[0].artifact_sha256, "0" * 64)
        self.assertEqual(records[0].http_status, 200)
        self.assertEqual(records[0].content_type, "application/rss+xml")
        self.assertEqual(records[0].observation_count, 8)
        self.assertEqual(records[0].status_summary, "ok")
