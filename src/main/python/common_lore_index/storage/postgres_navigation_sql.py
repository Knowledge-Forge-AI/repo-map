"""Single-statement SQL builder for PostgreSQL metadata navigation_search."""

from __future__ import annotations

from common_lore_index.storage.graph_readback_sql import escape_readback_like_pattern
from common_lore_index.storage.navigation_search import (
    CODE_KINDS,
    DOC_KINDS,
    EVIDENCE_SCAN_LIMIT,
    NODE_SCAN_LIMIT,
    NavigationSearchQuery,
)
from common_lore_index.storage.sql_core import sql_literal
from common_lore_index.storage.sqlite_local.node_location_queries import _EVIDENCE_ROLE_SQL

PG_SCOPED_TRANSPORT_ROW_CAP = 100_000
PG_SCOPED_TRANSPORT_BYTE_CAP = 33_554_432


def transport_budget_sql(*relations: str) -> str:
    """Bound detoasted UTF-8 JSON rows before aggregating or returning them.

    Two bytes per row cover JSON array separators; a 1024-byte reservation
    covers the fixed outer object. Every variable-width outer value belongs
    to one of the counted relations. Refusal deliberately returns empty rows.
    """
    terms = [
        f"COALESCE((SELECT sum(octet_length(convert_to(row_to_json(row_value)::text, 'UTF8')) + 2) "
        f"FROM {relation} row_value), 0)"
        for relation in relations
    ]
    counts = " OR ".join(
        f"(SELECT count(*) FROM {relation}) > {PG_SCOPED_TRANSPORT_ROW_CAP}"
        for relation in relations
    )
    return (
        "transport_budget AS MATERIALIZED (SELECT (" + counts + " OR (1024 + "
        + " + ".join(terms) + f") > {PG_SCOPED_TRANSPORT_BYTE_CAP}) AS exceeded)"
    )


def build_postgres_candidate_predicate_sql(query: NavigationSearchQuery) -> str:
    """Build SQL predicate over public.canonical_nodes matching SQLite candidate_predicate."""
    pattern_lit = sql_literal("%" + escape_readback_like_pattern(query.query) + "%")
    filters = [
        "subject.graph_key_version = 1",
        (
            f"(subject.canonical_key ILIKE {pattern_lit} ESCAPE '\\' "
            f"OR subject.kind ILIKE {pattern_lit} ESCAPE '\\' "
            f"OR subject.display_name ILIKE {pattern_lit} ESCAPE '\\')"
        ),
    ]
    if query.kind is not None:
        filters.append(f"subject.kind = {sql_literal(query.kind)}")
    kinds = (
        CODE_KINDS
        if query.scope == "code"
        else DOC_KINDS
        if query.scope == "docs"
        else ()
    )
    if kinds:
        kinds_sql = ", ".join(sql_literal(k) for k in kinds)
        filters.append(f"subject.kind IN ({kinds_sql})")
    return " AND ".join(filters)


def build_postgres_navigation_sql(
    query: NavigationSearchQuery,
    *,
    repository_identity: str | None,
    root_path: str,
) -> str:
    """Build single-statement request-pinned SQL for PostgreSQL navigation_search."""
    query.validate()
    repo_pred = (
        f"repo.repository_identity = {sql_literal(repository_identity)}"
        if repository_identity
        else f"repo.root_path = {sql_literal(root_path)}"
    )
    cand_pred = build_postgres_candidate_predicate_sql(query)
    has_scope = query.source_binding_id is not None
    node_fetch_limit = (
        PG_SCOPED_TRANSPORT_ROW_CAP + 1
        if has_scope
        else NODE_SCAN_LIMIT + 1
    )
    evidence_fetch_limit = (
        PG_SCOPED_TRANSPORT_ROW_CAP + 1
        if has_scope
        else EVIDENCE_SCAN_LIMIT + 1
    )

    return f"""WITH matched_repo AS MATERIALIZED (
    SELECT repo.id AS repository_id
    FROM public.repositories repo
    WHERE {repo_pred}
    ORDER BY repo.id DESC
    LIMIT 1
),
accepted_run AS MATERIALIZED (
    SELECT
        r.id AS run_id,
        r.publication_bundle_id,
        (
            SELECT count(*)::int
            FROM public.runs r2
            WHERE r2.repository_id = mr.repository_id
              AND r2.status = 'complete'
              AND r2.execution_route = 'portable-worker-v1'
              AND r2.publication_bundle_id IS NOT NULL
              AND r2.id <= r.id
        ) AS generation
    FROM public.runs r
    JOIN matched_repo mr ON mr.repository_id = r.repository_id
    WHERE r.status = 'complete'
      AND r.execution_route = 'portable-worker-v1'
      AND r.publication_bundle_id IS NOT NULL
      AND r.snapshot_manifest_id IS NOT NULL
      AND r.extraction_receipt_id IS NOT NULL
      AND r.graph_candidate_id IS NOT NULL
      AND r.snapshot_vector_json IS NOT NULL
      AND (
          r.portable_execution_mode <> 'coordinator'
          OR EXISTS (
              SELECT 1
              FROM public.graph_publication_authority gpa
              WHERE gpa.repository_id = mr.repository_id
                AND gpa.last_run_id = r.id
          )
      )
      AND NOT EXISTS (
          SELECT 1
          FROM public.graph_publication_authority gpa
          WHERE gpa.repository_id = mr.repository_id
            AND gpa.last_run_id IS NOT NULL
            AND gpa.last_run_id <> r.id
      )
    ORDER BY r.id DESC
    LIMIT 1
),
candidate_nodes AS MATERIALIZED (
    SELECT
        subject.id,
        subject.repository_id,
        subject.canonical_key,
        subject.kind,
        subject.display_name,
        subject.first_seen_run_id,
        subject.last_seen_run_id
    FROM public.canonical_nodes subject
    JOIN matched_repo mr ON mr.repository_id = subject.repository_id
    JOIN accepted_run acc ON TRUE
    WHERE {cand_pred}
    ORDER BY subject.canonical_key COLLATE "C" ASC
    LIMIT {node_fetch_limit}
),
selected_node_runs AS MATERIALIZED (
    SELECT
        subject.id AS node_id,
        subject.repository_id,
        subject.canonical_key,
        coalesce(
            max(CASE WHEN e.run_id = acc.run_id THEN e.run_id END),
            max(e.run_id)
        ) AS run_id
    FROM candidate_nodes subject
    CROSS JOIN accepted_run acc
    JOIN public.canonical_node_evidence link ON link.canonical_node_id = subject.id
    JOIN public.canonical_evidence e
      ON e.id = link.canonical_evidence_id
     AND e.repository_id = subject.repository_id
     AND e.graph_key_version = 1
    WHERE (
        {'TRUE' if has_scope else 'FALSE'}
        OR (
            SELECT count(*) FROM candidate_nodes
        ) <= {NODE_SCAN_LIMIT}
    )
    GROUP BY subject.id, subject.repository_id, subject.canonical_key
),
direct_evidence AS MATERIALIZED (
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
        ({_EVIDENCE_ROLE_SQL}) AS evidence_role,
        subject.id AS node_id,
        subject.canonical_key AS subject_canonical_key
    FROM selected_node_runs snr
    JOIN candidate_nodes subject ON subject.id = snr.node_id
    JOIN public.canonical_node_evidence link ON link.canonical_node_id = subject.id
    JOIN public.canonical_evidence e
      ON e.id = link.canonical_evidence_id
     AND e.repository_id = snr.repository_id
     AND e.run_id = snr.run_id
     AND e.graph_key_version = 1
    JOIN public.runs r ON r.id = e.run_id
    LEFT JOIN public.raw_observations raw
      ON raw.repository_id = e.repository_id
     AND raw.run_id = e.run_id
     AND raw.ordinal = e.raw_observation_ordinal
    WHERE ({_EVIDENCE_ROLE_SQL}) = 'direct'
    ORDER BY
        subject.canonical_key COLLATE "C" ASC,
        e.raw_observation_ordinal ASC,
        e.evidence_key COLLATE "C" ASC,
        link.link_kind COLLATE "C" ASC
    LIMIT {evidence_fetch_limit}
),
{transport_budget_sql('candidate_nodes', 'direct_evidence', 'accepted_run')}
SELECT json_build_object(
    'has_accepted', EXISTS (SELECT 1 FROM accepted_run),
    'transport_overflow', (SELECT exceeded FROM transport_budget),
    'accepted', (
        SELECT json_build_object(
            'generation', acc.generation,
            'run_id', acc.run_id,
            'publication_bundle_id', acc.publication_bundle_id
        )
        FROM accepted_run acc
        WHERE NOT (SELECT exceeded FROM transport_budget)
    ),
    'candidate_nodes', COALESCE(
        (
            SELECT json_agg(
                json_build_object(
                    'id', cn.id,
                    'canonical_key', cn.canonical_key,
                    'kind', cn.kind,
                    'display_name', cn.display_name,
                    'first_seen_run_id', cn.first_seen_run_id,
                    'last_seen_run_id', cn.last_seen_run_id
                )
                ORDER BY cn.canonical_key COLLATE "C" ASC
            )
            FROM candidate_nodes cn
            WHERE NOT (SELECT exceeded FROM transport_budget)
        ),
        '[]'::json
    ),
    'direct_evidence', COALESCE(
        (
            SELECT json_agg(
                row_to_json(de)
                ORDER BY
                    de.subject_canonical_key COLLATE "C" ASC,
                    de.raw_observation_ordinal ASC,
                    de.evidence_key COLLATE "C" ASC,
                    de.link_kind COLLATE "C" ASC
            )
            FROM direct_evidence de
            WHERE NOT (SELECT exceeded FROM transport_budget)
        ),
        '[]'::json
    )
)::text;"""


__all__ = [
    "build_postgres_candidate_predicate_sql",
    "build_postgres_navigation_sql",
]
