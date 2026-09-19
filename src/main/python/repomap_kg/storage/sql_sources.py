"""SQL builders for source and feed RepoMap storage readback."""

from __future__ import annotations

from repomap_kg.storage.graph_readback_sql import build_repository_select_sql
from repomap_kg.storage.sql_core import positive_limit, sql_literal

__all__ = (
    "build_ingested_source_query_sql",
    "build_source_summary_query_sql",
    "build_source_run_query_sql",
    "build_source_feed_item_query_sql",
    "build_source_reference_query_sql",
    "build_source_feed_item_explanation_query_sql",
    "source_observations_cte",
)


def build_ingested_source_query_sql(
    root_path: str,
    *,
    source_type: str | None = None,
    policy_status: str | None = None,
    limit: int = 50,
    repository_identity: str | None = None,
) -> str:
    filters = ["source_observations.metadata_json->>'source_id_configured' IS NOT NULL"]
    if source_type is not None:
        filters.append(f"source_observations.source_type = {sql_literal(source_type)}")
    if policy_status is not None:
        filters.append(f"source_observations.source_policy_status = {sql_literal(policy_status)}")
    where_sql = " AND ".join(filters)
    return (
        f"{source_observations_cte(root_path, repository_identity=repository_identity)} "
        "SELECT COALESCE(json_agg(json_build_object("
        "'source_id', source_id_configured, 'source_type', source_type, "
        "'display_name', display_name, 'policy_status', source_policy_status, "
        "'latest_source_run_id', latest_source_run_id, 'latest_artifact_id', latest_artifact_id, "
        "'latest_artifact_path', latest_artifact_path, 'latest_acquired_at', latest_acquired_at, "
        "'feed_observation_count', feed_observation_count, 'canonical_feed_item_count', canonical_feed_item_count"
        ") ORDER BY source_id_configured), '[]'::json)::text "
        "FROM ("
        "SELECT source_id_configured, MIN(source_type) AS source_type, "
        "MIN(source_display_name) AS display_name, MIN(source_policy_status) AS source_policy_status, "
        "(ARRAY_AGG(source_run_id ORDER BY source_acquired_at DESC NULLS LAST))[1] AS latest_source_run_id, "
        "(ARRAY_AGG(source_artifact_id ORDER BY source_acquired_at DESC NULLS LAST))[1] AS latest_artifact_id, "
        "(ARRAY_AGG(source_artifact_path ORDER BY source_acquired_at DESC NULLS LAST))[1] AS latest_artifact_path, "
        "MAX(source_acquired_at) AS latest_acquired_at, COUNT(*) AS feed_observation_count, "
        "COUNT(DISTINCT canonical_nodes.canonical_key) FILTER (WHERE canonical_nodes.kind = 'feed.item') AS canonical_feed_item_count "
        "FROM source_observations "
        "LEFT JOIN canonical_evidence ON canonical_evidence.raw_observation_id = source_observations.id "
        "AND canonical_evidence.repository_id = source_observations.repository_id "
        "LEFT JOIN canonical_node_evidence ON canonical_node_evidence.canonical_evidence_id = canonical_evidence.id "
        "LEFT JOIN canonical_nodes ON canonical_nodes.id = canonical_node_evidence.canonical_node_id "
        "AND canonical_nodes.repository_id = source_observations.repository_id "
        f"WHERE {where_sql} "
        f"GROUP BY source_id_configured ORDER BY source_id_configured LIMIT {positive_limit(limit)}"
        ") source_rows;"
    )


def build_source_summary_query_sql(
    root_path: str,
    *,
    source_id: str,
    repository_identity: str | None = None,
) -> str:
    source_filter = f"source_id_configured = {sql_literal(source_id)}"
    return (
        f"{source_observations_cte(root_path, repository_identity=repository_identity)} "
        "SELECT COALESCE(("
        "SELECT json_build_object("
        "'source_id', source_id_configured, 'source_type', MIN(source_type), "
        "'display_name', MIN(source_display_name), 'policy_status', MIN(source_policy_status), "
        "'configured_url_summary', MIN(acquisition_url_summary), "
        "'latest_source_run_id', (ARRAY_AGG(source_run_id ORDER BY source_acquired_at DESC NULLS LAST))[1], "
        "'latest_artifact_id', (ARRAY_AGG(source_artifact_id ORDER BY source_acquired_at DESC NULLS LAST))[1], "
        "'latest_artifact_path', (ARRAY_AGG(source_artifact_path ORDER BY source_acquired_at DESC NULLS LAST))[1], "
        "'latest_acquired_at', MAX(source_acquired_at), "
        "'feed_documents', COUNT(DISTINCT canonical_nodes.canonical_key) FILTER (WHERE canonical_nodes.kind = 'feed.document'), "
        "'feed_channels', COUNT(DISTINCT canonical_nodes.canonical_key) FILTER (WHERE canonical_nodes.kind = 'feed.channel'), "
        "'feed_items', COUNT(DISTINCT canonical_nodes.canonical_key) FILTER (WHERE canonical_nodes.kind = 'feed.item'), "
        "'feed_authors', COUNT(DISTINCT canonical_nodes.canonical_key) FILTER (WHERE canonical_nodes.kind = 'feed.author'), "
        "'feed_categories', COUNT(DISTINCT canonical_nodes.canonical_key) FILTER (WHERE canonical_nodes.kind = 'feed.category'), "
        "'link_references', COUNT(DISTINCT canonical_edges.id) FILTER "
        "(WHERE canonical_edges.edge_kind = 'references' AND canonical_edges.metadata_json->>'scope' = 'link'), "
        "'enclosure_references', COUNT(DISTINCT canonical_edges.id) FILTER "
        "(WHERE canonical_edges.edge_kind = 'references' AND canonical_edges.metadata_json->>'scope' = 'enclosure'), "
        "'parse_errors', COUNT(*) FILTER (WHERE source_observations.kind = 'feed.parse_error'), "
        "'known_limitations', json_build_array('source metadata is inferred from RSS2 evidence')"
        ") FROM source_observations "
        "LEFT JOIN canonical_evidence ON canonical_evidence.raw_observation_id = source_observations.id "
        "AND canonical_evidence.repository_id = source_observations.repository_id "
        "LEFT JOIN canonical_node_evidence ON canonical_node_evidence.canonical_evidence_id = canonical_evidence.id "
        "LEFT JOIN canonical_nodes ON canonical_nodes.id = canonical_node_evidence.canonical_node_id "
        "AND canonical_nodes.repository_id = source_observations.repository_id "
        "LEFT JOIN canonical_edge_evidence ON canonical_edge_evidence.canonical_evidence_id = canonical_evidence.id "
        "LEFT JOIN canonical_edges ON canonical_edges.id = canonical_edge_evidence.canonical_edge_id "
        "AND canonical_edges.repository_id = source_observations.repository_id "
        f"WHERE {source_filter} GROUP BY source_id_configured"
        "), json_build_object("
        f"'source_id', {sql_literal(source_id)}, 'source_type', null, 'display_name', null, "
        "'policy_status', 'unknown', 'configured_url_summary', null, "
        "'latest_source_run_id', null, 'latest_artifact_id', null, 'latest_artifact_path', null, "
        "'latest_acquired_at', null, 'feed_documents', 0, 'feed_channels', 0, 'feed_items', 0, "
        "'feed_authors', 0, 'feed_categories', 0, 'link_references', 0, 'enclosure_references', 0, "
        "'parse_errors', 0, 'known_limitations', json_build_array('source metadata unavailable')"
        "))::text;"
    )


def build_source_run_query_sql(
    root_path: str,
    *,
    source_id: str,
    limit: int = 25,
    repository_identity: str | None = None,
) -> str:
    return (
        f"{source_observations_cte(root_path, repository_identity=repository_identity)} "
        "SELECT COALESCE(json_agg(json_build_object("
        "'source_run_id', source_run_id, 'acquired_at', source_acquired_at, "
        "'artifact_id', source_artifact_id, 'artifact_path', source_artifact_path, "
        "'artifact_byte_length', source_artifact_bytes, 'artifact_sha256', source_artifact_sha256, "
        "'http_status', acquisition_http_status, 'content_type', acquisition_content_type, "
        "'observation_count', observation_count, 'status_summary', status_summary"
        ") ORDER BY source_acquired_at DESC NULLS LAST, source_run_id DESC), "
        "'[]'::json)::text FROM ("
        "SELECT source_run_id, "
        "MAX(source_acquired_at) AS source_acquired_at, MAX(source_artifact_id) AS source_artifact_id, "
        "MAX(source_artifact_path) AS source_artifact_path, MAX(source_artifact_bytes) AS source_artifact_bytes, "
        "MAX(source_artifact_sha256) AS source_artifact_sha256, MAX(acquisition_http_status) AS acquisition_http_status, "
        "MAX(acquisition_content_type) AS acquisition_content_type, COUNT(*) AS observation_count, "
        "CASE WHEN COUNT(*) FILTER (WHERE kind = 'feed.parse_error') > 0 "
        "THEN 'parse_errors' ELSE 'ok' END AS status_summary "
        "FROM source_observations "
        f"WHERE source_id_configured = {sql_literal(source_id)} "
        "AND source_run_id IS NOT NULL "
        "GROUP BY source_run_id "
        "ORDER BY source_acquired_at DESC NULLS LAST, source_run_id DESC "
        f"LIMIT {positive_limit(limit)}"
        ") run_rows;"
    )


def build_source_feed_item_query_sql(
    root_path: str,
    *,
    source_id: str,
    source_run_id: str | None = None,
    limit: int = 50,
    repository_identity: str | None = None,
) -> str:
    filters = [f"source_id_configured = {sql_literal(source_id)}"]
    if source_run_id is not None:
        filters.append(f"source_run_id = {sql_literal(source_run_id)}")
    where_sql = " AND ".join(filters)
    return (
        f"{source_observations_cte(root_path, repository_identity=repository_identity)} "
        "SELECT COALESCE(json_agg(item_rows.payload "
        "ORDER BY item_rows.published_at DESC NULLS LAST, item_rows.item_key), "
        "'[]'::json)::text "
        "FROM ("
        "SELECT canonical_nodes.canonical_key AS item_key, "
        "canonical_nodes.metadata_json->>'published_at' AS published_at, "
        "json_build_object("
        "'item_key', canonical_nodes.canonical_key, 'title', canonical_nodes.metadata_json->>'title', "
        "'published_at', canonical_nodes.metadata_json->>'published_at', 'updated_at', canonical_nodes.metadata_json->>'updated_at', "
        "'identity_source', canonical_nodes.metadata_json->>'identity_source', 'identity_strength', canonical_nodes.metadata_json->>'identity_strength', "
        "'duplicate_identity', COALESCE((canonical_nodes.metadata_json->>'duplicate_identity')::boolean, false), "
        "'link_targets', COALESCE(link_targets.targets, '[]'::json), 'authors', COALESCE(authors.names, '[]'::json), "
        "'categories', COALESCE(categories.names, '[]'::json), 'source_run_id', source_rows.source_run_id, "
        "'artifact_id', source_rows.source_artifact_id, 'artifact_path', source_rows.source_artifact_path"
        ") AS payload "
        "FROM canonical_nodes "
        "JOIN repo ON repo.id = canonical_nodes.repository_id "
        "JOIN ("
        "SELECT canonical_node_evidence.canonical_node_id, "
        "MAX(source_observations.source_run_id) AS source_run_id, "
        "MAX(source_observations.source_artifact_id) AS source_artifact_id, "
        "MAX(source_observations.source_artifact_path) AS source_artifact_path "
        "FROM source_observations "
        "JOIN canonical_evidence "
        "ON canonical_evidence.raw_observation_id = source_observations.id "
        "AND canonical_evidence.repository_id = source_observations.repository_id "
        "JOIN canonical_node_evidence "
        "ON canonical_node_evidence.canonical_evidence_id = canonical_evidence.id "
        f"WHERE {where_sql} "
        "GROUP BY canonical_node_evidence.canonical_node_id"
        ") source_rows ON source_rows.canonical_node_id = canonical_nodes.id "
        "LEFT JOIN LATERAL ("
        "SELECT json_agg(DISTINCT canonical_edges.target_canonical_key) AS targets "
        "FROM canonical_edges "
        "WHERE canonical_edges.repository_id = canonical_nodes.repository_id "
        "AND canonical_edges.source_canonical_key = canonical_nodes.canonical_key "
        "AND canonical_edges.edge_kind = 'references' "
        "AND canonical_edges.metadata_json->>'scope' IN ('link', 'enclosure')"
        ") link_targets ON true "
        "LEFT JOIN LATERAL ("
        "SELECT json_agg(DISTINCT target_nodes.display_name) AS names "
        "FROM canonical_edges "
        "JOIN canonical_nodes target_nodes "
        "ON target_nodes.canonical_key = canonical_edges.target_canonical_key "
        "AND target_nodes.repository_id = canonical_edges.repository_id "
        "WHERE canonical_edges.repository_id = canonical_nodes.repository_id "
        "AND canonical_edges.source_canonical_key = canonical_nodes.canonical_key "
        "AND canonical_edges.edge_kind = 'references' "
        "AND target_nodes.kind = 'feed.author'"
        ") authors ON true "
        "LEFT JOIN LATERAL ("
        "SELECT json_agg(DISTINCT target_nodes.display_name) AS names "
        "FROM canonical_edges "
        "JOIN canonical_nodes target_nodes "
        "ON target_nodes.canonical_key = canonical_edges.target_canonical_key "
        "AND target_nodes.repository_id = canonical_edges.repository_id "
        "WHERE canonical_edges.repository_id = canonical_nodes.repository_id "
        "AND canonical_edges.source_canonical_key = canonical_nodes.canonical_key "
        "AND canonical_edges.edge_kind = 'references' "
        "AND target_nodes.kind = 'feed.category'"
        ") categories ON true "
        "WHERE canonical_nodes.kind = 'feed.item' "
        "ORDER BY canonical_nodes.metadata_json->>'published_at' DESC NULLS LAST, "
        "canonical_nodes.canonical_key "
        f"LIMIT {positive_limit(limit)}"
        ") item_rows;"
    )


def build_source_reference_query_sql(
    root_path: str,
    *,
    source_id: str,
    source_run_id: str | None = None,
    target_kind: str | None = None,
    limit: int = 50,
    repository_identity: str | None = None,
) -> str:
    filters = [f"source_id_configured = {sql_literal(source_id)}"]
    if source_run_id is not None:
        filters.append(f"source_run_id = {sql_literal(source_run_id)}")
    if target_kind is not None:
        filters.append(f"split_part(canonical_edges.target_canonical_key, ':', 1) = {sql_literal(target_kind)}")
    where_sql = " AND ".join(filters)
    return (
        f"{source_observations_cte(root_path, repository_identity=repository_identity)} "
        "SELECT COALESCE(json_agg(reference_rows.payload "
        "ORDER BY reference_rows.source_item_key, reference_rows.target_key), "
        "'[]'::json)::text "
        "FROM ("
        "SELECT canonical_edges.source_canonical_key AS source_item_key, "
        "canonical_edges.target_canonical_key AS target_key, "
        "json_build_object("
        "'source_item_key', canonical_edges.source_canonical_key, 'relation', canonical_edges.edge_kind, "
        "'target_key', canonical_edges.target_canonical_key, 'target_display', canonical_edges.metadata_json->>'raw_target_summary', "
        "'not_fetched', COALESCE((canonical_edges.metadata_json->>'not_fetched')::boolean, true), "
        "'media_type', canonical_edges.metadata_json->>'mime_type', 'source_run_id', source_observations.source_run_id, "
        "'artifact_id', source_observations.source_artifact_id, 'artifact_path', source_observations.source_artifact_path"
        ") AS payload "
        "FROM canonical_edges "
        "JOIN repo ON repo.id = canonical_edges.repository_id "
        "JOIN canonical_edge_evidence "
        "ON canonical_edge_evidence.canonical_edge_id = canonical_edges.id "
        "JOIN canonical_evidence "
        "ON canonical_evidence.id = canonical_edge_evidence.canonical_evidence_id "
        "AND canonical_evidence.repository_id = canonical_edges.repository_id "
        "JOIN source_observations "
        "ON source_observations.id = canonical_evidence.raw_observation_id "
        "WHERE canonical_edges.edge_kind = 'references' "
        "AND split_part(canonical_edges.source_canonical_key, ':', 1) = 'feed.item' "
        f"AND {where_sql} "
        "ORDER BY canonical_edges.source_canonical_key, "
        "canonical_edges.target_canonical_key "
        f"LIMIT {positive_limit(limit)}"
        ") reference_rows;"
    )


def build_source_feed_item_explanation_query_sql(
    root_path: str,
    *,
    item_key: str,
    source_id: str | None = None,
    repository_identity: str | None = None,
) -> str:
    filters = [f"canonical_nodes.canonical_key = {sql_literal(item_key)}"]
    source_summary_filter = "source_id_configured IS NOT NULL"
    if source_id is not None:
        filters.append(f"source_observations.source_id_configured = {sql_literal(source_id)}")
        source_summary_filter += f" AND source_id_configured = {sql_literal(source_id)}"
    where_sql = " AND ".join(filters)
    return (
        f"{source_observations_cte(root_path, repository_identity=repository_identity)} "
        "SELECT json_build_object("
        "'item', ("
        "SELECT json_build_object("
        "'canonical_key', canonical_nodes.canonical_key, "
        "'graph_key_version', canonical_nodes.graph_key_version, "
        "'kind', canonical_nodes.kind, "
        "'display_name', canonical_nodes.display_name, "
        "'confidence', canonical_nodes.confidence, "
        "'conflict', canonical_nodes.conflict, "
        "'metadata', canonical_nodes.metadata_json"
        ") FROM canonical_nodes "
        "JOIN repo ON repo.id = canonical_nodes.repository_id "
        "JOIN canonical_node_evidence "
        "ON canonical_node_evidence.canonical_node_id = canonical_nodes.id "
        "JOIN canonical_evidence "
        "ON canonical_evidence.id = canonical_node_evidence.canonical_evidence_id "
        "AND canonical_evidence.repository_id = repo.id "
        "JOIN source_observations "
        "ON source_observations.id = canonical_evidence.raw_observation_id "
        f"WHERE {where_sql} "
        "LIMIT 1"
        "), "
        "'source', ("
        "SELECT json_build_object("
        "'source_id', source_id_configured, 'source_type', MIN(source_type), "
        "'policy_status', MIN(source_policy_status), 'source_run_id', MAX(source_run_id), "
        "'artifact_id', MAX(source_artifact_id), 'artifact_path', MAX(source_artifact_path), "
        "'acquired_at', MAX(source_acquired_at)"
        ") FROM source_observations "
        f"WHERE {source_summary_filter} "
        "GROUP BY source_id_configured "
        "ORDER BY MAX(source_acquired_at) DESC NULLS LAST "
        "LIMIT 1"
        "), "
        "'evidence', COALESCE(("
        "SELECT json_agg(json_build_object("
        "'evidence_key', canonical_evidence.evidence_key, 'raw_kind', canonical_evidence.raw_kind, "
        "'raw_source_id', canonical_evidence.raw_source_id, 'path', canonical_evidence.path, "
        "'start_line', canonical_evidence.start_line, 'end_line', canonical_evidence.end_line, "
        "'extractor', canonical_evidence.extractor, 'extractor_version', canonical_evidence.extractor_version, "
        "'confidence', canonical_evidence.confidence, 'metadata', canonical_evidence.metadata_json"
        ") ORDER BY canonical_evidence.raw_observation_ordinal) "
        "FROM canonical_nodes "
        "JOIN repo ON repo.id = canonical_nodes.repository_id "
        "JOIN canonical_node_evidence "
        "ON canonical_node_evidence.canonical_node_id = canonical_nodes.id "
        "JOIN canonical_evidence "
        "ON canonical_evidence.id = canonical_node_evidence.canonical_evidence_id "
        "AND canonical_evidence.repository_id = repo.id "
        "JOIN source_observations "
        "ON source_observations.id = canonical_evidence.raw_observation_id "
        f"WHERE {where_sql} "
        "), '[]'::json), "
        "'references', COALESCE(("
        "SELECT json_agg(json_build_object("
        "'target_key', canonical_edges.target_canonical_key, "
        "'metadata', canonical_edges.metadata_json"
        ") ORDER BY canonical_edges.target_canonical_key) "
        "FROM canonical_edges "
        "JOIN repo ON repo.id = canonical_edges.repository_id "
        f"WHERE canonical_edges.source_canonical_key = {sql_literal(item_key)} "
        "AND canonical_edges.edge_kind = 'references' "
        "), '[]'::json), "
        "'content_policy', 'full feed bodies are not exposed'"
        ")::text;"
    )


def source_observations_cte(
    root_path: str,
    repository_identity: str | None = None,
) -> str:
    repo_select = build_repository_select_sql(root_path, repository_identity)
    return (
        f"WITH repo AS ({repo_select}), source_observations AS ("
        "SELECT raw_observations.*, "
        "raw_observations.payload_json->'metadata' AS metadata_json, "
        "raw_observations.payload_json->'metadata'->>'source_id_configured' AS source_id_configured, "
        "raw_observations.payload_json->'metadata'->>'source_type' AS source_type, "
        "raw_observations.payload_json->'metadata'->>'source_display_name' AS source_display_name, "
        "raw_observations.payload_json->'metadata'->>'source_policy_status' AS source_policy_status, "
        "raw_observations.payload_json->'metadata'->>'source_run_id' AS source_run_id, "
        "raw_observations.payload_json->'metadata'->>'source_artifact_id' AS source_artifact_id, "
        "raw_observations.payload_json->'metadata'->>'source_artifact_path' AS source_artifact_path, "
        "raw_observations.payload_json->'metadata'->>'source_artifact_sha256' AS source_artifact_sha256, "
        "(raw_observations.payload_json->'metadata'->>'source_artifact_bytes')::bigint AS source_artifact_bytes, "
        "raw_observations.payload_json->'metadata'->>'source_acquired_at' AS source_acquired_at, "
        "(raw_observations.payload_json->'metadata'->>'acquisition_http_status')::int AS acquisition_http_status, "
        "raw_observations.payload_json->'metadata'->>'acquisition_content_type' AS acquisition_content_type, "
        "raw_observations.payload_json->'metadata'->>'acquisition_url_summary' AS acquisition_url_summary "
        "FROM raw_observations "
        "JOIN repo ON repo.id = raw_observations.repository_id "
        "WHERE raw_observations.payload_json->'metadata'->>'source_id_configured' IS NOT NULL"
        ")"
    )
