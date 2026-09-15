"""Project and graph registry inventory helpers for RepoMap MCP server."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from repomap_kg.server.mcp_core import (
    PROJECT_DATABASE_DISPLAY,
    PROJECT_ROOT_DISPLAY,
    load_mcp_config as default_load_mcp_config,
)
from repomap_kg.server.ops import (
    graph_payload as default_graph_payload,
    load_mcp_ops_config as default_load_mcp_ops_config,
    visible_graphs as default_visible_graphs,
)


@dataclass(frozen=True)
class ProjectDependencies:
    load_mcp_config: Callable[..., Any] = default_load_mcp_config
    load_mcp_ops_config: Callable[..., Any] = default_load_mcp_ops_config
    visible_graphs: Callable[..., Any] = default_visible_graphs
    graph_payload: Callable[..., Any] = default_graph_payload


def repomap_projects(
    *,
    dependencies: ProjectDependencies | None = None,
) -> dict[str, Any]:
    deps = dependencies or ProjectDependencies()
    config = deps.load_mcp_config()
    graph_registry = graph_registry_projects_hint(dependencies=deps)
    return {
        "default_project": config.default_project,
        "allow_project_overrides": config.allow_project_overrides,
        "projects": [
            {
                "name": project.name,
                "default": project.name == config.default_project,
                "root_path": PROJECT_ROOT_DISPLAY,
                "pg_database": PROJECT_DATABASE_DISPLAY,
            }
            for project in sorted(config.projects.values(), key=lambda item: item.name)
        ],
        **graph_registry,
    }


def graph_registry_projects_hint(
    *,
    dependencies: ProjectDependencies | None = None,
) -> dict[str, Any]:
    deps = dependencies or ProjectDependencies()
    try:
        ops_config = deps.load_mcp_ops_config()
        graphs = deps.visible_graphs(ops_config)
    except (OSError, ValueError):
        return {
            "graph_registry_available": False,
            "graph_count": 0,
            "graphs": [],
            "message": (
                "legacy project config is active; graph registry inventory is "
                "unavailable"
            ),
        }

    graph_entries: list[dict[str, Any]] = []
    for graph in graphs:
        payload = deps.graph_payload(graph)
        graph_entries.append(
            {
                "graph_id": payload["graph_id"],
                "name": payload["name"],
                "repository_name": payload["repository_name"],
                "privacy": payload["privacy"],
                "private": payload["private"],
                "root_path_display": payload["root_path_display"],
                "root_path_expanded": payload["root_path_expanded"],
                "warnings": payload["warnings"],
            }
        )
    if graph_entries:
        message = (
            "graph registry is active; use repomap_list_graphs for the primary "
            "graph inventory"
        )
    else:
        message = "graph registry is active but has no MCP-visible graphs"
    return {
        "graph_registry_available": bool(graph_entries),
        "graph_count": len(graph_entries),
        "graphs": graph_entries,
        "message": message,
    }

