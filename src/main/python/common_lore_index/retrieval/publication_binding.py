"""Publication binding correspondence checks for the captured-input projection reference (S1)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from common_lore_index.artifacts._store_common import (
    ArtifactIntegrityError,
    ArtifactStore,
)
from common_lore_index.artifacts.bundle import PublicationBundle
from common_lore_index.artifacts.manifest import PortableSnapshotManifest
from common_lore_index.artifacts.receipt import ExtractionReceipt
from common_lore_index.artifacts.references import ArtifactReference
from common_lore_index.artifacts.validator import (
    PublicationExpectation,
    PublisherBundleValidator,
)
from common_lore_index.storage.publication import RunPublicationReceipt

PROJECTION_REFERENCE_VERSION = "cloe-captured-text-reference-v1"
DEFAULT_MAX_BUNDLE_BYTES = 16 * 1024 * 1024


class CorrespondenceErrorCode(str, Enum):
    """Closed refusal codes for accepted-publication to captured-input correspondence."""

    UNTRUSTED_CALLER_REFERENCE = "untrusted_caller_reference"
    MISSING_PORTABLE_BINDING = "missing_portable_binding"
    GRAPH_ID_MISMATCH = "graph_id_mismatch"
    ATTEMPT_MISMATCH = "attempt_mismatch"
    BUNDLE_ID_MISMATCH = "bundle_id_mismatch"
    CANDIDATE_ID_MISMATCH = "candidate_id_mismatch"
    MANIFEST_ID_MISMATCH = "manifest_id_mismatch"
    SNAPSHOT_VECTOR_MISMATCH = "snapshot_vector_mismatch"
    GENERATION_MISMATCH = "generation_mismatch"
    RECEIPT_ID_MISMATCH = "receipt_id_mismatch"
    CANONICAL_IDENTITY_MISMATCH = "canonical_identity_mismatch"
    BUNDLE_VALIDATION_FAILED = "bundle_validation_failed"
    STORE_VERIFICATION_FAILED = "store_verification_failed"
    PUBLICATION_ADVANCED = "publication_advanced"


class CorrespondenceRefusal(ValueError):
    """Structured refusal raised when captured inputs fail publication correspondence."""

    def __init__(self, code: CorrespondenceErrorCode, detail: str) -> None:
        super().__init__(f"{code.value}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class AcceptedPublicationReference:
    """Trusted caller-supplied accepted store marker (`trusted_caller` is a caller-obligation marker)."""

    graph_id: str
    repository_id: str
    backend: str
    run_id: str | int
    publication_bundle_id: str
    job_id: str
    attempt: int
    accepted_generation: int | None = None
    snapshot_manifest_id: str | None = None
    extraction_receipt_id: str | None = None
    trusted_caller: bool = False

    def validate(self) -> AcceptedPublicationReference:
        if self.trusted_caller is not True:
            raise CorrespondenceRefusal(
                CorrespondenceErrorCode.UNTRUSTED_CALLER_REFERENCE,
                "AcceptedPublicationReference requires trusted_caller=True from accepted-store readback",
            )
        for name, val in (
            ("graph_id", self.graph_id),
            ("repository_id", self.repository_id),
            ("publication_bundle_id", self.publication_bundle_id),
            ("job_id", self.job_id),
        ):
            if not isinstance(val, str) or not val.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if self.backend not in {"sqlite", "postgresql"}:
            raise ValueError(f"unsupported accepted publication backend: {self.backend!r}")
        if isinstance(self.run_id, bool) or not isinstance(self.run_id, (str, int)) or str(self.run_id).strip() == "":
            raise ValueError("run_id must be a non-empty string or integer")
        if isinstance(self.attempt, bool) or not isinstance(self.attempt, int) or self.attempt < 1:
            raise ValueError("attempt must be a positive integer")
        if self.accepted_generation is not None and (
            isinstance(self.accepted_generation, bool)
            or not isinstance(self.accepted_generation, int)
            or self.accepted_generation < 1
        ):
            raise ValueError("accepted_generation must be a positive integer when present")
        for opt_name, opt_val in (("snapshot_manifest_id", self.snapshot_manifest_id), ("extraction_receipt_id", self.extraction_receipt_id)):
            if opt_val is not None and (not isinstance(opt_val, str) or not opt_val.strip()):
                raise ValueError(f"{opt_name} must be a non-empty string when present")
        return self

    def matches_current(self, current: AcceptedPublicationReference | None) -> bool:
        if current is None:
            return False
        return (
            self.graph_id == current.graph_id
            and self.repository_id == current.repository_id
            and self.backend == current.backend
            and str(self.run_id) == str(current.run_id)
            and self.publication_bundle_id == current.publication_bundle_id
            and self.job_id == current.job_id
            and self.attempt == current.attempt
            and self.accepted_generation == current.accepted_generation
        )

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "graph_id": self.graph_id, "repository_id": self.repository_id, "backend": self.backend,
            "run_id": self.run_id, "publication_bundle_id": self.publication_bundle_id,
            "job_id": self.job_id, "attempt": self.attempt, "accepted_generation": self.accepted_generation,
            "snapshot_manifest_id": self.snapshot_manifest_id, "extraction_receipt_id": self.extraction_receipt_id,
            "trusted_caller": self.trusted_caller,
        }

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> AcceptedPublicationReference:
        allowed = {"graph_id", "repository_id", "backend", "run_id", "publication_bundle_id", "job_id", "attempt", "accepted_generation", "snapshot_manifest_id", "extraction_receipt_id", "trusted_caller"}
        extra = set(raw.keys()) - allowed
        if extra:
            raise ValueError(f"AcceptedPublicationReference has unexpected fields: {sorted(extra)}")
        trusted_raw = raw.get("trusted_caller", False)
        if not isinstance(trusted_raw, bool):
            raise ValueError("trusted_caller must be a bool")
        attempt_raw = raw.get("attempt")
        if not isinstance(attempt_raw, int) or isinstance(attempt_raw, bool):
            raise ValueError("attempt must be an integer")
        accepted_gen = raw.get("accepted_generation")
        if accepted_gen is not None and (not isinstance(accepted_gen, int) or isinstance(accepted_gen, bool)):
            raise ValueError("accepted_generation must be an integer or None")
        for req_str in ("graph_id", "repository_id", "backend", "publication_bundle_id", "job_id"):
            if not isinstance(raw.get(req_str), str):
                raise ValueError(f"{req_str} must be a string")
        for opt_str in ("snapshot_manifest_id", "extraction_receipt_id"):
            if raw.get(opt_str) is not None and not isinstance(raw.get(opt_str), str):
                raise ValueError(f"{opt_str} must be a string or None")
        return cls(
            graph_id=raw["graph_id"], repository_id=raw["repository_id"], backend=raw["backend"],
            run_id=raw["run_id"], publication_bundle_id=raw["publication_bundle_id"],
            job_id=raw["job_id"], attempt=attempt_raw,
            accepted_generation=accepted_gen, snapshot_manifest_id=raw.get("snapshot_manifest_id"),
            extraction_receipt_id=raw.get("extraction_receipt_id"), trusted_caller=trusted_raw,
        ).validate()


@dataclass(frozen=True)
class ProjectionInputs:
    """Complete captured inputs and accepted-store reference for projection."""

    accepted_reference: AcceptedPublicationReference
    receipt: RunPublicationReceipt
    manifest: PortableSnapshotManifest
    bundle: PublicationBundle
    store: ArtifactStore
    manifest_reference: ArtifactReference | None = None
    bundle_reference: ArtifactReference | None = None
    receipt_reference: ArtifactReference | None = None
    extraction_receipt: ExtractionReceipt | None = None
    spool_dir: Path | None = None
    max_bundle_bytes: int = DEFAULT_MAX_BUNDLE_BYTES


def _verify_canonical_parsers(manifest: PortableSnapshotManifest, bundle: PublicationBundle) -> None:
    try:
        reparsed_manifest = PortableSnapshotManifest.from_bytes(manifest.canonical_bytes())
        reparsed_bundle = PublicationBundle.from_bytes(bundle.canonical_bytes())
    except (TypeError, ValueError) as error:
        raise CorrespondenceRefusal(
            CorrespondenceErrorCode.CANONICAL_IDENTITY_MISMATCH,
            f"canonical parser verification failed ({type(error).__name__})",
        ) from error
    if reparsed_manifest.manifest_id != manifest.manifest_id or reparsed_bundle.bundle_id != bundle.bundle_id:
        raise CorrespondenceRefusal(
            CorrespondenceErrorCode.CANONICAL_IDENTITY_MISMATCH,
            "re-parsed manifest_id or bundle_id does not match",
        )


def _verify_store_references(inputs: ProjectionInputs) -> None:
    if isinstance(inputs.max_bundle_bytes, bool) or not isinstance(inputs.max_bundle_bytes, int) or inputs.max_bundle_bytes <= 0:
        raise CorrespondenceRefusal(
            CorrespondenceErrorCode.BUNDLE_VALIDATION_FAILED,
            "max_bundle_bytes must be a positive integer",
        )
    if len(inputs.bundle.canonical_bytes()) > inputs.max_bundle_bytes:
        raise CorrespondenceRefusal(
            CorrespondenceErrorCode.BUNDLE_VALIDATION_FAILED,
            "publication bundle canonical_bytes exceeds max_bundle_bytes",
        )
    for label, ref in (("manifest", inputs.manifest_reference), ("bundle", inputs.bundle_reference), ("receipt", inputs.receipt_reference)):
        if ref is None:
            raise CorrespondenceRefusal(
                CorrespondenceErrorCode.STORE_VERIFICATION_FAILED,
                f"{label} reference is required for publisher validation",
            )
        try:
            ok = inputs.store.verify(ref.with_store_version(None), max_bytes=inputs.max_bundle_bytes)
        except (ArtifactIntegrityError, OSError, ValueError) as error:
            raise CorrespondenceRefusal(
                CorrespondenceErrorCode.STORE_VERIFICATION_FAILED,
                f"{label} reference failed store verification ({type(error).__name__})",
            ) from error
        if not ok:
            raise CorrespondenceRefusal(
                CorrespondenceErrorCode.STORE_VERIFICATION_FAILED,
                f"{label} reference returned False from store.verify",
            )
    manifest_ref = inputs.manifest_reference
    if manifest_ref is None:
        raise CorrespondenceRefusal(CorrespondenceErrorCode.STORE_VERIFICATION_FAILED, "manifest reference is required")
    try:
        # Compare the actual retained manifest, preserving its execution references.
        stored_manifest = PortableSnapshotManifest.from_bytes(
            inputs.store.read(manifest_ref, max_bytes=inputs.max_bundle_bytes)
        )
        if stored_manifest.canonical_bytes() != inputs.manifest.canonical_bytes():
            raise ValueError("stored manifest differs from projection inputs")
    except (ArtifactIntegrityError, OSError, TypeError, ValueError) as error:
        raise CorrespondenceRefusal(
            CorrespondenceErrorCode.STORE_VERIFICATION_FAILED,
            f"stored manifest correspondence failed ({type(error).__name__})",
        ) from error


def _verify_bundle_validator(inputs: ProjectionInputs) -> None:
    if len(inputs.bundle.canonical_bytes()) > inputs.max_bundle_bytes:
        raise CorrespondenceRefusal(
            CorrespondenceErrorCode.BUNDLE_VALIDATION_FAILED,
            "publication bundle canonical_bytes exceeds max_bundle_bytes",
        )
    if (
        inputs.bundle_reference is None
        or inputs.receipt_reference is None
        or inputs.spool_dir is None
    ):
        raise CorrespondenceRefusal(
            CorrespondenceErrorCode.BUNDLE_VALIDATION_FAILED,
            "bundle/receipt references and spool_dir are required for publisher validation",
        )
    portable = inputs.receipt.portable
    if portable is None:
        raise CorrespondenceRefusal(CorrespondenceErrorCode.MISSING_PORTABLE_BINDING, "portable receipt is required")
    expectation = PublicationExpectation(
        request_id=inputs.bundle.request_id, job_id=inputs.bundle.job_id, attempt=inputs.bundle.attempt,
        graph_id=inputs.manifest.graph_id, candidate_id=inputs.bundle.candidate_id,
        snapshot_manifest_id=inputs.manifest.manifest_id, snapshot_vector=inputs.manifest.snapshot_vector,
        source_generation=inputs.manifest.source_generation, config_generation=inputs.manifest.config_generation,
        extractor_generation=inputs.manifest.extractor_generation, canonicalizer_generation=inputs.manifest.canonicalizer_generation,
        extractor_capability_identity=inputs.manifest.extractor_capability_identity, resolver_identity=inputs.manifest.resolver_identity,
        canonicalizer_identity=inputs.manifest.canonicalizer_identity, semantic_contract_identity=inputs.manifest.semantic_contract_identity,
        quality_rule_identity=inputs.manifest.quality_rule_identity, mutating_owner_count=1,
        worker_capability_identity=portable.worker_capability_identity, expected_privacy=inputs.manifest.effective_privacy.value,
    )
    try:
        validated = PublisherBundleValidator().validate_bundle_stream(
            store=inputs.store, bundle_reference=inputs.bundle_reference.with_store_version(None),
            receipt_reference=inputs.receipt_reference.with_store_version(None),
            expectation=expectation,
            stage_id=portable.stage_id,
            spool_dir=inputs.spool_dir,
            max_bundle_bytes=inputs.max_bundle_bytes,
        )
        try:
            if (validated.bundle_id != inputs.bundle.bundle_id
                    or validated.receipt_id != portable.extraction_receipt_id
                    or validated.snapshot_manifest_id != inputs.manifest.manifest_id):
                raise ValueError("validated stored bundle/receipt differs from projection inputs")
        finally:
            validated.close()
    except (ArtifactIntegrityError, OSError, TypeError, ValueError) as error:
        raise CorrespondenceRefusal(
            CorrespondenceErrorCode.BUNDLE_VALIDATION_FAILED,
            f"PublisherBundleValidator failed ({type(error).__name__})",
        ) from error


def check_correspondence(inputs: ProjectionInputs) -> AcceptedPublicationReference:
    """Verify full correspondence across accepted reference, receipt, manifest, bundle, and store."""
    accepted = inputs.accepted_reference.validate()
    receipt = inputs.receipt.validate()
    manifest = inputs.manifest
    bundle = inputs.bundle
    portable = receipt.portable
    if portable is None:
        raise CorrespondenceRefusal(
            CorrespondenceErrorCode.MISSING_PORTABLE_BINDING,
            "RunPublicationReceipt.portable is required for captured-input projection",
        )
    if not (accepted.graph_id == manifest.graph_id == bundle.graph_id):
        raise CorrespondenceRefusal(CorrespondenceErrorCode.GRAPH_ID_MISMATCH, "graph_id mismatch")
    receipt_job = (str(receipt.attempt.job_id), int(receipt.attempt.attempt))
    if not ((accepted.job_id, accepted.attempt) == receipt_job == (bundle.job_id, bundle.attempt)):
        raise CorrespondenceRefusal(CorrespondenceErrorCode.ATTEMPT_MISMATCH, "job_id/attempt mismatch")
    if not (accepted.publication_bundle_id == portable.publication_bundle_id == bundle.bundle_id):
        raise CorrespondenceRefusal(CorrespondenceErrorCode.BUNDLE_ID_MISMATCH, "publication_bundle_id mismatch")
    if portable.candidate_id != bundle.candidate_id:
        raise CorrespondenceRefusal(CorrespondenceErrorCode.CANDIDATE_ID_MISMATCH, "candidate_id mismatch")
    if not (portable.snapshot_manifest_id == manifest.manifest_id == bundle.snapshot_manifest_id):
        raise CorrespondenceRefusal(CorrespondenceErrorCode.MANIFEST_ID_MISMATCH, "snapshot_manifest_id mismatch")
    if accepted.snapshot_manifest_id is not None and accepted.snapshot_manifest_id != manifest.manifest_id:
        raise CorrespondenceRefusal(CorrespondenceErrorCode.MANIFEST_ID_MISMATCH, "accepted snapshot_manifest_id mismatch")
    if not (portable.snapshot_vector == manifest.snapshot_vector == bundle.snapshot_vector):
        raise CorrespondenceRefusal(CorrespondenceErrorCode.SNAPSHOT_VECTOR_MISMATCH, "snapshot_vector mismatch")

    receipt_gens = (
        str(receipt.generations.source_generation), str(receipt.generations.config_generation),
        str(receipt.generations.extractor_generation), str(receipt.generations.canonicalizer_generation),
    )
    manifest_gens = (manifest.source_generation, manifest.config_generation, manifest.extractor_generation, manifest.canonicalizer_generation)
    bundle_gens = (bundle.source_generation, bundle.config_generation, bundle.extractor_generation, bundle.canonicalizer_generation)
    if not (receipt_gens == manifest_gens == bundle_gens):
        raise CorrespondenceRefusal(CorrespondenceErrorCode.GENERATION_MISMATCH, "generation tuple mismatch")

    portable_ids = (portable.resolver_identity, portable.canonicalizer_identity, portable.semantic_contract_identity, portable.quality_rule_identity)
    manifest_ids = (manifest.resolver_identity, manifest.canonicalizer_identity, manifest.semantic_contract_identity, manifest.quality_rule_identity)
    bundle_ids = (bundle.resolver_identity, bundle.canonicalizer_identity, bundle.semantic_contract_identity, bundle.quality_rule_identity)
    if not (portable_ids == manifest_ids == bundle_ids and manifest.extractor_capability_identity == bundle.extractor_capability_identity):
        raise CorrespondenceRefusal(CorrespondenceErrorCode.CANONICAL_IDENTITY_MISMATCH, "canonical identity mismatch")

    if accepted.extraction_receipt_id is not None and accepted.extraction_receipt_id != portable.extraction_receipt_id:
        raise CorrespondenceRefusal(CorrespondenceErrorCode.RECEIPT_ID_MISMATCH, "accepted extraction_receipt_id mismatch")
    if inputs.extraction_receipt is not None:
        ext = inputs.extraction_receipt
        if ext.receipt_id != portable.extraction_receipt_id or ext.bundle_id != bundle.bundle_id or ext.snapshot_manifest_id != manifest.manifest_id:
            raise CorrespondenceRefusal(CorrespondenceErrorCode.RECEIPT_ID_MISMATCH, "ExtractionReceipt mismatch")

    _verify_canonical_parsers(manifest, bundle)
    _verify_store_references(inputs)
    _verify_bundle_validator(inputs)
    return accepted
