"""WARC ingestion records and JSON contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from repomap_kg.observations.raw import RawObservation
from repomap_kg.ops.ingestion.acquisition_contracts import NonPublicationResult


@dataclass(frozen=True)
class WarcSourceConfig:
    source_id: str
    source_type: str
    display_name: str | None
    policy_status: str
    max_artifact_bytes: int
    max_file_count: int
    max_warc_records: int
    max_record_bytes: int
    max_total_payload_bytes: int
    retention_policy: str
    requires_manual_review: bool
    artifact_path: str
    artifact_kind: str
    artifact_profile: str
    redacted_config_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class WarcRecordSummary:
    ordinal: int
    record_type: str
    record_id: str
    record_key: str
    identity_source: str
    identity_strength: str
    duplicate_identity: bool
    target_uri_summary: str | None
    target_key: str | None
    target_uri_redacted: bool
    warc_date: str | None
    content_type: str | None
    payload_byte_length: int
    payload_sha256: str | None
    extractor_route: str | None
    materialized_path: str | None
    skip_reason: str | None
    safe_headers: Mapping[str, Any]
    duplicate_disambiguator: str | None = None

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "ordinal": self.ordinal,
            "record_type": self.record_type,
            "record_id": self.record_id,
            "record_key": self.record_key,
            "identity_source": self.identity_source,
            "identity_strength": self.identity_strength,
            "duplicate_identity": self.duplicate_identity,
            "duplicate_disambiguator": self.duplicate_disambiguator,
            "target_uri_summary": self.target_uri_summary,
            "target_key": self.target_key,
            "target_uri_redacted": self.target_uri_redacted,
            "warc_date": self.warc_date,
            "content_type": self.content_type,
            "payload_byte_length": self.payload_byte_length,
            "payload_sha256": self.payload_sha256,
            "extractor_route": self.extractor_route,
            "materialized_path": self.materialized_path,
            "skip_reason": self.skip_reason,
            "safe_headers": dict(self.safe_headers),
        }


@dataclass(frozen=True)
class WarcManifest:
    source_id: str
    source_type: str
    policy_status: str
    artifact_run_id: str
    artifact_manifest_id: str
    artifact_profile: str
    artifact_path: str
    warc_version: str | None
    records: tuple[WarcRecordSummary, ...]
    policy_snapshot: Mapping[str, Any]
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def record_count(self) -> int:
        return len(self.records)

    @property
    def parsed_record_count(self) -> int:
        return len(self.records)

    @property
    def skipped_record_count(self) -> int:
        return sum(
            1
            for record in self.records
            if record.skip_reason is not None
            and record.record_type
            not in {"warcinfo", "request", "revisit", "conversion"}
        )

    @property
    def routed_payload_count(self) -> int:
        return sum(1 for record in self.records if record.materialized_path is not None)

    @property
    def total_payload_bytes(self) -> int:
        return sum(record.payload_byte_length for record in self.records)

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_type": self.source_type,
            "policy_status": self.policy_status,
            "artifact_run_id": self.artifact_run_id,
            "artifact_manifest_id": self.artifact_manifest_id,
            "artifact_profile": self.artifact_profile,
            "artifact_path": self.artifact_path,
            "warc_version": self.warc_version,
            "record_count": self.record_count,
            "parsed_record_count": self.parsed_record_count,
            "skipped_record_count": self.skipped_record_count,
            "routed_payload_count": self.routed_payload_count,
            "total_payload_bytes": self.total_payload_bytes,
            "records": [record.to_jsonable() for record in self.records],
            "policy_snapshot": dict(self.policy_snapshot),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class WarcImportSummary:
    source_id: str
    source_type: str
    policy_status: str
    artifact_run_id: str
    artifact_manifest_id: str
    record_count: int
    parsed_records: int
    skipped_records: int
    routed_payloads: int
    observations: int
    raw_observations: tuple[RawObservation, ...]
    manifest: WarcManifest | None
    publication: NonPublicationResult

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_type": self.source_type,
            "policy_status": self.policy_status,
            "artifact_run_id": self.artifact_run_id,
            "artifact_manifest_id": self.artifact_manifest_id,
            "record_count": self.record_count,
            "parsed_records": self.parsed_records,
            "skipped_records": self.skipped_records,
            "routed_payloads": self.routed_payloads,
            "observations": self.observations,
            "publication": self.publication.to_jsonable(),
        }
