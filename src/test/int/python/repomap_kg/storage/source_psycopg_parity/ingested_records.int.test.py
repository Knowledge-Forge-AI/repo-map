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
    query_ingested_source_records,
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


class StorageIngestedSourceRecordsPsycopgParityIntegrationTests(unittest.TestCase):
    def test_psycopg33_ingested_source_records_psycopg_driver_parity(self):
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

        from repomap_kg.server.mcp import repomap_ingested_sources

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
                    psql_records = query_ingested_source_records(
                        postgres.psql_args,
                        root_path=str(root_path),
                        psql_command=postgres.psql_command,
                    )
                    psql_filtered = query_ingested_source_records(
                        postgres.psql_args,
                        root_path=str(root_path),
                        source_type="feed.rss",
                        policy_status="allowed_with_limits",
                        psql_command=postgres.psql_command,
                    )
                    psql_limit_one = query_ingested_source_records(
                        postgres.psql_args,
                        root_path=str(root_path),
                        limit=1,
                        psql_command=postgres.psql_command,
                    )
                    psql_missing_type = query_ingested_source_records(
                        postgres.psql_args,
                        root_path=str(root_path),
                        source_type="feed.atom",
                        psql_command=postgres.psql_command,
                    )
                    psql_missing_policy = query_ingested_source_records(
                        postgres.psql_args,
                        root_path=str(root_path),
                        policy_status="blocked",
                        psql_command=postgres.psql_command,
                    )
                    psql_mcp_payload = repomap_ingested_sources(
                        **mcp_args,
                        source_type="feed.rss",
                        policy_status="allowed_with_limits",
                        limit=1,
                    )

                    _select_pg_connector_for_postgres(None, postgres=postgres)
                    default_records = query_ingested_source_records(
                        postgres.psql_args,
                        root_path=str(root_path),
                        psql_command=psycopg_only_psql_command,
                    )
                    default_filtered = query_ingested_source_records(
                        postgres.psql_args,
                        root_path=str(root_path),
                        source_type="feed.rss",
                        policy_status="allowed_with_limits",
                        psql_command=psycopg_only_psql_command,
                    )
                    default_limit_one = query_ingested_source_records(
                        postgres.psql_args,
                        root_path=str(root_path),
                        limit=1,
                        psql_command=psycopg_only_psql_command,
                    )
                    default_missing_type = query_ingested_source_records(
                        postgres.psql_args,
                        root_path=str(root_path),
                        source_type="feed.atom",
                        psql_command=psycopg_only_psql_command,
                    )
                    default_missing_policy = query_ingested_source_records(
                        postgres.psql_args,
                        root_path=str(root_path),
                        policy_status="blocked",
                        psql_command=psycopg_only_psql_command,
                    )

                    _select_pg_connector_for_postgres("psycopg", postgres=postgres)
                    psycopg_records = query_ingested_source_records(
                        postgres.psql_args,
                        root_path=str(root_path),
                        psql_command=psycopg_only_psql_command,
                    )
                    psycopg_filtered = query_ingested_source_records(
                        postgres.psql_args,
                        root_path=str(root_path),
                        source_type="feed.rss",
                        policy_status="allowed_with_limits",
                        psql_command=psycopg_only_psql_command,
                    )
                    psycopg_limit_one = query_ingested_source_records(
                        postgres.psql_args,
                        root_path=str(root_path),
                        limit=1,
                        psql_command=psycopg_only_psql_command,
                    )
                    psycopg_missing_type = query_ingested_source_records(
                        postgres.psql_args,
                        root_path=str(root_path),
                        source_type="feed.atom",
                        psql_command=psycopg_only_psql_command,
                    )
                    psycopg_missing_policy = query_ingested_source_records(
                        postgres.psql_args,
                        root_path=str(root_path),
                        policy_status="blocked",
                        psql_command=psycopg_only_psql_command,
                    )
                    psycopg_mcp_payload = repomap_ingested_sources(
                        **mcp_args,
                        source_type="feed.rss",
                        policy_status="allowed_with_limits",
                        limit=1,
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
        psql_payload = [record.to_dict() for record in psql_records]
        psql_filtered_payload = [record.to_dict() for record in psql_filtered]
        psql_limit_payload = [record.to_dict() for record in psql_limit_one]
        self.assertEqual([record.to_dict() for record in default_records], psql_payload)
        self.assertEqual([record.to_dict() for record in psycopg_records], psql_payload)
        self.assertEqual(
            [record.to_dict() for record in default_filtered],
            psql_filtered_payload,
        )
        self.assertEqual(
            [record.to_dict() for record in psycopg_filtered],
            psql_filtered_payload,
        )
        self.assertEqual(
            [record.to_dict() for record in default_limit_one],
            psql_limit_payload,
        )
        self.assertEqual(
            [record.to_dict() for record in psycopg_limit_one],
            psql_limit_payload,
        )
        self.assertEqual(default_missing_type, psql_missing_type)
        self.assertEqual(psycopg_missing_type, psql_missing_type)
        self.assertEqual(default_missing_policy, psql_missing_policy)
        self.assertEqual(psycopg_missing_policy, psql_missing_policy)
        self.assertEqual(psql_mcp_payload, psql_limit_payload)
        self.assertEqual(psycopg_mcp_payload, psql_limit_payload)

        self.assertEqual([record["source_id"] for record in psql_payload], ["example-rss-feed"])
        self.assertEqual(
            [record["source_id"] for record in psql_payload],
            sorted(record["source_id"] for record in psql_payload),
        )
        self.assertEqual(psql_filtered_payload, psql_payload)
        self.assertEqual(psql_limit_payload, psql_payload[:1])
        self.assertEqual(psql_missing_type, ())
        self.assertEqual(psql_missing_policy, ())

        record = psql_payload[0]
        self.assertEqual(record["source_type"], "feed.rss")
        self.assertEqual(record["display_name"], "Example RSS Feed")
        self.assertEqual(record["policy_status"], "allowed_with_limits")
        self.assertEqual(record["latest_source_run_id"], "20260630T120000Z")
        self.assertIsInstance(record["latest_artifact_id"], str)
        self.assertIsInstance(record["latest_artifact_path"], str)
        self.assertIsInstance(record["latest_acquired_at"], str)
        self.assertGreaterEqual(record["feed_observation_count"], 1)
        self.assertGreaterEqual(record["canonical_feed_item_count"], 1)

        serialized = json.dumps(
            {
                "sources": psql_payload,
                "filtered": psql_filtered_payload,
                "mcp_sources": psycopg_mcp_payload,
            },
            sort_keys=True,
        )
        self.assertNotIn(private_root, serialized)
        self.assertNotIn("fixture-secret", serialized)
        self.assertNotIn("fixture-feed-secret", serialized)
        self.assertNotIn("<rss", serialized.lower())
