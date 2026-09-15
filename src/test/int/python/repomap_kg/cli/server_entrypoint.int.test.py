import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from repomap_test_support.cli_in_process import REPO_ROOT, module_environment
from repomap_test_support.cli_integration import (
    CliIntegrationTestCase,
    OPS_CONFIG_TEMPLATE,
)

from repomap_kg.ops.config_records import OpsPostgresStatus


class CliServerEntrypointIntegrationTests(CliIntegrationTestCase):
    def test_module_entrypoint_prints_version(self):
        result = self.run_cli("--version")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout.strip(), r"^repomap-kg \d+\.\d+\.\d+$")
        self.assertEqual(result.stderr, "")

    def test_module_entrypoint_can_run_in_process(self):
        exit_code, stdout, stderr = self.run_module_entrypoint("--version")

        self.assertEqual(exit_code, 0)
        self.assertRegex(stdout.strip(), r"^repomap-kg \d+\.\d+\.\d+$")
        self.assertEqual(stderr, "")

    def test_mcp_server_package_module_entrypoint_runs_jsonrpc(self):
        request = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize"}
        )
        result = subprocess.run(
            [sys.executable, "-m", "repomap_kg.server.mcp"],
            cwd=REPO_ROOT,
            env=module_environment(),
            input=f"{request}\n",
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        payload = json.loads(result.stdout)
        self.assertEqual(payload["id"], 1)
        self.assertEqual(payload["result"]["serverInfo"]["name"], "repomap-kg")

    def test_server_serve_http_health_and_status_are_bounded_and_private(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            (home).mkdir()
            (home / "repomap.rpl.toml").write_text(OPS_CONFIG_TEMPLATE, encoding="utf-8")
            port = self.local_server_test_port()
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "repomap_kg",
                    "server",
                    "serve",
                    "--repo-map-home",
                    str(home),
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                ],
                cwd=REPO_ROOT,
                env=module_environment(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                live = self.fetch_json_when_ready(
                    f"http://127.0.0.1:{port}/livez",
                    process,
                )
                health = self.fetch_json_when_ready(
                    f"http://127.0.0.1:{port}/healthz",
                    process,
                )
                status = self.fetch_json_when_ready(
                    f"http://127.0.0.1:{port}/status",
                    process,
                )
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)

        self.assertEqual(health["service"], "repomap")
        self.assertEqual(live["status"], "live")
        self.assertEqual(health["status"], "healthy")
        self.assertTrue(health["local_only"])
        self.assertEqual(status["graph_count"], 1)
        self.assertEqual(status["status"], "not_ready")
        self.assertEqual(status["checks"]["liveness"]["status"], "live")
        self.assertEqual(status["checks"]["configuration"]["status"], "healthy")
        self.assertEqual(status["checks"]["storage"]["status"], "not_ready")
        rendered = json.dumps(status, sort_keys=True)
        self.assertNotIn(str(home), rendered)
        self.assertNotIn("repo-map", rendered)
        self.assertNotIn("repository_name", rendered)
        self.assertNotIn("database", rendered)
        self.assertNotIn("diagnostics", rendered)
        self.assertFalse(status["safety"]["graph_roots_read"])
        self.assertFalse(status["safety"]["server_memory_read"])
        self.assertFalse(status["safety"]["destructive_db_actions"])

    def test_server_payload_helpers_are_read_only_in_process(self):
        from repomap_kg.server.http import (
            RepoMapLocalRequestHandler,
            build_health_payload,
            build_status_payload,
            serve_local_http,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            home.mkdir()
            (home / "repomap.rpl.toml").write_text(OPS_CONFIG_TEMPLATE, encoding="utf-8")

            health = build_health_payload(home)
            with patch(
                "repomap_kg.server.http.check_ops_postgres_status",
                return_value=OpsPostgresStatus(
                    db_checked=True,
                    connected=False,
                    schema_available=False,
                    required_tables={},
                ),
            ):
                status = build_status_payload(home)
            health_status, handled_health = self.call_local_server_handler(
                RepoMapLocalRequestHandler,
                "/healthz",
                home,
            )
            missing_status, missing = self.call_local_server_handler(
                RepoMapLocalRequestHandler,
                "/missing",
                home,
            )

            class FakeServer:
                def __init__(self, address, repo_map_home):
                    self.address = address
                    self.repo_map_home = repo_map_home

                def serve_forever(self):
                    raise KeyboardInterrupt

                def server_close(self):
                    return None

            with patch("repomap_kg.server.http.RepoMapLocalServer", FakeServer):
                serve_result = serve_local_http(
                    home,
                    host="0.0.0.0",
                    port=55880,
                    allow_container_internal=True,
                )

        self.assertEqual(health["status"], "healthy")
        self.assertEqual(status["status"], "not_ready")
        self.assertNotIn("graphs", status)
        self.assertNotIn("diagnostics", status)
        self.assertFalse(status["safety"]["graph_roots_read"])
        self.assertEqual(health_status, 200)
        self.assertEqual(handled_health["service"], "repomap")
        self.assertEqual(missing_status, 404)
        self.assertEqual(missing["status"], "not_found")
        self.assertEqual(serve_result, 0)

    def test_identity_command_emits_json_for_scripts_and_tests(self):
        exit_code, stdout, stderr = self.run_module_entrypoint("identity", "--json")

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout)
        self.assertEqual(payload["name"], "RepoMap")
        self.assertEqual(payload["cli"], "repomap-kg")
        self.assertEqual(payload["database"], "Postgres")
        self.assertEqual(stderr, "")
