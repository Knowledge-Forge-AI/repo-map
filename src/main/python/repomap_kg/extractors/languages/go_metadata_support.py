"""Observation and target helpers for static Go metadata extraction."""

from __future__ import annotations

import posixpath
from pathlib import PurePosixPath
from urllib.parse import quote

from repomap_kg.observations.raw import RawObservation


EXTRACTOR = "repo-go-metadata"
EXTRACTOR_VERSION = "0.1.0"


def observation(
    path: str,
    kind: str,
    line: int,
    ordinal: int,
    *,
    name: str | None,
    metadata: dict[str, object],
    target: str | None = None,
    confidence: str = "extracted",
) -> RawObservation:
    return RawObservation(
        kind=kind,
        source_id=f"{path}#{kind}:{line}:{ordinal}",
        path=path,
        confidence=confidence,
        extractor=EXTRACTOR,
        extractor_version=EXTRACTOR_VERSION,
        start_line=line,
        end_line=line,
        name=name,
        target=target,
        metadata=metadata,
    )


def module_target(module: str, version: str | None) -> str:
    encoded_module = quote(module, safe="")
    encoded_version = quote(version or "unspecified", safe="")
    return f"go.module-ref:{encoded_module}@{encoded_version}"


def local_target(document_path: str, value: str) -> str:
    base = PurePosixPath(document_path).parent.as_posix()
    normalized = posixpath.normpath(posixpath.join(base, value))
    if normalized == ".." or normalized.startswith("../") or value.startswith("/"):
        return "external-path:<redacted>"
    return f"file:{normalized}"


def require_fields(directive: str, fields: tuple[str, ...], count: int) -> None:
    if len(fields) != count:
        raise ValueError(f"{directive} requires {count} field(s)")


def retract_bounds(value: str) -> tuple[str, str]:
    stripped = value.strip()
    if stripped.startswith("[") and stripped.endswith("]") and "," in stripped:
        low, high = stripped[1:-1].split(",", 1)
        return low.strip(), high.strip()
    return stripped, stripped
