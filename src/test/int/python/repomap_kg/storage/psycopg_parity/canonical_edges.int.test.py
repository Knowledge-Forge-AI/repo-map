import os
import json
import unittest

from repomap_test_support.cli_in_process import run_repo_map_in_process
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)

from repomap_test_support.storage_publication import load_file_observations
from repomap_kg.storage import (
    apply_migrations,
    default_rdbms_root,
    query_canonical_edge_records,
)
from repomap_kg.storage.readback_driver import (
    READBACK_DRIVER_ENV,
)

from repomap_test_support.storage_integration import (
    _psycopg5_summary_parity_observations,
    _restore_environment_variable,
    _select_readback_driver_for_postgres,
)


class StoragePsycopgCanonicalEdgeParityIntegrationTests(unittest.TestCase):
    def test_psycopg13_canonical_edge_records_psycopg_driver_parity(self):
        require_postgres_binaries()
        root_path = "/tmp/repomap-psycopg-parity"
        repository_name = "psycopg-parity-fixture"
        observations = _psycopg5_summary_parity_observations()
        previous_driver_present = READBACK_DRIVER_ENV in os.environ
        previous_driver = os.environ.get(READBACK_DRIVER_ENV)
        previous_pgpassword_present = "PGPASSWORD" in os.environ
        previous_pgpassword = os.environ.get("PGPASSWORD")

        try:
            with temporary_postgres() as postgres:
                apply_migrations(
                    default_rdbms_root(),
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
                common_cli_args = [
                    "--root-path",
                    root_path,
                    "--pg-host",
                    str(postgres.socket_dir),
                    "--pg-port",
                    str(postgres.port),
                    "--pg-user",
                    postgres.user,
                    "--pg-database",
                    postgres.database,
                    "--psql-command",
                    postgres.psql_command,
                ]

                _select_readback_driver_for_postgres("psql", postgres=postgres)
                psql_records = query_canonical_edge_records(
                    postgres.psql_args,
                    root_path=root_path,
                    graph_key_version=1,
                    psql_command=postgres.psql_command,
                )
                self.assertGreaterEqual(len(psql_records), 1)
                selected_edge = psql_records[0]
                psql_kind_records = query_canonical_edge_records(
                    postgres.psql_args,
                    root_path=root_path,
                    kind=selected_edge.edge_kind,
                    graph_key_version=1,
                    psql_command=postgres.psql_command,
                )
                psql_source_records = query_canonical_edge_records(
                    postgres.psql_args,
                    root_path=root_path,
                    source_key=selected_edge.source_key,
                    graph_key_version=1,
                    psql_command=postgres.psql_command,
                )
                psql_target_records = query_canonical_edge_records(
                    postgres.psql_args,
                    root_path=root_path,
                    target_key=selected_edge.target_key,
                    graph_key_version=1,
                    psql_command=postgres.psql_command,
                )
                psql_cli_exit, psql_cli_stdout, psql_cli_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "edges",
                        *common_cli_args,
                        "--kind",
                        selected_edge.edge_kind,
                        "--source-key",
                        selected_edge.source_key,
                        "--json",
                    )
                )

                _select_readback_driver_for_postgres("psycopg", postgres=postgres)
                psycopg_records = query_canonical_edge_records(
                    postgres.psql_args,
                    root_path=root_path,
                    graph_key_version=1,
                    psql_command=postgres.psql_command,
                )
                psycopg_kind_records = query_canonical_edge_records(
                    postgres.psql_args,
                    root_path=root_path,
                    kind=selected_edge.edge_kind,
                    graph_key_version=1,
                    psql_command=postgres.psql_command,
                )
                psycopg_source_records = query_canonical_edge_records(
                    postgres.psql_args,
                    root_path=root_path,
                    source_key=selected_edge.source_key,
                    graph_key_version=1,
                    psql_command=postgres.psql_command,
                )
                psycopg_target_records = query_canonical_edge_records(
                    postgres.psql_args,
                    root_path=root_path,
                    target_key=selected_edge.target_key,
                    graph_key_version=1,
                    psql_command=postgres.psql_command,
                )
                psycopg_cli_exit, psycopg_cli_stdout, psycopg_cli_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "edges",
                        *common_cli_args,
                        "--kind",
                        selected_edge.edge_kind,
                        "--source-key",
                        selected_edge.source_key,
                        "--json",
                    )
                )
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

        psql_payload = [record.to_dict() for record in psql_records]
        psycopg_payload = [record.to_dict() for record in psycopg_records]
        self.assertEqual(psycopg_payload, psql_payload)

        ordering_keys = [
            (
                record.source_key,
                record.edge_kind,
                record.target_key,
                record.identity_metadata_hash,
            )
            for record in psql_records
        ]
        self.assertEqual(ordering_keys, sorted(ordering_keys))

        self.assertEqual(
            [record.to_dict() for record in psycopg_kind_records],
            [record.to_dict() for record in psql_kind_records],
        )
        self.assertTrue(
            all(
                record.edge_kind == selected_edge.edge_kind
                for record in psql_kind_records
            )
        )
        self.assertEqual(
            [record.to_dict() for record in psycopg_source_records],
            [record.to_dict() for record in psql_source_records],
        )
        self.assertTrue(
            all(
                record.source_key == selected_edge.source_key
                for record in psql_source_records
            )
        )
        self.assertEqual(
            [record.to_dict() for record in psycopg_target_records],
            [record.to_dict() for record in psql_target_records],
        )
        self.assertTrue(
            all(
                record.target_key == selected_edge.target_key
                for record in psql_target_records
            )
        )

        first_payload = psql_payload[0]
        self.assertEqual(first_payload["source_key"], selected_edge.source_key)
        self.assertEqual(first_payload["edge_kind"], selected_edge.edge_kind)
        self.assertEqual(first_payload["target_key"], selected_edge.target_key)
        self.assertEqual(first_payload["graph_key_version"], 1)
        self.assertIsInstance(first_payload["identity_metadata"], dict)
        self.assertEqual(len(first_payload["identity_metadata_hash"]), 64)
        self.assertIsInstance(first_payload["metadata"], dict)
        self.assertIsInstance(first_payload["confidence"], str)
        self.assertIsInstance(first_payload["conflict"], bool)
        self.assertIsInstance(first_payload["last_seen_run_id"], int)

        self.assertEqual(psql_cli_exit, 0, psql_cli_stderr)
        self.assertEqual(psycopg_cli_exit, 0, psycopg_cli_stderr)
        self.assertEqual(json.loads(psycopg_cli_stdout), json.loads(psql_cli_stdout))
        self.assertEqual(
            [
                record["source_key"]
                for record in json.loads(psql_cli_stdout)["items"]
            ],
            [record.source_key for record in psql_source_records],
        )
