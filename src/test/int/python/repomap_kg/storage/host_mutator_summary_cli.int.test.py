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


class StorageHostMutatorSummaryCliIntegrationTests(unittest.TestCase):
    def test_storage_host_mutators_summary_cli_reads_loaded_counts(self):
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
                source_id=(
                    "scripts/maintain.sh"
                    "#host-mutation:3:filesystem-mutation-rm"
                ),
                path="scripts/maintain.sh",
                start_line=3,
                end_line=3,
                name="rm",
                target="host:filesystem-mutation",
                confidence="heuristic",
                extractor="fixture-shell",
                extractor_version="0.1.0",
                metadata={
                    "argv": ["rm", "-rf", "~/Library/Caches/example"],
                    "category": "filesystem-mutation",
                    "effective_argv": ["rm", "-rf", "~/Library/Caches/example"],
                    "privileged": False,
                    "reason": "rm host filesystem path",
                    "tool": "rm",
                },
            ),
            RawObservation(
                kind="shell.host_mutation",
                source_id="scripts/maintain.sh#host-mutation:4:package",
                path="scripts/maintain.sh",
                start_line=4,
                end_line=4,
                name="brew install",
                target="host:package-management",
                confidence="heuristic",
                extractor="fixture-shell",
                extractor_version="0.1.0",
                metadata={
                    "argv": ["brew", "install", "postgresql"],
                    "category": "package-management",
                    "effective_argv": ["brew", "install", "postgresql"],
                    "privileged": False,
                    "reason": "brew install",
                    "tool": "brew",
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
                "host-mutators-summary",
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
        self.assertEqual(payload, [
            {
                "category": "filesystem-mutation",
                "canonical_edge_count": 1,
                "edge_kind": "host_mutation_intent",
                "intent_edge_count": 1,
                "privileged_edge_count": 0,
                "proven_edge_count": 0,
                "source_count": 1,
            },
            {
                "category": "filesystem-mutation",
                "canonical_edge_count": 1,
                "edge_kind": "mutates_host",
                "intent_edge_count": 0,
                "privileged_edge_count": 1,
                "proven_edge_count": 1,
                "source_count": 1,
            }
        ])
        for row in payload:
            self.assertNotIn("count", row)
            self.assertNotIn("privileged_count", row)
        self.assertNotIn("network_intent", {row["edge_kind"] for row in payload})
        self.assertNotIn("package_intent", {row["edge_kind"] for row in payload})
