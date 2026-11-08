"""Bounded, non-ingesting proof of retained manifest, receipt, and bundle."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from collections.abc import Mapping

from common_lore_index.artifacts import (
    DEFAULT_ARTIFACT_LIMITS,
    FileSystemArtifactStore,
    ExtractionReceipt,
    PortableSnapshotManifest,
)
from common_lore_index.artifacts._canonical import canonical_json, decode_canonical_json
from common_lore_index.artifacts.bundle import (
    MAX_BUNDLE_LINE_BYTES,
    MAX_BUNDLE_RECORDS,
    PUBLICATION_FAMILIES,
    STREAMING_MAX_BUNDLE_BYTES,
)
from common_lore_index.ops._retained_attempt_record import RetainedRecord


class RetainedArtifactError(ValueError):
    """Retained objects are missing, malformed, or inconsistent."""


@dataclass(frozen=True)
class RetainedArtifactProof:
    manifest: PortableSnapshotManifest
    receipt: ExtractionReceipt
    candidate_id: str
    bundle_id: str
    family_receipts: tuple[tuple[str, int, int, str], ...]


def _header(proof: RetainedArtifactProof, header: Mapping[str, object]) -> None:
    receipt, manifest = proof.receipt, proof.manifest
    if (
        manifest.graph_id != receipt.graph_id
        or manifest.manifest_id != receipt.snapshot_manifest_id
        or manifest.extractor_capability_identity != receipt.extractor_capability_identity
        or (
            manifest.source_generation,
            manifest.config_generation,
            manifest.extractor_generation,
            manifest.canonicalizer_generation,
            manifest.resolver_identity,
            manifest.canonicalizer_identity,
            manifest.semantic_contract_identity,
            manifest.quality_rule_identity,
            manifest.snapshot_vector,
        )
        != (
            receipt.source_generation,
            receipt.config_generation,
            receipt.extractor_generation,
            receipt.canonicalizer_generation,
            receipt.resolver_identity,
            receipt.canonicalizer_identity,
            receipt.semantic_contract_identity,
            receipt.quality_rule_identity,
            receipt.snapshot_vector,
        )
    ):
        raise RetainedArtifactError("manifest-mismatch")
    keys = {
        "attempt", "candidate_id", "canonicalizer_generation", "canonicalizer_identity",
        "config_generation", "extractor_capability_identity", "extractor_generation", "frame",
        "framing_version", "graph_id", "job_id", "privacy", "quality_rule_identity", "request_id",
        "resolver_identity", "schema_version", "semantic_contract_identity", "snapshot_manifest_id",
        "snapshot_vector", "source_generation",
    }
    if "row_stage_contract" in header:
        keys.add("row_stage_contract")
    if set(header) != keys or header.get("frame") != "header" or header.get("schema_version") != 1:
        raise RetainedArtifactError("bundle-invalid")
    if type(header.get("schema_version")) is not int or type(header.get("attempt")) is not int:
        raise RetainedArtifactError("bundle-invalid")
    vector = header.get("snapshot_vector")
    if not isinstance(vector, list) or any(
        not isinstance(item, list)
        or len(item) != 3
        or not isinstance(item[0], str)
        or type(item[1]) is not int
        or not isinstance(item[2], str)
        for item in vector
    ):
        raise RetainedArtifactError("bundle-invalid")
    if header.get("framing_version") != "repomap-publication-bundle-jsonl-v1":
        raise RetainedArtifactError("bundle-invalid")
    if not isinstance(header.get("candidate_id"), str):
        raise RetainedArtifactError("bundle-invalid")
    expected = {
        "attempt": receipt.attempt, "graph_id": receipt.graph_id, "job_id": receipt.job_id,
        "request_id": receipt.request_id, "snapshot_manifest_id": manifest.manifest_id,
        "snapshot_vector": [list(item) for item in manifest.snapshot_vector],
        "source_generation": manifest.source_generation, "config_generation": manifest.config_generation,
        "extractor_generation": manifest.extractor_generation,
        "canonicalizer_generation": manifest.canonicalizer_generation,
        "extractor_capability_identity": manifest.extractor_capability_identity,
        "resolver_identity": manifest.resolver_identity, "canonicalizer_identity": manifest.canonicalizer_identity,
        "semantic_contract_identity": manifest.semantic_contract_identity,
        "quality_rule_identity": manifest.quality_rule_identity,
        "privacy": manifest.effective_privacy.value,
    }
    if any(header.get(key) != value for key, value in expected.items()):
        raise RetainedArtifactError("bundle-mismatch")
    stage = header.get("row_stage_contract", "legacy-absent-v1")
    if stage not in {"legacy-absent-v1", "stage-unassigned-v1"}:
        raise RetainedArtifactError("bundle-invalid")


def read_retained_artifacts(record: RetainedRecord, store: FileSystemArtifactStore) -> RetainedArtifactProof:
    try:
        manifest_ref, receipt_ref, bundle_ref = record.references
        manifest_bytes = store.read(manifest_ref, max_bytes=DEFAULT_ARTIFACT_LIMITS.max_manifest_bytes)
        manifest = PortableSnapshotManifest.from_bytes(manifest_bytes)
        if manifest.manifest_id != record.payload.get("manifest_id"):
            raise RetainedArtifactError("manifest-mismatch")
        receipt_bytes = store.read(receipt_ref, max_bytes=DEFAULT_ARTIFACT_LIMITS.max_manifest_bytes)
        receipt = ExtractionReceipt.from_bytes(receipt_bytes)
        if (
            receipt.outcome != "completed"
            or receipt.cancellation not in {"not-requested", "not-observed"}
            or receipt.bundle_reference is None or receipt.bundle_id is None
        ):
            raise RetainedArtifactError("receipt-invalid")
        if receipt.bundle_reference != bundle_ref:
            raise RetainedArtifactError("receipt-mismatch")
        with store.open_stream(bundle_ref, max_bytes=STREAMING_MAX_BUNDLE_BYTES) as stream:
            header_line = stream.readline(MAX_BUNDLE_LINE_BYTES + 1)
            if not header_line.endswith(b"\n") or len(header_line) > MAX_BUNDLE_LINE_BYTES:
                raise RetainedArtifactError("bundle-invalid")
            header = decode_canonical_json(header_line)
            raw_hash = hashlib.sha256(header_line)
            bundle_hash = hashlib.sha256(b"repomap-publication-bundle-v1\x00" + header_line)
            _header_placeholder = RetainedArtifactProof(manifest, receipt, "", "", ())
            _header(_header_placeholder, header)
            counts = {family: 0 for family in PUBLICATION_FAMILIES}
            lengths = {family: 0 for family in PUBLICATION_FAMILIES}
            hashes = {family: hashlib.sha256() for family in PUBLICATION_FAMILIES}
            total_bytes = len(header_line)
            total_records = 0
            current_family_index = 0
            last_record: bytes | None = None
            row_stage_contract = header.get("row_stage_contract", "legacy-absent-v1")
            trailer: Mapping[str, object] | None = None
            while True:
                line = stream.readline(MAX_BUNDLE_LINE_BYTES + 1)
                if not line:
                    break
                if len(line) > MAX_BUNDLE_LINE_BYTES or not line.endswith(b"\n"):
                    raise RetainedArtifactError("bundle-invalid")
                total_bytes += len(line)
                if total_bytes > STREAMING_MAX_BUNDLE_BYTES:
                    raise RetainedArtifactError("bundle-invalid")
                raw_hash.update(line)
                bundle_hash.update(line)
                frame = decode_canonical_json(line)
                if frame.get("frame") == "trailer":
                    trailer = frame
                    break
                if frame.get("frame") != "record" or set(frame) != {"family", "frame", "record"}:
                    raise RetainedArtifactError("bundle-invalid")
                family, item = frame.get("family"), frame.get("record")
                if family not in PUBLICATION_FAMILIES or not isinstance(item, dict):
                    raise RetainedArtifactError("bundle-invalid")
                family_index = PUBLICATION_FAMILIES.index(family)
                if family_index < current_family_index:
                    raise RetainedArtifactError("bundle-invalid")
                if family_index > current_family_index:
                    current_family_index = family_index
                    last_record = None
                canonical_record = canonical_json(item)
                if last_record is not None and canonical_record < last_record:
                    raise RetainedArtifactError("bundle-invalid")
                last_record = canonical_record
                stage_value = item.get("stage_id")
                if row_stage_contract == "stage-unassigned-v1" and stage_value != "stage-unassigned":
                    raise RetainedArtifactError("bundle-invalid")
                if row_stage_contract != "stage-unassigned-v1" and stage_value is not None:
                    raise RetainedArtifactError("bundle-invalid")
                total_records += 1
                if total_records > MAX_BUNDLE_RECORDS:
                    raise RetainedArtifactError("bundle-invalid")
                counts[family] += 1
                lengths[family] += len(line)
                hashes[family].update(line)
            if trailer is None or stream.read(1):
                raise RetainedArtifactError("bundle-invalid")
            summaries = [
                {"byte_length": lengths[f], "content_digest": "sha256:" + hashes[f].hexdigest(),
                 "family": f, "record_count": counts[f]}
                for f in PUBLICATION_FAMILIES
            ]
            expected_trailer = {
                "complete": True, "families": summaries, "frame": "trailer",
                "total_family_bytes": sum(lengths.values()), "total_records": sum(counts.values()),
            }
            trailer_families = trailer.get("families")
            strict_family_summaries = isinstance(trailer_families, list) and len(trailer_families) == len(summaries) and all(
                isinstance(item, dict)
                and set(item) == {"byte_length", "content_digest", "family", "record_count"}
                and isinstance(item.get("family"), str)
                and type(item.get("byte_length")) is int
                and type(item.get("record_count")) is int
                and isinstance(item.get("content_digest"), str)
                for item in trailer_families
            )
            if (
                trailer.get("complete") is not True
                or type(trailer.get("total_family_bytes")) is not int
                or type(trailer.get("total_records")) is not int
                or not strict_family_summaries
                or dict(trailer) != expected_trailer
            ):
                raise RetainedArtifactError("bundle-mismatch")
            bundle_id = "bundle1:" + bundle_hash.hexdigest()
            artifact_digest = "sha256:" + raw_hash.hexdigest()
            # The verifying stream checks the exact referenced size and digest;
            # this second digest is the bundle's domain-prefixed identity.
            if bundle_id != receipt.bundle_id or artifact_digest != bundle_ref.content_digest:
                raise RetainedArtifactError("bundle-mismatch")
            if dict(receipt.family_counts) != counts:
                raise RetainedArtifactError("receipt-mismatch")
            candidate_id = str(header["candidate_id"])
            return RetainedArtifactProof(
                manifest, receipt, candidate_id, bundle_id,
                tuple((f, counts[f], lengths[f], "sha256:" + hashes[f].hexdigest()) for f in PUBLICATION_FAMILIES),
            )
    except RetainedArtifactError:
        raise
    except (OSError, TypeError, ValueError, KeyError) as error:
        raise RetainedArtifactError("artifact-unavailable") from error


__all__ = ("RetainedArtifactError", "RetainedArtifactProof", "read_retained_artifacts")
