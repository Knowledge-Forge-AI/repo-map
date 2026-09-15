"""Record models and constants for archive-source ingestion."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from repomap_kg.observations.raw import RawObservation
from repomap_kg.ops.ingestion.acquisition_contracts import NonPublicationResult

JAVASCRIPT_ARCHIVE_EXTENSIONS = frozenset(
    {".js", ".mjs", ".cjs", ".jsx", ".ts", ".mts", ".cts", ".tsx"}
)
ARCHIVE_EXCLUDED_DIR_NAMES = frozenset(
    {
        ".git",
        ".gnupg",
        ".hg",
        ".mail",
        ".mypy_cache",
        ".password-store",
        ".pytest_cache",
        ".ruff_cache",
        ".ssh",
        ".svn",
        "__pycache__",
        "build",
        "cache",
        "Caches",
        "dist",
        "Mail",
        "mail",
        "node_modules",
        "tmp",
        "temp",
    }
)


@dataclass(frozen=True)
class ArchiveSourceConfig:
    source_id: str
    source_type: str
    display_name: str | None
    policy_status: str
    max_artifact_bytes: int
    max_file_count: int
    max_depth: int
    symlink_policy: str
    hidden_files: bool
    retention_policy: str
    requires_manual_review: bool
    artifact_path: str
    artifact_kind: str
    artifact_profile: str
    entry_document: str | None
    redacted_config_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class ArchiveIncludedFile:
    relative_path: str
    repository_path: str
    byte_length: int
    sha256: str
    extractor_route: str
    media_type: str

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "relative_path": self.relative_path,
            "repository_path": self.repository_path,
            "byte_length": self.byte_length,
            "sha256": self.sha256,
            "extractor_route": self.extractor_route,
            "media_type": self.media_type,
        }


@dataclass(frozen=True)
class ArchiveSkippedFile:
    relative_path: str
    reason: str

    def to_jsonable(self) -> dict[str, Any]:
        return {"relative_path": self.relative_path, "reason": self.reason}


@dataclass(frozen=True)
class ArchiveManifest:
    source_id: str
    source_type: str
    policy_status: str
    artifact_run_id: str
    artifact_manifest_id: str
    artifact_profile: str
    artifact_root: str
    entry_document: str | None
    included_files: tuple[ArchiveIncludedFile, ...]
    skipped_files: tuple[ArchiveSkippedFile, ...]
    policy_snapshot: Mapping[str, Any]
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def file_count(self) -> int:
        return len(self.included_files)

    @property
    def total_byte_count(self) -> int:
        return sum(item.byte_length for item in self.included_files)

    @property
    def skipped_file_count(self) -> int:
        return len(self.skipped_files)

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_type": self.source_type,
            "policy_status": self.policy_status,
            "artifact_run_id": self.artifact_run_id,
            "artifact_manifest_id": self.artifact_manifest_id,
            "artifact_profile": self.artifact_profile,
            "artifact_root": self.artifact_root,
            "entry_document": self.entry_document,
            "file_count": self.file_count,
            "total_byte_count": self.total_byte_count,
            "skipped_file_count": self.skipped_file_count,
            "included_files": [
                item.to_jsonable() for item in self.included_files
            ],
            "skipped_files": [item.to_jsonable() for item in self.skipped_files],
            "policy_snapshot": dict(self.policy_snapshot),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class ArchiveImportSummary:
    source_id: str
    source_type: str
    policy_status: str
    artifact_run_id: str
    artifact_manifest_id: str
    included_files: int
    skipped_files: int
    observations: int
    raw_observations: tuple[RawObservation, ...]
    manifest: ArchiveManifest
    publication: NonPublicationResult

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_type": self.source_type,
            "policy_status": self.policy_status,
            "artifact_run_id": self.artifact_run_id,
            "artifact_manifest_id": self.artifact_manifest_id,
            "included_files": self.included_files,
            "skipped_files": self.skipped_files,
            "observations": self.observations,
            "publication": self.publication.to_jsonable(),
        }
