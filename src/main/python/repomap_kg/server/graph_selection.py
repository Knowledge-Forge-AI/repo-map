"""Backend-neutral logical graph selection for configured MCP tools.

Configured-graph tools first select a graph from the parsed operations config:
existence, enablement, readback support and MCP visibility refuse here with the
public texts, before any storage backend is bound. The resulting
:class:`GraphSelection` carries only what graph identity, privacy redaction and
safe presentation use: the maintained graph record and the config locations
treated as private path markers.

It carries no database name, host, port, user, password, client executable or
the credential-bearing ``OpsConfig``. Backend binding (for PostgreSQL:
``server.postgres_read_binding``; for SQLite Local:
``server.sqlite_read_binding``) receives a selection and owns those details.
Selection accepts any :class:`GraphRegistryConfig`: a PostgreSQL ``OpsConfig``
or a SQLite Local ``LocalSqliteConfig``, which has no PostgreSQL settings.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from repomap_kg.ops.config_helpers import PRIVATE_PRIVACY
from repomap_kg.ops.config_records import OpsGraphConfig
from repomap_kg.ops.graph_registry import GraphRegistryConfig
from repomap_kg.ops.resolved_config import configured_repository_identity

__all__ = (
    "GraphSelection",
    "McpOpsError",
    "checked_graph",
    "config_locations",
    "configured_graph_root_path",
    "find_graph",
    "graph_path_markers",
    "select_graph",
    "visible_graphs",
)


class McpOpsError(ValueError):
    """Raised when an MCP operations readback request is invalid."""


def visible_graphs(config: GraphRegistryConfig) -> tuple[OpsGraphConfig, ...]:
    return tuple(graph for graph in config.graphs if graph.enabled and graph.mcp_visible)


def find_graph(config: GraphRegistryConfig, graph_id: str) -> OpsGraphConfig:
    if not isinstance(graph_id, str) or not graph_id.strip():
        raise McpOpsError("graph_id is required")
    for graph in config.graphs:
        if graph.id == graph_id:
            return graph
    raise McpOpsError(f"unknown graph_id: {graph_id}")


def checked_graph(
    config: GraphRegistryConfig,
    graph_id: str,
    *,
    require_readback: bool = True,
) -> OpsGraphConfig:
    """Return an enabled, MCP-visible graph or raise the public refusal."""
    graph = find_graph(config, graph_id)
    if not graph.enabled:
        raise McpOpsError(f"graph {graph_id!r} is not enabled")
    if require_readback and graph.readback_unsupported_classification is not None:
        raise McpOpsError(graph.readback_unsupported_classification)
    if not graph.mcp_visible:
        raise McpOpsError(f"graph {graph_id!r} is not MCP-visible")
    return graph


@dataclass(frozen=True)
class GraphSelection:
    """One selected, visible configured graph; no backend or credential data."""

    graph: OpsGraphConfig
    config_locations: tuple[str, ...]

    @property
    def graph_id(self) -> str:
        return self.graph.id

    @property
    def private(self) -> bool:
        return self.graph.privacy in PRIVATE_PRIVACY

    @property
    def root_path(self) -> str:
        return configured_graph_root_path(self.graph)

    @property
    def repository_identity(self) -> str:
        return str(configured_repository_identity(self.graph.id))

    @property
    def path_markers(self) -> tuple[str, ...]:
        return graph_path_markers(self.graph, self.config_locations)


def select_graph(
    config: GraphRegistryConfig,
    graph_id: str,
    *,
    require_readback: bool = True,
) -> GraphSelection:
    """Select a configured graph, refusing with the public texts first."""
    graph = checked_graph(config, graph_id, require_readback=require_readback)
    return GraphSelection(graph=graph, config_locations=config_locations(config))


def config_locations(config: GraphRegistryConfig) -> tuple[str, ...]:
    values = (config.config_path, config.config_home, *config.config_files)
    return tuple(value for value in values if isinstance(value, str))


def configured_graph_root_path(graph: OpsGraphConfig) -> str:
    if graph.explicit_source_bindings:
        return f"graph:{graph.id}"
    return graph.root_path_expanded or graph.root_path


def graph_path_markers(
    graph: OpsGraphConfig,
    locations: tuple[str, ...],
) -> tuple[str, ...]:
    markers: set[str] = set()
    values = [
        graph.root_path,
        graph.root_path_expanded,
        *locations,
        str(Path.home()),
        Path.home().name,
    ]
    if graph.privacy in PRIVATE_PRIVACY:
        for binding in graph.effective_source_bindings:
            values.extend((binding.root_path, binding.root_path_expanded))
    for value in values:
        if isinstance(value, str):
            marker = value.strip()
            if marker and marker not in {".", "/", "~", "[private-root]"}:
                markers.add(marker)
    return tuple(sorted(markers, key=len, reverse=True))
