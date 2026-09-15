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
    query_canonical_node_records,
)
from repomap_kg.storage.readback_driver import (
    READBACK_DRIVER_ENV,
)

from repomap_test_support.storage_integration import (
    _psycopg5_summary_parity_observations,
    _restore_environment_variable,
    _select_readback_driver_for_postgres,
)


class StoragePsycopgCanonicalNodeParityIntegrationTests(unittest.TestCase):
    def test_psycopg11_canonical_node_records_psycopg_driver_parity(self):
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
                psql_records = query_canonical_node_records(
                    postgres.psql_args,
                    root_path=root_path,
                    graph_key_version=1,
                    psql_command=postgres.psql_command,
                )
                psql_file_records = query_canonical_node_records(
                    postgres.psql_args,
                    root_path=root_path,
                    kind="file",
                    graph_key_version=1,
                    psql_command=postgres.psql_command,
                )
                psql_key_records = query_canonical_node_records(
                    postgres.psql_args,
                    root_path=root_path,
                    canonical_key="file:src/app.py",
                    graph_key_version=1,
                    psql_command=postgres.psql_command,
                )
                psql_prefix_records = query_canonical_node_records(
                    postgres.psql_args,
                    root_path=root_path,
                    path_prefix="src/",
                    graph_key_version=1,
                    psql_command=postgres.psql_command,
                )
                psql_cli_exit, psql_cli_stdout, psql_cli_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "nodes",
                        *common_cli_args,
                        "--path-prefix",
                        "src/",
                        "--json",
                    )
                )

                _select_readback_driver_for_postgres("psycopg", postgres=postgres)
                psycopg_records = query_canonical_node_records(
                    postgres.psql_args,
                    root_path=root_path,
                    graph_key_version=1,
                    psql_command=postgres.psql_command,
                )
                psycopg_file_records = query_canonical_node_records(
                    postgres.psql_args,
                    root_path=root_path,
                    kind="file",
                    graph_key_version=1,
                    psql_command=postgres.psql_command,
                )
                psycopg_key_records = query_canonical_node_records(
                    postgres.psql_args,
                    root_path=root_path,
                    canonical_key="file:src/app.py",
                    graph_key_version=1,
                    psql_command=postgres.psql_command,
                )
                psycopg_prefix_records = query_canonical_node_records(
                    postgres.psql_args,
                    root_path=root_path,
                    path_prefix="src/",
                    graph_key_version=1,
                    psql_command=postgres.psql_command,
                )
                psycopg_cli_exit, psycopg_cli_stdout, psycopg_cli_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "nodes",
                        *common_cli_args,
                        "--path-prefix",
                        "src/",
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
        self.assertGreaterEqual(len(psql_payload), 2)

        canonical_keys = [record.canonical_key for record in psql_records]
        self.assertEqual(canonical_keys, sorted(canonical_keys))
        self.assertIn("file:src/app.py", canonical_keys)

        self.assertEqual(
            [record.to_dict() for record in psycopg_file_records],
            [record.to_dict() for record in psql_file_records],
        )
        self.assertTrue(
            all(
                record.canonical_key.startswith("file:")
                for record in psql_file_records
            )
        )
        self.assertEqual(
            [record.to_dict() for record in psycopg_key_records],
            [record.to_dict() for record in psql_key_records],
        )
        self.assertEqual(
            [record.canonical_key for record in psql_key_records],
            ["file:src/app.py"],
        )
        self.assertEqual(
            [record.to_dict() for record in psycopg_prefix_records],
            [record.to_dict() for record in psql_prefix_records],
        )
        self.assertEqual(
            [record.canonical_key for record in psql_prefix_records],
            ["file:src/app.py"],
        )

        self.assertEqual(psql_cli_exit, 0, psql_cli_stderr)
        self.assertEqual(psycopg_cli_exit, 0, psycopg_cli_stderr)
        self.assertEqual(json.loads(psycopg_cli_stdout), json.loads(psql_cli_stdout))
        self.assertEqual(
            [
                record["canonical_key"]
                for record in json.loads(psql_cli_stdout)["items"]
            ],
            ["file:src/app.py"],
        )
