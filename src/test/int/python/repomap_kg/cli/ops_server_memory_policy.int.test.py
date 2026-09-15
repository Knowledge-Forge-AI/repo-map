import json
import tempfile
from pathlib import Path

from repomap_test_support.cli_integration import (
    CliIntegrationTestCase,
    OPS_CONFIG_TEMPLATE,
    OPS_POLICY_FIXTURES,
    SERVER_MEMORY_FIXTURES,
)



class CliOpsServerMemoryPolicyIntegrationTests(CliIntegrationTestCase):
    def test_ops_server_memory_summary_and_search_read_fake_jsonl_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            memory_path = SERVER_MEMORY_FIXTURES / "basic" / "memory.jsonl"
            config_path = self.write_ops_config(
                Path(tmpdir),
                OPS_CONFIG_TEMPLATE.replace(
                    "enabled = false\npath = \"./server-memory\"",
                    f"enabled = true\npath = \"{memory_path}\"",
                ),
            )

            summary_exit, summary_stdout, summary_stderr = self.run_module_entrypoint(
                "ops",
                "server-memory-summary",
                "--config",
                str(config_path),
                "--json",
            )
            search_exit, search_stdout, search_stderr = self.run_module_entrypoint(
                "ops",
                "server-memory-search",
                "--config",
                str(config_path),
                "--query",
                "RepoMap",
                "--limit",
                "1",
                "--json",
            )
            table_exit, table_stdout, table_stderr = self.run_module_entrypoint(
                "ops",
                "server-memory-summary",
                "--config",
                str(config_path),
            )

        self.assertEqual(summary_exit, 0, summary_stderr)
        self.assertEqual(search_exit, 0, search_stderr)
        self.assertEqual(table_exit, 0, table_stderr)
        summary = json.loads(summary_stdout)
        search = json.loads(search_stdout)
        self.assertEqual(summary["summary"]["entry_count"], 3)
        self.assertEqual(summary["summary"]["entity_count"], 2)
        self.assertEqual(summary["summary"]["relation_count"], 1)
        self.assertFalse(summary["safety"]["server_memory_mutated"])
        self.assertEqual(search["result_count"], 1)
        self.assertTrue(search["has_more"])
        self.assertIn("server_memory:", table_stdout)
        self.assertEqual(summary_stderr, "")
        self.assertEqual(search_stderr, "")
        self.assertEqual(table_stderr, "")

    def test_ops_server_memory_summary_reads_repo_map_home_only_when_explicit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            home.mkdir()
            memory_path = SERVER_MEMORY_FIXTURES / "basic" / "memory.jsonl"
            self.write_fixture(
                home / "00-project.rp.toml",
                OPS_CONFIG_TEMPLATE.replace(
                    "enabled = false\npath = \"./server-memory\"",
                    f"enabled = true\npath = \"{memory_path}\"",
                ),
            )

            exit_code, stdout, stderr = self.run_module_entrypoint(
                "ops",
                "server-memory-summary",
                "--repo-map-home",
                str(home),
                "--json",
            )

        self.assertEqual(exit_code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["summary"]["entry_count"], 3)
        self.assertTrue(payload["safety"]["read_only"])
        self.assertFalse(payload["safety"]["server_memory_mutated"])
        self.assertEqual(stderr, "")

    def test_ops_server_memory_disabled_config_returns_safe_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = self.write_ops_config(Path(tmpdir), OPS_CONFIG_TEMPLATE)

            exit_code, stdout, stderr = self.run_module_entrypoint(
                "ops",
                "server-memory-summary",
                "--config",
                str(config_path),
                "--json",
            )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout)
        self.assertFalse(payload["enabled"])
        self.assertEqual(payload["diagnostics"][0]["code"], "server-memory-disabled")
        self.assertEqual(stderr, "")

    def test_ops_server_memory_handles_redaction_malformed_and_directory_fixtures(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            redaction_config = self.write_ops_config(
                Path(tmpdir),
                OPS_CONFIG_TEMPLATE.replace(
                    "enabled = false\npath = \"./server-memory\"",
                    "enabled = true\n"
                    f"path = \"{SERVER_MEMORY_FIXTURES / 'redaction' / 'memory.jsonl'}\"",
                ),
                name="redaction.toml",
            )
            malformed_config = self.write_ops_config(
                Path(tmpdir),
                OPS_CONFIG_TEMPLATE.replace(
                    "enabled = false\npath = \"./server-memory\"",
                    "enabled = true\n"
                    f"path = \"{SERVER_MEMORY_FIXTURES / 'malformed' / 'memory.jsonl'}\"",
                ),
                name="malformed.toml",
            )
            directory_config = self.write_ops_config(
                Path(tmpdir),
                OPS_CONFIG_TEMPLATE.replace(
                    "enabled = false\npath = \"./server-memory\"",
                    f"enabled = true\npath = \"{SERVER_MEMORY_FIXTURES / 'paths'}\"",
                ),
                name="directory.toml",
            )

            redaction_exit, redaction_stdout, redaction_stderr = (
                self.run_module_entrypoint(
                    "ops",
                    "server-memory-search",
                    "--config",
                    str(redaction_config),
                    "--query",
                    "Credential",
                    "--json",
                )
            )
            malformed_exit, malformed_stdout, malformed_stderr = (
                self.run_module_entrypoint(
                    "ops",
                    "server-memory-summary",
                    "--config",
                    str(malformed_config),
                    "--json",
                )
            )
            directory_exit, directory_stdout, directory_stderr = (
                self.run_module_entrypoint(
                    "ops",
                    "server-memory-search",
                    "--config",
                    str(directory_config),
                    "--query",
                    "Path Catalog",
                    "--kind",
                    "entity",
                )
            )

        self.assertEqual(redaction_exit, 0, redaction_stderr)
        self.assertEqual(malformed_exit, 0, malformed_stderr)
        self.assertEqual(directory_exit, 0, directory_stderr)
        redaction = json.loads(redaction_stdout)
        malformed = json.loads(malformed_stdout)
        self.assertEqual(redaction["result_count"], 1)
        self.assertIn("[REDACTED]", redaction_stdout)
        self.assertNotIn("mcp-ops5-fake-token", redaction_stdout)
        self.assertEqual(malformed["summary"]["malformed_line_count"], 1)
        self.assertEqual(malformed["diagnostics"][0]["code"], "malformed-jsonl")
        self.assertIn("server_memory_search:", directory_stdout)
        self.assertIn("Path Catalog", directory_stdout)

    def test_ops_policy_dogfood_reports_public_safe_boundary_model(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            home = root / "repo-map-home"
            memory = root / "server-memory"
            memory.mkdir(parents=True)
            memory_file = memory / "memory.jsonl"
            memory_file.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "type": "entity",
                                "name": "Memory Boundary Policy",
                                "entityType": "policy",
                                "observations": [
                                    "Durable rules belong in AGENTS.md.",
                                    "Use server-memory as a card catalog.",
                                ],
                            }
                        ),
                        json.dumps(
                            {
                                "type": "entity",
                                "name": "Private Runtime Note",
                                "entityType": "local-config",
                                "observations": [
                                    "Machine path /path/to/codex-vc stays private.",
                                    "password=mcp-ops6-fake-password",
                                ],
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            self.write_fixture(
                home / "00-project.rp.toml",
                f"""\
schema_version = 1

[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[postgres]
host = "127.0.0.1"
port = 5432
database = "repomap"
user = "admin"
password_env = "REPOMAP_PG_PASSWORD"

[[graphs]]
id = "codex-vc"
name = "Codex VC Fixture"
root_path = "../codex-vc"
repository_name = "codex-vc"
privacy = "private-ops"
enabled = true
mcp_visible = true
extractor_profile = "private-ops"
refresh_policy = "manual"
exclude_paths = [
  ".git",
  ".serena",
  "mcp/server-memory/memory.jsonl",
  "mcp/server-memory/serena",
]

[server_memory]
enabled = true
path = "{memory_file}"
mode = "read_only"
""",
            )

            json_exit, json_stdout, json_stderr = self.run_module_entrypoint(
                "ops",
                "policy-dogfood",
                "--repo-map-home",
                str(home),
                "--graph",
                "codex-vc",
                "--json",
            )
            table_exit, table_stdout, table_stderr = self.run_module_entrypoint(
                "ops",
                "policy-dogfood",
                "--repo-map-home",
                str(home),
                "--graph",
                "codex-vc",
            )

        self.assertEqual(json_exit, 0, json_stderr)
        self.assertEqual(table_exit, 0, table_stderr)
        payload = json.loads(json_stdout)
        self.assertEqual(payload["command"], "policy-dogfood")
        self.assertEqual(payload["graph"]["graph_id"], "codex-vc")
        self.assertEqual(payload["graph"]["exclude_paths_count"], 4)
        self.assertGreaterEqual(
            payload["policy_boundary"]["durable_operational_rules"]["count"],
            1,
        )
        self.assertGreaterEqual(
            payload["policy_boundary"]["private_local_preferences"]["count"],
            1,
        )
        self.assertTrue(payload["agents_refinement"]["applied"] is False)
        self.assertTrue(payload["safety"]["no_graph_root_reads"])
        self.assertFalse(payload["safety"]["server_memory_mutated"])
        self.assertNotIn("mcp-ops6-fake-password", json_stdout)
        self.assertNotIn("raw_payload", json_stdout)
        self.assertNotIn("observations", json_stdout)
        self.assertIn("policy_dogfood:", table_stdout)
        self.assertIn("agents_applied=false", table_stdout)
        self.assertEqual(json_stderr, "")
        self.assertEqual(table_stderr, "")

    def test_ops_policy_dogfood_committed_fixture_is_public_safe(self):
        exit_code, stdout, stderr = self.run_module_entrypoint(
            "ops",
            "policy-dogfood",
            "--repo-map-home",
            str(OPS_POLICY_FIXTURES / "repo_map_home"),
            "--graph",
            "codex-vc",
            "--json",
        )

        self.assertEqual(exit_code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["server_memory"]["entry_count"], 4)
        self.assertTrue(payload["safety"]["server_memory_read"])
        self.assertTrue(payload["safety"]["no_graph_root_reads"])
        self.assertIn(
            "mcp/server-memory/memory.jsonl",
            payload["graph"]["exclude_paths_summary"],
        )
        self.assertNotIn("mcp-ops6-fake-token", stdout)
        self.assertNotIn("raw_payload", stdout)
        self.assertEqual(stderr, "")

    def test_ops_policy_dogfood_hidden_and_unknown_graphs_are_safe(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory = root / "memory.jsonl"
            memory.write_text(
                json.dumps(
                    {
                        "type": "entity",
                        "name": "Should Not Read",
                        "observations": ["token=mcp-ops6-hidden-token"],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            config_path = self.write_ops_config(
                root,
                OPS_CONFIG_TEMPLATE.replace(
                    'id = "repo-map"', 'id = "hidden-policy"'
                ).replace(
                    'name = "RepoMap"', 'name = "Hidden Policy Fixture"'
                ).replace(
                    'repository_name = "repo-map"', 'repository_name = "hidden-policy"'
                ).replace(
                    'privacy = "public-dev"', 'privacy = "private-ops"'
                ).replace(
                    "mcp_visible = true", "mcp_visible = false"
                ).replace(
                    'enabled = false\npath = "./server-memory"', f'enabled = true\npath = "{memory}"'
                ),
                name="hidden.rp.toml",
            )

            hidden_exit, hidden_stdout, hidden_stderr = self.run_module_entrypoint(
                "ops", "policy-dogfood", "--config", str(config_path), "--graph", "hidden-policy", "--json",
            )
            unknown_exit, _unknown_stdout, unknown_stderr = self.run_module_entrypoint(
                "ops", "policy-dogfood", "--config", str(config_path), "--graph", "missing-policy", "--json",
            )

        self.assertEqual(hidden_exit, 0, hidden_stderr)
        hidden = json.loads(hidden_stdout)
        self.assertFalse(hidden["graph"]["mcp_visible"])
        self.assertEqual(hidden["server_memory"]["entry_count"], 0)
        self.assertFalse(hidden["safety"]["server_memory_read"])
        self.assertEqual(hidden["diagnostics"][0]["code"], "graph-not-mcp-visible")
        self.assertNotIn("mcp-ops6-hidden-token", hidden_stdout)
        self.assertEqual(hidden_stderr, "")
        self.assertEqual(unknown_exit, 1)
        self.assertIn("unknown graph id", unknown_stderr)
