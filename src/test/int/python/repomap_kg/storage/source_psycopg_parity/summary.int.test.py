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
    query_source_summary,
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


class StorageSourceSummaryPsycopgParityIntegrationTests(unittest.TestCase):
    def test_psycopg31_source_summary_psycopg_driver_parity(self):
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

        from repomap_kg.server.mcp import repomap_source_summary

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
                    psql_record = query_source_summary(
                        postgres.psql_args,
                        root_path=str(root_path),
                        source_id="example-rss-feed",
                        psql_command=postgres.psql_command,
                    )
                    psql_missing = query_source_summary(
                        postgres.psql_args,
                        root_path=str(root_path),
                        source_id="missing-source",
                        psql_command=postgres.psql_command,
                    )
                    psql_mcp_payload = repomap_source_summary(
                        **mcp_args,
                        source_id="example-rss-feed",
                    )

                    _select_pg_connector_for_postgres(None, postgres=postgres)
                    default_record = query_source_summary(
                        postgres.psql_args,
                        root_path=str(root_path),
                        source_id="example-rss-feed",
                        psql_command=psycopg_only_psql_command,
                    )
                    default_missing = query_source_summary(
                        postgres.psql_args,
                        root_path=str(root_path),
                        source_id="missing-source",
                        psql_command=psycopg_only_psql_command,
                    )

                    _select_pg_connector_for_postgres("psycopg", postgres=postgres)
                    psycopg_record = query_source_summary(
                        postgres.psql_args,
                        root_path=str(root_path),
                        source_id="example-rss-feed",
                        psql_command=psycopg_only_psql_command,
                    )
                    psycopg_missing = query_source_summary(
                        postgres.psql_args,
                        root_path=str(root_path),
                        source_id="missing-source",
                        psql_command=psycopg_only_psql_command,
                    )
                    psycopg_mcp_payload = repomap_source_summary(
                        **mcp_args,
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
        psql_payload = psql_record.to_dict()
        self.assertEqual(default_record.to_dict(), psql_payload)
        self.assertEqual(psycopg_record.to_dict(), psql_payload)
        self.assertEqual(default_missing.to_dict(), psql_missing.to_dict())
        self.assertEqual(psycopg_missing.to_dict(), psql_missing.to_dict())
        self.assertEqual(psql_missing.policy_status, "unknown")
        self.assertEqual(psql_missing.feed_items, 0)
        self.assertEqual(psql_mcp_payload, psql_payload)
        self.assertEqual(psycopg_mcp_payload, psql_payload)

        self.assertEqual(psql_payload["source_id"], "example-rss-feed")
        self.assertEqual(psql_payload["source_type"], "feed.rss")
        self.assertEqual(psql_payload["display_name"], "Example RSS Feed")
        self.assertEqual(psql_payload["policy_status"], "allowed_with_limits")
        self.assertEqual(
            psql_payload["configured_url_summary"],
            "https://example.invalid/rss.xml",
        )
        self.assertEqual(psql_payload["latest_source_run_id"], "20260630T120000Z")
        self.assertEqual(psql_payload["feed_documents"], 1)
        self.assertEqual(psql_payload["feed_channels"], 1)
        self.assertGreaterEqual(psql_payload["feed_items"], 1)
        self.assertIsInstance(psql_payload["link_references"], int)
        self.assertGreaterEqual(psql_payload["link_references"], 0)
        self.assertEqual(psql_payload["parse_errors"], 0)
        self.assertEqual(
            psql_payload["known_limitations"],
            ("source metadata is inferred from RSS2 evidence",),
        )

        serialized = json.dumps(
            {
                "summary": psql_payload,
                "missing": psql_missing.to_dict(),
                "mcp_summary": psycopg_mcp_payload,
            },
            sort_keys=True,
        )
        self.assertNotIn(private_root, serialized)
        self.assertNotIn("fixture-secret", serialized)
        self.assertNotIn("fixture-feed-secret", serialized)
        self.assertNotIn("<rss", serialized.lower())
