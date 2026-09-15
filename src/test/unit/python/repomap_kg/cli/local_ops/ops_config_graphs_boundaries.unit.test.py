import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from repomap_kg.cli import main


class CliLocalOpsConfigGraphsBoundariesUnitTests(unittest.TestCase):
    def test_ops_config_check_reports_validation_errors_without_secret_leakage(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "repomap.local.toml"
            config_path.write_text(
                """\
[postgres]
password = "mcp-ops1-fake-password"
""",
                encoding="utf-8",
            )
            stderr = io.StringIO()

            with redirect_stderr(stderr):
                exit_code = main(
                    ["ops", "config-check", "--config", str(config_path), "--json"]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("schema_version is required", stderr.getvalue())
        self.assertNotIn("mcp-ops1-fake-password", stderr.getvalue())

    def test_ops_graphs_mixed_multi_source_registry_redacts_every_binding_root(self):
        public_root = "/synthetic/public-source"
        private_root = "/synthetic/private-source"
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "repomap.local.toml"
            config_path.write_text(
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
id = "mixed"
name = "Mixed Sources"
enabled = true
mcp_visible = true
refresh_policy = "manual"
database = "repomap_mixed"

[[graphs.source_bindings]]
schema_version = 1
source_definition_id = "src1:public"
alias = "public"
revision = 1
kind = "folder"
root_path = "{public_root}"
repository_name = "public-source"
logical_root = "public"
privacy = "public-dev"
evidence_retention = "metadata-only"
extractor_profile = "default"
resolution_policy = "isolated"
role = "composition"
input_name = "public-input"
enabled = true

[[graphs.source_bindings]]
schema_version = 1
source_definition_id = "src1:private"
alias = "private"
revision = 1
kind = "folder"
root_path = "{private_root}"
repository_name = "private-source"
logical_root = "private"
privacy = "private-ops"
evidence_retention = "metadata-only"
extractor_profile = "default"
resolution_policy = "isolated"
role = "security"
input_name = "private-input"
enabled = true

[server_memory]
enabled = false
path = "disabled"
mode = "read_only"
""",
                encoding="utf-8",
            )
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(
                    ["ops", "graphs", "--config", str(config_path), "--json"]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        graph = payload["graphs"][0]
        self.assertEqual(graph["id"], "mixed")
        self.assertEqual(graph["privacy"], "private-ops")
        bindings = {item["alias"]: item for item in graph["source_bindings"]}
        self.assertEqual(set(bindings), {"public", "private"})
        self.assertEqual(bindings["public"]["role"], "composition")
        self.assertEqual(bindings["private"]["role"], "security")
        for binding in bindings.values():
            self.assertEqual(binding["root_path"], "[private-root]")
            self.assertEqual(binding["root_path_expanded"], "[private-root]")
            self.assertTrue(binding["binding_id"].startswith("bind1:"))

        rendered = stdout.getvalue()
        self.assertNotIn(public_root, rendered)
        self.assertNotIn(private_root, rendered)


if __name__ == "__main__":
    unittest.main()
