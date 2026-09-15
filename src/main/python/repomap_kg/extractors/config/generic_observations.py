"""Observation construction helpers for structured configuration extractors."""

from __future__ import annotations

from typing import Any

from repomap_kg import __version__
from repomap_kg.extractors.config.format_contracts import (
    PLIST_XML_FORMAT,
    PLIST_XML_SAFETY_MODE,
)
from repomap_kg.extractors.config.generic_profile_helpers import EXTRACTOR_NAME
from repomap_kg.extractors.config.generic_structure import _parser_name
from repomap_kg.extractors.config.generic_values import (
    _document_role,
    _is_secret_key,
    _safe_value_summary,
    _value_type,
)
from repomap_kg.graph.keys import config_document_key
from repomap_kg.observations.raw import RawObservation


def _document_observation(
    relative_path: str,
    *,
    format_name: str,
    parser: str,
    confidence: str,
    top_level_type: str,
    path_count: int,
    record_count: int | None,
    parse_error_count: int,
    extra_metadata: dict[str, Any] | None = None,
) -> RawObservation:
    metadata: dict[str, Any] = {
        "format": format_name,
        "parser": parser,
        "top_level_type": top_level_type,
        "document_role": _document_role(relative_path),
        "path_count": path_count,
        "parse_error_count": parse_error_count,
    }
    if format_name == PLIST_XML_FORMAT:
        metadata["safety_mode"] = PLIST_XML_SAFETY_MODE
    if record_count is not None:
        metadata["record_count"] = record_count
    if extra_metadata:
        metadata.update(extra_metadata)
    return RawObservation(
        kind="config.document",
        source_id=f"{relative_path}#config-document",
        path=relative_path,
        target=config_document_key(relative_path),
        confidence=confidence,
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
    )


def _jsonl_record_observation(
    relative_path: str,
    value: Any,
    *,
    line_number: int,
    record_index: int,
) -> RawObservation:
    metadata = {
        "format": "jsonl",
        "record_index": record_index,
        "line_number": line_number,
        "top_level_type": _value_type(value),
    }
    if isinstance(value, dict):
        safe_keys = []
        redacted_keys = []
        for key in sorted(str(item) for item in value):
            if _is_secret_key(key):
                redacted_keys.append(key)
            else:
                safe_keys.append(key)
        metadata["safe_keys"] = safe_keys
        metadata["redacted_keys"] = redacted_keys
    else:
        summary = _safe_value_summary(value)
        if summary is not None:
            metadata["value_summary"] = summary
    return RawObservation(
        kind="config.jsonl_record",
        source_id=f"{relative_path}#jsonl-record:{line_number}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        confidence="extracted",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
    )


def _parse_error_observation(
    relative_path: str,
    *,
    format_name: str,
    error_kind: str,
    error: Any | None = None,
    message: str | None = None,
    start_line: int | None = None,
    recovered: bool,
) -> RawObservation:
    line_number = start_line or (error.lineno if error is not None else None)
    metadata: dict[str, Any] = {
        "format": format_name,
        "parser": _parser_name(format_name),
        "error_kind": error_kind,
        "message_summary": _safe_error_message(error, message),
        "recovered": recovered,
    }
    if line_number is not None:
        metadata["line_number"] = line_number
    column_number = getattr(error, "colno", None)
    if column_number is not None:
        metadata["column_number"] = column_number
    return RawObservation(
        kind="config.parse_error",
        source_id=f"{relative_path}#config-parse-error:{line_number or 'document'}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        confidence="unknown",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
    )


def _safe_error_message(
    error: Any | None,
    message: str | None,
) -> str:
    if message is not None:
        summary = message
    elif error is not None:
        summary = getattr(error, "msg", str(error))
    else:
        summary = "parse error"
    return summary[:120]
