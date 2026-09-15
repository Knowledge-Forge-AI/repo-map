"""Record types for explicit-policy-gated bulk ingestion."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from repomap_kg.observations.raw import RawObservation
from repomap_kg.ops.ingestion.acquisition_contracts import NonPublicationResult


class BulkPolicyError(ValueError):
    """Raised when a bulk source config is not explicitly allowed and bounded."""


@dataclass(frozen=True)
class BulkSourceConfig:
    config_path: Path
    source_id: str
    source_type: str
    corpus_kind: str
    policy_status: str
    root_path_configured: str
    resolved_root: Path
    max_files: int
    max_total_bytes: int
    max_file_bytes: int
    max_depth: int
    follow_symlinks: bool
    include_hidden: bool
    include_extensions: tuple[str, ...]
    excluded_directories: tuple[str, ...]
    excluded_paths: tuple[str, ...]
    retention_policy: str | None
    redaction_profile: str | None
    sensitivity: str | None


@dataclass(frozen=True)
class BulkIncludedFile:
    relative_path: str
    repository_path: str
    route: str
    byte_count: int
    sha256: str
    skipped: bool = False

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "relative_path": self.relative_path,
            "repository_path": self.repository_path,
            "route": self.route,
            "byte_count": self.byte_count,
            "sha256": self.sha256,
            "skipped": self.skipped,
        }


@dataclass(frozen=True)
class BulkSkippedFile:
    relative_path: str
    reason: str
    byte_count: int | None = None
    route: str | None = None
    skipped: bool = True

    def to_jsonable(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "relative_path": self.relative_path,
            "reason": self.reason,
            "skipped": self.skipped,
        }
        if self.byte_count is not None:
            payload["byte_count"] = self.byte_count
        if self.route is not None:
            payload["route"] = self.route
        return payload


@dataclass(frozen=True)
class BulkManifest:
    source_id: str
    source_type: str
    corpus_kind: str
    policy_status: str
    root_path_summary: str
    bulk_run_id: str
    bulk_manifest_id: str
    included_files: tuple[BulkIncludedFile, ...]
    skipped_files: tuple[BulkSkippedFile, ...]
    total_bytes_seen: int
    total_bytes_included: int
    limit_hit: bool
    limit_reason: str | None
    extractor_counts: Mapping[str, int]
    diagnostic_counts: Mapping[str, int]
    redaction_counts: Mapping[str, int] = field(default_factory=dict)
    manifest_sha256: str = ""
    no_provider_api: bool = True
    no_external_fetch: bool = True
    no_source_mutation: bool = True
    no_archive_decompression: bool = True

    @property
    def file_count_seen(self) -> int:
        return len(self.included_files) + len(self.skipped_files)

    @property
    def file_count_included(self) -> int:
        return len(self.included_files)

    @property
    def file_count_skipped(self) -> int:
        return len(self.skipped_files)

    def to_jsonable(self) -> dict[str, Any]:
        payload = {
            "bulk_run_id": self.bulk_run_id,
            "bulk_manifest_id": self.bulk_manifest_id,
            "source_id": self.source_id,
            "source_type": self.source_type,
            "corpus_kind": self.corpus_kind,
            "policy_status": self.policy_status,
            "root_path_summary": self.root_path_summary,
            "file_count_seen": self.file_count_seen,
            "file_count_included": self.file_count_included,
            "file_count_skipped": self.file_count_skipped,
            "total_bytes_seen": self.total_bytes_seen,
            "total_bytes_included": self.total_bytes_included,
            "limit_hit": self.limit_hit,
            "limit_reason": self.limit_reason,
            "extractor_counts": dict(sorted(self.extractor_counts.items())),
            "diagnostic_counts": dict(sorted(self.diagnostic_counts.items())),
            "redaction_counts": dict(sorted(self.redaction_counts.items())),
            "manifest_sha256": self.manifest_sha256,
            "included_files": [item.to_jsonable() for item in self.included_files],
            "skipped_files": [item.to_jsonable() for item in self.skipped_files],
            "no_provider_api": self.no_provider_api,
            "no_external_fetch": self.no_external_fetch,
            "no_source_mutation": self.no_source_mutation,
            "no_archive_decompression": self.no_archive_decompression,
        }
        return payload


@dataclass(frozen=True)
class BulkImportSummary:
    source_id: str
    source_type: str
    corpus_kind: str
    policy_status: str
    bulk_run_id: str
    bulk_manifest_id: str
    observations: int
    raw_observations: tuple[RawObservation, ...]
    included_files: int
    skipped_files: int
    output_path: Path
    output_path_summary: str
    manifest: BulkManifest
    publication: NonPublicationResult

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_type": self.source_type,
            "corpus_kind": self.corpus_kind,
            "policy_status": self.policy_status,
            "bulk_run_id": self.bulk_run_id,
            "bulk_manifest_id": self.bulk_manifest_id,
            "observations": self.observations,
            "included_files": self.included_files,
            "skipped_files": self.skipped_files,
            "output_path": self.output_path_summary,
            "publication": self.publication.to_jsonable(),
            "manifest": self.manifest.to_jsonable(),
            "no_provider_api": True,
            "no_external_fetch": True,
            "no_source_mutation": True,
            "no_archive_decompression": True,
        }
