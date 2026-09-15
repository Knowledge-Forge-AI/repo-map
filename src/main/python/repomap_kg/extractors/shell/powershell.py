"""Conservative static PowerShell raw observation extraction."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any

from repomap_kg import __version__
from repomap_kg.extractors.shell.powershell_common import (
    EXTRACTOR_NAME,
    SECRET_EXACT_NAMES,
    SECRET_MARKERS,
    SLUG_PATTERN,
    _is_dynamic_token,
    _is_secret_like_name,
    _redacted_token_summary,
    _resolve_static_path,
    _secret_like_observation,
    _strip_quotes,
    slug,
)
from repomap_kg.extractors.shell.powershell_aliases import (
    AliasDefinition,
    _alias_definition_observation,
    _alias_definition_parts,
    _alias_target_family,
)
from repomap_kg.extractors.shell.powershell_tokens import (
    TOKEN_PATTERN,
    _argument_value_kind,
    _collect_pipeline_lines,
    _command_tokens,
    _has_pipeline_separator,
    _pipeline_segments,
    _skip_hashtable,
    _starts_pipeline,
    _token_has_argument_value,
    _token_is_positional_argument,
)
from repomap_kg.extractors.shell.powershell_vocabulary import (
    CANONICAL_CMDLETS,
    COMMAND_SKIP_KEYWORDS,
    EXTERNAL_COMMANDS,
    POWERSHELL_ALIASES,
)
from repomap_kg.extractors.shell.powershell_manifest import (
    ARRAY_START_PATTERN,
    MANIFEST_EXPORT_FIELDS,
    MANIFEST_FIELD_PATTERN,
    MANIFEST_FILE_REFERENCE_FIELDS,
    MANIFEST_REFERENCE_SUFFIXES,
    MISSING,
    QUOTED_VALUE_PATTERN,
    STRING_LITERAL_PATTERN,
    ManifestToken,
    ManifestValue,
    _collect_manifest_array,
    _extract_manifest_fields,
    _extract_manifest_fields_legacy,
    _manifest_array_is_string_only,
    _manifest_dependency_observation,
    _manifest_dependency_observations,
    _manifest_export_observation,
    _manifest_export_observations,
    _manifest_field_is_redacted,
    _manifest_field_observation,
    _manifest_field_observation_from_value,
    _manifest_file_reference_observation,
    _manifest_file_reference_observations,
    _manifest_item_values,
    _manifest_private_data_observations,
    _manifest_specialized_observations,
    _manifest_static_string,
    _manifest_string_token,
    _manifest_tokens,
    _manifest_value_metadata,
    _manifest_value_observations,
    _parse_manifest_array,
    _parse_manifest_document,
    _parse_manifest_hashtable,
    _parse_manifest_value,
    _required_module_dependency_observations,
    _resolve_manifest_reference,
    _skip_parenthesized_manifest_expression,
    _string_like_manifest_items,
)
from repomap_kg.extractors.shell.powershell_side_effects import (
    CREDENTIAL_COMMANDS,
    EXTERNAL_PACKAGE_MANAGERS,
    FILE_READ_COMMANDS,
    FILE_WRITE_COMMANDS,
    NETWORK_COMMANDS,
    PACKAGE_CMDLETS,
    PROCESS_MUTATION_COMMANDS,
    REGISTRY_READ_COMMANDS,
    REGISTRY_WRITE_COMMANDS,
    REMOTING_COMMANDS,
    SCHEDULED_TASK_COMMANDS,
    SECURITY_POLICY_COMMANDS,
    SERVICE_MUTATION_COMMANDS,
    _argument_value,
    _empty_target_summary,
    _env_observation,
    _external_package_name,
    _external_package_operation,
    _host_mutation_for_command_category,
    _host_mutation_observation,
    _is_credential_command,
    _is_registry_target,
    _is_sensitive_command_argument,
    _mask_quoted_strings,
    _network_observation,
    _observation_target,
    _package_host_mutation_observation,
    _process_target,
    _registry_target_from_arguments,
    _remoting_observation,
    _side_effect_metadata,
    _side_effect_observations_for_command,
    _target_display,
    _target_from_arguments,
    _target_observation,
    _target_summary,
    _parsed_arguments,
    _split_named_argument,
)
from repomap_kg.extractors.shell.powershell_splats import (
    SplatAssignment,
    _splat_assignment_from_lines,
    _splat_observation,
)
from repomap_kg.extractors.shell.powershell_structure import (
    ASSIGNMENT_PATTERN,
    CALL_OPERATOR_PATTERN,
    DOT_SOURCE_PATTERN,
    FUNCTION_PATTERN,
    IMPORT_MODULE_PATTERN,
    INVOKE_EXPRESSION_PATTERN,
    PARAM_NAME_PATTERN,
    PARAM_START_PATTERN,
    REQUIRES_PATTERN,
    USING_MODULE_PATTERN,
    _brace_delta,
    _collect_parenthesized_block,
    _dot_source_or_dynamic_observation,
    _dynamic_invocation_observation,
    _extract_script_or_module_observations,
    _first_argument,
    _function_observation,
    _module_reference_observation,
    _param_observations,
    _parameter_type,
    _reference_target_metadata,
    _requires_observation,
    _static_invocation_target_display,
    _static_scan_lines,
)
from repomap_kg.observations.raw import RawObservation


POWERSHELL_SUFFIX_FILE_TYPE = {
    ".ps1": ("powershell.script", "script"),
    ".psm1": ("powershell.module", "module"),
    ".psd1": ("powershell.manifest", "manifest"),
}


def extract_powershell_file_observations(
    relative_path: str,
    content: str,
) -> tuple[RawObservation, ...]:
    suffix = PurePosixPath(relative_path).suffix.lower()
    file_kind, file_type = POWERSHELL_SUFFIX_FILE_TYPE.get(
        suffix,
        ("powershell.script", "script"),
    )
    observations = [
        RawObservation(
            kind=file_kind,
            source_id=f"{relative_path}#powershell-{file_type}",
            path=relative_path,
            name=relative_path,
            confidence="extracted",
            extractor=EXTRACTOR_NAME,
            extractor_version=__version__,
            metadata={
                "file_type": file_type,
                "parser": "stdlib-static-scanner",
                "static_only": True,
                "powershell_executed": False,
            },
        )
    ]
    if suffix == ".psd1":
        observations.extend(_extract_manifest_fields(relative_path, content))
        return tuple(observations)
    observations.extend(_extract_script_or_module_observations(relative_path, content))
    observations.extend(_extract_command_like_observations(relative_path, content))
    observations.extend(_extract_environment_reference_observations(relative_path, content))
    return tuple(observations)


def _extract_command_like_observations(
    relative_path: str,
    content: str,
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    local_aliases: dict[str, AliasDefinition] = {}
    splat_assignments: dict[str, SplatAssignment] = {}
    lines = _static_scan_lines(content)
    index = 0
    while index < len(lines):
        line_number = index + 1
        line = lines[index]
        stripped = line.strip()
        alias_definition = _alias_definition_observation(relative_path, line_number, stripped)
        if alias_definition is not None:
            observations.append(alias_definition)
            alias_name = alias_definition.metadata["alias_name"]
            local_aliases[alias_name.lower()] = AliasDefinition(
                alias_name=alias_name,
                target_name=alias_definition.metadata["target_name"],
                target_family=alias_definition.metadata["target_family"],
                source_id=alias_definition.source_id,
            )
            index += 1
            continue
        splat_assignment, end_index, secret_like = _splat_assignment_from_lines(
            relative_path,
            lines,
            index,
        )
        if splat_assignment is not None:
            observations.append(splat_assignment)
            observations.extend(secret_like)
            splat_assignments[splat_assignment.name.lower()] = SplatAssignment(
                variable_name=splat_assignment.name,
                source_id=splat_assignment.source_id,
                known_keys=tuple(splat_assignment.metadata["known_keys"]),
                redacted_keys=tuple(splat_assignment.metadata["redacted_keys"]),
                contains_dynamic_values=splat_assignment.metadata["contains_dynamic_values"],
                key_count=splat_assignment.metadata["key_count"],
            )
            index = end_index + 1
            continue
        if not _is_command_candidate_line(stripped, local_aliases=local_aliases):
            index += 1
            continue
        if _starts_pipeline(stripped):
            index += 1
            continue
        if _line_is_pipeline_start(stripped, local_aliases=local_aliases):
            pipeline_lines, end_index = _collect_pipeline_lines(lines, index)
            observations.extend(
                _pipeline_observations(
                    relative_path,
                    line_number,
                    end_index + 1,
                    pipeline_lines,
                    local_aliases=local_aliases,
                    splat_assignments=splat_assignments,
                )
            )
            index = end_index + 1
            continue
        observations.extend(
            _command_segment_observations(
                relative_path,
                line_number,
                stripped,
                pipeline_id=None,
                pipeline_index=None,
                local_aliases=local_aliases,
                splat_assignments=splat_assignments,
            )
        )
        index += 1
    return tuple(observations)


def _pipeline_observations(
    relative_path: str,
    start_line: int,
    end_line: int,
    pipeline_lines: list[str],
    *,
    local_aliases: dict[str, AliasDefinition] | None = None,
    splat_assignments: dict[str, SplatAssignment] | None = None,
) -> tuple[RawObservation, ...]:
    segments = _pipeline_segments(pipeline_lines)
    pipeline_id = f"{relative_path}#pipeline:{start_line}"
    observations: list[RawObservation] = [
        RawObservation(
            kind="powershell.pipeline",
            source_id=pipeline_id,
            path=relative_path,
            start_line=start_line,
            end_line=end_line,
            name=f"pipeline:{start_line}",
            confidence="heuristic",
            extractor=EXTRACTOR_NAME,
            extractor_version=__version__,
            metadata={
                "pipeline_id": pipeline_id,
                "segment_count": len(segments),
                "static_only": True,
                "powershell_executed": False,
                "object_flow_modeled": False,
            },
        )
    ]
    for offset, segment in enumerate(segments):
        observations.extend(
            _command_segment_observations(
                relative_path,
                min(start_line + offset, end_line),
                segment,
                pipeline_id=pipeline_id,
                pipeline_index=offset,
                local_aliases=local_aliases,
                splat_assignments=splat_assignments,
            )
        )
    return tuple(observations)


def _command_segment_observations(
    relative_path: str,
    line_number: int,
    segment: str,
    *,
    pipeline_id: str | None,
    pipeline_index: int | None,
    local_aliases: dict[str, AliasDefinition] | None = None,
    splat_assignments: dict[str, SplatAssignment] | None = None,
) -> tuple[RawObservation, ...]:
    tokens = _command_tokens(segment)
    if not tokens:
        return ()
    command_token = tokens[0]
    command_info = _command_info(command_token, local_aliases=local_aliases)
    if command_info is None:
        return ()
    normalized, family, alias_expansion, alias_source = command_info
    observations: list[RawObservation] = []
    metadata = _command_metadata(
        command_token,
        normalized,
        family,
        tokens,
        pipeline_id=pipeline_id,
        pipeline_index=pipeline_index,
        alias_expansion=alias_expansion,
        alias_source=alias_source,
    )
    command_source_id = f"{relative_path}#command:{line_number}:{slug(command_token)}"
    if alias_expansion is not None:
        alias_target = (
            f"tool:{normalized}" if family == "external" else f"powershell.command:{normalized}"
        )
        observations.append(
            RawObservation(
                kind="powershell.alias_command",
                source_id=f"{relative_path}#alias-command:{line_number}:{slug(command_token)}",
                path=relative_path,
                start_line=line_number,
                end_line=line_number,
                name=command_token,
                target=alias_target,
                confidence="heuristic",
                extractor=EXTRACTOR_NAME,
                extractor_version=__version__,
                metadata=metadata,
            )
        )
    if family == "external":
        observations.append(
            RawObservation(
                kind="powershell.external_command",
                source_id=f"{relative_path}#external-command:{line_number}:{slug(command_token)}",
                path=relative_path,
                start_line=line_number,
                end_line=line_number,
                name=normalized,
                target=f"tool:{normalized}",
                confidence="heuristic",
                extractor=EXTRACTOR_NAME,
                extractor_version=__version__,
                metadata=metadata,
            )
        )
    else:
        observations.append(
            RawObservation(
                kind="powershell.command",
                source_id=command_source_id,
                path=relative_path,
                start_line=line_number,
                end_line=line_number,
                name=normalized,
                target=f"powershell.command:{normalized}",
                confidence="heuristic",
                extractor=EXTRACTOR_NAME,
                extractor_version=__version__,
                metadata=metadata,
            )
        )
    observations.extend(
        _argument_observations(
            relative_path,
            line_number,
            tokens[1:],
            command_name=normalized,
            command_source_id=command_source_id,
            pipeline_id=pipeline_id,
            pipeline_index=pipeline_index,
            splat_assignments=splat_assignments,
        )
    )
    observations.extend(
        _secret_like_hashtable_observations(
            relative_path,
            line_number,
            segment,
        )
    )
    observations.extend(
        _side_effect_observations_for_command(
            relative_path,
            line_number,
            segment,
            original_token=command_token,
            command_name=normalized,
            command_family=family,
            tokens=tokens,
        )
    )
    return tuple(observations)


def _argument_observations(
    relative_path: str,
    line_number: int,
    tokens: list[str],
    *,
    command_name: str,
    command_source_id: str,
    pipeline_id: str | None,
    pipeline_index: int | None,
    splat_assignments: dict[str, SplatAssignment] | None = None,
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    index = 0
    position = 0
    while index < len(tokens):
        token = tokens[index]
        if token in {"|", ";", "&&", "||"}:
            break
        if token == "@{":
            index = _skip_hashtable(tokens, index)
            continue
        if token == "{":
            break
        if token.startswith("@") and len(token) > 1:
            splat_name = token[1:]
            observations.append(
                _splat_observation(
                    relative_path,
                    line_number,
                    splat_name,
                    command_name=command_name,
                    command_source_id=command_source_id,
                    pipeline_id=pipeline_id,
                    pipeline_index=pipeline_index,
                    assignment=(
                        splat_assignments or {}
                    ).get(splat_name.lower()),
                )
            )
            index += 1
            continue
        if token.startswith("-") and len(token) > 1:
            argument_name = token.lstrip("-")
            value_token: str | None = None
            value_kind = "switch"
            consumed = 1
            if index + 1 < len(tokens) and _token_has_argument_value(tokens[index + 1]):
                value_token = tokens[index + 1]
                consumed = 2
                value_kind = _argument_value_kind(value_token)
                if value_token == "@{":
                    consumed = _skip_hashtable(tokens, index + 1) - index
                    value_token = None
                    value_kind = "hashtable"
            observations.append(
                _command_argument_observation(
                    relative_path,
                    line_number,
                    command_name=command_name,
                    command_source_id=command_source_id,
                    argument_name=argument_name,
                    argument_position=None,
                    value_token=value_token,
                    value_kind=value_kind,
                    pipeline_id=pipeline_id,
                    pipeline_index=pipeline_index,
                )
            )
            if _is_secret_like_name(argument_name):
                observations.append(
                    _secret_like_observation(
                        relative_path,
                        line_number,
                        argument_name,
                        secret_source="command_argument",
                        reason="secret-like command argument name",
                    )
                )
            index += consumed
            continue
        if _token_is_positional_argument(token):
            observations.append(
                _command_argument_observation(
                    relative_path,
                    line_number,
                    command_name=command_name,
                    command_source_id=command_source_id,
                    argument_name=None,
                    argument_position=position,
                    value_token=token,
                    value_kind=_argument_value_kind(token),
                    pipeline_id=pipeline_id,
                    pipeline_index=pipeline_index,
                )
            )
            position += 1
        index += 1
    return tuple(observations)


def _command_argument_observation(
    relative_path: str,
    line_number: int,
    *,
    command_name: str,
    command_source_id: str,
    argument_name: str | None,
    argument_position: int | None,
    value_token: str | None,
    value_kind: str,
    pipeline_id: str | None,
    pipeline_index: int | None,
) -> RawObservation:
    if argument_name is not None:
        argument_label = argument_name
    else:
        assert argument_position is not None
        argument_label = f"position:{argument_position}"
    metadata: dict[str, Any] = {
        "command_name": command_name,
        "command_source_id": command_source_id,
        "value_kind": value_kind,
        "static_only": True,
        "powershell_executed": False,
    }
    if argument_name is not None:
        metadata["argument_name"] = argument_name
    if argument_position is not None:
        metadata["argument_position"] = argument_position
    if pipeline_id is not None:
        metadata["pipeline_id"] = pipeline_id
        metadata["pipeline_index"] = pipeline_index
    redacted = (
        argument_name is not None and _is_secret_like_name(argument_name)
    ) or _is_sensitive_command_argument(command_name, argument_name, argument_position)
    if redacted:
        metadata["redacted"] = True
        metadata["redaction_reason"] = "secret-like command argument name"
        metadata["raw_value_stored"] = False
    elif value_token is not None and value_kind == "static":
        metadata["value"] = _strip_quotes(value_token)
    return RawObservation(
        kind="powershell.command_argument",
        source_id=(
            f"{relative_path}#command-argument:{line_number}:"
            f"{slug(command_name)}:{slug(argument_label)}"
        ),
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=argument_label,
        confidence="heuristic",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
    )


def _secret_like_hashtable_observations(
    relative_path: str,
    line_number: int,
    segment: str,
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    for match in re.finditer(r"(?P<name>[A-Za-z][0-9A-Za-z_-]*)\s*=", segment):
        name = match.group("name")
        if _is_secret_like_name(name):
            observations.append(
                _secret_like_observation(
                    relative_path,
                    line_number,
                    name,
                    secret_source="command_hashtable",
                    reason="secret-like command hashtable key",
                )
            )
    return tuple(observations)


def _command_metadata(
    original_token: str,
    normalized_command: str,
    command_family: str,
    tokens: list[str],
    *,
    pipeline_id: str | None,
    pipeline_index: int | None,
    alias_expansion: str | None,
    alias_source: str | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "original_token": original_token,
        "normalized_command": normalized_command,
        "command_family": command_family,
        "argument_count": max(0, len(tokens) - 1),
        "static_only": True,
        "powershell_executed": False,
    }
    if alias_expansion is not None:
        metadata["alias_expansion"] = alias_expansion
    if alias_source is not None:
        metadata["alias_source"] = alias_source
    if pipeline_id is not None:
        metadata["pipeline_id"] = pipeline_id
        metadata["pipeline_index"] = pipeline_index
    return metadata


def _command_info(
    command_token: str,
    *,
    local_aliases: dict[str, AliasDefinition] | None = None,
) -> tuple[str, str, str | None, str | None] | None:
    token = command_token.strip()
    if not token or token.startswith("$") or token.startswith("&"):
        return None
    alias_expansion = POWERSHELL_ALIASES.get(token.lower())
    if alias_expansion is not None:
        return alias_expansion, "alias", alias_expansion, "builtin"
    local_alias = (local_aliases or {}).get(token.lower())
    if local_alias is not None:
        family = "external" if local_alias.target_family == "external" else "alias"
        return local_alias.target_name, family, local_alias.target_name, "local"
    cmdlet = CANONICAL_CMDLETS.get(token.lower())
    if cmdlet is not None:
        return cmdlet, "cmdlet", None, None
    if token.lower() in EXTERNAL_COMMANDS:
        return token.lower(), "external", None, None
    return None


def _is_command_candidate_line(
    stripped: str,
    *,
    local_aliases: dict[str, AliasDefinition] | None = None,
) -> bool:
    if not stripped or stripped.startswith("#"):
        return False
    first_token = _command_tokens(stripped[:120])
    if not first_token:
        return False
    token = first_token[0]
    if len(first_token) > 1 and first_token[1] == "=":
        return False
    lower = token.lower()
    if lower in COMMAND_SKIP_KEYWORDS:
        return False
    if token in {"}", "{", "|", ";", "&&", "||", "="}:
        return False
    if stripped.startswith(". "):
        return False
    if CALL_OPERATOR_PATTERN.match(stripped) or INVOKE_EXPRESSION_PATTERN.match(stripped):
        return False
    if ASSIGNMENT_PATTERN.match(stripped):
        return False
    if FUNCTION_PATTERN.match(stripped) or PARAM_START_PATTERN.match(stripped):
        return False
    if REQUIRES_PATTERN.match(stripped) or USING_MODULE_PATTERN.match(stripped):
        return False
    return _command_info(token, local_aliases=local_aliases) is not None


def _line_is_pipeline_start(
    stripped: str,
    *,
    local_aliases: dict[str, AliasDefinition] | None = None,
) -> bool:
    return _is_command_candidate_line(stripped, local_aliases=local_aliases) and _has_pipeline_separator(stripped)


def _extract_environment_reference_observations(
    relative_path: str,
    content: str,
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    for index, line in enumerate(_static_scan_lines(content)):
        line_number = index + 1
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ASSIGNMENT_PATTERN.match(stripped):
            continue
        masked = _mask_quoted_strings(line)
        env_write = re.match(
            r"^\s*\$env:(?P<name>[A-Za-z_][0-9A-Za-z_]*)\s*=",
            masked,
            re.IGNORECASE,
        )
        if env_write is not None:
            name = env_write.group("name")
            observations.append(
                _env_observation(
                    "powershell.env_write",
                    relative_path,
                    line_number,
                    name,
                    operation="env-assignment",
                )
            )
            observations.append(
                _host_mutation_observation(
                    relative_path,
                    line_number,
                    operation="env-assignment",
                    command_name="env-assignment",
                    original_token="$env",
                    mutation_category="env_write",
                    target=_target_summary(f"Env:{name}"),
                    destructive=False,
                )
            )
            if _is_secret_like_name(name):
                observations.append(
                    _secret_like_observation(
                        relative_path,
                        line_number,
                        name,
                        secret_source="environment",
                        reason="secret-like environment variable name",
                    )
                )
            continue
        for match in re.finditer(r"\$env:(?P<name>[A-Za-z_][0-9A-Za-z_]*)", masked, re.IGNORECASE):
            observations.append(
                _env_observation(
                    "powershell.env_read",
                    relative_path,
                    line_number,
                    match.group("name"),
                    operation="env-read",
                )
            )
    return tuple(observations)
