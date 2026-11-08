"""Comparison of retained evidence with one authoritative complete run."""

from __future__ import annotations

import hashlib

from common_lore_index.ops._retained_attempt_artifacts import RetainedArtifactProof
from common_lore_index.storage.publication_readback import RunPublicationRecord


def portable_stage_id(operation_id: str, attempt: int) -> str:
    digest = hashlib.sha256(f"{operation_id}:{attempt}".encode("utf-8")).hexdigest()
    return f"stage-{digest[:48]}"


def publication_proof_matches(
    proof: RetainedArtifactProof,
    publication: RunPublicationRecord,
    *,
    stage_id: str,
) -> bool:
    receipt = publication.receipt
    portable = receipt.portable
    if portable is None or receipt.attempt.job_id != proof.receipt.job_id or receipt.attempt.attempt != proof.receipt.attempt:
        return False
    expected_families = {
        family: {"count": count, "byte_length": length, "digest": digest}
        for family, count, length, digest in proof.family_receipts
    }
    return (
        receipt.generations.source_generation == proof.manifest.source_generation
        and receipt.generations.config_generation == proof.manifest.config_generation
        and receipt.generations.extractor_generation == proof.manifest.extractor_generation
        and receipt.generations.canonicalizer_generation == proof.manifest.canonicalizer_generation
        and portable.snapshot_manifest_id == proof.manifest.manifest_id
        and portable.snapshot_vector == proof.manifest.snapshot_vector
        and portable.extraction_receipt_id == proof.receipt.receipt_id
        and portable.publication_bundle_id == proof.bundle_id
        and portable.candidate_id == proof.candidate_id
        and portable.resolver_identity == proof.manifest.resolver_identity
        and portable.canonicalizer_identity == proof.manifest.canonicalizer_identity
        and portable.semantic_contract_identity == proof.manifest.semantic_contract_identity
        and portable.quality_rule_identity == proof.manifest.quality_rule_identity
        and portable.protocol_version == proof.receipt.contract_version
        and portable.worker_capability_identity == proof.receipt.worker_capability_identity
        and portable.stage_id == stage_id
        and dict(portable.family_receipts) == expected_families
    )


__all__ = ("portable_stage_id", "publication_proof_matches")
