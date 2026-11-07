"""Single-statement PostgreSQL recursive literal_captured_text SQL builder for cloe_lexical."""

from __future__ import annotations

from common_lore_index.storage.lexical_fence_sql import (
    LATERAL_EVIDENCE_LINK_SQL,
    LEXICAL_FENCE_CTE_SQL,
)

DEFAULT_MAX_OCCURRENCES_PER_FILE = 1024

LITERAL_CAPTURED_TEXT_QUERY_SQL = f"""
WITH RECURSIVE
{LEXICAL_FENCE_CTE_SQL},
scoped_documents AS MATERIALIZED (
    SELECT
        doc.repository_id,
        doc.lexical_generation_id,
        ag.gen_run_id AS run_id,
        ag.representation_version,
        doc.binding_id,
        doc.source_relative_path,
        doc.normalized_byte_length,
        doc.normalized_text,
        doc.artifact_privacy
    FROM cloe_lexical.documents doc
    JOIN admitted_generation ag
      ON ag.repository_id = doc.repository_id
     AND ag.lexical_generation_id = doc.lexical_generation_id
    WHERE doc.binding_id = ANY(%(admitted_binding_ids)s::text[])
      AND (
          cardinality(%(path_prefixes)s::text[]) = 0
          OR EXISTS (
              SELECT 1
              FROM unnest(%(path_prefixes)s::text[]) AS p(prefix)
               WHERE doc.source_relative_path = p.prefix OR
                     left(doc.source_relative_path, length(p.prefix) + 1) = p.prefix || '/'
          )
      )
),
literal_scan_budget AS MATERIALIZED (
    SELECT
        (
            count(*) > 4096
            OR COALESCE(sum(sd.normalized_byte_length), 0) > 16777216
        ) AS overflowed
    FROM scoped_documents sd
),
eligible_documents AS MATERIALIZED (
    SELECT
        doc.repository_id,
        doc.lexical_generation_id,
        doc.run_id,
        doc.representation_version,
        doc.binding_id,
        doc.source_relative_path,
        doc.normalized_text,
        doc.artifact_privacy
    FROM scoped_documents doc
    CROSS JOIN literal_scan_budget lsb
    WHERE NOT lsb.overflowed
      AND strpos(doc.normalized_text, %(query_text)s) > 0
),
raw_occurrences AS (
    SELECT
        ed.repository_id,
        ed.lexical_generation_id,
        ed.run_id,
        ed.representation_version,
        ed.binding_id,
        ed.source_relative_path,
        ed.normalized_text,
        ed.artifact_privacy,
        1 AS occurrence_index,
        strpos(ed.normalized_text, %(query_text)s) AS match_pos_1
    FROM eligible_documents ed
    UNION ALL
    SELECT
        ro.repository_id,
        ro.lexical_generation_id,
        ro.run_id,
        ro.representation_version,
        ro.binding_id,
        ro.source_relative_path,
        ro.normalized_text,
        ro.artifact_privacy,
        ro.occurrence_index + 1 AS occurrence_index,
        ro.match_pos_1 + strpos(substr(ro.normalized_text, ro.match_pos_1 + 1), %(query_text)s) AS match_pos_1
    FROM raw_occurrences ro
    WHERE ro.occurrence_index <= %(max_occurrences_per_file)s
      AND strpos(substr(ro.normalized_text, ro.match_pos_1 + 1), %(query_text)s) > 0
),
capped_files AS MATERIALIZED (
    SELECT DISTINCT
        ro.binding_id,
        ro.source_relative_path
    FROM raw_occurrences ro
    WHERE ro.occurrence_index > %(max_occurrences_per_file)s
),
admitted_occurrences AS MATERIALIZED (
    SELECT
        ro.repository_id,
        ro.lexical_generation_id,
        ro.run_id,
        ro.representation_version,
        ro.binding_id,
        ro.source_relative_path,
        ro.artifact_privacy,
        ro.occurrence_index,
        ro.match_pos_1,
        1 + (ro.match_pos_1 - 1) - char_length(
            replace(left(ro.normalized_text, ro.match_pos_1 - 1), chr(10), '')
        ) AS start_line,
        1 + (
            CASE
                WHEN right(%(query_text)s, 1) = chr(10) AND char_length(%(query_text)s) > 1
                    THEN ro.match_pos_1 + char_length(%(query_text)s) - 2
                ELSE ro.match_pos_1 + char_length(%(query_text)s) - 1
            END - 1
        ) - char_length(
            replace(
                left(
                    ro.normalized_text,
                    CASE
                        WHEN right(%(query_text)s, 1) = chr(10) AND char_length(%(query_text)s) > 1
                            THEN ro.match_pos_1 + char_length(%(query_text)s) - 2
                        ELSE ro.match_pos_1 + char_length(%(query_text)s) - 1
                    END - 1
                ),
                chr(10),
                ''
            )
        ) AS end_line
    FROM raw_occurrences ro
    WHERE ro.occurrence_index <= %(max_occurrences_per_file)s
),
ordered_hits AS MATERIALIZED (
    SELECT
        ao.repository_id,
        ao.lexical_generation_id,
        ao.run_id,
        ao.representation_version,
        ao.binding_id,
        ao.source_relative_path,
        ao.artifact_privacy,
        ao.occurrence_index,
        ao.match_pos_1,
        ao.start_line,
        GREATEST(ao.start_line, ao.end_line) AS end_line,
        ch.chunk_id,
        ch.chunk_sha256
    FROM admitted_occurrences ao
    LEFT JOIN LATERAL (
        SELECT c.chunk_id, c.chunk_sha256
        FROM cloe_lexical.chunks c
        WHERE c.repository_id = ao.repository_id
          AND c.lexical_generation_id = ao.lexical_generation_id
          AND c.binding_id = ao.binding_id
          AND c.source_relative_path = ao.source_relative_path
        ORDER BY
            (c.start_line <= ao.start_line AND c.end_line >= ao.start_line) DESC,
            c.chunk_ordinal ASC
        LIMIT 1
    ) ch ON true
    ORDER BY
        ao.binding_id COLLATE "C" ASC,
        ao.source_relative_path COLLATE "C" ASC,
        ao.start_line ASC,
        GREATEST(ao.start_line, ao.end_line) ASC,
        ao.match_pos_1 ASC,
        COALESCE(ch.chunk_id, '') COLLATE "C" ASC
),
paged AS MATERIALIZED (
    SELECT *
    FROM ordered_hits
    OFFSET %(offset)s
    LIMIT %(limit)s
),
enriched_hits AS MATERIALIZED (
    SELECT
        paged.binding_id,
        paged.source_relative_path,
        paged.start_line,
        paged.end_line,
        paged.match_pos_1,
        paged.chunk_id,
        paged.chunk_sha256,
        paged.representation_version,
        paged.artifact_privacy,
        1.0::double precision AS score,
        ev.canonical_key,
        ev.evidence_key,
        ev.link_kind
    FROM paged
    {LATERAL_EVIDENCE_LINK_SQL}
    ORDER BY
        paged.binding_id COLLATE "C" ASC,
        paged.source_relative_path COLLATE "C" ASC,
        paged.start_line ASC,
        paged.end_line ASC,
        paged.match_pos_1 ASC,
        COALESCE(paged.chunk_id, '') COLLATE "C" ASC
)
SELECT json_build_object(
    'fence_status', (SELECT status FROM fence_state),
    'lexical_generation_id', (SELECT active_generation_id FROM fence_state),
    'latest_generation_id', (SELECT latest_generation_id FROM fence_state),
    'latest_revocation_reason', (SELECT latest_revocation_reason FROM fence_state),
    'run_id', (SELECT live_run_id FROM fence_state),
    'publication_bundle_id', (SELECT live_bundle_id FROM fence_state),
    'snapshot_manifest_id', (SELECT live_manifest_id FROM fence_state),
    'extraction_receipt_id', (SELECT live_receipt_id FROM fence_state),
    'graph_candidate_id', (SELECT live_candidate_id FROM fence_state),
    'total_matches', (SELECT count(*)::int FROM ordered_hits),
    'candidate_overflow', COALESCE((SELECT overflowed FROM literal_scan_budget), false),
    'capped_files', COALESCE(
        (
            SELECT json_agg(
                json_build_object(
                    'binding_id', cf.binding_id,
                    'source_relative_path', cf.source_relative_path
                )
                ORDER BY cf.binding_id COLLATE "C" ASC, cf.source_relative_path COLLATE "C" ASC
            )
            FROM capped_files cf
        ),
        '[]'::json
    ),
    'omissions', COALESCE(
        (
            SELECT json_agg(
                json_build_object(
                    'binding_id', so.binding_id,
                    'source_relative_path', so.source_relative_path,
                    'reason_code', so.reason_code,
                    'detail', so.detail
                )
                ORDER BY so.omission_ordinal ASC
            )
            FROM scoped_omissions so
        ),
        '[]'::json
    ),
    'hits', COALESCE(
        (
            SELECT json_agg(row_to_json(eh) ORDER BY
                eh.binding_id COLLATE "C" ASC, eh.source_relative_path COLLATE "C" ASC,
                eh.start_line ASC, eh.end_line ASC, eh.match_pos_1 ASC,
                COALESCE(eh.chunk_id, '') COLLATE "C" ASC)
            FROM enriched_hits eh
        ),
        '[]'::json
    )
)::text
"""

__all__ = [
    "DEFAULT_MAX_OCCURRENCES_PER_FILE",
    "LITERAL_CAPTURED_TEXT_QUERY_SQL",
]
