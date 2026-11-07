"""Shared canonicalization metadata helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _append_metadata_text(
    summary: dict[str, Any],
    metadata: Mapping[str, Any],
    source_key: str,
    summary_key: str,
) -> None:
    value = _metadata_text(metadata, source_key)
    if value is not None:
        summary[summary_key] = [value]


def _metadata_text(metadata: Mapping[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return None
