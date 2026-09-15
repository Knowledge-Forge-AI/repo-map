"""Validation helpers for the read-only MCP JSON-RPC boundary."""

from __future__ import annotations

from typing import Any

from repomap_kg.server.mcp_core import RepoMapMcpError


def validated_tool_call_params(
    params: object,
    *,
    error_type: type[RepoMapMcpError] = RepoMapMcpError,
) -> tuple[str, dict[str, Any] | None]:
    """Validate and return the name and arguments for a ``tools/call`` request."""

    if not isinstance(params, dict):
        raise error_type("tools/call params must be a JSON object")
    name = params.get("name")
    if not isinstance(name, str):
        raise error_type("tool name must be a string")
    arguments = params.get("arguments")
    if arguments is not None and not isinstance(arguments, dict):
        raise error_type("tool arguments must be a JSON object")
    return name, arguments
