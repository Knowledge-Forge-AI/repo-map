"""Transactional population of cloe_lexical generation, document, chunk, and omission rows."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from common_lore_index.retrieval.lexical_capture import LexicalCapturePlan
from common_lore_index.storage.lexical_build_lease import (
    LEXICAL_BUILD_LEASE_SECONDS,
    acquire_repository_lifecycle_lock,
    refresh_lexical_build_lease,
)
from common_lore_index.storage.lexical_driver import (
    LexicalStorageError,
    sanitize_driver_exception,
)

INSERT_GENERATION_SQL = f"""
INSERT INTO cloe_lexical.generations (
    repository_id,
    lexical_generation_id,
    run_id,
    publication_bundle_id,
    snapshot_manifest_id,
    extraction_receipt_id,
    graph_candidate_id,
    snapshot_vector_json,
    publication_receipt_json,
    representation_version,
    text_config_regconfig,
    ranking_function,
    normalization_flags,
    alias_split_rule_version,
    policy_digest,
    resolved_graph_privacy,
    binding_policy_digests_json,
    admitted_binding_ids_json,
    excluded_binding_ids_json,
    projected_document_count,
    projected_chunk_count,
    omitted_record_count,
    aggregate_input_bytes,
    aggregate_projected_bytes,
    state,
    builder_owner_id,
    lease_expires_at,
    published_at,
    revoked_at,
    revocation_reason
) SELECT
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
    %s, %s, %s, %s, %s, %s, %s, %s, %s, 'building', %s, clock_timestamp() + interval '{LEXICAL_BUILD_LEASE_SECONDS} seconds', NULL, NULL, NULL
WHERE NOT EXISTS (
    SELECT 1
    FROM cloe_lexical.generations existing_generation
    WHERE existing_generation.repository_id = %s
      AND existing_generation.state = 'building'
      AND (
          existing_generation.lease_expires_at IS NULL
          OR existing_generation.lease_expires_at > clock_timestamp()
      )
)
ON CONFLICT (repository_id, lexical_generation_id) DO NOTHING
"""

INSERT_DOCUMENT_SQL = """
INSERT INTO cloe_lexical.documents (
    repository_id,
    lexical_generation_id,
    document_ordinal,
    binding_id,
    binding_revision,
    snapshot_id,
    source_relative_path,
    file_content_sha256,
    normalized_byte_length,
    line_count,
    chunk_count,
    normalized_text,
    artifact_privacy,
    evidence_retention
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

INSERT_CHUNK_SQL = """
INSERT INTO cloe_lexical.chunks (
    repository_id,
    lexical_generation_id,
    chunk_id,
    binding_id,
    binding_revision,
    snapshot_id,
    source_relative_path,
    chunk_ordinal,
    start_line,
    end_line,
    byte_length,
    chunk_sha256,
    chunk_text,
    alias_tokens_text,
    ranked_vector,
    phrase_vector,
    artifact_privacy
) VALUES (
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
    setweight(to_tsvector('pg_catalog.simple'::regconfig, %s), 'A')
        || setweight(to_tsvector('pg_catalog.simple'::regconfig, %s), 'D'),
    to_tsvector('pg_catalog.simple'::regconfig, %s),
    %s
)
"""

INSERT_OMISSION_SQL = """
INSERT INTO cloe_lexical.omissions (
    repository_id,
    lexical_generation_id,
    omission_ordinal,
    binding_id,
    source_relative_path,
    reason_code,
    detail
) VALUES (%s, %s, %s, %s, %s, %s, %s)
"""


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _generation_params(
    plan: LexicalCapturePlan,
    builder_owner_id: str,
) -> tuple[Any, ...]:
    snapshot_vector_payload = [
        [binding_id, int(binding_revision), snapshot_id]
        for binding_id, binding_revision, snapshot_id in plan.snapshot_vector
    ]
    return (
        plan.repository_id,
        plan.lexical_generation_id,
        plan.run_id,
        plan.publication_bundle_id,
        plan.snapshot_manifest_id,
        plan.extraction_receipt_id,
        plan.graph_candidate_id,
        _canonical_json(snapshot_vector_payload),
        plan.publication_receipt_json or "{}",
        plan.representation_version,
        plan.text_config_regconfig,
        plan.ranking_function,
        plan.normalization_flags,
        plan.alias_split_rule_version,
        plan.policy_digest,
        plan.resolved_graph_privacy,
        _canonical_json(dict(plan.binding_policy_digests)),
        _canonical_json(list(plan.admitted_binding_ids)),
        _canonical_json(list(plan.excluded_binding_ids)),
        plan.projected_document_count,
        plan.projected_chunk_count,
        plan.omitted_record_count,
        plan.aggregate_input_bytes,
        plan.aggregate_projected_bytes,
        builder_owner_id,
    )


def claim_lexical_generation(
    connection: Any,
    plan: LexicalCapturePlan,
    *,
    builder_owner_id: str = "local-builder",
) -> None:
    """Claim one durable building row without replacing another generation."""
    try:
        with connection.cursor() as cursor:
            acquire_repository_lifecycle_lock(connection, plan.repository_id)
            cursor.execute(
                INSERT_GENERATION_SQL,
                _generation_params(plan, builder_owner_id) + (plan.repository_id,),
            )
            if cursor.rowcount != 1:
                raise LexicalStorageError(
                    "cloe_lexical_competing_builder_in_progress",
                    "lexical generation identity is already owned or published",
                )
        connection.commit()
    except Exception as error:
        raise sanitize_driver_exception(error, operation="lexical_claim") from None


def _write_document_batch(
    cursor: Any,
    plan: LexicalCapturePlan,
    documents: Sequence[Any],
) -> None:
    for doc in documents:
        cursor.execute(
            INSERT_DOCUMENT_SQL,
            (
                plan.repository_id,
                plan.lexical_generation_id,
                doc.document_ordinal,
                doc.binding_id,
                doc.binding_revision,
                doc.snapshot_id,
                doc.source_relative_path,
                doc.file_content_sha256,
                doc.normalized_byte_length,
                doc.line_count,
                doc.chunk_count,
                doc.normalized_text,
                doc.artifact_privacy,
                doc.evidence_retention,
            ),
        )
        for chunk in doc.chunks:
            cursor.execute(
                INSERT_CHUNK_SQL,
                (
                    plan.repository_id,
                    plan.lexical_generation_id,
                    chunk.chunk_id,
                    chunk.binding_id,
                    chunk.binding_revision,
                    chunk.snapshot_id,
                    chunk.source_relative_path,
                    chunk.chunk_ordinal,
                    chunk.start_line,
                    chunk.end_line,
                    chunk.byte_length,
                    chunk.chunk_sha256,
                    chunk.chunk_text,
                    chunk.alias_tokens_text,
                    chunk.alias_tokens_text,
                    chunk.chunk_text,
                    chunk.chunk_text,
                    chunk.artifact_privacy,
                ),
            )


def _write_omission_batch(
    cursor: Any,
    plan: LexicalCapturePlan,
    omissions: Sequence[Any],
    start_ordinal: int,
) -> None:
    for offset, omission in enumerate(omissions):
        cursor.execute(
            INSERT_OMISSION_SQL,
            (
                plan.repository_id,
                plan.lexical_generation_id,
                start_ordinal + offset,
                omission.binding_id,
                omission.source_relative_path,
                omission.reason_code,
                omission.detail,
            ),
        )


def populate_lexical_generation_rows(
    connection: Any,
    plan: LexicalCapturePlan,
    *,
    builder_owner_id: str = "local-builder",
    batch_size: int = 256,
    claim_generation: bool = True,
) -> None:
    """Insert captured rows in bounded transactions under one owned lease."""
    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or not 1 <= batch_size <= 256:
        raise ValueError("batch_size must be a positive integer")
    try:
        if claim_generation:
            claim_lexical_generation(
                connection,
                plan,
                builder_owner_id=builder_owner_id,
            )
        documents = plan.documents
        omissions = plan.omissions
        document_batches = (
            tuple(documents[idx : idx + batch_size])
            for idx in range(0, len(documents), batch_size)
        )
        for document_batch in document_batches:
            refresh_lexical_build_lease(
                connection,
                repository_id=plan.repository_id,
                lexical_generation_id=plan.lexical_generation_id,
                builder_owner_id=builder_owner_id,
            )
            with connection.cursor() as cursor:
                _write_document_batch(cursor, plan, document_batch)
            refresh_lexical_build_lease(
                connection,
                repository_id=plan.repository_id,
                lexical_generation_id=plan.lexical_generation_id,
                builder_owner_id=builder_owner_id,
            )
            connection.commit()
        for start in range(0, len(omissions), batch_size):
            refresh_lexical_build_lease(
                connection,
                repository_id=plan.repository_id,
                lexical_generation_id=plan.lexical_generation_id,
                builder_owner_id=builder_owner_id,
            )
            with connection.cursor() as cursor:
                _write_omission_batch(
                    cursor,
                    plan,
                    omissions[start : start + batch_size],
                    start,
                )
            refresh_lexical_build_lease(
                connection,
                repository_id=plan.repository_id,
                lexical_generation_id=plan.lexical_generation_id,
                builder_owner_id=builder_owner_id,
            )
            connection.commit()
    except Exception as error:
        raise sanitize_driver_exception(error, operation="lexical_populate") from None


__all__ = [
    "INSERT_CHUNK_SQL",
    "INSERT_DOCUMENT_SQL",
    "INSERT_GENERATION_SQL",
    "INSERT_OMISSION_SQL",
    "claim_lexical_generation",
    "populate_lexical_generation_rows",
]
