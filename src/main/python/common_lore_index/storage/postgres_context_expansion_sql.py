"""Bounded PostgreSQL depth-1 context expansion SQL (REPOMAP-CLOE-SERVER-PARITY1)."""

from __future__ import annotations

from collections.abc import Sequence

from common_lore_index.retrieval.intent_policy import CONTEXT_DIRECT_EVIDENCE_ROLE_V1
from common_lore_index.storage.context_postgres_identity import (
    postgres_accepted_json_sql,
    postgres_accepted_run_cte_sql,
    postgres_repo_predicate_sql,
)
from common_lore_index.storage.errors import StorageSchemaError
from common_lore_index.storage.navigation_search import EVIDENCE_SCAN_LIMIT
from common_lore_index.storage.postgres_navigation_sql import transport_budget_sql
from common_lore_index.storage.sql_core import sql_literal


def _validate_inputs(
    seed_keys: Sequence[str],
    edge_kinds: Sequence[str],
    node_limit: int,
    edge_limit: int,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    seeds = tuple(seed_keys)
    if not 1 <= len(seeds) <= 5:
        raise StorageSchemaError("context expansion requires 1..5 distinct seeds")
    if any(not isinstance(seed, str) or not seed for seed in seeds):
        raise StorageSchemaError("context expansion seeds must be non-empty strings")
    if len(set(seeds)) != len(seeds):
        raise StorageSchemaError("context expansion requires 1..5 distinct seeds")
    if type(node_limit) is not int or not 1 <= node_limit <= 32:
        raise StorageSchemaError("node_limit must be in 1..32")
    if type(edge_limit) is not int or not 1 <= edge_limit <= 64:
        raise StorageSchemaError("edge_limit must be in 1..64")
    raw_kinds = tuple(edge_kinds)
    if any(not isinstance(kind, str) or not kind for kind in raw_kinds):
        raise StorageSchemaError("edge_kinds must contain non-empty strings")
    kinds = tuple(sorted(dict.fromkeys(raw_kinds)))
    if not kinds:
        raise StorageSchemaError("context expansion requires at least one edge kind")
    return seeds, kinds


def build_postgres_context_expansion_sql(
    seed_keys: Sequence[str],
    *,
    edge_kinds: Sequence[str],
    node_limit: int,
    edge_limit: int,
    repository_identity: str | None,
    role_sql: str = CONTEXT_DIRECT_EVIDENCE_ROLE_V1,
) -> str:
    """Build one request-pinned statement for all depth-1 seeds and locations."""
    seeds, kinds = _validate_inputs(seed_keys, edge_kinds, node_limit, edge_limit)
    repo_predicate = postgres_repo_predicate_sql(
        repository_identity, "", context_identity=True
    )
    kind_sql = ", ".join(sql_literal(kind) for kind in kinds)
    seed_sql = ",\n        ".join(
        f"({index}, {sql_literal(seed)})" for index, seed in enumerate(seeds)
    )
    fetch_limit = edge_limit + 1
    relation_sql = (
        "json_build_array(e.source_canonical_key, e.edge_kind, "
        "e.target_canonical_key, e.identity_metadata_hash)::text"
    )
    edge_columns = """
        edge.edge_kind, edge.source_canonical_key, edge.target_canonical_key,
        edge.edge_confidence, edge.edge_conflict, edge.edge_first_seen_run_id,
        edge.edge_last_seen_run_id, edge.neighbor_id, edge.neighbor_canonical_key,
        edge.neighbor_kind, edge.neighbor_display_name, edge.neighbor_first_seen_run_id,
        edge.neighbor_last_seen_run_id"""
    return f"""WITH RECURSIVE matched_repo AS MATERIALIZED (
    SELECT repo.id AS repository_id
    FROM public.repositories repo
    WHERE {repo_predicate}
    ORDER BY repo.id DESC
    LIMIT 1
),
{postgres_accepted_run_cte_sql(context_identity=True)},
seed_input(seed_ord, seed_key) AS (
    VALUES
        {seed_sql}
),
seed_window AS MATERIALIZED (
    SELECT
        si.seed_ord,
        edge.direction,
        edge.direction_rank,
        edge.edge_key,
        edge.relation_identity,
        {edge_columns}
    FROM seed_input si
    JOIN accepted_run acc ON TRUE
    CROSS JOIN LATERAL (
        SELECT
            'outgoing'::text AS direction,
            0::int AS direction_rank,
            e.identity_metadata_hash AS edge_key,
            {relation_sql} AS relation_identity,
            e.edge_kind,
            e.source_canonical_key,
            e.target_canonical_key,
            e.confidence::text AS edge_confidence,
            e.conflict AS edge_conflict,
            e.first_seen_run_id AS edge_first_seen_run_id,
            e.last_seen_run_id AS edge_last_seen_run_id,
            target.id AS neighbor_id,
            target.canonical_key AS neighbor_canonical_key,
            target.kind AS neighbor_kind,
            target.display_name AS neighbor_display_name,
            target.first_seen_run_id AS neighbor_first_seen_run_id,
            target.last_seen_run_id AS neighbor_last_seen_run_id
        FROM public.canonical_edges e
        JOIN public.canonical_nodes target
          ON target.repository_id = acc.repository_id
         AND target.graph_key_version = 1
         AND target.canonical_key = e.target_canonical_key
        WHERE e.repository_id = acc.repository_id
          AND e.graph_key_version = 1
          AND e.source_canonical_key = si.seed_key
          AND e.edge_kind IN ({kind_sql})
        ORDER BY e.edge_kind COLLATE "C" ASC,
                 e.target_canonical_key COLLATE "C" ASC,
                 e.identity_metadata_hash COLLATE "C" ASC
        LIMIT {fetch_limit}
    ) edge
    UNION ALL
    SELECT
        si.seed_ord,
        edge.direction,
        edge.direction_rank,
        edge.edge_key,
        edge.relation_identity,
        {edge_columns}
    FROM seed_input si
    JOIN accepted_run acc ON TRUE
    CROSS JOIN LATERAL (
        SELECT
            'incoming'::text AS direction,
            1::int AS direction_rank,
            e.identity_metadata_hash AS edge_key,
            {relation_sql} AS relation_identity,
            e.edge_kind,
            e.source_canonical_key,
            e.target_canonical_key,
            e.confidence::text AS edge_confidence,
            e.conflict AS edge_conflict,
            e.first_seen_run_id AS edge_first_seen_run_id,
            e.last_seen_run_id AS edge_last_seen_run_id,
            source.id AS neighbor_id,
            source.canonical_key AS neighbor_canonical_key,
            source.kind AS neighbor_kind,
            source.display_name AS neighbor_display_name,
            source.first_seen_run_id AS neighbor_first_seen_run_id,
            source.last_seen_run_id AS neighbor_last_seen_run_id
        FROM public.canonical_edges e
        JOIN public.canonical_nodes source
          ON source.repository_id = acc.repository_id
         AND source.graph_key_version = 1
         AND source.canonical_key = e.source_canonical_key
        WHERE e.repository_id = acc.repository_id
          AND e.graph_key_version = 1
          AND e.target_canonical_key = si.seed_key
          AND e.edge_kind IN ({kind_sql})
        ORDER BY e.edge_kind COLLATE "C" ASC,
                 e.source_canonical_key COLLATE "C" ASC,
                 e.identity_metadata_hash COLLATE "C" ASC
        LIMIT {fetch_limit}
    ) edge
),
seed_ranked AS MATERIALIZED (
    SELECT sw.*,
           row_number() OVER (
               PARTITION BY sw.seed_ord
               ORDER BY sw.edge_kind COLLATE "C" ASC,
                        sw.direction_rank ASC,
                        sw.neighbor_canonical_key COLLATE "C" ASC,
                        sw.edge_key COLLATE "C" ASC
           ) AS seed_rank,
           count(*) OVER (PARTITION BY sw.seed_ord) AS seed_edge_count
    FROM seed_window sw
),
kept AS MATERIALIZED (
    SELECT sr.*,
           row_number() OVER (ORDER BY sr.seed_ord ASC, sr.seed_rank ASC) AS step
    FROM seed_ranked sr
    WHERE sr.seed_rank <= {edge_limit}
),
fold(step, seed_ord, seed_new, seen, rejected, admitted, action) AS (
    SELECT 0::bigint, -1::int, 0::int,
           ARRAY[]::text[], ARRAY[]::text[], ARRAY[]::text[], 'start'::text
    UNION ALL
    SELECT
        k.step,
        k.seed_ord,
        CASE WHEN decision.action = 'new' THEN base.base_count + 1
             ELSE base.base_count END,
        CASE WHEN decision.action IN ('new', 'existing', 'seed_to_seed')
             THEN array_append(f.seen, k.relation_identity)
             ELSE f.seen END,
        CASE WHEN decision.action = 'relation_limit'
             THEN array_append(f.rejected, k.relation_identity)
             ELSE f.rejected END,
        CASE WHEN decision.action = 'new'
             THEN array_append(f.admitted, k.neighbor_canonical_key)
             ELSE f.admitted END,
        decision.action
    FROM fold f
    JOIN kept k ON k.step = f.step + 1
    CROSS JOIN LATERAL (
        SELECT CASE WHEN k.seed_ord = f.seed_ord THEN f.seed_new ELSE 0 END AS base_count
    ) base
    CROSS JOIN LATERAL (
        SELECT (CASE
            WHEN k.relation_identity = ANY(f.seen)
              OR k.relation_identity = ANY(f.rejected) THEN 'skip'
            WHEN cardinality(f.seen) >= 256 THEN 'relation_limit'
            WHEN EXISTS (
                SELECT 1 FROM seed_input si
                WHERE si.seed_key = k.neighbor_canonical_key
            ) THEN 'seed_to_seed'
            WHEN k.neighbor_canonical_key = ANY(f.admitted) THEN 'existing'
            WHEN base.base_count >= {node_limit}
              OR cardinality(f.admitted) >= 128 THEN 'node_limit'
            ELSE 'new'
        END)::text AS action
    ) decision
),
folded AS MATERIALIZED (
    SELECT k.*, f.action
    FROM kept k
    JOIN fold f ON f.step = k.step
),
admitted AS MATERIALIZED (
    SELECT * FROM folded WHERE action = 'new'
),
selected_run AS MATERIALIZED (
    SELECT
        a.neighbor_id,
        a.neighbor_canonical_key,
        coalesce(
            max(e.run_id) FILTER (WHERE e.run_id = acc.run_id),
            max(e.run_id)
        ) AS run_id
    FROM admitted a
    JOIN accepted_run acc ON TRUE
    JOIN public.canonical_node_evidence link
      ON link.canonical_node_id = a.neighbor_id
    JOIN public.canonical_evidence e
      ON e.id = link.canonical_evidence_id
     AND e.repository_id = acc.repository_id
     AND e.graph_key_version = 1
    GROUP BY a.neighbor_id, a.neighbor_canonical_key
),
neighbor_evidence AS MATERIALIZED (
    SELECT
        e.evidence_key,
        link.link_kind,
        e.run_id,
        e.raw_observation_ordinal,
        raw.payload_hash,
        e.raw_kind,
        e.raw_source_id,
        e.path,
        e.start_line,
        e.end_line,
        e.extractor,
        e.extractor_version,
        e.confidence::text AS confidence,
        e.metadata_json,
        r.publication_bundle_id,
        r.snapshot_manifest_id,
        r.extraction_receipt_id,
        r.graph_candidate_id,
        r.snapshot_vector_json,
        ({role_sql}) AS evidence_role,
        subject.id AS node_id,
        subject.canonical_key AS subject_canonical_key
    FROM selected_run sr
    JOIN public.canonical_nodes subject
      ON subject.id = sr.neighbor_id
    JOIN public.canonical_node_evidence link
      ON link.canonical_node_id = subject.id
    JOIN public.canonical_evidence e
      ON e.id = link.canonical_evidence_id
     AND e.repository_id = subject.repository_id
     AND e.run_id = sr.run_id
     AND e.graph_key_version = 1
    JOIN public.runs r
      ON r.id = e.run_id
     AND r.repository_id = e.repository_id
    LEFT JOIN public.raw_observations raw
      ON raw.repository_id = e.repository_id
     AND raw.run_id = e.run_id
     AND raw.ordinal = e.raw_observation_ordinal
    WHERE ({role_sql}) = 'direct'
    ORDER BY subject.canonical_key COLLATE "C" ASC,
             e.raw_observation_ordinal ASC,
             e.evidence_key COLLATE "C" ASC,
             link.link_kind COLLATE "C" ASC
    LIMIT {EVIDENCE_SCAN_LIMIT + 1}
),
{transport_budget_sql('seed_window', 'neighbor_evidence', 'accepted_run')}
SELECT json_build_object(
    'has_accepted', EXISTS (SELECT 1 FROM accepted_run),
    'transport_overflow', (SELECT exceeded FROM transport_budget),
    'accepted', (
        SELECT {postgres_accepted_json_sql(context_identity=True)}
        FROM accepted_run acc
        WHERE NOT (SELECT exceeded FROM transport_budget)
    ),
    'truncated_seeds', coalesce((
        SELECT count(DISTINCT seed_ord)::int FROM seed_ranked
        WHERE seed_edge_count > {edge_limit}
    ), 0),
    'relation_limit_hits', coalesce((
        SELECT count(*)::int FROM folded WHERE action = 'relation_limit'
    ), 0),
    'node_limit_hits', coalesce((
        SELECT count(*)::int FROM folded WHERE action = 'node_limit'
    ), 0),
    'edges', coalesce((
        SELECT json_agg(
            json_build_object(
                'action', f.action,
                'step', f.step,
                'direction', f.direction,
                'direction_rank', f.direction_rank,
                'edge_key', f.edge_key,
                'edge_kind', f.edge_kind,
                'source_canonical_key', f.source_canonical_key,
                'target_canonical_key', f.target_canonical_key,
                'confidence', f.edge_confidence,
                'conflict', f.edge_conflict,
                'first_seen_run_id', f.edge_first_seen_run_id,
                'last_seen_run_id', f.edge_last_seen_run_id,
                'neighbor_id', f.neighbor_id,
                'neighbor_canonical_key', f.neighbor_canonical_key,
                'neighbor_kind', f.neighbor_kind,
                'neighbor_display_name', f.neighbor_display_name,
                'neighbor_first_seen_run_id', f.neighbor_first_seen_run_id,
                'neighbor_last_seen_run_id', f.neighbor_last_seen_run_id
            ) ORDER BY f.step
        )
        FROM folded f
        WHERE f.action IN ('seed_to_seed', 'existing', 'new')
          AND NOT (SELECT exceeded FROM transport_budget)
    ), '[]'::json),
    'evidence', coalesce((
        SELECT json_agg(row_to_json(ne) ORDER BY
            ne.subject_canonical_key COLLATE "C" ASC,
            ne.raw_observation_ordinal ASC,
            ne.evidence_key COLLATE "C" ASC,
            ne.link_kind COLLATE "C" ASC
        )
        FROM neighbor_evidence ne
        WHERE NOT (SELECT exceeded FROM transport_budget)
    ), '[]'::json)
)::text;"""


__all__ = ["build_postgres_context_expansion_sql"]
