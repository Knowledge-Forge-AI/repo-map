"""Read-only MCP helpers backed by unified operations TOML config."""

from __future__ import annotations

import os
from typing import Any

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
from repomap_kg.ops._refresh_queries import (
    query_refresh_status as query_refresh_status,
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
    checked_graph as checked_graph,
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
from repomap_kg.server.graph_selection import select_graph
from repomap_kg.server.investigation_read_store import (
    ConfiguredInvestigationGraph,
    GraphRefreshStatusQuery,
    InvestigationStoreBinding,
    InvestigationStorageQueries,
    LanguageSummaryQueries,
)
from repomap_kg.ops.config_local import LocalSqliteConfig
from repomap_kg.server.postgres_read_binding import postgres_investigation_stores
from repomap_kg.server.sqlite_read_binding import (
    SQLITE_DATABASE_SOURCE,
    SQLITE_STORAGE_LABEL,
    SqliteInvestigationStores,
)
from repomap_kg.storage import (
    query_canonical_neighborhood as query_canonical_neighborhood,
    query_canonical_storage_summary as query_canonical_storage_summary,
    query_js_framework_summary as query_js_framework_summary,
    query_nix_summary as query_nix_summary,
    query_openapi_summary as query_openapi_summary,
    query_python_summary as query_python_summary,
    query_terraform_summary as query_terraform_summary,
)

def investigation_storage_queries() -> InvestigationStorageQueries:
    """Bind the facade's investigation query owners at call time for the seam."""
    return InvestigationStorageQueries(
        refresh_status=query_refresh_status,
        search=query_mcp_search,
        storage_summary=query_canonical_storage_summary,
        neighborhood=query_canonical_neighborhood,
        language_summaries=LanguageSummaryQueries(
            python=query_python_summary,
            terraform=query_terraform_summary,
            openapi=query_openapi_summary,
            js_framework=query_js_framework_summary,
            nix=query_nix_summary,
        ),
    )


def investigation_stores(config: OpsConfig | LocalSqliteConfig) -> InvestigationStoreBinding:
    """Production investigation binding for the backend the home declares."""
    if isinstance(config, LocalSqliteConfig):
        return SqliteInvestigationStores(config)
    return postgres_investigation_stores(config, investigation_storage_queries())


def configured_graph(
    graph_id: str,
    *,
    config_path: str | os.PathLike[str] | None = None,
) -> ConfiguredInvestigationGraph:
    """Select a visible configured graph, then bind its investigation stores."""
    config = load_mcp_ops_config(config_path)
    selection = select_graph(config, graph_id)
    return ConfiguredInvestigationGraph(selection, investigation_stores(config))


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
        "database_source": (
            SQLITE_DATABASE_SOURCE
            if database == SQLITE_STORAGE_LABEL
            else "graph" if graph.database else "postgres-default"
        ),
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
            graph_payload(graph, database=_storage_label(config, graph))
            for graph in graphs
        ],
        "safety": safety_markers(),
    }


def _storage_label(config: OpsConfig | LocalSqliteConfig, graph: OpsGraphConfig) -> str:
    if isinstance(config, LocalSqliteConfig):
        return SQLITE_STORAGE_LABEL
    return graph_database(config, graph)


def graph_status_payload(
    graph_id: str,
    *,
    config_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    target = configured_graph(graph_id, config_path=config_path)
    selection = target.selection
    statuses = target.stores.investigation_store().refresh_statuses(
        GraphRefreshStatusQuery(graph_ids=(selection.graph_id,))
    )
    status = statuses.get(selection.graph_id)
    storage = (
        refresh_graph_status_payload(status, graph=selection.graph)
        if status is not None
        else None
    )
    return {
        "server": "repomap-kg",
        "version": __version__,
        "read_only": True,
        "graph": graph_payload(
            selection.graph, database=target.stores.storage_label(selection)
        ),
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
        graph = checked_graph(config, graph_id, require_readback=False)
        visible_by_id = {graph.id: graph}
    statuses = investigation_stores(config).investigation_store().refresh_statuses(
        GraphRefreshStatusQuery(graph_ids=tuple(visible_by_id))
    )
    graphs = []
    for graph in visible_by_id.values():
        status = statuses.get(graph.id)
        if status is None:
            continue
        payload = refresh_graph_status_payload(status, graph=graph)
        payload = {**payload, "warnings": graph_payload(graph)["warnings"]}
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
        configured_graph=configured_graph,
        graph_payload=graph_payload,
    )


def _ops_summary_dependencies() -> _ops_summaries_impl.OpsSummaryDependencies:
    return _ops_summaries_impl.OpsSummaryDependencies(
        configured_graph=configured_graph,
        graph_payload=graph_payload,
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
    repository_identity: str | None = None,
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
        repository_identity=repository_identity,
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
        dependencies=_ops_summary_dependencies(),
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
        dependencies=_ops_summary_dependencies(),
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
        dependencies=_ops_summary_dependencies(),
    )
