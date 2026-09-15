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


class StorageSourceReferenceRecordsPsycopgParityIntegrationTests(unittest.TestCase):
    def test_psycopg39_source_reference_records_psycopg_driver_parity(self):
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

        from repomap_kg.server.mcp import repomap_source_references

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
                    psql_records = query_source_reference_records(
                        postgres.psql_args,
                        root_path=str(root_path),
                        source_id="example-rss-feed",
                        psql_command=postgres.psql_command,
                    )
                    source_run_id = psql_records[0].source_run_id
                    target_kind = psql_records[0].target_key.split(":", 1)[0]
                    psql_filtered_run = query_source_reference_records(
                        postgres.psql_args,
                        root_path=str(root_path),
                        source_id="example-rss-feed",
                        source_run_id=source_run_id,
                        psql_command=postgres.psql_command,
                    )
                    psql_filtered_target = query_source_reference_records(
                        postgres.psql_args,
                        root_path=str(root_path),
                        source_id="example-rss-feed",
                        target_kind=target_kind,
                        psql_command=postgres.psql_command,
                    )
                    psql_limit_one = query_source_reference_records(
                        postgres.psql_args,
                        root_path=str(root_path),
                        source_id="example-rss-feed",
                        limit=1,
                        psql_command=postgres.psql_command,
                    )
                    psql_missing_source = query_source_reference_records(
                        postgres.psql_args,
                        root_path=str(root_path),
                        source_id="missing-source",
                        psql_command=postgres.psql_command,
                    )
                    psql_mcp_payload = repomap_source_references(
                        **mcp_args,
                        source_id="example-rss-feed",
                        source_run_id=source_run_id,
                        target_kind=target_kind,
                        limit=1,
                    )

                    _select_pg_connector_for_postgres(None, postgres=postgres)
                    default_records = query_source_reference_records(
                        postgres.psql_args,
                        root_path=str(root_path),
                        source_id="example-rss-feed",
                        psql_command=psycopg_only_psql_command,
                    )
                    default_filtered_run = query_source_reference_records(
                        postgres.psql_args,
                        root_path=str(root_path),
                        source_id="example-rss-feed",
                        source_run_id=source_run_id,
                        psql_command=psycopg_only_psql_command,
                    )
                    default_filtered_target = query_source_reference_records(
                        postgres.psql_args,
                        root_path=str(root_path),
                        source_id="example-rss-feed",
                        target_kind=target_kind,
                        psql_command=psycopg_only_psql_command,
                    )
                    default_limit_one = query_source_reference_records(
                        postgres.psql_args,
                        root_path=str(root_path),
                        source_id="example-rss-feed",
                        limit=1,
                        psql_command=psycopg_only_psql_command,
                    )
                    default_missing_source = query_source_reference_records(
                        postgres.psql_args,
                        root_path=str(root_path),
                        source_id="missing-source",
                        psql_command=psycopg_only_psql_command,
                    )

                    _select_pg_connector_for_postgres("psycopg", postgres=postgres)
                    psycopg_records = query_source_reference_records(
                        postgres.psql_args,
                        root_path=str(root_path),
                        source_id="example-rss-feed",
                        psql_command=psycopg_only_psql_command,
                    )
                    psycopg_filtered_run = query_source_reference_records(
                        postgres.psql_args,
                        root_path=str(root_path),
                        source_id="example-rss-feed",
                        source_run_id=source_run_id,
                        psql_command=psycopg_only_psql_command,
                    )
                    psycopg_filtered_target = query_source_reference_records(
                        postgres.psql_args,
                        root_path=str(root_path),
                        source_id="example-rss-feed",
                        target_kind=target_kind,
                        psql_command=psycopg_only_psql_command,
                    )
                    psycopg_limit_one = query_source_reference_records(
                        postgres.psql_args,
                        root_path=str(root_path),
                        source_id="example-rss-feed",
                        limit=1,
                        psql_command=psycopg_only_psql_command,
                    )
                    psycopg_missing_source = query_source_reference_records(
                        postgres.psql_args,
                        root_path=str(root_path),
                        source_id="missing-source",
                        psql_command=psycopg_only_psql_command,
                    )
                    psycopg_mcp_payload = repomap_source_references(
                        **mcp_args,
                        source_id="example-rss-feed",
                        source_run_id=source_run_id,
                        target_kind=target_kind,
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
        psql_run_payload = [record.to_dict() for record in psql_filtered_run]
        psql_target_payload = [record.to_dict() for record in psql_filtered_target]
        psql_limit_payload = [record.to_dict() for record in psql_limit_one]
        self.assertEqual([record.to_dict() for record in default_records], psql_payload)
        self.assertEqual([record.to_dict() for record in psycopg_records], psql_payload)
        self.assertEqual(
            [record.to_dict() for record in default_filtered_run],
            psql_run_payload,
        )
        self.assertEqual(
            [record.to_dict() for record in psycopg_filtered_run],
            psql_run_payload,
        )
        self.assertEqual(
            [record.to_dict() for record in default_filtered_target],
            psql_target_payload,
        )
        self.assertEqual(
            [record.to_dict() for record in psycopg_filtered_target],
            psql_target_payload,
        )
        self.assertEqual(
            [record.to_dict() for record in default_limit_one],
            psql_limit_payload,
        )
        self.assertEqual(
            [record.to_dict() for record in psycopg_limit_one],
            psql_limit_payload,
        )
        self.assertEqual(default_missing_source, psql_missing_source)
        self.assertEqual(psycopg_missing_source, psql_missing_source)
        self.assertEqual(psql_mcp_payload, psql_limit_payload)
        self.assertEqual(psycopg_mcp_payload, psql_limit_payload)

        self.assertGreaterEqual(len(psql_payload), 1)
        self.assertEqual(psql_run_payload, psql_payload)
        self.assertEqual(psql_limit_payload, psql_payload[:1])
        self.assertEqual(psql_missing_source, ())
        self.assertTrue(
            all(
                record["target_key"].split(":", 1)[0] == target_kind
                for record in psql_target_payload
            )
        )
        self.assertGreaterEqual(len(psql_target_payload), 1)
        for previous, current in zip(psql_payload, psql_payload[1:]):
            self.assertLessEqual(previous["source_item_key"], current["source_item_key"])
            if previous["source_item_key"] == current["source_item_key"]:
                self.assertLessEqual(previous["target_key"], current["target_key"])

        record = psql_payload[0]
        self.assertTrue(record["source_item_key"].startswith("feed.item:"))
        self.assertEqual(record["relation"], "references")
        self.assertIn(":", record["target_key"])
        self.assertIsInstance(record["not_fetched"], bool)
        self.assertEqual(record["source_run_id"], "20260630T120000Z")
        self.assertIsInstance(record["artifact_id"], str)
        self.assertIsInstance(record["artifact_path"], str)

        serialized = json.dumps(
            {
                "references": psql_payload,
                "filtered_run": psql_run_payload,
                "filtered_target": psql_target_payload,
                "mcp_references": psycopg_mcp_payload,
                "missing": [record.to_dict() for record in psql_missing_source],
            },
            sort_keys=True,
        )
        self.assertNotIn(private_root, serialized)
        self.assertNotIn("fixture-secret", serialized)
        self.assertNotIn("fixture-feed-secret", serialized)
        self.assertNotIn("<rss", serialized.lower())
