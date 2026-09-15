"""Python web raw observation constructors."""

from __future__ import annotations

import ast
from typing import Any

from repomap_kg import __version__
from repomap_kg.extractors.languages.python_common import (
    EXTRACTOR_NAME,
    end_line,
    slug,
)
from repomap_kg.extractors.languages.python_web_helpers import (
    _bounded_metadata_string,
    _line_slug,
)
from repomap_kg.observations.raw import RawObservation


def python_web_profile_observation(
    kind: str,
    relative_path: str,
    module: str,
    node: ast.AST,
    *,
    name: str,
    metadata: dict[str, Any],
    target: str | None = None,
    confidence: str = "extracted",
) -> RawObservation:
    return RawObservation(
        kind=kind,
        source_id=f"{relative_path}#{kind.replace('.', '-')}:{_line_slug(node)}:{slug(name)}",
        path=relative_path,
        start_line=getattr(node, "lineno", None),
        end_line=end_line(node) if hasattr(node, "lineno") else None,
        name=name,
        target=target,
        confidence=confidence,
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata={
            "profile": "python",
            "source_format": "python-ast",
            "module": module,
            "raw_profile_only": True,
            "not_executed": True,
            "not_fetched": True,
            **metadata,
        },
    )


def python_web_reference_observation(
    relative_path: str,
    module: str,
    node: ast.AST,
    *,
    name: str,
    target: str,
    framework: str,
    reference_kind: str,
    metadata: dict[str, Any] | None = None,
) -> RawObservation:
    payload = {
        "profile": "python",
        "source_format": "python-ast",
        "module": module,
        "framework": framework,
        "reference_kind": reference_kind,
        "not_executed": True,
        "not_fetched": True,
        "raw_profile_only": True,
    }
    if metadata:
        payload.update(metadata)
    return RawObservation(
        kind="python.reference",
        source_id=(
            f"{relative_path}#python-reference:{_line_slug(node)}:"
            f"{slug(reference_kind)}:{slug(name)}"
        ),
        path=relative_path,
        start_line=getattr(node, "lineno", None),
        end_line=end_line(node) if hasattr(node, "lineno") else None,
        name=name,
        target=target,
        confidence="extracted",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=payload,
    )


def python_web_parse_error_observation(
    relative_path: str,
    module: str,
    node: ast.AST | RawObservation,
    *,
    error_kind: str,
    framework: str,
    message_summary: str,
    recovered: bool,
    dynamic: bool = False,
) -> RawObservation:
    line_number = getattr(node, "lineno", None)
    if isinstance(node, RawObservation):
        line_number = node.start_line
    return RawObservation(
        kind="python.parse_error",
        source_id=(
            f"{relative_path}#python-web-diagnostic:{line_number or 'module'}:"
            f"{slug(error_kind)}"
        ),
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=module,
        confidence="unknown",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata={
            "profile": "python",
            "source_format": "python-ast",
            "framework": framework,
            "error_kind": error_kind,
            "message_summary": _bounded_metadata_string(message_summary),
            "dynamic": dynamic,
            "recovered": recovered,
            "raw_profile_only": True,
            "not_executed": True,
            "not_fetched": True,
        },
    )


def python_web_redaction_observation(
    relative_path: str,
    module: str,
    node: ast.AST,
    *,
    framework: str,
    name: str,
    redaction_reason: str,
    field_name: str | None = None,
) -> RawObservation:
    metadata: dict[str, Any] = {
        "profile": "python",
        "source_format": "python-ast",
        "module": module,
        "framework": framework,
        "redacted": True,
        "redaction_reason": redaction_reason,
        "raw_profile_only": True,
        "not_executed": True,
        "not_fetched": True,
    }
    if field_name is not None:
        metadata["field_name"] = _bounded_metadata_string(field_name)
    return RawObservation(
        kind="python.redaction",
        source_id=(
            f"{relative_path}#python-redaction:{_line_slug(node)}:"
            f"{slug(framework)}:{slug(name)}"
        ),
        path=relative_path,
        start_line=getattr(node, "lineno", None),
        end_line=end_line(node) if hasattr(node, "lineno") else None,
        name=_bounded_metadata_string(name),
        confidence="extracted",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
    )
