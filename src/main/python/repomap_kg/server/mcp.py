"""Minimal read-only MCP server for RepoMap canonical readback."""

from __future__ import annotations

# Same-name aliases are facade compatibility re-exports pinned by the ops helper-branch tests.
import os as os
import sys as sys
from typing import Any, TextIO

import repomap_kg.server._mcp_dispatch as _mcp_dispatch
import repomap_kg.server._mcp_projects as _mcp_projects
import repomap_kg.server._mcp_sources as _mcp_sources
import repomap_kg.server.mcp_canonical as _canonical_impl
from repomap_kg import __version__
from repomap_kg.graph.keys import GRAPH_KEY_VERSION
from repomap_kg.server._mcp_dispatch import (
    MCP_PROTOCOL_VERSION as MCP_PROTOCOL_VERSION,
    TOOL_FUNCTIONS as TOOL_FUNCTIONS,
    jsonrpc_error as jsonrpc_error,
    jsonrpc_result as jsonrpc_result,
)
from repomap_kg.server._mcp_ops_tools import (
    ops_payload as ops_payload,
    repomap_graph_status as repomap_graph_status,
    repomap_js_framework_summary as repomap_js_framework_summary,
    repomap_list_graphs as repomap_list_graphs,
    repomap_neighborhood as repomap_neighborhood,
    repomap_nix_summary as repomap_nix_summary,
    repomap_openapi_summary as repomap_openapi_summary,
    repomap_project_summary as repomap_project_summary,
    repomap_python_summary as repomap_python_summary,
    repomap_refresh_status as repomap_refresh_status,
    repomap_search_files as repomap_search_files,
    repomap_search_nodes as repomap_search_nodes,
    repomap_search_observations as repomap_search_observations,
    repomap_server_memory_search as repomap_server_memory_search,
    repomap_server_memory_summary as repomap_server_memory_summary,
    repomap_terraform_summary as repomap_terraform_summary,
)
from repomap_kg.server.mcp_core import (
    ENV_MCP_CONFIG as ENV_MCP_CONFIG,
    PROJECT_DATABASE_DISPLAY as PROJECT_DATABASE_DISPLAY,
    PROJECT_ROOT_DISPLAY as PROJECT_ROOT_DISPLAY,
    RepoMapMcpError as RepoMapMcpError,
    default_mcp_config_path as default_mcp_config_path,
    load_mcp_config as load_mcp_config,
    public_storage_error_message as public_storage_error_message,
    resolve_mcp_config_path as resolve_mcp_config_path,
    storage_connection as storage_connection,
    validate_canonical_edge_args as validate_canonical_edge_args,
    validate_canonical_limit as validate_canonical_limit,
    validate_canonical_neighborhood_args as validate_canonical_neighborhood_args,
    validate_canonical_node_args as validate_canonical_node_args,
    validate_identity_metadata as validate_identity_metadata,
    validate_offset as validate_offset,
    validate_read_schema_version as validate_read_schema_version,
)
from repomap_kg.server.mcp_schemas import tool_definitions as tool_definitions
from repomap_kg.server.ops import (
    graph_payload as graph_payload,
    load_mcp_ops_config as load_mcp_ops_config,
    visible_graphs as visible_graphs,
)
from repomap_kg.storage import (
    canonical_edge_explanation_to_jsonable as canonical_edge_explanation_to_jsonable,
    canonical_edge_records_to_jsonable as canonical_edge_records_to_jsonable,
    canonical_neighborhood_to_jsonable as canonical_neighborhood_to_jsonable,
    canonical_node_records_to_jsonable as canonical_node_records_to_jsonable,
    identity_metadata_hash as identity_metadata_hash,
    ingested_source_records_to_jsonable as ingested_source_records_to_jsonable,
    public_embedded_read_result_to_jsonable as public_embedded_read_result_to_jsonable,
    public_read_page as public_read_page,
    public_read_page_to_jsonable as public_read_page_to_jsonable,
    query_canonical_edge_explanation as query_canonical_edge_explanation,
    query_canonical_edge_records as query_canonical_edge_records,
    query_canonical_neighborhood as query_canonical_neighborhood,
    query_canonical_node_records as query_canonical_node_records,
    query_canonical_storage_summary as query_canonical_storage_summary,
    query_ingested_source_records as query_ingested_source_records,
    query_source_feed_item_explanation as query_source_feed_item_explanation,
    query_source_feed_item_records as query_source_feed_item_records,
    query_source_reference_records as query_source_reference_records,
    query_source_run_records as query_source_run_records,
    query_source_summary as query_source_summary,
    source_feed_item_records_to_jsonable as source_feed_item_records_to_jsonable,
    source_reference_records_to_jsonable as source_reference_records_to_jsonable,
    source_run_records_to_jsonable as source_run_records_to_jsonable,
    source_summary_to_jsonable as source_summary_to_jsonable,
)


def _canonical_tool_dependencies() -> _canonical_impl.CanonicalToolDependencies:
    return _canonical_impl.CanonicalToolDependencies(
        storage_connection=storage_connection,
        validate_canonical_node_args=validate_canonical_node_args,
        validate_canonical_edge_args=validate_canonical_edge_args,
        validate_canonical_neighborhood_args=validate_canonical_neighborhood_args,
        validate_identity_metadata=validate_identity_metadata,
        validate_limit=validate_canonical_limit,
        validate_offset=validate_offset,
        validate_read_schema_version=validate_read_schema_version,
        query_canonical_node_records=query_canonical_node_records,
        query_canonical_edge_records=query_canonical_edge_records,
        query_canonical_edge_explanation=query_canonical_edge_explanation,
        query_canonical_neighborhood=query_canonical_neighborhood,
        canonical_node_records_to_jsonable=canonical_node_records_to_jsonable,
        canonical_edge_records_to_jsonable=canonical_edge_records_to_jsonable,
        canonical_edge_explanation_to_jsonable=canonical_edge_explanation_to_jsonable,
        canonical_neighborhood_to_jsonable=canonical_neighborhood_to_jsonable,
        public_read_page=public_read_page,
        public_read_page_to_jsonable=public_read_page_to_jsonable,
        public_embedded_read_result_to_jsonable=public_embedded_read_result_to_jsonable,
        identity_metadata_hash=identity_metadata_hash,
    )


def _project_dependencies() -> _mcp_projects.ProjectDependencies:
    return _mcp_projects.ProjectDependencies(
        load_mcp_config=load_mcp_config,
        load_mcp_ops_config=load_mcp_ops_config,
        visible_graphs=visible_graphs,
        graph_payload=graph_payload,
    )


def repomap_projects() -> dict[str, Any]:
    return _mcp_projects.repomap_projects(dependencies=_project_dependencies())


def graph_registry_projects_hint() -> dict[str, Any]:
    return _mcp_projects.graph_registry_projects_hint(dependencies=_project_dependencies())


def _source_tool_dependencies() -> _mcp_sources.SourceToolDependencies:
    return _mcp_sources.SourceToolDependencies(
        storage_connection=storage_connection,
        query_ingested_source_records=query_ingested_source_records,
        ingested_source_records_to_jsonable=ingested_source_records_to_jsonable,
        query_source_summary=query_source_summary,
        source_summary_to_jsonable=source_summary_to_jsonable,
        query_source_run_records=query_source_run_records,
        source_run_records_to_jsonable=source_run_records_to_jsonable,
        query_source_feed_item_records=query_source_feed_item_records,
        source_feed_item_records_to_jsonable=source_feed_item_records_to_jsonable,
        query_source_feed_item_explanation=query_source_feed_item_explanation,
        query_source_reference_records=query_source_reference_records,
        source_reference_records_to_jsonable=source_reference_records_to_jsonable,
    )


def repomap_status(
    *,
    root_path: str | None = None,
    project: str | None = None,
    pg_database: str | None = None,
    pg_host: str | None = None,
    pg_port: str | int | None = None,
    pg_user: str | None = None,
    psql_command: str | None = None,
) -> dict[str, Any]:
    connection = storage_connection(
        root_path=root_path,
        project=project,
        pg_database=pg_database,
        pg_host=pg_host,
        pg_port=pg_port,
        pg_user=pg_user,
        psql_command=psql_command,
    )
    summary = connection.query_storage(
        query_canonical_storage_summary,
        root_path=connection.root_path,
    )
    payload = {
        "server": "repomap-kg",
        "version": __version__,
        "read_only": True,
        "root_path": summary.root_path,
        "repository_name": summary.repository_name,
        "graph_key_version": GRAPH_KEY_VERSION,
        "storage_model": "canonical",
        "counts": {
            "runs": summary.runs,
            "files": summary.files,
            "raw_observations": summary.raw_observations,
            "canonical_nodes": summary.canonical_nodes,
            "canonical_edges": summary.canonical_edges,
            "canonical_evidence": summary.canonical_evidence,
        },
    }
    payload["root_path"] = connection.root_path_display
    if connection.project is not None:
        payload["project"] = connection.project
    return payload


def repomap_canonical_nodes(
    *,
    root_path: str | None = None, project: str | None = None,
    pg_database: str | None = None, pg_host: str | None = None,
    pg_port: str | int | None = None, pg_user: str | None = None,
    psql_command: str | None = None, kind: str | None = None,
    canonical_key: str | None = None, path_prefix: str | None = None,
    graph_key_version: int = GRAPH_KEY_VERSION,
    limit: int = 50, offset: int = 0, result_schema_version: int = 1,
) -> dict[str, Any] | list[dict[str, Any]]:
    return _canonical_impl.canonical_nodes_payload(
        **locals(), dependencies=_canonical_tool_dependencies(),
    )


def repomap_canonical_edges(
    *,
    root_path: str | None = None, project: str | None = None,
    pg_database: str | None = None, pg_host: str | None = None,
    pg_port: str | int | None = None, pg_user: str | None = None,
    psql_command: str | None = None, kind: str | None = None,
    source_key: str | None = None, target_key: str | None = None,
    graph_key_version: int = GRAPH_KEY_VERSION,
    limit: int = 50, offset: int = 0, result_schema_version: int = 1,
) -> dict[str, Any] | list[dict[str, Any]]:
    return _canonical_impl.canonical_edges_payload(
        **locals(), dependencies=_canonical_tool_dependencies(),
    )


def repomap_explain_canonical_edge(
    *,
    root_path: str | None = None, project: str | None = None,
    pg_database: str | None = None, pg_host: str | None = None,
    pg_port: str | int | None = None, pg_user: str | None = None,
    psql_command: str | None = None,
    source_key: str, kind: str, target_key: str,
    identity_metadata: dict[str, Any] | None = None,
    graph_key_version: int = GRAPH_KEY_VERSION,
    evidence_limit: int = 50, evidence_offset: int = 0,
    result_schema_version: int = 1,
) -> dict[str, Any]:
    return _canonical_impl.canonical_edge_explanation_payload(
        **locals(), dependencies=_canonical_tool_dependencies(),
    )


def repomap_canonical_neighborhood(
    *,
    root_path: str | None = None, project: str | None = None,
    pg_database: str | None = None, pg_host: str | None = None,
    pg_port: str | int | None = None, pg_user: str | None = None,
    psql_command: str | None = None,
    node: str, direction: str = "both", depth: int = 1,
    graph_key_version: int = GRAPH_KEY_VERSION,
    node_limit: int = 50, node_offset: int = 0,
    edge_limit: int = 50, edge_offset: int = 0,
    result_schema_version: int = 1,
) -> dict[str, Any]:
    return _canonical_impl.canonical_neighborhood_payload(
        **locals(), dependencies=_canonical_tool_dependencies(),
    )


def repomap_ingested_sources(
    *,
    root_path: str | None = None, project: str | None = None,
    pg_database: str | None = None, pg_host: str | None = None,
    pg_port: str | int | None = None, pg_user: str | None = None,
    psql_command: str | None = None,
    source_type: str | None = None, policy_status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    return _mcp_sources.repomap_ingested_sources(**locals(), dependencies=_source_tool_dependencies())


def repomap_source_summary(
    *,
    source_id: str,
    root_path: str | None = None, project: str | None = None,
    pg_database: str | None = None, pg_host: str | None = None,
    pg_port: str | int | None = None, pg_user: str | None = None,
    psql_command: str | None = None,
) -> dict[str, Any]:
    return _mcp_sources.repomap_source_summary(**locals(), dependencies=_source_tool_dependencies())


def repomap_source_runs(
    *,
    source_id: str,
    root_path: str | None = None, project: str | None = None,
    pg_database: str | None = None, pg_host: str | None = None,
    pg_port: str | int | None = None, pg_user: str | None = None,
    psql_command: str | None = None, limit: int = 25,
) -> list[dict[str, Any]]:
    return _mcp_sources.repomap_source_runs(**locals(), dependencies=_source_tool_dependencies())


def repomap_source_feed_items(
    *,
    source_id: str,
    root_path: str | None = None, project: str | None = None,
    pg_database: str | None = None, pg_host: str | None = None,
    pg_port: str | int | None = None, pg_user: str | None = None,
    psql_command: str | None = None,
    source_run_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    return _mcp_sources.repomap_source_feed_items(**locals(), dependencies=_source_tool_dependencies())


def repomap_explain_source_feed_item(
    *,
    item_key: str,
    root_path: str | None = None, project: str | None = None,
    pg_database: str | None = None, pg_host: str | None = None,
    pg_port: str | int | None = None, pg_user: str | None = None,
    psql_command: str | None = None,
    source_id: str | None = None,
) -> dict[str, Any]:
    return _mcp_sources.repomap_explain_source_feed_item(**locals(), dependencies=_source_tool_dependencies())


def repomap_source_references(
    *,
    source_id: str,
    root_path: str | None = None, project: str | None = None,
    pg_database: str | None = None, pg_host: str | None = None,
    pg_port: str | int | None = None, pg_user: str | None = None,
    psql_command: str | None = None,
    source_run_id: str | None = None,
    target_kind: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    return _mcp_sources.repomap_source_references(**locals(), dependencies=_source_tool_dependencies())



def _resolve_tool(function_name: str) -> Any:
    return globals().get(function_name)


def tool_input_schema(name: str) -> dict[str, Any]:
    return _mcp_dispatch.tool_input_schema(name)


def validate_tool_call_arguments(name: str, arguments: dict[str, Any]) -> None:
    _mcp_dispatch.validate_tool_call_arguments(name, arguments, schema_fn=tool_input_schema)


def handle_tool_call(name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    return _mcp_dispatch.handle_tool_call(
        name,
        arguments,
        tool_resolver=_resolve_tool,
        tool_functions=TOOL_FUNCTIONS,
        validate_fn=validate_tool_call_arguments,
    )


def handle_jsonrpc_message(message: dict[str, Any]) -> dict[str, Any] | None:
    return _mcp_dispatch.handle_jsonrpc_message(
        message,
        protocol_version=MCP_PROTOCOL_VERSION,
        tool_caller=handle_tool_call,
    )


def serve_stdio(
    *,
    input_stream: TextIO = sys.stdin,
    output_stream: TextIO = sys.stdout,
) -> int:
    return _mcp_dispatch.serve_stdio(
        input_stream=input_stream,
        output_stream=output_stream,
        message_handler=handle_jsonrpc_message,
    )


def main() -> int:
    return serve_stdio()


if __name__ == "__main__":
    raise SystemExit(main())
