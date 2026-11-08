"""Portable refresh records, re-exported unchanged by ``ops.portable_refresh``."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from common_lore_index.artifacts import ArtifactReference, FileSystemArtifactStore, PortableSnapshotManifest
from common_lore_index.ops._portable_retention import _annotate_retained_attempt, _mark_retained_terminal
from common_lore_index.ops.config_records import OpsGraphConfig
from common_lore_index.storage._staged_ingestion_authority import IngestionAuthority
from common_lore_index.storage.main import LoadSummary


@dataclass(frozen=True)
class PortableRefreshOutcome:
    summary: LoadSummary
    files: int
    observations: int


@dataclass(frozen=True)
class PortableCapture:
    """One sealed, executed portable candidate awaiting parent validation."""

    graph: OpsGraphConfig
    store: FileSystemArtifactStore
    manifest: PortableSnapshotManifest
    candidate_id: str
    authority: IngestionAuthority
    result_path: Path
    workspace_root: Path
    receipt_reference: ArtifactReference
    bundle_reference: ArtifactReference

    def mark_terminal(self, *, accepted: bool, sync_directory: bool = False) -> None:
        _mark_retained_terminal(
            self.result_path,
            "terminal-accepted" if accepted else "terminal-failed",
            sync_directory=sync_directory,
        )

    def annotate(
        self, key: str, value: Mapping[str, object], *, sync_directory: bool = False
    ) -> None:
        _annotate_retained_attempt(self.result_path, key, value, sync_directory=sync_directory)


__all__ = ("PortableCapture", "PortableRefreshOutcome")
