"""Shared RawObservation builders for static extractors."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from repomap_kg.observations.raw import RawObservation


def secret_like_observation(
    *,
    relative_path: str,
    line_number: int,
    name: str,
    secret_source: str,
    reason: str,
    source_prefix: str,
    extractor: str,
    extractor_version: str,
    metadata_builder: Callable[[dict[str, Any]], Mapping[str, Any]],
    slugger: Callable[[str], str],
) -> RawObservation:
    """Build a shell.secret_like observation without storing the raw value."""
    return RawObservation(
        kind="shell.secret_like",
        source_id=(
            f"{relative_path}#{source_prefix}-secret:"
            f"{line_number}:{slugger(secret_source + '-' + name)}"
        ),
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=name,
        confidence="heuristic",
        extractor=extractor,
        extractor_version=extractor_version,
        metadata=metadata_builder(
            {
                "secret_source": secret_source,
                "redacted": True,
                "redaction_reason": reason,
                "raw_value_stored": False,
            }
        ),
    )
