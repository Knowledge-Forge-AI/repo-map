"""Public-safe disposable SCALE15 runtime environment and fixture lifecycle."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import time

from repomap_kg.ops.config_loading import load_ops_config
from repomap_kg.ops.config_records import OpsConfig
from repomap_kg.runtime.backup_commands import read_runtime_password
from repomap_kg.runtime.local import (
    down_local_runtime,
    setup_local_runtime,
    up_local_runtime,
)
from repomap_kg.runtime.plan import LocalRuntimePlan, LocalRuntimeResult, build_local_runtime_plan


@dataclass(frozen=True)
class Scale15RuntimeFixture:
    home: Path
    repository: Path
    config_path: Path
    plan: LocalRuntimePlan
    password: str
    graph_ids: tuple[str, ...]
    proxy_container: str
    config_loader: Callable[[Path], OpsConfig] | None = None
    environment_loader: Callable[["Scale15RuntimeFixture"], dict[str, str]] | None = None

    @property
    def config(self) -> OpsConfig:
        loader = load_ops_config if self.config_loader is None else self.config_loader
        return loader(self.config_path)

    def psql_args(self, graph_id: str) -> tuple[str, ...]:
        graph = next(item for item in self.config.graphs if item.id == graph_id)
        return tuple(
            self.config.postgres.psql_args_for_database(graph.database)
        )


@dataclass(frozen=True)
class Scale15RuntimeEnvironmentCallbacks:
    """Typed lifecycle seams retained by the public campaign facade."""
    setup_local_runtime: Callable[[Path], LocalRuntimeResult]
    available_port: Callable[[], int]
    runtime_config: Callable[[tuple[str, ...], int, int], str]
    actual_config: Callable[[tuple[str, ...], Path, int], str]
    build_plan: Callable[[Path], LocalRuntimePlan]
    read_runtime_password: Callable[[Path], str]
    up_local_runtime: Callable[[Path], LocalRuntimeResult]
    down_local_runtime: Callable[[Path], LocalRuntimeResult]
    start_loopback_proxy: Callable[[LocalRuntimePlan, int], str]
    wait_for_databases: Callable[[Scale15RuntimeFixture], None]
    load_ops_config: Callable[[Path], OpsConfig]
    environment: Callable[[Scale15RuntimeFixture], dict[str, str]]


def start_scale15_runtime(
    root: Path,
    graph_ids: tuple[str, ...],
    *,
    callbacks: Scale15RuntimeEnvironmentCallbacks | None = None,
) -> Scale15RuntimeFixture:
    """Start one exact-scope RepoMap runtime with dedicated campaign graphs."""

    selected = callbacks or _default_environment_callbacks()
    home = root / "runtime-home"
    selected.setup_local_runtime(home)
    repository = home / "repository"
    repository.mkdir()
    repository.joinpath("app.py").write_text(
        "def public_fixture() -> int:\n    return 1\n",
        encoding="utf-8",
    )
    postgres_port = selected.available_port()
    server_port = selected.available_port()
    home.joinpath("repomap.rpl.toml").write_text(
        selected.runtime_config(graph_ids, postgres_port, server_port),
        encoding="utf-8",
    )
    selected.setup_local_runtime(home)
    plan = selected.build_plan(home)
    password = selected.read_runtime_password(plan.env_file)
    config_path = root / "actual.rp.toml"
    config_path.write_text(
        selected.actual_config(graph_ids, repository, server_port),
        encoding="utf-8",
    )
    started = False
    try:
        result = selected.up_local_runtime(home)
        if result.result != "started":
            raise AssertionError("disposable SCALE15 runtime did not start")
        started = True
        plan = selected.build_plan(home)
        proxy_container = selected.start_loopback_proxy(plan, server_port)
        fixture = Scale15RuntimeFixture(
            home,
            repository,
            config_path,
            plan,
            password,
            graph_ids,
            proxy_container,
            config_loader=selected.load_ops_config,
            environment_loader=selected.environment,
        )
        selected.wait_for_databases(fixture)
        return fixture
    except BaseException:
        try:
            selected.down_local_runtime(home)
        except BaseException:
            if started:
                raise
        raise


def stop_scale15_runtime(
    fixture: Scale15RuntimeFixture,
    *,
    callbacks: Scale15RuntimeEnvironmentCallbacks | None = None,
) -> None:
    """Stop the exact disposable runtime through its owned lifecycle."""

    selected = callbacks or _default_environment_callbacks()
    result = selected.down_local_runtime(fixture.home)
    if result.result != "stopped":
        raise AssertionError("disposable SCALE15 runtime did not stop")


def _environment(fixture: Scale15RuntimeFixture) -> dict[str, str]:
    environment = dict(os.environ)
    source = _repository_root() / "src"
    environment["PYTHONPATH"] = os.pathsep.join(
        (str(source / "main" / "python"), str(source / "test" / "support" / "python"))
    )
    environment["REPOMAP_PG_PASSWORD"] = fixture.password
    environment["PGPASSWORD"] = fixture.password
    return environment


def _wait_for_databases(fixture: Scale15RuntimeFixture) -> None:
    env_func = fixture.environment_loader or _environment
    environment = env_func(fixture)
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        ready = True
        for graph_id in fixture.graph_ids:
            completed = subprocess.run(
                ("psql", *fixture.psql_args(graph_id), "-qAt", "-c", "SELECT 1"),
                env=environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=2,
                shell=False,
            )
            ready = ready and completed.returncode == 0
        if ready:
            return
        time.sleep(0.2)
    raise AssertionError("disposable SCALE15 graph databases did not become ready")


def _start_loopback_proxy(plan: LocalRuntimePlan, host_port: int) -> str:
    name = plan.identity.server_container
    script = f"""
import socket
import threading

def copy(source, target):
    try:
        while True:
            payload = source.recv(65536)
            if not payload:
                break
            target.sendall(payload)
    finally:
        for connection in (source, target):
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

def handle(client):
    upstream = None
    forward = None
    try:
        upstream = socket.create_connection(("postgres", 5432), timeout=5)
        upstream.settimeout(None)
        forward = threading.Thread(
            target=copy,
            args=(client, upstream),
            daemon=True,
        )
        forward.start()
        copy(upstream, client)
    finally:
        client.close()
        if upstream is not None:
            upstream.close()
        if forward is not None:
            forward.join(timeout=1)

listener = socket.socket()
listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
listener.bind(("0.0.0.0", {host_port}))
listener.listen()
while True:
    client, _ = listener.accept()
    threading.Thread(target=handle, args=(client,), daemon=True).start()
"""
    override = plan.runtime_dir / "scale15-proxy.yaml"
    override.write_text(
        f"""services:
  http:
    entrypoint: ["python", "-c"]
    command: [{json.dumps(script)}]
    healthcheck:
      disable: true
    restart: "no"
""",
        encoding="utf-8",
    )
    completed = subprocess.run(
        (
            plan.container_runtime,
            "compose",
            "-f",
            str(plan.compose_file),
            "-f",
            str(override),
            "--project-name",
            plan.identity.project_name,
            "up",
            "-d",
            "--no-deps",
            "--force-recreate",
            "http",
        ),
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
        shell=False,
    )
    if completed.returncode != 0:
        raise AssertionError("disposable SCALE15 loopback transport did not start")
    time.sleep(0.1)
    running = subprocess.run(
        (
            plan.container_runtime,
            "inspect",
            "--format",
            "{{.State.Running}}",
            name,
        ),
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
        shell=False,
    )
    if running.returncode != 0 or running.stdout.strip() != "true":
        raise AssertionError("disposable SCALE15 loopback transport exited")
    return name


def _runtime_config(
    graph_ids: tuple[str, ...],
    postgres_port: int,
    server_port: int,
) -> str:
    return _config_text(graph_ids, postgres_host="postgres", postgres_port=5432, root_path="./repository", runtime=(postgres_port, server_port))


def _actual_config(
    graph_ids: tuple[str, ...],
    repository: Path,
    postgres_port: int,
) -> str:
    return _config_text(graph_ids, postgres_host="127.0.0.1", postgres_port=postgres_port, root_path=str(repository), runtime=None)


def _config_text(
    graph_ids: tuple[str, ...],
    *,
    postgres_host: str,
    postgres_port: int,
    root_path: str,
    runtime: tuple[int, int] | None,
) -> str:
    runtime_text = ""
    if runtime is not None:
        runtime_text = f"""
[runtime]
container_runtime = "docker"
server_host_port = {runtime[1]}
bind_host = "127.0.0.1"

[runtime.postgres]
direct_host_port_enabled = false
host_port = {runtime[0]}
bind_host = "127.0.0.1"
"""
    graphs = "\n".join(
        f"""
[[graphs]]
id = "{graph_id}"
name = "Public Fixture"
root_path = "{root_path}"
repository_name = "public-fixture"
database = "{_database(graph_id)}"
privacy = "public-dev"
enabled = true
mcp_visible = false
extractor_profile = "default"
refresh_policy = "manual"
"""
        for graph_id in graph_ids
    )
    return f"""schema_version = 1

[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"
{runtime_text}
[postgres]
host = "{postgres_host}"
port = {postgres_port}
database = "repomap"
user = "repomap"
password_env = "REPOMAP_PG_PASSWORD"
{graphs}
[server_memory]
enabled = false
path = "server-memory.jsonl"
mode = "read_only"
"""


def _database(graph_id: str) -> str:
    return "repomap_" + re.sub(r"[^a-z0-9_]", "_", graph_id.lower())


def _available_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[5]


def _default_environment_callbacks() -> Scale15RuntimeEnvironmentCallbacks:
    return Scale15RuntimeEnvironmentCallbacks(
        setup_local_runtime,
        _available_port,
        _runtime_config,
        _actual_config,
        build_local_runtime_plan,
        read_runtime_password,
        up_local_runtime,
        down_local_runtime,
        _start_loopback_proxy,
        _wait_for_databases,
        load_ops_config,
        _environment,
    )


__all__ = [
    "Scale15RuntimeFixture",
    "Scale15RuntimeEnvironmentCallbacks",
    "_actual_config",
    "_available_port",
    "_config_text",
    "_database",
    "_environment",
    "_repository_root",
    "_runtime_config",
    "_start_loopback_proxy",
    "_wait_for_databases",
    "start_scale15_runtime",
    "stop_scale15_runtime",
]
