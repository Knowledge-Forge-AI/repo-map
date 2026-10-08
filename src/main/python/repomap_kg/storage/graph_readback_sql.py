"""Bounded canonical graph and file/source index SQL builders."""

from __future__ import annotations

from repomap_kg.storage.sql_core import sql_literal

__all__ = (
    "build_canonical_node_search_sql",
    "build_file_source_search_sql",
    "build_repository_filter_sql",
    "build_repository_select_sql",
    "escape_readback_like_pattern",
)


def build_repository_select_sql(
    root_path: str,
    repository_identity: str | None = None,
) -> str:
    """Return SQL SELECT query for matching repository ID by identity or root path."""
    from repomap_kg.storage.repository_identity import validate_repository_identity

    quoted_root = sql_literal(root_path)
    if repository_identity is not None:
        identity = validate_repository_identity(repository_identity)
        quoted_identity = sql_literal(identity)
        return (
            "SELECT id FROM repositories WHERE "
            f"repository_identity = {quoted_identity} "
            f"OR (repository_identity IS NULL AND root_path = {quoted_root}) "
            f"ORDER BY (repository_identity = {quoted_identity}) DESC NULLS LAST, id "
            "LIMIT 1"
        )
    return (
        "SELECT id FROM repositories WHERE "
        f"repositories.root_path = {quoted_root} "
        "ORDER BY id LIMIT 1"
    )


def build_repository_filter_sql(
    root_path: str,
    repository_identity: str | None = None,
) -> str:
    """Return SQL predicate matching repository by stable identity or root path."""
    if repository_identity is not None:
        return f"repositories.id = ({build_repository_select_sql(root_path, repository_identity)})"
    return f"repositories.root_path = {sql_literal(root_path)}"


def build_canonical_node_search_sql(
    *,
    root_path: str,
    query: str,
    kind: str | None,
    limit: int,
    offset: int,
    repository_identity: str | None = None,
) -> str:
    fetch_limit = limit + 1
    pattern = _search_pattern(query)
    repo_filter = build_repository_filter_sql(root_path, repository_identity)
    filters = [
        repo_filter,
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
    repository_identity: str | None = None,
) -> str:
    fetch_limit = limit + 1
    pattern = _search_pattern(query)
    repo_filter = build_repository_filter_sql(root_path, repository_identity)
    filters = [
        repo_filter,
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
