"""Shared structured-config profile observation helpers."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from urllib.parse import urlsplit

from repomap_kg import __version__
from repomap_kg.extractors.config.generic_values import (
    _is_secret_key,
    _safe_value_summary,
    _value_type,
)
from repomap_kg.observations.raw import RawObservation


EXTRACTOR_NAME = "repo-config"


def _profile_observation(
    kind: str,
    relative_path: str,
    *,
    profile: str,
    format_name: str,
    confidence: str,
    metadata: dict[str, Any],
    name: str | None = None,
    target: str | None = None,
    source_suffix: str | None = None,
) -> RawObservation:
    full_metadata = {
        "format": format_name,
        "profile": profile,
        **metadata,
    }
    source_segment = source_suffix or kind.replace(".", "-")
    return RawObservation(
        kind=kind,
        source_id=f"{relative_path}#{source_segment}",
        path=relative_path,
        name=name,
        target=target,
        confidence=confidence,
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=full_metadata,
    )


def _url_has_credentials(value: str) -> bool:
    parsed = urlsplit(value)
    return parsed.username is not None or parsed.password is not None


def _stable_text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _stable_value_sha256(value: Any) -> str:
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
    except TypeError:
        encoded = repr(value)
    return _stable_text_sha256(encoded)


def _safe_selected_metadata(
    value: dict[str, Any],
    keys: tuple[str, ...],
) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key in keys:
        item = value.get(key)
        if _is_secret_key(key):
            metadata[f"{key}_redacted"] = True
            continue
        summary = _safe_value_summary(item)
        if summary is not None:
            metadata[key] = summary
        elif isinstance(item, (dict, list)):
            metadata[f"{key}_type"] = _value_type(item)
            metadata[f"{key}_shape"] = _value_shape(item)
    return metadata


def _value_shape(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {"type": "object", "key_count": len(value)}
    if isinstance(value, list):
        return {"type": "array", "item_count": len(value)}
    return {"type": _value_type(value)}
