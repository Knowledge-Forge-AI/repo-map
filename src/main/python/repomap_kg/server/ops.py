"""Read-only MCP helpers backed by unified operations TOML config."""

from __future__ import annotations

import os
from typing import Any, Callable, TypeVar

from repomap_kg import __version__
from repomap_kg.ops.config import (
    PRIVATE_PRIVACY,
    OpsConfig,
    OpsGraphConfig,
    graph_database,
    redact_text,
)
from repomap_kg.ops.readback import (
    execute_ops_json_readback as execute_ops_json_readback,
)
from repomap_kg.ops.refresh import (
    query_refresh_status as query_refresh_status,
    run_storage_readback_with_ops_psql as run_storage_readback_with_ops_psql,
)

from repomap_kg.server._ops_sanitization import (
    GRAPH_DATABASE_DISPLAY as GRAPH_DATABASE_DISPLAY,
    GRAPH_ROOT_DISPLAY as GRAPH_ROOT_DISPLAY,
    MAX_STRING_LENGTH as MAX_STRING_LENGTH,
    PRIVATE_DATABASE_DISPLAY as PRIVATE_DATABASE_DISPLAY,
    PRIVATE_PATH_DISPLAY as PRIVATE_PATH_DISPLAY,
    RAW_PAYLOAD_METADATA_SEMANTICS as RAW_PAYLOAD_METADATA_SEMANTICS,
    SAFE_VALUE_KEYS as SAFE_VALUE_KEYS,
    SUMMARY_ROOT_KEYS as SUMMARY_ROOT_KEYS,
    graph_database_display as graph_database_display,
    graph_root_display as graph_root_display,
    latest_run_consistency as latest_run_consistency,
    raw_payload_policy as raw_payload_policy,
    readback_path_markers as readback_path_markers,
    redacted_mapping_item as redacted_mapping_item,
    safety_markers as safety_markers,
    sanitize_jsonable as sanitize_jsonable,
    sanitize_summary_jsonable as sanitize_summary_jsonable,
    sanitize_text as sanitize_text,
    summary_root_value as summary_root_value,
    truncate_text as truncate_text,
)
from repomap_kg.server._ops_records import (
    ENV_OPS_CONFIG as ENV_OPS_CONFIG,
    ENV_PSQL_COMMAND as ENV_PSQL_COMMAND,
    McpOpsError as McpOpsError,
    McpOpsGraphContext as McpOpsGraphContext,
    find_graph as find_graph,
    graph_context as graph_context,
    load_mcp_ops_config as load_mcp_ops_config,
    psql_command_from_environment as psql_command_from_environment,
    visible_graphs as visible_graphs,
)
import repomap_kg.server._ops_search as _ops_search_impl
from repomap_kg.server._ops_search import (
    DEFAULT_SEARCH_LIMIT as DEFAULT_SEARCH_LIMIT,
    MAX_QUERY_LENGTH as MAX_QUERY_LENGTH,
    MAX_SEARCH_LIMIT as MAX_SEARCH_LIMIT,
    build_mcp_search_sql as build_mcp_search_sql,
    like_escape as like_escape,
    validate_limit as validate_limit,
    validate_offset as validate_offset,
    validate_query as validate_query,
)
import repomap_kg.server._ops_summaries as _ops_summaries_impl
from repomap_kg.storage import (
    query_canonical_neighborhood as query_canonical_neighborhood,
    query_canonical_storage_summary as query_canonical_storage_summary,
    query_js_framework_summary as query_js_framework_summary,
    query_nix_summary as query_nix_summary,
    query_openapi_summary as query_openapi_summary,
    query_python_summary as query_python_summary,
    query_terraform_summary as query_terraform_summary,
)

_StorageReadbackT = TypeVar("_StorageReadbackT")


def query_configured_storage(
    context: McpOpsGraphContext,
    storage_query: Callable[..., _StorageReadbackT],
    **query_kwargs: Any,
) -> _StorageReadbackT:
    return run_storage_readback_with_ops_psql(
        context.config,
        context.database,
        storage_query,
        psql_command=context.psql_command,
        **query_kwargs,
    )


def graph_payload(graph: OpsGraphConfig, *, database: str | None = None) -> dict[str, Any]:
    private = graph.privacy in PRIVATE_PRIVACY
    root_path_display = graph_root_display(graph)
    root_path_expanded = root_path_display
    warnings: list[dict[str, str]] = []
    if private:
        warnings.append(
            {
                "code": "private-graph-visible",
                "message": "graph is local/private and explicitly MCP-visible",
            }
        )
    return {
        "graph_id": graph.id,
        "name": redact_text(graph.name),
        "repository_name": graph.repository_name_display,
        "database": graph_database_display(graph, database),
        "database_source": "graph" if graph.database else "postgres-default",
        "privacy": graph.privacy,
        "enabled": graph.enabled,
        "mcp_visible": graph.mcp_visible,
        "private": private,
        "root_path_display": root_path_display,
        "root_path_expanded": root_path_expanded,
        "root_path_checked": False,
        "refresh_policy": graph.refresh_policy,
        "refresh_policy_status": (
            "implemented"
            if graph.refresh_policy in ("manual", "polling", "continuous")
            else "deferred"
        ),
        "warnings": warnings,
    }


def refresh_graph_status_payload(
    status: Any,
    *,
    graph: OpsGraphConfig | None = None,
) -> dict[str, Any]:
    payload = status.to_jsonable()
    if graph is not None:
        payload = {
            **payload,
            "database": graph_database_display(graph, payload.get("database")),
            "root_path_display": graph_root_display(graph),
            "root_path_expanded": graph_root_display(graph),
        }
    return {
        **payload,
        "latest_run_consistency": latest_run_consistency(payload),
    }


def list_graphs_payload(
    *,
    config_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    config = load_mcp_ops_config(config_path)
    graphs = visible_graphs(config)
    return {
        "server": "repomap-kg",
        "version": __version__,
        "read_only": True,
        "schema_version": config.schema_version,
        "graph_count": len(graphs),
        "hidden_graph_count": len(config.graphs) - len(graphs),
        "graphs": [
            graph_payload(graph, database=graph_database(config, graph))
            for graph in graphs
        ],
        "safety": safety_markers(),
    }


def graph_status_payload(
    graph_id: str,
    *,
    config_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    context = graph_context(graph_id, config_path=config_path)
    statuses = query_refresh_status(
        context.config,
        psql_command=context.psql_command,
    )
    status = statuses.get(context.graph.id)
    storage = (
        refresh_graph_status_payload(status, graph=context.graph)
        if status is not None
        else None
    )
    return {
        "server": "repomap-kg",
        "version": __version__,
        "read_only": True,
        "graph": graph_payload(context.graph, database=context.database),
        "storage": storage,
        "safety": safety_markers(),
    }


def refresh_status_payload(
    *,
    graph_id: str | None = None,
    config_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    config = load_mcp_ops_config(config_path)
    visible_by_id = {graph.id: graph for graph in visible_graphs(config)}
    if graph_id is not None:
        graph = find_graph(config, graph_id)
        if not graph.enabled:
            raise McpOpsError(f"graph {graph_id!r} is not enabled")
        if not graph.mcp_visible:
            raise McpOpsError(f"graph {graph_id!r} is not MCP-visible")
        visible_by_id = {graph.id: graph}
    statuses = query_refresh_status(config, psql_command=psql_command_from_environment())
    graphs = []
    for graph in visible_by_id.values():
        status = statuses.get(graph.id)
        if status is None:
            continue
        payload = refresh_graph_status_payload(status, graph=graph)
        payload = {
            **payload,
            "warnings": graph_payload(
                graph,
                database=graph_database(config, graph),
            )["warnings"],
        }
        graphs.append(sanitize_jsonable(payload))
    return {
        "server": "repomap-kg",
        "version": __version__,
        "read_only": True,
        "graph_count": len(graphs),
        "graphs": graphs,
        "safety": safety_markers(),
    }


def _ops_search_dependencies() -> _ops_search_impl.OpsSearchDependencies:
    return _ops_search_impl.OpsSearchDependencies(
        graph_context=graph_context,
        graph_payload=graph_payload,
        query_mcp_search=query_mcp_search,
    )


def _ops_summary_dependencies(
    *,
    query_storage_fn: Callable[..., Any] | None = None,
) -> _ops_summaries_impl.OpsSummaryDependencies:
    return _ops_summaries_impl.OpsSummaryDependencies(
        graph_context=graph_context,
        graph_payload=graph_payload,
        query_configured_storage=query_storage_fn or query_configured_storage,
        query_canonical_storage_summary=query_canonical_storage_summary,
        query_canonical_neighborhood=query_canonical_neighborhood,
        query_python_summary=query_python_summary,
        query_terraform_summary=query_terraform_summary,
        query_openapi_summary=query_openapi_summary,
        query_js_framework_summary=query_js_framework_summary,
        query_nix_summary=query_nix_summary,
    )


def query_mcp_search(
    config: OpsConfig,
    *,
    database: str,
    root_path: str,
    target: str,
    query: str,
    kind: str | None = None,
    path: str | None = None,
    limit: int = DEFAULT_SEARCH_LIMIT,
    offset: int = 0,
    include_raw: bool = False,
    psql_command: str | None = None,
) -> dict[str, Any]:
    return _ops_search_impl.query_mcp_search(
        config,
        database=database,
        root_path=root_path,
        target=target,
        query=query,
        kind=kind,
        path=path,
        limit=limit,
        offset=offset,
        include_raw=include_raw,
        psql_command=psql_command,
        execute_readback_fn=execute_ops_json_readback,
        build_sql_fn=build_mcp_search_sql,
    )


def search_payload(
    graph_id: str,
    *,
    target: str,
    query: str,
    kind: str | None = None,
    path: str | None = None,
    limit: int = DEFAULT_SEARCH_LIMIT,
    offset: int = 0,
    include_raw: bool = False,
    config_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    return _ops_search_impl.search_payload(
        graph_id,
        target=target,
        query=query,
        kind=kind,
        path=path,
        limit=limit,
        offset=offset,
        include_raw=include_raw,
        config_path=config_path,
        dependencies=_ops_search_dependencies(),
    )


def project_summary_payload(
    graph_id: str,
    *,
    config_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    return _ops_summaries_impl.project_summary_payload(
        graph_id,
        config_path=config_path,
        dependencies=_ops_summary_dependencies(
            query_storage_fn=query_configured_storage,
        ),
    )


def summary_payload(
    graph_id: str,
    *,
    summary_kind: str,
    config_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    return _ops_summaries_impl.summary_payload(
        graph_id,
        summary_kind=summary_kind,
        config_path=config_path,
        dependencies=_ops_summary_dependencies(
            query_storage_fn=query_configured_storage,
        ),
    )


def neighborhood_payload(
    graph_id: str,
    *,
    node: str,
    direction: str = "both",
    depth: int = 1,
    config_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    return _ops_summaries_impl.neighborhood_payload(
        graph_id,
        node=node,
        direction=direction,
        depth=depth,
        config_path=config_path,
        dependencies=_ops_summary_dependencies(
            query_storage_fn=query_configured_storage,
        ),
    )
