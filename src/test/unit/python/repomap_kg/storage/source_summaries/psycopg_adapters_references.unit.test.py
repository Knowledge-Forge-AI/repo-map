import unittest
from unittest.mock import patch

from repomap_kg.storage import (
    build_source_feed_item_query_sql,
    build_source_feed_item_explanation_query_sql,
    build_source_reference_query_sql,
    query_source_feed_item_records,
    query_source_feed_item_explanation,
    query_source_reference_records,
)

class StorageSourceReferenceAdapterUnitTests(unittest.TestCase):
    def test_psycopg37_query_source_feed_item_records_uses_json_readback_adapter(self):
        payload = [
            {
                "item_key": "feed.item:fixture:item-1",
                "title": "Synthetic Feed Item",
                "published_at": "2026-06-30T12:00:00Z",
                "updated_at": "2026-06-30T12:30:00Z",
                "identity_source": "guid",
                "identity_strength": "strong",
                "duplicate_identity": False,
                "link_targets": ["external.url:https%3A%2F%2Fexample.invalid%2Fitem-1"],
                "authors": ["Example Author"],
                "categories": ["release"],
                "source_run_id": "20260630T120000Z",
                "artifact_id": "abc123",
                "artifact_path": ".repomap/source-artifacts/example/rss.xml",
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
                side_effect=AssertionError("source feed items must use the adapter"),
            ),
        ):
            records = query_source_feed_item_records(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
                source_id="example-news-feed",
                source_run_id="20260630T120000Z",
                limit=5,
                psql_command="custom-psql",
            )

        self.assertEqual(execute_json_readback.call_count, 1)
        self.assertEqual(
            captured,
            {
                "sql": build_source_feed_item_query_sql(
                    "/tmp/fixture",
                    source_id="example-news-feed",
                    source_run_id="20260630T120000Z",
                    limit=5,
                ),
                "psql_args": ("-d", "postgres"),
                "psql_command": "custom-psql",
                "label": "source feed item records",
                "expected_shape": "array",
            },
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].item_key, "feed.item:fixture:item-1")
        self.assertEqual(records[0].title, "Synthetic Feed Item")
        self.assertEqual(records[0].published_at, "2026-06-30T12:00:00Z")
        self.assertEqual(records[0].updated_at, "2026-06-30T12:30:00Z")
        self.assertEqual(records[0].identity_source, "guid")
        self.assertEqual(records[0].identity_strength, "strong")
        self.assertFalse(records[0].duplicate_identity)
        self.assertEqual(
            records[0].link_targets,
            ("external.url:https%3A%2F%2Fexample.invalid%2Fitem-1",),
        )
        self.assertEqual(records[0].authors, ("Example Author",))
        self.assertEqual(records[0].categories, ("release",))
        self.assertEqual(records[0].source_run_id, "20260630T120000Z")
        self.assertEqual(records[0].artifact_id, "abc123")
        self.assertEqual(
            records[0].artifact_path,
            ".repomap/source-artifacts/example/rss.xml",
        )

    def test_psycopg39_query_source_reference_records_uses_json_readback_adapter(self):
        payload = [
            {
                "source_item_key": "feed.item:fixture:item-1",
                "relation": "references",
                "target_key": "external.url:https%3A%2F%2Fexample.invalid%2Fitem-1",
                "target_display": "https://example.invalid/item-1",
                "not_fetched": True,
                "media_type": "text/html",
                "source_run_id": "20260630T120000Z",
                "artifact_id": "abc123",
                "artifact_path": ".repomap/source-artifacts/example/rss.xml",
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
                side_effect=AssertionError("source references must use the adapter"),
            ),
        ):
            records = query_source_reference_records(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
                source_id="example-news-feed",
                source_run_id="20260630T120000Z",
                target_kind="external.url",
                limit=5,
                psql_command="custom-psql",
            )

        self.assertEqual(execute_json_readback.call_count, 1)
        self.assertEqual(
            captured,
            {
                "sql": build_source_reference_query_sql(
                    "/tmp/fixture",
                    source_id="example-news-feed",
                    source_run_id="20260630T120000Z",
                    target_kind="external.url",
                    limit=5,
                ),
                "psql_args": ("-d", "postgres"),
                "psql_command": "custom-psql",
                "label": "source reference records",
                "expected_shape": "array",
            },
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].source_item_key, "feed.item:fixture:item-1")
        self.assertEqual(records[0].relation, "references")
        self.assertEqual(
            records[0].target_key,
            "external.url:https%3A%2F%2Fexample.invalid%2Fitem-1",
        )
        self.assertEqual(records[0].target_display, "https://example.invalid/item-1")
        self.assertTrue(records[0].not_fetched)
        self.assertEqual(records[0].media_type, "text/html")
        self.assertEqual(records[0].source_run_id, "20260630T120000Z")
        self.assertEqual(records[0].artifact_id, "abc123")
        self.assertEqual(
            records[0].artifact_path,
            ".repomap/source-artifacts/example/rss.xml",
        )

    def test_psycopg41_query_source_feed_item_explanation_uses_json_readback_adapter(
        self,
    ):
        payload = {
            "item": {
                "canonical_key": "feed.item:fixture:item-1",
                "graph_key_version": 1,
                "kind": "feed.item",
                "display_name": "Synthetic Feed Item",
                "confidence": "high",
                "conflict": False,
                "metadata": {"source_id": "example-news-feed"},
            },
            "source": {
                "source_id": "example-news-feed",
                "source_type": "feed.rss",
                "policy_status": "allowed_with_limits",
                "source_run_id": "20260630T120000Z",
                "artifact_id": "abc123",
                "artifact_path": ".repomap/source-artifacts/example/rss.xml",
                "acquired_at": "2026-06-30T12:00:00Z",
            },
            "evidence": [
                {
                    "evidence_key": "evidence:fixture:item-1",
                    "raw_kind": "feed.item",
                    "raw_source_id": "source:example-news-feed",
                    "path": "fixtures/source-feed/feed.xml",
                    "start_line": 12,
                    "end_line": 18,
                    "extractor": "feed",
                    "extractor_version": "1",
                    "confidence": "high",
                    "metadata": {"source_run_id": "20260630T120000Z"},
                }
            ],
            "references": [
                {
                    "target_key": "external.url:https%3A%2F%2Fexample.invalid%2Fitem-1",
                    "metadata": {
                        "target_display": "https://example.invalid/item-1",
                        "not_fetched": True,
                        "media_type": "text/html",
                    },
                }
            ],
            "content_policy": "full feed bodies are not exposed",
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
                side_effect=AssertionError("source feed explanation must use the adapter"),
            ),
        ):
            explanation = query_source_feed_item_explanation(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
                item_key="feed.item:fixture:item-1",
                source_id="example-news-feed",
                psql_command="custom-psql",
            )

        self.assertEqual(execute_json_readback.call_count, 1)
        self.assertEqual(
            captured,
            {
                "sql": build_source_feed_item_explanation_query_sql(
                    "/tmp/fixture",
                    item_key="feed.item:fixture:item-1",
                    source_id="example-news-feed",
                ),
                "psql_args": ("-d", "postgres"),
                "psql_command": "custom-psql",
                "label": "source feed item explanation",
                "expected_shape": "object",
            },
        )
        self.assertIs(explanation, payload)
        self.assertEqual(explanation["item"]["canonical_key"], "feed.item:fixture:item-1")
        self.assertEqual(explanation["source"]["source_id"], "example-news-feed")
        self.assertEqual(explanation["evidence"][0]["path"], "fixtures/source-feed/feed.xml")
        self.assertEqual(
            explanation["references"][0]["target_key"],
            "external.url:https%3A%2F%2Fexample.invalid%2Fitem-1",
        )
        self.assertEqual(
            explanation["content_policy"],
            "full feed bodies are not exposed",
        )
