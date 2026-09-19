"""SQL builders for canonical RepoMap storage readback."""

from __future__ import annotations

from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.graph_readback_sql import build_repository_filter_sql
from repomap_kg.storage.sql_core import (
    canonical_file_path_prefix,
    positive_limit,
    require_supported_graph_key_version,
    sql_like_prefix_literal,
    sql_literal,
)

__all__ = (
    "build_canonical_node_query_sql",
    "build_canonical_edge_query_sql",
    "build_canonical_neighborhood_query_sql",
    "build_explain_canonical_edge_query_sql",
    "build_canonical_storage_summary_query_sql",
)


_NODE_OBJECT_SQL = (
    "'canonical_key', canonical_nodes.canonical_key, "
    "'graph_key_version', canonical_nodes.graph_key_version, "
    "'kind', canonical_nodes.kind, 'display_name', canonical_nodes.display_name, "
    "'confidence', canonical_nodes.confidence, 'conflict', canonical_nodes.conflict, "
    "'metadata', canonical_nodes.metadata_json, "
    "'first_seen_run_id', canonical_nodes.first_seen_run_id, "
    "'last_seen_run_id', canonical_nodes.last_seen_run_id"
)
_EDGE_OBJECT_SQL = (
    "'source_key', canonical_edges.source_canonical_key, "
    "'edge_kind', canonical_edges.edge_kind, "
    "'target_key', canonical_edges.target_canonical_key, "
    "'graph_key_version', canonical_edges.graph_key_version, "
    "'identity_metadata', canonical_edges.identity_metadata_json, "
    "'identity_metadata_hash', canonical_edges.identity_metadata_hash, "
    "'metadata', canonical_edges.metadata_json, "
    "'confidence', canonical_edges.confidence, 'conflict', canonical_edges.conflict, "
    "'first_seen_run_id', canonical_edges.first_seen_run_id, "
    "'last_seen_run_id', canonical_edges.last_seen_run_id"
)
_EDGE_ORDER_SQL = (
    "canonical_edges.source_canonical_key, canonical_edges.edge_kind, "
    "canonical_edges.target_canonical_key, canonical_edges.identity_metadata_hash"
)


def build_canonical_node_query_sql(
    root_path: str,
    *,
    kind: str | None = None,
    canonical_key: str | None = None,
    path_prefix: str | None = None,
    graph_key_version: int = 1,
    limit: int | None = None,
    offset: int = 0,
    repository_identity: str | None = None,
) -> str:
    require_supported_graph_key_version(graph_key_version)
    repo_filter = build_repository_filter_sql(root_path, repository_identity)
    filters = [repo_filter, f"canonical_nodes.graph_key_version = {graph_key_version}"]
    if kind is not None:
        filters.append(f"canonical_nodes.kind = {sql_literal(kind)}")
    if canonical_key is not None:
        filters.append(f"canonical_nodes.canonical_key = {sql_literal(canonical_key)}")
    if path_prefix is not None:
        filters.append(
            "canonical_nodes.canonical_key LIKE "
            f"{sql_like_prefix_literal(canonical_file_path_prefix(path_prefix))} "
            "ESCAPE '\\'"
        )
    where_sql = " AND ".join(filters)
    pagination_sql = _canonical_pagination_sql(limit=limit, offset=offset)
    if pagination_sql:
        return (
            f"SELECT COALESCE(json_agg(json_build_object({_NODE_OBJECT_SQL})"
            " ORDER BY canonical_nodes.canonical_key), '[]'::json)::text "
            "FROM (SELECT canonical_nodes.* FROM canonical_nodes "
            "JOIN repositories ON repositories.id = canonical_nodes.repository_id "
            f"WHERE {where_sql} ORDER BY canonical_nodes.canonical_key"
            f"{pagination_sql}) AS canonical_nodes;"
        )
    return (
        f"SELECT COALESCE(json_agg(json_build_object({_NODE_OBJECT_SQL})"
        " ORDER BY canonical_nodes.canonical_key), '[]'::json)::text "
        "FROM canonical_nodes "
        "JOIN repositories ON repositories.id = canonical_nodes.repository_id "
        f"WHERE {where_sql};"
    )


def build_canonical_edge_query_sql(
    root_path: str,
    *,
    kind: str | None = None,
    source_key: str | None = None,
    target_key: str | None = None,
    graph_key_version: int = 1,
    limit: int | None = None,
    offset: int = 0,
    repository_identity: str | None = None,
) -> str:
    require_supported_graph_key_version(graph_key_version)
    repo_filter = build_repository_filter_sql(root_path, repository_identity)
    filters = [repo_filter, f"canonical_edges.graph_key_version = {graph_key_version}"]
    if kind is not None:
        filters.append(f"canonical_edges.edge_kind = {sql_literal(kind)}")
    if source_key is not None:
        filters.append(f"canonical_edges.source_canonical_key = {sql_literal(source_key)}")
    if target_key is not None:
        filters.append(f"canonical_edges.target_canonical_key = {sql_literal(target_key)}")
    where_sql = " AND ".join(filters)
    pagination_sql = _canonical_pagination_sql(limit=limit, offset=offset)
    if pagination_sql:
        return (
            f"SELECT COALESCE(json_agg(json_build_object({_EDGE_OBJECT_SQL})"
            f" ORDER BY {_EDGE_ORDER_SQL}), '[]'::json)::text "
            "FROM (SELECT canonical_edges.* FROM canonical_edges "
            "JOIN repositories ON repositories.id = canonical_edges.repository_id "
            f"WHERE {where_sql} ORDER BY {_EDGE_ORDER_SQL}"
            f"{pagination_sql}) AS canonical_edges;"
        )
    return (
        f"SELECT COALESCE(json_agg(json_build_object({_EDGE_OBJECT_SQL})"
        f" ORDER BY {_EDGE_ORDER_SQL}), '[]'::json)::text "
        "FROM canonical_edges "
        "JOIN repositories ON repositories.id = canonical_edges.repository_id "
        f"WHERE {where_sql};"
    )


def _canonical_pagination_sql(*, limit: int | None, offset: int) -> str:
    if limit is None:
        if int(offset) != 0:
            raise StorageSchemaError("limit is required when offset is non-zero")
        return ""
    safe_limit = positive_limit(limit)
    try:
        safe_offset = int(offset)
    except (TypeError, ValueError) as error:
        raise StorageSchemaError(
            "offset must be a non-negative integer"
        ) from error
    if safe_offset < 0:
        raise StorageSchemaError("offset must be a non-negative integer")
    return f" LIMIT {safe_limit} OFFSET {safe_offset}"


def build_canonical_neighborhood_query_sql(
    root_path: str,
    *,
    node: str,
    direction: str = "both",
    graph_key_version: int = 1,
    node_limit: int | None = None,
    node_offset: int = 0,
    edge_limit: int | None = None,
    edge_offset: int = 0,
    repository_identity: str | None = None,
) -> str:
    require_supported_graph_key_version(graph_key_version)
    if direction not in {"both", "in", "out"}:
        raise StorageSchemaError("neighborhood direction must be one of both, in, out")
    quoted_node = sql_literal(node)
    edge_filters = []
    if direction in {"both", "out"}:
        edge_filters.append(f"canonical_edges.source_canonical_key = {quoted_node}")
    if direction in {"both", "in"}:
        edge_filters.append(f"canonical_edges.target_canonical_key = {quoted_node}")
    edge_filter_sql = " OR ".join(edge_filters)
    node_pagination_sql = _canonical_pagination_sql(limit=node_limit, offset=node_offset)
    edge_pagination_sql = _canonical_pagination_sql(limit=edge_limit, offset=edge_offset)
    repo_filter = build_repository_filter_sql(root_path, repository_identity)
    return (
        f"WITH repo AS (SELECT id FROM repositories WHERE {repo_filter} ORDER BY id DESC LIMIT 1), "
        "center AS ("
        "SELECT canonical_nodes.* FROM canonical_nodes "
        "JOIN repo ON repo.id = canonical_nodes.repository_id "
        f"WHERE canonical_nodes.graph_key_version = {graph_key_version} "
        f"AND canonical_nodes.canonical_key = {quoted_node}"
        "), "
        "all_neighborhood_edges AS ("
        "SELECT canonical_edges.* FROM canonical_edges "
        "JOIN repo ON repo.id = canonical_edges.repository_id "
        "JOIN center ON TRUE "
        f"WHERE canonical_edges.graph_key_version = {graph_key_version} "
        f"AND ({edge_filter_sql})"
        "), "
        "neighbor_keys AS ("
        "SELECT source_canonical_key AS canonical_key FROM all_neighborhood_edges "
        "UNION "
        "SELECT target_canonical_key AS canonical_key FROM all_neighborhood_edges"
        "), "
        "node_rows AS ("
        "SELECT canonical_nodes.* FROM canonical_nodes "
        "JOIN repo ON repo.id = canonical_nodes.repository_id "
        "JOIN neighbor_keys "
        "ON neighbor_keys.canonical_key = canonical_nodes.canonical_key "
        f"WHERE canonical_nodes.graph_key_version = {graph_key_version} "
        f"AND canonical_nodes.canonical_key <> {quoted_node}"
        " ORDER BY canonical_nodes.canonical_key"
        f"{node_pagination_sql}"
        "), "
        "edge_rows AS ("
        "SELECT canonical_edges.* FROM all_neighborhood_edges canonical_edges "
        "ORDER BY canonical_edges.source_canonical_key, "
        "canonical_edges.edge_kind, canonical_edges.target_canonical_key, "
        "canonical_edges.identity_metadata_hash"
        f"{edge_pagination_sql}"
        ") "
        "SELECT json_build_object("
        "'center', ("
        "SELECT json_build_object("
        "'canonical_key', canonical_nodes.canonical_key, "
        "'graph_key_version', canonical_nodes.graph_key_version, "
        "'kind', canonical_nodes.kind, "
        "'display_name', canonical_nodes.display_name, "
        "'confidence', canonical_nodes.confidence, "
        "'conflict', canonical_nodes.conflict, "
        "'metadata', canonical_nodes.metadata_json, "
        "'first_seen_run_id', canonical_nodes.first_seen_run_id, "
        "'last_seen_run_id', canonical_nodes.last_seen_run_id"
        ") FROM center canonical_nodes"
        "), "
        "'nodes', COALESCE(("
        "SELECT json_agg(json_build_object("
        "'canonical_key', canonical_nodes.canonical_key, "
        "'graph_key_version', canonical_nodes.graph_key_version, "
        "'kind', canonical_nodes.kind, "
        "'display_name', canonical_nodes.display_name, "
        "'confidence', canonical_nodes.confidence, "
        "'conflict', canonical_nodes.conflict, "
        "'metadata', canonical_nodes.metadata_json, "
        "'first_seen_run_id', canonical_nodes.first_seen_run_id, "
        "'last_seen_run_id', canonical_nodes.last_seen_run_id"
        ") ORDER BY canonical_nodes.canonical_key) "
        "FROM node_rows canonical_nodes"
        "), '[]'::json), "
        "'edges', COALESCE(("
        "SELECT json_agg(json_build_object("
        "'source_key', canonical_edges.source_canonical_key, "
        "'edge_kind', canonical_edges.edge_kind, "
        "'target_key', canonical_edges.target_canonical_key, "
        "'graph_key_version', canonical_edges.graph_key_version, "
        "'identity_metadata', canonical_edges.identity_metadata_json, "
        "'identity_metadata_hash', canonical_edges.identity_metadata_hash, "
        "'metadata', canonical_edges.metadata_json, "
        "'confidence', canonical_edges.confidence, "
        "'conflict', canonical_edges.conflict, "
        "'first_seen_run_id', canonical_edges.first_seen_run_id, "
        "'last_seen_run_id', canonical_edges.last_seen_run_id"
        ") ORDER BY canonical_edges.source_canonical_key, "
        "canonical_edges.edge_kind, "
        "canonical_edges.target_canonical_key, "
        "canonical_edges.identity_metadata_hash) "
        "FROM edge_rows canonical_edges"
        "), '[]'::json)"
        ")::text;"
    )


def build_explain_canonical_edge_query_sql(
    root_path: str,
    *,
    source_key: str,
    kind: str,
    target_key: str,
    identity_metadata_hash: str,
    graph_key_version: int = 1,
    evidence_limit: int | None = None,
    evidence_offset: int = 0,
    repository_identity: str | None = None,
) -> str:
    require_supported_graph_key_version(graph_key_version)
    repo_filter = build_repository_filter_sql(root_path, repository_identity)
    filters = [
        repo_filter,
        f"canonical_edges.graph_key_version = {graph_key_version}",
        f"canonical_edges.source_canonical_key = {sql_literal(source_key)}",
        f"canonical_edges.edge_kind = {sql_literal(kind)}",
        f"canonical_edges.target_canonical_key = {sql_literal(target_key)}",
        f"canonical_edges.identity_metadata_hash = {sql_literal(identity_metadata_hash)}",
    ]
    where_sql = " AND ".join(filters)
    evidence_pagination_sql = _canonical_pagination_sql(
        limit=evidence_limit,
        offset=evidence_offset,
    )
    return (
        "WITH matching_edge AS ("
        "SELECT canonical_edges.* "
        "FROM canonical_edges "
        "JOIN repositories ON repositories.id = canonical_edges.repository_id "
        f"WHERE {where_sql} "
        "LIMIT 1"
        "), "
        "edge_payload AS ("
        "SELECT json_build_object("
        "'source_key', matching_edge.source_canonical_key, "
        "'edge_kind', matching_edge.edge_kind, "
        "'target_key', matching_edge.target_canonical_key, "
        "'graph_key_version', matching_edge.graph_key_version, "
        "'identity_metadata', matching_edge.identity_metadata_json, "
        "'identity_metadata_hash', matching_edge.identity_metadata_hash, "
        "'metadata', matching_edge.metadata_json, "
        "'confidence', matching_edge.confidence, "
        "'conflict', matching_edge.conflict, "
        "'first_seen_run_id', matching_edge.first_seen_run_id, "
        "'last_seen_run_id', matching_edge.last_seen_run_id"
        ") AS edge "
        "FROM matching_edge"
        "), "
        "evidence_links AS ("
        "SELECT canonical_edge_evidence.* FROM matching_edge "
        "JOIN canonical_edge_evidence ON canonical_edge_evidence.canonical_edge_id = matching_edge.id "
        "JOIN canonical_evidence ON canonical_evidence.id = canonical_edge_evidence.canonical_evidence_id "
        "AND canonical_evidence.repository_id = matching_edge.repository_id "
        "ORDER BY canonical_evidence.run_id, canonical_evidence.raw_observation_ordinal, "
        "canonical_evidence.evidence_key, canonical_edge_evidence.link_kind"
        f"{evidence_pagination_sql}), "
        "evidence_payload AS ("
        "SELECT COALESCE(json_agg(json_build_object("
        "'evidence_key', canonical_evidence.evidence_key, "
        "'link_kind', evidence_links.link_kind, "
        "'raw_observation', json_build_object("
        "'run_id', canonical_evidence.run_id, "
        "'ordinal', canonical_evidence.raw_observation_ordinal, "
        "'payload_hash', raw_observations.payload_hash, "
        "'kind', COALESCE(raw_observations.kind, canonical_evidence.raw_kind), "
        "'source_id', COALESCE(raw_observations.source_id, canonical_evidence.raw_source_id)"
        "), "
        "'path', canonical_evidence.path, "
        "'start_line', canonical_evidence.start_line, "
        "'end_line', canonical_evidence.end_line, "
        "'extractor', canonical_evidence.extractor, "
        "'extractor_version', canonical_evidence.extractor_version, "
        "'confidence', canonical_evidence.confidence, "
        "'metadata', canonical_evidence.metadata_json"
        ") ORDER BY canonical_evidence.run_id, canonical_evidence.raw_observation_ordinal, "
        "canonical_evidence.evidence_key, evidence_links.link_kind), '[]'::json) AS evidence "
        "FROM matching_edge "
        "JOIN evidence_links ON evidence_links.canonical_edge_id = matching_edge.id "
        "JOIN canonical_evidence ON canonical_evidence.id = evidence_links.canonical_evidence_id "
        "AND canonical_evidence.repository_id = matching_edge.repository_id "
        "LEFT JOIN raw_observations ON raw_observations.id = canonical_evidence.raw_observation_id "
        "AND raw_observations.repository_id = matching_edge.repository_id) "
        "SELECT json_build_object('edge', (SELECT edge FROM edge_payload), "
        "'evidence', (SELECT evidence FROM evidence_payload))::text;"
    )


def build_canonical_storage_summary_query_sql(
    root_path: str, repository_identity: str | None = None,
) -> str:
    quoted_root = sql_literal(root_path)
    repo_filter = build_repository_filter_sql(root_path, repository_identity)
    return (
        f"WITH repo AS (SELECT id, name, root_path FROM repositories WHERE {repo_filter} ORDER BY id DESC LIMIT 1), "
        "latest_recorded_run AS ("
        "SELECT runs.* FROM runs JOIN repo ON repo.id = runs.repository_id "
        "ORDER BY runs.id DESC LIMIT 1) "
        "SELECT json_build_object("
        f"'root_path', {quoted_root}, "
        "'repository_name', (SELECT name FROM repo), "
        "'latest_run_id', (SELECT id FROM latest_recorded_run), "
        "'runs', (SELECT COUNT(*) FROM runs JOIN repo ON repo.id = runs.repository_id), "
        "'files', (SELECT COUNT(*) FROM files JOIN repo ON repo.id = files.repository_id), "
        "'raw_observations', (SELECT COUNT(*) FROM raw_observations JOIN repo ON repo.id = raw_observations.repository_id), "
        "'raw_observations_total', (SELECT COUNT(*) FROM raw_observations JOIN repo ON repo.id = raw_observations.repository_id), "
        "'latest_run_raw_observations', (SELECT COUNT(*) FROM raw_observations JOIN repo ON repo.id = raw_observations.repository_id WHERE raw_observations.run_id = (SELECT id FROM latest_recorded_run)), "
        "'canonical_nodes', (SELECT COUNT(*) FROM canonical_nodes JOIN repo ON repo.id = canonical_nodes.repository_id), "
        "'canonical_edges', (SELECT COUNT(*) FROM canonical_edges JOIN repo ON repo.id = canonical_edges.repository_id), "
        "'canonical_evidence', (SELECT COUNT(*) FROM canonical_evidence JOIN repo ON repo.id = canonical_evidence.repository_id)"
        ")::text;"
    )
