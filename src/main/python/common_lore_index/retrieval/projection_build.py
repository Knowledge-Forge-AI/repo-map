"""Builder for the bounded in-memory captured-input text projection reference (S1)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from common_lore_index.artifacts._store_common import (
    ArtifactErrorCode,
    ArtifactIntegrityError,
)
from common_lore_index.artifacts.manifest import PortableSnapshotManifest
from common_lore_index.retrieval.projection_chunks import (
    ProjectedChunk,
    build_file_chunks,
    frame_digest,
)
from common_lore_index.retrieval.projection_evidence import (
    ProjectedEvidenceLink,
    index_bundle_evidence,
)
from common_lore_index.retrieval.projection_policy import (
    BodyProjectionPolicy,
    ExclusionReason,
    ResolvedBindingPolicy,
    evaluate_artifact_pre_open,
    evaluate_binding_exclusion,
)
from common_lore_index.retrieval.projection_text import normalize_and_bound_text
from common_lore_index.retrieval.publication_binding import (
    AcceptedPublicationReference,
    CorrespondenceErrorCode,
    CorrespondenceRefusal,
    PROJECTION_REFERENCE_VERSION,
    ProjectionInputs,
    check_correspondence,
)


@dataclass(frozen=True)
class ExcludedFileRecord:
    """Explicit accounting record for an excluded artifact."""

    binding_id: str
    source_relative_path: str
    reason: ExclusionReason
    original_content_digest: str
    original_size_bytes: int
    artifact_privacy: str
    store_opened: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "binding_id": self.binding_id,
            "source_relative_path": self.source_relative_path,
            "reason": self.reason.value,
            "original_content_digest": self.original_content_digest,
            "original_size_bytes": self.original_size_bytes,
            "artifact_privacy": self.artifact_privacy,
            "store_opened": self.store_opened,
        }


@dataclass(frozen=True)
class ExcludedBindingRecord:
    """Explicit accounting record for an excluded source binding."""

    binding_id: str
    reason: ExclusionReason
    file_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "binding_id": self.binding_id,
            "reason": self.reason.value,
            "file_count": self.file_count,
        }


@dataclass(frozen=True)
class ProjectedFileRecord:
    """One projected file with full provenance, extent accounting, and contiguous chunks."""

    file_projection_id: str
    accepted_reference: AcceptedPublicationReference
    publication_bundle_id: str
    extraction_receipt_id: str
    snapshot_manifest_id: str
    source_definition_id: str
    binding_id: str
    binding_revision: int
    snapshot_id: str
    source_relative_path: str
    executable: bool
    original_content_digest: str
    original_size_bytes: int
    representation_version: str
    representation_digest: str
    source_format: str
    raw_byte_length: int
    raw_line_count: int
    normalized_byte_length: int
    normalized_line_count: int
    projected_byte_length: int
    projected_line_count: int
    truncated: bool
    had_crlf_or_cr: bool
    artifact_privacy: str
    binding_policy: ResolvedBindingPolicy
    evidence_links: tuple[ProjectedEvidenceLink, ...]
    chunks: tuple[ProjectedChunk, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_projection_id": self.file_projection_id, "accepted_reference": self.accepted_reference.to_dict(),
            "publication_bundle_id": self.publication_bundle_id, "extraction_receipt_id": self.extraction_receipt_id,
            "snapshot_manifest_id": self.snapshot_manifest_id, "source_definition_id": self.source_definition_id,
            "binding_id": self.binding_id, "binding_revision": self.binding_revision, "snapshot_id": self.snapshot_id,
            "source_relative_path": self.source_relative_path, "executable": self.executable,
            "original_content_digest": self.original_content_digest, "original_size_bytes": self.original_size_bytes,
            "representation_version": self.representation_version, "representation_digest": self.representation_digest,
            "source_format": self.source_format, "raw_byte_length": self.raw_byte_length, "raw_line_count": self.raw_line_count,
            "normalized_byte_length": self.normalized_byte_length, "normalized_line_count": self.normalized_line_count,
            "projected_byte_length": self.projected_byte_length, "projected_line_count": self.projected_line_count,
            "truncated": self.truncated, "had_crlf_or_cr": self.had_crlf_or_cr, "artifact_privacy": self.artifact_privacy,
            "binding_policy": self.binding_policy.to_dict(),
            "evidence_links": [link.to_dict() for link in self.evidence_links],
            "chunks": [chunk.to_dict() for chunk in self.chunks],
        }


@dataclass(frozen=True)
class CapturedTextProjection:
    """In-memory captured-input text projection reference (cloe-captured-text-reference-v1)."""

    reference_version: str
    accepted_reference: AcceptedPublicationReference
    publication_bundle_id: str
    extraction_receipt_id: str
    snapshot_manifest_id: str
    candidate_id: str
    policy: BodyProjectionPolicy
    policy_digest: str
    projected_files: tuple[ProjectedFileRecord, ...]
    excluded_files: tuple[ExcludedFileRecord, ...]
    excluded_bindings: tuple[ExcludedBindingRecord, ...]
    removed_files_from_prior: tuple[tuple[str, str], ...] = ()
    removed_bindings_from_prior: tuple[str, ...] = ()
    aggregate_input_bytes_read: int = 0
    projection_digest: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference_version": self.reference_version, "accepted_reference": self.accepted_reference.to_dict(),
            "publication_bundle_id": self.publication_bundle_id, "extraction_receipt_id": self.extraction_receipt_id,
            "snapshot_manifest_id": self.snapshot_manifest_id, "candidate_id": self.candidate_id,
            "policy": self.policy.to_dict(), "policy_digest": self.policy_digest,
            "projected_files": [f.to_dict() for f in self.projected_files],
            "excluded_files": [e.to_dict() for e in self.excluded_files],
            "excluded_bindings": [b.to_dict() for b in self.excluded_bindings],
            "removed_files_from_prior": [list(item) for item in self.removed_files_from_prior],
            "removed_bindings_from_prior": list(self.removed_bindings_from_prior),
            "aggregate_input_bytes_read": self.aggregate_input_bytes_read,
            "projection_digest": self.projection_digest,
        }


def build_captured_text_projection(
    inputs: ProjectionInputs,
    policy: BodyProjectionPolicy,
    *,
    prior_manifest: PortableSnapshotManifest | None = None,
) -> CapturedTextProjection:
    """Build a bounded in-memory text projection from verified captured inputs."""
    accepted = check_correspondence(inputs)
    policy.validate()
    if policy.graph_id != inputs.manifest.graph_id:
        raise ValueError("policy.graph_id must match manifest.graph_id")

    portable = inputs.receipt.portable
    if portable is None:
        raise CorrespondenceRefusal(
            CorrespondenceErrorCode.MISSING_PORTABLE_BINDING,
            "receipt.portable is required for projection build",
        )
    policy_digest = policy.policy_digest()
    evidence_index = index_bundle_evidence(inputs.bundle)

    bindings_by_id = {b.binding_id: b for b in inputs.manifest.bindings}
    entries_by_binding: dict[str, list[Any]] = {b.binding_id: [] for b in inputs.manifest.bindings}
    for entry in inputs.manifest.entries:
        entries_by_binding.setdefault(entry.binding_id, []).append(entry)

    excluded_bindings: list[ExcludedBindingRecord] = []
    for binding in sorted(inputs.manifest.bindings, key=lambda item: item.binding_id):
        b_reason = evaluate_binding_exclusion(policy, binding)
        if b_reason is not None:
            excluded_bindings.append(
                ExcludedBindingRecord(
                    binding_id=binding.binding_id,
                    reason=b_reason,
                    file_count=len(entries_by_binding.get(binding.binding_id, ())),
                )
            )

    projected_files: list[ProjectedFileRecord] = []
    excluded_files: list[ExcludedFileRecord] = []
    aggregate_bytes_read = 0

    sorted_entries = sorted(
        inputs.manifest.entries,
        key=lambda item: (item.binding_id, item.source_relative_path),
    )
    for entry in sorted_entries:
        binding = bindings_by_id[entry.binding_id]
        art_privacy = entry.reference.privacy.value
        pre_reason, source_format = evaluate_artifact_pre_open(policy, binding, entry)
        if pre_reason is not None or source_format is None:
            excluded_files.append(
                ExcludedFileRecord(
                    binding_id=entry.binding_id,
                    source_relative_path=entry.source_relative_path,
                    reason=pre_reason or ExclusionReason.UNSUPPORTED_SOURCE_FORMAT,
                    original_content_digest=entry.reference.content_digest,
                    original_size_bytes=entry.reference.size_bytes,
                    artifact_privacy=art_privacy,
                    store_opened=False,
                )
            )
            continue

        if (
            len(projected_files) >= policy.max_projected_files
            or aggregate_bytes_read + entry.reference.size_bytes > policy.max_aggregate_input_bytes
        ):
            excluded_files.append(
                ExcludedFileRecord(
                    binding_id=entry.binding_id,
                    source_relative_path=entry.source_relative_path,
                    reason=ExclusionReason.AGGREGATE_BUDGET_EXCEEDED,
                    original_content_digest=entry.reference.content_digest,
                    original_size_bytes=entry.reference.size_bytes,
                    artifact_privacy=art_privacy,
                    store_opened=False,
                )
            )
            continue

        try:
            raw_bytes = inputs.store.read(
                entry.reference.with_store_version(None),
                max_bytes=policy.max_input_artifact_bytes,
            )
        except ArtifactIntegrityError as error:
            reason = (
                ExclusionReason.ARTIFACT_MISSING
                if error.code == ArtifactErrorCode.ARTIFACT_MISSING
                else ExclusionReason.ARTIFACT_CORRUPT
            )
            excluded_files.append(
                ExcludedFileRecord(
                    binding_id=entry.binding_id,
                    source_relative_path=entry.source_relative_path,
                    reason=reason,
                    original_content_digest=entry.reference.content_digest,
                    original_size_bytes=entry.reference.size_bytes,
                    artifact_privacy=art_privacy,
                    store_opened=True,
                )
            )
            continue

        aggregate_bytes_read += len(raw_bytes)
        norm_res, text_reason = normalize_and_bound_text(
            raw_bytes,
            max_projected_bytes=policy.max_projected_file_bytes,
        )
        if norm_res is None or text_reason is not None:
            excluded_files.append(
                ExcludedFileRecord(
                    binding_id=entry.binding_id,
                    source_relative_path=entry.source_relative_path,
                    reason=text_reason or ExclusionReason.INVALID_UTF8,
                    original_content_digest=entry.reference.content_digest,
                    original_size_bytes=entry.reference.size_bytes,
                    artifact_privacy=art_privacy,
                    store_opened=True,
                )
            )
            continue

        file_proj_id = frame_digest(
            "projfile1",
            (
                policy_digest,
                inputs.bundle.bundle_id,
                inputs.manifest.manifest_id,
                binding.source_definition_id,
                binding.binding_id,
                str(binding.revision),
                binding.snapshot_id,
                entry.source_relative_path,
                entry.reference.content_digest,
                norm_res.representation_digest,
            ),
        )
        chunks = build_file_chunks(
            file_projection_id=file_proj_id,
            binding_id=binding.binding_id,
            source_relative_path=entry.source_relative_path,
            normalized_text=norm_res.normalized_text,
            artifact_privacy=art_privacy,
            policy_digest=policy_digest,
            publication_bundle_id=inputs.bundle.bundle_id,
            max_chunk_lines=policy.max_chunk_lines,
            max_chunk_bytes=policy.max_chunk_bytes,
        )
        projected_files.append(
            ProjectedFileRecord(
                file_projection_id=file_proj_id,
                accepted_reference=accepted,
                publication_bundle_id=inputs.bundle.bundle_id,
                extraction_receipt_id=portable.extraction_receipt_id,
                snapshot_manifest_id=inputs.manifest.manifest_id,
                source_definition_id=binding.source_definition_id,
                binding_id=binding.binding_id,
                binding_revision=binding.revision,
                snapshot_id=binding.snapshot_id,
                source_relative_path=entry.source_relative_path,
                executable=entry.executable,
                original_content_digest=entry.reference.content_digest,
                original_size_bytes=entry.reference.size_bytes,
                representation_version=norm_res.representation_version,
                representation_digest=norm_res.representation_digest,
                source_format=source_format,
                raw_byte_length=norm_res.raw_byte_length,
                raw_line_count=norm_res.raw_line_count,
                normalized_byte_length=norm_res.normalized_byte_length,
                normalized_line_count=norm_res.normalized_line_count,
                projected_byte_length=norm_res.projected_byte_length,
                projected_line_count=norm_res.projected_line_count,
                truncated=norm_res.truncated,
                had_crlf_or_cr=norm_res.had_crlf_or_cr,
                artifact_privacy=art_privacy,
                binding_policy=policy.bindings[binding.binding_id],
                evidence_links=evidence_index.get((binding.binding_id, entry.source_relative_path), ()),
                chunks=chunks,
            )
        )

    removed_bindings: tuple[str, ...] = ()
    removed_files: tuple[tuple[str, str], ...] = ()
    if prior_manifest is not None:
        current_b_ids = {b.binding_id for b in inputs.manifest.bindings}
        removed_bindings = tuple(
            sorted(b.binding_id for b in prior_manifest.bindings if b.binding_id not in current_b_ids)
        )
        current_f_keys = {(e.binding_id, e.source_relative_path) for e in inputs.manifest.entries}
        removed_files = tuple(
            sorted(
                (e.binding_id, e.source_relative_path)
                for e in prior_manifest.entries
                if (e.binding_id, e.source_relative_path) not in current_f_keys
            )
        )

    proj_digest = frame_digest(
        "sha256",
        (
            PROJECTION_REFERENCE_VERSION,
            policy_digest,
            inputs.bundle.bundle_id,
            inputs.manifest.manifest_id,
            *(f.file_projection_id for f in projected_files),
            *(f"{e.binding_id}:{e.source_relative_path}:{e.reason.value}" for e in excluded_files),
        ),
    )
    return CapturedTextProjection(
        reference_version=PROJECTION_REFERENCE_VERSION,
        accepted_reference=accepted,
        publication_bundle_id=inputs.bundle.bundle_id,
        extraction_receipt_id=portable.extraction_receipt_id,
        snapshot_manifest_id=inputs.manifest.manifest_id,
        candidate_id=inputs.bundle.candidate_id,
        policy=policy,
        policy_digest=policy_digest,
        projected_files=tuple(projected_files),
        excluded_files=tuple(excluded_files),
        excluded_bindings=tuple(excluded_bindings),
        removed_files_from_prior=removed_files,
        removed_bindings_from_prior=removed_bindings,
        aggregate_input_bytes_read=aggregate_bytes_read,
        projection_digest=proj_digest,
    )
