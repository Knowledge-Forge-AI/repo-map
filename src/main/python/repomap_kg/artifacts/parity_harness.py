"""Public-safe offline incumbent/portable semantic parity evidence."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
import hashlib
from pathlib import Path
import shutil
from types import SimpleNamespace

from repomap_kg.artifacts._canonical import canonical_json
from repomap_kg.artifacts._parity_sealing import (
    _harness_owned_source_graph,
    _seal_graph,
    _source_signature,
    seal_graph,
)
from repomap_kg.artifacts.bundle import PUBLICATION_FAMILIES, PublicationBundle
from repomap_kg.artifacts.receipt import ExtractionReceipt
from repomap_kg.artifacts.references import ArtifactReference
from repomap_kg.artifacts.store import FileSystemArtifactStore
from repomap_kg.artifacts.validator import PublicationExpectation, PublisherBundleValidator
from repomap_kg.coordinator._portable_capability import (
    PortableExecutionCapability,
    create_portable_capability,
)
from repomap_kg.coordinator._portable_worker_launch import run_portable_worker
from repomap_kg.graph.multi_source_pipeline import (
    capture_multi_source_candidate,
)
from repomap_kg.observations.raw import RawObservation
from repomap_kg.ops.config_records import OpsGraphConfig
from repomap_kg.storage.staged_rows import build_staged_rows


@dataclass(frozen=True)
class ParityResult:
    equal: bool
    family_counts: dict[str, int]
    binding_count: int
    resolution_outcomes: dict[str, int]
    artifact_count: int
    artifact_bytes: int
    materialized_bytes: int
    bundle_bytes: int
    process_count: int
    row_stage_contract: str
    temporary_entries_after: int
    worker_source_copies_unavailable: bool = False
    caller_roots_unchanged: bool = False
    bundle_validated: bool = False
    bundle_id: str = ""
    receipt_id: str = ""
    bundle_bytes_digest: str = ""
    receipt_bytes_digest: str = ""
    validator_idempotent: bool = False
    conflicting_attempt_rejected: bool = False
    publication_state: str = ""


def _has_single_observed_worker_launch(
    managed_process_launches: tuple[tuple[str, ...], ...],
) -> bool:
    """Return whether supervision observed exactly one worker launch."""

    return len(managed_process_launches) == 1


def compare_incumbent_and_portable_parity(
    graph: OpsGraphConfig,
    *,
    store_root: Path,
    workspace_root: Path,
) -> ParityResult:
    """Compatibility alias for real managed-subprocess parity."""

    return compare_incumbent_and_subprocess_parity(
        graph,
        store_root=store_root,
        workspace_root=workspace_root,
    )


def compare_incumbent_and_subprocess_parity(
    graph: OpsGraphConfig,
    *,
    store_root: Path,
    workspace_root: Path,
) -> ParityResult:
    """Compare incumbent rows with one real managed portable-worker process."""

    caller_signature = _source_signature(graph)
    incumbent = capture_multi_source_candidate(graph)
    store = FileSystemArtifactStore(store_root)
    workspace_root.mkdir(mode=0o700, parents=True)
    source_copy_root = workspace_root.parent / f".{workspace_root.name}-sources"
    with _harness_owned_source_graph(graph, source_copy_root) as (
        sealed_graph,
        sealed_roots,
    ):
        manifest = _seal_graph(sealed_graph, incumbent, store)
        manifest_reference = store.put(
            manifest.canonical_bytes(),
            media_type="application/x-repomap-snapshot-manifest-v1+json",
            record_format="canonical-json-v1",
            privacy=manifest.effective_privacy,
        )
        shutil.rmtree(source_copy_root)
        source_copies_unavailable = all(not root.exists() for root in sealed_roots)
    capability_root = workspace_root.parent / f".{workspace_root.name}-capability"
    capability_root.mkdir(mode=0o700)
    try:
        capability = PortableExecutionCapability(
            1,
            "parity-job",
            1,
            graph.id,
            store.root,
            workspace_root.resolve(),
            manifest_reference,
            manifest.source_generation,
            manifest.config_generation,
            manifest.extractor_generation,
            manifest.canonicalizer_generation,
            16 * 1024 * 1024,
            16 * 1024 * 1024,
        )
        capability_path = create_portable_capability(capability_root, capability)
        process_result = run_portable_worker(
            capability_path,
            {"job_id": capability.job_id, "attempt": capability.attempt},
            _portable_limits(),
        )
        if process_result.protocol_error is not None or process_result.terminal.get("status") != "succeeded":
            raise ValueError("portable subprocess did not produce a valid success terminal")
        extension = process_result.terminal.get("portable_snapshot")
        if not isinstance(extension, dict):
            raise ValueError("portable subprocess result extension is absent")
        bundle_reference = ArtifactReference.from_mapping(extension["bundle"])
        receipt_reference = ArtifactReference.from_mapping(extension["receipt"])
        bundle_bytes = store.read(bundle_reference, max_bytes=capability.max_bundle_bytes)
        receipt_bytes = store.read(receipt_reference, max_bytes=capability.max_artifact_bytes)
        bundle = PublicationBundle.from_bytes(bundle_bytes)
        receipt = ExtractionReceipt.from_bytes(receipt_bytes)
        expected_rows = _stage_families(
            incumbent.observations,
            graph.repository_name,
            "stage-unassigned",
        )
        validator = PublisherBundleValidator()
        validation = validator.validate_bundle(
            store=store,
            bundle_reference=bundle_reference,
            receipt_reference=receipt_reference,
            expectation=PublicationExpectation.from_bundle(
                bundle,
                mutating_owner_count=1,
                worker_capability_identity=receipt.worker_capability_identity,
            ),
        )
        replay = validator.validate_bundle(
            store=store,
            bundle_reference=bundle_reference,
            receipt_reference=receipt_reference,
            expectation=PublicationExpectation.from_bundle(
                bundle,
                mutating_owner_count=1,
                worker_capability_identity=receipt.worker_capability_identity,
            ),
        )
        conflict_bundle = PublicationBundle.create(
            request_id=bundle.request_id,
            job_id=bundle.job_id,
            attempt=bundle.attempt,
            graph_id=bundle.graph_id,
            candidate_id=bundle.candidate_id,
            snapshot_manifest_id=bundle.snapshot_manifest_id,
            snapshot_vector=bundle.snapshot_vector,
            source_generation=bundle.source_generation,
            config_generation=bundle.config_generation,
            extractor_generation=bundle.extractor_generation,
            canonicalizer_generation=bundle.canonicalizer_generation,
            extractor_capability_identity=bundle.extractor_capability_identity,
            resolver_identity=bundle.resolver_identity,
            canonicalizer_identity=bundle.canonicalizer_identity,
            semantic_contract_identity=bundle.semantic_contract_identity,
            quality_rule_identity="qual1:conflicting-attempt-v1",
            privacy=bundle.privacy,
            families=bundle.families,
            row_stage_contract=bundle.row_stage_contract,
        )
        conflict_bundle_reference = store.put(
            conflict_bundle.canonical_bytes(),
            media_type="application/x-repomap-publication-bundle-v1+jsonl",
            record_format="canonical-jsonl-v1",
            privacy=bundle.privacy,
        )
        conflict_receipt = replace(
            receipt,
            quality_rule_identity=conflict_bundle.quality_rule_identity,
            bundle_reference=conflict_bundle_reference,
            bundle_id=conflict_bundle.bundle_id,
        ).reidentify()
        conflict_receipt_reference = store.put(
            conflict_receipt.canonical_bytes(),
            media_type="application/x-repomap-extraction-receipt-v1+json",
            record_format="canonical-json-v1",
            privacy=bundle.privacy,
        )
        conflicting_attempt_rejected = False
        try:
            validator.validate_bundle(
                store=store,
                bundle_reference=conflict_bundle_reference,
                receipt_reference=conflict_receipt_reference,
                expectation=PublicationExpectation.from_bundle(
                    conflict_bundle,
                    mutating_owner_count=1,
                    worker_capability_identity=conflict_receipt.worker_capability_identity,
                ),
            )
        except ValueError as error:
            conflicting_attempt_rejected = "conflicting attempt reuse" in str(error)
        outcomes: dict[str, int] = {}
        for resolution in incumbent.resolutions:
            outcome = resolution.outcome.value
            outcomes[outcome] = outcomes.get(outcome, 0) + 1
        equal = (
            bundle.candidate_id == incumbent.candidate.candidate_id
            and _has_single_observed_worker_launch(
                process_result.managed_process_launches
            )
            and bundle.privacy == manifest.effective_privacy
            and all(
                tuple(canonical_json(row) for row in bundle.families[family])
                == tuple(canonical_json(row) for row in expected_rows[family])
                for family in PUBLICATION_FAMILIES
            )
        )
        return ParityResult(
            equal=equal,
            family_counts=bundle.family_counts,
            binding_count=len(manifest.bindings),
            resolution_outcomes=outcomes,
            artifact_count=manifest.total_files,
            artifact_bytes=manifest.total_bytes,
            materialized_bytes=manifest.total_bytes,
            bundle_bytes=len(bundle_bytes),
            process_count=len(process_result.managed_process_launches),
            row_stage_contract=bundle.row_stage_contract,
            temporary_entries_after=sum(1 for _ in workspace_root.iterdir()),
            worker_source_copies_unavailable=source_copies_unavailable,
            caller_roots_unchanged=_source_signature(graph) == caller_signature,
            bundle_validated=(
                validation.byte_integrity_valid and validation.semantic_authority_valid
            ),
            bundle_id=bundle.bundle_id,
            receipt_id=receipt.receipt_id,
            bundle_bytes_digest="sha256:" + hashlib.sha256(bundle_bytes).hexdigest(),
            receipt_bytes_digest="sha256:" + hashlib.sha256(receipt_bytes).hexdigest(),
            validator_idempotent=replay.idempotent_replay,
            conflicting_attempt_rejected=conflicting_attempt_rejected,
            publication_state=str(process_result.terminal["publication_state"]),
        )
    finally:
        if capability_root.exists():
            shutil.rmtree(capability_root)


def _portable_limits() -> SimpleNamespace:
    return SimpleNamespace(
        process_deadline_seconds=10.0,
        heartbeat_seconds=2.0,
        hello_deadline_seconds=2.0,
        cancellation_after_seconds=1.0,
        cancel_deadline_seconds=1.0,
        process_termination_grace_seconds=1.0,
        max_diagnostic_bytes=4096,
        max_protocol_line_bytes=65536,
        max_array_items=64,
    )


def _stage_families(
    observations: Iterable[RawObservation],
    repository_name: str,
    stage_id: str,
) -> dict[str, tuple[dict[str, object], ...]]:
    prepared = build_staged_rows(
        observations,
        repository_name=repository_name,
        stage_id=stage_id,
    )
    try:
        return {
            family: tuple(
                sorted(
                    (dict(row) for row in prepared.family_rows[family]),
                    key=canonical_json,
                )
            )
            for family in PUBLICATION_FAMILIES
        }
    finally:
        prepared.close()


__all__ = [
    "ParityResult",
    "compare_incumbent_and_portable_parity",
    "compare_incumbent_and_subprocess_parity",
    "seal_graph",
]
