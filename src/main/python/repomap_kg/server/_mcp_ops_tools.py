"""Ops, search, and summary tools for the RepoMap MCP server."""

from __future__ import annotations

from typing import Any

from repomap_kg.server.mcp_core import (
    RepoMapMcpError,
    public_storage_error_message,
)
from repomap_kg.server.memory_bridge import (
    server_memory_search_payload,
    server_memory_summary_payload,
)
from repomap_kg.server.ops import (
    McpOpsError,
    graph_status_payload,
    list_graphs_payload,
    neighborhood_payload,
    project_summary_payload,
    refresh_status_payload,
    search_payload,
    summary_payload,
)
from repomap_kg.storage import StorageSchemaError


def ops_payload(function: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return function(*args, **kwargs)
    except McpOpsError as error:
        raise RepoMapMcpError(str(error)) from error
    except StorageSchemaError as error:
        raise RepoMapMcpError(public_storage_error_message(error)) from error
    except ValueError as error:
        raise RepoMapMcpError(str(error)) from error


def repomap_list_graphs() -> dict[str, Any]:
    return ops_payload(list_graphs_payload)


def repomap_graph_status(*, graph_id: str) -> dict[str, Any]:
    return ops_payload(graph_status_payload, graph_id)


def repomap_search_nodes(
    *,
    graph_id: str,
    query: str,
    kind: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    return ops_payload(
        search_payload,
        graph_id,
        target="nodes",
        query=query,
        kind=kind,
        limit=limit,
        offset=offset,
    )


def repomap_search_observations(
    *,
    graph_id: str,
    query: str,
    kind: str | None = None,
    path: str | None = None,
    limit: int = 20,
    offset: int = 0,
    include_raw: bool = False,
) -> dict[str, Any]:
    return ops_payload(
        search_payload,
        graph_id,
        target="observations",
        query=query,
        kind=kind,
        path=path,
        limit=limit,
        offset=offset,
        include_raw=include_raw,
    )


def repomap_search_files(
    *,
    graph_id: str,
    query: str,
    path: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    return ops_payload(
        search_payload,
        graph_id,
        target="files",
        query=query,
        path=path,
        limit=limit,
        offset=offset,
    )


def repomap_neighborhood(
    *,
    graph_id: str,
    node: str,
    direction: str = "both",
    depth: int = 1,
) -> dict[str, Any]:
    return ops_payload(
        neighborhood_payload,
        graph_id,
        node=node,
        direction=direction,
        depth=depth,
    )


def repomap_project_summary(*, graph_id: str) -> dict[str, Any]:
    return ops_payload(project_summary_payload, graph_id)


def repomap_python_summary(*, graph_id: str) -> dict[str, Any]:
    return ops_payload(summary_payload, graph_id, summary_kind="python")


def repomap_terraform_summary(*, graph_id: str) -> dict[str, Any]:
    return ops_payload(summary_payload, graph_id, summary_kind="terraform")


def repomap_openapi_summary(*, graph_id: str) -> dict[str, Any]:
    return ops_payload(summary_payload, graph_id, summary_kind="openapi")


def repomap_js_framework_summary(*, graph_id: str) -> dict[str, Any]:
    return ops_payload(summary_payload, graph_id, summary_kind="js_framework")


def repomap_nix_summary(*, graph_id: str) -> dict[str, Any]:
    return ops_payload(summary_payload, graph_id, summary_kind="nix")


def repomap_refresh_status(graph_id: str | None = None) -> dict[str, Any]:
    return ops_payload(refresh_status_payload, graph_id=graph_id)


def repomap_server_memory_summary() -> dict[str, Any]:
    return ops_payload(server_memory_summary_payload)


def repomap_server_memory_search(
    *,
    query: str,
    kind: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    return ops_payload(
        server_memory_search_payload,
        query=query,
        kind=kind,
        limit=limit,
        offset=offset,
    )
