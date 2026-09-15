"""Reference observation support for conservative XML extraction."""

from __future__ import annotations

import re
from typing import Any

from repomap_kg import __version__
from repomap_kg.graph.keys import (
    dynamic_key,
    env_key,
    external_key,
    external_url_key,
    file_key,
    unknown_key,
)
from repomap_kg.observations.raw import RawObservation


def _generic_helper(name: str) -> Any:
    from repomap_kg.extractors.config import generic_contracts as generic

    return getattr(generic, name)


def _extractor_name() -> str:
    return _generic_helper("EXTRACTOR_NAME")


def _generic_xml_format() -> str:
    return _generic_helper("GENERIC_XML_FORMAT")


def _generic_xml_safety_mode() -> str:
    return _generic_helper("GENERIC_XML_SAFETY_MODE")


def _parser_name(format_name: str) -> str:
    return _generic_helper("_parser_name")(format_name)


def _normalized_key(value: str) -> str:
    return _generic_helper("_normalized_key")(value)


def _is_url(value: str) -> bool:
    return _generic_helper("_is_url")(value)


def _is_dynamic_value(value: str) -> bool:
    return _generic_helper("_is_dynamic_value")(value)


def _resolve_repo_path(relative_path: str, value: str) -> str | None:
    return _generic_helper("_resolve_repo_path")(relative_path, value)


def _normalize_repo_path(value: str) -> str | None:
    return _generic_helper("_normalize_repo_path")(value)


def _reference(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return _generic_helper("_reference")(*args, **kwargs)


def _xml_reference_observations(
    relative_path: str,
    *,
    value: str,
    key_context: str,
    source_key: str,
    source_kind: str,
    pointer: str,
    attribute_name: str | None,
    redacted: bool,
) -> tuple[RawObservation, ...]:
    references = _detect_xml_references(
        relative_path,
        key_context,
        value,
        redacted=redacted,
    )
    observations = []
    for ordinal, reference in enumerate(references):
        metadata: dict[str, Any] = {
            "format": _generic_xml_format(),
            "parser": _parser_name(_generic_xml_format()),
            "safety_mode": _generic_xml_safety_mode(),
            "source_key": source_key,
            "source_kind": source_kind,
            "element_pointer": pointer,
            "reference_kind": reference["kind"],
            "redacted": reference["redacted"],
            "resolution_reason": reference["reason"],
        }
        if attribute_name is not None:
            metadata["attribute_name"] = attribute_name
        if "summary" in reference:
            metadata["raw_value_summary"] = reference["summary"]
        if reference["redacted"]:
            metadata["redaction_reason"] = "secret-prone-key"
        observations.append(
            RawObservation(
                kind="xml.reference",
                source_id=(
                    f"{relative_path}#xml-reference:{pointer}:"
                    f"{attribute_name or 'text'}:{ordinal}"
                ),
                path=relative_path,
                name=pointer,
                target=reference["target"],
                confidence="heuristic",
                extractor=_extractor_name(),
                extractor_version=__version__,
                metadata=metadata,
            )
        )
    return tuple(observations)


def _detect_xml_references(
    relative_path: str,
    key_context: str,
    value: str,
    *,
    redacted: bool,
) -> tuple[dict[str, Any], ...]:
    stripped = value.strip()
    if not stripped:
        return ()
    references = []
    for token in stripped.split():
        if _is_url(token):
            references.append(
                _reference(
                    "external.url",
                    external_url_key(token),
                    "url-literal",
                    token,
                    redacted=redacted,
                )
            )
    if references:
        return tuple(references)
    env_placeholder = re.fullmatch(r"\$\{env\.([A-Za-z_][A-Za-z0-9_]*)\}", stripped)
    if env_placeholder is not None:
        return (
            _reference(
                "env",
                env_key(env_placeholder.group(1)),
                "env-property-placeholder",
                stripped,
                redacted=redacted,
            ),
        )
    if re.fullmatch(r"\$\{[^}]+\}", stripped):
        return (
            _reference(
                "dynamic",
                dynamic_key("xml.property-placeholder", "spring-maven-property"),
                "dynamic-property-placeholder",
                stripped,
                redacted=redacted,
            ),
        )
    normalized_context = _normalized_key(key_context)
    if _looks_like_xml_file_key(normalized_context, stripped):
        return (_xml_file_reference(relative_path, stripped, redacted=redacted),)
    return ()


def _looks_like_xml_file_key(key_context: str, value: str) -> bool:
    if _is_url(value):
        return False
    if value.startswith(("./", "../", "/", "${", "~")):
        return True
    markers = ("path", "file", "resource", "location", "config", "directory")
    return "/" in value and any(marker in key_context for marker in markers)


def _xml_file_reference(
    relative_path: str,
    value: str,
    *,
    redacted: bool,
) -> dict[str, Any]:
    if _is_dynamic_value(value):
        return _reference(
            "dynamic",
            dynamic_key("file", "xml-reference-expanded-from-variable"),
            "dynamic-file-reference",
            value,
            redacted=redacted,
        )
    if value.startswith("/"):
        return _reference(
            "external",
            external_key("file", "absolute-xml-reference"),
            "absolute-file-reference",
            value,
            redacted=redacted,
        )
    if value.startswith("../"):
        resolved = _resolve_repo_path(relative_path, value)
        if resolved is None:
            return _reference(
                "unknown",
                unknown_key("file", "repo-escaping-xml-reference"),
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
    if value.startswith("./"):
        resolved = _resolve_repo_path(relative_path, value)
    else:
        resolved = _normalize_repo_path(value)
    if resolved is None:
        return _reference(
            "unknown",
            unknown_key("file", "repo-escaping-xml-reference"),
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
