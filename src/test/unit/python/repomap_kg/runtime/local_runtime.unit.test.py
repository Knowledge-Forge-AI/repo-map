import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from repomap_kg.runtime.local import (
    DEFAULT_POSTGRES_HOST_PORT, DEFAULT_SERVER_HOST_PORT, ENV_RUNTIME_SOURCE_ROOT,
    LocalRuntimeError, LocalRuntimeIdentity, down_local_runtime, format_local_runtime_table,
    render_server_dockerfile, resolve_runtime_source_root, setup_local_runtime,
    up_local_runtime, query_local_runtime_status,
)
from repomap_kg.runtime.plan import LocalContainerStatus, is_runtime_source_root


class _FakeHttpResponse:
    def __enter__(self): return self
    def __exit__(self, exc_type, exc, tb): return False
    def read(self): return b"{\"status\":\"ok\",\"service\":\"repomap\"}"


def _fake_docker_inspect(home_hash: str, server_component: str = "http"):
    def fake_run(command, **kwargs):
        if command[:3] == ["docker", "ps", "-aq"]:
            return type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        if command[:2] == ["docker", "inspect"]:
            name = command[-1]
            component = server_component if "server" in name else "postgres"
            data = [{
                "Name": f"/{name}",
                "Config": {"Labels": {"org.repomap.runtime": "true", "org.repomap.home_hash": home_hash, "org.repomap.component": component}},
                "State": {"Status": "running", "ExitCode": 0, "Health": {"Status": "healthy"}}, "NetworkSettings": {"Ports": {"5432/tcp": None}},
            }]
            return type("Completed", (), {"returncode": 0, "stdout": json.dumps(data), "stderr": ""})()
        raise AssertionError(command)
    return fake_run


class LocalRuntimeUnitTests(unittest.TestCase):
    def test_live_ops5_local_runtime_json_omits_low_level_commands_and_private_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)
            self.write_runtime_server_port(home, 55981)
            result = up_local_runtime(home, dry_run=True)
            payload = result.to_jsonable()
            rendered = json.dumps(payload, sort_keys=True)
            self.assertEqual((payload["command"], payload["result"]), ("up", "dry_run"))
            self.assertIn("home_hash", payload.get("runtime", {}))
            for token in ("repo_map_home", "created_files", "planned_command"):
                self.assertNotIn(token, payload)
            for token in (str(home), "docker compose", "pg_dump", "pg_restore", "psql", "POSTGRES_PASSWORD", "PGPASSWORD"):
                self.assertNotIn(token, rendered)

    def test_ref5_local_runtime_facade_reexports_split_helpers(self):
        from repomap_kg import local_runtime as facade
        from repomap_kg.runtime import commands as cmds, plan
        for name, target in (
            ("LocalRuntimePlan", plan.LocalRuntimePlan), ("LocalRuntimeIdentity", plan.LocalRuntimeIdentity),
            ("build_local_runtime_plan", plan.build_local_runtime_plan), ("render_server_dockerfile", cmds.render_server_dockerfile),
            ("format_local_runtime_table", cmds.format_local_runtime_table),
        ):
            self.assertIs(getattr(facade, name), target)

    def test_setup_creates_runtime_files_only_inside_repo_map_home(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            result = setup_local_runtime(home)
            payload = result.to_jsonable()
            self.assertEqual(payload["command"], "setup")
            self.assertEqual(payload["result"], "success")
            for f in ("repomap.rpl.toml", "runtime/.env", "runtime/compose.yaml", "runtime/repomap-server.Dockerfile"):
                self.assertTrue((home / f).is_file())
            self.assertTrue((home / "logs").is_dir() and (home / "status").is_dir())
            env_text = (home / "runtime" / ".env").read_text(encoding="utf-8")
            for secret in ("REPOMAP_PG_PASSWORD=", "PGPASSWORD=", "REPOMAP_READ_STATUS_PASSWORD=",
                           "REPOMAP_REFRESH_PUBLICATION_PASSWORD=", "REPOMAP_COORDINATOR_CONTROL_PASSWORD="):
                self.assertIn(secret, env_text)
            self.assertEqual(payload["runtime"]["postgres_host_port"], DEFAULT_POSTGRES_HOST_PORT)
            self.assertEqual(payload["runtime"]["server_host_port"], DEFAULT_SERVER_HOST_PORT)
            for f in ("direct_db_host_port_enabled", "postgres_host_port_published", "containers_started"):
                self.assertFalse(payload["runtime"][f])
            config_text = (home / "repomap.rpl.toml").read_text(encoding="utf-8")
            for token in ("[runtime.postgres]", "direct_host_port_enabled = false"):
                self.assertIn(token, config_text)
            compose_text = (home / "runtime" / "compose.yaml").read_text(encoding="utf-8")
            self.assertNotIn(f"127.0.0.1:{DEFAULT_POSTGRES_HOST_PORT}:5432", compose_text)
            self.assertIn("REPOMAP_PG_PASSWORD: ${REPOMAP_READ_STATUS_PASSWORD}", compose_text)
            for token in ("POSTGRES_PASSWORD=", "PGPASSWORD="):
                self.assertNotIn(token, json.dumps(payload))

    def test_server_dockerfile_installs_declared_project_dependencies(self):
        dockerfile = render_server_dockerfile()
        for token in ("COPY pyproject.toml README.md ./", "COPY src/main/python ./src/main/python",
                      "COPY src/main/resources ./src/main/resources", '--no-build-isolation ".[postgres]"',
                      'ENTRYPOINT ["python", "-m", "repomap_kg"]', 'CMD ["server", "serve"',
                      "REPOMAP_PACKAGED_PSQL=/usr/lib/postgresql/16/bin/psql"):
            self.assertIn(token, dockerfile)
        for token in ("postgresql-client", 'CMD ["mcp", "serve"'): self.assertNotIn(token, dockerfile)

    def test_generated_runtime_uses_long_running_server_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)
            compose_text = (home / "runtime" / "compose.yaml").read_text(encoding="utf-8")
            for token in ('command: ["server", "serve"', '"--repo-map-home", "/repo-map-home"',
                          '"--port", "55880"', '"--container-internal-bind"', "127.0.0.1:55880:55880",
                          "healthcheck:", "http://127.0.0.1:55880/readyz", 'command: ["mcp", "serve"',
                          'profiles: ["integration"]', 'command: ["ops", "coordinator-serve"'):
                self.assertIn(token, compose_text)

    def test_compose_build_context_can_use_explicit_source_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_root = Path(tmpdir) / "source"
            for d in ("src/main/python/repomap_kg", "src/main/resources"): (source_root / d).mkdir(parents=True)
            (source_root / "src/main/python/repomap_kg/__main__.py").write_text("", encoding="utf-8")
            (source_root / "pyproject.toml").write_text("[build-system]\n", encoding="utf-8")
            (source_root / "README.md").write_text("# fixture\n", encoding="utf-8")
            home = Path(tmpdir) / "repo-map-home"
            with patch.dict("os.environ", {ENV_RUNTIME_SOURCE_ROOT: str(source_root)}):
                result = setup_local_runtime(home)
            compose_text = (home / "runtime" / "compose.yaml").read_text(encoding="utf-8")
            self.assertEqual(resolve_runtime_source_root(source_root), source_root.resolve())
            self.assertIn(f'context: "{source_root}"', compose_text)
            self.assertNotIn("/nix/store", compose_text)
            self.assertEqual(result.to_jsonable()["result"], "success")

    def test_runtime_source_root_requires_package_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_root = Path(tmpdir) / "source"
            for d in ("src/main/python/repomap_kg", "src/main/resources"): (source_root / d).mkdir(parents=True)
            (source_root / "src/main/python/repomap_kg/__main__.py").write_text("", encoding="utf-8")
            self.assertFalse(is_runtime_source_root(source_root))
            (source_root / "pyproject.toml").write_text("[build-system]\n", encoding="utf-8")
            self.assertFalse(is_runtime_source_root(source_root))
            (source_root / "README.md").write_text("# fixture\n", encoding="utf-8")
            self.assertTrue(is_runtime_source_root(source_root))

    def test_setup_dry_run_does_not_create_repo_map_home(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            result = setup_local_runtime(home, dry_run=True)
            payload = result.to_jsonable()
            self.assertEqual(payload["result"], "dry_run")
            self.assertFalse(home.exists())
            self.assertEqual((payload["created_file_count"], result.created_files), (0, ()))
            self.assertIn("setup-dry-run", [item["code"] for item in payload["diagnostics"]])

    def test_setup_does_not_overwrite_existing_config_or_secret(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            runtime = home / "runtime"
            home.mkdir(mode=0o700)
            runtime.mkdir(mode=0o700)
            config, env_file = home / "repomap.rpl.toml", runtime / ".env"
            config.write_text("schema_version = 1\n# keep me\n", encoding="utf-8")
            env_file.write_text("POSTGRES_PASSWORD=keep-existing\n", encoding="utf-8")
            env_file.chmod(0o600)
            result = setup_local_runtime(home)
            payload = result.to_jsonable()
            for f in (config, env_file): self.assertNotIn(f, result.created_files)
            self.assertEqual(config.read_text(encoding="utf-8"), "schema_version = 1\n# keep me\n")
            env_text = env_file.read_text(encoding="utf-8")
            for secret in ("POSTGRES_PASSWORD=keep-existing\n", "REPOMAP_READ_STATUS_PASSWORD=",
                           "REPOMAP_REFRESH_PUBLICATION_PASSWORD=", "REPOMAP_COORDINATOR_CONTROL_PASSWORD="):
                self.assertIn(secret, env_text)
            for code in ("config-exists", "env-role-secrets-added"):
                self.assertIn(code, [item["code"] for item in payload["diagnostics"]])
            self.assertNotIn("keep-existing", json.dumps(payload))

    def test_status_reports_not_running_without_invoking_container_runtime(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)
            status = query_local_runtime_status(home, check_containers=False)
            payload = status.to_jsonable()
            self.assertEqual(payload["command"], "status")
            self.assertEqual(payload["result"], "not_running")
            self.assertFalse(payload["container_runtime_checked"])
            self.assertFalse(payload["graph_roots_read"] or payload["server_memory_read"])
            self.assertFalse(payload["dbeaver"]["enabled"])
            self.assertIn("Direct DB access disabled", payload["dbeaver"]["message"])
            for key in ("host", "port"): self.assertNotIn(key, payload["dbeaver"])

    def test_status_can_report_unavailable_container_runtime_without_failing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)
            with patch("repomap_kg.runtime.local.shutil.which", return_value=None):
                status = query_local_runtime_status(home, check_containers=True)
        payload = status.to_jsonable()
        self.assertEqual(payload["result"], "not_running")
        self.assertTrue(payload["container_runtime_checked"])
        self.assertFalse(payload["container_runtime_available"])
        self.assertIn("container-runtime-unavailable", [item["code"] for item in payload["diagnostics"]])

    def test_status_check_containers_reports_server_health(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)
            home_hash = LocalRuntimeIdentity.from_home(home).home_hash
            with (
                patch("repomap_kg.runtime.local.shutil.which", return_value="/usr/bin/docker"),
                patch("repomap_kg.runtime.local.subprocess.run", side_effect=_fake_docker_inspect(home_hash)),
                patch("repomap_kg.runtime.local.urllib.request.urlopen", return_value=_FakeHttpResponse()),
            ):
                status = query_local_runtime_status(home, check_containers=True)
        payload = status.to_jsonable()
        self.assertEqual(payload["result"], "running")
        for name in ("server", "postgres"):
            self.assertEqual(payload["containers"][name]["status"], "running")
        self.assertEqual(payload["server_health"]["status"], "ok")
        self.assertTrue(payload["server_health"]["checked"])
        self.assertTrue(payload["runtime"]["containers_started"])
        self.assertFalse(payload["graph_roots_read"] or payload["server_memory_read"])

    def test_rendered_compose_server_labels_are_accepted_by_status(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)
            server = (home / "runtime/compose.yaml").read_text().split("\n  http:\n", 1)[1].split("\n  mcp:\n", 1)[0]
            labels = dict(line.strip().split(":", 1) for line in server.split("    labels:\n", 1)[1].splitlines())
            inspect = _fake_docker_inspect(labels["org.repomap.home_hash"].strip().strip('"'), labels["org.repomap.component"].strip().strip('"'))
            with (
                patch("repomap_kg.runtime.local.shutil.which", return_value="/usr/bin/docker"),
                patch("repomap_kg.runtime.local.subprocess.run", side_effect=inspect),
                patch("repomap_kg.runtime.local.urllib.request.urlopen", return_value=_FakeHttpResponse()),
            ):
                status = query_local_runtime_status(home, check_containers=True)
            self.assertEqual(status.to_jsonable()["result"], "running")

    def test_status_table_includes_container_and_server_health(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)
            home_hash = LocalRuntimeIdentity.from_home(home).home_hash
            with (
                patch("repomap_kg.runtime.local.shutil.which", return_value="/usr/bin/docker"),
                patch("repomap_kg.runtime.local.subprocess.run", side_effect=_fake_docker_inspect(home_hash)),
                patch("repomap_kg.runtime.local.urllib.request.urlopen", return_value=_FakeHttpResponse()),
            ):
                table = format_local_runtime_table(query_local_runtime_status(home, check_containers=True))
        for token in ("container: component=server status=running owned=true",
                      "container: component=postgres status=running owned=true",
                      "server_health: status=ok reachable=true"):
            self.assertIn(token, table)

    def test_status_rejects_wrong_home_or_service_labels(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)
            home_hash = LocalRuntimeIdentity.from_home(home).home_hash
            for observed_home, service in (("unrelated", "http"), (home_hash, "coordinator")):
                with (
                    self.subTest(home_matches=observed_home == home_hash, service=service),
                    patch("repomap_kg.runtime.local.shutil.which", return_value="/usr/bin/docker"),
                    patch("repomap_kg.runtime.local.subprocess.run", side_effect=_fake_docker_inspect(observed_home, service)),
                    patch("repomap_kg.runtime.local.urllib.request.urlopen", return_value=_FakeHttpResponse()),
                ):
                    status = query_local_runtime_status(home, check_containers=True)
                    self.assertEqual(status.result, "not_running")
                    assert status.containers is not None
                    self.assertFalse(status.containers["server"].owned)

    def test_up_dry_run_renders_compose_command_without_starting_containers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)
            self.write_runtime_server_port(home, 55981)
            result = up_local_runtime(home, dry_run=True)
        payload = result.to_jsonable()
        self.assertEqual((payload["command"], payload["result"]), ("up", "dry_run"))
        for token in ("compose", "up", "--build"): self.assertIn(token, result.planned_command)
        for cond in (payload["runtime"]["containers_started"], payload["source_trees_mutated"],
                     payload["graph_roots_read"], payload["server_memory_read"], payload["runtime"]["postgres_host_port_published"]):
            self.assertFalse(cond)

    def test_up_dry_run_reflects_enabled_direct_db_port_mapping(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)
            self.write_runtime_server_port(home, 55982)
            config = home / "repomap.rpl.toml"
            config.write_text(config.read_text(encoding="utf-8").replace("direct_host_port_enabled = false", "direct_host_port_enabled = true"), encoding="utf-8")
            with patch("repomap_kg.runtime.local.is_local_port_open", return_value=False):
                result = up_local_runtime(home, dry_run=True)
            payload = result.to_jsonable()
            self.assertTrue(payload["runtime"]["direct_db_host_port_enabled"])
            self.assertFalse(payload["runtime"]["postgres_host_port_published"])
            self.assertEqual(payload["runtime"]["postgres_bind_host"], "127.0.0.1")
            self.assertNotIn(f"127.0.0.1:{DEFAULT_POSTGRES_HOST_PORT}:5432", (home / "runtime" / "compose.yaml").read_text(encoding="utf-8"))
            self.assertTrue(payload["dbeaver"]["enabled"])
            self.assertEqual((payload["dbeaver"]["host"], payload["dbeaver"]["port"], payload["dbeaver"]["password"]),
                             ("127.0.0.1", DEFAULT_POSTGRES_HOST_PORT, "[REDACTED: see runtime/.env]"))

    def test_up_non_dry_run_invokes_compose_without_host_postgres(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)
            self.write_runtime_server_port(home, 55983)
            with patch("repomap_kg.runtime.local.shutil.which", return_value="/usr/bin/docker"), patch("repomap_kg.runtime.local.subprocess.run") as run, patch("repomap_kg.runtime.local.inspect_container", return_value=LocalContainerStatus("postgres", "postgres", postgres_host_binding_valid=True)):
                result = up_local_runtime(home)
        payload = result.to_jsonable()
        self.assertEqual(payload["result"], "started")
        self.assertTrue(payload["container_runtime_checked"] and payload["container_runtime_available"])
        command = run.call_args_list[0].args[0]
        self.assertEqual(command[0:2], ("docker", "compose"))
        self.assertIn("--build", command)
        self.assertNotIn("psql", command)
        for s in ("stdout", "stderr"): self.assertEqual(run.call_args_list[0].kwargs[s], subprocess.DEVNULL)

    def test_up_runtime_failure_is_bounded_and_private_safe(self):
        private_value = "/private/source-derived/runtime-detail"
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)
            self.write_runtime_server_port(home, 55984)
            failure = subprocess.CalledProcessError(17, (private_value, "compose", "up"), output=private_value, stderr=private_value)
            with (
                patch("repomap_kg.runtime.local.shutil.which", return_value="/usr/bin/docker"),
                patch("repomap_kg.runtime.local.subprocess.run", side_effect=failure),
            ):
                with self.assertRaises(LocalRuntimeError) as raised:
                    up_local_runtime(home)
        self.assertEqual(str(raised.exception), "container runtime command failed with exit code 17")
        self.assertNotIn(private_value, str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)
        self.assertTrue(raised.exception.__suppress_context__)

    def test_down_dry_run_preserves_volume_by_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)
            result = down_local_runtime(home, dry_run=True)
        payload = result.to_jsonable()
        self.assertEqual(payload["command"], "down")
        self.assertEqual(payload["result"], "dry_run")
        self.assertIn("down", result.planned_command)
        self.assertNotIn("-v", result.planned_command)
        self.assertFalse(payload["persistent_volume_deleted"] or payload["destructive_db_actions"])

    def test_down_non_dry_run_does_not_delete_volumes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)
            with patch("repomap_kg.runtime.local.shutil.which", return_value="/usr/bin/docker"), patch("repomap_kg.runtime.local.subprocess.run") as run:
                result = down_local_runtime(home)
        payload = result.to_jsonable()
        self.assertEqual(payload["result"], "stopped")
        command = run.call_args.args[0]
        self.assertEqual(command[0:2], ("docker", "compose"))
        self.assertIn("down", command)
        self.assertNotIn("-v", command)
        for s in ("stdout", "stderr"): self.assertEqual(run.call_args.kwargs[s], subprocess.DEVNULL)
        self.assertFalse(payload["persistent_volume_deleted"])

    def test_up_rejects_missing_runtime_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)
            (home / "runtime" / "compose.yaml").unlink()
            with self.assertRaises(LocalRuntimeError) as error:
                up_local_runtime(home, dry_run=True)
        self.assertIn("runtime-files-missing", [item.code for item in error.exception.diagnostics])

    def test_up_rejects_invalid_config_instead_of_using_host_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)
            (home / "repomap.rpl.toml").write_text("schema_version = 1\n# intentionally incomplete\n", encoding="utf-8")
            with self.assertRaises(LocalRuntimeError) as error:
                up_local_runtime(home, dry_run=True)
        self.assertIn("missing-section", [item.code for item in error.exception.diagnostics])

    def test_up_reports_local_port_conflict_before_runtime_invocation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            setup_local_runtime(home)
            config = home / "repomap.rpl.toml"
            config.write_text(config.read_text(encoding="utf-8").replace(f"postgres_host_port = {DEFAULT_POSTGRES_HOST_PORT}", "postgres_host_port = 55433"), encoding="utf-8")
            with patch("repomap_kg.runtime.local.is_local_port_open", return_value=True), patch("repomap_kg.runtime.local.inspect_container", return_value=LocalContainerStatus("server", "server")):
                with self.assertRaises(LocalRuntimeError) as error:
                    up_local_runtime(home, dry_run=True)
            self.assertIn("port-conflict", [item.code for item in error.exception.diagnostics])

    def test_table_output_reports_redacted_dbeaver_info_and_safety(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            result = setup_local_runtime(home)
            table = format_local_runtime_table(result)
        for token in ("RepoMap local runtime setup", "direct_db=disabled", "Direct DB access disabled",
                      "graph_roots_read=false", "destructive_db_actions=false"):
            self.assertIn(token, table)
        for token in ("password=[REDACTED: see runtime/.env]", "POSTGRES_PASSWORD="):
            self.assertNotIn(token, table)

    def write_runtime_server_port(self, home: Path, port: int) -> None:
        config = home / "repomap.rpl.toml"
        config.write_text(config.read_text(encoding="utf-8").replace(f"server_host_port = {DEFAULT_SERVER_HOST_PORT}", f"server_host_port = {port}"), encoding="utf-8")
