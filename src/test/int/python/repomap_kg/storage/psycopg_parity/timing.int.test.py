import os
import json
import tempfile
import unittest
from pathlib import Path

from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)
from repomap_test_support.schema_history import pre_arch5d_rdbms_root

from repomap_test_support.storage_publication import load_file_observations
from repomap_kg.storage import (
    apply_migrations,
)
from repomap_kg.storage.readback_driver import (
    READBACK_DRIVER_ENV,
)

from repomap_test_support.storage_integration import (
    _PSYCOPG19_TIMING_FIXTURE_LABEL,
    _PSYCOPG19_TIMING_ITERATIONS,
    _PSYCOPG19_TIMING_RECORD_FIELDS,
    _psycopg5_summary_parity_observations,
    _psycopg19_collect_connector_timing_records,
    _restore_environment_variable,
)


class StoragePsycopgTimingParityIntegrationTests(unittest.TestCase):
    def test_psycopg19_adapted_family_timing_comparison_local_only(self):
        require_postgres_binaries()
        root_path = "/tmp/repomap-psycopg-parity"
        repository_name = "psycopg-parity-fixture"
        observations = _psycopg5_summary_parity_observations()
        previous_driver_present = READBACK_DRIVER_ENV in os.environ
        previous_driver = os.environ.get(READBACK_DRIVER_ENV)
        previous_pgpassword_present = "PGPASSWORD" in os.environ
        previous_pgpassword = os.environ.get("PGPASSWORD")
        private_values: list[str] = []

        try:
            with tempfile.TemporaryDirectory() as migration_tmpdir, temporary_postgres() as postgres:
                apply_migrations(
                    pre_arch5d_rdbms_root(Path(migration_tmpdir)),
                    postgres.psql_args,
                    psql_command=postgres.psql_command,
                )
                load_file_observations(
                    postgres.psql_args,
                    observations,
                    repository_name=repository_name,
                    root_path=root_path,
                    psql_command=postgres.psql_command,
                )
                records, payloads = _psycopg19_collect_connector_timing_records(
                    postgres.psql_args,
                    root_path=root_path,
                    psql_command=postgres.psql_command,
                    postgres=postgres,
                    iterations=_PSYCOPG19_TIMING_ITERATIONS,
                )
                private_values = [
                    root_path,
                    repository_name,
                    str(postgres.socket_dir),
                    str(postgres.port),
                    postgres.user,
                    "postgres",
                ]
        finally:
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

        self.assertEqual(READBACK_DRIVER_ENV in os.environ, previous_driver_present)
        self.assertEqual(os.environ.get(READBACK_DRIVER_ENV), previous_driver)
        self.assertEqual("PGPASSWORD" in os.environ, previous_pgpassword_present)
        self.assertEqual(os.environ.get("PGPASSWORD"), previous_pgpassword)

        self.assertEqual(
            {
                (connector, operation)
                for connector in ("psql", "psycopg")
                for operation in (
                    "canonical_storage_summary",
                    "canonical_node_records",
                    "canonical_edge_records",
                    "canonical_edge_explanation",
                )
            },
            {(record["connector"], record["operation"]) for record in records},
        )
        for operation in (
            "canonical_storage_summary",
            "canonical_node_records",
            "canonical_edge_records",
            "canonical_edge_explanation",
        ):
            self.assertEqual(
                payloads[("psql", operation)],
                payloads[("psycopg", operation)],
            )

        for record in records:
            self.assertEqual(set(record), _PSYCOPG19_TIMING_RECORD_FIELDS)
            self.assertIn(record["connector"], {"psql", "psycopg"})
            self.assertIn(
                record["operation"],
                {
                    "canonical_storage_summary",
                    "canonical_node_records",
                    "canonical_edge_records",
                    "canonical_edge_explanation",
                },
            )
            self.assertEqual(record["method"], "query_function")
            elapsed = record["elapsed_seconds"]
            assert isinstance(elapsed, (int, float))
            self.assertGreaterEqual(elapsed, 0.0)
            self.assertEqual(record["iteration"], 1)
            self.assertEqual(record["iterations"], _PSYCOPG19_TIMING_ITERATIONS)
            payload_bytes = record["payload_bytes"]
            assert isinstance(payload_bytes, int)
            self.assertGreater(payload_bytes, 0)
            self.assertEqual(record["fixture"], _PSYCOPG19_TIMING_FIXTURE_LABEL)
            for field in (
                "runs",
                "files",
                "raw_observations",
                "canonical_nodes",
                "canonical_edges",
                "record_count",
                "file_node_count",
                "edge_kind_count",
                "evidence_count",
            ):
                field_val = record[field]
                self.assertIsInstance(field_val, int)
                assert isinstance(field_val, int)
                self.assertGreaterEqual(field_val, 0)
            self.assertIsInstance(record["has_edge"], bool)

        canonical_records = [
            record
            for record in records
            if record["operation"] == "canonical_storage_summary"
        ]
        node_records = [
            record
            for record in records
            if record["operation"] == "canonical_node_records"
        ]
        edge_records = [
            record
            for record in records
            if record["operation"] == "canonical_edge_records"
        ]
        explanation_records = [
            record
            for record in records
            if record["operation"] == "canonical_edge_explanation"
        ]
        for record in canonical_records:
            self.assertEqual(record["runs"], 1)
            files = record["files"]
            assert isinstance(files, int)
            self.assertGreaterEqual(files, 2)
            self.assertEqual(record["raw_observations"], len(observations))
            canonical_nodes = record["canonical_nodes"]
            assert isinstance(canonical_nodes, int)
            self.assertGreater(canonical_nodes, 0)
            canonical_edges = record["canonical_edges"]
            assert isinstance(canonical_edges, int)
            self.assertGreater(canonical_edges, 0)
            self.assertEqual(record["record_count"], 0)
        for record in node_records:
            record_count = record["record_count"]
            assert isinstance(record_count, int)
            self.assertGreaterEqual(record_count, 2)
            file_node_count = record["file_node_count"]
            assert isinstance(file_node_count, int)
            self.assertGreaterEqual(file_node_count, 1)
            self.assertEqual(record["edge_kind_count"], 0)
            self.assertFalse(record["has_edge"])
            self.assertEqual(record["evidence_count"], 0)
        for record in edge_records:
            record_count = record["record_count"]
            assert isinstance(record_count, int)
            self.assertGreaterEqual(record_count, 1)
            self.assertEqual(record["file_node_count"], 0)
            edge_kind_count = record["edge_kind_count"]
            assert isinstance(edge_kind_count, int)
            self.assertGreaterEqual(edge_kind_count, 1)
            self.assertFalse(record["has_edge"])
            self.assertEqual(record["evidence_count"], 0)
        for record in explanation_records:
            self.assertEqual(record["record_count"], 0)
            self.assertEqual(record["file_node_count"], 0)
            self.assertEqual(record["edge_kind_count"], 0)
            self.assertTrue(record["has_edge"])
            evidence_count = record["evidence_count"]
            assert isinstance(evidence_count, int)
            self.assertGreaterEqual(evidence_count, 1)

        serialized_records = json.dumps(records, sort_keys=True)
        self.assertNotIn("threshold_seconds", serialized_records)
        self.assertNotIn('"driver"', serialized_records)
        self.assertNotIn("root_path", serialized_records)
        self.assertNotIn("repository", serialized_records)
        self.assertNotIn("SELECT", serialized_records.upper())
        for forbidden_value in private_values:
            self.assertNotIn(forbidden_value, serialized_records)
        for forbidden_arg in ("--host", "--port", "--username", "--dbname"):
            self.assertNotIn(forbidden_arg, serialized_records)
