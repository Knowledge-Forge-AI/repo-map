import os
import json
import tempfile
import unittest
from pathlib import Path

from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)

from repomap_kg.ops.ingestion.source import (
    FeedFetchResponse,
    ingest_feed_source,
)
from repomap_kg.storage import (
    apply_migrations,
    default_rdbms_root,
    query_source_feed_item_explanation,
    query_source_reference_records,
)
from repomap_kg.storage.readback_driver import (
    PG_CONNECTOR_ENV,
    READBACK_DRIVER_ENV,
)

from repomap_test_support.storage_integration import (
    _restore_environment_variable,
    _select_pg_connector_for_postgres,
    discovery_fixture,
    fixed_source_clock,
    publish_acquisition_summary,
    source_fixture,
)


class StorageSourceFeedItemExplanationPsycopgParityIntegrationTests(unittest.TestCase):
    def test_psycopg41_source_feed_item_explanation_psycopg_driver_parity(self):
        require_postgres_binaries()
        config_path = source_fixture("allowed-rss.toml")
        feed_body = (discovery_fixture("feed_static_basic") / "rss.xml").read_bytes()
        calls = []
        psycopg_only_psql_command = "/bin/psql-not-used-by-psycopg"
        previous_pg_connector_present = PG_CONNECTOR_ENV in os.environ
        previous_pg_connector = os.environ.get(PG_CONNECTOR_ENV)
        previous_driver_present = READBACK_DRIVER_ENV in os.environ
        previous_driver = os.environ.get(READBACK_DRIVER_ENV)
        previous_pgpassword_present = "PGPASSWORD" in os.environ
        previous_pgpassword = os.environ.get("PGPASSWORD")

        def fetcher(config):
            calls.append(config.url)
            return FeedFetchResponse(
                status=200,
                headers={"content-type": "application/rss+xml"},
                body=feed_body,
            )

        from repomap_kg.server.mcp import repomap_explain_source_feed_item

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                root_path = Path(tmpdir) / "fixture-repo"
                root_path.mkdir()
                with temporary_postgres() as postgres:
                    apply_migrations(
                        default_rdbms_root(),
                        postgres.psql_args,
                        psql_command=postgres.psql_command,
                    )
                    summary = ingest_feed_source(
                        config_path,
                        root_path=root_path,
                        fetcher=fetcher,
                        clock=fixed_source_clock,
                    )
                    publish_acquisition_summary(
                        postgres,
                        summary,
                        repository_name="fixture",
                        root_path=root_path,
                    )
                    mcp_args = {
                        "root_path": str(root_path),
                        "pg_host": str(postgres.socket_dir),
                        "pg_port": str(postgres.port),
                        "pg_user": postgres.user,
                        "pg_database": postgres.database,
                        "psql_command": postgres.psql_command,
                    }
                    _select_pg_connector_for_postgres("psql", postgres=postgres)
                    reference_records = query_source_reference_records(
                        postgres.psql_args,
                        root_path=str(root_path),
                        source_id="example-rss-feed",
                        target_kind="external.url",
                        psql_command=postgres.psql_command,
                    )
                    item_key = reference_records[0].source_item_key
                    psql_explanation = query_source_feed_item_explanation(
                        postgres.psql_args,
                        root_path=str(root_path),
                        item_key=item_key,
                        source_id="example-rss-feed",
                        psql_command=postgres.psql_command,
                    )
                    psql_unfiltered = query_source_feed_item_explanation(
                        postgres.psql_args,
                        root_path=str(root_path),
                        item_key=item_key,
                        psql_command=postgres.psql_command,
                    )
                    psql_missing_item = query_source_feed_item_explanation(
                        postgres.psql_args,
                        root_path=str(root_path),
                        item_key="feed.item:missing-psycopg41",
                        source_id="example-rss-feed",
                        psql_command=postgres.psql_command,
                    )
                    psql_missing_source = query_source_feed_item_explanation(
                        postgres.psql_args,
                        root_path=str(root_path),
                        item_key=item_key,
                        source_id="missing-source",
                        psql_command=postgres.psql_command,
                    )
                    psql_mcp_payload = repomap_explain_source_feed_item(
                        **mcp_args,
                        item_key=item_key,
                        source_id="example-rss-feed",
                    )

                    _select_pg_connector_for_postgres(None, postgres=postgres)
                    default_explanation = query_source_feed_item_explanation(
                        postgres.psql_args,
                        root_path=str(root_path),
                        item_key=item_key,
                        source_id="example-rss-feed",
                        psql_command=psycopg_only_psql_command,
                    )
                    default_unfiltered = query_source_feed_item_explanation(
                        postgres.psql_args,
                        root_path=str(root_path),
                        item_key=item_key,
                        psql_command=psycopg_only_psql_command,
                    )
                    default_missing_item = query_source_feed_item_explanation(
                        postgres.psql_args,
                        root_path=str(root_path),
                        item_key="feed.item:missing-psycopg41",
                        source_id="example-rss-feed",
                        psql_command=psycopg_only_psql_command,
                    )
                    default_missing_source = query_source_feed_item_explanation(
                        postgres.psql_args,
                        root_path=str(root_path),
                        item_key=item_key,
                        source_id="missing-source",
                        psql_command=psycopg_only_psql_command,
                    )

                    _select_pg_connector_for_postgres("psycopg", postgres=postgres)
                    psycopg_explanation = query_source_feed_item_explanation(
                        postgres.psql_args,
                        root_path=str(root_path),
                        item_key=item_key,
                        source_id="example-rss-feed",
                        psql_command=psycopg_only_psql_command,
                    )
                    psycopg_unfiltered = query_source_feed_item_explanation(
                        postgres.psql_args,
                        root_path=str(root_path),
                        item_key=item_key,
                        psql_command=psycopg_only_psql_command,
                    )
                    psycopg_missing_item = query_source_feed_item_explanation(
                        postgres.psql_args,
                        root_path=str(root_path),
                        item_key="feed.item:missing-psycopg41",
                        source_id="example-rss-feed",
                        psql_command=psycopg_only_psql_command,
                    )
                    psycopg_missing_source = query_source_feed_item_explanation(
                        postgres.psql_args,
                        root_path=str(root_path),
                        item_key=item_key,
                        source_id="missing-source",
                        psql_command=psycopg_only_psql_command,
                    )
                    psycopg_mcp_payload = repomap_explain_source_feed_item(
                        **mcp_args,
                        item_key=item_key,
                        source_id="example-rss-feed",
                    )
                    private_root = str(root_path)
        finally:
            _restore_environment_variable(
                PG_CONNECTOR_ENV,
                previous_pg_connector_present,
                previous_pg_connector,
            )
            _restore_environment_variable(
                READBACK_DRIVER_ENV,
                previous_driver_present,
                previous_driver,
            )
            _restore_environment_variable(
                "PGPASSWORD",
                previous_pgpassword_present,
                previous_pgpassword,
            )

        self.assertEqual(PG_CONNECTOR_ENV in os.environ, previous_pg_connector_present)
        self.assertEqual(os.environ.get(PG_CONNECTOR_ENV), previous_pg_connector)
        self.assertEqual(READBACK_DRIVER_ENV in os.environ, previous_driver_present)
        self.assertEqual(os.environ.get(READBACK_DRIVER_ENV), previous_driver)
        self.assertEqual("PGPASSWORD" in os.environ, previous_pgpassword_present)
        self.assertEqual(os.environ.get("PGPASSWORD"), previous_pgpassword)

        self.assertEqual(calls, ["https://example.invalid/rss.xml"])
        self.assertEqual(default_explanation, psql_explanation)
        self.assertEqual(psycopg_explanation, psql_explanation)
        self.assertEqual(default_unfiltered, psql_unfiltered)
        self.assertEqual(psycopg_unfiltered, psql_unfiltered)
        self.assertEqual(default_missing_item, psql_missing_item)
        self.assertEqual(psycopg_missing_item, psql_missing_item)
        self.assertEqual(default_missing_source, psql_missing_source)
        self.assertEqual(psycopg_missing_source, psql_missing_source)
        self.assertEqual(psql_mcp_payload, psql_explanation)
        self.assertEqual(psycopg_mcp_payload, psql_explanation)

        self.assertEqual(
            set(psql_explanation),
            {"item", "source", "evidence", "references", "content_policy"},
        )
        self.assertEqual(psql_explanation["item"]["canonical_key"], item_key)
        self.assertEqual(psql_explanation["item"]["kind"], "feed.item")
        self.assertEqual(psql_explanation["source"]["source_id"], "example-rss-feed")
        self.assertEqual(psql_explanation["source"]["source_run_id"], "20260630T120000Z")
        self.assertEqual(psql_explanation["content_policy"], "full feed bodies are not exposed")
        self.assertIsInstance(psql_explanation["evidence"], list)
        self.assertIsInstance(psql_explanation["references"], list)
        self.assertGreaterEqual(len(psql_explanation["evidence"]), 1)
        self.assertGreaterEqual(len(psql_explanation["references"]), 1)

        evidence_keys = [
            record["evidence_key"] for record in psql_explanation["evidence"]
        ]
        self.assertEqual(
            evidence_keys,
            [record["evidence_key"] for record in default_explanation["evidence"]],
        )
        self.assertEqual(
            evidence_keys,
            [record["evidence_key"] for record in psycopg_explanation["evidence"]],
        )
        evidence_record = psql_explanation["evidence"][0]
        self.assertIsInstance(evidence_record["path"], str)
        self.assertIsInstance(evidence_record["raw_source_id"], str)
        self.assertIsInstance(evidence_record["extractor"], str)
        self.assertIsInstance(evidence_record["extractor_version"], str)
        self.assertIn("start_line", evidence_record)
        self.assertIn("end_line", evidence_record)

        reference_targets = [
            record["target_key"] for record in psql_explanation["references"]
        ]
        self.assertEqual(reference_targets, sorted(reference_targets))
        reference_record = psql_explanation["references"][0]
        self.assertTrue(reference_record["target_key"].startswith("external.url:"))
        self.assertIsInstance(reference_record["metadata"], dict)
        reference_metadata = reference_record["metadata"]
        self.assertIn("not_fetched", reference_metadata)
        self.assertTrue(reference_metadata["not_fetched"])
        self.assertEqual(reference_metadata["target_kind"], "external.url")
        self.assertIn("raw_target_summary", reference_metadata)

        self.assertIsNone(psql_missing_item["item"])
        self.assertEqual(psql_missing_item["evidence"], [])
        self.assertEqual(psql_missing_item["references"], [])
        self.assertEqual(
            psql_missing_item["content_policy"],
            "full feed bodies are not exposed",
        )
        self.assertIsNone(psql_missing_source["item"])
        self.assertIsNone(psql_missing_source["source"])
        self.assertEqual(psql_missing_source["evidence"], [])
        self.assertEqual(
            psql_missing_source["content_policy"],
            "full feed bodies are not exposed",
        )

        serialized = json.dumps(
            {
                "explanation": psql_explanation,
                "unfiltered": psql_unfiltered,
                "missing_item": psql_missing_item,
                "missing_source": psql_missing_source,
                "mcp_explanation": psycopg_mcp_payload,
            },
            sort_keys=True,
        )
        self.assertNotIn(private_root, serialized)
        self.assertNotIn("fixture-secret", serialized)
        self.assertNotIn("fixture-feed-secret", serialized)
        self.assertNotIn("<rss", serialized.lower())
