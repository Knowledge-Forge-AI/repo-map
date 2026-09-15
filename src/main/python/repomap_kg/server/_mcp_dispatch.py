"""Tool dispatch and stdio JSON-RPC transport for RepoMap MCP server."""

from __future__ import annotations

import json
import sys
from typing import Any, Callable, TextIO

from repomap_kg import __version__
from repomap_kg.server._ops_records import McpOpsError
from repomap_kg.server.mcp_core import (
    RepoMapMcpError,
    public_storage_error_message,
)
from repomap_kg.server.mcp_jsonrpc import validated_tool_call_params
from repomap_kg.server.mcp_schemas import tool_definitions
from repomap_kg.storage import StorageSchemaError

MCP_PROTOCOL_VERSION = "2024-11-05"

TOOL_FUNCTIONS: dict[str, str] = {
    "repomap_projects": "repomap_projects",
    "repomap_status": "repomap_status",
    "repomap_canonical_nodes": "repomap_canonical_nodes",
    "repomap_canonical_edges": "repomap_canonical_edges",
    "repomap_explain_canonical_edge": "repomap_explain_canonical_edge",
    "repomap_canonical_neighborhood": "repomap_canonical_neighborhood",
    "repomap_ingested_sources": "repomap_ingested_sources",
    "repomap_source_summary": "repomap_source_summary",
    "repomap_source_runs": "repomap_source_runs",
    "repomap_source_feed_items": "repomap_source_feed_items",
    "repomap_explain_source_feed_item": "repomap_explain_source_feed_item",
    "repomap_source_references": "repomap_source_references",
    "repomap_list_graphs": "repomap_list_graphs",
    "repomap_graph_status": "repomap_graph_status",
    "repomap_search_nodes": "repomap_search_nodes",
    "repomap_search_observations": "repomap_search_observations",
    "repomap_search_files": "repomap_search_files",
    "repomap_neighborhood": "repomap_neighborhood",
    "repomap_project_summary": "repomap_project_summary",
    "repomap_python_summary": "repomap_python_summary",
    "repomap_terraform_summary": "repomap_terraform_summary",
    "repomap_openapi_summary": "repomap_openapi_summary",
    "repomap_js_framework_summary": "repomap_js_framework_summary",
    "repomap_nix_summary": "repomap_nix_summary",
    "repomap_refresh_status": "repomap_refresh_status",
    "repomap_server_memory_summary": "repomap_server_memory_summary",
    "repomap_server_memory_search": "repomap_server_memory_search",
}


def tool_input_schema(name: str) -> dict[str, Any]:
    for tool in tool_definitions():
        if tool["name"] == name:
            return tool["inputSchema"]
    raise RepoMapMcpError(f"unknown RepoMap MCP tool: {name}")


def validate_tool_call_arguments(
    name: str,
    arguments: dict[str, Any],
    *,
    schema_fn: Callable[[str], dict[str, Any]] = tool_input_schema,
) -> None:
    schema = schema_fn(name)
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    allowed_names = set(properties)
    unexpected = sorted(set(arguments) - allowed_names)
    if unexpected:
        raise RepoMapMcpError(
            "unexpected argument(s): " + ", ".join(unexpected)
        )
    missing = sorted(name for name in required if name not in arguments)
    if missing:
        raise RepoMapMcpError(
            "missing required argument(s): " + ", ".join(missing)
        )


def handle_tool_call(
    name: str,
    arguments: dict[str, Any] | None,
    *,
    tool_resolver: Callable[[str], Callable[..., Any] | None] | None = None,
    tool_functions: dict[str, str] = TOOL_FUNCTIONS,
    validate_fn: Callable[[str, dict[str, Any]], None] = validate_tool_call_arguments,
) -> dict[str, Any]:
    function_name = tool_functions.get(name)
    if function_name is None:
        raise RepoMapMcpError(f"unknown RepoMap MCP tool: {name}")
    function = tool_resolver(function_name) if tool_resolver is not None else None
    if function is None:
        raise RepoMapMcpError(f"unknown RepoMap MCP tool: {name}")
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise RepoMapMcpError("tool arguments must be a JSON object")
    validate_fn(name, arguments)
    try:
        payload = function(**arguments)
    except TypeError as error:
        raise RepoMapMcpError(f"invalid tool arguments: {error}") from error
    except McpOpsError as error:
        raise RepoMapMcpError(str(error)) from error
    except StorageSchemaError as error:
        raise RepoMapMcpError(public_storage_error_message(error)) from error
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(payload, sort_keys=True),
            }
        ],
        "structuredContent": payload,
    }


def handle_jsonrpc_message(
    message: dict[str, Any],
    *,
    protocol_version: str = MCP_PROTOCOL_VERSION,
    tool_caller: Callable[[str, dict[str, Any] | None], dict[str, Any]] = handle_tool_call,
) -> dict[str, Any] | None:
    message_id = message.get("id")
    method = message.get("method")
    params = message.get("params") or {}
    if method == "initialize":
        return jsonrpc_result(
            message_id,
            {
                "protocolVersion": protocol_version,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "repomap-kg", "version": __version__},
            },
        )
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return jsonrpc_result(message_id, {"tools": tool_definitions()})
    if method == "tools/call":
        try:
            name, arguments = validated_tool_call_params(params, error_type=RepoMapMcpError)
            return jsonrpc_result(message_id, tool_caller(name, arguments))
        except RepoMapMcpError as error:
            return jsonrpc_result(
                message_id,
                {
                    "content": [{"type": "text", "text": str(error)}],
                    "structuredContent": {"error": str(error)},
                    "isError": True,
                },
            )
    return jsonrpc_error(message_id, -32601, f"method not found: {method}")


def jsonrpc_result(message_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def jsonrpc_error(message_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": message_id,
        "error": {"code": code, "message": message},
    }


def serve_stdio(
    *,
    input_stream: TextIO = sys.stdin,
    output_stream: TextIO = sys.stdout,
    message_handler: Callable[[dict[str, Any]], dict[str, Any] | None] = handle_jsonrpc_message,
) -> int:
    for line in input_stream:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
            if not isinstance(message, dict):
                raise ValueError("JSON-RPC message must be an object")
            response = message_handler(message)
        except Exception as error:  # pragma: no cover - defensive server boundary
            response = jsonrpc_error(None, -32700, str(error))
        if response is not None:
            print(json.dumps(response, sort_keys=True), file=output_stream, flush=True)
    return 0


def main(*, serve_fn: Callable[[], int] = serve_stdio) -> int:
    return serve_fn()
