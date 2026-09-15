import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from repomap_kg.cli import main
from repomap_kg.ops.config import OpsGraphStorageStatus


class CliLocalOpsConfigGraphsUnitTests(unittest.TestCase):
    def test_ops_config_check_prints_redacted_json_without_db_check(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "repomap.local.toml"
            config_path.write_text(
                """\
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
password = "mcp-ops1-fake-password"

[[graphs]]
id = "repo-map"
name = "RepoMap"
root_path = "/placeholder/repo-map"
repository_name = "repo-map"
database = "repomap_repo_map"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"

[server_memory]
enabled = false
path = "~/.codex/codex-vc/mcp/server-memory"
mode = "read_only"
""",
                encoding="utf-8",
            )
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(
                    ["ops", "config-check", "--config", str(config_path), "--json"]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["valid"])
        self.assertFalse(payload["postgres_status"]["db_checked"])
        self.assertEqual(payload["postgres"]["password"], "[REDACTED]")
        self.assertEqual(payload["config_path"], "[local-config]")
        self.assertEqual(payload["server_memory"]["path"], "[private-path]")
        self.assertEqual(payload["server_memory"]["path_expanded"], "[private-path]")
        self.assertNotIn(str(config_path), stdout.getvalue())
        self.assertNotIn("~/.codex/codex-vc", stdout.getvalue())
        self.assertNotIn("mcp-ops1-fake-password", stdout.getvalue())

    def test_ops_config_check_text_output_stays_local_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "repomap.local.toml"
            config_path.write_text(
                """\
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
id = "repo-map"
name = "RepoMap"
root_path = "/placeholder/repo-map"
repository_name = "repo-map"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"

[server_memory]
enabled = false
path = "~/.codex/codex-vc/mcp/server-memory"
mode = "read_only"
""",
                encoding="utf-8",
            )
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(["ops", "config-check", "--config", str(config_path)])

        self.assertEqual(exit_code, 0)
        self.assertIn("RepoMap ops config status", stdout.getvalue())
        self.assertIn("local_only=true", stdout.getvalue())
        self.assertIn("no_public_tunnel=true", stdout.getvalue())
        self.assertIn("no_destructive_operations=true", stdout.getvalue())

    def test_ops_config_check_can_run_explicit_read_only_db_probe(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "repomap.local.toml"
            config_path.write_text(
                """\
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
id = "repo-map"
name = "RepoMap"
root_path = "/placeholder/repo-map"
repository_name = "repo-map"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"

[server_memory]
enabled = false
path = "~/.codex/codex-vc/mcp/server-memory"
mode = "read_only"
""",
                encoding="utf-8",
            )
            stdout = io.StringIO()

            with patch("repomap_kg.cli.check_ops_postgres_status") as check_db:
                check_db.return_value.to_jsonable.return_value = {
                    "db_checked": True,
                    "connected": True,
                    "schema_available": True,
                    "required_tables": {"repositories": True},
                    "error": None,
                }
                with redirect_stdout(stdout):
                    exit_code = main(
                        [
                            "ops",
                            "config-check",
                            "--config",
                            str(config_path),
                            "--check-db",
                            "--json",
                        ]
                    )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["postgres_status"]["db_checked"])
        check_db.assert_called_once()

    def test_ops_graphs_prints_registry_json_without_db_check(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "repomap.local.toml"
            config_path.write_text(
                """\
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
password = "mcp-ops2-fake-password"

[[graphs]]
id = "repo-map"
name = "RepoMap"
root_path = "/placeholder/repo-map"
repository_name = "repo-map"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"

[[graphs]]
id = "codex-vc"
name = "Codex VC"
root_path = "~/.codex/codex-vc"
repository_name = "codex-vc"
database = "repomap_codex_vc"
privacy = "private-ops"
enabled = false
mcp_visible = false
extractor_profile = "private-ops"
refresh_policy = "watch"

[server_memory]
enabled = false
path = "~/.codex/codex-vc/mcp/server-memory"
mode = "read_only"
""",
                encoding="utf-8",
            )
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(["ops", "graphs", "--config", str(config_path), "--json"])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["graph_count"], 2)
        self.assertEqual(payload["enabled_graph_count"], 1)
        self.assertEqual(payload["mcp_visible_graph_count"], 1)
        self.assertEqual(payload["private_graph_count"], 1)
        self.assertFalse(payload["db_checked"])
        self.assertTrue(payload["security"]["private_roots_read"] is False)
        self.assertEqual(payload["graphs"][1]["refresh_policy_status"], "deferred")
        self.assertIsNone(payload["graphs"][0]["storage_status"])
        self.assertEqual(payload["config_path"], "[local-config]")
        self.assertEqual(payload["graphs"][1]["database"], "[private-database]")
        self.assertEqual(payload["graphs"][1]["root_path_display"], "[private-root]")
        self.assertEqual(payload["graphs"][1]["root_path_expanded"], "[private-root]")
        self.assertNotIn(str(config_path), stdout.getvalue())
        self.assertNotIn("~/.codex/codex-vc", stdout.getvalue())
        self.assertNotIn("mcp-ops2-fake-password", stdout.getvalue())

    def test_ops_graphs_text_output_lists_graphs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "repomap.local.toml"
            config_path.write_text(
                """\
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
id = "repo-map"
name = "RepoMap"
root_path = "/placeholder/repo-map"
repository_name = "repo-map"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"

[server_memory]
enabled = false
path = "~/.codex/codex-vc/mcp/server-memory"
mode = "read_only"
""",
                encoding="utf-8",
            )
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(["ops", "graphs", "--config", str(config_path)])

        self.assertEqual(exit_code, 0)
        self.assertIn("RepoMap ops graph registry", stdout.getvalue())
        self.assertIn(
            "repo-map | repo-map | repomap | public-dev | true | true",
            stdout.getvalue(),
        )
        self.assertIn("private_roots_read=false", stdout.getvalue())

    def test_ops_graphs_can_run_explicit_read_only_db_status(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "repomap.local.toml"
            config_path.write_text(
                """\
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
id = "repo-map"
name = "RepoMap"
root_path = "/placeholder/repo-map"
repository_name = "repo-map"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"

[server_memory]
enabled = false
path = "~/.codex/codex-vc/mcp/server-memory"
mode = "read_only"
""",
                encoding="utf-8",
            )
            stdout = io.StringIO()

            with patch("repomap_kg.cli.check_ops_graph_storage_status") as check_db:
                check_db.return_value = {
                    "repo-map": OpsGraphStorageStatus(
                        db_checked=True,
                        repository_name="repo-map",
                        schema_available=True,
                        repository_exists=True,
                        raw_observations=7,
                        canonical_nodes=5,
                        canonical_edges=3,
                    )
                }
                with redirect_stdout(stdout):
                    exit_code = main(
                        [
                            "ops",
                            "graphs",
                            "--config",
                            str(config_path),
                            "--check-db",
                            "--json",
                        ]
                    )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["db_checked"])
        self.assertEqual(payload["graphs"][0]["storage_status"]["raw_observations"], 7)
        self.assertEqual(payload["graphs"][0]["storage_status"]["canonical_nodes"], 5)
        self.assertEqual(payload["graphs"][0]["storage_status"]["canonical_edges"], 3)
        check_db.assert_called_once()


if __name__ == "__main__":
    unittest.main()
