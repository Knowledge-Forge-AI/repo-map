"""Neutral reference records for structured configuration extraction."""

from __future__ import annotations

from typing import Any

from repomap_kg.extractors.config.generic_values import (
    _is_dynamic_value,
    _normalize_repo_path,
    _resolve_repo_path,
    _safe_value_summary,
)
from repomap_kg.graph.keys import dynamic_key, external_key, file_key, unknown_key


def _reference(
    kind: str,
    target: str,
    reason: str,
    raw_value: Any,
    *,
    redacted: bool,
) -> dict[str, Any]:
    reference = {
        "kind": kind,
        "target": target,
        "reason": reason,
        "redacted": redacted,
    }
    if not redacted:
        summary = _safe_value_summary(raw_value)
        if summary is not None:
            reference["summary"] = summary
    return reference


def _file_reference(
    relative_path: str,
    value: str,
    *,
    redacted: bool,
) -> dict[str, Any]:
    if _is_dynamic_value(value):
        return _reference(
            "dynamic",
            dynamic_key("file", "config-reference-expanded-from-variable"),
            "dynamic-file-reference",
            value,
            redacted=redacted,
        )
    if value.startswith("/"):
        return _reference(
            "external",
            external_key("file", "absolute-config-reference"),
            "absolute-file-reference",
            value,
            redacted=redacted,
        )
    if value.startswith("../"):
        resolved = _resolve_repo_path(relative_path, value)
        if resolved is None:
            return _reference(
                "unknown",
                unknown_key("file", "repo-escaping-config-reference"),
                "repo-escaping-file-reference",
                value,
                redacted=redacted,
            )
        return _reference(
            "file",
            file_key(resolved),
            "relative-file-reference",
            value,
            redacted=redacted,
        )
    resolved = (
        _resolve_repo_path(relative_path, value)
        if value.startswith("./")
        else _normalize_repo_path(value)
    )
    if resolved is None:
        return _reference(
            "unknown",
            unknown_key("file", "repo-escaping-config-reference"),
            "repo-escaping-file-reference",
            value,
            redacted=redacted,
        )
    return _reference(
        "file",
        file_key(resolved),
        "relative-file-reference",
        value,
        redacted=redacted,
    )
