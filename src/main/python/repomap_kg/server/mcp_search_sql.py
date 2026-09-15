"""SQL construction for read-only MCP search operations."""

from __future__ import annotations

from collections.abc import Callable


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
    node_search_sql: Callable[..., str],
    file_search_sql: Callable[..., str],
    sql_literal: Callable[[str], str],
    like_escape: Callable[[str], str],
    error_type: type[Exception],
) -> str:
    """Build the bounded SQL statement for one MCP search target."""

    if target == "nodes":
        return node_search_sql(
            root_path=root_path,
            query=query,
            kind=kind,
            limit=limit,
            offset=offset,
        )
    if target == "files":
        return file_search_sql(
            root_path=root_path,
            query=query,
            path=path,
            limit=limit,
            offset=offset,
        )
    fetch_limit = limit + 1
    pattern = sql_literal("%" + like_escape(query) + "%")
    root_filter = f"repositories.root_path = {sql_literal(root_path)}"
    if target == "observations":
        payload_field = ", raw_observations.payload_json AS payload" if include_raw else ""
        filters = [
            root_filter,
            "("
            f"raw_observations.kind ILIKE {pattern} ESCAPE '\\' OR "
            f"raw_observations.source_id ILIKE {pattern} ESCAPE '\\' OR "
            f"raw_observations.path ILIKE {pattern} ESCAPE '\\' OR "
            f"raw_observations.payload_json::text ILIKE {pattern} ESCAPE '\\'"
            ")",
        ]
        if kind is not None:
            filters.append(f"raw_observations.kind = {sql_literal(kind)}")
        if path is not None:
            filters.append(f"raw_observations.path = {sql_literal(path)}")
        where_sql = " AND ".join(filters)
        return (
            "SELECT COALESCE(json_agg(row_to_json(rows)), '[]'::json)::text "
            "FROM (SELECT raw_observations.ordinal, raw_observations.kind, "
            "raw_observations.source_id, raw_observations.path, "
            "raw_observations.payload_json->'metadata' AS metadata "
            f"{payload_field} "
            "FROM raw_observations "
            "JOIN repositories ON repositories.id = raw_observations.repository_id "
            f"WHERE {where_sql} "
            "ORDER BY raw_observations.run_id DESC, raw_observations.ordinal "
            f"OFFSET {offset} LIMIT {fetch_limit}) rows;"
        )
    raise error_type("search target must be nodes, observations, or files")
