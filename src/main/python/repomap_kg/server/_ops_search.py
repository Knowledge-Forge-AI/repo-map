"""Search execution and SQL formatting for MCP operations."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable

from repomap_kg import __version__
from repomap_kg.ops.config import OpsConfig
from repomap_kg.ops.readback import (
    execute_ops_json_readback as default_execute_ops_json_readback,
)
from repomap_kg.server._ops_records import (
    McpOpsError,
    McpOpsGraphContext,
)
from repomap_kg.server._ops_sanitization import (
    raw_payload_policy,
    readback_path_markers,
    safety_markers,
    sanitize_jsonable,
)
from repomap_kg.server.mcp_search_sql import (
    build_mcp_search_sql as _build_mcp_search_sql,
)
from repomap_kg.storage.graph_readback_sql import (
    build_canonical_node_search_sql,
    build_file_source_search_sql,
    escape_readback_like_pattern,
)
from repomap_kg.storage import sql_literal


DEFAULT_SEARCH_LIMIT = 20
MAX_SEARCH_LIMIT = 100
MAX_QUERY_LENGTH = 200


def validate_query(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise McpOpsError("query is required")
    text = value.strip()
    if len(text) > MAX_QUERY_LENGTH:
        raise McpOpsError(f"query must be at most {MAX_QUERY_LENGTH} characters")
    return text


def validate_limit(value: int) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError) as error:
        raise McpOpsError("limit must be a positive integer") from error
    if limit < 1:
        raise McpOpsError("limit must be a positive integer")
    return min(limit, MAX_SEARCH_LIMIT)


def validate_offset(value: int) -> int:
    try:
        offset = int(value)
    except (TypeError, ValueError) as error:
        raise McpOpsError("offset must be a non-negative integer") from error
    if offset < 0:
        raise McpOpsError("offset must be a non-negative integer")
    return offset


def like_escape(value: str) -> str:
    return escape_readback_like_pattern(value)


def build_mcp_search_sql(
    *,
    root_path: str,
    target: str,
    query: str,
    kind: str | None = None,
    path: str | None = None,
    limit: int,
    offset: int,
    include_raw: bool,
    repository_identity: str | None = None,
) -> str:
    return _build_mcp_search_sql(
        root_path=root_path,
        target=target,
        query=query,
        kind=kind,
        path=path,
        limit=limit,
        offset=offset,
        include_raw=include_raw,
        node_search_sql=build_canonical_node_search_sql,
        file_search_sql=build_file_source_search_sql,
        sql_literal=sql_literal,
        like_escape=like_escape,
        error_type=McpOpsError,
        repository_identity=repository_identity,
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
    execute_readback_fn: Callable[..., Any] = default_execute_ops_json_readback,
    build_sql_fn: Callable[..., str] = build_mcp_search_sql,
    repository_identity: str | None = None,
) -> dict[str, Any]:
    sql = build_sql_fn(
        root_path=root_path,
        target=target,
        query=query,
        kind=kind,
        path=path,
        limit=limit,
        offset=offset,
        include_raw=include_raw,
        repository_identity=repository_identity,
    )
    payload = execute_readback_fn(
        config,
        database=database,
        sql=sql,
        label=f"{target} MCP search",
        expected_shape="array",
        mode="host_then_container",
        psql_command=psql_command,
    )
    if not isinstance(payload, list):
        raise McpOpsError("MCP search readback returned an object")
    has_more = len(payload) > limit
    rows = payload[:limit]
    return {
        "results": rows,
        "total": offset + len(rows),
        "has_more": has_more,
    }


@dataclass(frozen=True)
class OpsSearchDependencies:
    graph_context: Callable[..., McpOpsGraphContext]
    graph_payload: Callable[..., dict[str, Any]]
    query_mcp_search: Callable[..., Any] = query_mcp_search


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
    dependencies: OpsSearchDependencies,
) -> dict[str, Any]:
    context = dependencies.graph_context(graph_id, config_path=config_path)
    safe_query = validate_query(query)
    safe_limit = validate_limit(limit)
    safe_offset = validate_offset(offset)
    raw_payload = dependencies.query_mcp_search(
        context.config,
        database=context.database,
        root_path=context.root_path,
        target=target,
        query=safe_query,
        kind=kind,
        path=path,
        limit=safe_limit,
        offset=safe_offset,
        include_raw=include_raw,
        psql_command=context.psql_command,
        repository_identity=context.repository_identity,
    )
    results = list(raw_payload.get("results", ()))
    has_more = bool(raw_payload.get("has_more", False))
    if len(results) > safe_limit:
        has_more = True
        results = results[:safe_limit]
    payload = {
        "server": "repomap-kg",
        "version": __version__,
        "read_only": True,
        "graph": dependencies.graph_payload(context.graph, database=context.database),
        "target": target,
        "query": safe_query,
        "kind": kind,
        "path": path,
        "limit": safe_limit,
        "offset": safe_offset,
        "result_count": len(results),
        "total": int(raw_payload.get("total", safe_offset + len(results))),
        "has_more": has_more,
        "results": sanitize_jsonable(
            results,
            private_markers=readback_path_markers(context),
        ),
        "safety": safety_markers(),
    }
    if target == "observations":
        payload["raw_payload_policy"] = raw_payload_policy(include_raw)
    return payload
