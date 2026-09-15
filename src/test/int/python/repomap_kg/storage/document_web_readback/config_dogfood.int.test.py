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


class StorageConfigDogfoodReadbackIntegrationTests(unittest.TestCase):
    def test_storage_loads_codex_mcp_config_dogfood_into_canonical_readback(self):
        require_postgres_binaries()
        fixture_root = discovery_fixture("config_codex_mcp_dogfood")

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
                        "codex-mcp-config-dogfood",
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

                tool_explain_exit, tool_explain_stdout, tool_explain_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "explain-canonical-edge",
                        *storage_args,
                        "--source-key",
                        "config.path:file%3Amcp%2Frepo-map%2Fconfig.json:%2Fmcp_servers%2Frepomap%2Fcommand",
                        "--kind",
                        "references",
                        "--target-key",
                        "tool:repomap-kg",
                        "--json",
                    )
                )
                file_explain_exit, file_explain_stdout, file_explain_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "explain-canonical-edge",
                        *storage_args,
                        "--source-key",
                        "config.path:file%3Amcp%2Frepo-map%2Fconfig.json:%2Fmcp_servers%2Frepomap%2Fconfig_path",
                        "--kind",
                        "references",
                        "--target-key",
                        "file:codex/config.toml",
                        "--json",
                    )
                )
                env_explain_exit, env_explain_stdout, env_explain_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "explain-canonical-edge",
                        *storage_args,
                        "--source-key",
                        "config.path:file%3Amcp%2Frepo-map%2Fconfig.json:%2Fmcp_servers%2Frepomap%2Fenv%2FREPOMAP_MCP_CONFIG",
                        "--kind",
                        "references",
                        "--target-key",
                        "env:REPOMAP_MCP_CONFIG",
                        "--json",
                    )
                )

        for secret in (
            "cfg3-json-secret-token",
            "cfg3-json-secret-api-key",
            "cfg3-toml-secret-refresh-token",
            "cfg3-toml-secret-api-key",
            "cfg3-jsonl-secret-token",
            "cfg3-jsonc-secret-password",
        ):
            self.assertNotIn(secret, discover_stdout)
            self.assertNotIn(secret, document_stdout)
            self.assertNotIn(secret, path_stdout)
            self.assertNotIn(secret, references_stdout)
            self.assertNotIn(secret, tool_explain_stdout)
            self.assertNotIn(secret, file_explain_stdout)
            self.assertNotIn(secret, env_explain_stdout)

        self.assertEqual(discover_exit_code, 0, discover_stderr)
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
                "config.jsonl_record",
                "config.parse_error",
            }.issubset(discovered_kinds)
        )
        parse_errors = [
            record
            for record in discovered
            if record["kind"] == "config.parse_error"
        ]
        self.assertEqual(
            [(record["path"], record["metadata"]["error_kind"]) for record in parse_errors],
            [("logs/events.jsonl", "malformed-jsonl-line")],
        )
        self.assertEqual(
            sum(1 for record in discovered if record["kind"] == "config.jsonl_record"),
            3,
        )

        self.assertEqual(load_exit_code, 0, load_stderr)

        self.assertEqual(document_exit, 0, document_stderr)
        document_keys = {
            record["canonical_key"]
            for record in json.loads(document_stdout)
        }
        self.assertEqual(
            document_keys,
            {
                "config.document:file%3Acodex%2Fconfig.toml",
                "config.document:file%3Aeditor%2Fsettings.jsonc",
                "config.document:file%3Alogs%2Fevents.jsonl",
                "config.document:file%3Amcp%2Frepo-map%2Fconfig.json",
            },
        )

        self.assertEqual(path_exit, 0, path_stderr)
        path_keys = {record["canonical_key"] for record in json.loads(path_stdout)}
        self.assertTrue(
            {
                "config.path:file%3Amcp%2Frepo-map%2Fconfig.json:%2Fmcp_servers%2Frepomap%2Fcommand",
                "config.path:file%3Amcp%2Frepo-map%2Fconfig.json:%2Fmcp_servers%2Frepomap%2Fconfig_path",
                "config.path:file%3Amcp%2Frepo-map%2Fconfig.json:%2Fmcp_servers%2Frepomap%2Fenv%2FREPOMAP_MCP_CONFIG",
                "config.path:file%3Acodex%2Fconfig.toml:%2Fmcp_servers%2Frepomap%2Fcommand",
                "config.path:file%3Aeditor%2Fsettings.jsonc:%2Fconfig_path",
                "config.path:file%3Alogs%2Fevents.jsonl:%2Fcommand",
            }.issubset(path_keys)
        )
        self.assertTrue(all(":0" not in key for key in path_keys))

        self.assertEqual(defines_exit, 0, defines_stderr)
        define_targets = {
            record["target_key"]
            for record in json.loads(defines_stdout)
        }
        self.assertTrue(document_keys.issubset(define_targets))
        self.assertIn(
            "config.path:file%3Amcp%2Frepo-map%2Fconfig.json:%2Fmcp_servers%2Frepomap%2Fcommand",
            define_targets,
        )

        self.assertEqual(references_exit, 0, references_stderr)
        reference_edges = json.loads(references_stdout)
        reference_pairs = {
            (record["source_key"], record["target_key"])
            for record in reference_edges
        }
        self.assertTrue(
            {
                (
                    "config.path:file%3Amcp%2Frepo-map%2Fconfig.json:%2Fmcp_servers%2Frepomap%2Fcommand",
                    "tool:repomap-kg",
                ),
                (
                    "config.path:file%3Acodex%2Fconfig.toml:%2Fmcp_servers%2Frepomap%2Fcommand",
                    "tool:python3",
                ),
                (
                    "config.path:file%3Amcp%2Frepo-map%2Fconfig.json:%2Fmcp_servers%2Frepomap%2Fconfig_path",
                    "file:codex/config.toml",
                ),
                (
                    "config.path:file%3Aeditor%2Fsettings.jsonc:%2Fconfig_path",
                    "file:mcp/repo-map/config.json",
                ),
                (
                    "config.path:file%3Amcp%2Frepo-map%2Fconfig.json:%2Fmcp_servers%2Frepomap%2Fenv%2FREPOMAP_MCP_CONFIG",
                    "env:REPOMAP_MCP_CONFIG",
                ),
            }.issubset(reference_pairs)
        )
        reference_targets = {record["target_key"] for record in reference_edges}
        self.assertIn("unknown:file:repo-escaping-config-reference", reference_targets)
        self.assertIn(
            "external.url:https%3A%2F%2Fexample.com%2Frepo-map",
            reference_targets,
        )

        self.assertEqual(tool_explain_exit, 0, tool_explain_stderr)
        tool_explanation = json.loads(tool_explain_stdout)["result"]
        self.assertEqual(tool_explanation["edge"]["edge_kind"], "references")
        self.assertEqual(tool_explanation["edge"]["target_key"], "tool:repomap-kg")
        self.assertEqual(
            tool_explanation["evidence"][0]["raw_observation"]["kind"],
            "config.reference",
        )

        self.assertEqual(file_explain_exit, 0, file_explain_stderr)
        file_explanation = json.loads(file_explain_stdout)["result"]
        self.assertEqual(file_explanation["edge"]["target_key"], "file:codex/config.toml")
        self.assertEqual(
            file_explanation["evidence"][0]["raw_observation"]["kind"],
            "config.reference",
        )

        self.assertEqual(env_explain_exit, 0, env_explain_stderr)
        env_explanation = json.loads(env_explain_stdout)["result"]
        self.assertEqual(env_explanation["edge"]["target_key"], "env:REPOMAP_MCP_CONFIG")
        self.assertGreaterEqual(len(env_explanation["evidence"]), 1)
        self.assertTrue(
            {
                evidence["raw_observation"]["kind"]
                for evidence in env_explanation["evidence"]
            }.issubset({"config.reference"})
        )
