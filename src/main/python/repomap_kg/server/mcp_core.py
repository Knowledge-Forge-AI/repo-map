"""Configuration and validation support for the RepoMap MCP server."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, TypeVar

from repomap_kg.server._mcp_core_validation import (
    RepoMapMcpError as RepoMapMcpError,
    first_config_value as first_config_value,
    optional_text as optional_text,
    private_storage_payload as private_storage_payload,
    require_non_blank as require_non_blank,
    validate_canonical_limit as validate_canonical_limit,
    validate_feed_item_key as validate_feed_item_key,
    validate_identity_metadata as validate_identity_metadata,
    validate_limit as validate_limit,
    validate_offset as validate_offset,
    validate_optional_text_filter as validate_optional_text_filter,
    validate_psql_command as validate_psql_command,
    validate_read_schema_version as validate_read_schema_version,
    validate_source_id_arg as validate_source_id_arg,
)
from repomap_kg.server.ops import (
    McpOpsError,
    McpOpsGraphContext,
    graph_context,
    query_configured_storage,
)
from repomap_kg.ops.config import PRIVATE_PRIVACY
from repomap_kg.storage import StorageSchemaError
from repomap_kg.storage.canonical_filters import (
    canonical_edge_filters_from_args as canonical_edge_filters_from_args,
    canonical_neighborhood_filters_from_args as canonical_neighborhood_filters_from_args,
    canonical_node_kind_from_args as canonical_node_kind_from_args,
)

ENV_PG_HOST = "REPOMAP_PG_HOST"
ENV_PG_PORT = "REPOMAP_PG_PORT"
ENV_PG_USER = "REPOMAP_PG_USER"
ENV_PG_DATABASE = "REPOMAP_PG_DATABASE"
ENV_PSQL_COMMAND = "REPOMAP_PSQL_COMMAND"
ENV_MCP_CONFIG = "REPOMAP_MCP_CONFIG"
PRIVATE_ROOT_DISPLAY = "[private-root]"
GRAPH_ROOT_DISPLAY = "[graph-root]"
PROJECT_ROOT_DISPLAY = "[project-root]"
EXPLICIT_ROOT_DISPLAY = "[explicit-root]"
PROJECT_DATABASE_DISPLAY = "[project-database]"
_STORAGE_TOPOLOGY_HINT = " Direct DB host-port exposure is disabled"
_StorageReadbackT = TypeVar("_StorageReadbackT")


def default_mcp_config_path() -> Path:
    return Path.home() / ".codex" / "codex-vc" / "mcp" / "repo-map" / "config.json"


def public_storage_error_message(error: BaseException) -> str:
    """Remove operational topology appended to an MCP storage error."""
    message = str(error)
    safe_reason, separator, _ = message.partition(_STORAGE_TOPOLOGY_HINT)
    if separator:
        return safe_reason.strip() or "storage readback failed"
    return message


@dataclass(frozen=True)
class StorageConnection:
    root_path: str
    pg_database: str
    root_path_display: str
    pg_host: str | None = None
    pg_port: str | None = None
    pg_user: str | None = None
    psql_command: str = "psql"
    project: str | None = None
    ops_context: McpOpsGraphContext | None = None

    def psql_args(self) -> list[str]:
        args: list[str] = []
        if self.pg_host:
            args.extend(["-h", self.pg_host])
        if self.pg_port:
            args.extend(["-p", self.pg_port])
        if self.pg_user:
            args.extend(["-U", self.pg_user])
        args.extend(["-d", self.pg_database])
        return args

    def query_storage(
        self,
        storage_query: Callable[..., _StorageReadbackT],
        **query_kwargs: Any,
    ) -> _StorageReadbackT:
        if self.ops_context is not None:
            return query_configured_storage(
                self.ops_context,
                storage_query,
                **query_kwargs,
            )
        return storage_query(
            self.psql_args(),
            psql_command=self.psql_command,
            **query_kwargs,
        )


@dataclass(frozen=True)
class McpProjectConfig:
    name: str
    root_path: str
    pg_database: str
    pg_host: str | None = None
    pg_port: str | None = None
    pg_user: str | None = None
    psql_command: str | None = None


@dataclass(frozen=True)
class McpConfig:
    default_project: str | None
    projects: dict[str, McpProjectConfig]
    allow_project_overrides: bool = False


def load_mcp_config(config_path: str | os.PathLike[str] | None = None) -> McpConfig:
    path, path_is_explicit = resolve_mcp_config_path(config_path)
    if not path.exists():
        if path_is_explicit:
            raise RepoMapMcpError(f"RepoMap MCP config does not exist: {path}")
        return McpConfig(default_project=None, projects={})
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise RepoMapMcpError(f"invalid RepoMap MCP config JSON: {error}") from error
    if not isinstance(payload, dict):
        raise RepoMapMcpError("RepoMap MCP config must be a JSON object")

    default_project = optional_text(payload.get("default_project"))
    projects_payload = payload.get("projects", {})
    if not isinstance(projects_payload, dict):
        raise RepoMapMcpError("RepoMap MCP config projects must be a JSON object")
    projects: dict[str, McpProjectConfig] = {}
    for name, project_payload in projects_payload.items():
        if not isinstance(name, str) or not name.strip():
            raise RepoMapMcpError("RepoMap MCP project names must be non-blank strings")
        if not isinstance(project_payload, dict):
            raise RepoMapMcpError(f"RepoMap MCP project {name!r} must be a JSON object")
        projects[name] = McpProjectConfig(
            name=name,
            root_path=require_non_blank(project_payload.get("root_path"), "root_path"),
            pg_database=require_non_blank(
                project_payload.get("pg_database"),
                "pg_database",
            ),
            pg_host=optional_text(project_payload.get("pg_host")),
            pg_port=optional_text(project_payload.get("pg_port")),
            pg_user=optional_text(project_payload.get("pg_user")),
            psql_command=optional_text(project_payload.get("psql_command")),
        )
    if default_project is not None and default_project not in projects:
        raise RepoMapMcpError(
            f"default_project {default_project!r} is not configured"
        )
    return McpConfig(
        default_project=default_project,
        projects=projects,
        allow_project_overrides=bool(payload.get("allow_project_overrides", False)),
    )


def resolve_mcp_config_path(
    config_path: str | os.PathLike[str] | None,
) -> tuple[Path, bool]:
    if config_path is not None:
        return Path(config_path).expanduser(), True
    environment_path = optional_text(os.environ.get(ENV_MCP_CONFIG))
    if environment_path is not None:
        return Path(environment_path).expanduser(), True
    return default_mcp_config_path(), False


def storage_connection(
    *,
    root_path: str | None = None,
    project: str | None = None,
    pg_database: str | None = None,
    pg_host: str | None = None,
    pg_port: str | int | None = None,
    pg_user: str | None = None,
    psql_command: str | None = None,
) -> StorageConnection:
    config = load_mcp_config()
    explicit_values = {
        "root_path": root_path,
        "pg_database": pg_database,
        "pg_host": pg_host,
        "pg_port": pg_port,
        "pg_user": pg_user,
        "psql_command": psql_command,
    }
    has_explicit_connection = any(
        value is not None for value in explicit_values.values()
    )

    project_name = optional_text(project)
    if project_name is not None:
        project_config = config.projects.get(project_name)
        if project_config is None:
            return graph_registry_storage_connection(
                project_name,
                has_explicit_connection=has_explicit_connection,
            )
        if has_explicit_connection and not config.allow_project_overrides:
            raise RepoMapMcpError(
                "project cannot be combined with explicit connection overrides"
            )
        root = require_non_blank(
            root_path if root_path is not None else project_config.root_path,
            "root_path",
        )
        database = require_non_blank(
            pg_database if pg_database is not None else project_config.pg_database,
            "pg_database",
        )
        host = optional_text(pg_host) if pg_host is not None else project_config.pg_host
        port = optional_text(pg_port) if pg_port is not None else project_config.pg_port
        user = optional_text(pg_user) if pg_user is not None else project_config.pg_user
        command = require_non_blank(
            (
                optional_text(psql_command)
                if psql_command is not None
                else (
                    project_config.psql_command
                    or optional_text(os.environ.get(ENV_PSQL_COMMAND))
                    or "psql"
                )
            ),
            "psql_command",
        )
        validate_psql_command(command)
        return StorageConnection(
            root_path=root,
            pg_database=database,
            root_path_display=PROJECT_ROOT_DISPLAY,
            pg_host=host,
            pg_port=port,
            pg_user=user,
            psql_command=command,
            project=project_name,
        )

    if not has_explicit_connection and config.default_project is not None:
        return storage_connection(project=config.default_project)

    root = require_non_blank(root_path, "root_path")
    database = require_non_blank(
        first_config_value(pg_database, ENV_PG_DATABASE),
        "pg_database",
    )
    command = require_non_blank(
        first_config_value(psql_command, ENV_PSQL_COMMAND, default="psql"),
        "psql_command",
    )
    validate_psql_command(command)
    return StorageConnection(
        root_path=root,
        pg_database=database,
        root_path_display=EXPLICIT_ROOT_DISPLAY,
        pg_host=first_config_value(pg_host, ENV_PG_HOST),
        pg_port=first_config_value(pg_port, ENV_PG_PORT),
        pg_user=first_config_value(pg_user, ENV_PG_USER),
        psql_command=command,
    )


def graph_registry_storage_connection(
    project_name: str,
    *,
    has_explicit_connection: bool,
) -> StorageConnection:
    if has_explicit_connection:
        raise RepoMapMcpError(
            "graph-registry project routing cannot be combined with explicit "
            "connection overrides"
        )
    try:
        context = graph_context(project_name)
    except McpOpsError as error:
        message = str(error)
        if message == f"unknown graph_id: {project_name}":
            raise RepoMapMcpError(
                "unknown legacy MCP project or graph-registry graph_id: "
                f"{project_name}"
            ) from error
        raise RepoMapMcpError(message) from error

    command = context.psql_command or "psql"
    validate_psql_command(command)
    private = context.graph.privacy in PRIVATE_PRIVACY
    return StorageConnection(
        root_path=context.root_path,
        pg_database=context.database,
        root_path_display=(
            PRIVATE_ROOT_DISPLAY if private else GRAPH_ROOT_DISPLAY
        ),
        pg_host=context.config.postgres.host,
        pg_port=str(context.config.postgres.port),
        pg_user=context.config.postgres.user,
        psql_command=command,
        project=project_name,
        ops_context=context,
    )


def validate_canonical_node_args(
    *,
    kind: str | None,
    canonical_key: str | None,
    path_prefix: str | None,
    graph_key_version: int,
) -> str | None:
    args = SimpleNamespace(
        kind=kind,
        canonical_key=canonical_key,
        path_prefix=path_prefix,
        graph_key_version=graph_key_version,
    )
    try:
        return canonical_node_kind_from_args(args)
    except StorageSchemaError as error:
        raise RepoMapMcpError(str(error)) from error


def validate_canonical_edge_args(
    *,
    kind: str | None,
    source_key: str | None,
    target_key: str | None,
    graph_key_version: int,
) -> None:
    args = SimpleNamespace(
        kind=kind,
        source_key=source_key,
        target_key=target_key,
        graph_key_version=graph_key_version,
    )
    try:
        canonical_edge_filters_from_args(args)
    except StorageSchemaError as error:
        raise RepoMapMcpError(str(error)) from error


def validate_canonical_neighborhood_args(
    *,
    node: str,
    direction: str,
    depth: int,
    graph_key_version: int,
) -> None:
    if direction not in {"both", "in", "out"}:
        raise RepoMapMcpError("direction must be one of both, in, out")
    args = SimpleNamespace(
        node=node,
        depth=depth,
        graph_key_version=graph_key_version,
    )
    try:
        canonical_neighborhood_filters_from_args(args)
    except StorageSchemaError as error:
        raise RepoMapMcpError(str(error)) from error
