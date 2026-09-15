"""Shared records, context, and error classes for MCP operations."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from repomap_kg.ops.config import (
    OpsConfig,
    OpsGraphConfig,
    graph_database,
    load_ops_config,
    load_ops_config_home,
)
from repomap_kg.runtime.database_role_contract import (
    READ_STATUS_PASSWORD_ENV,
    project_read_status_config,
)

ENV_OPS_CONFIG = "REPOMAP_OPS_CONFIG"
ENV_PSQL_COMMAND = "REPOMAP_PSQL_COMMAND"


class McpOpsError(ValueError):
    """Raised when an MCP operations readback request is invalid."""


@dataclass(frozen=True)
class McpOpsGraphContext:
    config: OpsConfig
    graph: OpsGraphConfig
    psql_command: str | None

    @property
    def database(self) -> str:
        return graph_database(self.config, self.graph)

    @property
    def root_path(self) -> str:
        if self.graph.explicit_source_bindings:
            return f"graph:{self.graph.id}"
        return self.graph.root_path_expanded or self.graph.root_path

    @property
    def psql_args(self) -> list[str]:
        return self.config.postgres.psql_args_for_database(self.database)


def load_mcp_ops_config(config_path: str | os.PathLike[str] | None = None) -> OpsConfig:
    path_value = config_path or os.environ.get(ENV_OPS_CONFIG)
    if path_value:
        config = load_ops_config(Path(path_value).expanduser())
    else:
        config = load_ops_config_home()
    if READ_STATUS_PASSWORD_ENV in os.environ:
        return project_read_status_config(config)
    return config


def psql_command_from_environment() -> str | None:
    command = os.environ.get(ENV_PSQL_COMMAND)
    if command is None or not command.strip():
        return None
    if command == "psql":
        return None
    if any(character.isspace() for character in command):
        raise McpOpsError("psql command must not contain whitespace")
    if os.path.basename(command) != "psql":
        raise McpOpsError("psql command must name a psql executable")
    return command


def visible_graphs(config: OpsConfig) -> tuple[OpsGraphConfig, ...]:
    return tuple(graph for graph in config.graphs if graph.enabled and graph.mcp_visible)


def find_graph(config: OpsConfig, graph_id: str) -> OpsGraphConfig:
    if not isinstance(graph_id, str) or not graph_id.strip():
        raise McpOpsError("graph_id is required")
    for graph in config.graphs:
        if graph.id == graph_id:
            return graph
    raise McpOpsError(f"unknown graph_id: {graph_id}")


def graph_context(
    graph_id: str,
    *,
    config_path: str | os.PathLike[str] | None = None,
) -> McpOpsGraphContext:
    config = load_mcp_ops_config(config_path)
    graph = find_graph(config, graph_id)
    if not graph.enabled:
        raise McpOpsError(f"graph {graph_id!r} is not enabled")
    if graph.readback_unsupported_classification is not None:
        raise McpOpsError(graph.readback_unsupported_classification)
    if not graph.mcp_visible:
        raise McpOpsError(f"graph {graph_id!r} is not MCP-visible")
    return McpOpsGraphContext(
        config=config,
        graph=graph,
        psql_command=psql_command_from_environment(),
    )
