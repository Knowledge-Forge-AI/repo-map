"""PowerShell module manifest extraction helpers."""

from __future__ import annotations

import posixpath
import re
from typing import Any

from repomap_kg import __version__
from repomap_kg.extractors.shell.powershell_common import (
    EXTRACTOR_NAME,
    _is_secret_like_name,
    _resolve_static_path,
    _secret_like_observation,
    _strip_quotes,
    slug,
)
from repomap_kg.extractors.shell.powershell_manifest_parser import (
    ManifestToken,
    ManifestValue,
    _manifest_string_token,
    _manifest_tokens,
    _parse_manifest_array,
    _parse_manifest_document,
    _parse_manifest_hashtable,
    _parse_manifest_value,
    _skip_parenthesized_manifest_expression,
)
from repomap_kg.observations.raw import RawObservation


MANIFEST_FIELD_PATTERN = re.compile(
    r"^\s*(?P<name>[A-Za-z][0-9A-Za-z_]*)\s*=\s*(?P<value>.+?)\s*$"
)
STRING_LITERAL_PATTERN = re.compile(r"^['\"](?P<value>[^'\"]*)['\"]$")
ARRAY_START_PATTERN = re.compile(r"^@\(\s*$")
QUOTED_VALUE_PATTERN = re.compile(r"['\"](?P<value>[^'\"]+)['\"]")
MANIFEST_FILE_REFERENCE_FIELDS = frozenset(
    {
        "FileList",
        "FormatsToProcess",
        "ModuleList",
        "NestedModules",
        "RootModule",
        "ScriptsToProcess",
        "TypesToProcess",
    }
)
MANIFEST_EXPORT_FIELDS = {
    "AliasesToExport": "alias",
    "CmdletsToExport": "cmdlet",
    "DscResourcesToExport": "dsc_resource",
    "FunctionsToExport": "function",
    "VariablesToExport": "variable",
}
MANIFEST_REFERENCE_SUFFIXES = (
    ".dll",
    ".json",
    ".md",
    ".ps1",
    ".ps1xml",
    ".psd1",
    ".psm1",
    ".txt",
    ".xml",
)
MISSING = object()


def _extract_manifest_fields(relative_path: str, content: str) -> tuple[RawObservation, ...]:
    root = _parse_manifest_document(content)
    if root is None or not root.entries:
        return _extract_manifest_fields_legacy(relative_path, content)
    observations: list[RawObservation] = []
    for field, value in root.entries:
        observations.extend(
            _manifest_value_observations(
                relative_path,
                field,
                field,
                value,
            )
        )
        observations.extend(
            _manifest_specialized_observations(
                relative_path,
                field,
                value,
            )
        )
    return tuple(observations)


def _extract_manifest_fields_legacy(
    relative_path: str,
    content: str,
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    lines = content.splitlines()
    index = 0
    while index < len(lines):
        line_number = index + 1
        line = lines[index]
        match = MANIFEST_FIELD_PATTERN.match(line)
        if match is None:
            index += 1
            continue
        name = match.group("name")
        value = match.group("value").strip()
        if STRING_LITERAL_PATTERN.match(value):
            literal = STRING_LITERAL_PATTERN.match(value)
            assert literal is not None
            observations.append(
                _manifest_field_observation(
                    relative_path,
                    line_number,
                    line_number,
                    name,
                    value=literal.group("value"),
                )
            )
            index += 1
            continue
        if ARRAY_START_PATTERN.match(value):
            values, end_index = _collect_manifest_array(lines, index + 1)
            observations.append(
                _manifest_field_observation(
                    relative_path,
                    line_number,
                    end_index + 1,
                    name,
                    values=values,
                )
            )
            index = end_index + 1
            continue
        observations.append(
            _manifest_field_observation(
                relative_path,
                line_number,
                line_number,
                name,
                unknown=True,
            )
        )
        index += 1
    return tuple(observations)


def _manifest_value_observations(
    relative_path: str,
    field: str,
    field_path: str,
    value: ManifestValue,
) -> list[RawObservation]:
    observations = [
        _manifest_field_observation(
            relative_path,
            value.start_line,
            value.end_line,
            field,
            field_path=field_path,
            manifest_value=value,
        )
    ]
    if _manifest_field_is_redacted(field_path):
        observations.append(
            _secret_like_observation(
                relative_path,
                value.start_line,
                field_path,
                secret_source="manifest_field",
                reason="secret-like manifest field",
                end_line=value.end_line,
            )
        )
    if field_path.startswith("PrivateData."):
        observations.extend(
            _manifest_private_data_observations(
                relative_path,
                field,
                field_path,
                value,
            )
        )
    if value.kind == "hashtable":
        for nested_field, nested_value in value.entries:
            observations.extend(
                _manifest_value_observations(
                    relative_path,
                    nested_field,
                    f"{field_path}.{nested_field}",
                    nested_value,
                )
            )
    return observations


def _manifest_private_data_observations(
    relative_path: str,
    field: str,
    field_path: str,
    value: ManifestValue,
) -> list[RawObservation]:
    if value.kind not in {"string", "array", "bool", "int", "null"}:
        return []
    metadata = _manifest_value_metadata(field, field_path, value)
    if metadata.get("redacted"):
        return []
    return [
        RawObservation(
            kind="powershell.manifest_private_data",
            source_id=(
                f"{relative_path}#manifest-private-data:"
                f"{value.start_line}:{slug(field_path)}"
            ),
            path=relative_path,
            start_line=value.start_line,
            end_line=value.end_line,
            name=field_path,
            confidence="extracted",
            extractor=EXTRACTOR_NAME,
            extractor_version=__version__,
            metadata=metadata,
        )
    ]


def _manifest_specialized_observations(
    relative_path: str,
    field: str,
    value: ManifestValue,
) -> list[RawObservation]:
    observations: list[RawObservation] = []
    observations.extend(
        _manifest_dependency_observations(relative_path, field, value)
    )
    observations.extend(
        _manifest_file_reference_observations(relative_path, field, value)
    )
    observations.extend(_manifest_export_observations(relative_path, field, value))
    return observations


def _manifest_dependency_observations(
    relative_path: str,
    field: str,
    value: ManifestValue,
) -> list[RawObservation]:
    if field == "RequiredModules":
        return _required_module_dependency_observations(relative_path, field, value)
    if field == "RequiredAssemblies":
        return [
            _manifest_dependency_observation(
                relative_path,
                field,
                item,
                dependency_kind="assembly",
                assembly_name=item.value,
                value_shape=item.kind,
            )
            for item in _string_like_manifest_items(value, field, include_unknown=False)
            if item.kind == "string"
        ]
    if field == "NestedModules":
        return [
            _manifest_dependency_observation(
                relative_path,
                field,
                item,
                dependency_kind="nested_module",
                module_name=item.value,
                value_shape=item.kind,
            )
            for item in _string_like_manifest_items(value, field, include_unknown=False)
            if item.kind == "string"
        ]
    return []


def _required_module_dependency_observations(
    relative_path: str,
    field: str,
    value: ManifestValue,
) -> list[RawObservation]:
    observations: list[RawObservation] = []
    for item in _manifest_item_values(value):
        if item.kind == "string":
            observations.append(
                _manifest_dependency_observation(
                    relative_path,
                    field,
                    item,
                    dependency_kind="module",
                    module_name=item.value,
                    value_shape="string",
                )
            )
            continue
        if item.kind != "hashtable":
            observations.append(
                _manifest_dependency_observation(
                    relative_path,
                    field,
                    item,
                    dependency_kind="module",
                    value_shape=item.kind,
                    unknown_reason=item.unknown_reason or "unsupported-module-spec",
                )
            )
            continue
        entry_map = {key: nested for key, nested in item.entries}
        module_name = _manifest_static_string(entry_map.get("ModuleName"))
        metadata_values = {
            "module_version": _manifest_static_string(entry_map.get("ModuleVersion")),
            "required_version": _manifest_static_string(entry_map.get("RequiredVersion")),
            "maximum_version": _manifest_static_string(entry_map.get("MaximumVersion")),
            "guid": _manifest_static_string(entry_map.get("GUID")),
        }
        observations.append(
            _manifest_dependency_observation(
                relative_path,
                field,
                item,
                dependency_kind="module",
                module_name=module_name,
                value_shape="hashtable",
                **metadata_values,
            )
        )
    return observations


def _manifest_dependency_observation(
    relative_path: str,
    field: str,
    value: ManifestValue,
    *,
    dependency_kind: str,
    value_shape: str,
    module_name: str | None = None,
    assembly_name: str | None = None,
    module_version: str | None = None,
    required_version: str | None = None,
    maximum_version: str | None = None,
    guid: str | None = None,
    unknown_reason: str | None = None,
) -> RawObservation:
    name = module_name or assembly_name or f"{field}:unknown"
    metadata: dict[str, Any] = {
        "field": field,
        "dependency_kind": dependency_kind,
        "value_shape": value_shape,
        "static_only": True,
        "powershell_executed": False,
    }
    for key, item in (
        ("module_name", module_name),
        ("assembly_name", assembly_name),
        ("module_version", module_version),
        ("required_version", required_version),
        ("maximum_version", maximum_version),
        ("guid", guid),
    ):
        if item is not None:
            metadata[key] = item
    confidence = "extracted"
    if unknown_reason is not None or (module_name is None and assembly_name is None):
        confidence = "unknown"
        metadata["resolution"] = "unknown"
        metadata["unknown_reason"] = unknown_reason or "unsupported-dependency-value"
    return RawObservation(
        kind="powershell.manifest_dependency",
        source_id=(
            f"{relative_path}#manifest-dependency:"
            f"{value.start_line}:{slug(field)}:{slug(name)}"
        ),
        path=relative_path,
        start_line=value.start_line,
        end_line=value.end_line,
        name=name,
        target=f"module:{module_name}" if module_name else None,
        confidence=confidence,
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
    )


def _manifest_file_reference_observations(
    relative_path: str,
    field: str,
    value: ManifestValue,
) -> list[RawObservation]:
    if field not in MANIFEST_FILE_REFERENCE_FIELDS and field != "RequiredAssemblies":
        return []
    observations: list[RawObservation] = []
    for item in _string_like_manifest_items(value, field, include_unknown=True):
        if item.kind != "string":
            observations.append(
                _manifest_file_reference_observation(
                    relative_path,
                    field,
                    item,
                    reference="[unknown]",
                    resolution="unknown",
                    unknown_reason=item.unknown_reason or "unsupported-reference-value",
                )
            )
            continue
        reference = item.value
        resolved = _resolve_manifest_reference(relative_path, reference)
        resolution = "static" if resolved is not None else "module-name"
        observations.append(
            _manifest_file_reference_observation(
                relative_path,
                field,
                item,
                reference=reference,
                resolved_path=resolved,
                resolution=resolution,
            )
        )
    return observations


def _manifest_file_reference_observation(
    relative_path: str,
    field: str,
    value: ManifestValue,
    *,
    reference: str,
    resolution: str,
    resolved_path: str | None = None,
    unknown_reason: str | None = None,
) -> RawObservation:
    metadata: dict[str, Any] = {
        "field": field,
        "reference": reference,
        "resolution": resolution,
        "static_only": True,
        "powershell_executed": False,
    }
    if resolved_path is not None:
        metadata["resolved_path"] = resolved_path
    confidence = "extracted"
    if unknown_reason is not None:
        confidence = "unknown"
        metadata["unknown_reason"] = unknown_reason
    return RawObservation(
        kind="powershell.manifest_file_reference",
        source_id=(
            f"{relative_path}#manifest-file-reference:"
            f"{value.start_line}:{slug(field)}:{slug(reference)}"
        ),
        path=relative_path,
        start_line=value.start_line,
        end_line=value.end_line,
        name=reference,
        target=f"file:{resolved_path}" if resolved_path is not None else None,
        confidence=confidence,
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
    )


def _manifest_export_observations(
    relative_path: str,
    field: str,
    value: ManifestValue,
) -> list[RawObservation]:
    export_kind = MANIFEST_EXPORT_FIELDS.get(field)
    if export_kind is None:
        return []
    observations: list[RawObservation] = []
    for item in _string_like_manifest_items(value, field, include_unknown=True):
        if item.kind != "string":
            observations.append(
                _manifest_export_observation(
                    relative_path,
                    field,
                    item,
                    export_kind=export_kind,
                    name="[unknown]",
                    wildcard=False,
                    unknown_reason=item.unknown_reason or "unsupported-export-value",
                )
            )
            continue
        observations.append(
            _manifest_export_observation(
                relative_path,
                field,
                item,
                export_kind=export_kind,
                name=item.value,
                wildcard=item.value == "*",
            )
        )
    return observations


def _manifest_export_observation(
    relative_path: str,
    field: str,
    value: ManifestValue,
    *,
    export_kind: str,
    name: str,
    wildcard: bool,
    unknown_reason: str | None = None,
) -> RawObservation:
    metadata = {
        "field": field,
        "export_kind": export_kind,
        "wildcard": wildcard,
        "static_only": True,
        "powershell_executed": False,
    }
    confidence = "extracted"
    if unknown_reason is not None:
        confidence = "unknown"
        metadata["resolution"] = "unknown"
        metadata["unknown_reason"] = unknown_reason
    return RawObservation(
        kind="powershell.manifest_export",
        source_id=f"{relative_path}#manifest-export:{value.start_line}:{slug(field)}:{slug(name)}",
        path=relative_path,
        start_line=value.start_line,
        end_line=value.end_line,
        name=name,
        target=f"powershell-export:{export_kind}:{name}" if name != "[unknown]" else None,
        confidence=confidence,
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
    )


def _manifest_field_observation(
    relative_path: str,
    start_line: int,
    end_line: int,
    name: str,
    *,
    field_path: str | None = None,
    manifest_value: ManifestValue | None = None,
    value: Any = MISSING,
    values: tuple[str, ...] | None = None,
    unknown: bool = False,
) -> RawObservation:
    field_path = field_path or name
    if manifest_value is not None:
        return _manifest_field_observation_from_value(
            relative_path,
            name,
            field_path,
            manifest_value,
        )
    metadata: dict[str, Any] = {
        "field": name,
        "field_path": field_path,
        "static_only": True,
        "powershell_executed": False,
    }
    confidence = "extracted"
    if value is not MISSING:
        metadata["value"] = value
        metadata["value_type"] = "string"
    elif values is not None:
        metadata["values"] = list(values)
        metadata["value_type"] = "string-array"
    elif unknown:
        confidence = "unknown"
        metadata["resolution"] = "unknown"
        metadata["unknown_reason"] = "unsupported-manifest-value"
    return RawObservation(
        kind="powershell.manifest_field",
        source_id=f"{relative_path}#manifest-field:{start_line}:{slug(name)}",
        path=relative_path,
        start_line=start_line,
        end_line=end_line,
        name=name,
        confidence=confidence,
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
    )


def _manifest_field_observation_from_value(
    relative_path: str,
    field: str,
    field_path: str,
    value: ManifestValue,
) -> RawObservation:
    metadata = _manifest_value_metadata(field, field_path, value)
    confidence = "extracted"
    if value.kind in {"unknown", "hashtable"} or metadata.get("resolution") == "unknown":
        confidence = "unknown"
        metadata["resolution"] = "unknown"
        metadata.setdefault(
            "unknown_reason",
            value.unknown_reason or "unsupported-manifest-value",
        )
    return RawObservation(
        kind="powershell.manifest_field",
        source_id=f"{relative_path}#manifest-field:{value.start_line}:{slug(field_path)}",
        path=relative_path,
        start_line=value.start_line,
        end_line=value.end_line,
        name=field,
        confidence=confidence,
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
    )


def _manifest_value_metadata(
    field: str,
    field_path: str,
    value: ManifestValue,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "field": field,
        "field_path": field_path,
        "static_only": True,
        "powershell_executed": False,
        "redacted": False,
    }
    if _manifest_field_is_redacted(field_path):
        metadata["redacted"] = True
        metadata["redaction_reason"] = "secret-like manifest field"
        metadata["raw_value_stored"] = False
    if value.kind == "string":
        metadata["value_type"] = "string"
        metadata["value"] = "[redacted]" if metadata["redacted"] else value.value
    elif value.kind == "array":
        static_strings = [
            item.value for item in value.items if item.kind == "string"
        ]
        metadata["value_type"] = (
            "string-array" if _manifest_array_is_string_only(value) else "array"
        )
        if metadata["redacted"]:
            metadata["values"] = ["[redacted]"] if static_strings else []
        elif _manifest_array_is_string_only(value):
            metadata["values"] = static_strings
        else:
            metadata["value_shape"] = [
                item.kind for item in value.items
            ]
    elif value.kind == "bool":
        metadata["value_type"] = "bool"
        metadata["value"] = value.value
    elif value.kind == "int":
        metadata["value_type"] = "int"
        metadata["value"] = value.value
    elif value.kind == "null":
        metadata["value_type"] = "null"
        metadata["value"] = None
    elif value.kind == "hashtable":
        metadata["value_type"] = "hashtable"
        metadata["entry_count"] = len(value.entries)
        metadata["resolution"] = "unknown"
        metadata["unknown_reason"] = "nested-manifest-value"
    else:
        metadata["value_type"] = "unknown"
        metadata["resolution"] = "unknown"
        metadata["unknown_reason"] = value.unknown_reason or "unsupported-manifest-value"
    return metadata


def _manifest_field_is_redacted(field_path: str) -> bool:
    return any(_is_secret_like_name(part) for part in field_path.split("."))


def _manifest_array_is_string_only(value: ManifestValue) -> bool:
    return value.kind == "array" and all(item.kind == "string" for item in value.items)


def _manifest_item_values(value: ManifestValue) -> tuple[ManifestValue, ...]:
    if value.kind == "array":
        return value.items
    return (value,)


def _string_like_manifest_items(
    value: ManifestValue,
    field: str,
    *,
    include_unknown: bool,
) -> tuple[ManifestValue, ...]:
    items = _manifest_item_values(value)
    result: list[ManifestValue] = []
    for item in items:
        if item.kind == "string":
            result.append(item)
        elif include_unknown and item.kind == "unknown":
            result.append(item)
        elif include_unknown and item.kind == "hashtable":
            result.append(
                ManifestValue(
                    "unknown",
                    start_line=item.start_line,
                    end_line=item.end_line,
                    unknown_reason=f"unsupported-{field.lower()}-value",
                )
            )
    return tuple(result)


def _manifest_static_string(value: ManifestValue | None) -> str | None:
    if value is not None and value.kind == "string":
        return value.value
    return None


def _resolve_manifest_reference(relative_path: str, token: str) -> str | None:
    existing = _resolve_static_path(relative_path, token)
    if existing is not None:
        return existing
    normalized_token = _strip_quotes(token).replace("\\", "/")
    if (
        "/" not in normalized_token
        and not normalized_token.lower().endswith(MANIFEST_REFERENCE_SUFFIXES)
    ):
        return None
    base = posixpath.dirname(relative_path)
    resolved = posixpath.normpath(posixpath.join(base, normalized_token))
    if resolved == "." or resolved.startswith("../"):
        return None
    return resolved


def _collect_manifest_array(lines: list[str], start_index: int) -> tuple[tuple[str, ...], int]:
    values: list[str] = []
    index = start_index
    while index < len(lines):
        line = lines[index]
        values.extend(match.group("value") for match in QUOTED_VALUE_PATTERN.finditer(line))
        if ")" in line:
            return tuple(values), index
        index += 1
    return tuple(values), max(start_index, len(lines) - 1)
