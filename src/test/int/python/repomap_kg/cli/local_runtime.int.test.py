import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from repomap_test_support.cli_integration import (
    CliIntegrationTestCase,
    OPS_CONFIG_TEMPLATE,
)

from repomap_kg.runtime.local import LocalRuntimeIdentity


class CliLocalRuntimeIntegrationTests(CliIntegrationTestCase):
    def test_local_setup_creates_runtime_files_under_temp_repo_map_home(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"

            exit_code, stdout, stderr = self.run_module_entrypoint(
                "local", "setup", "--repo-map-home", str(home), "--json",
            )

        self.assertEqual(exit_code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["command"], "setup")
        self.assertEqual(payload["result"], "success")
        self.assertTrue(payload["runtime"]["runtime_files_rendered"])
        self.assertFalse(payload["runtime"]["containers_started"])
        self.assertFalse(payload["runtime"]["direct_db_host_port_enabled"])
        self.assertFalse(payload["runtime"]["postgres_host_port_published"])
        self.assertFalse(payload["dbeaver"]["enabled"])
        self.assertIn("Direct DB access disabled", payload["dbeaver"]["message"])
        self.assertNotIn("POSTGRES_PASSWORD=", stdout)
        self.assertNotIn("admin/admin", stdout)
        self.assertEqual(stderr, "")

    def test_local_setup_dry_run_does_not_create_repo_map_home(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"

            exit_code, stdout, stderr = self.run_module_entrypoint(
                "local", "setup", "--repo-map-home", str(home), "--dry-run", "--json",
            )

            self.assertFalse(home.exists())

        self.assertEqual(exit_code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["result"], "dry_run")
        self.assertEqual(payload["created_file_count"], 0)
        self.assertNotIn("created_files", payload)
        self.assertIn("setup-dry-run", [item["code"] for item in payload["diagnostics"]])
        self.assertEqual(stderr, "")

    def test_local_setup_reuses_existing_config_and_env_without_leaking_secret(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            runtime = home / "runtime"
            runtime.mkdir(parents=True)
            (home / "repomap.rpl.toml").write_text(OPS_CONFIG_TEMPLATE, encoding="utf-8")
            (runtime / ".env").write_text(
                "POSTGRES_PASSWORD=fake-existing-secret\n"
                "REPOMAP_PG_PASSWORD=fake-existing-secret\n",
                encoding="utf-8",
            )

            exit_code, stdout, stderr = self.run_module_entrypoint(
                "local", "setup", "--repo-map-home", str(home), "--json",
            )

        self.assertEqual(exit_code, 0, stderr)
        payload = json.loads(stdout)
        codes = [item["code"] for item in payload["diagnostics"]]
        self.assertIn("config-exists", codes)
        self.assertIn("env-role-secrets-added", codes)
        self.assertNotIn("fake-existing-secret", stdout)
        self.assertTrue(payload["runtime"]["runtime_files_rendered"])
        self.assertEqual(stderr, "")

    def test_local_setup_table_output_is_redacted_and_local_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"

            exit_code, stdout, stderr = self.run_module_entrypoint(
                "local", "setup", "--repo-map-home", str(home),
            )

        self.assertEqual(exit_code, 0, stderr)
        self.assertIn("RepoMap local runtime setup", stdout)
        self.assertIn("direct_db=disabled", stdout)
        self.assertIn("server=127.0.0.1:55880", stdout)
        self.assertIn("Direct DB access disabled", stdout)
        self.assertNotIn("password=[REDACTED: see runtime/.env]", stdout)
        self.assertIn("graph_roots_read=false", stdout)
        self.assertIn("server_memory_read=false", stdout)
        self.assertIn("destructive_db_actions=false", stdout)
        self.assertNotIn("POSTGRES_PASSWORD=", stdout)
        self.assertEqual(stderr, "")

    def test_local_up_and_down_dry_run_do_not_start_or_delete_containers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_exit, _setup_stdout, setup_stderr = self.run_module_entrypoint(
                "local", "setup", "--repo-map-home", str(home), "--json",
            )
            self.assertEqual(setup_exit, 0, setup_stderr)
            self.write_runtime_server_port(home, self.local_runtime_test_port(1))

            up_exit, up_stdout, up_stderr = self.run_module_entrypoint(
                "local", "up", "--repo-map-home", str(home), "--dry-run", "--json",
            )
            down_exit, down_stdout, down_stderr = self.run_module_entrypoint(
                "local", "down", "--repo-map-home", str(home), "--dry-run", "--json",
            )

        self.assertEqual(up_exit, 0, up_stderr)
        up_payload = json.loads(up_stdout)
        self.assertEqual(up_payload["result"], "dry_run")
        self.assertNotIn("planned_command", up_payload)
        self.assertNotIn("docker compose", up_stdout)
        self.assertFalse(up_payload["runtime"]["direct_db_host_port_enabled"])
        self.assertFalse(up_payload["runtime"]["postgres_host_port_published"])
        self.assertFalse(up_payload["dbeaver"]["enabled"])
        self.assertFalse(up_payload["source_trees_mutated"])
        self.assertFalse(up_payload["graph_roots_read"])
        self.assertEqual(down_exit, 0, down_stderr)
        down_payload = json.loads(down_stdout)
        self.assertEqual(down_payload["result"], "dry_run")
        self.assertFalse(down_payload["persistent_volume_deleted"])
        self.assertNotIn("planned_command", down_payload)

    def test_local_up_non_dry_run_invokes_repo_map_owned_compose(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_exit, _setup_stdout, setup_stderr = self.run_module_entrypoint(
                "local",
                "setup",
                "--repo-map-home",
                str(home),
                "--json",
            )
            self.assertEqual(setup_exit, 0, setup_stderr)
            self.write_runtime_server_port(home, self.local_runtime_test_port(2))

            with (
                patch("repomap_kg.runtime.local.shutil.which", return_value="/usr/bin/docker"),
                patch("repomap_kg.runtime.local.subprocess.run") as run_mock,
            ):
                exit_code, stdout, stderr = self.run_repo_map_in_process(
                    "local", "up", "--repo-map-home", str(home), "--json",
                )

        self.assertEqual(exit_code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["result"], "started")
        self.assertTrue(payload["container_runtime_checked"])
        self.assertTrue(payload["container_runtime_available"])
        self.assertFalse(payload["graph_roots_read"])
        self.assertFalse(payload["server_memory_read"])
        self.assertNotIn("planned_command", payload)
        command = run_mock.call_args.args[0]
        self.assertIn("compose", command)
        self.assertIn("--project-name", command)
        self.assertNotIn("psql", command)

    def test_local_down_non_dry_run_preserves_persistent_volume(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_exit, _setup_stdout, setup_stderr = self.run_module_entrypoint(
                "local", "setup", "--repo-map-home", str(home), "--json",
            )
            self.assertEqual(setup_exit, 0, setup_stderr)

            with (
                patch("repomap_kg.runtime.local.shutil.which", return_value="/usr/bin/docker"),
                patch("repomap_kg.runtime.local.subprocess.run") as run_mock,
            ):
                exit_code, stdout, stderr = self.run_repo_map_in_process(
                    "local", "down", "--repo-map-home", str(home), "--json",
                )

        self.assertEqual(exit_code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["result"], "stopped")
        self.assertFalse(payload["persistent_volume_deleted"])
        self.assertNotIn("planned_command", payload)
        command = run_mock.call_args.args[0]
        self.assertIn("down", command)
        self.assertNotIn("-v", command)

    def test_local_status_reports_not_running_without_reading_private_roots(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_exit, _setup_stdout, setup_stderr = self.run_module_entrypoint(
                "local", "setup", "--repo-map-home", str(home), "--json",
            )
            self.assertEqual(setup_exit, 0, setup_stderr)

            exit_code, stdout, stderr = self.run_module_entrypoint(
                "local", "status", "--repo-map-home", str(home), "--json",
            )

        self.assertEqual(exit_code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["command"], "status")
        self.assertFalse(payload["graph_roots_read"])
        self.assertFalse(payload["server_memory_read"])
        self.assertFalse(payload["dbeaver"]["enabled"])
        self.assertIn("Direct DB access disabled", payload["dbeaver"]["message"])
        self.assertNotIn("host", payload["dbeaver"])
        self.assertNotIn("password", payload["dbeaver"])

    def test_local_status_check_containers_reports_owned_server_health_in_process(self):
        from repomap_kg.runtime.local import query_local_runtime_status

        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_exit, _setup_stdout, setup_stderr = self.run_module_entrypoint(
                "local", "setup", "--repo-map-home", str(home), "--json",
            )
            self.assertEqual(setup_exit, 0, setup_stderr)
            home_hash = LocalRuntimeIdentity.from_home(home).home_hash

            class FakeResponse:
                def __enter__(self): return self
                def __exit__(self, exc_type, exc, tb): return False
                def read(self): return b'{"status":"ok","service":"repomap"}'

            def fake_run(command, **kwargs):
                if command[:2] == ["docker", "inspect"]:
                    component = "server" if "server" in command[-1] else "postgres"
                    labels = {"org.repomap.runtime": "true", "org.repomap.home_hash": home_hash, "org.repomap.component": component}
                    inspect_body = json.dumps([{"Config": {"Labels": labels}, "State": {"Status": "running", "ExitCode": 0, "Health": {"Status": "healthy"}}}])
                    return type("Completed", (), {"returncode": 0, "stdout": inspect_body, "stderr": ""})()
                raise AssertionError(command)

            with (
                patch("repomap_kg.runtime.local.shutil.which", return_value="/usr/bin/docker"),
                patch("repomap_kg.runtime.local.subprocess.run", side_effect=fake_run),
                patch("repomap_kg.runtime.local.urllib.request.urlopen", return_value=FakeResponse()),
            ):
                status = query_local_runtime_status(home, check_containers=True)

        payload = status.to_jsonable()
        self.assertEqual(payload["result"], "running")
        self.assertEqual(payload["containers"]["server"]["status"], "running")
        self.assertEqual(payload["containers"]["postgres"]["status"], "running")
        self.assertEqual(payload["server_health"]["status"], "ok")
        self.assertTrue(payload["runtime"]["containers_started"])
        self.assertFalse(payload["graph_roots_read"])
        self.assertFalse(payload["server_memory_read"])

    def test_local_up_dry_run_reflects_direct_db_debug_toggle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_exit, _setup_stdout, setup_stderr = self.run_module_entrypoint(
                "local", "setup", "--repo-map-home", str(home), "--json",
            )
            self.assertEqual(setup_exit, 0, setup_stderr)
            self.write_runtime_server_port(home, self.local_runtime_test_port(3))
            config_path = home / "repomap.rpl.toml"
            config_path.write_text(
                config_path.read_text(encoding="utf-8").replace(
                    "direct_host_port_enabled = false",
                    "direct_host_port_enabled = true",
                ),
                encoding="utf-8",
            )

            with patch(
                "repomap_kg.runtime.local.is_local_port_open",
                return_value=False,
            ):
                up_exit, up_stdout, up_stderr = self.run_repo_map_in_process(
                    "local", "up", "--repo-map-home", str(home), "--dry-run", "--json",
                )

            self.assertEqual(up_exit, 0, up_stderr)
            payload = json.loads(up_stdout)
            self.assertTrue(payload["runtime"]["direct_db_host_port_enabled"])
            self.assertTrue(payload["runtime"]["postgres_host_port_published"])
            self.assertTrue(payload["dbeaver"]["enabled"])
            self.assertEqual(payload["dbeaver"]["host"], "127.0.0.1")
            self.assertEqual(payload["dbeaver"]["port"], 55432)
            self.assertEqual(payload["dbeaver"]["password"], "[REDACTED: see runtime/.env]")
            compose_text = (home / "runtime" / "compose.yaml").read_text(encoding="utf-8")
            self.assertIn("127.0.0.1:55432:5432", compose_text)
        self.assertEqual(up_stderr, "")

    def test_local_status_check_containers_reports_missing_runtime_safely(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_exit, _setup_stdout, setup_stderr = self.run_module_entrypoint(
                "local", "setup", "--repo-map-home", str(home), "--json",
            )
            self.assertEqual(setup_exit, 0, setup_stderr)

            with patch("repomap_kg.runtime.local.shutil.which", return_value=None):
                exit_code, stdout, stderr = self.run_repo_map_in_process(
                    "local", "status", "--repo-map-home", str(home), "--check-containers", "--json",
                )

        self.assertEqual(exit_code, 0, stderr)
        payload = json.loads(stdout)
        self.assertTrue(payload["container_runtime_checked"])
        self.assertFalse(payload["container_runtime_available"])
        self.assertIn(
            "container-runtime-unavailable",
            [item["code"] for item in payload["diagnostics"]],
        )
        self.assertNotIn("POSTGRES_PASSWORD=", stdout)
        self.assertEqual(stderr, "")

    def test_local_status_before_setup_reports_missing_runtime_files_without_creating_home(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"

            exit_code, stdout, stderr = self.run_module_entrypoint(
                "local", "status", "--repo-map-home", str(home), "--json",
            )

            self.assertFalse(home.exists())

        self.assertEqual(exit_code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["result"], "not_running")
        self.assertIn(
            "runtime-files-missing",
            [item["code"] for item in payload["diagnostics"]],
        )
        self.assertFalse(payload["runtime"]["runtime_files_rendered"])
        self.assertFalse(payload["graph_roots_read"])
        self.assertEqual(stderr, "")

    def test_local_up_reports_missing_runtime_files_without_starting_containers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_exit, _setup_stdout, setup_stderr = self.run_module_entrypoint(
                "local", "setup", "--repo-map-home", str(home), "--json",
            )
            self.assertEqual(setup_exit, 0, setup_stderr)
            (home / "runtime" / "compose.yaml").unlink()

            exit_code, stdout, stderr = self.run_module_entrypoint(
                "local", "up", "--repo-map-home", str(home), "--dry-run", "--json",
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("runtime file is missing", stderr)
        self.assertNotIn("docker compose", stderr)

    def test_local_up_reports_port_conflict_before_container_start(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_exit, _setup_stdout, setup_stderr = self.run_module_entrypoint(
                "local", "setup", "--repo-map-home", str(home), "--json",
            )
            self.assertEqual(setup_exit, 0, setup_stderr)

            with patch("repomap_kg.runtime.local.is_local_port_open", return_value=True):
                exit_code, stdout, stderr = self.run_repo_map_in_process(
                    "local", "up", "--repo-map-home", str(home), "--dry-run", "--json",
                )

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("host port 55880 is already accepting local connections", stderr)
        self.assertNotIn("host port 55432 is already accepting local connections", stderr)
        self.assertNotIn("docker compose", stderr)

    def test_local_up_rejects_invalid_public_bind_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_exit, _setup_stdout, setup_stderr = self.run_module_entrypoint(
                "local", "setup", "--repo-map-home", str(home), "--json",
            )
            self.assertEqual(setup_exit, 0, setup_stderr)
            config_path = home / "repomap.rpl.toml"
            config_path.write_text(config_path.read_text(encoding="utf-8").replace('bind_host = "127.0.0.1"', 'bind_host = "0.0.0.0"'), encoding="utf-8")

            exit_code, stdout, stderr = self.run_module_entrypoint(
                "local", "up", "--repo-map-home", str(home), "--dry-run", "--json",
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("bind_host", stderr)
        self.assertIn("localhost-only", stderr)
        self.assertNotIn("docker compose", stderr)
