import json
import unittest

from repomap_test_support.cli_in_process import run_repo_map_in_process
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)

from repomap_kg.observations import RawObservation
from repomap_test_support.storage_publication import load_file_observations
from repomap_kg.storage import (
    apply_migrations,
    default_rdbms_root,
)


class StorageHostMutatorsCliIntegrationTests(unittest.TestCase):
    def test_storage_host_mutators_cli_reads_loaded_relationship_rows(self):
        require_postgres_binaries()
        observations = [
            RawObservation(
                kind="file",
                source_id="scripts/maintain.sh",
                path="scripts/maintain.sh",
                confidence="extracted",
                extractor="fixture-discovery",
                extractor_version="0.1.0",
                metadata={
                    "language": "shell",
                    "role": "script",
                    "content_hash": "0" * 64,
                    "generated": False,
                    "executable": True,
                },
            ),
            RawObservation(
                kind="shell.host_mutation",
                source_id=(
                    "scripts/maintain.sh"
                    "#host-mutation:2:filesystem-mutation-rm"
                ),
                path="scripts/maintain.sh",
                start_line=2,
                end_line=2,
                name="rm",
                target="host:filesystem-mutation",
                confidence="heuristic",
                extractor="fixture-shell",
                extractor_version="0.1.0",
                metadata={
                    "argv": ["sudo", "rm", "-rf", "/Library/Caches/example"],
                    "category": "filesystem-mutation",
                    "effective_argv": ["rm", "-rf", "/Library/Caches/example"],
                    "privileged": True,
                    "reason": "rm host filesystem path",
                    "tool": "rm",
                },
            ),
        ]

        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            load_file_observations(
                postgres.psql_args,
                observations,
                repository_name="fixture",
                root_path="/tmp/fixture",
                psql_command=postgres.psql_command,
            )
            exit_code, stdout, stderr = run_repo_map_in_process(
                "storage",
                "host-mutators",
                "--root-path",
                "/tmp/fixture",
                "--category",
                "filesystem-mutation",
                "--tool",
                "rm",
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

        payload = json.loads(stdout)
        self.assertEqual(exit_code, 0, stderr)
        self.assertEqual(payload[0]["source_key"], "file:scripts/maintain.sh")
        self.assertEqual(payload[0]["category"], "filesystem-mutation")
        self.assertEqual(
            payload[0]["target_key"], "host.category:filesystem-mutation"
        )
        self.assertEqual(payload[0]["tool_names"], ["rm"])

    def test_storage_host_mutators_canonical_cli_reads_mutates_host_edges(self):
        require_postgres_binaries()
        observations = [
            RawObservation(
                kind="file",
                source_id="scripts/maintain.sh",
                path="scripts/maintain.sh",
                confidence="extracted",
                extractor="fixture-discovery",
                extractor_version="0.1.0",
                metadata={
                    "language": "shell",
                    "role": "script",
                    "content_hash": "0" * 64,
                    "generated": False,
                    "executable": True,
                },
            ),
            RawObservation(
                kind="shell.host_mutation",
                source_id=(
                    "scripts/maintain.sh"
                    "#host-mutation:2:filesystem-mutation-rm"
                ),
                path="scripts/maintain.sh",
                start_line=2,
                end_line=2,
                name="rm",
                target="host:filesystem-mutation",
                confidence="heuristic",
                extractor="fixture-shell",
                extractor_version="0.1.0",
                metadata={
                    "argv": ["sudo", "rm", "-rf", "/Library/Caches/example"],
                    "category": "filesystem-mutation",
                    "effective_argv": ["rm", "-rf", "/Library/Caches/example"],
                    "privileged": True,
                    "reason": "rm host filesystem path",
                    "tool": "rm",
                },
            ),
            RawObservation(
                kind="shell.host_mutation",
                source_id="scripts/startup.zsh#host-mutation-intent:rm",
                path="scripts/startup.zsh",
                start_line=3,
                end_line=3,
                name="rm",
                target="host:filesystem-mutation",
                confidence="heuristic",
                extractor="fixture-zsh",
                extractor_version="0.1.0",
                metadata={
                    "command_name": "rm",
                    "dialect": "zsh",
                    "language": "zsh",
                    "mutation_category": "filesystem-mutation",
                    "operation": "cleanup",
                    "runtime_intent": True,
                    "shell_executed": False,
                    "static_only": True,
                    "target_kind": "static",
                    "zsh_executed": False,
                },
            ),
            RawObservation(
                kind="shell.network_call",
                source_id="scripts/startup.zsh#network-intent:curl",
                path="scripts/startup.zsh",
                start_line=4,
                end_line=4,
                name="curl",
                target="https://example.invalid/install.zsh",
                confidence="heuristic",
                extractor="fixture-zsh",
                extractor_version="0.1.0",
                metadata={
                    "command_name": "curl",
                    "dialect": "zsh",
                    "language": "zsh",
                    "target_display": "https://example.invalid/install.zsh",
                    "target_kind": "static",
                },
            ),
            RawObservation(
                kind="shell.package_manager",
                source_id="scripts/startup.zsh#package-intent:brew",
                path="scripts/startup.zsh",
                start_line=5,
                end_line=5,
                name="brew",
                target="tool:brew",
                confidence="heuristic",
                extractor="fixture-zsh",
                extractor_version="0.1.0",
                metadata={
                    "command_name": "brew",
                    "dialect": "zsh",
                    "language": "zsh",
                    "operation": "install",
                    "target_kind": "static",
                },
            ),
        ]

        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            load_file_observations(
                postgres.psql_args,
                observations,
                repository_name="fixture",
                root_path="/tmp/fixture",
                psql_command=postgres.psql_command,
            )
            exit_code, stdout, stderr = run_repo_map_in_process(
                "storage",
                "host-mutators",
                "--root-path",
                "/tmp/fixture",
                "--category",
                "filesystem-mutation",
                "--tool",
                "rm",
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
            explain_exit_code, explain_stdout, explain_stderr = (
                run_repo_map_in_process(
                    "storage",
                    "explain-canonical-edge",
                    "--root-path",
                    "/tmp/fixture",
                    "--source-key",
                    "file:scripts/maintain.sh",
                    "--kind",
                    "mutates_host",
                    "--target-key",
                    "host.category:filesystem-mutation",
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
            )

        payload = json.loads(stdout)
        self.assertEqual(exit_code, 0, stderr)
        self.assertEqual(
            {(row["edge_kind"], row["category"]) for row in payload},
            {
                ("mutates_host", "filesystem-mutation"),
                ("host_mutation_intent", "filesystem-mutation"),
            },
        )
        self.assertNotIn("network_intent", {row["edge_kind"] for row in payload})
        self.assertNotIn("package_intent", {row["edge_kind"] for row in payload})
        mutates_row = next(
            row for row in payload if row["edge_kind"] == "mutates_host"
        )
        intent_row = next(
            row for row in payload if row["edge_kind"] == "host_mutation_intent"
        )
        self.assertEqual(mutates_row["source_key"], "file:scripts/maintain.sh")
        self.assertEqual(
            mutates_row["target_key"],
            "host.category:filesystem-mutation",
        )
        self.assertEqual(mutates_row["graph_key_version"], 1)
        self.assertEqual(mutates_row["confidence"], "heuristic")
        self.assertFalse(mutates_row["conflict"])
        self.assertEqual(mutates_row["tool_names"], ["rm"])
        self.assertTrue(mutates_row["privileged_observed"])
        self.assertEqual(intent_row["command_names"], ["rm"])
        self.assertTrue(intent_row["runtime_intent"])
        self.assertFalse(intent_row["host_mutation_proven"])
        for row in payload:
            self.assertNotIn("metadata", row)
            self.assertNotIn("argv_examples", row)
            self.assertNotIn("effective_argv_examples", row)
            self.assertNotIn("reasons", row)
            self.assertNotIn("stable_key", row)
            self.assertNotIn("id", row)

        explain_payload = json.loads(explain_stdout)["result"]
        self.assertEqual(explain_exit_code, 0, explain_stderr)
        self.assertEqual(
            explain_payload["edge"]["target_key"],
            "host.category:filesystem-mutation",
        )
        self.assertEqual(
            explain_payload["evidence"][0]["path"],
            "scripts/maintain.sh",
        )
        self.assertEqual(
            explain_payload["evidence"][0]["metadata"]["tool"],
            "rm",
        )
