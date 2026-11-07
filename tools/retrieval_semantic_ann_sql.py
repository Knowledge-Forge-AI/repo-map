"""Evaluator-owned SQL for the disposable W5 HNSW arm.

This module deliberately does not change the production semantic-candidate
query.  It shares the accepted-publication predicate and reproduces the
production scope predicates around a direct ordered vector scan so the plan
can prove (or honestly fail to prove) HNSW use.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import re

from common_lore_index.storage.semantic_candidate_sql import accepted_candidate_publication_sql
from common_lore_index.storage.semantic_candidates import (
    CandidateQuery,
    MAX_IMPORT_ROWS,
    PGVECTOR_VERSION,
    checked_identity,
)
from common_lore_index.storage.sql_core import sql_literal
from retrieval_semantic_ann_models import HnswSourceScope
from retrieval_semantic_ann_scope import candidate_query_digest, index_name


HNSW_DIMENSIONS = 384
DEFAULT_EF_SEARCH = 40
DEFAULT_ITERATIVE_SCAN = "strict_order"
DEFAULT_OWNER_IDENTITY = "repomap_w5_hnsw_owner"
INDEX_SCHEMA = "repomap_enrichment"
INDEX_TABLE = "embeddings"
VECTOR_SCHEMA = "repomap_vector"
_INDEX_NAME = re.compile(r"repomap_w5_hnsw384_[0-9a-f]{32}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_ITERATIVE_SCAN_VALUES = frozenset({"off", "strict_order", "relaxed_order"})
_ACCEPTED_EVIDENCE_LINK_SQL = "link.link_kind NOT IN ('inferred', 'inferred_from_edge')"


@dataclass(frozen=True, slots=True)
class HnswIndexSpec:
    """An invocation-owned per-rebuild HNSW index identity."""

    name: str
    rebuild_id: str
    query_digest: str
    attempt_identity: str
    owner_identity: str = DEFAULT_OWNER_IDENTITY

    def validate(self, query: CandidateQuery | None = None,
                 source_scope: HnswSourceScope | None = None) -> HnswIndexSpec:
        if _INDEX_NAME.fullmatch(self.name) is None or _DIGEST.fullmatch(self.query_digest) is None:
            raise ValueError("invalid owned HNSW index identity")
        checked_identity(self.rebuild_id)
        checked_identity(self.attempt_identity)
        checked_identity(self.owner_identity)
        if (query is None) != (source_scope is None):
            raise ValueError("query and source scope must be supplied together")
        if query is not None and source_scope is not None:
            query.validate()
            if query.rebuild_id != self.rebuild_id:
                raise ValueError("HNSW index rebuild does not match query")
            expected_digest = candidate_query_digest(query, source_scope)
            if expected_digest != self.query_digest:
                raise ValueError("HNSW index query digest does not match query")
        expected = index_name(self.query_digest, self.rebuild_id, self.attempt_identity, self.owner_identity)
        if self.name != expected:
            raise ValueError("HNSW index name is not bound to the expected query and attempt")
        return self

    @classmethod
    def from_query(
        cls,
        query: CandidateQuery,
        *,
        source_scope: HnswSourceScope,
        attempt_identity: str,
        owner_identity: str = DEFAULT_OWNER_IDENTITY,
    ) -> HnswIndexSpec:
        query.validate()
        if query.selected is not True:
            raise ValueError("HNSW index requires explicit query selection")
        if query.profile.dimensions != HNSW_DIMENSIONS:
            raise ValueError("HNSW requires a 384-dimensional profile")
        checked_identity(attempt_identity)
        checked_identity(owner_identity)
        query_digest = candidate_query_digest(query, source_scope)
        name = index_name(query_digest, query.rebuild_id, attempt_identity, owner_identity)
        return cls(name, query.rebuild_id, query_digest, attempt_identity, owner_identity).validate(
            query, source_scope=source_scope
        )


def _quote_identifier(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", value):
        raise ValueError("invalid SQL identifier")
    return '"' + value + '"'


def build_hnsw_index_create_sql(spec: HnswIndexSpec) -> str:
    """Create only the exact invocation-owned fixed-dimension expression index."""
    spec.validate()
    return f"""CREATE INDEX {_quote_identifier(spec.name)}
ON {_quote_identifier(INDEX_SCHEMA)}.{_quote_identifier(INDEX_TABLE)}
USING hnsw (
    (embedding::{_quote_identifier(VECTOR_SCHEMA)}.vector({HNSW_DIMENSIONS}))
        {_quote_identifier(VECTOR_SCHEMA)}.vector_cosine_ops
)
WHERE rebuild_id = {sql_literal(spec.rebuild_id)} AND dimensions = {HNSW_DIMENSIONS};"""


def build_hnsw_index_catalog_sql(spec: HnswIndexSpec) -> str:
    """Read the owned index's catalog shape without accepting caller assertions."""
    spec.validate()
    index = sql_literal(spec.name)
    schema = sql_literal(INDEX_SCHEMA)
    return f"""WITH selected AS (
    SELECT c.oid::bigint AS index_oid, table_rel.oid::bigint AS table_oid,
           i.indnatts AS index_attribute_count, i.indnkeyatts AS index_key_count,
           ns.nspname AS index_schema, c.relname AS index_name,
           table_ns.nspname AS table_schema, table_rel.relname AS table_name,
           am.amname AS access_method, i.indisvalid AS is_valid,
           i.indisready AS is_ready,
           pg_get_userbyid(c.relowner) AS index_owner, current_user AS current_user,
           op_ns.nspname AS opclass_schema, op.opcname AS opclass_name,
           pg_get_expr(i.indexprs, i.indrelid) AS expression,
           COALESCE(c.reloptions, ARRAY[]::text[]) AS reloptions,
           pg_get_expr(i.indpred, i.indrelid) AS predicate
    FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace ns ON ns.oid = c.relnamespace
    JOIN pg_catalog.pg_index i ON i.indexrelid = c.oid
    JOIN pg_catalog.pg_class table_rel ON table_rel.oid = i.indrelid
    JOIN pg_catalog.pg_namespace table_ns ON table_ns.oid = table_rel.relnamespace
    JOIN pg_catalog.pg_am am ON am.oid = c.relam
    LEFT JOIN pg_catalog.pg_opclass op ON op.oid = i.indclass[0]
    LEFT JOIN pg_catalog.pg_namespace op_ns ON op_ns.oid = op.opcnamespace
    WHERE ns.nspname = {schema} AND c.relname = {index}
    LIMIT 1
) SELECT json_build_object(
    'present', EXISTS (SELECT 1 FROM selected),
    'index_oid', (SELECT index_oid FROM selected),
    'table_oid', (SELECT table_oid FROM selected),
    'index_attribute_count', (SELECT index_attribute_count FROM selected),
    'index_key_count', (SELECT index_key_count FROM selected),
    'index_schema', (SELECT index_schema FROM selected),
    'index_name', (SELECT index_name FROM selected),
    'table_schema', (SELECT table_schema FROM selected),
    'table_name', (SELECT table_name FROM selected),
    'access_method', (SELECT access_method FROM selected),
    'is_valid', (SELECT is_valid FROM selected),
    'is_ready', (SELECT is_ready FROM selected),
    'index_owner', (SELECT index_owner FROM selected),
    'current_user', (SELECT selected.current_user FROM selected),
    'opclass_schema', (SELECT opclass_schema FROM selected),
    'opclass_name', (SELECT opclass_name FROM selected),
    'expression', (SELECT expression FROM selected),
    'predicate', (SELECT predicate FROM selected),
    'reloptions', (SELECT reloptions FROM selected)
)::text;"""


def build_hnsw_index_drop_sql(spec: HnswIndexSpec) -> str:
    """Drop one already-verified owned index, never with CASCADE."""
    spec.validate()
    return (
        f"DROP INDEX {_quote_identifier(INDEX_SCHEMA)}.{_quote_identifier(spec.name)} RESTRICT;"
    )


def _vector_literal(query: CandidateQuery) -> str:
    return sql_literal("[" + ",".join(str(float(value)) for value in query.vector) + "]")


def _metadata_filters(query: CandidateQuery) -> str:
    receipt = query.publication.publication.receipt
    portable = receipt.portable
    assert portable is not None
    profile = query.profile
    values = (
        ("model", profile.model),
        ("model_version", profile.model_version),
        ("generator", profile.generator),
        ("generator_version", profile.generator_version),
        ("representation_version", profile.representation_version),
        ("normalization", profile.normalization),
        ("metric", profile.metric),
        *zip(receipt.generations.field_names(), receipt.generations.values(), strict=True),
        ("publication_bundle_id", portable.publication_bundle_id),
        ("snapshot_manifest_id", portable.snapshot_manifest_id),
    )
    return " AND ".join(f"rebuild.{field} = {sql_literal(str(value))}" for field, value in values)


def _query_filters(query: CandidateQuery) -> tuple[str, str, str]:
    filters = ["node.graph_key_version = 1", "node.last_seen_run_id = accepted.id"]
    if query.kind is not None:
        filters.append(f"node.kind = {sql_literal(query.kind)}")
    if query.source_binding_id is not None:
        filters.append(
            f"embedding.source_binding_id = {sql_literal(query.source_binding_id)}"
        )
    path_filter = "" if query.path is None else f"AND evidence.path = {sql_literal(query.path)}"
    evidence_scope = f"""evidence.repository_id = accepted.repository_id
        AND evidence.run_id = accepted.id AND evidence.graph_key_version = 1
        AND evidence.metadata_json->>'binding_id' = embedding.source_binding_id
        AND evidence.metadata_json->>'snapshot_id' = embedding.snapshot_id
        AND {_ACCEPTED_EVIDENCE_LINK_SQL}
        {path_filter}"""
    return " AND ".join(filters), path_filter, evidence_scope


def _source_scope_sql(source_scope: Sequence[tuple[str, str]]) -> str:
    """Render a validated public binding/snapshot scope as a fixed VALUES CTE."""
    pairs = tuple(source_scope)
    try:
        unique = len(set(pairs))
    except TypeError as exc:
        raise ValueError("HNSW source scope pair is unhashable") from exc
    if not pairs or unique != len(pairs):
        raise ValueError("HNSW source scope must contain unique public pairs")
    values: list[str] = []
    for pair in pairs:
        if type(pair) is not tuple or len(pair) != 2:
            raise ValueError("HNSW source scope pair is malformed")
        binding_id, snapshot_id = pair
        checked_identity(binding_id)
        checked_identity(snapshot_id)
        values.append(f"({sql_literal(binding_id)}, {sql_literal(snapshot_id)})")
    return "source_scope(source_binding_id, snapshot_id) AS MATERIALIZED (VALUES " + ", ".join(values) + ")"


def _validate_ann_bounds(query: CandidateQuery, ann_scan_limit: int) -> None:
    query.validate()
    if query.selected is not True:
        raise ValueError("HNSW evaluation requires explicit selection")
    if query.profile.dimensions != HNSW_DIMENSIONS:
        raise ValueError("HNSW requires a 384-dimensional profile")
    if len(query.vector) != HNSW_DIMENSIONS:
        raise ValueError("HNSW query vector must contain 384 values")
    if type(ann_scan_limit) is not int or not query.limit <= ann_scan_limit <= MAX_IMPORT_ROWS:
        raise ValueError("HNSW scan limit must cover the result limit and stay within 500")


def build_hnsw_ann_statement(
    query: CandidateQuery,
    *,
    source_scope: HnswSourceScope,
    ann_scan_limit: int = MAX_IMPORT_ROWS,
) -> str:
    """Build one direct ordered ANN statement; no materialized distance CTE."""
    _validate_ann_bounds(query, ann_scan_limit)
    pairs = tuple(source_scope)
    if query.source_binding_id is None or len(pairs) != 1 or pairs[0][0] != query.source_binding_id:
        raise ValueError("HNSW SQL scope must bind the selected source")
    vector = _vector_literal(query)
    scope_cte = _source_scope_sql(pairs)
    accepted = accepted_candidate_publication_sql(query.publication)
    metadata_filters = _metadata_filters(query)
    node_filters, path_filter, evidence_scope = _query_filters(query)
    order_distance = (
        f"(embedding.embedding::{_quote_identifier(VECTOR_SCHEMA)}.vector({HNSW_DIMENSIONS})) "
        f"OPERATOR({_quote_identifier(VECTOR_SCHEMA)}.<=>) "
        f"{vector}::{_quote_identifier(VECTOR_SCHEMA)}.vector({HNSW_DIMENSIONS})"
    )
    return f"""WITH {scope_cte},
{accepted},
candidate_rebuild AS (
    SELECT rebuild.* FROM repomap_enrichment.rebuilds rebuild JOIN accepted
      ON rebuild.repository_identity = {sql_literal(query.publication.repository_identity)}
     AND rebuild.run_id = accepted.id
     AND rebuild.receipt_identity = {sql_literal(query.publication.receipt_identity)}
    WHERE rebuild.rebuild_id = {sql_literal(query.rebuild_id)}
),
profile_rebuild AS (
    SELECT rebuild.* FROM candidate_rebuild rebuild
    WHERE rebuild.profile_identity = {sql_literal(query.profile.identity)}
      AND rebuild.dimensions = {HNSW_DIMENSIONS}
      AND rebuild.privacy_class = 'public'
      AND {metadata_filters}
),
extension_status AS (
    SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_extension ext
        JOIN pg_catalog.pg_namespace n ON n.oid = ext.extnamespace
        WHERE ext.extname = 'vector' AND ext.extversion = '{PGVECTOR_VERSION}'
          AND n.nspname = '{VECTOR_SCHEMA}') AS available
),
matching AS MATERIALIZED (
    SELECT rebuild.* FROM profile_rebuild rebuild CROSS JOIN extension_status
    WHERE extension_status.available
      AND rebuild.row_count BETWEEN 1 AND {MAX_IMPORT_ROWS}
      AND rebuild.row_count = (SELECT count(*) FROM repomap_enrichment.embeddings e
          WHERE e.rebuild_id = rebuild.rebuild_id)
),
ann_scan AS (
    SELECT node.id AS node_id, node.canonical_key, node.kind, node.display_name,
        node.confidence, node.conflict, embedding.source_binding_id,
        embedding.input_digest, embedding.snapshot_id,
        {order_distance} AS distance
    FROM matching JOIN accepted ON accepted.id = matching.run_id
    JOIN repomap_enrichment.embeddings embedding USING (rebuild_id)
    JOIN source_scope scope
      ON scope.source_binding_id = embedding.source_binding_id
     AND scope.snapshot_id = embedding.snapshot_id
    JOIN public.canonical_nodes node ON node.repository_id = accepted.repository_id
      AND node.canonical_key = embedding.canonical_key
    WHERE {node_filters}
      AND embedding.rebuild_id = {sql_literal(query.rebuild_id)}
      AND embedding.dimensions = {HNSW_DIMENSIONS}
      AND repomap_vector.vector_dims(embedding.embedding) = {HNSW_DIMENSIONS}
      AND EXISTS (SELECT 1 FROM public.canonical_node_evidence link
        JOIN public.canonical_evidence evidence ON evidence.id = link.canonical_evidence_id
        WHERE link.canonical_node_id = node.id AND {evidence_scope})
    ORDER BY {order_distance}
    FETCH FIRST {ann_scan_limit} ROWS WITH TIES
),
ranked AS MATERIALIZED (
    SELECT * FROM ann_scan
    ORDER BY distance, canonical_key COLLATE "C", source_binding_id COLLATE "C"
    LIMIT {query.limit}
),
expanded AS (
    SELECT ranked.*, (
        SELECT COALESCE(json_agg(row_to_json(items)), '[]'::json) FROM (
            SELECT evidence.evidence_key, evidence.path, evidence.start_line,
                evidence.end_line, evidence.raw_kind, evidence.extractor,
                evidence.extractor_version, evidence.confidence
            FROM public.canonical_node_evidence link
            JOIN public.canonical_evidence evidence
              ON evidence.id = link.canonical_evidence_id
            JOIN accepted ON evidence.repository_id = accepted.repository_id
            WHERE link.canonical_node_id = ranked.node_id
              AND evidence.run_id = accepted.id
              AND evidence.graph_key_version = 1
              AND evidence.metadata_json->>'binding_id' = ranked.source_binding_id
              AND evidence.metadata_json->>'snapshot_id' = ranked.snapshot_id
              AND {_ACCEPTED_EVIDENCE_LINK_SQL}
              {path_filter}
            ORDER BY evidence.evidence_key COLLATE "C"
            LIMIT {query.evidence_limit}
        ) items
    ) AS evidence FROM ranked
)
SELECT json_build_object(
    'status', CASE
        WHEN NOT EXISTS (SELECT 1 FROM accepted) THEN 'stale_publication'
        WHEN NOT EXISTS (SELECT 1 FROM candidate_rebuild) THEN 'stale_rebuild'
        WHEN NOT EXISTS (SELECT 1 FROM profile_rebuild) THEN 'profile_mismatch'
        WHEN NOT EXISTS (SELECT 1 FROM extension_status WHERE available) THEN 'unsupported_extension'
        WHEN NOT EXISTS (SELECT 1 FROM matching) THEN 'rebuild_integrity_mismatch'
        WHEN NOT EXISTS (SELECT 1 FROM matching rebuild
            JOIN repomap_enrichment.embeddings embedding USING (rebuild_id)
            JOIN source_scope scope
              ON scope.source_binding_id = embedding.source_binding_id
             AND scope.snapshot_id = embedding.snapshot_id)
            THEN 'source_scope_unavailable'
        ELSE 'ok' END,
    'candidates', (SELECT COALESCE(json_agg(row_to_json(expanded)
        ORDER BY distance, canonical_key COLLATE "C", source_binding_id COLLATE "C"), '[]'::json)
        FROM expanded),
    'ann_scan_limit', {ann_scan_limit}
)::text"""


def _settings_prefix() -> str:
    return (
        "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;\n"
        f"SET LOCAL hnsw.ef_search = '{DEFAULT_EF_SEARCH}';\n"
        f"SET LOCAL hnsw.iterative_scan = '{DEFAULT_ITERATIVE_SCAN}';\n"
    )


def build_hnsw_query_sql(
    query: CandidateQuery,
    *,
    source_scope: HnswSourceScope,
    ann_scan_limit: int = MAX_IMPORT_ROWS,
) -> str:
    """Wrap the fixed query in its bounded, frozen HNSW settings."""
    statement = build_hnsw_ann_statement(
        query, source_scope=source_scope, ann_scan_limit=ann_scan_limit
    )
    return _settings_prefix() + statement + ";\nCOMMIT;"


def build_hnsw_explain_sql(
    query: CandidateQuery,
    *,
    source_scope: HnswSourceScope,
    ann_scan_limit: int = MAX_IMPORT_ROWS,
) -> str:
    """Explain and execute the same statement under the same frozen settings."""
    statement = build_hnsw_ann_statement(
        query, source_scope=source_scope, ann_scan_limit=ann_scan_limit
    )
    return _settings_prefix() + "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)\n" + statement + ";\nCOMMIT;"


def allowed_iterative_scan(value: str) -> bool:
    """Expose the pgvector setting vocabulary for strict boundary tests."""
    return type(value) is str and value in _ITERATIVE_SCAN_VALUES
