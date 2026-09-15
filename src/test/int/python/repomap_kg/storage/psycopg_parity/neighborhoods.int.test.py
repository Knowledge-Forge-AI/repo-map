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
    query_canonical_neighborhood,
)
from repomap_kg.storage.readback_driver import (
    PG_CONNECTOR_ENV,
    READBACK_DRIVER_ENV,
)

from repomap_test_support.storage_integration import (
    _psycopg5_summary_parity_observations,
    _restore_environment_variable,
    _select_pg_connector_for_postgres,
)


class StoragePsycopgNeighborhoodParityIntegrationTests(unittest.TestCase):
    def test_psycopg28_canonical_neighborhood_psycopg_driver_parity(self):
        require_postgres_binaries()
        root_path = "/tmp/repomap-psycopg-parity"
        repository_name = "psycopg-parity-fixture"
        observations = _psycopg5_summary_parity_observations()
        center_key = "file:src/app.py"
        psycopg_only_psql_command = "/bin/psql-not-used-by-psycopg"
        previous_pg_connector_present = PG_CONNECTOR_ENV in os.environ
        previous_pg_connector = os.environ.get(PG_CONNECTOR_ENV)
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

                _select_pg_connector_for_postgres("psql", postgres=postgres)
                psql_record = query_canonical_neighborhood(
                    postgres.psql_args,
                    root_path=root_path,
                    node=center_key,
                    direction="both",
                    depth=1,
                    graph_key_version=1,
                    psql_command=postgres.psql_command,
                )
                psql_out_record = query_canonical_neighborhood(
                    postgres.psql_args,
                    root_path=root_path,
                    node=center_key,
                    direction="out",
                    depth=1,
                    graph_key_version=1,
                    psql_command=postgres.psql_command,
                )
                psql_missing = query_canonical_neighborhood(
                    postgres.psql_args,
                    root_path=root_path,
                    node="tool:missing",
                    direction="both",
                    depth=1,
                    graph_key_version=1,
                    psql_command=postgres.psql_command,
                )
                psql_cli_exit, psql_cli_stdout, psql_cli_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "neighborhood",
                        *common_cli_args,
                        "--node",
                        center_key,
                        "--direction",
                        "both",
                        "--json",
                    )
                )

                _select_pg_connector_for_postgres(None, postgres=postgres)
                default_record = query_canonical_neighborhood(
                    postgres.psql_args,
                    root_path=root_path,
                    node=center_key,
                    direction="both",
                    depth=1,
                    graph_key_version=1,
                    psql_command=psycopg_only_psql_command,
                )
                default_out_record = query_canonical_neighborhood(
                    postgres.psql_args,
                    root_path=root_path,
                    node=center_key,
                    direction="out",
                    depth=1,
                    graph_key_version=1,
                    psql_command=psycopg_only_psql_command,
                )
                default_missing = query_canonical_neighborhood(
                    postgres.psql_args,
                    root_path=root_path,
                    node="tool:missing",
                    direction="both",
                    depth=1,
                    graph_key_version=1,
                    psql_command=psycopg_only_psql_command,
                )
                default_cli_exit, default_cli_stdout, default_cli_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "neighborhood",
                        *common_cli_args,
                        "--node",
                        center_key,
                        "--direction",
                        "both",
                        "--psql-command",
                        psycopg_only_psql_command,
                        "--json",
                    )
                )

                _select_pg_connector_for_postgres("psycopg", postgres=postgres)
                psycopg_record = query_canonical_neighborhood(
                    postgres.psql_args,
                    root_path=root_path,
                    node=center_key,
                    direction="both",
                    depth=1,
                    graph_key_version=1,
                    psql_command=psycopg_only_psql_command,
                )
                psycopg_out_record = query_canonical_neighborhood(
                    postgres.psql_args,
                    root_path=root_path,
                    node=center_key,
                    direction="out",
                    depth=1,
                    graph_key_version=1,
                    psql_command=psycopg_only_psql_command,
                )
                psycopg_missing = query_canonical_neighborhood(
                    postgres.psql_args,
                    root_path=root_path,
                    node="tool:missing",
                    direction="both",
                    depth=1,
                    graph_key_version=1,
                    psql_command=psycopg_only_psql_command,
                )
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

        psql_payload = psql_record.to_dict()
        self.assertEqual(default_record.to_dict(), psql_payload)
        self.assertEqual(psycopg_record.to_dict(), psql_payload)
        self.assertEqual(default_out_record.to_dict(), psql_out_record.to_dict())
        self.assertEqual(psycopg_out_record.to_dict(), psql_out_record.to_dict())
        self.assertEqual(default_missing.to_dict(), psql_missing.to_dict())
        self.assertEqual(psycopg_missing.to_dict(), psql_missing.to_dict())
        self.assertEqual(psql_missing.to_dict(), {"center": None, "nodes": [], "edges": []})

        self.assertIsNotNone(psql_record.center)
        if psql_record.center is None:
            raise AssertionError("expected selected neighborhood to include center")
        self.assertEqual(psql_record.center.canonical_key, center_key)
        self.assertEqual(psql_record.center.graph_key_version, 1)
        self.assertIsInstance(psql_payload["center"], dict)
        self.assertIsInstance(psql_payload["nodes"], list)
        self.assertIsInstance(psql_payload["edges"], list)
        self.assertGreaterEqual(len(psql_payload["nodes"]), 1)
        self.assertGreaterEqual(len(psql_payload["edges"]), 1)

        node_keys = [record["canonical_key"] for record in psql_payload["nodes"]]
        self.assertEqual(node_keys, sorted(node_keys))
        self.assertNotIn(center_key, node_keys)
        self.assertTrue(
            all(record["graph_key_version"] == 1 for record in psql_payload["nodes"])
        )

        edge_ordering_keys = [
            (
                record["source_key"],
                record["edge_kind"],
                record["target_key"],
                record["identity_metadata_hash"],
            )
            for record in psql_payload["edges"]
        ]
        self.assertEqual(edge_ordering_keys, sorted(edge_ordering_keys))
        self.assertTrue(
            any(
                record["source_key"] == center_key or record["target_key"] == center_key
                for record in psql_payload["edges"]
            )
        )
        self.assertTrue(
            all(record["graph_key_version"] == 1 for record in psql_payload["edges"])
        )

        self.assertEqual(psql_cli_exit, 0, psql_cli_stderr)
        self.assertEqual(default_cli_exit, 0, default_cli_stderr)
        self.assertEqual(json.loads(default_cli_stdout), json.loads(psql_cli_stdout))
        self.assertEqual(json.loads(psql_cli_stdout)["result"], psql_payload)
