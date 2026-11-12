"""Actual portable-worker reference bytes and publication expectations."""
from pathlib import Path

from common_lore_index.artifacts._bundle_stream_encode import StreamingBundleEncoder
from common_lore_index.artifacts.manifest import PortableSnapshotManifest
from common_lore_index.artifacts.validator import PublicationExpectation
from common_lore_index.coordinator._portable_capability import PortableExecutionCapability
from common_lore_index.graph.multi_source_pipeline import MultiSourceCandidateBundle
from common_lore_index.storage.staged_rows import build_staged_rows


def reference_bytes(
    captured: MultiSourceCandidateBundle, manifest: PortableSnapshotManifest,
    capability: PortableExecutionCapability, sort_root: Path,
) -> bytes:
    prepared = build_staged_rows(
        captured.observations, repository_name=manifest.bindings[0].repository_scope or "", stage_id="stage-unassigned",
    )
    try:
        encoder = StreamingBundleEncoder(
            request_id=capability.job_id, job_id=capability.job_id, attempt=capability.attempt,
            graph_id=manifest.graph_id, candidate_id=captured.candidate.candidate_id,
            snapshot_manifest_id=manifest.manifest_id, snapshot_vector=manifest.snapshot_vector,
            source_generation=manifest.source_generation, config_generation=manifest.config_generation,
            extractor_generation=manifest.extractor_generation,
            canonicalizer_generation=manifest.canonicalizer_generation,
            extractor_capability_identity=manifest.extractor_capability_identity,
            resolver_identity=manifest.resolver_identity, canonicalizer_identity=manifest.canonicalizer_identity,
            semantic_contract_identity=manifest.semantic_contract_identity,
            quality_rule_identity=manifest.quality_rule_identity, privacy=manifest.effective_privacy,
            family_rows=prepared.family_rows, row_stage_contract="stage-unassigned-v1",
            max_bundle_bytes=capability.max_bundle_bytes, spool_dir=sort_root,
        )
        return b"".join(encoder.stream_chunks())
    finally:
        prepared.close()


def publication_expectation(manifest: PortableSnapshotManifest, cap: PortableExecutionCapability, candidate_id: str) -> PublicationExpectation:
    return PublicationExpectation(
        request_id=cap.job_id, job_id=cap.job_id, attempt=cap.attempt, graph_id=manifest.graph_id,
        candidate_id=candidate_id, snapshot_manifest_id=manifest.manifest_id,
        snapshot_vector=manifest.snapshot_vector, source_generation=manifest.source_generation,
        config_generation=manifest.config_generation, extractor_generation=manifest.extractor_generation,
        canonicalizer_generation=manifest.canonicalizer_generation,
        extractor_capability_identity=manifest.extractor_capability_identity,
        resolver_identity=manifest.resolver_identity, canonicalizer_identity=manifest.canonicalizer_identity,
        semantic_contract_identity=manifest.semantic_contract_identity,
        quality_rule_identity=manifest.quality_rule_identity, mutating_owner_count=1,
        worker_capability_identity="cap1:portable-python-worker-v1",
        expected_privacy=manifest.effective_privacy.value,
    )
