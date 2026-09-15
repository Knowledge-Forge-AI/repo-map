"""Neutral records shared by discovery and extractor routing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from repomap_kg import __version__
from repomap_kg.observations.raw import RawObservation

__all__ = ["FileInfo"]


@dataclass(frozen=True)
class FileInfo:
    path: str
    language: str
    role: str
    content_hash: str
    executable: bool
    generated: bool
    confidence: str = "extracted"

    def to_observation(self) -> RawObservation:
        return RawObservation(
            kind="file",
            source_id=self.path,
            path=self.path,
            name=self.path,
            confidence=self.confidence,
            extractor="repo-discovery",
            extractor_version=__version__,
            metadata=self.to_metadata(),
        )

    def to_metadata(self) -> dict[str, Any]:
        return {
            "language": self.language,
            "role": self.role,
            "content_hash": self.content_hash,
            "executable": self.executable,
            "generated": self.generated,
        }
