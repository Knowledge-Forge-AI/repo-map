"""Explicit enrichment import, separate from refresh and read authority.

SQL builders are experimental lifecycle/import contracts, never startup hooks.
Extension artifact acquisition and extension DDL are deliberately absent.
"""

from __future__ import annotations

from collections.abc import Sequence
import re

from repomap_kg.storage.semantic_candidate_sql import accepted_publication_sql
from repomap_kg.storage.semantic_candidates import (
    CandidatePublication, CandidateQuery, EmbeddingEntry, EmbeddingProfile,
    MAX_IMPORT_ROWS, PGVECTOR_VERSION, checked_identity,
)
from repomap_kg.storage.sql_core import sql_literal

_ROLE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,62}\Z")


def _role(value: str) -> str:
    if not isinstance(value, str) or _ROLE.fullmatch(value) is None:
        raise ValueError("invalid enrichment principal")
    return '"' + value + '"'


def candidate_schema_sql(*, read_principal: str, enrichment_principal: str) -> str:
    """Lifecycle-admin-only optional schema, after explicit extension enablement.

    Production admission and extension-aware backup/restore are not implemented;
    this builder is for a separately admitted disposable experiment (ADR 0077).
    It requires already-installed, lifecycle-owned pgvector and refuses adoption.
    """
    reader, writer = _role(read_principal), _role(enrichment_principal)
    if read_principal == enrichment_principal:
        raise ValueError("read and enrichment principals must be distinct")
    return f"""BEGIN;
DO $candidate_schema$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_extension ext
        JOIN pg_catalog.pg_namespace ns ON ns.oid = ext.extnamespace
        WHERE ext.extname = 'vector' AND ext.extversion = '{PGVECTOR_VERSION}'
          AND ns.nspname = 'repomap_vector'
          AND pg_get_userbyid(ext.extowner) = current_user
          AND pg_get_userbyid(ns.nspowner) = current_user) THEN
        RAISE EXCEPTION 'candidate extension is absent, unsupported or foreign';
    END IF;
END;
$candidate_schema$;
CREATE SCHEMA repomap_enrichment;
COMMENT ON SCHEMA repomap_enrichment IS 'repomap-enrichment-schema:1';
REVOKE ALL ON SCHEMA repomap_vector, repomap_enrichment FROM PUBLIC;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA repomap_vector FROM PUBLIC;
GRANT USAGE ON SCHEMA repomap_vector, repomap_enrichment TO {reader}, {writer};
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA repomap_vector TO {reader}, {writer};
CREATE TABLE repomap_enrichment.rebuilds (
    rebuild_id TEXT PRIMARY KEY,
    repository_identity TEXT NOT NULL,
    run_id BIGINT NOT NULL CHECK (run_id > 0),
    receipt_identity TEXT NOT NULL,
    source_generation TEXT NOT NULL,
    config_generation TEXT NOT NULL,
    extractor_generation TEXT NOT NULL,
    canonicalizer_generation TEXT NOT NULL,
    publication_bundle_id TEXT NOT NULL,
    snapshot_manifest_id TEXT NOT NULL,
    profile_identity TEXT NOT NULL,
    model TEXT NOT NULL, model_version TEXT NOT NULL,
    generator TEXT NOT NULL, generator_version TEXT NOT NULL,
    representation_version TEXT NOT NULL CHECK (representation_version = 'canonical-node-v1'),
    dimensions INTEGER NOT NULL CHECK (dimensions BETWEEN 1 AND 2000),
    normalization TEXT NOT NULL CHECK (normalization = 'l2-unit'),
    metric TEXT NOT NULL CHECK (metric = 'cosine'),
    privacy_class TEXT NOT NULL CHECK (privacy_class = 'public'),
    enrichment_principal TEXT NOT NULL DEFAULT current_user,
    row_count INTEGER NOT NULL CHECK (row_count BETWEEN 1 AND {MAX_IMPORT_ROWS}),
    UNIQUE (rebuild_id, dimensions)
);
CREATE TABLE repomap_enrichment.embeddings (
    rebuild_id TEXT NOT NULL,
    canonical_key TEXT NOT NULL,
    source_binding_id TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    input_digest TEXT NOT NULL CHECK (input_digest ~ '^sha256:[0-9a-f]{{64}}$'),
    dimensions INTEGER NOT NULL,
    embedding repomap_vector.vector NOT NULL,
    PRIMARY KEY (rebuild_id, canonical_key, source_binding_id),
    FOREIGN KEY (rebuild_id, dimensions) REFERENCES repomap_enrichment.rebuilds(rebuild_id, dimensions),
    CHECK (repomap_vector.vector_dims(embedding) = dimensions),
    CHECK (abs(repomap_vector.vector_norm(embedding) - 1) < 0.00001)
);
REVOKE ALL ON ALL TABLES IN SCHEMA repomap_enrichment FROM PUBLIC;
GRANT SELECT ON ALL TABLES IN SCHEMA repomap_enrichment TO {reader};
GRANT SELECT ON ALL TABLES IN SCHEMA repomap_enrichment TO {writer};
GRANT INSERT (
    rebuild_id, repository_identity, receipt_identity, source_generation,
    config_generation, extractor_generation, canonicalizer_generation,
    publication_bundle_id, snapshot_manifest_id, profile_identity,
    model, model_version, generator, generator_version, representation_version,
    normalization, metric, run_id, dimensions, privacy_class, row_count
) ON repomap_enrichment.rebuilds TO {writer};
GRANT INSERT ON repomap_enrichment.embeddings TO {writer};
GRANT SELECT ON public.repositories, public.runs, public.canonical_nodes,
    public.canonical_evidence, public.canonical_node_evidence TO {reader}, {writer};
COMMIT;
"""


def build_embedding_import_sql(
    publication: CandidatePublication, profile: EmbeddingProfile,
    entries: Sequence[EmbeddingEntry], *, rebuild_id: str,
    enrichment_principal: str, public_safe: bool = False,
) -> str:
    """Build one bounded, atomic immutable import; never generate an embedding."""
    publication.validate()
    profile.validate()
    checked_identity(rebuild_id)
    _role(enrichment_principal)
    if public_safe is not True:
        raise ValueError("this slice requires an explicit public-safe import")
    if not 1 <= len(entries) <= MAX_IMPORT_ROWS:
        raise ValueError("embedding import must contain between 1 and 500 records")
    identities: set[tuple[str, str]] = set()
    for entry in entries:
        entry.validate(profile, publication)
        identity = (entry.canonical_key, entry.source_binding_id)
        if identity in identities:
            raise ValueError("duplicate embedding identity")
        identities.add(identity)
    portable = publication.publication.receipt.portable
    assert portable is not None
    snapshots = {binding: snapshot for binding, _, snapshot in portable.snapshot_vector}
    query = CandidateQuery(publication, profile, rebuild_id, entries[0].vector, selected=True)
    values = ",\n".join(
        "(" + ", ".join((sql_literal(entry.canonical_key), sql_literal(entry.source_binding_id),
            sql_literal(snapshots[entry.source_binding_id]), sql_literal(entry.input_digest),
            sql_literal("[" + ",".join(str(float(v)) for v in entry.vector) + "]") + "::repomap_vector.vector")) + ")"
        for entry in entries
    )
    generations = publication.publication.receipt.generations.values()
    metadata = (rebuild_id, publication.repository_identity, publication.receipt_identity,
                *generations, portable.publication_bundle_id, portable.snapshot_manifest_id,
                profile.identity, profile.model, profile.model_version, profile.generator,
                profile.generator_version, profile.representation_version, profile.normalization,
                profile.metric)
    literal = [sql_literal(value) for value in metadata]
    return f"""BEGIN ISOLATION LEVEL REPEATABLE READ;
DO $candidate_import$
BEGIN
    IF current_user <> {sql_literal(enrichment_principal)} THEN
        RAISE EXCEPTION 'embedding import requires the named enrichment principal';
    END IF;
    IF NOT EXISTS (WITH {accepted_publication_sql(query)} SELECT 1 FROM accepted) THEN
        RAISE EXCEPTION 'embedding publication is not current and accepted';
    END IF;
END;
$candidate_import$;
INSERT INTO repomap_enrichment.rebuilds (
    rebuild_id, repository_identity, receipt_identity, source_generation,
    config_generation, extractor_generation, canonicalizer_generation,
    publication_bundle_id, snapshot_manifest_id, profile_identity,
    model, model_version, generator, generator_version, representation_version,
    normalization, metric, run_id, dimensions, privacy_class, row_count
) VALUES ({', '.join(literal)}, {publication.publication.run_id}, {profile.dimensions}, 'public', {len(entries)});
WITH input(canonical_key, source_binding_id, snapshot_id, input_digest, embedding) AS (VALUES {values}),
{accepted_publication_sql(query)}
INSERT INTO repomap_enrichment.embeddings
    (rebuild_id, canonical_key, source_binding_id, snapshot_id, input_digest, dimensions, embedding)
SELECT {sql_literal(rebuild_id)}, input.canonical_key, input.source_binding_id,
    input.snapshot_id, input.input_digest, {profile.dimensions}, input.embedding
FROM input JOIN accepted ON true JOIN public.canonical_nodes node
    ON node.repository_id = accepted.repository_id AND node.canonical_key = input.canonical_key
    AND node.graph_key_version = 1 AND node.last_seen_run_id = accepted.id
WHERE EXISTS (SELECT 1 FROM public.canonical_node_evidence link
    JOIN public.canonical_evidence evidence ON evidence.id = link.canonical_evidence_id
    WHERE link.canonical_node_id = node.id AND evidence.run_id = accepted.id
      AND evidence.repository_id = accepted.repository_id
      AND evidence.metadata_json->>'binding_id' = input.source_binding_id
      AND evidence.metadata_json->>'snapshot_id' = input.snapshot_id);
DO $candidate_count$
BEGIN
    IF (SELECT count(*) FROM repomap_enrichment.embeddings WHERE rebuild_id = {sql_literal(rebuild_id)}) <> {len(entries)} THEN
        RAISE EXCEPTION 'embedding batch contains a node without accepted source evidence';
    END IF;
END;
$candidate_count$;
COMMIT;
"""
