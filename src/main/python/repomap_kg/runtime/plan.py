"""Local runtime plan records and configuration-derived defaults."""

from __future__ import annotations

import os
from pathlib import Path

from repomap_kg.ops.config_loading import (
    OpsConfig,
    OpsConfigError as OpsConfigError,
    load_ops_config_home as load_ops_config_home,
)
from repomap_kg.ops.resolved_config import resolve_ops_config
from repomap_kg.runtime._plan_records import (
    DBeaverInfo as DBeaverInfo,
    DEFAULT_BIND_HOST as DEFAULT_BIND_HOST,
    DEFAULT_CONTAINER_RUNTIME as DEFAULT_CONTAINER_RUNTIME,
    DEFAULT_POSTGRES_HOST_PORT as DEFAULT_POSTGRES_HOST_PORT,
    DEFAULT_SERVER_HOST_PORT as DEFAULT_SERVER_HOST_PORT,
    ENV_RUNTIME_SOURCE_ROOT as ENV_RUNTIME_SOURCE_ROOT,
    LOCAL_RUNTIME_COMPOSE_FILE as LOCAL_RUNTIME_COMPOSE_FILE,
    LOCAL_RUNTIME_DOCKERFILE as LOCAL_RUNTIME_DOCKERFILE,
    LOCAL_RUNTIME_ENV_FILE as LOCAL_RUNTIME_ENV_FILE,
    LOCAL_RUNTIME_POSTGRES_DATA_DIR as LOCAL_RUNTIME_POSTGRES_DATA_DIR,
    LocalContainerStatus as LocalContainerStatus,
    LocalRuntimeDiagnostic as LocalRuntimeDiagnostic,
    LocalRuntimeError as LocalRuntimeError,
    LocalRuntimeIdentity as LocalRuntimeIdentity,
    LocalRuntimePlan as LocalRuntimePlan,
    LocalRuntimeResult as LocalRuntimeResult,
    LocalServerHealth as LocalServerHealth,
    SERVER_HEALTH_PATH as SERVER_HEALTH_PATH,
    redact_runtime_text as redact_runtime_text,
)


def build_local_runtime_plan(
    repo_map_home: Path,
    *,
    fallback_identity: LocalRuntimeIdentity | None = None,
    allow_invalid_config: bool = False,
) -> LocalRuntimePlan:
    config: OpsConfig | None = None
    try:
        config = load_ops_config_home(repo_map_home)
    except OpsConfigError as error:
        if not allow_invalid_config:
            raise LocalRuntimeError(
                tuple(
                    LocalRuntimeDiagnostic(
                        diagnostic.severity,
                        diagnostic.code,
                        diagnostic.path,
                        diagnostic.message,
                    )
                    for diagnostic in error.diagnostics
                )
            ) from error
    identity = fallback_identity or LocalRuntimeIdentity.from_home(repo_map_home)
    runtime = config.runtime if config else None
    postgres = config.postgres if config else None
    resolved = resolve_ops_config(config) if config else None
    return LocalRuntimePlan(
        repo_map_home=repo_map_home,
        config=config,
        identity=identity,
        container_runtime=(
            runtime.container_runtime if runtime and runtime.container_runtime else DEFAULT_CONTAINER_RUNTIME
        ),
        bind_host=runtime.bind_host if runtime else DEFAULT_BIND_HOST,
        postgres_host_port=(
            runtime.postgres.host_port
            if runtime and runtime.postgres.host_port
            else DEFAULT_POSTGRES_HOST_PORT
        ),
        postgres_bind_host=(
            runtime.postgres.bind_host
            if runtime
            else DEFAULT_BIND_HOST
        ),
        direct_db_host_port_enabled=(
            runtime.postgres.direct_host_port_enabled
            if runtime
            else False
        ),
        server_host_port=(
            runtime.server_host_port
            if runtime and runtime.server_host_port
            else DEFAULT_SERVER_HOST_PORT
        ),
        database=(
            str(resolved.default_database)
            if resolved
            else "repomap"
        ),
        user=postgres.user if postgres and postgres.user else "repomap",
    )


def default_local_runtime_plan(repo_map_home: Path) -> LocalRuntimePlan:
    return LocalRuntimePlan(
        repo_map_home=repo_map_home,
        config=None,
        identity=LocalRuntimeIdentity.from_home(repo_map_home),
        container_runtime=DEFAULT_CONTAINER_RUNTIME,
        bind_host=DEFAULT_BIND_HOST,
        postgres_host_port=DEFAULT_POSTGRES_HOST_PORT,
        postgres_bind_host=DEFAULT_BIND_HOST,
        direct_db_host_port_enabled=False,
        server_host_port=DEFAULT_SERVER_HOST_PORT,
        database="repomap",
        user="repomap",
    )


def resolve_runtime_source_root(start: Path | None = None) -> Path:
    env_root = os.environ.get(ENV_RUNTIME_SOURCE_ROOT)
    if env_root:
        candidate = Path(env_root).expanduser()
        if is_runtime_source_root(candidate):
            return candidate
    search_start = (start or Path.cwd()).resolve()
    for candidate in (search_start, *search_start.parents):
        if is_runtime_source_root(candidate):
            return candidate
    module_start = Path(__file__).resolve()
    for candidate in module_start.parents:
        if is_runtime_source_root(candidate):
            return candidate
    return module_start.parents[4]


def is_runtime_source_root(path: Path) -> bool:
    return (
        (path / "pyproject.toml").is_file()
        and (path / "README.md").is_file()
        and (path / "src" / "main" / "python" / "repomap_kg" / "__main__.py").is_file()
        and (path / "src" / "main" / "resources").is_dir()
    )


def default_repomap_rpl_toml() -> str:
    return f"""\
schema_version = 1

[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[runtime]
container_runtime = "{DEFAULT_CONTAINER_RUNTIME}"
server_host_port = {DEFAULT_SERVER_HOST_PORT}
bind_host = "{DEFAULT_BIND_HOST}"

[runtime.postgres]
direct_host_port_enabled = false
host_port = {DEFAULT_POSTGRES_HOST_PORT}
bind_host = "{DEFAULT_BIND_HOST}"

[postgres]
host = "postgres"
port = 5432
database = "repomap"
user = "repomap"
password_env = "REPOMAP_PG_PASSWORD"

[[graphs]]
id = "repo-map"
name = "RepoMap"
root_path = "./repo-map"
repository_name = "repo-map"
privacy = "public-dev"
enabled = false
mcp_visible = false
extractor_profile = "default"
refresh_policy = "manual"
exclude_paths = [
  ".git",
  ".serena",
  ".venv",
  "__pycache__",
  ".pytest_cache",
  ".ruff_cache",
  "node_modules",
  ".terraform",
]

[server_memory]
enabled = false
path = "./server-memory"
mode = "read_only"
"""


__all__ = [
    "DBeaverInfo",
    "DEFAULT_BIND_HOST",
    "DEFAULT_CONTAINER_RUNTIME",
    "DEFAULT_POSTGRES_HOST_PORT",
    "DEFAULT_SERVER_HOST_PORT",
    "ENV_RUNTIME_SOURCE_ROOT",
    "LOCAL_RUNTIME_COMPOSE_FILE",
    "LOCAL_RUNTIME_DOCKERFILE",
    "LOCAL_RUNTIME_ENV_FILE",
    "LOCAL_RUNTIME_POSTGRES_DATA_DIR",
    "LocalContainerStatus",
    "LocalRuntimeDiagnostic",
    "LocalRuntimeError",
    "LocalRuntimeIdentity",
    "LocalRuntimePlan",
    "LocalRuntimeResult",
    "LocalServerHealth",
    "OpsConfigError",
    "SERVER_HEALTH_PATH",
    "build_local_runtime_plan",
    "default_local_runtime_plan",
    "default_repomap_rpl_toml",
    "is_runtime_source_root",
    "load_ops_config_home",
    "redact_runtime_text",
    "resolve_runtime_source_root",
]
