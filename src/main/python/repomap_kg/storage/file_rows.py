"""First-class file/source index write rows."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from repomap_kg.observations.raw import RawObservation
from repomap_kg.storage.row_helpers import metadata_bool, metadata_text, optional_text

__all__ = ("FileRow", "file_rows_from_observations")


@dataclass(frozen=True)
class FileRow:
    path: str
    language: str
    role: str
    confidence: str
    content_hash: str | None
    executable: bool
    generated: bool
    metadata_json: dict[str, Any]


def file_rows_from_observations(
    observations: Iterable[RawObservation],
) -> tuple[FileRow, ...]:
    rows = []
    for observation in observations:
        if observation.kind != "file":
            continue
        metadata = dict(observation.metadata)
        rows.append(
            FileRow(
                path=observation.path,
                language=metadata_text(metadata, "language", "unknown"),
                role=metadata_text(metadata, "role", "unknown"),
                confidence=observation.confidence,
                content_hash=optional_text(metadata.get("content_hash")),
                executable=metadata_bool(metadata, "executable"),
                generated=metadata_bool(metadata, "generated"),
                metadata_json={
                    "raw_source_id": observation.source_id,
                    "confidence": observation.confidence,
                    "extractor": observation.extractor,
                    "extractor_version": observation.extractor_version,
                    "source_metadata": metadata,
                },
            )
        )
    return tuple(sorted(rows, key=lambda row: row.path))
