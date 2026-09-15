"""Conservative YAML configuration raw observation extraction."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from repomap_kg.extractors.config import generic_contracts as _generic_contracts
from repomap_kg.extractors.config import infrastructure as _infrastructure
from repomap_kg.extractors.config import openapi as _openapi
from repomap_kg.extractors.config import openapi_helpers as _openapi_helpers
from repomap_kg.extractors.config.format_contracts import (
    YAML_ALIAS_PATTERN,
    YAML_ANCHOR_PATTERN,
    YAML_FORMAT,
    YAML_MAX_ALIASES,
    YAML_MAX_DEPTH,
    YAML_MAX_DOCUMENTS,
    YAML_MAX_FILE_BYTES,
    YAML_MAX_NODES,
    YAML_MAX_SCALAR_LENGTH,
    YAML_PARSER,
    YAML_SIMPLE_IMAGE_PATTERN,
    YAML_TAG_PATTERN,
)
from repomap_kg.extractors.config.paths import _pointer_segments, json_pointer
from repomap_kg.graph.keys import (
    config_path_key,
    dynamic_key,
    external_key,
    external_url_key,
    file_key,
    unknown_key,
)
from repomap_kg.observations.raw import RawObservation
from repomap_kg.extractors.config.yaml_lexical import (
    YamlParseError,
    _looks_like_yaml_mapping_pair,
    _parse_yaml_plain_scalar,
    _split_yaml_inline_items,
    _split_yaml_mapping_pair,
    _strip_yaml_comment,
    _unquote_yaml_scalar,
    _yaml_first_token,
    _yaml_mapping_colon_index,
)
from repomap_kg.extractors.config.yaml_profiles import (
    _apply_yaml_profile_metadata,
    _apply_yaml_stable_array_metadata,
    _yaml_document_index_from_pointer,
    _yaml_documents,
    _yaml_openapi_ref,
    _yaml_pointer_is_kubernetes_secret_data,
    _yaml_pointer_is_redacted,
    _yaml_pointer_values,
    _yaml_profile,
    _yaml_redaction_reason,
    _yaml_spring_file_reference_value,
    _yaml_string_references,
    _yaml_uses_reference,
)


def _generic_helper(name: str) -> Any:
    for owner in (_openapi, _openapi_helpers, _infrastructure):
        if hasattr(owner, name):
            return getattr(owner, name)
    return getattr(_generic_contracts, name)


def _yaml_format() -> str:
    return _generic_helper("YAML_FORMAT")


def _yaml_parser() -> str:
    return _generic_helper("YAML_PARSER")


def _yaml_max_file_bytes() -> int:
    return _generic_helper("YAML_MAX_FILE_BYTES")


def _yaml_max_documents() -> int:
    return _generic_helper("YAML_MAX_DOCUMENTS")


def _yaml_max_nodes() -> int:
    return _generic_helper("YAML_MAX_NODES")


def _yaml_max_depth() -> int:
    return _generic_helper("YAML_MAX_DEPTH")


def _yaml_max_scalar_length() -> int:
    return _generic_helper("YAML_MAX_SCALAR_LENGTH")


def _yaml_max_aliases() -> int:
    return _generic_helper("YAML_MAX_ALIASES")


def _parse_error_observation(*args: Any, **kwargs: Any) -> RawObservation:
    return _generic_helper("_parse_error_observation")(*args, **kwargs)


def _document_observation(*args: Any, **kwargs: Any) -> RawObservation:
    return _generic_helper("_document_observation")(*args, **kwargs)


def _structure_observations(*args: Any, **kwargs: Any) -> tuple[Any, Any]:
    return _generic_helper("_structure_observations")(*args, **kwargs)


def _value_type(value: Any) -> str:
    return _generic_helper("_value_type")(value)


def _is_openapi_file_name(relative_path: str) -> bool:
    return _generic_helper("_is_openapi_file_name")(relative_path)


def _openapi_parse_error_observation(*args: Any, **kwargs: Any) -> RawObservation:
    return _generic_helper("_openapi_parse_error_observation")(*args, **kwargs)


def _openapi_profile_observations(*args: Any, **kwargs: Any) -> tuple[RawObservation, ...]:
    return _generic_helper("_openapi_profile_observations")(*args, **kwargs)


def _normalized_key(value: str) -> str:
    return _generic_helper("_normalized_key")(value)


def _is_openapi_document(value: Any) -> bool:
    return _generic_helper("_is_openapi_document")(value)


def _is_kubernetes_document(value: Any) -> bool:
    return _generic_helper("_is_kubernetes_document")(value)


def _is_docker_compose_document(value: Any) -> bool:
    return _generic_helper("_is_docker_compose_document")(value)


def _is_grafana_document(value: Any) -> bool:
    return _generic_helper("_is_grafana_document")(value)


def _stable_array_members(value: list[Any]) -> list[Any]:
    return _generic_helper("_stable_array_members")(value)


def _is_secret_pointer(pointer: str) -> bool:
    return _generic_helper("_is_secret_pointer")(pointer)


def _openapi_pointer_is_redacted(pointer: str, value: Any) -> bool:
    return _generic_helper("_openapi_pointer_is_redacted")(pointer, value)


def _looks_like_secret_scalar(value: Any) -> bool:
    return _generic_helper("_looks_like_secret_scalar")(value)


def _is_secret_key(key: str) -> bool:
    return _generic_helper("_is_secret_key")(key)


def _reference(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return _generic_helper("_reference")(*args, **kwargs)


def _file_reference(relative_path: str, value: str, *, redacted: bool) -> dict[str, Any]:
    return _generic_helper("_file_reference")(relative_path, value, redacted=redacted)


def _safe_value_summary(value: Any) -> Any:
    return _generic_helper("_safe_value_summary")(value)


def _is_url(value: str) -> bool:
    return _generic_helper("_is_url")(value)


def _is_dynamic_value(value: str) -> bool:
    return _generic_helper("_is_dynamic_value")(value)


def _normalize_repo_path(value: str) -> str | None:
    return _generic_helper("_normalize_repo_path")(value)


def _looks_like_container_image(value: str) -> bool:
    return _generic_helper("_looks_like_container_image")(value)


@dataclass(frozen=True)
class _YamlLine:
    indent: int
    text: str
    line_number: int


@dataclass(frozen=True)
class _YamlValue:
    value: Any
    yaml_tag: str | None = None
    anchor: str | None = None
    alias: str | None = None
    metadata_only: bool = False


@dataclass
class _YamlParseState:
    node_count: int = 0
    alias_count: int = 0
    metadata_by_pointer: dict[str, dict[str, Any]] | None = None

    def metadata(self) -> dict[str, dict[str, Any]]:
        if self.metadata_by_pointer is None:
            self.metadata_by_pointer = {}
        return self.metadata_by_pointer


def _extract_yaml_observations(
    relative_path: str,
    content: str,
) -> tuple[RawObservation, ...]:
    try:
        parsed, metadata_overrides, document_count = _parse_yaml_documents(
            relative_path,
            content,
        )
    except YamlParseError as error:
        observation = _parse_error_observation(
            relative_path,
            format_name=_yaml_format(),
            error_kind=error.error_kind,
            message=str(error),
            start_line=error.line_number,
            recovered=False,
        )
        if error.error_kind == "duplicate-yaml-key":
            observation.metadata["duplicate_key_policy"] = "parse-error"
        if _is_openapi_file_name(relative_path):
            return (
                observation,
                _openapi_parse_error_observation(
                    relative_path,
                    format_name=_yaml_format(),
                    error_kind="malformed-openapi-yaml",
                    message=str(error),
                    start_line=error.line_number,
                ),
            )
        return (observation,)

    profile = _yaml_profile(relative_path, parsed, document_count=document_count)
    _apply_yaml_profile_metadata(
        parsed,
        metadata_overrides,
        profile=profile,
        document_count=document_count,
    )
    path_observations, reference_observations = _structure_observations(
        relative_path,
        parsed,
        format_name=_yaml_format(),
        confidence="extracted",
        content=content,
        metadata_overrides=metadata_overrides,
    )
    document = _document_observation(
        relative_path,
        format_name=_yaml_format(),
        parser=_yaml_parser(),
        confidence="extracted",
        top_level_type=_value_type(parsed),
        path_count=len(path_observations),
        record_count=None,
        parse_error_count=0,
        extra_metadata={
            "profile": profile,
            "document_count": document_count,
            "duplicate_key_policy": "parse-error",
        },
    )
    profile_observations = ()
    if profile == "openapi":
        profile_observations = _openapi_profile_observations(
            relative_path,
            parsed,
            format_name=_yaml_format(),
            confidence="extracted",
            profile=profile,
            document_count=document_count,
        )
    return (document, *profile_observations, *path_observations, *reference_observations)


def _parse_yaml_documents(
    relative_path: str,
    content: str,
) -> tuple[Any, dict[str, dict[str, Any]], int]:
    encoded_size = len(content.encode("utf-8"))
    if encoded_size > _yaml_max_file_bytes():
        raise YamlParseError(
            "YAML file exceeds conservative byte limit",
            error_kind="yaml-file-byte-limit",
        )
    documents = _split_yaml_documents(content)
    if len(documents) > _yaml_max_documents():
        raise YamlParseError(
            "YAML stream exceeds conservative document limit",
            error_kind="yaml-document-count-limit",
        )

    parsed_documents: list[Any] = []
    all_metadata: dict[str, dict[str, Any]] = {}
    for document_index, document_lines in enumerate(documents):
        state = _YamlParseState()
        lines = _yaml_logical_lines(document_lines)
        if not lines:
            parsed = None
        else:
            parsed, next_index = _parse_yaml_block(
                lines,
                0,
                lines[0].indent,
                state,
                pointer_segments=(),
                depth=0,
            )
            if next_index != len(lines):
                line = lines[next_index]
                raise YamlParseError(
                    "unsupported YAML structure after parsed document",
                    line_number=line.line_number,
                )
        parsed_documents.append(parsed)
        pointer_prefix: tuple[str, ...]
        if len(documents) == 1:
            pointer_prefix = ()
        else:
            pointer_prefix = ("documents", str(document_index))
        for pointer, metadata in state.metadata().items():
            combined_pointer = json_pointer(
                (*pointer_prefix, *_pointer_segments(pointer))
            )
            all_metadata.setdefault(combined_pointer, {}).update(metadata)

    if len(parsed_documents) == 1:
        parsed_value = parsed_documents[0]
    else:
        parsed_value = {
            "documents": {
                str(index): value for index, value in enumerate(parsed_documents)
            }
        }
    return parsed_value, all_metadata, len(parsed_documents)


def _split_yaml_documents(content: str) -> list[tuple[tuple[int, str], ...]]:
    documents: list[list[tuple[int, str]]] = [[]]
    for line_number, line in enumerate(content.splitlines(), start=1):
        stripped = line.strip()
        if stripped == "---":
            if documents[-1]:
                documents.append([])
            continue
        if stripped == "...":
            if documents[-1]:
                documents.append([])
            continue
        documents[-1].append((line_number, line))
    return [tuple(document) for document in documents if document] or [()]


def _yaml_logical_lines(lines: tuple[tuple[int, str], ...]) -> tuple[_YamlLine, ...]:
    logical_lines: list[_YamlLine] = []
    for line_number, raw_line in lines:
        if "\t" in raw_line[: len(raw_line) - len(raw_line.lstrip(" \t"))]:
            raise YamlParseError(
                "tabs are not supported for YAML indentation",
                line_number=line_number,
            )
        stripped_comment = _strip_yaml_comment(raw_line).rstrip()
        if not stripped_comment.strip():
            continue
        indent = len(stripped_comment) - len(stripped_comment.lstrip(" "))
        logical_lines.append(
            _YamlLine(
                indent=indent,
                text=stripped_comment.strip(),
                line_number=line_number,
            )
        )
    return tuple(logical_lines)


def _parse_yaml_block(
    lines: tuple[_YamlLine, ...],
    index: int,
    indent: int,
    state: _YamlParseState,
    *,
    pointer_segments: tuple[str, ...],
    depth: int,
) -> tuple[Any, int]:
    if depth > _yaml_max_depth():
        raise YamlParseError(
            "YAML nesting exceeds conservative depth limit",
            error_kind="yaml-depth-limit",
            line_number=lines[index].line_number if index < len(lines) else None,
        )
    if index >= len(lines):
        return None, index
    line = lines[index]
    if line.indent < indent:
        return None, index
    if line.indent > indent:
        raise YamlParseError(
            "unexpected YAML indentation",
            line_number=line.line_number,
        )
    if line.text.startswith("- "):
        return _parse_yaml_sequence(
            lines,
            index,
            indent,
            state,
            pointer_segments=pointer_segments,
            depth=depth,
        )
    return _parse_yaml_mapping(
        lines,
        index,
        indent,
        state,
        pointer_segments=pointer_segments,
        depth=depth,
    )


def _parse_yaml_mapping(
    lines: tuple[_YamlLine, ...],
    index: int,
    indent: int,
    state: _YamlParseState,
    *,
    pointer_segments: tuple[str, ...],
    depth: int,
) -> tuple[dict[str, Any], int]:
    mapping: dict[str, Any] = {}
    seen_keys: set[str] = set()
    while index < len(lines):
        line = lines[index]
        if line.indent < indent:
            break
        if line.indent > indent:
            raise YamlParseError(
                "unexpected YAML indentation",
                line_number=line.line_number,
            )
        if line.text.startswith("- "):
            break
        key, value_text = _split_yaml_mapping_pair(line.text, line.line_number)
        if key in seen_keys:
            raise YamlParseError(
                f"duplicate YAML key: {key}",
                error_kind="duplicate-yaml-key",
                line_number=line.line_number,
            )
        seen_keys.add(key)
        child_segments = (*pointer_segments, key)
        value, index = _yaml_value_or_nested_block(
            lines,
            index,
            indent,
            value_text,
            state,
            pointer_segments=child_segments,
            depth=depth,
        )
        mapping[key] = value
        state.node_count += 1
        if state.node_count > _yaml_max_nodes():
            raise YamlParseError(
                "YAML node count exceeds conservative limit",
                error_kind="yaml-node-count-limit",
                line_number=line.line_number,
            )
    return mapping, index


def _parse_yaml_sequence(
    lines: tuple[_YamlLine, ...],
    index: int,
    indent: int,
    state: _YamlParseState,
    *,
    pointer_segments: tuple[str, ...],
    depth: int,
) -> tuple[list[Any], int]:
    sequence: list[Any] = []
    while index < len(lines):
        line = lines[index]
        if line.indent < indent:
            break
        if line.indent > indent:
            raise YamlParseError(
                "unexpected YAML indentation",
                line_number=line.line_number,
            )
        if not line.text.startswith("- "):
            break
        item_text = line.text[2:].strip()
        item_index = len(sequence)
        child_segments = (*pointer_segments, str(item_index))
        if not item_text:
            next_index = index + 1
            if next_index < len(lines) and lines[next_index].indent > indent:
                value, index = _parse_yaml_block(
                    lines,
                    next_index,
                    lines[next_index].indent,
                    state,
                    pointer_segments=child_segments,
                    depth=depth + 1,
                )
            else:
                value, index = None, next_index
        elif _looks_like_yaml_mapping_pair(item_text):
            key, value_text = _split_yaml_mapping_pair(item_text, line.line_number)
            item_mapping: dict[str, Any] = {}
            value, next_index = _yaml_value_or_nested_block(
                lines,
                index,
                indent,
                value_text,
                state,
                pointer_segments=(*child_segments, key),
                depth=depth,
            )
            item_mapping[key] = value
            if next_index < len(lines) and lines[next_index].indent > indent:
                extra, next_index = _parse_yaml_block(
                    lines,
                    next_index,
                    lines[next_index].indent,
                    state,
                    pointer_segments=child_segments,
                    depth=depth + 1,
                )
                if isinstance(extra, dict):
                    for extra_key, extra_value in extra.items():
                        if extra_key in item_mapping:
                            raise YamlParseError(
                                f"duplicate YAML key: {extra_key}",
                                error_kind="duplicate-yaml-key",
                                line_number=line.line_number,
                            )
                        item_mapping[extra_key] = extra_value
                else:
                    raise YamlParseError(
                        "sequence item cannot combine scalar and nested sequence",
                        line_number=line.line_number,
                    )
            value, index = item_mapping, next_index
        else:
            parsed = _parse_yaml_scalar(item_text, line.line_number, state)
            _record_yaml_value_metadata(
                parsed,
                state,
                pointer_segments=child_segments,
                merge_key=False,
            )
            value = parsed.value
            index += 1
        sequence.append(value)
        state.node_count += 1
        if state.node_count > _yaml_max_nodes():
            raise YamlParseError(
                "YAML node count exceeds conservative limit",
                error_kind="yaml-node-count-limit",
                line_number=line.line_number,
            )
    return sequence, index


def _yaml_value_or_nested_block(
    lines: tuple[_YamlLine, ...],
    index: int,
    indent: int,
    value_text: str,
    state: _YamlParseState,
    *,
    pointer_segments: tuple[str, ...],
    depth: int,
) -> tuple[Any, int]:
    line = lines[index]
    parsed = _parse_yaml_scalar(value_text, line.line_number, state)
    next_index = index + 1
    merge_key = bool(pointer_segments and pointer_segments[-1] == "<<")
    if parsed.metadata_only and next_index < len(lines) and lines[next_index].indent > indent:
        value, next_index = _parse_yaml_block(
            lines,
            next_index,
            lines[next_index].indent,
            state,
            pointer_segments=pointer_segments,
            depth=depth + 1,
        )
    elif parsed.metadata_only:
        value = None
    else:
        value = parsed.value
    _record_yaml_value_metadata(
        parsed,
        state,
        pointer_segments=pointer_segments,
        merge_key=merge_key,
    )
    return value, next_index


def _parse_yaml_scalar(
    text: str,
    line_number: int,
    state: _YamlParseState,
) -> _YamlValue:
    stripped = text.strip()
    yaml_tag: str | None = None
    anchor: str | None = None
    while True:
        token, rest = _yaml_first_token(stripped)
        if token is not None and YAML_TAG_PATTERN.match(token):
            yaml_tag = token
            stripped = rest
            continue
        if token is not None and YAML_ANCHOR_PATTERN.match(token):
            anchor = token[1:]
            stripped = rest
            continue
        break
    if not stripped:
        return _YamlValue(None, yaml_tag=yaml_tag, anchor=anchor, metadata_only=True)
    if YAML_ALIAS_PATTERN.match(stripped):
        state.alias_count += 1
        if state.alias_count > _yaml_max_aliases():
            raise YamlParseError(
                "YAML alias count exceeds conservative limit",
                error_kind="yaml-alias-count-limit",
                line_number=line_number,
            )
        return _YamlValue(
            stripped[1:],
            yaml_tag=yaml_tag,
            anchor=anchor,
            alias=stripped[1:],
        )
    if len(stripped) > _yaml_max_scalar_length():
        raise YamlParseError(
            "YAML scalar exceeds conservative length limit",
            error_kind="yaml-scalar-length-limit",
            line_number=line_number,
        )
    if stripped.startswith("["):
        if not stripped.endswith("]"):
            raise YamlParseError(
                "unterminated YAML inline sequence",
                line_number=line_number,
            )
        return _YamlValue(
            _parse_yaml_inline_sequence(stripped, line_number, state),
            yaml_tag=yaml_tag,
            anchor=anchor,
        )
    if stripped.startswith("{"):
        if not stripped.endswith("}"):
            raise YamlParseError(
                "unterminated YAML inline mapping",
                line_number=line_number,
            )
        return _YamlValue(
            _parse_yaml_inline_mapping(stripped, line_number, state),
            yaml_tag=yaml_tag,
            anchor=anchor,
        )
    return _YamlValue(_parse_yaml_plain_scalar(stripped), yaml_tag=yaml_tag, anchor=anchor)


def _record_yaml_value_metadata(
    parsed: _YamlValue,
    state: _YamlParseState,
    *,
    pointer_segments: tuple[str, ...],
    merge_key: bool,
) -> None:
    if not pointer_segments:
        return
    metadata: dict[str, Any] = {}
    if parsed.yaml_tag is not None:
        metadata["yaml_tag"] = parsed.yaml_tag
        if _is_secret_key(parsed.yaml_tag):
            metadata["redacted"] = True
            metadata["redaction_reason"] = "secret-prone-yaml-tag"
    if parsed.anchor is not None:
        metadata["anchor"] = parsed.anchor
    if parsed.alias is not None:
        metadata["alias"] = parsed.alias
    if merge_key:
        metadata["merge_key"] = True
    if not metadata:
        return
    pointer = json_pointer(pointer_segments)
    state.metadata().setdefault(pointer, {}).update(metadata)


def _parse_yaml_inline_sequence(
    text: str,
    line_number: int,
    state: _YamlParseState,
) -> list[Any]:
    inner = text[1:-1].strip()
    if not inner:
        return []
    return [
        _parse_yaml_scalar(item, line_number, state).value
        for item in _split_yaml_inline_items(inner, line_number)
    ]


def _parse_yaml_inline_mapping(
    text: str,
    line_number: int,
    state: _YamlParseState,
) -> dict[str, Any]:
    inner = text[1:-1].strip()
    if not inner:
        return {}
    result: dict[str, Any] = {}
    for item in _split_yaml_inline_items(inner, line_number):
        key, value_text = _split_yaml_mapping_pair(item, line_number)
        if key in result:
            raise YamlParseError(
                f"duplicate YAML key: {key}",
                error_kind="duplicate-yaml-key",
                line_number=line_number,
            )
        result[key] = _parse_yaml_scalar(value_text, line_number, state).value
    return result
