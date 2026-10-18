"""One MVCC snapshot for accepted publication, qualified seed and candidates."""

from __future__ import annotations

from repomap_kg.storage.semantic_candidate_sql import accepted_candidate_publication_sql
from repomap_kg.storage.semantic_candidates import CandidatePublication, PGVECTOR_VERSION
from repomap_kg.storage.semantic_seed import SimilarNodesQuery
from repomap_kg.storage.sql_core import sql_literal


def build_seed_query_sql(publication: CandidatePublication, query: SimilarNodesQuery) -> str:
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
        )
    )
    snapshots = ", ".join(
        f"({sql_literal(binding)}, {sql_literal(snapshot)})"
        for binding, _, snapshot in portable.snapshot_vector
    )
    seed_binding = "" if query.source_binding_id is None else (
        f"AND evidence.metadata_json->>'binding_id' = {sql_literal(query.source_binding_id)}"
    )
    kind_filter = "" if query.kind is None else f"AND node.kind = {sql_literal(query.kind)}"
    path_filter = "" if query.path is None else f"AND evidence.path = {sql_literal(query.path)}"
    profile_fields = (
        "model", "model_version", "generator", "generator_version", "dimensions",
        "representation_version", "normalization", "metric",
    )
    profile_json = ", ".join(f"'{field}', {field}" for field in profile_fields)
    return f"""WITH {accepted_candidate_publication_sql(publication)},
    snapshots(binding_id, snapshot_id) AS (VALUES {snapshots}),
    bound_rebuild AS MATERIALIZED (
        SELECT rebuild.* FROM repomap_enrichment.rebuilds rebuild JOIN accepted
          ON rebuild.repository_identity = {sql_literal(publication.repository_identity)}
         AND rebuild.run_id = accepted.id
         AND rebuild.receipt_identity = {sql_literal(publication.receipt_identity)}
        WHERE rebuild.rebuild_id = {sql_literal(query.rebuild_id)}
          AND rebuild.privacy_class = 'public' AND {metadata}
          AND rebuild.row_count = (SELECT count(*) FROM repomap_enrichment.embeddings e
              WHERE e.rebuild_id = rebuild.rebuild_id)
          AND EXISTS (SELECT 1 FROM pg_catalog.pg_extension ext
            JOIN pg_catalog.pg_namespace n ON n.oid = ext.extnamespace
            WHERE ext.extname = 'vector' AND ext.extversion = '{PGVECTOR_VERSION}'
              AND n.nspname = 'repomap_vector')
    ), matching AS MATERIALIZED (
        SELECT * FROM bound_rebuild WHERE profile_identity = {sql_literal(query.profile_identity)}
          AND dimensions = {query.dimensions} AND representation_version = 'canonical-node-v1'
          AND normalization = 'l2-unit' AND metric = 'cosine'
    ), seed_identities AS MATERIALIZED (
        SELECT DISTINCT node.canonical_key, snapshots.binding_id AS source_binding_id,
            snapshots.snapshot_id
        FROM public.canonical_nodes node JOIN accepted ON node.repository_id = accepted.repository_id
        JOIN public.canonical_node_evidence link ON link.canonical_node_id = node.id
        JOIN public.canonical_evidence evidence ON evidence.id = link.canonical_evidence_id
        JOIN snapshots ON evidence.metadata_json->>'binding_id' = snapshots.binding_id
          AND evidence.metadata_json->>'snapshot_id' = snapshots.snapshot_id
        WHERE node.canonical_key = {sql_literal(query.canonical_key)}
          AND node.graph_key_version = 1 AND node.last_seen_run_id = accepted.id
          AND evidence.repository_id = accepted.repository_id AND evidence.run_id = accepted.id
          AND evidence.graph_key_version = 1 {seed_binding}
    ), seed AS MATERIALIZED (
        SELECT embedding.* FROM matching
        JOIN repomap_enrichment.embeddings embedding USING (rebuild_id)
        JOIN seed_identities identity ON identity.canonical_key = embedding.canonical_key
          AND identity.source_binding_id = embedding.source_binding_id
          AND identity.snapshot_id = embedding.snapshot_id
        WHERE (SELECT count(*) FROM seed_identities) = 1
          AND repomap_vector.vector_dims(embedding.embedding) = {query.dimensions}
    ), distances AS MATERIALIZED (
        SELECT node.canonical_key, node.kind, node.display_name, node.confidence, node.conflict,
            embedding.source_binding_id, embedding.snapshot_id, embedding.input_digest,
            node.id AS node_id,
            embedding.embedding OPERATOR(repomap_vector.<=>) seed.embedding AS distance
        FROM matching JOIN accepted ON accepted.id = matching.run_id
        JOIN repomap_enrichment.embeddings embedding USING (rebuild_id)
        JOIN seed ON seed.rebuild_id = matching.rebuild_id
        JOIN public.canonical_nodes node ON node.repository_id = accepted.repository_id
          AND node.canonical_key = embedding.canonical_key
        WHERE node.graph_key_version = 1 AND node.last_seen_run_id = accepted.id {kind_filter}
          AND (embedding.canonical_key, embedding.source_binding_id)
              <> (seed.canonical_key, seed.source_binding_id)
          AND repomap_vector.vector_dims(embedding.embedding) = {query.dimensions}
          AND EXISTS (SELECT 1 FROM public.canonical_node_evidence link
            JOIN public.canonical_evidence evidence ON evidence.id = link.canonical_evidence_id
            JOIN snapshots ON evidence.metadata_json->>'binding_id' = snapshots.binding_id
              AND evidence.metadata_json->>'snapshot_id' = snapshots.snapshot_id
            WHERE link.canonical_node_id = node.id AND evidence.repository_id = accepted.repository_id
              AND evidence.run_id = accepted.id AND evidence.graph_key_version = 1
              AND snapshots.binding_id = embedding.source_binding_id
              AND snapshots.snapshot_id = embedding.snapshot_id {path_filter})
    ), nearest AS MATERIALIZED (
        SELECT * FROM distances ORDER BY distance, canonical_key COLLATE "C", source_binding_id COLLATE "C"
        LIMIT {query.limit}
    ), expanded AS (
        SELECT nearest.*, (SELECT COALESCE(json_agg(row_to_json(items)), '[]'::json) FROM (
            SELECT evidence.evidence_key, evidence.path, evidence.start_line, evidence.end_line,
                evidence.raw_kind, evidence.extractor, evidence.extractor_version, evidence.confidence
            FROM public.canonical_node_evidence link
            JOIN public.canonical_evidence evidence ON evidence.id = link.canonical_evidence_id
            JOIN accepted ON evidence.repository_id = accepted.repository_id
            WHERE link.canonical_node_id = nearest.node_id AND evidence.run_id = accepted.id
              AND evidence.graph_key_version = 1
              AND evidence.metadata_json->>'binding_id' = nearest.source_binding_id
              AND evidence.metadata_json->>'snapshot_id' = nearest.snapshot_id {path_filter}
            ORDER BY evidence.evidence_key COLLATE "C" LIMIT {query.evidence_limit}
        ) items) AS evidence FROM nearest
    ) SELECT json_build_object(
        'status', CASE WHEN NOT EXISTS (SELECT 1 FROM accepted) THEN 'stale_publication'
            WHEN EXISTS (SELECT 1 FROM repomap_enrichment.rebuilds rebuild
                WHERE rebuild.rebuild_id = {sql_literal(query.rebuild_id)}
                  AND rebuild.repository_identity <> {sql_literal(publication.repository_identity)})
                THEN 'foreign_publication'
            WHEN EXISTS (SELECT 1 FROM repomap_enrichment.rebuilds rebuild
                WHERE rebuild.rebuild_id = {sql_literal(query.rebuild_id)}
                  AND (rebuild.run_id <> {publication.publication.run_id}
                    OR rebuild.receipt_identity <> {sql_literal(publication.receipt_identity)}
                    OR NOT ({metadata}))) THEN 'stale_rebuild'
            WHEN NOT EXISTS (SELECT 1 FROM bound_rebuild) THEN 'enrichment_unavailable'
            WHEN NOT EXISTS (SELECT 1 FROM matching) THEN 'profile_mismatch'
            WHEN NOT EXISTS (SELECT 1 FROM seed_identities) THEN 'seed_node_missing'
            WHEN (SELECT count(*) FROM seed_identities) > 1 THEN 'seed_ambiguous'
            WHEN NOT EXISTS (SELECT 1 FROM seed) THEN 'seed_embedding_missing' ELSE 'ok' END,
        'profile', (SELECT json_build_object({profile_json}) FROM matching),
        'seed', (SELECT json_build_object('canonical_key', canonical_key,
            'source_binding_id', source_binding_id, 'snapshot_id', snapshot_id) FROM seed),
        'candidates', (SELECT COALESCE(json_agg(row_to_json(expanded)
            ORDER BY distance, canonical_key COLLATE "C", source_binding_id COLLATE "C"), '[]'::json) FROM expanded)
    )::text;"""
