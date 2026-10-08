"""PostgreSQL compatibility context and config loading for MCP operations.

Logical graph selection and its refusals live in ``server.graph_selection`` and
are re-exported here for existing importers. :class:`McpOpsGraphContext` is the
PostgreSQL-specific context (database name, psql arguments, client command)
built only by the PostgreSQL binding and the ``graph_context`` compatibility
constructor; configured MCP tool paths select a neutral ``GraphSelection``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from repomap_kg.ops.config import (
    OpsConfig,
    OpsGraphConfig,
    graph_database,
)
from repomap_kg.ops.config_local import (
    LocalSqliteConfig,
    load_graph_registry_config,
    load_graph_registry_config_home,
)
from repomap_kg.ops.resolved_config import configured_repository_identity
from repomap_kg.runtime.database_role_contract import (
    READ_STATUS_PASSWORD_ENV,
    project_read_status_config,
)
from repomap_kg.server.graph_selection import (
    McpOpsError as McpOpsError,
    checked_graph as checked_graph,
    configured_graph_root_path,
    find_graph as find_graph,
    visible_graphs as visible_graphs,
)

ENV_OPS_CONFIG = "REPOMAP_OPS_CONFIG"
ENV_PSQL_COMMAND = "REPOMAP_PSQL_COMMAND"


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
        return configured_graph_root_path(self.graph)

    @property
    def repository_identity(self) -> str:
        return str(configured_repository_identity(self.graph.id))

    @property
    def psql_args(self) -> list[str]:
        return self.config.postgres.psql_args_for_database(self.database)


def load_mcp_ops_config(
    config_path: str | os.PathLike[str] | None = None,
) -> OpsConfig | LocalSqliteConfig:
    """Load the MCP graph registry as whichever backend the home declares."""
    path_value = config_path or os.environ.get(ENV_OPS_CONFIG)
    if path_value:
        config = load_graph_registry_config(Path(path_value).expanduser())
    else:
        config = load_graph_registry_config_home()
    if isinstance(config, OpsConfig) and READ_STATUS_PASSWORD_ENV in os.environ:
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


def graph_context(
    graph_id: str,
    *,
    config_path: str | os.PathLike[str] | None = None,
) -> McpOpsGraphContext:
    config = load_mcp_ops_config(config_path)
    if not isinstance(config, OpsConfig):
        raise McpOpsError("graph context is PostgreSQL-only; this home selects SQLite Local")
    graph = checked_graph(config, graph_id)
    return McpOpsGraphContext(
        config=config,
        graph=graph,
        psql_command=psql_command_from_environment(),
    )
