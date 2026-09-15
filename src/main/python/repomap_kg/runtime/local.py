"""Local container runtime planning and lifecycle helpers for RepoMap."""

from __future__ import annotations

import json
import os as os
import shutil
import socket
import subprocess
from pathlib import Path
import urllib.error
import urllib.request

from repomap_kg.ops.config_loading import (
    resolve_repo_map_home,
)
from repomap_kg.runtime.commands import (
    default_env_text,
    ensure_runtime_home_hash,
    ensure_runtime_files_exist,
    format_local_runtime_table as format_local_runtime_table,
    render_local_runtime_files,
    render_server_dockerfile as render_server_dockerfile,
)
from repomap_kg.runtime.database_role_contract import ensure_role_secrets
from repomap_kg.runtime.plan import (
    DEFAULT_POSTGRES_HOST_PORT as DEFAULT_POSTGRES_HOST_PORT,
    DEFAULT_SERVER_HOST_PORT as DEFAULT_SERVER_HOST_PORT,
    ENV_RUNTIME_SOURCE_ROOT as ENV_RUNTIME_SOURCE_ROOT,
    LOCAL_RUNTIME_ENV_FILE,
    LocalContainerStatus,
    LocalRuntimeDiagnostic,
    LocalRuntimeError,
    LocalRuntimeIdentity,
    LocalRuntimePlan,
    LocalRuntimeResult,
    LocalServerHealth,
    build_local_runtime_plan,
    default_local_runtime_plan,
    default_repomap_rpl_toml,
    redact_runtime_text as redact_runtime_text,
    resolve_runtime_source_root as resolve_runtime_source_root,
)

def setup_local_runtime(
    repo_map_home: str | Path | None = None,
    *,
    dry_run: bool = False,
) -> LocalRuntimeResult:
    home = resolve_repo_map_home(repo_map_home)
    identity = LocalRuntimeIdentity.from_home(home)
    diagnostics: list[LocalRuntimeDiagnostic] = []
    created: list[Path] = []
    if dry_run:
        plan = default_local_runtime_plan(home)
        return LocalRuntimeResult(
            command="setup",
            result="dry_run",
            plan=plan,
            diagnostics=(LocalRuntimeDiagnostic(
                "info", "setup-dry-run", str(home),
                "local setup would create REPOMAP_HOME runtime files",
            ),),
            planned_command=("local", "setup", "--repo-map-home", str(home)),
        )

    home.mkdir(parents=True, exist_ok=True)
    for directory in (home / "runtime", home / "logs", home / "status"):
        if not directory.exists():
            directory.mkdir(parents=True)
            created.append(directory)
    config_path = home / "repomap.rpl.toml"
    if not config_path.exists():
        config_path.write_text(default_repomap_rpl_toml(), encoding="utf-8")
        created.append(config_path)
    else:
        diagnostics.append(LocalRuntimeDiagnostic(
            "info", "config-exists", str(config_path),
            "repomap.rpl.toml already exists and was not overwritten",
        ))
    env_file = home / LOCAL_RUNTIME_ENV_FILE
    if not env_file.exists():
        env_file.write_text(default_env_text(identity.home_hash), encoding="utf-8")
        env_file.chmod(0o600)
        created.append(env_file)
    else:
        added_role_secrets = ensure_role_secrets(env_file)
        diagnostics.append(LocalRuntimeDiagnostic(
            "info", "env-role-secrets-added" if added_role_secrets else "env-exists",
            str(env_file),
            (
                "missing private database-role secrets were added"
                if added_role_secrets
                else "runtime env file already exists and was not overwritten"
            ),
        ))
    if ensure_runtime_home_hash(env_file, identity.home_hash):
        diagnostics.append(LocalRuntimeDiagnostic(
            "info", "env-runtime-identity-aligned", str(env_file),
            "private runtime identity authority was aligned",
        ))
    plan = build_local_runtime_plan(
        home,
        fallback_identity=identity,
        allow_invalid_config=True,
    )
    runtime_files = render_local_runtime_files(plan)
    for path, text in runtime_files.items():
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            path.write_text(text, encoding="utf-8")
            created.append(path)
    if not plan.postgres_data_dir.exists():
        plan.postgres_data_dir.mkdir(parents=True)
        created.append(plan.postgres_data_dir)
    return LocalRuntimeResult(
        command="setup",
        result="success",
        plan=plan,
        diagnostics=tuple(diagnostics),
        created_files=tuple(created),
    )


def up_local_runtime(
    repo_map_home: str | Path | None = None,
    *,
    dry_run: bool = False,
) -> LocalRuntimeResult:
    plan = build_local_runtime_plan(resolve_repo_map_home(repo_map_home))
    ensure_runtime_files_exist(plan)
    check_runtime_ports_available(plan)
    if not dry_run:
        for path, text in render_local_runtime_files(plan).items():
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                path.write_text(text, encoding="utf-8")
    else:
        for path, text in render_local_runtime_files(plan).items():
            if path.exists() and path.read_text(encoding="utf-8") != text:
                path.write_text(text, encoding="utf-8")
    command = tuple(plan.compose_command("up", "-d", "--build"))
    if dry_run:
        return LocalRuntimeResult(
            command="up",
            result="dry_run",
            plan=plan,
            planned_command=command,
        )
    runtime_path = shutil.which(plan.container_runtime)
    if runtime_path is None:
        raise LocalRuntimeError((
            LocalRuntimeDiagnostic(
                "error", "container-runtime-unavailable", plan.container_runtime,
                f"container runtime {plan.container_runtime!r} is not available",
            ),
        ))
    _run_container_runtime(command)
    return LocalRuntimeResult(
        command="up",
        result="started",
        plan=plan,
        planned_command=command,
        container_runtime_checked=True,
        container_runtime_available=True,
    )


def down_local_runtime(
    repo_map_home: str | Path | None = None,
    *,
    dry_run: bool = False,
) -> LocalRuntimeResult:
    plan = build_local_runtime_plan(resolve_repo_map_home(repo_map_home))
    ensure_runtime_files_exist(plan)
    command = tuple(plan.compose_command("down"))
    if dry_run:
        return LocalRuntimeResult(
            command="down",
            result="dry_run",
            plan=plan,
            planned_command=command,
        )
    runtime_path = shutil.which(plan.container_runtime)
    if runtime_path is None:
        raise LocalRuntimeError((
            LocalRuntimeDiagnostic(
                "error", "container-runtime-unavailable", plan.container_runtime,
                f"container runtime {plan.container_runtime!r} is not available",
            ),
        ))
    _run_container_runtime(command)
    return LocalRuntimeResult(
        command="down",
        result="stopped",
        plan=plan,
        planned_command=command,
        container_runtime_checked=True,
        container_runtime_available=True,
    )


def _run_container_runtime(command: tuple[str, ...]) -> None:
    try:
        subprocess.run(
            command,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError as error:
        raise LocalRuntimeError((
            LocalRuntimeDiagnostic(
                "error", "container-runtime-command-failed", "container-runtime",
                f"container runtime command failed with exit code {error.returncode}",
            ),
        )) from None


def query_local_runtime_status(
    repo_map_home: str | Path | None = None,
    *,
    check_containers: bool = False,
) -> LocalRuntimeResult:
    plan = build_local_runtime_plan(
        resolve_repo_map_home(repo_map_home),
        allow_invalid_config=True,
    )
    diagnostics: list[LocalRuntimeDiagnostic] = []
    runtime_available: bool | None = None
    containers: dict[str, LocalContainerStatus] = {}
    server_health = LocalServerHealth(url=plan.server_health_url)
    if not plan.compose_file.exists():
        diagnostics.append(LocalRuntimeDiagnostic(
            "warning", "runtime-files-missing", str(plan.compose_file),
            "runtime files are missing; run repomap-kg local setup",
        ))
    if check_containers:
        runtime_available = shutil.which(plan.container_runtime) is not None
        if not runtime_available:
            diagnostics.append(LocalRuntimeDiagnostic(
                "warning", "container-runtime-unavailable", plan.container_runtime,
                f"container runtime {plan.container_runtime!r} is not available",
            ))
        else:
            containers = inspect_local_runtime_containers(plan)
            server_status = containers.get("server")
            if server_status and server_status.status == "running":
                server_health = probe_server_health(plan)
            elif (
                server_status
                and server_status.exists
                and server_status.status == "exited"
                and server_status.exit_code == 0
            ):
                diagnostics.append(LocalRuntimeDiagnostic(
                    "warning", "server-exited-cleanly", server_status.name,
                    (
                        "server container exited cleanly; older stdio MCP "
                        "container mode closes when stdin closes"
                    ),
                ))
    server_c = containers.get("server")
    postgres_c = containers.get("postgres")
    running = bool(
        server_c is not None
        and server_c.status == "running"
        and server_c.owned
        and postgres_c is not None
        and postgres_c.status == "running"
        and postgres_c.owned
    )
    return LocalRuntimeResult(
        command="status",
        result="running" if running else "not_running",
        plan=plan,
        diagnostics=tuple(diagnostics),
        container_runtime_checked=check_containers,
        container_runtime_available=runtime_available,
        containers=containers,
        server_health=server_health,
    )


def check_runtime_ports_available(plan: LocalRuntimePlan) -> None:
    diagnostics: list[LocalRuntimeDiagnostic] = []
    checks = [("server", plan.bind_host, plan.server_host_port)]
    if plan.direct_db_host_port_enabled:
        checks.append(("postgres", plan.postgres_bind_host, plan.postgres_host_port))
    for label, host, port in checks:
        if is_local_port_open(host, port):
            diagnostics.append(LocalRuntimeDiagnostic(
                "error", "port-conflict", f"{host}:{port}",
                f"{label} host port {port} is already accepting local connections",
            ))
    if diagnostics:
        raise LocalRuntimeError(tuple(diagnostics))


def is_local_port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.2):
            return True
    except OSError:
        return False


def inspect_local_runtime_containers(
    plan: LocalRuntimePlan,
) -> dict[str, LocalContainerStatus]:
    return {
        "postgres": inspect_container(plan, "postgres", plan.identity.postgres_container),
        "server": inspect_container(plan, "server", plan.identity.server_container),
    }


def inspect_container(
    plan: LocalRuntimePlan,
    component: str,
    name: str,
) -> LocalContainerStatus:
    completed = subprocess.run(
        [plan.container_runtime, "inspect", name],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if completed.returncode != 0:
        return LocalContainerStatus(
            name=name,
            component=component,
            checked=True,
            exists=False,
            diagnostic=completed.stderr.strip() or "container not found",
        )
    try:
        payload = json.loads(completed.stdout)
        record = payload[0] if isinstance(payload, list) and payload else {}
        labels = record.get("Config", {}).get("Labels", {}) or {}
        state = record.get("State", {}) or {}
        health = state.get("Health", {}) or {}
    except (TypeError, ValueError) as error:
        return LocalContainerStatus(
            name=name,
            component=component,
            checked=True,
            exists=True,
            diagnostic=f"container inspect output was not understood: {error}",
        )
    owned = (
        labels.get("org.repomap.runtime") == "true"
        and labels.get("org.repomap.home_hash") == plan.identity.home_hash
        and labels.get("org.repomap.component") == component
    )
    exit_code = state.get("ExitCode")
    return LocalContainerStatus(
        name=name,
        component=component,
        checked=True,
        exists=True,
        owned=owned,
        status=str(state.get("Status") or "unknown"),
        exit_code=exit_code if isinstance(exit_code, int) else None,
        health=health.get("Status") if isinstance(health, dict) else None,
    )


def probe_server_health(plan: LocalRuntimePlan) -> LocalServerHealth:
    try:
        with urllib.request.urlopen(plan.server_health_url, timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError) as error:
        return LocalServerHealth(
            checked=True,
            reachable=False,
            status="unreachable",
            url=plan.server_health_url,
            diagnostic=str(error),
        )
    status = str(payload.get("status", "unknown")) if isinstance(payload, dict) else "unknown"
    return LocalServerHealth(
        checked=True,
        reachable=True,
        status=status,
        url=plan.server_health_url,
        payload=payload if isinstance(payload, dict) else None,
    )
