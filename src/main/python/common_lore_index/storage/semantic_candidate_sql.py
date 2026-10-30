"""Source-blind exact pgvector retrieval over accepted publication evidence."""

from __future__ import annotations

from common_lore_index.storage._publication_fencing_sql import build_receipt_predicate_sql
from common_lore_index.storage.semantic_candidates import CandidatePublication, CandidateQuery, EmbeddingProfile, EmbeddingProfilesQuery, PGVECTOR_VERSION
from common_lore_index.storage.sql_core import sql_literal


CAPABILITY_PROBE_SQL = """SELECT json_build_object(
    'installed_version', (SELECT extversion FROM pg_catalog.pg_extension WHERE extname = 'vector'),
    'installation_schema', (SELECT n.nspname FROM pg_catalog.pg_extension e
        JOIN pg_catalog.pg_namespace n ON n.oid = e.extnamespace WHERE e.extname = 'vector'),
    'schema_version', (SELECT obj_description(n.oid, 'pg_namespace')
        FROM pg_catalog.pg_namespace n WHERE n.nspname = 'repomap_enrichment'),
    'objects_present', to_regclass('repomap_enrichment.rebuilds') IS NOT NULL
        AND to_regclass('repomap_enrichment.embeddings') IS NOT NULL
)::text;"""


def accepted_publication_sql(query: CandidateQuery) -> str:
    """Latest complete run, never the latest receipt-bearing historical fallback."""
    return accepted_candidate_publication_sql(query.publication)


def accepted_candidate_publication_sql(publication: CandidatePublication) -> str:
    """Fence an exact complete receipt against the latest graph publication."""
    predicate = build_receipt_predicate_sql(publication.publication.receipt)["matching"]
    return f"""latest AS MATERIALIZED (
        SELECT runs.* FROM public.runs
        JOIN public.repositories repo ON repo.id = runs.repository_id
        WHERE repo.repository_identity = {sql_literal(publication.repository_identity)}
          AND runs.status = 'complete' ORDER BY runs.id DESC LIMIT 1
    ), accepted AS MATERIALIZED (
        SELECT * FROM latest WHERE id = {publication.publication.run_id} AND {predicate}
    )"""


def build_candidate_query_sql(query: CandidateQuery) -> str:
    query.validate()
    vector = sql_literal("[" + ",".join(str(float(v)) for v in query.vector) + "]")
    profile = query.profile
    portable = query.publication.publication.receipt.portable
    assert portable is not None
    metadata_filters = " AND ".join(
        f"rebuild.{field} = {sql_literal(str(value))}"
        for field, value in (
            *profile.__dict__.items(),
            *zip(query.publication.publication.receipt.generations.field_names(),
                 query.publication.publication.receipt.generations.values(), strict=True),
            ("publication_bundle_id", portable.publication_bundle_id),
            ("snapshot_manifest_id", portable.snapshot_manifest_id),
        ) if field != "dimensions"
    )
    filters = ["node.graph_key_version = 1", "node.last_seen_run_id = accepted.id"]
    if query.kind is not None:
        filters.append(f"node.kind = {sql_literal(query.kind)}")
    if query.source_binding_id is not None:
        filters.append(f"embedding.source_binding_id = {sql_literal(query.source_binding_id)}")
    path_filter = "" if query.path is None else f"AND evidence.path = {sql_literal(query.path)}"
    evidence_scope = f"""evidence.repository_id = accepted.repository_id
        AND evidence.run_id = accepted.id AND evidence.graph_key_version = 1
        AND evidence.metadata_json->>'binding_id' = embedding.source_binding_id
        AND evidence.metadata_json->>'snapshot_id' = embedding.snapshot_id
        {path_filter}"""
    return f"""WITH {accepted_publication_sql(query)},
    matching AS MATERIALIZED (
        SELECT rebuild.* FROM repomap_enrichment.rebuilds rebuild JOIN accepted
          ON rebuild.repository_identity = {sql_literal(query.publication.repository_identity)}
         AND rebuild.run_id = accepted.id
         AND rebuild.receipt_identity = {sql_literal(query.publication.receipt_identity)}
        WHERE rebuild.rebuild_id = {sql_literal(query.rebuild_id)}
          AND rebuild.profile_identity = {sql_literal(profile.identity)}
          AND rebuild.dimensions = {profile.dimensions} AND rebuild.privacy_class = 'public'
          AND {metadata_filters}
          AND rebuild.row_count = (SELECT count(*) FROM repomap_enrichment.embeddings e
            WHERE e.rebuild_id = rebuild.rebuild_id)
          AND EXISTS (SELECT 1 FROM pg_catalog.pg_extension ext
            JOIN pg_catalog.pg_namespace n ON n.oid = ext.extnamespace
            WHERE ext.extname = 'vector' AND ext.extversion = '{PGVECTOR_VERSION}'
              AND n.nspname = 'repomap_vector')
    ), distances AS MATERIALIZED (
        SELECT node.id AS node_id, node.canonical_key, node.kind, node.display_name,
            node.confidence, node.conflict, embedding.source_binding_id,
            embedding.input_digest, embedding.snapshot_id,
            embedding.embedding OPERATOR(repomap_vector.<=>) {vector}::repomap_vector.vector AS distance
        FROM matching JOIN accepted ON accepted.id = matching.run_id
        JOIN repomap_enrichment.embeddings embedding USING (rebuild_id)
        JOIN public.canonical_nodes node ON node.repository_id = accepted.repository_id
          AND node.canonical_key = embedding.canonical_key
        WHERE {' AND '.join(filters)}
          AND repomap_vector.vector_dims(embedding.embedding) = {profile.dimensions}
          AND EXISTS (SELECT 1 FROM public.canonical_node_evidence link
            JOIN public.canonical_evidence evidence ON evidence.id = link.canonical_evidence_id
            WHERE link.canonical_node_id = node.id AND {evidence_scope})
    ), nearest AS MATERIALIZED (
        SELECT * FROM distances ORDER BY distance, canonical_key COLLATE "C", source_binding_id COLLATE "C"
        LIMIT {query.limit}
    ), expanded AS (
        SELECT nearest.*, (
            SELECT COALESCE(json_agg(row_to_json(items)), '[]'::json) FROM (
                SELECT evidence.evidence_key, evidence.path, evidence.start_line, evidence.end_line,
                    evidence.raw_kind, evidence.extractor, evidence.extractor_version, evidence.confidence
                FROM public.canonical_node_evidence link
                JOIN public.canonical_evidence evidence ON evidence.id = link.canonical_evidence_id
                JOIN accepted ON evidence.repository_id = accepted.repository_id
                WHERE link.canonical_node_id = nearest.node_id AND evidence.run_id = accepted.id
                  AND evidence.metadata_json->>'binding_id' = nearest.source_binding_id
                  AND evidence.metadata_json->>'snapshot_id' = nearest.snapshot_id
                  {path_filter}
                ORDER BY evidence.evidence_key COLLATE "C" LIMIT {query.evidence_limit}
            ) items
        ) AS evidence FROM nearest
    ) SELECT json_build_object(
        'status', CASE WHEN NOT EXISTS (SELECT 1 FROM accepted) THEN 'stale_publication'
            WHEN NOT EXISTS (SELECT 1 FROM matching) THEN 'enrichment_unavailable' ELSE 'ok' END,
        'candidates', (SELECT COALESCE(json_agg(row_to_json(expanded)
            ORDER BY distance, canonical_key COLLATE "C", source_binding_id COLLATE "C"), '[]'::json) FROM expanded)
    )::text;"""

def build_embedding_profiles_sql(publication: CandidatePublication, query: EmbeddingProfilesQuery) -> str:
    publication.validate()
    query.validate()
    receipt = publication.publication.receipt
    portable = receipt.portable
    assert portable is not None
    metadata = " AND ".join(
        f"rebuild.{field} = {sql_literal(value)}" for field, value in (
            *zip(receipt.generations.field_names(), receipt.generations.values(), strict=True),
            ("publication_bundle_id", portable.publication_bundle_id),
            ("snapshot_manifest_id", portable.snapshot_manifest_id),
            ("receipt_identity", publication.receipt_identity),
        )
    )
    snapshots = ", ".join(f"({sql_literal(binding)}, {sql_literal(snapshot)})"
                          for binding, _, snapshot in portable.snapshot_vector)
    fields = ("rebuild_id", "profile_identity", *EmbeddingProfile.__dataclass_fields__, "row_count")
    projection = ", ".join(f"rebuild.{field}" for field in fields)
    return f"""WITH {accepted_candidate_publication_sql(publication)},
    capability AS MATERIALIZED (
        SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_extension ext
            JOIN pg_catalog.pg_namespace ns ON ns.oid = ext.extnamespace
            WHERE ext.extname = 'vector' AND ext.extversion = '{PGVECTOR_VERSION}'
              AND ns.nspname = 'repomap_vector') AS extension_ok,
            EXISTS (SELECT 1 FROM pg_catalog.pg_namespace ns
                WHERE ns.nspname = 'repomap_enrichment'
                  AND obj_description(ns.oid, 'pg_namespace') = 'repomap-enrichment-schema:1') AS schema_ok
    ), snapshots(binding_id, snapshot_id) AS (VALUES {snapshots}),
    scoped AS MATERIALIZED (
        SELECT rebuild.* FROM repomap_enrichment.rebuilds rebuild
        WHERE rebuild.repository_identity = {sql_literal(publication.repository_identity)}
    ), bound AS MATERIALIZED (
        SELECT rebuild.* FROM scoped rebuild JOIN accepted ON rebuild.run_id = accepted.id
        WHERE {metadata} AND rebuild.privacy_class = 'public'
    ), eligible AS MATERIALIZED (
        SELECT {projection}, (SELECT COALESCE(json_agg(row_to_json(source)
            ORDER BY source.source_binding_id COLLATE "C", source.snapshot_id COLLATE "C"), '[]'::json)
            FROM (SELECT DISTINCT e.source_binding_id, e.snapshot_id
                FROM repomap_enrichment.embeddings e WHERE e.rebuild_id = rebuild.rebuild_id) source
            ) AS source_scope
        FROM bound rebuild JOIN accepted ON true
        WHERE rebuild.row_count BETWEEN 1 AND 500
          AND rebuild.row_count = (SELECT count(*) FROM repomap_enrichment.embeddings e
              WHERE e.rebuild_id = rebuild.rebuild_id)
          AND NOT EXISTS (
            SELECT 1 FROM repomap_enrichment.embeddings e WHERE e.rebuild_id = rebuild.rebuild_id
              AND (e.dimensions <> rebuild.dimensions OR e.input_digest !~ '^sha256:[0-9a-f]{{64}}$'
                OR NOT EXISTS (
                    SELECT 1 FROM public.canonical_nodes node
                    JOIN public.canonical_node_evidence link ON link.canonical_node_id = node.id
                    JOIN public.canonical_evidence evidence ON evidence.id = link.canonical_evidence_id
                    JOIN snapshots ON snapshots.binding_id = e.source_binding_id
                      AND snapshots.snapshot_id = e.snapshot_id
                    WHERE node.repository_id = accepted.repository_id
                      AND node.canonical_key = e.canonical_key
                      AND node.graph_key_version = 1 AND node.last_seen_run_id = accepted.id
                      AND evidence.repository_id = accepted.repository_id
                      AND evidence.run_id = accepted.id AND evidence.graph_key_version = 1
                      AND evidence.metadata_json->>'binding_id' = snapshots.binding_id
                      AND evidence.metadata_json->>'snapshot_id' = snapshots.snapshot_id))
          )
    ), page AS MATERIALIZED (
        SELECT * FROM eligible ORDER BY rebuild_id COLLATE "C" LIMIT {query.limit + 1}
    ) SELECT json_build_object(
        'status', CASE WHEN NOT EXISTS (SELECT 1 FROM accepted) THEN 'stale_publication'
            WHEN NOT (SELECT extension_ok FROM capability) THEN 'extension_unsupported'
            WHEN NOT (SELECT schema_ok FROM capability) THEN 'enrichment_schema_absent_or_unsupported'
            WHEN NOT EXISTS (SELECT 1 FROM scoped) THEN 'no_import'
            WHEN NOT EXISTS (SELECT 1 FROM bound) THEN 'stale_rebuild'
            WHEN NOT EXISTS (SELECT 1 FROM eligible) THEN 'invalid_rebuild' ELSE 'ok' END,
        'has_excluded_rebuilds', EXISTS (SELECT 1 FROM scoped
            WHERE NOT EXISTS (SELECT 1 FROM eligible WHERE eligible.rebuild_id = scoped.rebuild_id)),
        'profiles', (SELECT COALESCE(json_agg(row_to_json(page)
            ORDER BY rebuild_id COLLATE "C"), '[]'::json) FROM page)
    )::text;"""
