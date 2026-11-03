"""SQL builders for the disposable PostgreSQL JSONB evidence experiment (ADR 0137)."""

from __future__ import annotations

import inspect

from common_lore_index.storage.context_postgres_identity import (
    postgres_accepted_json_sql,
    postgres_accepted_run_cte_sql,
    postgres_repo_predicate_sql,
)
from common_lore_index.storage.postgres_navigation_sql import transport_budget_sql
from common_lore_index.storage.postgres_node_locations import (
    build_postgres_node_locations_sql,
)
from common_lore_index.storage.sql_core import sql_literal
from retrieval_jsonb_contracts import (
    DISPOSABLE_SCHEMA,
    GIN_OPS_INDEX,
    GIN_PATH_OPS_INDEX,
    JSONB_EXPERIMENT_POLICY_VERSION,
    PROJECTION_TABLE,
    STATE_TABLE,
    VARIANT_NAMES,
    JsonbFacetFilter,
    NamedEvidenceWorkloadItem,
    NodeLocationsQuery,
    _thaw_jsonable,
    decode_node_locations_payload,
    normalize_node_locations_result_for_equality,
    validate_evidence_metadata_facets,
)
from retrieval_semantic_representation import _require

_DEFAULT_ROLE_SQL = str(inspect.signature(build_postgres_node_locations_sql).parameters["role_sql"].default)


def _sql_valid_metadata_facets_predicate(col_expr: str = "e.metadata_json::jsonb") -> str:
    path_val = f"({col_expr} ->> 'source_relative_path')"
    return (
        f"({col_expr} IS NOT NULL AND jsonb_typeof({col_expr}) = 'object' "
        f"AND jsonb_typeof({col_expr} -> 'binding_id') = 'string' "
        f"AND length(btrim({col_expr} ->> 'binding_id')) > 0 "
        f"AND ({col_expr} ->> 'binding_id') = btrim({col_expr} ->> 'binding_id') "
        f"AND jsonb_typeof({col_expr} -> 'snapshot_id') = 'string' "
        f"AND length(btrim({col_expr} ->> 'snapshot_id')) > 0 "
        f"AND ({col_expr} ->> 'snapshot_id') = btrim({col_expr} ->> 'snapshot_id') "
        f"AND (NOT ({col_expr} ? 'source_relative_path') OR ("
        f"jsonb_typeof({col_expr} -> 'source_relative_path') = 'string' "
        f"AND length(btrim({path_val})) > 0 AND {path_val} = btrim({path_val}) "
        f"AND {path_val} ~ '^[^/\\\\:~[:cntrl:]][^\\\\:~[:cntrl:]]*$' "
        f"AND {path_val} !~ '(^|/)\\.\\.?(/|$)' "
        f"AND strpos({path_val}, '//') = 0)))"
    )


def _relational_facet_predicate_sql(facet_filter: JsonbFacetFilter | None) -> str:
    if facet_filter is None:
        return ""
    facet_filter.validate()
    preds = [
        _sql_valid_metadata_facets_predicate("e.metadata_json::jsonb"),
        f"(e.metadata_json::jsonb ->> 'binding_id') = {sql_literal(facet_filter.binding_id)}",
        f"(e.metadata_json::jsonb ->> 'snapshot_id') = {sql_literal(facet_filter.snapshot_id)}",
    ]
    if facet_filter.source_relative_path is not None:
        preds.append(
            f"(e.metadata_json::jsonb ->> 'source_relative_path') = {sql_literal(facet_filter.source_relative_path)}"
        )
    return "AND " + " AND ".join(preds)


def _jsonb_facet_predicate_sql(facet_filter: JsonbFacetFilter | None) -> str:
    if facet_filter is None:
        return ""
    pred = f"AND p.facet_doc IS NOT NULL AND p.facet_doc @> {sql_literal(facet_filter.to_containment_json())}::jsonb"
    if facet_filter.source_relative_path is not None:
        pred += f" AND (p.facet_doc ->> 'source_relative_path') = {sql_literal(facet_filter.source_relative_path)}"
    return pred


def build_relational_workload_sql(
    item: NamedEvidenceWorkloadItem, *, repository_identity: str | None, root_path: str
) -> str:
    """Build the relational baseline SQL for a workload item."""
    item.validate()
    base_sql = str(
        build_postgres_node_locations_sql(
            item.query,
            repository_identity=repository_identity,
            root_path=root_path,
            context_identity=item.context_identity,
        )
    )
    if item.facet_filter is None:
        return base_sql
    _require(
        base_sql.count("WHERE e.graph_key_version = 1") == 3,
        "relational_sql_anchor_drift",
        "Expected exactly 3 canonical_evidence anchor clauses in build_postgres_node_locations_sql",
    )
    return base_sql.replace(
        "WHERE e.graph_key_version = 1",
        f"WHERE e.graph_key_version = 1\n      {_relational_facet_predicate_sql(item.facet_filter)}",
    )


def _live_evidence_cte_sql() -> str:
    ev_fp = (
        "COALESCE((SELECT md5(string_agg(concat_ws('|', e_fp.id::text, e_fp.run_id::text, "
        "e_fp.raw_observation_ordinal::text, e_fp.evidence_key, COALESCE(e_fp.path, ''), "
        "COALESCE(e_fp.start_line::text, ''), COALESCE(e_fp.end_line::text, ''), COALESCE(e_fp.extractor, ''), "
        "COALESCE(e_fp.extractor_version, ''), COALESCE(e_fp.confidence::text, ''), "
        "COALESCE(e_fp.metadata_json::text, '')), '#' ORDER BY e_fp.id ASC)) "
        "FROM public.canonical_evidence e_fp WHERE e_fp.repository_id = mr.repository_id AND e_fp.graph_key_version = 1), 'empty') "
        "|| ':' || "
        "COALESCE((SELECT md5(string_agg(concat_ws('|', lnk_fp.canonical_node_id::text, "
        "lnk_fp.canonical_evidence_id::text, lnk_fp.link_kind), '#' "
        "ORDER BY lnk_fp.canonical_node_id ASC, lnk_fp.canonical_evidence_id ASC, lnk_fp.link_kind ASC)) "
        "FROM public.canonical_node_evidence lnk_fp "
        "JOIN public.canonical_nodes cn_fp ON cn_fp.id = lnk_fp.canonical_node_id "
        "AND cn_fp.repository_id = mr.repository_id AND cn_fp.graph_key_version = 1), 'empty')"
    )
    return (
        "live_ev AS MATERIALIZED (\n"
        "  SELECT mr.repository_id,\n"
        "    COALESCE((SELECT MAX(e2.run_id) FROM public.canonical_evidence e2 WHERE e2.repository_id = mr.repository_id AND e2.graph_key_version = 1), 0) AS max_evidence_run_id,\n"
        "    COALESCE((SELECT COUNT(*) FROM public.canonical_evidence e3 WHERE e3.repository_id = mr.repository_id AND e3.graph_key_version = 1), 0) AS total_evidence_row_count,\n"
        f"    ({ev_fp}) AS evidence_fingerprint\n"
        "  FROM matched_repo mr\n"
        ")"
    )


def build_jsonb_projection_ddl_sql(
    *, repository_identity: str | None, root_path: str, context_identity: bool = False
) -> str:
    """Build population-wide disposable JSONB projection DDL/DML pinned to live accepted publication."""
    repo_pred = postgres_repo_predicate_sql(repository_identity, root_path, context_identity=context_identity)
    valid_pred = _sql_valid_metadata_facets_predicate("e.metadata_json::jsonb")
    facet_expr = (
        f"CASE WHEN e.metadata_json IS NOT NULL AND {valid_pred} "
        "THEN jsonb_strip_nulls(jsonb_build_object('binding_id', e.metadata_json::jsonb -> 'binding_id', "
        "'snapshot_id', e.metadata_json::jsonb -> 'snapshot_id', 'source_relative_path', "
        "CASE WHEN e.metadata_json::jsonb ? 'source_relative_path' "
        "THEN e.metadata_json::jsonb -> 'source_relative_path' ELSE NULL END)) ELSE NULL END"
    )
    return (
        f"DROP TABLE IF EXISTS {PROJECTION_TABLE} RESTRICT;\n"
        f"DROP TABLE IF EXISTS {STATE_TABLE} RESTRICT;\n"
        f"CREATE TABLE {STATE_TABLE} (repository_id bigint PRIMARY KEY, accepted_run_id bigint NOT NULL, "
        f"accepted_generation bigint, publication_job_id text, publication_attempt integer, "
        f"publication_bundle_id text, snapshot_manifest_id text, extraction_receipt_id text, graph_candidate_id text, "
        f"source_generation text, config_generation text, extractor_generation text, canonicalizer_generation text, "
        f"snapshot_vector_json text, max_evidence_run_id bigint NOT NULL, total_evidence_row_count bigint NOT NULL, "
        f"evidence_fingerprint text NOT NULL, malformed_metadata_count bigint NOT NULL, projected_row_count bigint NOT NULL);\n"
        f"CREATE TABLE {PROJECTION_TABLE} (repository_id bigint NOT NULL, canonical_node_id bigint NOT NULL, "
        f"canonical_key text NOT NULL, evidence_key text NOT NULL, link_kind text NOT NULL, run_id bigint NOT NULL, "
        f"raw_observation_ordinal integer NOT NULL, payload_hash text, raw_kind text, raw_source_id text, path text, "
        f"start_line integer, end_line integer, extractor text, extractor_version text, confidence text, metadata_json jsonb, "
        f"publication_bundle_id text, snapshot_manifest_id text, extraction_receipt_id text, graph_candidate_id text, "
        f"snapshot_vector_json text, evidence_role text NOT NULL, facet_doc jsonb);\n"
        f"WITH matched_repo AS MATERIALIZED (SELECT repo.id AS repository_id FROM public.repositories repo WHERE {repo_pred} ORDER BY repo.id DESC LIMIT 1),\n"
        f"{postgres_accepted_run_cte_sql(context_identity=context_identity)},\n"
        f"{_live_evidence_cte_sql()},\n"
        f"inserted_rows AS (\n"
        f"  INSERT INTO {PROJECTION_TABLE}\n"
        f"  SELECT subject.repository_id, subject.id, subject.canonical_key, e.evidence_key, link.link_kind, e.run_id, e.raw_observation_ordinal, "
        f"raw.payload_hash, e.raw_kind, e.raw_source_id, e.path, e.start_line, e.end_line, e.extractor, e.extractor_version, "
        f"e.confidence::text, e.metadata_json, r.publication_bundle_id, r.snapshot_manifest_id, r.extraction_receipt_id, "
        f"r.graph_candidate_id, r.snapshot_vector_json, ({_DEFAULT_ROLE_SQL}) AS evidence_role, {facet_expr} AS facet_doc\n"
        f"  FROM public.canonical_node_evidence link\n"
        f"  JOIN public.canonical_nodes subject ON subject.id = link.canonical_node_id AND subject.graph_key_version = 1\n"
        f"  JOIN matched_repo mr ON mr.repository_id = subject.repository_id JOIN accepted_run acc ON TRUE\n"
        f"  JOIN public.canonical_evidence e ON e.id = link.canonical_evidence_id AND e.repository_id = subject.repository_id AND e.graph_key_version = 1\n"
        f"  LEFT JOIN public.raw_observations raw ON raw.repository_id = e.repository_id AND raw.run_id = e.run_id AND raw.ordinal = e.raw_observation_ordinal\n"
        f"  JOIN public.runs r ON r.id = e.run_id RETURNING repository_id, metadata_json, facet_doc\n"
        f")\n"
        f"INSERT INTO {STATE_TABLE}\n"
        f"SELECT mr.repository_id, acc.run_id, acc.generation, r_acc.publication_job_id, r_acc.publication_attempt, "
        f"r_acc.publication_bundle_id, r_acc.snapshot_manifest_id, r_acc.extraction_receipt_id, r_acc.graph_candidate_id, "
        f"r_acc.source_generation, r_acc.config_generation, r_acc.extractor_generation, r_acc.canonicalizer_generation, "
        f"r_acc.snapshot_vector_json, live_ev.max_evidence_run_id, live_ev.total_evidence_row_count, live_ev.evidence_fingerprint, "
        f"COALESCE((SELECT count(*) FROM inserted_rows ir WHERE ir.metadata_json IS NOT NULL AND ir.metadata_json <> '{{}}'::jsonb AND ir.facet_doc IS NULL), 0), "
        f"COALESCE((SELECT count(*) FROM inserted_rows), 0) "
        f"FROM matched_repo mr JOIN accepted_run acc ON TRUE JOIN public.runs r_acc ON r_acc.id = acc.run_id "
        f"JOIN live_ev ON live_ev.repository_id = mr.repository_id;\n"
        f"ANALYZE {PROJECTION_TABLE};\nANALYZE {STATE_TABLE};"
    )


def build_jsonb_workload_sql(
    item: NamedEvidenceWorkloadItem, *, repository_identity: str | None, root_path: str
) -> str:
    """Build single-statement node_locations SQL against the disposable JSONB projection with live-publication correspondence."""
    item.validate()
    query = item.query
    repo_pred = postgres_repo_predicate_sql(repository_identity, root_path, context_identity=item.context_identity)
    role_filter_sql = f"AND p.evidence_role = {sql_literal(query.evidence_role)}" if query.evidence_role != "all" else ""
    facet_sql = _jsonb_facet_predicate_sql(item.facet_filter)
    window_limit = int(query.limit) + 1
    target_display_col = ", cn.display_name" if item.context_identity else ""
    extra_node_cols = ", 'kind', tn.kind, 'display_name', tn.display_name" if item.context_identity else ""
    cols = (
        "p.evidence_key, p.link_kind, p.run_id, p.raw_observation_ordinal, p.payload_hash, p.raw_kind, p.raw_source_id, "
        "p.path, p.start_line, p.end_line, p.extractor, p.extractor_version, p.confidence, p.metadata_json, "
        "p.publication_bundle_id, p.snapshot_manifest_id, p.extraction_receipt_id, p.graph_candidate_id, p.snapshot_vector_json, p.evidence_role"
    )
    order_clause = 'ORDER BY p.run_id DESC, p.raw_observation_ordinal ASC, p.evidence_key COLLATE "C" ASC, p.link_kind COLLATE "C" ASC'
    cand_col = "acc.graph_candidate_id" if item.context_identity else "r_acc.graph_candidate_id"
    return (
        f"WITH matched_repo AS MATERIALIZED (SELECT repo.id AS repository_id FROM public.repositories repo WHERE {repo_pred} ORDER BY repo.id DESC LIMIT 1),\n"
        f"{postgres_accepted_run_cte_sql(context_identity=item.context_identity)},\n"
        f"{_live_evidence_cte_sql()},\n"
        f"live_projection AS MATERIALIZED (\n"
        f"  SELECT st.repository_id, st.malformed_metadata_count FROM {STATE_TABLE} st\n"
        f"  JOIN matched_repo mr ON mr.repository_id = st.repository_id\n"
        f"  JOIN accepted_run acc ON st.accepted_run_id = acc.run_id AND st.accepted_generation IS NOT DISTINCT FROM acc.generation\n"
        f"  JOIN public.runs r_acc ON r_acc.id = acc.run_id\n"
        f"  JOIN live_ev ON live_ev.repository_id = st.repository_id\n"
        f"  WHERE st.publication_bundle_id IS NOT DISTINCT FROM r_acc.publication_bundle_id\n"
        f"    AND st.snapshot_manifest_id IS NOT DISTINCT FROM r_acc.snapshot_manifest_id\n"
        f"    AND st.extraction_receipt_id IS NOT DISTINCT FROM r_acc.extraction_receipt_id\n"
        f"    AND st.graph_candidate_id = {cand_col}\n"
        f"    AND st.publication_job_id IS NOT DISTINCT FROM r_acc.publication_job_id\n"
        f"    AND st.publication_attempt IS NOT DISTINCT FROM r_acc.publication_attempt\n"
        f"    AND st.source_generation IS NOT DISTINCT FROM r_acc.source_generation\n"
        f"    AND st.config_generation IS NOT DISTINCT FROM r_acc.config_generation\n"
        f"    AND st.extractor_generation IS NOT DISTINCT FROM r_acc.extractor_generation\n"
        f"    AND st.canonicalizer_generation IS NOT DISTINCT FROM r_acc.canonicalizer_generation\n"
        f"    AND st.snapshot_vector_json IS NOT DISTINCT FROM r_acc.snapshot_vector_json\n"
        f"    AND st.max_evidence_run_id = live_ev.max_evidence_run_id\n"
        f"    AND st.total_evidence_row_count = live_ev.total_evidence_row_count\n"
        f"    AND st.evidence_fingerprint = live_ev.evidence_fingerprint\n"
        f"),\n"
        f"target_node AS MATERIALIZED (\n"
        f"  SELECT cn.id, cn.repository_id, cn.kind{target_display_col}, cn.metadata_json, cn.first_seen_run_id, cn.last_seen_run_id\n"
        f"  FROM public.canonical_nodes cn JOIN live_projection lp ON lp.repository_id = cn.repository_id\n"
        f"  WHERE cn.graph_key_version = 1 AND cn.canonical_key = {sql_literal(query.canonical_key)} LIMIT 1\n"
        f"),\n"
        f"selected_run AS MATERIALIZED (\n"
        f"  SELECT p.run_id FROM {PROJECTION_TABLE} p JOIN target_node tn ON tn.id = p.canonical_node_id AND tn.repository_id = p.repository_id\n"
        f"  JOIN accepted_run acc ON TRUE WHERE TRUE {facet_sql} ORDER BY (p.run_id = acc.run_id) DESC, p.run_id DESC LIMIT 1\n"
        f"),\n"
        f"current_window AS MATERIALIZED (\n"
        f"  SELECT {cols} FROM {PROJECTION_TABLE} p JOIN target_node subject ON subject.id = p.canonical_node_id AND subject.repository_id = p.repository_id\n"
        f"  JOIN selected_run sr ON p.run_id = sr.run_id WHERE TRUE {role_filter_sql} {facet_sql} {order_clause} LIMIT {window_limit}\n"
        f"),\n"
        f"historical_window AS MATERIALIZED (\n"
        f"  SELECT {cols} FROM {PROJECTION_TABLE} p JOIN target_node subject ON subject.id = p.canonical_node_id AND subject.repository_id = p.repository_id\n"
        f"  JOIN selected_run sr ON p.run_id <> sr.run_id WHERE TRUE {role_filter_sql} {facet_sql} {order_clause} LIMIT {window_limit}\n"
        f"),\n"
        f"{transport_budget_sql('target_node', 'current_window', 'historical_window', 'accepted_run')}\n"
        f"SELECT json_build_object(\n"
        f"  'has_accepted', EXISTS (SELECT 1 FROM accepted_run),\n"
        f"  'projection_stale', EXISTS (SELECT 1 FROM accepted_run) AND NOT EXISTS (SELECT 1 FROM live_projection),\n"
        f"  'malformed_metadata_count', COALESCE((SELECT malformed_metadata_count FROM live_projection LIMIT 1), 0),\n"
        f"  'transport_overflow', (SELECT exceeded FROM transport_budget),\n"
        f"  'accepted', (SELECT {postgres_accepted_json_sql(context_identity=item.context_identity)} FROM accepted_run acc WHERE NOT (SELECT exceeded FROM transport_budget)),\n"
        f"  'has_node', EXISTS (SELECT 1 FROM target_node),\n"
        f"  'node', (SELECT json_build_object('id', tn.id, 'metadata_json', tn.metadata_json, 'first_seen_run_id', tn.first_seen_run_id, 'last_seen_run_id', tn.last_seen_run_id{extra_node_cols}) FROM target_node tn WHERE NOT (SELECT exceeded FROM transport_budget)),\n"
        f"  'selected_run_id', (SELECT run_id FROM selected_run),\n"
        f"  'current_rows', COALESCE((SELECT json_agg(row_to_json(cw)) FROM current_window cw WHERE NOT (SELECT exceeded FROM transport_budget)), '[]'::json),\n"
        f"  'historical_rows', COALESCE((SELECT json_agg(row_to_json(hw)) FROM historical_window hw WHERE NOT (SELECT exceeded FROM transport_budget)), '[]'::json)\n"
        f")::text;"
    )


def build_cleanup_sql() -> str:
    """Build strict RESTRICT cleanup SQL for the disposable JSONB experiment schema."""
    return (
        f"DROP INDEX IF EXISTS {DISPOSABLE_SCHEMA}.{GIN_OPS_INDEX} RESTRICT;\n"
        f"DROP INDEX IF EXISTS {DISPOSABLE_SCHEMA}.{GIN_PATH_OPS_INDEX} RESTRICT;\n"
        f"DROP TABLE IF EXISTS {PROJECTION_TABLE} RESTRICT;\n"
        f"DROP TABLE IF EXISTS {STATE_TABLE} RESTRICT;\n"
        f"DROP SCHEMA IF EXISTS {DISPOSABLE_SCHEMA} RESTRICT;"
    )


__all__ = [
    "DISPOSABLE_SCHEMA",
    "GIN_OPS_INDEX",
    "GIN_PATH_OPS_INDEX",
    "JSONB_EXPERIMENT_POLICY_VERSION",
    "PROJECTION_TABLE",
    "STATE_TABLE",
    "VARIANT_NAMES",
    "JsonbFacetFilter",
    "NamedEvidenceWorkloadItem",
    "NodeLocationsQuery",
    "_thaw_jsonable",
    "build_cleanup_sql",
    "build_jsonb_projection_ddl_sql",
    "build_jsonb_workload_sql",
    "build_relational_workload_sql",
    "decode_node_locations_payload",
    "normalize_node_locations_result_for_equality",
    "sql_literal",
    "validate_evidence_metadata_facets",
]
