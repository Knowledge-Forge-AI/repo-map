import json
import tempfile
import unittest

from repomap_test_support.cli_in_process import run_repo_map_in_process
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)

from repomap_kg.storage import (
    apply_migrations,
    default_rdbms_root,
    query_canonical_edge_records,
    query_canonical_node_records,
    query_terraform_summary,
)

from repomap_test_support.storage_integration import (
    discovery_fixture,
    terraform_hcl_fixture,
)


def _storage_args(fixture_root, postgres):
    return (
        "--root-path", str(fixture_root),
        "--pg-host", str(postgres.socket_dir),
        "--pg-port", str(postgres.port),
        "--pg-user", postgres.user,
        "--pg-database", postgres.database,
        "--psql-command", postgres.psql_command,
    )


class StorageTerraformProfileDomainSummaryIntegrationTests(unittest.TestCase):
    def test_storage_loads_tfjson_profile_observations_as_raw_evidence(self):
        require_postgres_binaries()
        fixture_root = discovery_fixture("tfjson1_ecosystem_config")

        discover_exit_code, discover_stdout, discover_stderr = run_repo_map_in_process(
            "discover", str(fixture_root), "--jsonl",
        )
        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as jsonl_file:
            jsonl_file.write(discover_stdout)
            jsonl_file.flush()

            with temporary_postgres() as postgres:
                apply_migrations(
                    default_rdbms_root(),
                    postgres.psql_args,
                    psql_command=postgres.psql_command,
                )
                storage_args = _storage_args(fixture_root, postgres)
                load_exit_code, _load_stdout, load_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "load-files",
                        jsonl_file.name,
                        "--repository-name",
                        "tfjson-fixture",
                        *storage_args,
                        "--json",
                    )
                )
                raw_kinds_json = postgres.psql_scalar(
                    """
SELECT COALESCE(jsonb_agg(payload_json->>'kind' ORDER BY ordinal)::text, '[]')
FROM raw_observations;
"""
                )
                raw_payload = postgres.psql_scalar(
                    """
SELECT COALESCE(jsonb_agg(payload_json ORDER BY ordinal)::text, '[]')
FROM raw_observations;
"""
                )
                canonical_kinds = {
                    record.kind
                    for record in query_canonical_node_records(
                        postgres.psql_args,
                        root_path=str(fixture_root),
                        psql_command=postgres.psql_command,
                    )
                }
                canonical_edges = query_canonical_edge_records(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    psql_command=postgres.psql_command,
                )

        self.assertEqual(discover_exit_code, 0, discover_stderr)
        discovered = [
            json.loads(line)
            for line in discover_stdout.splitlines()
            if line.strip()
        ]
        discovered_kinds = {record["kind"] for record in discovered}
        self.assertTrue(
            {
                "ecosystem.config_profile",
                "npm.package",
                "npm.script",
                "npm.dependency",
                "typescript.config",
                "typescript.reference",
                "angular.project",
                "angular.target",
                "jest.config",
                "nest.config",
                "playwright.config",
                "terraform.file",
                "terraform.required_provider",
                "terraform.resource",
                "terraform.module",
                "terraform.variable",
                "terraform.output",
                "terraform.reference",
                "kubernetes.resource",
                "argocd.application",
                "liquibase.changelog",
                "liquibase.changeset",
                "docker.reference",
            }.issubset(discovered_kinds)
        )
        self.assertNotIn("fake-tfjson-package-secret", discover_stdout)
        self.assertNotIn("fake-tfjson-terraform-secret", discover_stdout)
        self.assertNotIn("fake-tfjson-tfvars-secret", discover_stdout)
        self.assertNotIn("fake-tfjson-k8s-secret", discover_stdout)

        self.assertEqual(load_exit_code, 0, load_stderr)
        raw_kinds = set(json.loads(raw_kinds_json))
        self.assertTrue(
            {"npm.package", "terraform.resource", "kubernetes.resource"}.issubset(
                raw_kinds
            )
        )
        self.assertNotIn("fake-tfjson-package-secret", raw_payload)
        self.assertNotIn("fake-tfjson-terraform-secret", raw_payload)
        self.assertNotIn("fake-tfjson-tfvars-secret", raw_payload)
        self.assertNotIn("fake-tfjson-k8s-secret", raw_payload)
        self.assertIn("config.document", canonical_kinds)
        self.assertIn("config.path", canonical_kinds)
        self.assertNotIn("terraform.resource", canonical_kinds)
        self.assertNotIn("npm.package", canonical_kinds)
        self.assertNotIn("kubernetes.resource", canonical_kinds)
        self.assertEqual(
            {edge.edge_kind for edge in canonical_edges} - {"defines", "references"},
            set(),
        )
    def test_storage_loads_tfhcl_profile_observations_as_raw_evidence(self):
        require_postgres_binaries()
        fixture_root = terraform_hcl_fixture("basic")

        discover_exit_code, discover_stdout, discover_stderr = (
            run_repo_map_in_process(
                "discover",
                str(fixture_root),
                "--jsonl",
            )
        )
        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as jsonl_file:
            jsonl_file.write(discover_stdout)
            jsonl_file.flush()

            with temporary_postgres() as postgres:
                apply_migrations(
                    default_rdbms_root(),
                    postgres.psql_args,
                    psql_command=postgres.psql_command,
                )
                storage_args = _storage_args(fixture_root, postgres)
                load_exit_code, _load_stdout, load_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "load-files",
                        jsonl_file.name,
                        "--repository-name",
                        "tfhcl-fixture",
                        *storage_args,
                        "--json",
                    )
                )
                raw_kinds_json = postgres.psql_scalar(
                    """
SELECT COALESCE(jsonb_agg(payload_json->>'kind' ORDER BY ordinal)::text, '[]')
FROM raw_observations;
"""
                )
                raw_payload = postgres.psql_scalar(
                    """
SELECT COALESCE(jsonb_agg(payload_json ORDER BY ordinal)::text, '[]')
FROM raw_observations;
"""
                )
                canonical_kinds = {
                    record.kind
                    for record in query_canonical_node_records(
                        postgres.psql_args,
                        root_path=str(fixture_root),
                        psql_command=postgres.psql_command,
                    )
                }
                canonical_edges = query_canonical_edge_records(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    psql_command=postgres.psql_command,
                )

        self.assertEqual(discover_exit_code, 0, discover_stderr)
        discovered = [
            json.loads(line)
            for line in discover_stdout.splitlines()
            if line.strip()
        ]
        discovered_kinds = {record["kind"] for record in discovered}
        self.assertTrue(
            {
                "terraform.file",
                "terraform.block",
                "terraform.required_version",
                "terraform.required_provider",
                "terraform.backend",
                "terraform.provider",
                "terraform.resource",
                "terraform.module",
                "terraform.variable",
                "terraform.output",
                "terraform.reference",
                "terraform.import",
                "terraform.redaction",
                "terraform.parse_error",
            }.issubset(discovered_kinds)
        )
        self.assertNotIn("fake-tfhcl-provider-secret", discover_stdout)
        self.assertNotIn("fake-tfhcl-module-secret", discover_stdout)
        self.assertNotIn("fake-tfhcl-prod-tfvars-secret", discover_stdout)
        self.assertNotIn("fake-tfhcl-tfvars-secret", discover_stdout)
        self.assertNotIn("fake-tfhcl-import-secret", discover_stdout)

        self.assertEqual(load_exit_code, 0, load_stderr)
        raw_kinds = set(json.loads(raw_kinds_json))
        self.assertTrue(
            {"terraform.block", "terraform.resource", "terraform.variable"}.issubset(
                raw_kinds
            )
        )
        self.assertNotIn("fake-tfhcl-provider-secret", raw_payload)
        self.assertNotIn("fake-tfhcl-module-secret", raw_payload)
        self.assertNotIn("fake-tfhcl-prod-tfvars-secret", raw_payload)
        self.assertNotIn("fake-tfhcl-tfvars-secret", raw_payload)
        self.assertNotIn("fake-tfhcl-import-secret", raw_payload)
        self.assertNotIn("terraform.resource", canonical_kinds)
        self.assertNotIn("terraform.module", canonical_kinds)
        self.assertNotIn("terraform.variable", canonical_kinds)
        self.assertEqual(
            {edge.edge_kind for edge in canonical_edges} - {"defines", "references"},
            set(),
        )
    def test_storage_terraform_summary_reads_hcl_evidence_without_reload(self):
        require_postgres_binaries()
        fixture_root = terraform_hcl_fixture("basic")

        discover_exit_code, discover_stdout, discover_stderr = (
            run_repo_map_in_process(
                "discover",
                str(fixture_root),
                "--jsonl",
            )
        )
        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as jsonl_file:
            jsonl_file.write(discover_stdout)
            jsonl_file.flush()

            with temporary_postgres() as postgres:
                apply_migrations(
                    default_rdbms_root(),
                    postgres.psql_args,
                    psql_command=postgres.psql_command,
                )
                storage_args = _storage_args(fixture_root, postgres)
                load_exit_code, _load_stdout, load_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "load-files",
                        jsonl_file.name,
                        "--repository-name",
                        "tfhcl2-fixture",
                        *storage_args,
                        "--json",
                    )
                )
                raw_count_before = postgres.psql_scalar(
                    "SELECT COUNT(*)::text FROM raw_observations;"
                )
                summary = query_terraform_summary(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    psql_command=postgres.psql_command,
                )
                summary_exit_code, summary_stdout, summary_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "terraform-summary",
                        *storage_args,
                        "--json",
                    )
                )
                table_exit_code, table_stdout, table_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "terraform-summary",
                        *storage_args,
                    )
                )
                raw_count_after = postgres.psql_scalar(
                    "SELECT COUNT(*)::text FROM raw_observations;"
                )
                canonical_nodes = query_canonical_node_records(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    psql_command=postgres.psql_command,
                )
                canonical_edges = query_canonical_edge_records(
                    postgres.psql_args,
                    root_path=str(fixture_root),
                    psql_command=postgres.psql_command,
                )

        self.assertEqual(discover_exit_code, 0, discover_stderr)
        self.assertEqual(load_exit_code, 0, load_stderr)
        self.assertEqual(summary_exit_code, 0, summary_stderr)
        self.assertEqual(table_exit_code, 0, table_stderr)
        self.assertEqual(raw_count_before, raw_count_after)
        payload = json.loads(summary_stdout)
        self.assertEqual(payload["repository_name"], "tfhcl2-fixture")
        self.assertEqual(payload["file_families"]["tf"], 2)
        self.assertEqual(payload["file_families"]["tfvars"], 1)
        self.assertEqual(payload["file_families"]["terraform.tfvars"], 1)
        self.assertEqual(payload["file_families"]["auto.tfvars"], 1)
        self.assertEqual(summary.file_families["tf"], 2)
        self.assertGreaterEqual(payload["terraform_observations"], 20)
        self.assertEqual(payload["terraform_files"], 5)
        self.assertGreaterEqual(payload["terraform"]["blocks"], 10)
        self.assertGreaterEqual(payload["terraform"]["providers"], 1)
        self.assertGreaterEqual(payload["terraform"]["required_providers"], 1)
        self.assertGreaterEqual(payload["terraform"]["required_versions"], 1)
        self.assertGreaterEqual(payload["terraform"]["backends"], 1)
        self.assertGreaterEqual(payload["terraform"]["resources"], 1)
        self.assertGreaterEqual(payload["terraform"]["data_sources"], 1)
        self.assertGreaterEqual(payload["terraform"]["modules"], 1)
        self.assertGreaterEqual(payload["terraform"]["variables"], 4)
        self.assertGreaterEqual(payload["terraform"]["outputs"], 1)
        self.assertGreaterEqual(payload["terraform"]["locals"], 1)
        self.assertGreaterEqual(payload["terraform"]["moved"], 1)
        self.assertGreaterEqual(payload["terraform"]["imports"], 1)
        self.assertGreaterEqual(payload["terraform"]["checks"], 1)
        self.assertGreaterEqual(payload["terraform"]["removed"], 1)
        self.assertGreaterEqual(payload["references"]["total"], 1)
        self.assertGreaterEqual(payload["references"]["module_sources"], 1)
        self.assertGreaterEqual(payload["references"]["local_module_refs"], 1)
        self.assertGreaterEqual(payload["references"]["remote_refs_not_fetched"], 1)
        self.assertGreaterEqual(payload["references"]["depends_on"], 1)
        self.assertGreaterEqual(payload["references"]["provider_aliases"], 1)
        self.assertEqual(payload["tfvars"]["files"], 3)
        self.assertGreaterEqual(payload["tfvars"]["variables"], 3)
        self.assertFalse(payload["tfvars"]["literal_values_exposed"])
        self.assertGreaterEqual(payload["redactions"]["tfvars_values"], 3)
        self.assertGreaterEqual(payload["redactions"]["secret_like_fields"], 1)
        self.assertGreaterEqual(payload["redactions"]["credentialed_urls"], 1)
        self.assertGreaterEqual(payload["redactions"]["import_ids"], 1)
        self.assertGreaterEqual(payload["diagnostics"]["parse_errors"], 1)
        self.assertGreaterEqual(payload["diagnostics"]["malformed_hcl"], 1)
        self.assertGreaterEqual(payload["generic_config"]["file_nodes"], 5)
        self.assertTrue(payload["safety"]["no_execution"])
        self.assertTrue(payload["safety"]["no_fetch"])
        self.assertTrue(payload["safety"]["no_terraform_cli"])
        self.assertTrue(payload["safety"]["tfvars_redacted"])
        self.assertTrue(payload["safety"]["no_new_canonical_namespaces"])
        self.assertIn("terraform_observations", table_stdout)
        self.assertIn("remote_refs_not_fetched", table_stdout)
        self.assertIn("literal_values_exposed=false", table_stdout)
        self.assertIn("no_terraform_cli=true", table_stdout)

        readback_payload = "\n".join((summary_stdout, table_stdout))
        self.assertNotIn("fake-tfhcl-provider-secret", readback_payload)
        self.assertNotIn("fake-tfhcl-module-secret", readback_payload)
        self.assertNotIn("fake-tfhcl-prod-tfvars-secret", readback_payload)
        self.assertNotIn("fake-tfhcl-tfvars-secret", readback_payload)
        self.assertNotIn("fake-tfhcl-import-secret", readback_payload)
        self.assertNotIn("user:pass@", readback_payload)
        self.assertFalse(
            any(record.kind.startswith("terraform.") for record in canonical_nodes)
        )
        self.assertEqual(
            {edge.edge_kind for edge in canonical_edges} - {"defines", "references"},
            set(),
        )
