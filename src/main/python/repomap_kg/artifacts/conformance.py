"""Non-production adapter from a sealed snapshot to bundle contracts."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from repomap_kg.artifacts.bundle import PublicationBundle
from repomap_kg.artifacts.manifest import PortableSnapshotManifest
from repomap_kg.artifacts.receipt import ExtractionReceipt
from repomap_kg.artifacts.references import ArtifactReference
from repomap_kg.artifacts.store import ArtifactIntegrityError, ArtifactStore
from repomap_kg.storage.staging_family_rows import StageFamily


SemanticEngine = Callable[
    [Mapping[tuple[str, str], bytes]],
    Mapping[StageFamily, Sequence[Mapping[str, object]]],
]


@dataclass(frozen=True)
class ConformanceRequest:
    request_id: str
    job_id: str
    attempt: int
    candidate_id: str
    snapshot_manifest_id: str
    worker_capability_identity: str
    contract_version: str
    producer_identity: str

    def __post_init__(self) -> None:
        if (
            not self.request_id
            or not self.job_id
            or not isinstance(self.attempt, int)
            or isinstance(self.attempt, bool)
            or self.attempt < 1
            or not self.candidate_id.startswith("cand1:")
            or not self.snapshot_manifest_id.startswith("snapmanifest1:")
            or not self.worker_capability_identity.startswith("cap1:")
            or self.contract_version != "1.0"
            or not self.producer_identity.startswith("producer1:")
        ):
            raise ValueError("conformance request is invalid")


@dataclass(frozen=True)
class ConformanceResult:
    receipt: ExtractionReceipt
    bundle: PublicationBundle | None
    bundle_reference: ArtifactReference | None


class ArtifactExtractionConformanceAdapter:
    """Read only accepted artifact bytes, then invoke one supplied semantic owner."""

    def __init__(self, store: ArtifactStore) -> None:
        self._store = store

    def run(
        self,
        *,
        manifest: PortableSnapshotManifest,
        request: ConformanceRequest,
        semantic_engine: SemanticEngine,
        cancellation_requested: bool = False,
    ) -> ConformanceResult:
        if manifest.manifest_id != request.snapshot_manifest_id:
            raise ValueError("snapshot manifest identity mismatch")
        if cancellation_requested:
            return ConformanceResult(
                self._receipt(
                    manifest, request, outcome="cancelled", cancellation="requested",
                    bundle=None, bundle_reference=None,
                    diagnostic_category="cancelled",
                ),
                None,
                None,
            )
        try:
            files = {
                (entry.binding_id, entry.source_relative_path): self._store.read(
                    entry.reference,
                    max_bytes=entry.reference.size_bytes,
                )
                for entry in manifest.entries
            }
        except ArtifactIntegrityError as error:
            category = str(error.code)
            return ConformanceResult(
                self._receipt(
                    manifest, request, outcome="failed", cancellation="not-observed",
                    bundle=None, bundle_reference=None,
                    diagnostic_category=category,
                ),
                None,
                None,
            )
        families = semantic_engine(files)
        bundle = PublicationBundle.create(
            request_id=request.request_id,
            job_id=request.job_id,
            attempt=request.attempt,
            graph_id=manifest.graph_id,
            candidate_id=request.candidate_id,
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
        bundle_reference = self._store.put(
            bundle.canonical_bytes(),
            media_type="application/x-repomap-publication-bundle-v1+jsonl",
            record_format="canonical-jsonl-v1",
            privacy=bundle.privacy,
        )
        receipt = self._receipt(
            manifest, request, outcome="completed", cancellation="not-requested",
            bundle=bundle, bundle_reference=bundle_reference,
            diagnostic_category=None,
        )
        return ConformanceResult(receipt, bundle, bundle_reference)

    @staticmethod
    def _receipt(
        manifest: PortableSnapshotManifest,
        request: ConformanceRequest,
        *,
        outcome: str,
        cancellation: str,
        bundle: PublicationBundle | None,
        bundle_reference: ArtifactReference | None,
        diagnostic_category: str | None,
    ) -> ExtractionReceipt:
        return ExtractionReceipt.create(
            request_id=request.request_id,
            job_id=request.job_id,
            attempt=request.attempt,
            graph_id=manifest.graph_id,
            worker_capability_identity=request.worker_capability_identity,
            contract_version=request.contract_version,
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
            outcome=outcome,
            cancellation=cancellation,
            bundle_reference=bundle_reference,
            bundle_id=None if bundle is None else bundle.bundle_id,
            family_counts={} if bundle is None else bundle.family_counts,
            diagnostic_category=diagnostic_category,
            diagnostic_summary=(),
            producer_identity=request.producer_identity,
            attestation_class="untrusted-self-assertion",
        )

