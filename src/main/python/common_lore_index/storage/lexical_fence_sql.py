"""Single-statement publication and policy fence CTE builders for cloe_lexical queries."""

from __future__ import annotations

from common_lore_index.storage.publication import RunPublicationReceipt

_RUN_RECEIPT_JSON_COLS = ", ".join(
    f"'{f}', runs.{f}" for f in RunPublicationReceipt.field_names()
)

LEXICAL_FENCE_CTE_SQL = f"""
matched_repo AS MATERIALIZED (
    SELECT r.id AS repository_id, r.name AS repository_name, r.repository_identity
    FROM public.repositories r
    WHERE (%(repository_identity)s::text IS NOT NULL AND r.repository_identity = %(repository_identity)s)
       OR (r.repository_identity IS NULL AND %(repository_name)s::text IS NOT NULL AND r.name = %(repository_name)s)
       OR (r.repository_identity IS NULL AND %(root_path)s::text IS NOT NULL AND r.root_path = %(root_path)s)
    ORDER BY
        (r.repository_identity = %(repository_identity)s) DESC NULLS LAST,
        (r.name = %(repository_name)s) DESC NULLS LAST,
        (r.root_path = %(root_path)s) DESC NULLS LAST,
        r.id DESC
    LIMIT 1
),
latest_complete_run AS MATERIALIZED (
    SELECT
        runs.id AS run_id,
        runs.repository_id,
        runs.execution_route,
        runs.publication_bundle_id,
        runs.snapshot_manifest_id,
        runs.extraction_receipt_id,
        runs.graph_candidate_id,
        runs.snapshot_vector_json,
        json_build_object({_RUN_RECEIPT_JSON_COLS})::jsonb AS publication_receipt_jsonb,
        (
            runs.portable_execution_mode <> 'coordinator'
            OR EXISTS (
                SELECT 1
                FROM public.graph_publication_authority gpa
                WHERE gpa.repository_id = runs.repository_id
                  AND gpa.last_run_id = runs.id
            )
        ) AS authority_consistent
    FROM public.runs runs
    JOIN matched_repo mr ON mr.repository_id = runs.repository_id
    WHERE runs.status = 'complete'
    ORDER BY runs.id DESC
    LIMIT 1
),
active_authority AS MATERIALIZED (
    SELECT
        auth.repository_id,
        auth.lexical_generation_id,
        auth.run_id AS authority_run_id,
        auth.publication_bundle_id AS authority_bundle_id,
        auth.snapshot_manifest_id AS authority_manifest_id,
        auth.policy_digest AS authority_policy_digest,
        gen.run_id AS gen_run_id,
        gen.publication_bundle_id AS gen_bundle_id,
        gen.snapshot_manifest_id AS gen_manifest_id,
        gen.extraction_receipt_id AS gen_receipt_id,
        gen.graph_candidate_id AS gen_candidate_id,
        gen.snapshot_vector_json AS gen_vector_json,
        gen.publication_receipt_json AS gen_receipt_json,
        gen.policy_digest AS gen_policy_digest,
        gen.resolved_graph_privacy,
        gen.binding_policy_digests_json,
        gen.admitted_binding_ids_json,
        gen.representation_version,
        gen.text_config_regconfig,
        gen.ranking_function,
        gen.normalization_flags,
        gen.alias_split_rule_version,
        gen.state AS gen_state
    FROM cloe_lexical.authority auth
    JOIN matched_repo mr ON mr.repository_id = auth.repository_id
    JOIN cloe_lexical.generations gen
      ON gen.repository_id = auth.repository_id
     AND gen.lexical_generation_id = auth.lexical_generation_id
),
latest_generation AS MATERIALIZED (
    SELECT
        gen.lexical_generation_id,
        gen.state,
        gen.revocation_reason
    FROM cloe_lexical.generations gen
    JOIN matched_repo mr ON mr.repository_id = gen.repository_id
    ORDER BY gen.created_at DESC, gen.lexical_generation_id DESC
    LIMIT 1
),
fence_state AS MATERIALIZED (
    SELECT
        CASE
            WHEN NOT EXISTS (SELECT 1 FROM matched_repo) THEN 'repository_missing'
            WHEN NOT EXISTS (
                SELECT 1 FROM latest_complete_run lcr
                WHERE lcr.execution_route = 'portable-worker-v1'
                  AND lcr.publication_bundle_id IS NOT NULL
                  AND lcr.snapshot_manifest_id IS NOT NULL
                  AND lcr.extraction_receipt_id IS NOT NULL
                  AND lcr.graph_candidate_id IS NOT NULL
                  AND lcr.snapshot_vector_json IS NOT NULL
                  AND lcr.authority_consistent
            ) THEN 'stale_graph_publication_missing'
            WHEN NOT EXISTS (SELECT 1 FROM active_authority) THEN
                CASE
                    WHEN EXISTS (SELECT 1 FROM latest_generation lg WHERE lg.state = 'revoked')
                        THEN 'unavailable_lexical_generation_revoked'
                    WHEN EXISTS (SELECT 1 FROM latest_generation lg WHERE lg.state = 'invalidated')
                        THEN 'stale_lexical_generation_invalidated'
                    WHEN EXISTS (SELECT 1 FROM latest_generation lg WHERE lg.state = 'building')
                        THEN 'unavailable_lexical_generation_building'
                    ELSE 'unavailable_no_lexical_generation'
                END
            WHEN EXISTS (SELECT 1 FROM active_authority aa WHERE aa.gen_state <> 'published')
                THEN 'unavailable_lexical_generation_not_published'
            WHEN EXISTS (
                SELECT 1 FROM active_authority aa
                WHERE aa.resolved_graph_privacy <> 'public-dev'
            ) THEN 'refused_non_public_lexical_generation'
            WHEN EXISTS (
                SELECT 1
                FROM active_authority aa
                CROSS JOIN latest_complete_run lcr
                WHERE aa.authority_run_id <> lcr.run_id
                   OR aa.gen_run_id <> lcr.run_id
            ) THEN 'stale_run_id_mismatch'
            WHEN EXISTS (
                SELECT 1
                FROM active_authority aa
                CROSS JOIN latest_complete_run lcr
                WHERE aa.authority_bundle_id <> lcr.publication_bundle_id
                   OR aa.gen_bundle_id <> lcr.publication_bundle_id
            ) THEN 'stale_publication_bundle_mismatch'
            WHEN EXISTS (
                SELECT 1
                FROM active_authority aa
                CROSS JOIN latest_complete_run lcr
                WHERE aa.authority_manifest_id <> lcr.snapshot_manifest_id
                   OR aa.gen_manifest_id <> lcr.snapshot_manifest_id
            ) THEN 'stale_snapshot_manifest_mismatch'
            WHEN EXISTS (
                SELECT 1
                FROM active_authority aa
                CROSS JOIN latest_complete_run lcr
                WHERE aa.gen_receipt_id <> lcr.extraction_receipt_id
                   OR aa.gen_candidate_id <> lcr.graph_candidate_id
                   OR aa.gen_vector_json::jsonb <> lcr.snapshot_vector_json::jsonb
                   OR (
                       aa.gen_receipt_json <> '{{}}'
                       AND aa.gen_receipt_json::jsonb <> lcr.publication_receipt_jsonb
                   )
            ) THEN 'stale_publication_vector_mismatch'
            WHEN EXISTS (
                SELECT 1
                FROM active_authority aa,
                     jsonb_array_elements_text(aa.admitted_binding_ids_json::jsonb) AS adm(b_id)
                WHERE (%(privacy_excluded_bindings_json)s::jsonb) ? adm.b_id
            ) THEN 'refused_reclassified:' || (
                SELECT (%(privacy_excluded_bindings_json)s::jsonb) ->> adm.b_id
                FROM active_authority aa,
                     jsonb_array_elements_text(aa.admitted_binding_ids_json::jsonb) AS adm(b_id)
                WHERE (%(privacy_excluded_bindings_json)s::jsonb) ? adm.b_id
                ORDER BY adm.b_id ASC
                LIMIT 1
            )
            WHEN EXISTS (
                SELECT 1
                FROM active_authority aa
                WHERE aa.authority_policy_digest <> %(expected_policy_digest)s
                   OR aa.gen_policy_digest <> %(expected_policy_digest)s
                   OR aa.binding_policy_digests_json <> %(expected_binding_policy_digests_json)s
            ) THEN 'stale_policy_digest_mismatch'
            WHEN EXISTS (
                SELECT 1
                FROM active_authority aa,
                     unnest(%(admitted_binding_ids)s::text[]) AS req(b_id)
                WHERE NOT ((aa.admitted_binding_ids_json::jsonb) ? req.b_id)
            ) THEN 'unavailable_requested_binding_not_projected'
            ELSE 'ok'
        END AS status,
        (SELECT lexical_generation_id FROM active_authority LIMIT 1) AS active_generation_id,
        (SELECT lexical_generation_id FROM latest_generation LIMIT 1) AS latest_generation_id,
        (SELECT revocation_reason FROM latest_generation LIMIT 1) AS latest_revocation_reason,
        (SELECT run_id FROM latest_complete_run LIMIT 1) AS live_run_id,
        (SELECT publication_bundle_id FROM latest_complete_run LIMIT 1) AS live_bundle_id,
        (SELECT snapshot_manifest_id FROM latest_complete_run LIMIT 1) AS live_manifest_id,
        (SELECT extraction_receipt_id FROM latest_complete_run LIMIT 1) AS live_receipt_id,
        (SELECT graph_candidate_id FROM latest_complete_run LIMIT 1) AS live_candidate_id
),
admitted_generation AS MATERIALIZED (
    SELECT aa.*
    FROM active_authority aa
    JOIN fence_state fs ON fs.status = 'ok'
),
scoped_omissions AS MATERIALIZED (
    SELECT
        om.omission_ordinal,
        om.binding_id,
        om.source_relative_path,
        om.reason_code,
        om.detail
    FROM cloe_lexical.omissions om
    JOIN admitted_generation ag
      ON ag.repository_id = om.repository_id
     AND ag.lexical_generation_id = om.lexical_generation_id
    WHERE om.binding_id = ANY(%(omission_binding_ids)s::text[])
      AND (
          om.source_relative_path IS NULL
          OR cardinality(%(path_prefixes)s::text[]) = 0
          OR EXISTS (
              SELECT 1
              FROM unnest(%(path_prefixes)s::text[]) AS p(prefix)
              WHERE om.source_relative_path = p.prefix OR
                    left(om.source_relative_path, length(p.prefix) + 1) = p.prefix || '/'
          )
      )
    ORDER BY om.omission_ordinal ASC
)
"""

LATERAL_EVIDENCE_LINK_SQL = """
LEFT JOIN LATERAL (
    SELECT
        ce.evidence_key AS evidence_key,
        cn.canonical_key AS canonical_key,
        cne.link_kind AS link_kind
    FROM public.canonical_evidence ce
    LEFT JOIN public.canonical_node_evidence cne
      ON cne.canonical_evidence_id = ce.id
    LEFT JOIN public.canonical_nodes cn
      ON cn.id = cne.canonical_node_id
     AND cn.repository_id = paged.repository_id
     AND cn.graph_key_version = 1
     AND cn.last_seen_run_id = paged.run_id
    WHERE ce.repository_id = paged.repository_id
      AND ce.run_id = paged.run_id
      AND ce.graph_key_version = 1
      AND ce.metadata_json->>'binding_id' = paged.binding_id
      AND ce.metadata_json->>'source_relative_path' = paged.source_relative_path
      AND ce.start_line IS NOT NULL
      AND ce.start_line <= paged.end_line
      AND COALESCE(ce.end_line, ce.start_line) >= paged.start_line
    ORDER BY
        ce.start_line ASC,
        COALESCE(ce.end_line, ce.start_line) ASC,
        ce.evidence_key COLLATE "C" ASC,
        COALESCE(cn.canonical_key, '') COLLATE "C" ASC,
        COALESCE(cne.link_kind, '') COLLATE "C" ASC
    LIMIT 1
) ev ON true
"""

__all__ = [
    "LATERAL_EVIDENCE_LINK_SQL",
    "LEXICAL_FENCE_CTE_SQL",
]
