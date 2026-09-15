"""Canonical graph-file filters and deterministic SQL projection."""

from __future__ import annotations

from dataclasses import dataclass

from repomap_kg.graph.keys import GraphKeyError, file_key
from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.sql_core import (
    canonical_file_path_prefix,
    positive_limit,
    sql_like_prefix_literal,
    sql_literal,
)


GRAPH_FILE_DEFAULT_LIMIT = 50
GRAPH_FILE_MAX_LIMIT = 200
_TRI_STATE_FILTERS = frozenset(("include", "exclude", "only"))
_OBSERVATION_STATES = frozenset(("any", "observed", "referenced"))
_AMBIGUITY_FILTERS = frozenset(("include", "exclude", "only"))


@dataclass(frozen=True)
class GraphFileFilters:
    path: str | None = None
    path_prefix: str | None = None
    language: str | None = None
    role: str | None = None
    generated: str = "include"
    executable: str = "include"
    observation_state: str = "any"
    ambiguity: str = "include"


def build_graph_file_query_sql(
    repository_name: str,
    *,
    filters: GraphFileFilters,
    limit: int,
    offset: int,
) -> str:
    safe_limit, safe_offset = validate_graph_file_query(
        filters,
        limit=limit,
        offset=offset,
    )
    repository = sql_literal(repository_name)
    where_sql = " AND ".join(_filter_sql(filters)) or "TRUE"
    metadata_fields = {
        name: _metadata_array_sql(name)
        for name in (
            "language", "role", "generated", "executable",
            "binding_id", "binding_alias", "binding_role", "snapshot_id",
            "candidate_id", "source_relative_path",
        )
    }
    return (
        "WITH repo AS ("
        "SELECT id FROM repositories "
        f"WHERE name = {repository} ORDER BY id DESC LIMIT 1"
        "), file_nodes AS ("
        "SELECT canonical_nodes.id, canonical_nodes.canonical_key, "
        "canonical_nodes.graph_key_version, canonical_nodes.confidence, "
        "canonical_nodes.conflict, canonical_nodes.metadata_json "
        "FROM canonical_nodes "
        "WHERE canonical_nodes.repository_id = (SELECT id FROM repo) "
        "AND canonical_nodes.kind = 'file'"
        "), evidence_stats AS ("
        "SELECT file_nodes.id, "
        "COUNT(canonical_node_evidence.canonical_evidence_id)::int "
        "AS evidence_count, "
        "COUNT(canonical_evidence.id) FILTER "
        "(WHERE canonical_evidence.raw_kind = 'file')::int "
        "AS file_observation_count, "
        "COALESCE(to_jsonb(array_agg(DISTINCT canonical_node_evidence.link_kind "
        "ORDER BY canonical_node_evidence.link_kind) FILTER "
        "(WHERE canonical_node_evidence.link_kind IS NOT NULL)), '[]'::jsonb) "
        "AS link_kinds "
        "FROM file_nodes "
        "LEFT JOIN canonical_node_evidence "
        "ON canonical_node_evidence.canonical_node_id = file_nodes.id "
        "LEFT JOIN canonical_evidence "
        "ON canonical_evidence.id = canonical_node_evidence.canonical_evidence_id "
        "GROUP BY file_nodes.id"
        "), normalized AS ("
        "SELECT file_nodes.canonical_key, file_nodes.graph_key_version, "
        "file_nodes.confidence, file_nodes.conflict, "
        f"{metadata_fields['language']} AS languages, "
        f"{metadata_fields['role']} AS roles, "
        f"{metadata_fields['generated']} AS generated_states, "
        f"{metadata_fields['executable']} AS executable_states, "
        f"{metadata_fields['binding_id']} AS binding_id, "
        f"{metadata_fields['binding_alias']} AS binding_alias, "
        f"{metadata_fields['binding_role']} AS binding_role, "
        f"{metadata_fields['snapshot_id']} AS snapshot_id, "
        f"{metadata_fields['candidate_id']} AS candidate_id, "
        f"{metadata_fields['source_relative_path']} AS source_relative_path, "
        "COALESCE(evidence_stats.evidence_count, 0) AS evidence_count, "
        "COALESCE(evidence_stats.file_observation_count, 0) "
        "AS file_observation_count, "
        "COALESCE(evidence_stats.link_kinds, '[]'::jsonb) AS link_kinds "
        "FROM file_nodes LEFT JOIN evidence_stats ON evidence_stats.id = file_nodes.id"
        ") SELECT COALESCE(json_agg(json_build_object("
        "'canonical_key', canonical_key, "
        "'graph_key_version', graph_key_version, "
        "'confidence', confidence, "
        "'conflict', conflict, "
        "'metadata', jsonb_build_object("
        "'language', languages, 'role', roles, "
        "'generated', generated_states, 'executable', executable_states, "
        "'binding_id', binding_id, 'binding_alias', binding_alias, "
        "'binding_role', binding_role, 'snapshot_id', snapshot_id, "
        "'candidate_id', candidate_id, "
        "'source_relative_path', source_relative_path), "
        "'evidence_count', evidence_count, "
        "'file_observation_count', file_observation_count, "
        "'link_kinds', link_kinds"
        ") ORDER BY canonical_key), '[]'::json)::text FROM ("
        "SELECT * FROM normalized "
        f"WHERE {where_sql} ORDER BY canonical_key "
        f"LIMIT {safe_limit + 1} OFFSET {safe_offset}"
        ") AS graph_file_page;"
    )


def validate_graph_file_query(
    filters: GraphFileFilters,
    *,
    limit: int,
    offset: int,
) -> tuple[int, int]:
    if filters.path is not None and filters.path_prefix is not None:
        raise StorageSchemaError("cannot combine path and path prefix")
    if filters.generated not in _TRI_STATE_FILTERS:
        raise StorageSchemaError("invalid generated filter")
    if filters.executable not in _TRI_STATE_FILTERS:
        raise StorageSchemaError("invalid executable filter")
    if filters.observation_state not in _OBSERVATION_STATES:
        raise StorageSchemaError("invalid observation state filter")
    if filters.ambiguity not in _AMBIGUITY_FILTERS:
        raise StorageSchemaError("invalid ambiguity filter")
    for value, label in ((filters.language, "language"), (filters.role, "role")):
        if value is not None and not value:
            raise StorageSchemaError(f"{label} filter must not be empty")
    safe_limit = positive_limit(limit)
    if safe_limit > GRAPH_FILE_MAX_LIMIT:
        raise StorageSchemaError("limit must be between 1 and 200")
    try:
        safe_offset = int(offset)
    except (TypeError, ValueError) as error:
        raise StorageSchemaError("offset must be a non-negative integer") from error
    if safe_offset < 0:
        raise StorageSchemaError("offset must be a non-negative integer")
    return safe_limit, safe_offset


def _filter_sql(filters: GraphFileFilters) -> list[str]:
    clauses: list[str] = []
    if filters.path is not None:
        try:
            clauses.append(f"canonical_key = {sql_literal(file_key(filters.path))}")
        except GraphKeyError as error:
            raise StorageSchemaError("invalid canonical file path") from error
    if filters.path_prefix is not None:
        prefix = canonical_file_path_prefix(filters.path_prefix)
        clauses.append(
            "canonical_key LIKE "
            f"{sql_like_prefix_literal(prefix)} ESCAPE '\\'"
        )
    for field, value in (("languages", filters.language), ("roles", filters.role)):
        if value is not None:
            clauses.append(f"{field} @> jsonb_build_array({sql_literal(value)}::text)")
    clauses.extend(_boolean_filter_sql("generated_states", filters.generated))
    clauses.extend(_boolean_filter_sql("executable_states", filters.executable))
    if filters.observation_state == "observed":
        clauses.append("file_observation_count > 0")
    elif filters.observation_state == "referenced":
        clauses.append("file_observation_count = 0")
    ambiguity_sql = (
        "(conflict OR jsonb_array_length(languages) > 1 "
        "OR jsonb_array_length(roles) > 1 "
        "OR jsonb_array_length(generated_states) > 1 "
        "OR jsonb_array_length(executable_states) > 1)"
    )
    if filters.ambiguity == "only":
        clauses.append(ambiguity_sql)
    elif filters.ambiguity == "exclude":
        clauses.append(f"NOT {ambiguity_sql}")
    return clauses


def _boolean_filter_sql(field: str, mode: str) -> list[str]:
    if mode == "include":
        return []
    if mode == "only":
        return [f"{field} @> '[true]'::jsonb"]
    return [
        f"{field} @> '[false]'::jsonb",
        f"NOT ({field} @> '[true]'::jsonb)",
    ]


def _metadata_array_sql(field: str) -> str:
    value = f"file_nodes.metadata_json->'{field}'"
    return (
        f"CASE WHEN NOT (file_nodes.metadata_json ? '{field}') "
        f"OR {value} = 'null'::jsonb THEN '[]'::jsonb "
        f"WHEN jsonb_typeof({value}) = 'array' THEN {value} "
        f"ELSE jsonb_build_array({value}) END"
    )


__all__ = (
    "GRAPH_FILE_DEFAULT_LIMIT",
    "GRAPH_FILE_MAX_LIMIT",
    "GraphFileFilters",
    "build_graph_file_query_sql",
    "validate_graph_file_query",
)
