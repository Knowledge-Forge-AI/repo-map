import json
from pathlib import Path
import tempfile
import unittest


def write_policy_fixture(tmpdir: str) -> tuple[Path, Path]:
    root = Path(tmpdir)
    repo_map_home = root / "repo-map-home"
    server_memory = root / "server-memory"
    server_memory.mkdir(parents=True)
    (server_memory / "memory.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "entity",
                        "name": "Memory Boundary Policy",
                        "entityType": "policy",
                        "observations": [
                            "Durable memory boundary rules belong in AGENTS.md.",
                            "Use server-memory as a card catalog for policy pointers.",
                        ],
                    }
                ),
                json.dumps(
                    {
                        "type": "entity",
                        "name": "Private Local Path",
                        "entityType": "local-config",
                        "observations": [
                            "Machine-specific path /path/to/codex-vc stays private.",
                            "token=mcp-ops6-fake-token",
                        ],
                    }
                ),
                json.dumps(
                    {
                        "source": "Memory Boundary Policy",
                        "target": "RepoMap Graph Evidence",
                        "relationType": "is informed by",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    repo_map_home.mkdir()
    (repo_map_home / "00-project.rp.toml").write_text(
        f"""
schema_version = 1

[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[postgres]
host = "127.0.0.1"
port = 5432
database = "repomap"
user = "repo_map"
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
path = "{server_memory / "memory.jsonl"}"
mode = "read_only"
""",
        encoding="utf-8",
    )
    return repo_map_home, server_memory / "memory.jsonl"


class OpsPolicyDogfoodUnitTests(unittest.TestCase):
    def test_payload_classifies_policy_boundaries_and_redacts_secrets(self):
        from repomap_kg.ops.policy_dogfood import policy_dogfood_payload

        with tempfile.TemporaryDirectory() as tmpdir:
            repo_map_home, _ = write_policy_fixture(tmpdir)

            payload = policy_dogfood_payload(
                config_home=repo_map_home,
                graph_id="codex-vc",
            )

        self.assertEqual(payload["command"], "policy-dogfood")
        self.assertTrue(payload["read_only"])
        self.assertEqual(payload["graph"]["graph_id"], "codex-vc")
        self.assertEqual(payload["graph"]["privacy"], "private-ops")
        self.assertEqual(payload["graph"]["exclude_paths_count"], 4)
        self.assertIn(
            "mcp/server-memory/memory.jsonl",
            payload["graph"]["exclude_paths_summary"],
        )
        buckets = payload["policy_boundary"]
        self.assertGreaterEqual(buckets["durable_operational_rules"]["count"], 1)
        self.assertGreaterEqual(buckets["private_local_preferences"]["count"], 1)
        self.assertGreaterEqual(buckets["secrets_sensitive"]["count"], 1)
        self.assertGreaterEqual(payload["server_memory"]["entry_count"], 3)
        self.assertTrue(payload["leakage_checks"]["secrets_redacted"])
        self.assertTrue(payload["safety"]["no_agents_modification"])
        serialized = json.dumps(payload, sort_keys=True)
        self.assertNotIn("mcp-ops6-fake-token", serialized)
        self.assertNotIn("raw_payload", serialized)
        self.assertNotIn("observations", serialized)

    def test_agents_suggestions_are_public_safe_and_non_mutating(self):
        from repomap_kg.ops.policy_dogfood import (
            format_policy_dogfood_table,
            policy_dogfood_payload,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            repo_map_home, _ = write_policy_fixture(tmpdir)

            payload = policy_dogfood_payload(
                config_home=repo_map_home,
                graph_id="codex-vc",
            )
            table = format_policy_dogfood_table(payload)

        suggestions = payload["agents_refinement"]["suggested_rules"]
        self.assertTrue(any("server-memory" in item for item in suggestions))
        self.assertTrue(any("RepoMap graph evidence" in item for item in suggestions))
        self.assertTrue(payload["agents_refinement"]["applied"] is False)
        self.assertIn("policy_dogfood:", table)
        self.assertIn("agents_applied=false", table)
        self.assertNotIn("mcp-ops6-fake-token", table)

    def test_disabled_or_hidden_graph_does_not_read_private_root(self):
        from repomap_kg.ops.policy_dogfood import policy_dogfood_payload

        with tempfile.TemporaryDirectory() as tmpdir:
            repo_map_home, _ = write_policy_fixture(tmpdir)
            config_file = repo_map_home / "00-project.rp.toml"
            config_file.write_text(
                config_file.read_text(encoding="utf-8").replace(
                    "mcp_visible = true",
                    "mcp_visible = false",
                ),
                encoding="utf-8",
            )

            payload = policy_dogfood_payload(
                config_home=repo_map_home,
                graph_id="codex-vc",
            )

        self.assertFalse(payload["graph"]["mcp_visible"])
        self.assertEqual(payload["server_memory"]["entry_count"], 0)
        self.assertEqual(payload["diagnostics"][0]["code"], "graph-not-mcp-visible")
        self.assertTrue(payload["safety"]["no_graph_root_reads"])
        self.assertTrue(payload["safety"]["no_private_root_reads"])


if __name__ == "__main__":
    unittest.main()
