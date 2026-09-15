"""Local runtime plan records and diagnostics."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from repomap_kg.ops.config_loading import OpsConfig
from repomap_kg.ops.resolved_config import resolve_ops_config

DEFAULT_POSTGRES_HOST_PORT = 55432
DEFAULT_SERVER_HOST_PORT = 55880
DEFAULT_BIND_HOST = "127.0.0.1"
DEFAULT_CONTAINER_RUNTIME = "docker"
ENV_RUNTIME_SOURCE_ROOT = "REPOMAP_SOURCE_ROOT"
LOCAL_RUNTIME_ENV_FILE = "runtime/.env"
LOCAL_RUNTIME_COMPOSE_FILE = "runtime/compose.yaml"
LOCAL_RUNTIME_DOCKERFILE = "runtime/repomap-server.Dockerfile"
LOCAL_RUNTIME_POSTGRES_DATA_DIR = "runtime/postgres-data"
SERVER_HEALTH_PATH = "/healthz"


class LocalRuntimeError(RuntimeError):
    """Raised when a local runtime lifecycle command cannot continue safely."""

    def __init__(self, diagnostics: Sequence["LocalRuntimeDiagnostic"]):
        self.diagnostics = tuple(diagnostics)
        message = "; ".join(diagnostic.message for diagnostic in self.diagnostics)
        super().__init__(message or "local runtime error")


@dataclass(frozen=True)
class LocalRuntimeDiagnostic:
    severity: str
    code: str
    path: str
    message: str

    def to_jsonable(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "code": self.code,
            "path": self.path,
            "message": redact_runtime_text(self.message),
        }


@dataclass(frozen=True)
class LocalRuntimeIdentity:
    home_hash: str
    project_name: str
    network_name: str
    postgres_container: str
    server_container: str

    @classmethod
    def from_home(cls, repo_map_home: Path) -> "LocalRuntimeIdentity":
        digest = hashlib.sha256(str(repo_map_home).encode("utf-8")).hexdigest()[:12]
        return cls(
            home_hash=digest,
            project_name=f"repomap-{digest}",
            network_name=f"repomap-local-{digest}",
            postgres_container=f"repomap-postgres-{digest}",
            server_container=f"repomap-server-{digest}",
        )

    def labels(self, component: str) -> dict[str, str]:
        return {
            "org.repomap.runtime": "true",
            "org.repomap.home_hash": self.home_hash,
            "org.repomap.component": component,
        }


@dataclass(frozen=True)
class DBeaverInfo:
    enabled: bool
    host: str | None = None
    port: int | None = None
    database: str | None = None
    user: str | None = None
    password: str | None = "[REDACTED: see runtime/.env]"
    ssl: str | None = "disabled-local"
    message: str | None = None

    def to_jsonable(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"enabled": self.enabled}
        for key, value in (
            ("host", self.host),
            ("port", self.port),
            ("database", self.database),
            ("user", self.user),
            ("password", self.password),
            ("ssl", self.ssl),
            ("message", self.message),
        ):
            if value is not None:
                payload[key] = value
        return payload


@dataclass(frozen=True)
class LocalContainerStatus:
    name: str
    component: str
    checked: bool = False
    exists: bool = False
    owned: bool = False
    status: str = "unknown"
    exit_code: int | None = None
    health: str | None = None
    diagnostic: str | None = None

    def to_jsonable(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "component": self.component,
            "checked": self.checked,
            "exists": self.exists,
            "owned": self.owned,
            "status": self.status,
        }
        if self.exit_code is not None:
            payload["exit_code"] = self.exit_code
        if self.health is not None:
            payload["health"] = self.health
        if self.diagnostic is not None:
            payload["diagnostic"] = redact_runtime_text(self.diagnostic)
        return payload


@dataclass(frozen=True)
class LocalServerHealth:
    checked: bool = False
    reachable: bool = False
    status: str = "unknown"
    url: str | None = None
    payload: dict[str, Any] | None = None
    diagnostic: str | None = None

    def to_jsonable(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "checked": self.checked,
            "reachable": self.reachable,
            "status": self.status,
        }
        if self.url is not None:
            payload["url"] = self.url
        if self.payload is not None:
            payload["payload"] = self.payload
        if self.diagnostic is not None:
            payload["diagnostic"] = redact_runtime_text(self.diagnostic)
        return payload


@dataclass(frozen=True)
class LocalRuntimePlan:
    repo_map_home: Path
    config: OpsConfig | None
    identity: LocalRuntimeIdentity
    container_runtime: str
    bind_host: str
    postgres_host_port: int
    postgres_bind_host: str
    direct_db_host_port_enabled: bool
    server_host_port: int
    database: str
    user: str

    @property
    def owned_databases(self) -> tuple[str, ...]:
        """Return exact configured graph/control ownership, if available."""

        if self.config is None:
            return ()
        return tuple(str(value) for value in resolve_ops_config(self.config).owned_databases)

    @property
    def graph_databases(self) -> tuple[str, ...]:
        """Return exact configured graph database ownership, if available."""

        if self.config is None:
            return ()
        resolved = resolve_ops_config(self.config)
        return tuple(str(graph.database) for graph in resolved.graphs)

    @property
    def maintenance_database(self) -> str:
        """Return the non-owned PostgreSQL maintenance connection target."""

        if self.config is None:
            return "postgres"
        return str(resolve_ops_config(self.config).maintenance_database)

    @property
    def runtime_dir(self) -> Path:
        return self.repo_map_home / "runtime"

    @property
    def env_file(self) -> Path:
        return self.repo_map_home / LOCAL_RUNTIME_ENV_FILE

    @property
    def compose_file(self) -> Path:
        return self.repo_map_home / LOCAL_RUNTIME_COMPOSE_FILE

    @property
    def dockerfile(self) -> Path:
        return self.repo_map_home / LOCAL_RUNTIME_DOCKERFILE

    @property
    def postgres_data_dir(self) -> Path:
        return self.repo_map_home / LOCAL_RUNTIME_POSTGRES_DATA_DIR

    def dbeaver_info(self) -> DBeaverInfo:
        if not self.direct_db_host_port_enabled:
            return DBeaverInfo(
                enabled=False,
                password=None,
                ssl=None,
                message=(
                    "Direct DB access disabled; use RepoMap MCP/server API or "
                    "enable dev/debug toggle."
                ),
            )
        return DBeaverInfo(
            enabled=True,
            host=self.postgres_bind_host,
            port=self.postgres_host_port,
            database=self.database,
            user=self.user,
        )

    def compose_command(self, *args: str) -> list[str]:
        return [
            self.container_runtime,
            "compose",
            "-f",
            str(self.compose_file),
            "--project-name",
            self.identity.project_name,
            *args,
        ]

    def runtime_jsonable(self, *, files_rendered: bool, containers_started: bool) -> dict[str, Any]:
        return {
            "container_runtime": self.container_runtime,
            "containerized_target": True,
            "runtime_files_rendered": files_rendered,
            "containers_started": containers_started,
            "postgres_host_port": self.postgres_host_port,
            "postgres_bind_host": self.postgres_bind_host,
            "direct_db_host_port_enabled": self.direct_db_host_port_enabled,
            "postgres_host_port_published": self.direct_db_host_port_enabled,
            "postgres_internal_host": "postgres",
            "postgres_internal_port": 5432,
            "server_host_port": self.server_host_port,
            "server_health_url": self.server_health_url,
            "bind_host": self.bind_host,
            "postgres_container": self.identity.postgres_container,
            "server_container": self.identity.server_container,
            "network": self.identity.network_name,
            "home_hash": self.identity.home_hash,
        }

    @property
    def server_health_url(self) -> str:
        return f"http://{self.bind_host}:{self.server_host_port}{SERVER_HEALTH_PATH}"


@dataclass(frozen=True)
class LocalRuntimeResult:
    command: str
    result: str
    plan: LocalRuntimePlan
    diagnostics: tuple[LocalRuntimeDiagnostic, ...] = ()
    created_files: tuple[Path, ...] = ()
    planned_command: tuple[str, ...] = ()
    container_runtime_checked: bool = False
    container_runtime_available: bool | None = None
    source_trees_mutated: bool = False
    graph_roots_read: bool = False
    server_memory_read: bool = False
    destructive_db_actions: bool = False
    persistent_volume_deleted: bool = False
    containers: dict[str, LocalContainerStatus] | None = None
    server_health: LocalServerHealth | None = None

    def to_jsonable(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "command": self.command,
            "result": self.result,
            "runtime": self.plan.runtime_jsonable(
                files_rendered=self.plan.compose_file.exists(),
                containers_started=self.result in ("started", "running"),
            ),
            "dbeaver": self.plan.dbeaver_info().to_jsonable(),
            "diagnostics": [diagnostic.to_jsonable() for diagnostic in self.diagnostics],
            "created_file_count": len(self.created_files),
            "container_runtime_checked": self.container_runtime_checked,
            "container_runtime_available": self.container_runtime_available,
            "source_trees_mutated": self.source_trees_mutated,
            "graph_roots_read": self.graph_roots_read,
            "server_memory_read": self.server_memory_read,
            "destructive_db_actions": self.destructive_db_actions,
            "persistent_volume_deleted": self.persistent_volume_deleted,
            "containers": {
                key: status.to_jsonable()
                for key, status in (self.containers or {}).items()
            },
            "server_health": (
                self.server_health.to_jsonable()
                if self.server_health
                else LocalServerHealth(url=self.plan.server_health_url).to_jsonable()
            ),
            "network_exposure": {
                "bind_host": self.plan.bind_host,
                "postgres_bind_host": self.plan.postgres_bind_host,
                "localhost_only": (
                    self.plan.bind_host in ("127.0.0.1", "localhost", "::1")
                    and self.plan.postgres_bind_host in ("127.0.0.1", "localhost", "::1")
                ),
                "public_tunnel": False,
                "remote_postgres": False,
            },
        }
        return payload


def redact_runtime_text(value: str) -> str:
    redacted = value
    for key in ("POSTGRES_PASSWORD", "REPOMAP_PG_PASSWORD", "PGPASSWORD", "password"):
        redacted = re.sub(
            rf"({re.escape(key)}=)[^\s]+",
            r"\1[REDACTED]",
            redacted,
            flags=re.IGNORECASE,
        )
    return redacted


for _cls in (
    LocalRuntimeError,
    LocalRuntimeDiagnostic,
    LocalRuntimeIdentity,
    DBeaverInfo,
    LocalContainerStatus,
    LocalServerHealth,
    LocalRuntimePlan,
    LocalRuntimeResult,
):
    _cls.__module__ = "repomap_kg.runtime.plan"


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
    "SERVER_HEALTH_PATH",
    "redact_runtime_text",
]
