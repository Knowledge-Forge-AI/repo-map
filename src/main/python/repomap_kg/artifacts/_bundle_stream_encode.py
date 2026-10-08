"""Streaming publication bundle encoder with dual hashing and bounded sorting."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import threading
from typing import Callable, Iterable, Iterator, Mapping

from repomap_kg.artifacts._canonical import canonical_json
from repomap_kg.artifacts._bundle_stream_sort import BoundedExternalRowSorter
from repomap_kg.artifacts.bundle import (
    MAX_BUNDLE_LINE_BYTES,
    MAX_BUNDLE_RECORDS,
    PUBLICATION_FAMILIES,
    STREAMING_MAX_BUNDLE_BYTES,
    FamilySummary,
    PublicationBundle,
    _validate_metadata,
)
from repomap_kg.storage.staging_family_contracts import PrivacyClassification
from repomap_kg.storage.staging_family_rows import StageFamily


@dataclass(frozen=True)
class PublicationExpectation:
    request_id: str
    job_id: str
    attempt: int
    graph_id: str
    candidate_id: str
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
    mutating_owner_count: int
    contract_version: str = "1.0"
    worker_capability_identity: str = "cap1:portable-worker-v1"
    expected_privacy: str | None = None

    @classmethod
    def from_bundle(
        cls,
        bundle: PublicationBundle,
        *,
        mutating_owner_count: int,
        contract_version: str = "1.0",
        worker_capability_identity: str = "cap1:portable-worker-v1",
        expected_privacy: str | None = None,
    ) -> "PublicationExpectation":
        return cls(
            bundle.request_id,
            bundle.job_id,
            bundle.attempt,
            bundle.graph_id,
            bundle.candidate_id,
            bundle.snapshot_manifest_id,
            bundle.snapshot_vector,
            bundle.source_generation,
            bundle.config_generation,
            bundle.extractor_generation,
            bundle.canonicalizer_generation,
            bundle.extractor_capability_identity,
            bundle.resolver_identity,
            bundle.canonicalizer_identity,
            bundle.semantic_contract_identity,
            bundle.quality_rule_identity,
            mutating_owner_count,
            contract_version=contract_version,
            worker_capability_identity=worker_capability_identity,
            expected_privacy=expected_privacy or bundle.privacy.value,
        )


@dataclass(frozen=True)
class BundleValidationResult:
    bundle_id: str
    receipt_id: str
    byte_integrity_valid: bool
    semantic_authority_valid: bool
    idempotent_replay: bool
    mutated: bool = False


@dataclass(frozen=True)
class StreamingBundleDescriptor:
    """Readback descriptor for a stream-encoded publication bundle."""

    request_id: str
    job_id: str
    attempt: int
    graph_id: str
    candidate_id: str
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
    family_summaries: tuple[FamilySummary, ...]
    terminal_complete: bool
    schema_version: int
    bundle_id: str
    total_bytes: int
    total_records: int
    artifact_content_digest: str

    @property
    def family_counts(self) -> dict[str, int]:
        return {item.family: item.record_count for item in self.family_summaries}

    def header_mapping(self) -> dict[str, object]:
        header: dict[str, object] = {
            "attempt": self.attempt,
            "candidate_id": self.candidate_id,
            "canonicalizer_generation": self.canonicalizer_generation,
            "canonicalizer_identity": self.canonicalizer_identity,
            "config_generation": self.config_generation,
            "extractor_capability_identity": self.extractor_capability_identity,
            "extractor_generation": self.extractor_generation,
            "frame": "header",
            "framing_version": PublicationBundle.FRAMING_VERSION,
            "graph_id": self.graph_id,
            "job_id": self.job_id,
            "privacy": self.privacy.value,
            "quality_rule_identity": self.quality_rule_identity,
            "request_id": self.request_id,
            "resolver_identity": self.resolver_identity,
            "schema_version": self.schema_version,
            "semantic_contract_identity": self.semantic_contract_identity,
            "snapshot_manifest_id": self.snapshot_manifest_id,
            "snapshot_vector": [list(item) for item in self.snapshot_vector],
            "source_generation": self.source_generation,
        }
        if self.row_stage_contract != "legacy-absent-v1":
            header["row_stage_contract"] = self.row_stage_contract
        return header

    def trailer_mapping(self) -> dict[str, object]:
        return {
            "complete": self.terminal_complete,
            "families": [item.mapping() for item in self.family_summaries],
            "frame": "trailer",
            "total_family_bytes": sum(item.byte_length for item in self.family_summaries),
            "total_records": sum(item.record_count for item in self.family_summaries),
        }


class StreamingBundleEncoder:
    """Encode publication candidate rows into a v1 canonical JSONL stream."""

    def __init__(
        self,
        *,
        request_id: str,
        job_id: str,
        attempt: int,
        graph_id: str,
        candidate_id: str,
        snapshot_manifest_id: str,
        snapshot_vector: tuple[tuple[str, int, str], ...],
        source_generation: str,
        config_generation: str,
        extractor_generation: str,
        canonicalizer_generation: str,
        extractor_capability_identity: str,
        resolver_identity: str,
        canonicalizer_identity: str,
        semantic_contract_identity: str,
        quality_rule_identity: str,
        privacy: PrivacyClassification,
        family_rows: Mapping[str, Iterable[dict[str, object]]] | Mapping[StageFamily, Iterable[dict[str, object]]],
        row_stage_contract: str = "stage-unassigned-v1",
        terminal_complete: bool = True,
        schema_version: int = 1,
        max_bundle_bytes: int = STREAMING_MAX_BUNDLE_BYTES,
        spool_dir: Path | str | None = None,
        cancel_event: threading.Event | None = None,
        checkpoint: Callable[[], None] | None = None,
        max_sorter_buffer_bytes: int | None = None,
    ) -> None:
        _validate_metadata(
            request_id=request_id, job_id=job_id, attempt=attempt, graph_id=graph_id,
            candidate_id=candidate_id, snapshot_manifest_id=snapshot_manifest_id,
            source_generation=source_generation, config_generation=config_generation,
            extractor_generation=extractor_generation,
            canonicalizer_generation=canonicalizer_generation,
            extractor_capability_identity=extractor_capability_identity,
            resolver_identity=resolver_identity,
            canonicalizer_identity=canonicalizer_identity,
            semantic_contract_identity=semantic_contract_identity,
            quality_rule_identity=quality_rule_identity,
        )
        if not isinstance(privacy, PrivacyClassification):
            raise ValueError("bundle privacy is invalid")
        if row_stage_contract not in {"legacy-absent-v1", "stage-unassigned-v1"}:
            raise ValueError("bundle row stage contract is invalid")
        if not isinstance(terminal_complete, bool):
            raise ValueError("bundle terminal completeness is invalid")
        if set(family_rows) != set(PUBLICATION_FAMILIES):
            raise ValueError("publication bundle family inventory is invalid")

        self.request_id = request_id
        self.job_id = job_id
        self.attempt = attempt
        self.graph_id = graph_id
        self.candidate_id = candidate_id
        self.snapshot_manifest_id = snapshot_manifest_id
        self.snapshot_vector = snapshot_vector
        self.source_generation = source_generation
        self.config_generation = config_generation
        self.extractor_generation = extractor_generation
        self.canonicalizer_generation = canonicalizer_generation
        self.extractor_capability_identity = extractor_capability_identity
        self.resolver_identity = resolver_identity
        self.canonicalizer_identity = canonicalizer_identity
        self.semantic_contract_identity = semantic_contract_identity
        self.quality_rule_identity = quality_rule_identity
        self.privacy = privacy
        self.row_stage_contract = row_stage_contract
        self.terminal_complete = terminal_complete
        self.schema_version = schema_version
        self.family_rows = family_rows
        self.max_bundle_bytes = max_bundle_bytes
        self.spool_dir = spool_dir
        self.cancel_event = cancel_event
        self.checkpoint = checkpoint
        self.max_sorter_buffer_bytes = max_sorter_buffer_bytes
        self.spill_run_count = 0
        self.spill_bytes = 0
        self._descriptor: StreamingBundleDescriptor | None = None

    def _header_mapping(self) -> dict[str, object]:
        header: dict[str, object] = {
            "attempt": self.attempt,
            "candidate_id": self.candidate_id,
            "canonicalizer_generation": self.canonicalizer_generation,
            "canonicalizer_identity": self.canonicalizer_identity,
            "config_generation": self.config_generation,
            "extractor_capability_identity": self.extractor_capability_identity,
            "extractor_generation": self.extractor_generation,
            "frame": "header",
            "framing_version": PublicationBundle.FRAMING_VERSION,
            "graph_id": self.graph_id,
            "job_id": self.job_id,
            "privacy": self.privacy.value,
            "quality_rule_identity": self.quality_rule_identity,
            "request_id": self.request_id,
            "resolver_identity": self.resolver_identity,
            "schema_version": self.schema_version,
            "semantic_contract_identity": self.semantic_contract_identity,
            "snapshot_manifest_id": self.snapshot_manifest_id,
            "snapshot_vector": [list(item) for item in self.snapshot_vector],
            "source_generation": self.source_generation,
        }
        if self.row_stage_contract != "legacy-absent-v1":
            header["row_stage_contract"] = self.row_stage_contract
        return header

    def stream_chunks(self, chunk_size: int = 65536) -> Iterator[bytes]:
        """Stream canonical bundle chunks directly to artifact store."""
        artifact_hasher = hashlib.sha256()
        bundle_hasher = hashlib.sha256(b"repomap-publication-bundle-v1\x00")
        total_records = 0
        total_bytes = 0
        summaries: list[FamilySummary] = []
        chunk_buf = bytearray()

        def emit_line(line: bytes) -> Iterator[bytes]:
            nonlocal total_bytes
            total_bytes += len(line)
            if total_bytes > self.max_bundle_bytes:
                raise ValueError("publication bundle byte bounds exceeded")
            artifact_hasher.update(line)
            bundle_hasher.update(line)
            chunk_buf.extend(line)
            if len(chunk_buf) >= chunk_size:
                out = bytes(chunk_buf)
                chunk_buf.clear()
                yield out

        # 1. Header frame
        header_line = canonical_json(self._header_mapping())
        if len(header_line) > MAX_BUNDLE_LINE_BYTES:
            raise ValueError("publication bundle line bounds exceeded")
        yield from emit_line(header_line)

        # 2. Family record lines (ordered by family)
        for family in PUBLICATION_FAMILIES:
            if self.cancel_event is not None and self.cancel_event.is_set():
                raise ValueError("cancelled")
            if self.max_sorter_buffer_bytes is not None:
                sorter = BoundedExternalRowSorter(
                    max_buffer_bytes=self.max_sorter_buffer_bytes,
                    spool_dir=self.spool_dir,
                )
            else:
                sorter = BoundedExternalRowSorter(spool_dir=self.spool_dir)
            try:
                family_records = 0
                family_bytes = 0
                family_hasher = hashlib.sha256()
                for line in sorter.sort_family_records(family, self.family_rows[family]):
                    if self.cancel_event is not None and self.cancel_event.is_set():
                        raise ValueError("cancelled")
                    family_records += 1
                    family_bytes += len(line)
                    total_records += 1
                    if total_records > MAX_BUNDLE_RECORDS:
                        raise ValueError("publication bundle record bounds exceeded")
                    family_hasher.update(line)
                    yield from emit_line(line)
                    if self.checkpoint is not None and (total_records % 1000 == 0):
                        self.checkpoint()
                self.spill_run_count += sorter.spill_run_count
                self.spill_bytes += sorter.spill_bytes
                summaries.append(
                    FamilySummary(
                        family,
                        family_records,
                        family_bytes,
                        "sha256:" + family_hasher.hexdigest(),
                    )
                )
            finally:
                sorter.close()

        # 3. Trailer frame
        trailer_mapping = {
            "complete": self.terminal_complete,
            "families": [item.mapping() for item in summaries],
            "frame": "trailer",
            "total_family_bytes": sum(item.byte_length for item in summaries),
            "total_records": sum(item.record_count for item in summaries),
        }
        trailer_line = canonical_json(trailer_mapping)
        if len(trailer_line) > MAX_BUNDLE_LINE_BYTES:
            raise ValueError("publication bundle line bounds exceeded")
        yield from emit_line(trailer_line)

        if chunk_buf:
            yield bytes(chunk_buf)
            chunk_buf.clear()

        bundle_id = "bundle1:" + bundle_hasher.hexdigest()
        content_digest = "sha256:" + artifact_hasher.hexdigest()

        self._descriptor = StreamingBundleDescriptor(
            request_id=self.request_id,
            job_id=self.job_id,
            attempt=self.attempt,
            graph_id=self.graph_id,
            candidate_id=self.candidate_id,
            snapshot_manifest_id=self.snapshot_manifest_id,
            snapshot_vector=self.snapshot_vector,
            source_generation=self.source_generation,
            config_generation=self.config_generation,
            extractor_generation=self.extractor_generation,
            canonicalizer_generation=self.canonicalizer_generation,
            extractor_capability_identity=self.extractor_capability_identity,
            resolver_identity=self.resolver_identity,
            canonicalizer_identity=self.canonicalizer_identity,
            semantic_contract_identity=self.semantic_contract_identity,
            quality_rule_identity=self.quality_rule_identity,
            privacy=self.privacy,
            row_stage_contract=self.row_stage_contract,
            family_summaries=tuple(summaries),
            terminal_complete=self.terminal_complete,
            schema_version=self.schema_version,
            bundle_id=bundle_id,
            total_bytes=total_bytes,
            total_records=total_records,
            artifact_content_digest=content_digest,
        )

    def descriptor(self) -> StreamingBundleDescriptor:
        if self._descriptor is None:
            raise ValueError("streaming encoding has not completed")
        return self._descriptor
