"""Streaming publication bundle parser and validator with single-pass verification."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from types import MappingProxyType
from typing import IO, Mapping, Sequence, cast

from repomap_kg.artifacts._bundle_stream_encode import (
    BundleValidationResult, PublicationExpectation, STREAMING_MAX_BUNDLE_BYTES,
)
from repomap_kg.artifacts._bundle_stream_links import DiskFamilyLinkValidator
from repomap_kg.artifacts._canonical import canonical_json, decode_canonical_json
from repomap_kg.artifacts.bundle import (
    MAX_BUNDLE_LINE_BYTES, MAX_BUNDLE_RECORDS, PUBLICATION_FAMILIES,
    FamilySummary, PublicationBundle, _integer, _string, _validate_metadata, _vector,
)
from repomap_kg.artifacts.receipt import ExtractionReceipt
from repomap_kg.storage.row_spool import RowSpool, RowSpoolWriter
from repomap_kg.storage.staged_rows import PreparedStageRows
from repomap_kg.storage.staging_checksums import FamilyChecksum, _FamilyChecksumAccumulator
from repomap_kg.storage.staging_family_catalog import family_privacy_classifications
from repomap_kg.storage.staging_family_contracts import (
    PrivacyClassification,
    STAGING_FAMILY_DESCRIPTORS,
)
from repomap_kg.storage.staging_family_rows import StageFamily


@dataclass(frozen=True)
class ValidatedBundleDescriptor:
    """Validated publication bundle metadata and stage spools without full heap loading."""

    bundle_id: str
    receipt_id: str
    candidate_id: str
    graph_id: str
    snapshot_manifest_id: str
    snapshot_vector: tuple[tuple[str, int, str], ...]
    source_generation: str
    config_generation: str
    extractor_generation: str
    canonicalizer_generation: str
    extractor_capability_identity: str
    resolver_identity: str
    canonicalizer_identity: str
    semantic_contract_identity: str
    quality_rule_identity: str
    privacy: PrivacyClassification
    row_stage_contract: str
    family_counts: dict[str, int]
    family_summaries: tuple[FamilySummary, ...]
    validation_result: BundleValidationResult
    total_bytes: int
    total_records: int
    request_id: str = ""
    job_id: str = ""
    attempt: int = 1
    schema_version: int = 1
    terminal_complete: bool = True
    family_spools: Mapping[StageFamily, RowSpool] | None = None
    checksums: Mapping[StageFamily, FamilyChecksum] | None = None
    row_counts: Mapping[StageFamily, int] | None = None
    normalized_byte_counts: Mapping[StageFamily, int] | None = None

    @property
    def families(self) -> Mapping[StageFamily, Sequence[Mapping[str, object]]]:
        if self.family_spools is None:
            return {f: () for f in PUBLICATION_FAMILIES}
        if self.row_stage_contract == "stage-unassigned-v1":
            return {
                f: tuple({**r, "stage_id": "stage-unassigned"} for r in self.family_spools[f])
                for f in PUBLICATION_FAMILIES
            }
        return {
            f: tuple({k: v for k, v in r.items() if k != "stage_id"} for r in self.family_spools[f])
            for f in PUBLICATION_FAMILIES
        }

    def canonical_bytes(self) -> bytes:
        from repomap_kg.artifacts.bundle import canonical_json, _family_frames
        hdr: dict[str, object] = {
            "attempt": self.attempt, "candidate_id": self.candidate_id,
            "canonicalizer_generation": self.canonicalizer_generation,
            "canonicalizer_identity": self.canonicalizer_identity,
            "config_generation": self.config_generation,
            "extractor_capability_identity": self.extractor_capability_identity,
            "extractor_generation": self.extractor_generation, "frame": "header",
            "framing_version": "repomap-publication-bundle-jsonl-v1",
            "graph_id": self.graph_id, "job_id": self.job_id,
            "privacy": self.privacy.value, "quality_rule_identity": self.quality_rule_identity,
            "request_id": self.request_id, "resolver_identity": self.resolver_identity,
            "schema_version": self.schema_version,
            "semantic_contract_identity": self.semantic_contract_identity,
            "snapshot_manifest_id": self.snapshot_manifest_id,
            "snapshot_vector": [list(item) for item in self.snapshot_vector],
            "source_generation": self.source_generation,
            **({"row_stage_contract": self.row_stage_contract} if self.row_stage_contract != "legacy-absent-v1" else {}),
        }
        trl = {
            "complete": self.terminal_complete, "families": [s.mapping() for s in self.family_summaries],
            "frame": "trailer", "total_family_bytes": sum(s.byte_length for s in self.family_summaries),
            "total_records": sum(s.record_count for s in self.family_summaries),
        }
        return b"".join([canonical_json(hdr), *_family_frames(self.families), canonical_json(trl)])

    @classmethod
    def from_bytes(cls, data: bytes) -> PublicationBundle:
        return PublicationBundle.from_bytes(data)

    def to_prepared_stage_rows(self) -> PreparedStageRows:
        if any(v is None for v in (self.family_spools, self.checksums, self.row_counts, self.normalized_byte_counts)):
            raise ValueError("stage rows were not prepared during streaming validation")
        return PreparedStageRows(
            family_rows=MappingProxyType(cast(Mapping[str, RowSpool], self.family_spools)),
            checksums=MappingProxyType(cast(Mapping[str, FamilyChecksum], self.checksums)),
            row_counts=MappingProxyType(cast(Mapping[str, int], self.row_counts)),
            normalized_byte_counts=MappingProxyType(cast(Mapping[str, int], self.normalized_byte_counts)),
            privacy_classifications=cast(Mapping[str, PrivacyClassification], family_privacy_classifications()),
            files=cast(Mapping[StageFamily, int], self.row_counts)["files"],
        )

    def close(self) -> None:
        for spool in (self.family_spools or {}).values():
            try:
                spool.close()
            except Exception:
                pass


class StreamingBundleParser:
    """Parse and validate a publication bundle stream in a single forward pass."""

    def __init__(
        self,
        *,
        spool_dir: Path | str | None = None,
        max_bundle_bytes: int = STREAMING_MAX_BUNDLE_BYTES,
    ) -> None:
        self.spool_dir = Path(spool_dir) if spool_dir is not None else None
        if self.spool_dir is not None:
            self.spool_dir.mkdir(parents=True, exist_ok=True)
        self.max_bundle_bytes = max_bundle_bytes

    def parse_and_validate(
        self,
        stream: IO[bytes],
        expectation: PublicationExpectation,
        receipt: ExtractionReceipt,
        *,
        stage_id: str | None = None,
        prior_attempt: tuple[str, str | None, str] | None = None,
    ) -> ValidatedBundleDescriptor:
        if expectation.mutating_owner_count != 1:
            raise ValueError("exactly one mutating owner is required")

        header_line = stream.readline(MAX_BUNDLE_LINE_BYTES + 1)
        if not header_line or not header_line.endswith(b"\n") or len(header_line) > MAX_BUNDLE_LINE_BYTES:
            raise ValueError("publication bundle framing is invalid")

        header = decode_canonical_json(header_line)
        if header.get("frame") != "header":
            raise ValueError("publication bundle framing is invalid")
        if header.get("schema_version") != 1 or header.get("framing_version") != PublicationBundle.FRAMING_VERSION:
            raise ValueError("unsupported publication bundle version")

        self._validate_header(header, expectation, receipt)
        row_stage_contract = (
            _string(header, "row_stage_contract")
            if "row_stage_contract" in header
            else "legacy-absent-v1"
        )
        if row_stage_contract not in {"legacy-absent-v1", "stage-unassigned-v1"}:
            raise ValueError("bundle row stage contract is invalid")

        artifact_hasher = hashlib.sha256(header_line)
        bundle_hasher = hashlib.sha256(b"repomap-publication-bundle-v1\x00" + header_line)
        total_bytes, total_records = len(header_line), 0
        spool_writers: dict[StageFamily, RowSpoolWriter] = (
            {f: RowSpoolWriter(dir=self.spool_dir) for f in PUBLICATION_FAMILIES} if stage_id is not None else {}
        )
        checksum_accumulators: dict[StageFamily, _FamilyChecksumAccumulator] = (
            {f: _FamilyChecksumAccumulator(STAGING_FAMILY_DESCRIPTORS[f].identity_columns) for f in PUBLICATION_FAMILIES}
            if stage_id is not None else {}
        )
        link_validator = DiskFamilyLinkValidator(spool_dir=self.spool_dir)
        current_family_idx, last_canonical_record_bytes = 0, None
        family_record_counts = {f: 0 for f in PUBLICATION_FAMILIES}
        family_byte_lengths = {f: 0 for f in PUBLICATION_FAMILIES}
        family_hashers = {f: hashlib.sha256() for f in PUBLICATION_FAMILIES}
        trailer_frame: dict[str, object] | None = None
        family_spools: dict[StageFamily, RowSpool] | None = None

        try:
            while True:
                line = stream.readline(MAX_BUNDLE_LINE_BYTES + 1)
                if not line:
                    break
                if len(line) > MAX_BUNDLE_LINE_BYTES or not line.endswith(b"\n"):
                    raise ValueError("publication bundle line bounds exceeded")
                total_bytes += len(line)
                if total_bytes > self.max_bundle_bytes:
                    raise ValueError("publication bundle byte bounds exceeded")

                frame = decode_canonical_json(line)
                if frame.get("frame") == "trailer":
                    trailer_frame = frame
                    artifact_hasher.update(line)
                    bundle_hasher.update(line)
                    break

                if frame.get("frame") != "record" or set(frame.keys()) != {"family", "frame", "record"}:
                    raise ValueError("publication bundle record frame is invalid")

                family = frame.get("family")
                record = frame.get("record")
                if not isinstance(record, dict) or family not in PUBLICATION_FAMILIES:
                    raise ValueError("publication bundle family is invalid")

                family_idx = PUBLICATION_FAMILIES.index(family)
                if family_idx < current_family_idx:
                    raise ValueError("publication bundle family ordering is invalid")
                while family_idx > current_family_idx:
                    link_validator.finish_family(PUBLICATION_FAMILIES[current_family_idx])
                    current_family_idx += 1
                    last_canonical_record_bytes = None

                # Intra-family ordering check
                canonical_record_bytes = canonical_json(record)
                if last_canonical_record_bytes is not None and canonical_record_bytes < last_canonical_record_bytes:
                    raise ValueError("publication bundle intra-family ordering is invalid")
                last_canonical_record_bytes = canonical_record_bytes

                # Stage contract verification
                stage_val = record.get("stage_id")
                if row_stage_contract == "stage-unassigned-v1" and stage_val != "stage-unassigned":
                    raise ValueError("bundle stage representation is ambiguous: stage identity")
                if row_stage_contract != "stage-unassigned-v1" and stage_val is not None:
                    raise ValueError("legacy bundle stage representation is ambiguous")

                # Update hashes and counts
                artifact_hasher.update(line)
                bundle_hasher.update(line)
                family_hashers[family].update(line)
                family_record_counts[family] += 1
                family_byte_lengths[family] += len(line)
                total_records += 1
                if total_records > MAX_BUNDLE_RECORDS:
                    raise ValueError("publication bundle record bounds exceeded")

                self._record_links(link_validator, family, record)

                if stage_id is not None:
                    spool_writers[family].write_row({**record, "stage_id": stage_id})
                    checksum_accumulators[family].add({k: v for k, v in record.items() if k != "stage_id"})

            if trailer_frame is None:
                raise ValueError("publication bundle framing is invalid")

            while current_family_idx < len(PUBLICATION_FAMILIES):
                link_validator.finish_family(PUBLICATION_FAMILIES[current_family_idx])
                current_family_idx += 1

            # Validate trailer
            expected_summaries = tuple(
                FamilySummary(
                    f,
                    family_record_counts[f],
                    family_byte_lengths[f],
                    "sha256:" + family_hashers[f].hexdigest(),
                )
                for f in PUBLICATION_FAMILIES
            )
            expected_trailer = {
                "complete": True,
                "families": [item.mapping() for item in expected_summaries],
                "frame": "trailer",
                "total_family_bytes": sum(item.byte_length for item in expected_summaries),
                "total_records": sum(item.record_count for item in expected_summaries),
            }
            if trailer_frame != expected_trailer:
                raise ValueError("publication bundle summary is inconsistent")

            # Check EOF
            extra = stream.read(1)
            if extra:
                raise ValueError("publication bundle framing is invalid")

            # Verify bundle ID and receipt matches
            bundle_id = "bundle1:" + bundle_hasher.hexdigest()
            if bundle_id != receipt.bundle_id:
                raise ValueError("receipt and bundle terminal state is inconsistent")
            artifact_digest = "sha256:" + artifact_hasher.hexdigest()
            counts_match = dict(receipt.family_counts) == {item.family: item.record_count for item in expected_summaries}
            if receipt.bundle_reference is None or artifact_digest != receipt.bundle_reference.content_digest or not counts_match:
                raise ValueError("receipt and bundle terminal state is inconsistent")

            checksums, row_counts, normalized_byte_counts = None, None, None
            if stage_id is not None:
                family_spools = {f: spool_writers[f].finish() for f in PUBLICATION_FAMILIES}
                checksums = {f: checksum_accumulators[f].finish() for f in PUBLICATION_FAMILIES}
                row_counts = {f: checksums[f].row_count for f in PUBLICATION_FAMILIES}
                normalized_byte_counts = {f: checksums[f].normalized_byte_count for f in PUBLICATION_FAMILIES}

            replay = prior_attempt == (receipt.receipt_id, bundle_id, "completed")

            return ValidatedBundleDescriptor(
                bundle_id=bundle_id, receipt_id=receipt.receipt_id,
                candidate_id=_string(header, "candidate_id"), graph_id=_string(header, "graph_id"),
                snapshot_manifest_id=_string(header, "snapshot_manifest_id"),
                snapshot_vector=_vector(header.get("snapshot_vector")),
                source_generation=_string(header, "source_generation"),
                config_generation=_string(header, "config_generation"),
                extractor_generation=_string(header, "extractor_generation"),
                canonicalizer_generation=_string(header, "canonicalizer_generation"),
                extractor_capability_identity=_string(header, "extractor_capability_identity"),
                resolver_identity=_string(header, "resolver_identity"),
                canonicalizer_identity=_string(header, "canonicalizer_identity"),
                semantic_contract_identity=_string(header, "semantic_contract_identity"),
                quality_rule_identity=_string(header, "quality_rule_identity"),
                privacy=PrivacyClassification(_string(header, "privacy")),
                row_stage_contract=row_stage_contract,
                family_counts={item.family: item.record_count for item in expected_summaries},
                family_summaries=expected_summaries,
                validation_result=BundleValidationResult(
                    bundle_id, receipt.receipt_id, byte_integrity_valid=True,
                    semantic_authority_valid=True, idempotent_replay=replay,
                ),
                total_bytes=total_bytes, total_records=total_records,
                request_id=_string(header, "request_id"), job_id=_string(header, "job_id"),
                attempt=_integer(header, "attempt"),
                schema_version=_integer(header, "schema_version") if "schema_version" in header else 1,
                terminal_complete=True, family_spools=family_spools, checksums=checksums,
                row_counts=row_counts, normalized_byte_counts=normalized_byte_counts,
            )
        except Exception:
            if stage_id is not None:
                for s in (family_spools or {}).values():
                    s.close()
                for w in spool_writers.values():
                    w.abort()
            raise
        finally:
            link_validator.close()

    @staticmethod
    def _validate_header(
        header: dict[str, object], expected: PublicationExpectation, receipt: ExtractionReceipt
    ) -> None:
        expected_keys = {
            "attempt", "candidate_id", "canonicalizer_generation", "canonicalizer_identity",
            "config_generation", "extractor_capability_identity", "extractor_generation",
            "frame", "framing_version", "graph_id", "job_id", "privacy",
            "quality_rule_identity", "request_id", "resolver_identity", "schema_version",
            "semantic_contract_identity", "snapshot_manifest_id", "snapshot_vector",
            "source_generation",
        }
        if "row_stage_contract" in header:
            expected_keys.add("row_stage_contract")
        if set(header.keys()) != expected_keys:
            raise ValueError("publication bundle framing is invalid")
        meta_keys = (
            "request_id", "job_id", "graph_id", "candidate_id", "snapshot_manifest_id",
            "source_generation", "config_generation", "extractor_generation",
            "canonicalizer_generation", "extractor_capability_identity", "resolver_identity",
            "canonicalizer_identity", "semantic_contract_identity", "quality_rule_identity",
        )
        _validate_metadata(
            attempt=_integer(header, "attempt"),
            **{k: _string(header, k) for k in meta_keys},
        )
        fields = ("attempt", "candidate_id", *meta_keys)
        if any(header.get(f) != getattr(expected, f) for f in fields) or _vector(header.get("snapshot_vector")) != expected.snapshot_vector:
            raise ValueError("bundle semantic authority mismatch")
        receipt_fields = tuple(f for f in fields if f != "candidate_id")
        if any(header.get(f) != getattr(receipt, f) for f in receipt_fields) or _vector(header.get("snapshot_vector")) != receipt.snapshot_vector:
            raise ValueError("receipt semantic authority mismatch")
        if receipt.contract_version != expected.contract_version or receipt.worker_capability_identity != expected.worker_capability_identity:
            raise ValueError("receipt contract version mismatch")
        if expected.expected_privacy is not None and header.get("privacy") != expected.expected_privacy:
            raise ValueError("bundle privacy mismatch")
        if receipt.outcome != "completed" or receipt.cancellation not in {"not-requested", "not-observed"}:
            raise ValueError("receipt and bundle terminal state is inconsistent")

    @staticmethod
    def _record_links(
        validator: DiskFamilyLinkValidator, family: StageFamily, record: dict[str, object]
    ) -> None:
        dispatch = {
            "raw_observations": validator.record_raw_observation, "canonical_nodes": validator.record_canonical_node,
            "canonical_edges": validator.record_canonical_edge, "canonical_evidence": validator.record_and_validate_evidence,
            "canonical_node_evidence": validator.validate_node_evidence, "canonical_edge_evidence": validator.validate_edge_evidence,
        }
        handler = dispatch.get(family)
        if handler is not None:
            handler(record)
