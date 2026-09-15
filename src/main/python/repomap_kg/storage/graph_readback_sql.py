"""Bounded canonical graph and file/source index SQL builders."""

from __future__ import annotations

from repomap_kg.storage.sql_core import sql_literal

__all__ = (
    "build_canonical_node_search_sql",
    "build_file_source_search_sql",
    "escape_readback_like_pattern",
)


def build_canonical_node_search_sql(
    *,
    root_path: str,
    query: str,
    kind: str | None,
    limit: int,
    offset: int,
) -> str:
    fetch_limit = limit + 1
    pattern = _search_pattern(query)
    filters = [
        f"repositories.root_path = {sql_literal(root_path)}",
        "canonical_nodes.graph_key_version = 1",
        "("
        f"canonical_nodes.canonical_key ILIKE {pattern} ESCAPE '\\' OR "
        f"canonical_nodes.kind ILIKE {pattern} ESCAPE '\\' OR "
        f"canonical_nodes.display_name ILIKE {pattern} ESCAPE '\\'"
        ")",
    ]
    if kind is not None:
        filters.append(f"canonical_nodes.kind = {sql_literal(kind)}")
    where_sql = " AND ".join(filters)
    return (
        "SELECT COALESCE(json_agg(row_to_json(rows)), '[]'::json)::text "
        "FROM (SELECT canonical_nodes.canonical_key, "
        "canonical_nodes.graph_key_version, canonical_nodes.kind, "
        "canonical_nodes.display_name, canonical_nodes.confidence, "
        "canonical_nodes.conflict, canonical_nodes.metadata_json AS metadata, "
        "canonical_nodes.first_seen_run_id, canonical_nodes.last_seen_run_id "
        "FROM canonical_nodes "
        "JOIN repositories ON repositories.id = canonical_nodes.repository_id "
        f"WHERE {where_sql} "
        "ORDER BY canonical_nodes.canonical_key "
        f"OFFSET {offset} LIMIT {fetch_limit}) rows;"
    )


def build_file_source_search_sql(
    *,
    root_path: str,
    query: str,
    path: str | None,
    limit: int,
    offset: int,
) -> str:
    fetch_limit = limit + 1
    pattern = _search_pattern(query)
    filters = [
        f"repositories.root_path = {sql_literal(root_path)}",
        "("
        f"files.path ILIKE {pattern} ESCAPE '\\' OR "
        f"files.language ILIKE {pattern} ESCAPE '\\' OR "
        f"files.role ILIKE {pattern} ESCAPE '\\'"
        ")",
    ]
    if path is not None:
        filters.append(f"files.path = {sql_literal(path)}")
    where_sql = " AND ".join(filters)
    return (
        "SELECT COALESCE(json_agg(row_to_json(rows)), '[]'::json)::text "
        "FROM (SELECT files.path, files.language, files.role, "
        "files.executable, files.generated "
        "FROM files "
        "JOIN repositories ON repositories.id = files.repository_id "
        f"WHERE {where_sql} "
        f"ORDER BY files.path OFFSET {offset} LIMIT {fetch_limit}) rows;"
    )


def escape_readback_like_pattern(value: str) -> str:
    """Escape one literal value for a PostgreSQL LIKE pattern."""

    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _search_pattern(query: str) -> str:
    return sql_literal("%" + escape_readback_like_pattern(query) + "%")
