"""Structured config path and reference observation helpers."""

from __future__ import annotations

import re
from typing import Any

from repomap_kg import __version__
from repomap_kg.extractors.config.generic_profile_helpers import EXTRACTOR_NAME
from repomap_kg.extractors.config.format_contracts import (
    GENERIC_XML_FORMAT,
    PLIST_XML_FORMAT,
    PLIST_XML_SAFETY_MODE,
    YAML_FORMAT,
    YAML_PARSER,
)
from repomap_kg.extractors.config.generic_reference_contracts import (
    _file_reference,
    _reference,
)
from repomap_kg.extractors.config.generic_values import (
    _is_dynamic_value,
    _is_secret_pointer,
    _is_url,
    _looks_like_file_key,
    _normalized_key,
    _safe_value_summary,
    _stable_array_members,
    _value_type,
)
from repomap_kg.extractors.config.paths import json_pointer
from repomap_kg.extractors.config.toml_lines import _line_for_toml_pointer
from repomap_kg.extractors.config.yaml_reference_contracts import (
    _yaml_string_references,
)
from repomap_kg.graph.keys import (
    config_document_key,
    config_path_key,
    dynamic_key,
    env_key,
    external_url_key,
    tool_key,
    unknown_key,
)
from repomap_kg.observations.raw import RawObservation


ENV_CONTAINER_KEYS = frozenset(("env", "environment", "env_vars"))
TOOL_KEYS = frozenset(("command", "cmd", "executable", "program"))
SIMPLE_COMMAND_PATTERN = re.compile(r"^[0-9A-Za-z_.+-]+$")
ENV_REFERENCE_PATTERN = re.compile(r"^\$(?P<brace>\{?)(?P<name>[A-Za-z_][A-Za-z0-9_]*)\}?$")
ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _structure_observations(
    relative_path: str,
    value: Any,
    *,
    format_name: str,
    confidence: str,
    content: str,
    source_suffix: str = "",
    line_offset: int = 0,
    metadata_overrides: dict[str, dict[str, Any]] | None = None,
) -> tuple[tuple[RawObservation, ...], tuple[RawObservation, ...]]:
    paths: list[RawObservation] = []
    references: list[RawObservation] = []
    _walk_value(
        relative_path,
        value,
        pointer_segments=(),
        parent_type=None,
        format_name=format_name,
        confidence=confidence,
        content=content,
        source_suffix=source_suffix,
        line_offset=line_offset,
        metadata_overrides=metadata_overrides or {},
        paths=paths,
        references=references,
    )
    return tuple(paths), tuple(references)


def _walk_value(
    relative_path: str,
    value: Any,
    *,
    pointer_segments: tuple[str, ...],
    parent_type: str | None,
    format_name: str,
    confidence: str,
    content: str,
    source_suffix: str,
    line_offset: int,
    metadata_overrides: dict[str, dict[str, Any]],
    paths: list[RawObservation],
    references: list[RawObservation],
) -> None:
    if pointer_segments:
        pointer = json_pointer(pointer_segments)
        metadata_override = metadata_overrides.get(pointer, {})
        path_observation = _path_observation(
            relative_path,
            pointer,
            value,
            parent_type=parent_type,
            format_name=format_name,
            confidence=confidence,
            content=content,
            source_suffix=source_suffix,
            line_offset=line_offset,
            metadata_override=metadata_override,
        )
        paths.append(path_observation)
        references.extend(
            _reference_observations_for_value(
                relative_path,
                pointer_segments,
                value,
                source_path_key=path_observation.target or config_path_key(
                    relative_path,
                    pointer,
                ),
                format_name=format_name,
                confidence="heuristic",
                content=content,
                source_suffix=source_suffix,
                line_offset=line_offset,
                metadata_override=metadata_override,
            )
        )
    if isinstance(value, dict):
        for key, child in value.items():
            _walk_value(
                relative_path,
                child,
                pointer_segments=(*pointer_segments, str(key)),
                parent_type="object",
                format_name=format_name,
                confidence=confidence,
                content=content,
                source_suffix=source_suffix,
                line_offset=line_offset,
                metadata_overrides=metadata_overrides,
                paths=paths,
                references=references,
            )
    if isinstance(value, list) and _uses_stable_array_member_paths(format_name):
        for member in _stable_array_members(value):
            _walk_value(
                relative_path,
                member.value,
                pointer_segments=(*pointer_segments, member.segment),
                parent_type="array",
                format_name=format_name,
                confidence=confidence,
                content=content,
                source_suffix=source_suffix,
                line_offset=line_offset,
                metadata_overrides=metadata_overrides,
                paths=paths,
                references=references,
            )


def _path_observation(
    relative_path: str,
    pointer: str,
    value: Any,
    *,
    parent_type: str | None,
    format_name: str,
    confidence: str,
    content: str,
    source_suffix: str,
    line_offset: int,
    metadata_override: dict[str, Any] | None = None,
) -> RawObservation:
    metadata_override = metadata_override or {}
    redacted = bool(metadata_override.get("redacted")) or _is_secret_pointer(pointer)
    metadata = _path_metadata(
        pointer,
        value,
        parent_type=parent_type,
        format_name=format_name,
        redacted=redacted,
    )
    if metadata_override:
        metadata.update(metadata_override)
        if metadata.get("redacted"):
            metadata.pop("value_summary", None)
            metadata.pop("value_summaries", None)
            metadata.setdefault("redaction_reason", "secret-prone-key")
    line_number = _line_for_pointer(content, pointer)
    if line_number is not None:
        line_number += line_offset
    return RawObservation(
        kind="config.path",
        source_id=f"{relative_path}#config-path:{pointer}{source_suffix}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=pointer,
        target=config_path_key(relative_path, pointer),
        confidence=confidence,
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
    )


def _path_metadata(
    pointer: str,
    value: Any,
    *,
    parent_type: str | None,
    format_name: str,
    redacted: bool,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "format": format_name,
        "pointer": pointer,
        "display_path": pointer,
        "value_type": _value_type(value),
        "redacted": redacted,
    }
    if format_name == PLIST_XML_FORMAT:
        metadata["parser"] = _parser_name(format_name)
        metadata["safety_mode"] = PLIST_XML_SAFETY_MODE
    if parent_type is not None:
        metadata["container_type"] = parent_type
    if redacted:
        metadata["redaction_reason"] = "secret-prone-key"
        return metadata
    value_summary = _safe_value_summary(value)
    if value_summary is not None:
        metadata["value_summary"] = value_summary
    if isinstance(value, list):
        metadata["item_count"] = len(value)
        stable_members = (
            _stable_array_members(value)
            if _uses_stable_array_member_paths(format_name)
            else ()
        )
        if stable_members:
            metadata["array_policy"] = "stable-member-key"
            metadata["stable_member_keys"] = sorted(
                {member.key for member in stable_members}
            )
        else:
            metadata["array_policy"] = "summary-only"
        scalar_summaries = [
            summary
            for item in value[:5]
            if (summary := _safe_value_summary(item)) is not None
        ]
        if scalar_summaries:
            metadata["value_summaries"] = scalar_summaries
    return metadata


def _uses_stable_array_member_paths(format_name: str) -> bool:
    return format_name in ("toml", PLIST_XML_FORMAT, YAML_FORMAT)


def _reference_observations_for_value(
    relative_path: str,
    pointer_segments: tuple[str, ...],
    value: Any,
    *,
    source_path_key: str,
    format_name: str,
    confidence: str,
    content: str,
    source_suffix: str,
    line_offset: int,
    metadata_override: dict[str, Any] | None = None,
) -> tuple[RawObservation, ...]:
    pointer = json_pointer(pointer_segments)
    metadata_override = metadata_override or {}
    if metadata_override.get("redacted"):
        return ()
    references = _detect_references(
        relative_path,
        pointer_segments,
        value,
        format_name=format_name,
    )
    observations: list[RawObservation] = []
    for ordinal, reference in enumerate(references):
        line_number = _line_for_pointer(content, pointer)
        if line_number is not None:
            line_number += line_offset
        metadata = {
            "format": format_name,
            "pointer": pointer,
            "raw_key": pointer_segments[-1],
            "reference_kind": reference["kind"],
            "redacted": reference["redacted"],
            "resolution_reason": reference["reason"],
            "source_document_key": config_document_key(relative_path),
            "source_path_key": source_path_key,
        }
        if format_name == PLIST_XML_FORMAT:
            metadata["parser"] = _parser_name(format_name)
            metadata["safety_mode"] = PLIST_XML_SAFETY_MODE
        if format_name == YAML_FORMAT:
            for key in ("profile", "document_index", "yaml_tag", "anchor", "alias", "merge_key"):
                if key in metadata_override:
                    metadata[key] = metadata_override[key]
        if "summary" in reference:
            metadata["raw_value_summary"] = reference["summary"]
        if reference["redacted"]:
            metadata["redaction_reason"] = "secret-prone-key"
        observations.append(
            RawObservation(
                kind="config.reference",
                source_id=(
                    f"{relative_path}#config-reference:{pointer}:"
                    f"{ordinal}{source_suffix}"
                ),
                path=relative_path,
                start_line=line_number,
                end_line=line_number,
                name=pointer,
                target=reference["target"],
                confidence=confidence,
                extractor=EXTRACTOR_NAME,
                extractor_version=__version__,
                metadata=metadata,
            )
        )
    return tuple(observations)


def _detect_references(
    relative_path: str,
    pointer_segments: tuple[str, ...],
    value: Any,
    *,
    format_name: str = "",
) -> tuple[dict[str, Any], ...]:
    if not pointer_segments:
        return ()
    key = pointer_segments[-1]
    key_normalized = _normalized_key(key)
    pointer_key_normalized = "_".join(
        _normalized_key(segment) for segment in pointer_segments
    )
    parent_key = _normalized_key(pointer_segments[-2]) if len(pointer_segments) > 1 else ""
    redacted = _is_secret_pointer(json_pointer(pointer_segments))
    references: list[dict[str, Any]] = []
    if parent_key in ENV_CONTAINER_KEYS:
        references.append(_env_key_reference(key, redacted=redacted))
    if isinstance(value, str):
        references.extend(
            _string_references(
                relative_path,
                key_normalized,
                pointer_key_normalized,
                value,
                pointer_segments=pointer_segments,
                format_name=format_name,
                redacted=redacted,
            )
        )
    elif isinstance(value, list) and key_normalized == "args" and value:
        first = value[0]
        if isinstance(first, str) and _is_clear_command_name(first):
            references.append(_tool_reference_from_command(first, redacted=redacted))
    return tuple(references)


def _string_references(
    relative_path: str,
    key_normalized: str,
    pointer_key_normalized: str,
    value: str,
    *,
    pointer_segments: tuple[str, ...],
    format_name: str,
    redacted: bool,
) -> tuple[dict[str, Any], ...]:
    if format_name == YAML_FORMAT:
        yaml_references = _yaml_string_references(
            relative_path,
            pointer_segments,
            key_normalized,
            pointer_key_normalized,
            value,
            redacted=redacted,
        )
        if yaml_references:
            return yaml_references
    if _is_url(value):
        return (
            _reference(
                "external.url",
                external_url_key(value),
                "url-literal",
                value,
                redacted=redacted,
            ),
        )
    env_match = ENV_REFERENCE_PATTERN.match(value)
    if env_match is not None:
        return (
            _reference(
                "env",
                env_key(env_match.group("name")),
                "env-var-reference",
                value,
                redacted=redacted,
            ),
        )
    if key_normalized in TOOL_KEYS:
        return (_tool_reference_from_command(value, redacted=redacted),)
    if _looks_like_file_key(key_normalized, value) or _looks_like_file_key(
        pointer_key_normalized,
        value,
    ):
        return (_file_reference(relative_path, value, redacted=redacted),)
    return ()


def _tool_reference_from_command(command: str, *, redacted: bool) -> dict[str, Any]:
    if _is_clear_command_name(command):
        return _reference(
            "tool",
            tool_key(command),
            "simple-command-field",
            command,
            redacted=redacted,
        )
    if _is_dynamic_value(command) or any(character.isspace() for character in command):
        return _reference(
            "dynamic",
            dynamic_key("tool", "config-command-fragment"),
            "dynamic-command-field",
            command,
            redacted=redacted,
        )
    return _reference(
        "unknown",
        unknown_key("tool", "unknown-config-command"),
        "unknown-command-field",
        command,
        redacted=redacted,
    )


def _is_clear_command_name(command: str) -> bool:
    return bool(SIMPLE_COMMAND_PATTERN.match(command)) and not command.startswith("-")


def _env_key_reference(name: str, *, redacted: bool) -> dict[str, Any]:
    if ENV_NAME_PATTERN.match(name):
        return _reference(
            "env",
            env_key(name),
            "env-object-key",
            name,
            redacted=redacted,
        )
    return _reference(
        "dynamic",
        dynamic_key("env", "dynamic-config-env-name"),
        "dynamic-env-object-key",
        name,
        redacted=redacted,
    )


def _parser_name(format_name: str) -> str:
    if format_name == YAML_FORMAT:
        return YAML_PARSER
    if format_name == "jsonc":
        return "jsonc-conservative"
    if format_name == "toml":
        return "stdlib-tomllib"
    if format_name == PLIST_XML_FORMAT:
        return "stdlib-elementtree-safe"
    if format_name == GENERIC_XML_FORMAT:
        return "stdlib-elementtree-safe"
    return "stdlib-json"


def _line_for_pointer(content: str, pointer: str) -> int | None:
    if pointer == "":
        return None
    toml_line = _line_for_toml_pointer(content, pointer)
    if toml_line is not None:
        return toml_line
    key = pointer.rsplit("/", 1)[-1].replace("~1", "/").replace("~0", "~")
    json_pattern = re.compile(rf'"{re.escape(key)}"\s*:')
    toml_pattern = re.compile(
        rf"^\s*(?:{re.escape(key)}|\"{re.escape(key)}\"|'{re.escape(key)}')\s*="
    )
    yaml_pattern = re.compile(
        rf"^\s*(?:{re.escape(key)}|\"{re.escape(key)}\"|'{re.escape(key)}')\s*:"
    )
    plist_pattern = re.compile(rf"<key>\s*{re.escape(key)}\s*</key>")
    for line_number, line in enumerate(content.splitlines(), start=1):
        if (
            json_pattern.search(line)
            or toml_pattern.search(line)
            or yaml_pattern.search(line)
            or plist_pattern.search(line)
        ):
            return line_number
    return None
