import json
import os
import unittest
from unittest.mock import patch

from repomap_kg.storage import (
    apply_migrations,
    default_rdbms_root,
    query_canonical_storage_summary,
)
from repomap_test_support.cli_in_process import run_repo_map_in_process
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)
from repomap_test_support.storage_integration import (
    _psycopg5_summary_parity_observations,
    _select_readback_driver_for_postgres,
)
from repomap_test_support.storage_publication import load_file_observations


class StoragePsycopgSummaryParityIntegrationTests(unittest.TestCase):
    def test_canonical_summary_matches_psql_and_psycopg(self):
        require_postgres_binaries()
        root_path = "/tmp/repomap-psycopg-summary-parity"
        observations = _psycopg5_summary_parity_observations()

        with patch.dict(os.environ, {}, clear=False), temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            load_file_observations(
                postgres.psql_args,
                observations,
                repository_name="psycopg-summary-parity",
                root_path=root_path,
                psql_command=postgres.psql_command,
            )

            _select_readback_driver_for_postgres("psql", postgres=postgres)
            expected = query_canonical_storage_summary(
                postgres.psql_args,
                root_path=root_path,
                psql_command=postgres.psql_command,
            ).to_dict()

            _select_readback_driver_for_postgres("psycopg", postgres=postgres)
            actual = query_canonical_storage_summary(
                postgres.psql_args,
                root_path=root_path,
                psql_command=postgres.psql_command,
            ).to_dict()

        self.assertEqual(actual, expected)
        self.assertEqual(actual["raw_observations"], len(observations))
        self.assertGreater(actual["canonical_nodes"], 0)
        self.assertGreater(actual["canonical_edges"], 0)
        self.assertGreater(actual["canonical_evidence"], 0)
        self.assertNotIn("legacy_nodes", actual)
        self.assertNotIn("nodes", actual)

    def test_canonical_summary_cli_uses_the_selected_psycopg_driver(self):
        require_postgres_binaries()
        root_path = "/tmp/repomap-psycopg-summary-cli"
        observations = _psycopg5_summary_parity_observations()

        with patch.dict(os.environ, {}, clear=False), temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            load_file_observations(
                postgres.psql_args,
                observations,
                repository_name="psycopg-summary-cli",
                root_path=root_path,
                psql_command=postgres.psql_command,
            )
            _select_readback_driver_for_postgres("psycopg", postgres=postgres)
            exit_code, stdout, stderr = run_repo_map_in_process(
                "storage",
                "summary",
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
                "--json",
            )

        self.assertEqual(exit_code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["raw_observations"], len(observations))
        self.assertIn("latest_run_id", payload)
        self.assertNotIn("legacy_nodes", payload)
