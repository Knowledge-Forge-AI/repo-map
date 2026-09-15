"""Observation construction helpers for JavaScript extraction."""

from __future__ import annotations

import re
from typing import Any

from repomap_kg import __version__
from repomap_kg.graph.keys import js_component_key
from repomap_kg.observations.raw import RawObservation
from repomap_kg.extractors.languages.javascript_references import (
    _package_name,
    _safe_summary,
    _sanitize_url,
)


EXTRACTOR = "repo-js"
PARSER = "stdlib-js-lexical"
FRAMEWORK_SPECIFIER_PREFIXES = (
    "express",
    "@nestjs/",
    "next",
    "next/",
    "@jest/",
    "jest",
    "jquery",
)


def _framework_observation(
    kind: str,
    relative_path: str,
    js_format: str,
    profile: str,
    line_number: int,
    name: str,
    source_key: str,
    *,
    metadata: dict[str, Any],
    target: str | None = None,
) -> RawObservation:
    payload = {
        "format": js_format,
        "profile": profile,
        "profiles": [profile],
        "parser": PARSER,
        "source_key": source_key,
        "raw_profile_observation": True,
    }
    payload.update(metadata)
    return _observation(
        kind=kind,
        relative_path=relative_path,
        source_id=(
            f"{relative_path}#{kind}:{line_number}:"
            f"{_source_id_fragment(name)}"
        ),
        start_line=line_number,
        name=_safe_summary(name),
        target=target,
        metadata=payload,
    )


def _framework_specifier_observation(
    relative_path: str,
    js_format: str,
    profile: str,
    line_number: int,
    specifier: str,
    source_key: str,
) -> RawObservation | None:
    if not _is_framework_specifier(specifier):
        return None
    return _framework_observation(
        "js.framework_reference",
        relative_path,
        js_format,
        profile,
        line_number,
        specifier,
        source_key,
        metadata={
            "reference_kind": "framework-package",
            "specifier": _safe_summary(_sanitize_url(specifier)),
            "package_name": _package_name(specifier),
            "not_loaded": True,
            "not_fetched": True,
        },
    )


def _is_framework_specifier(specifier: str) -> bool:
    return specifier == "express" or specifier == "jquery" or any(
        specifier.startswith(prefix) for prefix in FRAMEWORK_SPECIFIER_PREFIXES
    )


def _source_id_fragment(value: str) -> str:
    fragment = re.sub(r"[^A-Za-z0-9_.:-]+", "-", value)
    return fragment[:80] or "item"


def _observation(
    *,
    kind: str,
    relative_path: str,
    source_id: str,
    metadata: dict[str, Any],
    confidence: str = "extracted",
    start_line: int | None = None,
    name: str | None = None,
    target: str | None = None,
) -> RawObservation:
    return RawObservation(
        kind=kind,
        source_id=source_id,
        path=relative_path,
        confidence=confidence,
        extractor=EXTRACTOR,
        extractor_version=__version__,
        start_line=start_line,
        end_line=start_line,
        name=name,
        target=target,
        metadata={key: value for key, value in metadata.items() if value is not None},
    )


def _definition_observation(
    kind: str,
    relative_path: str,
    js_format: str,
    profile: str,
    line_number: int,
    name: str,
    target: str,
    *,
    source_key: str,
    metadata: dict[str, Any],
) -> RawObservation:
    payload = {
        "format": js_format,
        "profile": profile,
        "profiles": [profile],
        "parser": PARSER,
        "source_key": source_key,
        "identity_strength": "symbolic",
    }
    payload.update(metadata)
    return _observation(
        kind=kind,
        relative_path=relative_path,
        source_id=f"{relative_path}#{kind}:{name}:{line_number}",
        start_line=line_number,
        name=name,
        target=target,
        metadata=payload,
    )


def _reference_observation(
    relative_path: str,
    js_format: str,
    profile: str,
    line_number: int,
    reference_kind: str,
    raw_value: str,
    target: str,
    source_key: str,
    *,
    resolution_reason: str,
    dynamic: bool = False,
    extra_metadata: dict[str, Any] | None = None,
) -> RawObservation:
    metadata: dict[str, Any] = {
        "format": js_format,
        "profile": profile,
        "profiles": [profile],
        "parser": PARSER,
        "reference_kind": reference_kind,
        "raw_value_summary": _safe_summary(_sanitize_url(raw_value)),
        "source_key": source_key,
        "target_key": target,
        "resolution_reason": resolution_reason,
        "not_fetched": True,
        "dynamic": dynamic,
        "dynamic_reason": "dynamic-import" if dynamic else None,
    }
    if extra_metadata:
        metadata.update(extra_metadata)
    return _observation(
        kind="js.reference",
        relative_path=relative_path,
        source_id=(
            f"{relative_path}#js-reference:"
            f"{reference_kind}:{line_number}:{len(raw_value)}"
        ),
        start_line=line_number,
        name=reference_kind,
        target=target,
        metadata=metadata,
    )


def _component_observation(
    relative_path: str,
    js_format: str,
    profile: str,
    line_number: int,
    component_name: str,
    source_key: str,
) -> RawObservation:
    return _definition_observation(
        "js.component",
        relative_path,
        js_format,
        profile,
        line_number,
        component_name,
        js_component_key(relative_path, component_name),
        source_key=source_key,
        metadata={"component_name": component_name, "qualified_name": component_name},
    )


def _hook_observation(
    relative_path: str,
    js_format: str,
    profile: str,
    line_number: int,
    hook_name: str,
    source_key: str,
) -> RawObservation:
    return _observation(
        kind="js.hook",
        relative_path=relative_path,
        source_id=f"{relative_path}#js-hook:{hook_name}:{line_number}",
        start_line=line_number,
        name=hook_name,
        metadata={
            "format": js_format,
            "profile": profile,
            "parser": PARSER,
            "hook_name": hook_name,
            "source_key": source_key,
        },
    )


def _diagnostic_observation(
    relative_path: str,
    js_format: str,
    profile: str,
    line_number: int,
    diagnostic_kind: str,
    name: str,
    *,
    redacted: bool,
) -> RawObservation:
    return _observation(
        kind="js.parse_error",
        relative_path=relative_path,
        source_id=f"{relative_path}#js-diagnostic:{diagnostic_kind}:{line_number}",
        confidence="unknown",
        start_line=line_number,
        name=diagnostic_kind,
        metadata={
            "format": js_format,
            "profile": profile,
            "parser": PARSER,
            "error_kind": diagnostic_kind,
            "dynamic": True,
            "dynamic_reason": "environment",
            "redacted": redacted,
            "redaction_reason": "secret-prone-env-name" if redacted else None,
            "recovered": True,
        },
    )


def _parse_error(
    relative_path: str,
    js_format: str,
    profile: str,
    error_kind: str,
    message: str,
    line_number: int,
    *,
    dynamic_reason: str | None = None,
) -> RawObservation:
    return _observation(
        kind="js.parse_error",
        relative_path=relative_path,
        source_id=f"{relative_path}#js-parse-error:{line_number}:{error_kind}",
        confidence="unknown",
        start_line=line_number,
        name=error_kind,
        metadata={
            "format": js_format,
            "profile": profile,
            "parser": PARSER,
            "error_kind": error_kind,
            "message_summary": message,
            "dynamic": dynamic_reason is not None,
            "dynamic_reason": dynamic_reason,
            "recovered": True,
        },
    )
