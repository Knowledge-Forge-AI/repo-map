"""Static structured configuration raw observation extraction."""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
import sys
import tomllib
import types
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from repomap_kg import __version__
from repomap_kg.extractors.config import format_contracts as _format_contracts
from repomap_kg.extractors.config import generic_contracts as _generic_contracts
from repomap_kg.extractors.config.jsonc import (
    JsoncNormalizationError,
    _strip_jsonc_comments,
    _strip_jsonc_trailing_commas,
    normalize_jsonc,
)
from repomap_kg.extractors.config.paths import (
    _escape_pointer_segment,
    _pointer_segments,
    json_pointer,
)
from repomap_kg.extractors.config.generic_values import (
    DYNAMIC_MARKERS,
    PATH_KEY_MARKERS,
    SECRET_PRONE_KEYS,
    STABLE_ARRAY_MEMBER_KEYS,
    _document_role,
    _is_dynamic_value,
    _is_secret_key,
    _is_secret_pointer,
    _is_url,
    _looks_like_file_key,
    _looks_like_secret_scalar,
    _normalize_repo_path,
    _normalized_key,
    _resolve_repo_path,
    _safe_value_summary,
    _StableArrayMember,
    _stable_array_members,
    _stable_member_key,
    _value_type,
)
from repomap_kg.extractors.config.generic_profile_helpers import (
    EXTRACTOR_NAME,
    _profile_observation,
    _safe_selected_metadata,
    _stable_text_sha256,
    _stable_value_sha256,
    _url_has_credentials,
    _value_shape,
)
from repomap_kg.extractors.config.generic_structure import (
    ENV_CONTAINER_KEYS,
    ENV_NAME_PATTERN,
    ENV_REFERENCE_PATTERN,
    SIMPLE_COMMAND_PATTERN,
    TOOL_KEYS,
    _detect_references,
    _env_key_reference,
    _file_reference,
    _is_clear_command_name,
    _line_for_pointer,
    _parser_name,
    _path_metadata,
    _path_observation,
    _reference,
    _reference_observations_for_value,
    _string_references,
    _structure_observations,
    _tool_reference_from_command,
    _uses_stable_array_member_paths,
    _walk_value,
)
from repomap_kg.extractors.config.generic_tfjson_profiles import (
    TFJSON_PROFILE_FORMATS,
    _json_pointer_values,
    _tfjson_document_metadata,
    _tfjson_metadata_overrides,
    _tfjson_pointer_is_redacted,
    _tfjson_profile,
    _tfjson_profile_family,
    _tfjson_profile_observations,
    _tfjson_redaction_reason,
)
from repomap_kg.extractors.config.toml_lines import (
    _line_for_toml_pointer,
    _parse_toml_section_lines,
    _TomlSection,
    _toml_array_member_segment,
    _toml_dotted_segments,
    _toml_key_segments,
    _toml_sections,
    _toml_table_header,
)
from repomap_kg.extractors.config.python import (
    PYTHON_MAX_METADATA_STRING,
    PYTHON_MAX_REQUIREMENT_DIAGNOSTICS,
    PYTHON_MAX_REQUIREMENT_REFERENCES,
    PYTHON_MAX_REQUIREMENTS,
    PYTHON_REQUIREMENT_NAME_PATTERN,
    PYTHON_REQUIREMENTS_FORMAT,
    PYTHON_REQUIREMENTS_NAME_PATTERN,
    PYTHON_REQUIREMENTS_PROFILE,
    _extract_python_requirements_observations,
    _is_pyproject_file_name,
    _is_python_requirements_file_name,
    _parse_python_requirement_line,
    _PythonRequirement,
    _python_bounded_string,
    _python_dependency_source_metadata,
    _python_entry_point_observations,
    _python_package_file_observation,
    _python_parse_error_observation,
    _python_pyproject_metadata_overrides,
    _python_pyproject_observations,
    _python_pyproject_value_requires_redaction,
    _python_pyproject_walk,
    _python_redaction_observation,
    _python_reference_observation,
    _python_requirement_extras,
    _python_requirement_file_family,
    _python_requirement_file_reference_observations,
    _python_requirement_is_direct_source,
    _python_requirement_is_local_path,
    _python_requirement_is_vcs_source,
    _python_requirement_line_without_comment,
    _python_requirement_local_path_target,
    _python_requirement_local_path_value,
    _python_requirement_observation,
    _python_requirement_observations_from_values,
    _python_requirement_package_from_source,
    _python_requirement_source_observations,
    _python_requirement_url_reference_observations,
    _python_sequence_count,
    _python_slug,
    _python_value_has_credentialed_url_fragment,
)
from repomap_kg.extractors.config.javascript import (
    TFJSON_FRAMEWORK_DEPENDENCY_HINTS,
    TFJSON_PACKAGE_DEPENDENCY_GROUPS,
    _angular_observations,
    _package_dependency_observations,
    _package_framework_hints,
    _package_json_observations,
    _package_lock_observations,
    _package_reference_observations,
    _playwright_observation,
    _script_command_summary,
    _script_is_secret_prone,
    _typescript_config_observations,
    _typescript_reference_observation,
)
from repomap_kg.extractors.config.terraform import (
    TERRAFORM_HCL_ATTRIBUTE_PATTERN,
    TERRAFORM_HCL_BLOCK_HEADER_PATTERN,
    TERRAFORM_HCL_BLOCK_TYPES,
    TERRAFORM_HCL_FORMAT,
    TERRAFORM_HCL_MAX_ATTRIBUTES_PER_BLOCK,
    TERRAFORM_HCL_MAX_BLOCKS,
    TERRAFORM_HCL_MAX_DIAGNOSTICS,
    TERRAFORM_HCL_MAX_FILE_BYTES,
    TERRAFORM_HCL_MAX_METADATA_STRING,
    TERRAFORM_HCL_MAX_REFERENCES,
    TERRAFORM_HCL_PARSER,
    TERRAFORM_HCL_PROFILE,
    TERRAFORM_HCL_TFVARS_PROFILE,
    TERRAFORM_HCL_TRAVERSAL_PATTERN,
    _extract_terraform_hcl_observations,
    _extract_terraform_hcl_tfvars_observations,
    _is_terraform_hcl_file_name,
    _is_terraform_tfvars_hcl_file_name,
    _TerraformHclAttribute,
    _TerraformHclBlock,
    _terraform_block_names,
    _terraform_hcl_attribute_redactions,
    _terraform_hcl_block_observation,
    _terraform_hcl_block_profile_observations,
    _terraform_hcl_bool_literal,
    _terraform_hcl_bounded_string,
    _terraform_hcl_brace_delta,
    _terraform_hcl_collection_body,
    _terraform_hcl_collection_delta,
    _terraform_hcl_credentialed_url,
    _terraform_hcl_data_observations,
    _terraform_hcl_delimiter_delta,
    _terraform_hcl_expression_kind,
    _terraform_hcl_expression_summary,
    _terraform_hcl_import_observations,
    _terraform_hcl_labels,
    _terraform_hcl_literal_string,
    _terraform_hcl_local_observations,
    _terraform_hcl_local_path_target,
    _terraform_hcl_module_observations,
    _terraform_hcl_module_source,
    _terraform_hcl_move_like_observations,
    _terraform_hcl_nested_block_body,
    _terraform_hcl_nested_block_count,
    _terraform_hcl_nested_block_labels,
    _terraform_hcl_observation,
    _terraform_hcl_output_observations,
    _terraform_hcl_parse_error_observation,
    _terraform_hcl_provider_observations,
    _terraform_hcl_redaction_observation,
    _terraform_hcl_reference_names,
    _terraform_hcl_reference_observation,
    _terraform_hcl_reference_observations_from_attribute,
    _terraform_hcl_resource_observations,
    _terraform_hcl_scan_blocks,
    _terraform_hcl_strip_comment,
    _terraform_hcl_terraform_block_observations,
    _terraform_hcl_text_presence_metadata,
    _terraform_hcl_top_level_attributes,
    _terraform_hcl_value_type,
    _terraform_hcl_variable_observations,
    _terraform_json_observations,
    _terraform_named_block_observations,
    _terraform_reference_observation,
    _terraform_tfvars_observations,
)
from repomap_kg.extractors.config.openapi import (
    OPENAPI_EXAMPLE_KEYS,
    OPENAPI_HTTP_METHODS,
    OPENAPI_MAX_EXAMPLES,
    OPENAPI_MAX_METADATA_STRING,
    OPENAPI_MAX_OPERATIONS,
    OPENAPI_MAX_PARAMETERS_PER_OPERATION,
    OPENAPI_MAX_PATHS,
    OPENAPI_MAX_REFERENCES,
    OPENAPI_MAX_RESPONSES_PER_OPERATION,
    OPENAPI_MAX_SCHEMAS,
    OPENAPI_TEXT_KEYS,
    _is_openapi_document,
    _is_openapi_file_name,
    _openapi_bounded_string,
    _openapi_component_observations,
    _openapi_components,
    _openapi_example_and_redaction_observations,
    _openapi_info_observations,
    _openapi_media_types,
    _openapi_oauth_flow_names,
    _openapi_operation_count,
    _openapi_parameter_observation,
    _openapi_parameters,
    _openapi_parse_error_observation,
    _openapi_path_operation_observations,
    _openapi_pointer_is_redacted,
    _openapi_profile_observations,
    _openapi_redaction_reason,
    _openapi_ref_values,
    _openapi_reference_metadata,
    _openapi_reference_observations,
    _openapi_reference_scope,
    _openapi_request_body_observations,
    _openapi_response_observations,
    _openapi_safe_string,
    _openapi_scope_names,
    _openapi_sensitive_key,
    _openapi_server_count,
    _openapi_server_observations,
    _openapi_source_suffix,
    _openapi_spec_metadata,
    _openapi_string_list,
    _openapi_tag_observations,
    _openapi_text_metadata,
    _openapi_url_metadata,
    _openapi_walk,
)
from repomap_kg.extractors.config.yaml import (
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
    YamlParseError,
    _apply_yaml_profile_metadata,
    _apply_yaml_stable_array_metadata,
    _extract_yaml_observations,
    _looks_like_yaml_mapping_pair,
    _parse_yaml_block,
    _parse_yaml_documents,
    _parse_yaml_inline_mapping,
    _parse_yaml_inline_sequence,
    _parse_yaml_mapping,
    _parse_yaml_plain_scalar,
    _parse_yaml_scalar,
    _parse_yaml_sequence,
    _record_yaml_value_metadata,
    _split_yaml_documents,
    _split_yaml_inline_items,
    _split_yaml_mapping_pair,
    _strip_yaml_comment,
    _unquote_yaml_scalar,
    _YamlLine,
    _YamlParseState,
    _YamlValue,
    _yaml_document_index_from_pointer,
    _yaml_documents,
    _yaml_first_token,
    _yaml_logical_lines,
    _yaml_mapping_colon_index,
    _yaml_openapi_ref,
    _yaml_pointer_is_kubernetes_secret_data,
    _yaml_pointer_is_redacted,
    _yaml_pointer_values,
    _yaml_profile,
    _yaml_redaction_reason,
    _yaml_spring_file_reference_value,
    _yaml_string_references,
    _yaml_uses_reference,
    _yaml_value_or_nested_block,
)
from repomap_kg.extractors.config.xml import (
    GENERIC_XML_FORMAT,
    GENERIC_XML_SAFETY_MODE,
    PLIST_ROOT_PATTERN,
    PLIST_XML_FORMAT,
    PLIST_XML_SAFETY_MODE,
    UNSAFE_PROCESSING_INSTRUCTION_PATTERN,
    UNSAFE_XML_DECLARATION_PATTERN,
    GenericXmlSafetyError,
    PlistXmlParseError,
    PlistXmlSafetyError,
    _check_safe_generic_xml,
    _check_safe_plist_xml,
    _detect_xml_references,
    _extract_generic_xml_observations,
    _extract_plist_xml_observations,
    _generic_xml_document_role,
    _is_placeholder_heavy,
    _is_secret_xml_element,
    _looks_like_plist_xml,
    _looks_like_xml_file_key,
    _plist_dict,
    _plist_root_value,
    _plist_value,
    _walk_xml_element,
    _xml_attribute_metadata,
    _xml_attribute_parts,
    _xml_attribute_semantic_key,
    _xml_child_pointers,
    _xml_direct_child_texts,
    _xml_domain_metadata,
    _xml_element_metadata,
    _xml_file_reference,
    _xml_local_name,
    _xml_name_parts,
    _xml_namespace_summary,
    _xml_parse_error_line,
    _xml_parse_error_observation,
    _xml_parentish_property_name,
    _xml_reference_observations,
    _xml_role_hint,
)
from repomap_kg.extractors.config.infrastructure import (
    _argocd_observations,
    _docker_image_observations,
    _docker_json_observations,
    _is_argocd_json_document,
    _is_docker_compose_document,
    _is_grafana_document,
    _is_kubernetes_document,
    _is_liquibase_json_document,
    _json_image_values,
    _json_pointer_is_kubernetes_secret_data,
    _kubernetes_json_observations,
    _liquibase_changeset_count,
    _liquibase_observations,
    _looks_like_container_image,
)
from repomap_kg.extractors.config.generic_observations import (
    _document_observation,
    _jsonl_record_observation,
    _parse_error_observation,
    _safe_error_message,
)
from repomap_kg.graph.keys import (
    config_document_key,
    config_path_key,
    dynamic_key,
    env_key,
    external_key,
    external_url_key,
    file_key,
    tool_key,
    unknown_key,
    xml_attribute_key,
    xml_document_key,
    xml_element_key,
)
from repomap_kg.observations.raw import RawObservation


def extract_config_file_observations(
    relative_path: str,
    content: str,
) -> tuple[RawObservation, ...]:
    suffix = PurePosixPath(relative_path).suffix.lower()
    if _is_python_requirements_file_name(relative_path):
        return _extract_python_requirements_observations(relative_path, content)
    if _is_terraform_hcl_file_name(relative_path):
        return _extract_terraform_hcl_observations(relative_path, content)
    if _is_terraform_tfvars_hcl_file_name(relative_path):
        return _extract_terraform_hcl_tfvars_observations(relative_path, content)
    if suffix == ".jsonl":
        return _extract_jsonl_observations(relative_path, content)
    if suffix == ".jsonc":
        return _extract_jsonc_observations(relative_path, content)
    if suffix == ".toml":
        return _extract_toml_observations(relative_path, content)
    if suffix in (".yaml", ".yml"):
        return _extract_yaml_observations(relative_path, content)
    if suffix == ".plist":
        return _extract_plist_xml_observations(relative_path, content)
    if suffix == ".xml":
        if _looks_like_plist_xml(content):
            return _extract_plist_xml_observations(relative_path, content)
        return _extract_generic_xml_observations(relative_path, content)
    return _extract_json_observations(relative_path, content)


def _extract_json_observations(
    relative_path: str,
    content: str,
) -> tuple[RawObservation, ...]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as error:
        parse_error = _parse_error_observation(
            relative_path,
            format_name="json",
            error_kind="malformed-json",
            error=error,
            recovered=False,
        )
        if _is_openapi_file_name(relative_path):
            return (
                parse_error,
                _openapi_parse_error_observation(
                    relative_path,
                    format_name="json",
                    error_kind="malformed-openapi-json",
                    message=str(error),
                    start_line=error.lineno,
                ),
            )
        return (
            parse_error,
        )
    profile = _tfjson_profile(relative_path, parsed, format_name="json")
    metadata_overrides = _tfjson_metadata_overrides(
        relative_path,
        parsed,
        profile=profile,
    )
    path_observations, reference_observations = _structure_observations(
        relative_path,
        parsed,
        format_name="json",
        confidence="extracted",
        content=content,
        metadata_overrides=metadata_overrides,
    )
    profile_observations = _tfjson_profile_observations(
        relative_path,
        parsed,
        format_name="json",
        confidence="extracted",
        profile=profile,
        content=content,
    )
    document = _document_observation(
        relative_path,
        format_name="json",
        parser="stdlib-json",
        confidence="extracted",
        top_level_type=_value_type(parsed),
        path_count=len(path_observations),
        record_count=None,
        parse_error_count=0,
        extra_metadata=_tfjson_document_metadata(profile),
    )
    return (document, *profile_observations, *path_observations, *reference_observations)


def _extract_jsonc_observations(
    relative_path: str,
    content: str,
) -> tuple[RawObservation, ...]:
    try:
        normalized = normalize_jsonc(content)
        parsed = json.loads(normalized)
    except JsoncNormalizationError as error:
        return (
            _parse_error_observation(
                relative_path,
                format_name="jsonc",
                error_kind="unsupported-jsonc-construct",
                message=str(error),
                recovered=False,
            ),
        )
    except json.JSONDecodeError as error:
        return (
            _parse_error_observation(
                relative_path,
                format_name="jsonc",
                error_kind="malformed-jsonc",
                error=error,
                recovered=False,
            ),
        )
    profile = _tfjson_profile(relative_path, parsed, format_name="jsonc")
    metadata_overrides = _tfjson_metadata_overrides(
        relative_path,
        parsed,
        profile=profile,
    )
    path_observations, reference_observations = _structure_observations(
        relative_path,
        parsed,
        format_name="jsonc",
        confidence="heuristic",
        content=content,
        metadata_overrides=metadata_overrides,
    )
    profile_observations = _tfjson_profile_observations(
        relative_path,
        parsed,
        format_name="jsonc",
        confidence="heuristic",
        profile=profile,
        content=content,
    )
    document = _document_observation(
        relative_path,
        format_name="jsonc",
        parser="jsonc-conservative",
        confidence="heuristic",
        top_level_type=_value_type(parsed),
        path_count=len(path_observations),
        record_count=None,
        parse_error_count=0,
        extra_metadata=_tfjson_document_metadata(profile),
    )
    return (document, *profile_observations, *path_observations, *reference_observations)


def _extract_jsonl_observations(
    relative_path: str,
    content: str,
) -> tuple[RawObservation, ...]:
    path_observations: list[RawObservation] = []
    reference_observations: list[RawObservation] = []
    records: list[RawObservation] = []
    errors: list[RawObservation] = []
    parseable_record_index = 0
    for line_number, line in enumerate(content.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as error:
            errors.append(
                _parse_error_observation(
                    relative_path,
                    format_name="jsonl",
                    error_kind="malformed-jsonl-line",
                    error=error,
                    start_line=line_number,
                    recovered=True,
                )
            )
            continue
        records.append(
            _jsonl_record_observation(
                relative_path,
                parsed,
                line_number=line_number,
                record_index=parseable_record_index,
            )
        )
        if isinstance(parsed, dict):
            paths, references = _structure_observations(
                relative_path,
                parsed,
                format_name="jsonl",
                confidence="extracted",
                content=line,
                source_suffix=f":record-{parseable_record_index}",
                line_offset=line_number - 1,
            )
            path_observations.extend(paths)
            reference_observations.extend(references)
        parseable_record_index += 1
    document = _document_observation(
        relative_path,
        format_name="jsonl",
        parser="stdlib-json",
        confidence="extracted" if not errors else "heuristic",
        top_level_type="mixed-jsonl",
        path_count=len(path_observations),
        record_count=len(records),
        parse_error_count=len(errors),
    )
    return (
        document,
        *records,
        *path_observations,
        *reference_observations,
        *errors,
    )


def _extract_toml_observations(
    relative_path: str,
    content: str,
) -> tuple[RawObservation, ...]:
    try:
        parsed = tomllib.loads(content)
    except tomllib.TOMLDecodeError as error:
        parse_error = _parse_error_observation(
            relative_path,
            format_name="toml",
            error_kind="malformed-toml",
            message=str(error),
            start_line=getattr(error, "lineno", None),
            recovered=False,
        )
        if _is_pyproject_file_name(relative_path):
            return (
                parse_error,
                _python_parse_error_observation(
                    relative_path,
                    error_kind="malformed-pyproject-toml",
                    message=str(error),
                    start_line=getattr(error, "lineno", None),
                    source_suffix="pyproject",
                ),
            )
        return (parse_error,)
    metadata_overrides = (
        _python_pyproject_metadata_overrides(parsed)
        if _is_pyproject_file_name(relative_path)
        else None
    )
    path_observations, reference_observations = _structure_observations(
        relative_path,
        parsed,
        format_name="toml",
        confidence="extracted",
        content=content,
        metadata_overrides=metadata_overrides,
    )
    profile_observations: tuple[RawObservation, ...] = ()
    if _is_pyproject_file_name(relative_path):
        profile_observations = _python_pyproject_observations(
            relative_path,
            parsed,
            format_name="toml",
            confidence="extracted",
        )
    document = _document_observation(
        relative_path,
        format_name="toml",
        parser="stdlib-tomllib",
        confidence="extracted",
        top_level_type=_value_type(parsed),
        path_count=len(path_observations),
        record_count=None,
        parse_error_count=0,
    )
    return (document, *profile_observations, *path_observations, *reference_observations)


_FORMAT_CONTRACT_NAMES = frozenset(
    {
        "GENERIC_XML_FORMAT",
        "GENERIC_XML_SAFETY_MODE",
        "PLIST_ROOT_PATTERN",
        "PLIST_XML_FORMAT",
        "PLIST_XML_SAFETY_MODE",
        "UNSAFE_PROCESSING_INSTRUCTION_PATTERN",
        "UNSAFE_XML_DECLARATION_PATTERN",
        "YAML_ALIAS_PATTERN",
        "YAML_ANCHOR_PATTERN",
        "YAML_FORMAT",
        "YAML_MAX_ALIASES",
        "YAML_MAX_DEPTH",
        "YAML_MAX_DOCUMENTS",
        "YAML_MAX_FILE_BYTES",
        "YAML_MAX_NODES",
        "YAML_MAX_SCALAR_LENGTH",
        "YAML_PARSER",
        "YAML_SIMPLE_IMAGE_PATTERN",
        "YAML_TAG_PATTERN",
    }
)


class _GenericFacadeModule(types.ModuleType):
    """Keep patched facade format values synchronized with their owner."""

    def __setattr__(self, name: str, value: object) -> None:
        super().__setattr__(name, value)
        if name in _FORMAT_CONTRACT_NAMES:
            setattr(_format_contracts, name, value)
            setattr(_generic_contracts, name, value)


sys.modules[__name__].__class__ = _GenericFacadeModule
