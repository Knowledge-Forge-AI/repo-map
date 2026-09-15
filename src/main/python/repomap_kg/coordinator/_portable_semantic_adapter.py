"""Database-independent adaptation of sealed artifacts to publication evidence."""

from __future__ import annotations

from dataclasses import dataclass
import threading
from typing import Callable

from repomap_kg.artifacts.bundle import PUBLICATION_FAMILIES, PublicationBundle
from repomap_kg.artifacts.manifest import PortableSnapshotManifest
from repomap_kg.artifacts.receipt import ExtractionReceipt
from repomap_kg.artifacts.references import ArtifactReference
from repomap_kg.artifacts.store import (
    ArtifactErrorCode,
    ArtifactIntegrityError,
    ArtifactStore,
    FileSystemArtifactStore,
)
from repomap_kg.coordinator._portable_capability import PortableExecutionCapability
from repomap_kg.coordinator._portable_materialization import MaterializedWorkspace
from repomap_kg.graph.multi_source import SourceKind
from repomap_kg.graph.multi_source_pipeline import (
    MultiSourceCaptureError,
    SealedSourceBinding,
    capture_sealed_multi_source_candidate,
)
from repomap_kg.storage.staged_rows import build_staged_rows
from repomap_kg.storage.staging_family_contracts import PrivacyClassification


WORKER_CAPABILITY_IDENTITY = "cap1:portable-python-worker-v1"
PRODUCER_IDENTITY = "producer1:portable-python-worker-v1"


class PortableExecutionError(ValueError):
    def __init__(self, category: str) -> None:
        self.category = category
        super().__init__(category)


@dataclass(frozen=True)
class PortableExecutionResult:
    manifest: PortableSnapshotManifest
    candidate_id: str
    receipt: ExtractionReceipt
    receipt_reference: ArtifactReference
    bundle: PublicationBundle
    bundle_reference: ArtifactReference
    materialized_bytes: int


@dataclass(frozen=True)
class FailureReceiptWrite:
    reference: ArtifactReference | None
    status: str
    diagnostic: str | None


def execute_portable_extraction(
    capability: PortableExecutionCapability,
    *,
    emit_progress: Callable[[str, int, int], None],
    cancel_event: threading.Event,
    checkpoint: Callable[[str], None] | None = None,
) -> PortableExecutionResult:
    """Consume one exact sealed manifest and run the existing semantic owners."""

    capability.validate()
    _checkpoint("before_manifest", cancel_event, checkpoint)
    try:
        store = FileSystemArtifactStore(capability.store_root)
    except ArtifactIntegrityError as error:
        raise PortableExecutionError(_artifact_error_category(error)) from error
    try:
        manifest_bytes = store.read(
            capability.manifest_reference,
            max_bytes=capability.max_artifact_bytes,
        )
    except ArtifactIntegrityError as error:
        raise PortableExecutionError(
            _artifact_error_category(error, bounds_category="manifest_bounds")
        ) from error
    try:
        manifest = PortableSnapshotManifest.from_bytes(manifest_bytes)
    except (TypeError, ValueError) as error:
        raise PortableExecutionError("contract_validation") from error
    if (
        manifest.graph_id != capability.graph_id
        or manifest.source_generation != capability.source_generation
        or manifest.config_generation != capability.config_generation
        or manifest.extractor_generation != capability.extractor_generation
        or manifest.canonicalizer_generation != capability.canonicalizer_generation
    ):
        raise PortableExecutionError("contract_validation")
    _cancelled(cancel_event)
    emit_progress("discovery", 0, manifest.total_files)
    try:
        with MaterializedWorkspace(
            store,
            manifest,
            capability.workspace_root,
            job_id=capability.job_id,
            attempt=capability.attempt,
            max_artifact_bytes=capability.max_artifact_bytes,
            cancel_check=lambda: _checkpoint(
                "during_materialization", cancel_event, checkpoint
            ),
        ) as materialized:
            _checkpoint("before_semantic", cancel_event, checkpoint)
            emit_progress("extraction", manifest.total_files, manifest.total_files)
            _cancelled(cancel_event)
            try:
                semantic = capture_sealed_multi_source_candidate(
                    manifest.graph_id,
                    _sealed_bindings(manifest, materialized.binding_roots),
                    expected_snapshot_vector=manifest.snapshot_vector,
                )
            except MultiSourceCaptureError as error:
                raise PortableExecutionError(error.category) from error
            _checkpoint("during_semantic", cancel_event, checkpoint)
            if (
                semantic.source_generation != manifest.source_generation
                or semantic.config_generation != manifest.config_generation
                or semantic.candidate.extractor_capability_identity
                != manifest.extractor_capability_identity
                or semantic.candidate.resolver_identity != manifest.resolver_identity
                or semantic.candidate.canonicalizer_identity != manifest.canonicalizer_identity
                or semantic.candidate.semantic_contract_identity
                != manifest.semantic_contract_identity
                or semantic.candidate.quality_rule_identity != manifest.quality_rule_identity
            ):
                raise PortableExecutionError("contract_validation")
            _cancelled(cancel_event)
            emit_progress("canonicalization", manifest.total_files, manifest.total_files)
            _cancelled(cancel_event)
            prepared = build_staged_rows(
                semantic.observations,
                repository_name=manifest.bindings[0].repository_scope or "",
                stage_id="stage-unassigned",
            )
            try:
                families = {
                    family: tuple(dict(row) for row in prepared.family_rows[family])
                    for family in PUBLICATION_FAMILIES
                }
            finally:
                prepared.close()
            _cancelled(cancel_event)
            emit_progress("storage_prepare", manifest.total_files, manifest.total_files)
            _cancelled(cancel_event)
            bundle = PublicationBundle.create(
                request_id=capability.job_id,
                job_id=capability.job_id,
                attempt=capability.attempt,
                graph_id=manifest.graph_id,
                candidate_id=semantic.candidate.candidate_id,
                snapshot_manifest_id=manifest.manifest_id,
                snapshot_vector=manifest.snapshot_vector,
                source_generation=manifest.source_generation,
                config_generation=manifest.config_generation,
                extractor_generation=manifest.extractor_generation,
                canonicalizer_generation=manifest.canonicalizer_generation,
                extractor_capability_identity=manifest.extractor_capability_identity,
                resolver_identity=manifest.resolver_identity,
                canonicalizer_identity=manifest.canonicalizer_identity,
                semantic_contract_identity=manifest.semantic_contract_identity,
                quality_rule_identity=manifest.quality_rule_identity,
                privacy=manifest.effective_privacy,
                families=families,
                row_stage_contract="stage-unassigned-v1",
            )
            bundle_bytes = bundle.canonical_bytes()
            if len(bundle_bytes) > capability.max_bundle_bytes:
                raise PortableExecutionError("contract_validation")
            _checkpoint("after_bundle", cancel_event, checkpoint)
            try:
                bundle_reference = store.put(
                    bundle_bytes,
                    media_type="application/x-repomap-publication-bundle-v1+jsonl",
                    record_format="canonical-jsonl-v1",
                    privacy=manifest.effective_privacy,
                )
            except ArtifactIntegrityError as error:
                raise PortableExecutionError(_artifact_error_category(error)) from error
            _cancelled(cancel_event)
            receipt = ExtractionReceipt.create(
                request_id=capability.job_id,
                job_id=capability.job_id,
                attempt=capability.attempt,
                graph_id=manifest.graph_id,
                worker_capability_identity=WORKER_CAPABILITY_IDENTITY,
                contract_version="1.0",
                source_generation=manifest.source_generation,
                config_generation=manifest.config_generation,
                extractor_generation=manifest.extractor_generation,
                canonicalizer_generation=manifest.canonicalizer_generation,
                snapshot_manifest_id=manifest.manifest_id,
                snapshot_vector=manifest.snapshot_vector,
                resolver_identity=manifest.resolver_identity,
                extractor_capability_identity=manifest.extractor_capability_identity,
                canonicalizer_identity=manifest.canonicalizer_identity,
                semantic_contract_identity=manifest.semantic_contract_identity,
                quality_rule_identity=manifest.quality_rule_identity,
                outcome="completed",
                cancellation="not-requested",
                bundle_reference=bundle_reference,
                bundle_id=bundle.bundle_id,
                family_counts=bundle.family_counts,
                diagnostic_category=None,
                diagnostic_summary=(),
                producer_identity=PRODUCER_IDENTITY,
                attestation_class="untrusted-self-assertion",
            )
            try:
                receipt_reference = store.put(
                    receipt.canonical_bytes(),
                    media_type="application/x-repomap-extraction-receipt-v1+json",
                    record_format="canonical-json-v1",
                    privacy=manifest.effective_privacy,
                )
            except ArtifactIntegrityError as error:
                raise PortableExecutionError(_artifact_error_category(error)) from error
            _checkpoint("before_terminal", cancel_event, checkpoint)
            emit_progress("complete", manifest.total_files, manifest.total_files)
            return PortableExecutionResult(
                manifest,
                semantic.candidate.candidate_id,
                receipt,
                receipt_reference,
                bundle,
                bundle_reference,
                materialized.materialized_bytes,
            )
    except ArtifactIntegrityError as error:
        raise PortableExecutionError(_artifact_error_category(error)) from error


def create_failure_receipt(
    capability: PortableExecutionCapability,
    category: str,
    *,
    store: ArtifactStore | None = None,
    manifest: PortableSnapshotManifest | None = None,
    cancellation_requested: bool = False,
) -> FailureReceiptWrite:
    """Create and persist an untrusted extraction receipt on error or cancellation."""
    try:
        if store is None:
            store = FileSystemArtifactStore(capability.store_root)
        outcome = "cancelled" if category == "cancelled" else "failed"
        cancellation = (
            "requested"
            if (category == "cancelled" or cancellation_requested)
            else "not-requested"
        )
        receipt = ExtractionReceipt.create(
            request_id=capability.job_id,
            job_id=capability.job_id,
            attempt=capability.attempt,
            graph_id=capability.graph_id,
            worker_capability_identity=WORKER_CAPABILITY_IDENTITY,
            contract_version="1.0",
            source_generation=capability.source_generation,
            config_generation=capability.config_generation,
            extractor_generation=capability.extractor_generation,
            canonicalizer_generation=capability.canonicalizer_generation,
            snapshot_manifest_id=(
                manifest.manifest_id
                if manifest is not None
                else capability.manifest_reference.content_digest
            ),
            snapshot_vector=manifest.snapshot_vector if manifest is not None else (),
            resolver_identity=(
                manifest.resolver_identity if manifest is not None else "res1:static-nix-v1"
            ),
            extractor_capability_identity=(
                manifest.extractor_capability_identity if manifest is not None else "cap1:standard-v1"
            ),
            canonicalizer_identity=(
                manifest.canonicalizer_identity if manifest is not None else "canon1:standard-v1"
            ),
            semantic_contract_identity=(
                manifest.semantic_contract_identity if manifest is not None else "sem1:standard-v1"
            ),
            quality_rule_identity=(
                manifest.quality_rule_identity if manifest is not None else "qual1:standard-v1"
            ),
            outcome=outcome,
            cancellation=cancellation,
            bundle_reference=None,
            bundle_id=None,
            family_counts={},
            diagnostic_category=category,
            diagnostic_summary=(),
            producer_identity=PRODUCER_IDENTITY,
            attestation_class="untrusted-self-assertion",
        )
        reference = store.put(
            receipt.canonical_bytes(),
            media_type="application/x-repomap-extraction-receipt-v1+json",
            record_format="canonical-json-v1",
            privacy=(
                manifest.effective_privacy
                if manifest is not None
                else PrivacyClassification.RAW_SOURCE
            ),
        )
        return FailureReceiptWrite(reference, "stored", None)
    except Exception as error:
        return FailureReceiptWrite(None, "unavailable", _receipt_write_diagnostic(error))


def _receipt_write_diagnostic(error: BaseException) -> str:
    chain: list[BaseException] = []
    current: BaseException | None = error
    while current is not None and current not in chain:
        chain.append(current)
        current = current.__cause__ or current.__context__
    code_map = {
        ArtifactErrorCode.STORE_UNAVAILABLE: "store_unavailable",
        ArtifactErrorCode.ARTIFACT_MISSING: "store_unavailable",
        ArtifactErrorCode.PERMISSION_DENIED: "permission_denied",
        ArtifactErrorCode.ARTIFACT_BOUNDS: "receipt_bounds",
        ArtifactErrorCode.WRITE_FAILED: "write_failed",
        ArtifactErrorCode.ARTIFACT_STALE: "write_failed",
        ArtifactErrorCode.ARTIFACT_CORRUPT: "write_failed",
    }
    for item in chain:
        if isinstance(item, ArtifactIntegrityError):
            return code_map[item.code]
        if isinstance(item, PermissionError):
            return "permission_denied"
    return "write_failed"


def _artifact_error_category(
    error: ArtifactIntegrityError,
    *,
    bounds_category: str = "artifact_bounds",
) -> str:
    code = error.code
    if code in {ArtifactErrorCode.ARTIFACT_MISSING, ArtifactErrorCode.ARTIFACT_STALE, ArtifactErrorCode.ARTIFACT_CORRUPT}:
        return str(code)
    if code == ArtifactErrorCode.ARTIFACT_BOUNDS:
        return bounds_category
    return "artifact_corrupt"


def _sealed_bindings(manifest, roots):
    result = []
    for binding in manifest.bindings:
        if binding.alias is None:
            raise PortableExecutionError("unsupported_contract")
        result.append(
            SealedSourceBinding(
                binding_id=binding.binding_id,
                source_definition_id=binding.source_definition_id,
                alias=binding.alias,
                revision=binding.revision,
                source_kind=(
                    SourceKind.FOLDER
                    if binding.source_kind == "local-directory"
                    else SourceKind.GIT_WORKING_TREE
                ),
                root=roots[binding.binding_id],
                repository_scope=binding.repository_scope or "",
                logical_root=binding.logical_root or "",
                privacy=binding.privacy_policy,
                evidence_retention=binding.evidence_retention_policy or "",
                extractor_profile=binding.extractor_profile or "",
                selection_policy_id=binding.selection_policy_id,
                resolution_policy=binding.resolution_policy or "",
                role=binding.role,
                input_name=binding.input_name,
            )
        )
    return tuple(result)


def _cancelled(event: threading.Event) -> None:
    if event.is_set():
        raise PortableExecutionError("cancelled")


def _checkpoint(
    name: str,
    event: threading.Event,
    callback: Callable[[str], None] | None,
) -> None:
    if callback is not None:
        callback(name)
    _cancelled(event)


__all__ = [
    "FailureReceiptWrite", "PortableExecutionError", "PortableExecutionResult",
    "create_failure_receipt", "execute_portable_extraction",
]
