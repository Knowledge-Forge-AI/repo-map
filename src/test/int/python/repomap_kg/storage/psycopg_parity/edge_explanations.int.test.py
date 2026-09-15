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
    query_canonical_edge_explanation,
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


class StoragePsycopgEdgeExplanationParityIntegrationTests(unittest.TestCase):
    def test_psycopg15_canonical_edge_explanation_psycopg_driver_parity(self):
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
                psql_edges = query_canonical_edge_records(
                    postgres.psql_args,
                    root_path=root_path,
                    graph_key_version=1,
                    psql_command=postgres.psql_command,
                )
                self.assertGreaterEqual(len(psql_edges), 1)
                selected_edge = psql_edges[0]
                identity_metadata_json = json.dumps(
                    selected_edge.identity_metadata,
                    sort_keys=True,
                )
                psql_explanation = query_canonical_edge_explanation(
                    postgres.psql_args,
                    root_path=root_path,
                    source_key=selected_edge.source_key,
                    kind=selected_edge.edge_kind,
                    target_key=selected_edge.target_key,
                    identity_metadata_hash=selected_edge.identity_metadata_hash,
                    graph_key_version=selected_edge.graph_key_version,
                    psql_command=postgres.psql_command,
                )
                psql_missing = query_canonical_edge_explanation(
                    postgres.psql_args,
                    root_path=root_path,
                    source_key=selected_edge.source_key,
                    kind=selected_edge.edge_kind,
                    target_key="tool:missing",
                    identity_metadata_hash=selected_edge.identity_metadata_hash,
                    graph_key_version=selected_edge.graph_key_version,
                    psql_command=postgres.psql_command,
                )
                psql_cli_exit, psql_cli_stdout, psql_cli_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "explain-canonical-edge",
                        *common_cli_args,
                        "--source-key",
                        selected_edge.source_key,
                        "--kind",
                        selected_edge.edge_kind,
                        "--target-key",
                        selected_edge.target_key,
                        "--identity-metadata-json",
                        identity_metadata_json,
                        "--json",
                    )
                )

                _select_readback_driver_for_postgres("psycopg", postgres=postgres)
                psycopg_explanation = query_canonical_edge_explanation(
                    postgres.psql_args,
                    root_path=root_path,
                    source_key=selected_edge.source_key,
                    kind=selected_edge.edge_kind,
                    target_key=selected_edge.target_key,
                    identity_metadata_hash=selected_edge.identity_metadata_hash,
                    graph_key_version=selected_edge.graph_key_version,
                    psql_command=postgres.psql_command,
                )
                psycopg_missing = query_canonical_edge_explanation(
                    postgres.psql_args,
                    root_path=root_path,
                    source_key=selected_edge.source_key,
                    kind=selected_edge.edge_kind,
                    target_key="tool:missing",
                    identity_metadata_hash=selected_edge.identity_metadata_hash,
                    graph_key_version=selected_edge.graph_key_version,
                    psql_command=postgres.psql_command,
                )
                psycopg_cli_exit, psycopg_cli_stdout, psycopg_cli_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "explain-canonical-edge",
                        *common_cli_args,
                        "--source-key",
                        selected_edge.source_key,
                        "--kind",
                        selected_edge.edge_kind,
                        "--target-key",
                        selected_edge.target_key,
                        "--identity-metadata-json",
                        identity_metadata_json,
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

        self.assertEqual(psycopg_explanation.to_dict(), psql_explanation.to_dict())
        self.assertEqual(psycopg_missing.to_dict(), psql_missing.to_dict())
        self.assertEqual(psql_missing.to_dict(), {"edge": None, "evidence": []})

        self.assertIsNotNone(psql_explanation.edge)
        if psql_explanation.edge is None:
            raise AssertionError("expected selected edge explanation to include edge")
        self.assertEqual(psql_explanation.edge.source_key, selected_edge.source_key)
        self.assertEqual(psql_explanation.edge.edge_kind, selected_edge.edge_kind)
        self.assertEqual(psql_explanation.edge.target_key, selected_edge.target_key)
        self.assertEqual(
            psql_explanation.edge.identity_metadata_hash,
            selected_edge.identity_metadata_hash,
        )
        self.assertEqual(
            psql_explanation.edge.graph_key_version,
            selected_edge.graph_key_version,
        )
        self.assertGreaterEqual(len(psql_explanation.evidence), 1)

        evidence_ordering_keys = [
            (
                record.raw_observation["run_id"],
                record.raw_observation["ordinal"],
                record.evidence_key,
                record.link_kind,
            )
            for record in psql_explanation.evidence
        ]
        self.assertEqual(evidence_ordering_keys, sorted(evidence_ordering_keys))
        first_evidence = psql_explanation.evidence[0].to_dict()
        self.assertIsInstance(first_evidence["raw_observation"], dict)
        self.assertIn("run_id", first_evidence["raw_observation"])
        self.assertIn("ordinal", first_evidence["raw_observation"])
        self.assertIn("payload_hash", first_evidence["raw_observation"])
        self.assertEqual(len(first_evidence["raw_observation"]["payload_hash"]), 64)
        self.assertIsInstance(first_evidence["metadata"], dict)

        self.assertEqual(psql_cli_exit, 0, psql_cli_stderr)
        self.assertEqual(psycopg_cli_exit, 0, psycopg_cli_stderr)
        self.assertEqual(json.loads(psycopg_cli_stdout), json.loads(psql_cli_stdout))
        self.assertEqual(
            json.loads(psql_cli_stdout)["result"],
            psql_explanation.to_dict(),
        )
