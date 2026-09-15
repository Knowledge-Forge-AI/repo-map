"""Shared support for RepoMap CLI integration tests."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from urllib.request import urlopen

from repomap_test_support.cli_in_process import (
    FIXTURE_ROOT,
    REPO_ROOT,
    module_environment,
    run_repo_map_in_process,
    write_text_fixture,
)


def _module_process_environment() -> dict[str, str]:
    env = module_environment()
    # The runner prepends its owned sitecustomize directory to PYTHONPATH.
    # Retain it for measured children while keeping the source helper's defaults.
    inherited_path = os.environ.get("PYTHONPATH")
    if inherited_path and env.get("COVERAGE_PROCESS_START") and env.get("COVERAGE_CHILD_MANIFEST_DIR"):
        env["PYTHONPATH"] = os.pathsep.join((env["PYTHONPATH"], inherited_path))
    return env


def run_cli_module(*args: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "repomap_kg", *args],
        check=False,
        cwd=REPO_ROOT,
        env=_module_process_environment(),
        input=input_text,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def run_module_entrypoint(*args: str) -> tuple[int, str, str]:
    completed = run_cli_module(*args)
    return completed.returncode, completed.stdout, completed.stderr


SERVER_MEMORY_FIXTURES = FIXTURE_ROOT / "server_memory"
OPS_POLICY_FIXTURES = FIXTURE_ROOT / "ops_policy"

OPS_CONFIG_TEMPLATE = """\
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
root_path = "./repo-map"
repository_name = "repo-map"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"

[server_memory]
enabled = false
path = "./server-memory"
mode = "read_only"
"""


class CliIntegrationTestCase(unittest.TestCase):
    def run_cli(self, *args, input_text=None):
        return run_cli_module(*args, input_text=input_text)

    def local_server_test_port(self) -> int:
        return 55890 + (os.getpid() % 100)

    def call_local_server_handler(self, handler_cls, path: str, home: Path):
        handler = object.__new__(handler_cls)
        handler.path = path
        handler.server = type("Server", (), {"repo_map_home": home})()
        handler.wfile = io.BytesIO()
        handler.response_status = 0
        handler.headers = []

        def send_response(status):
            handler.response_status = status

        def send_header(name, value):
            handler.headers.append((name, value))

        def end_headers():
            return None

        handler.send_response = send_response
        handler.send_header = send_header
        handler.end_headers = end_headers
        handler.do_GET()
        return handler.response_status, json.loads(handler.wfile.getvalue())

    def fetch_json_when_ready(self, url: str, process, *, attempts: int = 30):
        for _ in range(attempts):
            if process.poll() is not None:
                stdout, stderr = process.communicate(timeout=1)
                raise AssertionError(
                    f"server exited early with {process.returncode}\n{stdout}\n{stderr}"
                )
            try:
                with urlopen(url, timeout=0.5) as response:
                    return json.loads(response.read().decode("utf-8"))
            except OSError:
                time.sleep(0.1)
        raise AssertionError(f"server did not become ready at {url}")

    def run_module_entrypoint(self, *args):
        return run_module_entrypoint(*args)

    def run_repo_map_in_process(self, *args):
        return run_repo_map_in_process(*args)

    def assert_lifecycle_public_output_safe(
        self,
        rendered: str,
        home: Path,
        *paths: Path,
        raw_dump_marker: str | None = None,
        allow_container_runtime_label: bool = False,
    ) -> None:
        forbidden = [
            str(home),
            str(Path.home()),
            Path.home().name,
            '"planned_command"',
            "planned_command=",
            "docker exec",
            "pg_dump",
            "pg_restore",
            "psql",
            "POSTGRES_PASSWORD",
            "PGPASSWORD",
        ]
        if not allow_container_runtime_label:
            forbidden.append("docker")
        if raw_dump_marker:
            forbidden.append(raw_dump_marker)
        forbidden.extend(str(path) for path in paths)

        for marker in forbidden:
            self.assertNotIn(marker, rendered)

    def local_runtime_test_port(self, offset: int) -> int:
        return 56080 + ((os.getpid() + offset) % 1000)

    def write_runtime_server_port(self, home: Path, port: int) -> None:
        config_path = home / "repomap.rpl.toml"
        config_path.write_text(
            config_path.read_text(encoding="utf-8").replace(
                "server_host_port = 55880",
                f"server_host_port = {port}",
                1,
            ),
            encoding="utf-8",
        )

    def write_fixture(self, path, content):
        return write_text_fixture(path, content)

    def write_ops_config(self, directory, content, *, name="repomap.local.toml"):
        path = directory / name
        path.write_text(content, encoding="utf-8")
        return path
