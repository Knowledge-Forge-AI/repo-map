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
)

from repomap_test_support.storage_integration import (
    discovery_fixture,
)


class StorageTomlYamlReadbackIntegrationTests(unittest.TestCase):
    def test_storage_loads_toml_config_discovery_into_canonical_readback(self):
        require_postgres_binaries()
        fixture_root = discovery_fixture("config_toml_basic")

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
                storage_args = (
                    "--root-path",
                    str(fixture_root),
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
                )
                load_exit_code, _load_stdout, load_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "load-files",
                        jsonl_file.name,
                        "--repository-name",
                        "toml-config-fixture",
                        *storage_args,
                        "--json",
                    )
                )

                def canonical_nodes(kind):
                    return run_repo_map_in_process(
                        "storage",
                        "nodes",
                        *storage_args,
                        "--kind",
                        kind,
                        "--limit",
                        "200",
                        "--legacy-json-array",
                        "--json",
                    )

                document_exit, document_stdout, document_stderr = (
                    canonical_nodes("config.document")
                )
                path_exit, path_stdout, path_stderr = canonical_nodes("config.path")

                def canonical_edges(kind):
                    return run_repo_map_in_process(
                        "storage",
                        "edges",
                        *storage_args,
                        "--kind",
                        kind,
                        "--limit",
                        "200",
                        "--legacy-json-array",
                        "--json",
                    )

                defines_exit, defines_stdout, defines_stderr = canonical_edges(
                    "defines"
                )
                references_exit, references_stdout, references_stderr = (
                    canonical_edges("references")
                )
                explain_exit, explain_stdout, explain_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "explain-canonical-edge",
                        *storage_args,
                        "--source-key",
                        "config.path:file%3Amcp%2Fconfig.toml:%2Fmcp_servers%2Frepomap%2Fcommand",
                        "--kind",
                        "references",
                        "--target-key",
                        "tool:python3",
                        "--json",
                    )
                )

        self.assertEqual(discover_exit_code, 0, discover_stderr)
        self.assertNotIn("cfg2-sensitive-api-key", discover_stdout)
        self.assertNotIn("cfg2-sensitive-token", discover_stdout)
        discovered = [
            json.loads(line)
            for line in discover_stdout.splitlines()
            if line.strip()
        ]
        discovered_kinds = {record["kind"] for record in discovered}
        self.assertTrue(
            {
                "config.document",
                "config.path",
                "config.reference",
                "config.parse_error",
            }.issubset(discovered_kinds)
        )

        self.assertEqual(load_exit_code, 0, load_stderr)

        self.assertEqual(document_exit, 0, document_stderr)
        document_keys = {
            record["canonical_key"]
            for record in json.loads(document_stdout)
        }
        self.assertIn(
            "config.document:file%3Amcp%2Fconfig.toml",
            document_keys,
        )

        self.assertEqual(path_exit, 0, path_stderr)
        path_keys = {record["canonical_key"] for record in json.loads(path_stdout)}
        self.assertIn(
            "config.path:file%3Amcp%2Fconfig.toml:%2Fmcp_servers%2Frepomap%2Fcommand",
            path_keys,
        )
        self.assertIn(
            "config.path:file%3Amcp%2Fconfig.toml:%2Ftools%2Frepomap%2Fcommand",
            path_keys,
        )
        self.assertTrue(all(":0" not in key for key in path_keys))

        self.assertEqual(defines_exit, 0, defines_stderr)
        define_targets = {
            record["target_key"]
            for record in json.loads(defines_stdout)
        }
        self.assertIn(
            "config.document:file%3Amcp%2Fconfig.toml",
            define_targets,
        )
        self.assertIn(
            "config.path:file%3Amcp%2Fconfig.toml:%2Ftools%2Frepomap%2Fpath",
            define_targets,
        )

        self.assertEqual(references_exit, 0, references_stderr)
        reference_edges = json.loads(references_stdout)
        self.assertIn(
            (
                "config.path:file%3Amcp%2Fconfig.toml:%2Fmcp_servers%2Frepomap%2Fcommand",
                "tool:python3",
            ),
            {
                (record["source_key"], record["target_key"])
                for record in reference_edges
            },
        )
        self.assertIn(
            "file:bin/tool",
            {record["target_key"] for record in reference_edges},
        )
        self.assertIn(
            "external.url:https%3A%2F%2Fexample.com%2Fdocs",
            {record["target_key"] for record in reference_edges},
        )

        self.assertEqual(explain_exit, 0, explain_stderr)
        explanation = json.loads(explain_stdout)["result"]
        self.assertEqual(explanation["edge"]["edge_kind"], "references")
        self.assertEqual(explanation["edge"]["target_key"], "tool:python3")
        self.assertEqual(len(explanation["evidence"]), 1)
        self.assertEqual(
            explanation["evidence"][0]["raw_observation"]["kind"],
            "config.reference",
        )
        self.assertNotIn("cfg2-sensitive-api-key", explain_stdout)
        self.assertNotIn("cfg2-sensitive-token", explain_stdout)

    def test_storage_loads_yaml_config_discovery_into_canonical_readback(self):
        require_postgres_binaries()
        fixture_root = discovery_fixture("yaml_basic")

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
                storage_args = (
                    "--root-path",
                    str(fixture_root),
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
                )
                load_exit_code, _load_stdout, load_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "load-files",
                        jsonl_file.name,
                        "--repository-name",
                        "yaml-config-fixture",
                        *storage_args,
                        "--json",
                    )
                )

                def canonical_nodes(kind):
                    return run_repo_map_in_process(
                        "storage",
                        "nodes",
                        *storage_args,
                        "--kind",
                        kind,
                        "--limit",
                        "200",
                        "--legacy-json-array",
                        "--json",
                    )

                document_exit, document_stdout, document_stderr = (
                    canonical_nodes("config.document")
                )
                path_exit, path_stdout, path_stderr = canonical_nodes("config.path")

                def canonical_edges(kind):
                    return run_repo_map_in_process(
                        "storage",
                        "edges",
                        *storage_args,
                        "--kind",
                        kind,
                        "--limit",
                        "200",
                        "--legacy-json-array",
                        "--json",
                    )

                defines_exit, defines_stdout, defines_stderr = canonical_edges(
                    "defines"
                )
                references_exit, references_stdout, references_stderr = (
                    canonical_edges("references")
                )
                explain_exit, explain_stdout, explain_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "explain-canonical-edge",
                        *storage_args,
                        "--source-key",
                        "config.path:file%3A.github%2Fworkflows%2Fbuild.yml:%2Fjobs%2Ftest%2Fsteps%2Fcheckout%2Fuses",
                        "--kind",
                        "references",
                        "--target-key",
                        "external:github.action:actions%2Fcheckout%40v4",
                        "--json",
                    )
                )

        self.assertEqual(discover_exit_code, 0, discover_stderr)
        self.assertNotIn("fake-actions-token", discover_stdout)
        self.assertNotIn("fake-kubernetes-password", discover_stdout)
        self.assertNotIn("fake-client-secret", discover_stdout)
        discovered = [
            json.loads(line)
            for line in discover_stdout.splitlines()
            if line.strip()
        ]
        discovered_kinds = {record["kind"] for record in discovered}
        self.assertTrue(
            {
                "config.document",
                "config.path",
                "config.reference",
                "config.parse_error",
            }.issubset(discovered_kinds)
        )

        self.assertEqual(load_exit_code, 0, load_stderr)

        self.assertEqual(document_exit, 0, document_stderr)
        documents = json.loads(document_stdout)
        document_keys = {record["canonical_key"] for record in documents}
        self.assertIn("config.document:file%3Aopenapi.yaml", document_keys)
        self.assertTrue(
            any(
                record["metadata"].get("profile") == "github_actions"
                for record in documents
            )
        )

        self.assertEqual(path_exit, 0, path_stderr)
        path_keys = {record["canonical_key"] for record in json.loads(path_stdout)}
        self.assertIn(
            "config.path:file%3Aopenapi.yaml:%2Fpaths%2F~1pets%2Fget%2Fresponses%2F200%2F%24ref",
            path_keys,
        )
        self.assertIn(
            "config.path:file%3Adocker-compose.yml:%2Fservices%2Fapp%2Fimage",
            path_keys,
        )

        self.assertEqual(defines_exit, 0, defines_stderr)
        define_targets = {
            record["target_key"]
            for record in json.loads(defines_stdout)
        }
        self.assertIn("config.document:file%3Aopenapi.yaml", define_targets)

        self.assertEqual(references_exit, 0, references_stderr)
        reference_edges = json.loads(references_stdout)
        edge_pairs = {
            (record["source_key"], record["target_key"])
            for record in reference_edges
        }
        self.assertIn(
            (
                "config.path:file%3A.github%2Fworkflows%2Fbuild.yml:%2Fjobs%2Ftest%2Fsteps%2Fcheckout%2Fuses",
                "external:github.action:actions%2Fcheckout%40v4",
            ),
            edge_pairs,
        )
        self.assertIn(
            (
                "config.path:file%3Aopenapi.yaml:%2Fpaths%2F~1pets%2Fget%2Fresponses%2F200%2F%24ref",
                "config.path:file%3Aopenapi.yaml:%2Fcomponents%2Fresponses%2FPets",
            ),
            edge_pairs,
        )

        self.assertEqual(explain_exit, 0, explain_stderr)
        explanation = json.loads(explain_stdout)["result"]
        self.assertEqual(explanation["edge"]["edge_kind"], "references")
        self.assertEqual(
            explanation["edge"]["target_key"],
            "external:github.action:actions%2Fcheckout%40v4",
        )
        self.assertEqual(len(explanation["evidence"]), 1)
        self.assertEqual(
            explanation["evidence"][0]["raw_observation"]["kind"],
            "config.reference",
        )
        self.assertNotIn("fake-actions-token", explain_stdout)
        self.assertNotIn("fake-kubernetes-password", explain_stdout)
        self.assertNotIn("fake-client-secret", explain_stdout)
