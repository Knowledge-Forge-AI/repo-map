"""Terraform HCL block scanning and profile observation builders."""

from __future__ import annotations

from typing import Any

from repomap_kg import __version__
from repomap_kg.extractors.config.terraform_hcl_helpers import (
    TERRAFORM_HCL_BLOCK_HEADER_PATTERN,
    TERRAFORM_HCL_MAX_METADATA_STRING,
    TERRAFORM_HCL_TRAVERSAL_PATTERN,
    _is_terraform_hcl_file_name,
    _is_terraform_tfvars_hcl_file_name,
    _terraform_hcl_bool_literal,
    _terraform_hcl_bounded_string,
    _terraform_hcl_brace_delta,
    _terraform_hcl_collection_body,
    _terraform_hcl_collection_delta,
    _terraform_hcl_credentialed_url,
    _terraform_hcl_delimiter_delta,
    _terraform_hcl_expression_kind,
    _terraform_hcl_expression_summary,
    _terraform_hcl_labels,
    _terraform_hcl_literal_string,
    _terraform_hcl_local_path_target,
    _terraform_hcl_module_source,
    _terraform_hcl_nested_block_body,
    _terraform_hcl_nested_block_count,
    _terraform_hcl_nested_block_labels,
    _terraform_hcl_reference_names,
    _terraform_hcl_strip_comment,
    _terraform_hcl_text_presence_metadata,
    _terraform_hcl_value_type,
)
from repomap_kg.extractors.config.terraform_hcl_scan import (
    TERRAFORM_HCL_ATTRIBUTE_PATTERN,
    TERRAFORM_HCL_BLOCK_TYPES,
    TERRAFORM_HCL_MAX_ATTRIBUTES_PER_BLOCK,
    TERRAFORM_HCL_MAX_BLOCKS,
    TERRAFORM_HCL_MAX_DIAGNOSTICS,
    _TerraformHclAttribute,
    _TerraformHclBlock,
    _terraform_hcl_scan_blocks as _scan_terraform_hcl_blocks,
    _terraform_hcl_top_level_attributes as _scan_terraform_hcl_top_level_attributes,
)
from repomap_kg.extractors.config.terraform_hcl_observations import (
    TERRAFORM_HCL_FORMAT,
    TERRAFORM_HCL_MAX_FILE_BYTES,
    TERRAFORM_HCL_MAX_REFERENCES,
    TERRAFORM_HCL_PARSER,
    TERRAFORM_HCL_PROFILE,
    TERRAFORM_HCL_TFVARS_PROFILE,
    _is_secret_key,
    _is_url,
    _profile_observation,
    _safe_value_summary,
    _stable_text_sha256,
    _terraform_hcl_attribute_redactions,
    _terraform_hcl_block_observation,
    _terraform_hcl_observation,
    _terraform_hcl_parse_error_observation,
    _terraform_hcl_redaction_observation,
    _terraform_hcl_reference_observation,
    _terraform_hcl_reference_observations_from_attribute,
    _value_shape,
    _value_type,
)
from repomap_kg.graph.keys import external_key
from repomap_kg.observations.raw import RawObservation


def _terraform_hcl_scan_blocks(
    relative_path: str,
    content: str,
) -> tuple[list[_TerraformHclBlock], list[RawObservation]]:
    return _scan_terraform_hcl_blocks(
        relative_path,
        content,
        parse_error_observation=_terraform_hcl_parse_error_observation,
    )


def _terraform_hcl_top_level_attributes(
    relative_path: str,
    content: str,
    *,
    base_line: int,
) -> tuple[list[_TerraformHclAttribute], list[RawObservation]]:
    return _scan_terraform_hcl_top_level_attributes(
        relative_path,
        content,
        base_line=base_line,
        parse_error_observation=_terraform_hcl_parse_error_observation,
    )

def _terraform_hcl_block_profile_observations(
    relative_path: str,
    block: _TerraformHclBlock,
) -> list[RawObservation]:
    attributes, diagnostics = _terraform_hcl_top_level_attributes(
        relative_path,
        block.body,
        base_line=block.start_line + 1,
    )
    by_name = {attribute.name: attribute for attribute in attributes}
    observations: list[RawObservation] = list(diagnostics)
    observations.extend(
        _terraform_hcl_attribute_redactions(relative_path, attributes)
    )
    if block.block_type == "terraform":
        observations.extend(
            _terraform_hcl_terraform_block_observations(
                relative_path,
                block,
                by_name,
            )
        )
    elif block.block_type == "provider":
        observations.extend(
            _terraform_hcl_provider_observations(relative_path, block, by_name)
        )
    elif block.block_type == "resource":
        observations.extend(
            _terraform_hcl_resource_observations(relative_path, block, by_name)
        )
    elif block.block_type == "data":
        observations.extend(_terraform_hcl_data_observations(relative_path, block))
    elif block.block_type == "module":
        observations.extend(
            _terraform_hcl_module_observations(relative_path, block, by_name)
        )
    elif block.block_type == "variable":
        observations.extend(
            _terraform_hcl_variable_observations(relative_path, block, by_name)
        )
    elif block.block_type == "output":
        observations.extend(
            _terraform_hcl_output_observations(relative_path, block, by_name)
        )
    elif block.block_type == "locals":
        observations.extend(_terraform_hcl_local_observations(relative_path, attributes))
    elif block.block_type == "moved":
        observations.extend(
            _terraform_hcl_move_like_observations(
                relative_path,
                "terraform.moved",
                block,
                by_name,
                fields=("from", "to"),
            )
        )
    elif block.block_type == "import":
        observations.extend(_terraform_hcl_import_observations(relative_path, block, by_name))
    elif block.block_type == "removed":
        observations.extend(
            _terraform_hcl_move_like_observations(
                relative_path,
                "terraform.removed",
                block,
                by_name,
                fields=("from",),
            )
        )
    elif block.block_type == "check":
        observations.append(
            _terraform_hcl_observation(
                "terraform.check",
                relative_path,
                confidence="heuristic",
                metadata={
                    "file_family": "tf",
                    "check_name": block.labels[0] if block.labels else None,
                    "assertion_count": _terraform_hcl_nested_block_count(
                        block.body,
                        "assert",
                    ),
                },
                name=block.labels[0] if block.labels else None,
                start_line=block.start_line,
                end_line=block.end_line,
                source_suffix=f"terraform-check:{block.labels[0] if block.labels else block.start_line}",
            )
        )
    return observations

def _terraform_hcl_terraform_block_observations(
    relative_path: str,
    block: _TerraformHclBlock,
    attributes: dict[str, _TerraformHclAttribute],
) -> list[RawObservation]:
    observations: list[RawObservation] = []
    required_version = attributes.get("required_version")
    if required_version is not None:
        version_constraint = _terraform_hcl_literal_string(required_version.value)
        if version_constraint is None:
            version_constraint = _terraform_hcl_expression_summary(required_version.value)
        observations.append(
            _terraform_hcl_observation(
                "terraform.required_version",
                relative_path,
                confidence="heuristic",
                metadata={
                    "file_family": "tf",
                    "version_constraint": version_constraint,
                    "expression_kind": _terraform_hcl_expression_kind(
                        required_version.value
                    ),
                },
                start_line=required_version.start_line,
                source_suffix="terraform-required-version",
            )
        )
        observations.append(
            _terraform_hcl_reference_observation(
                relative_path,
                "required_version",
                version_constraint,
                target=external_key("terraform.version", version_constraint),
                start_line=required_version.start_line,
            )
        )

    required_providers_body = _terraform_hcl_nested_block_body(
        block.body,
        "required_providers",
    )
    if required_providers_body is not None:
        provider_attributes, diagnostics = _terraform_hcl_top_level_attributes(
            relative_path,
            required_providers_body,
            base_line=block.start_line,
        )
        observations.extend(diagnostics)
        for provider in provider_attributes:
            provider_body = _terraform_hcl_collection_body(provider.value)
            provider_source = provider.name
            version_constraint = None
            if provider_body is not None:
                provider_config, provider_diagnostics = _terraform_hcl_top_level_attributes(
                    relative_path,
                    provider_body,
                    base_line=provider.start_line,
                )
                observations.extend(provider_diagnostics)
                provider_fields = {item.name: item for item in provider_config}
                source = provider_fields.get("source")
                version = provider_fields.get("version")
                if source is not None:
                    provider_source = (
                        _terraform_hcl_literal_string(source.value) or provider.name
                    )
                if version is not None:
                    version_constraint = (
                        _terraform_hcl_literal_string(version.value)
                        or _terraform_hcl_expression_summary(version.value)
                    )
            observations.append(
                _terraform_hcl_observation(
                    "terraform.required_provider",
                    relative_path,
                    confidence="heuristic",
                    metadata={
                        "file_family": "tf",
                        "provider_name": provider.name,
                        "provider_source": provider_source,
                        "version_constraint": version_constraint,
                        "not_fetched": True,
                    },
                    name=provider.name,
                    target=external_key("terraform.provider", provider_source),
                    start_line=provider.start_line,
                    source_suffix=f"terraform-required-provider:{provider.name}",
                )
            )
            observations.append(
                _terraform_hcl_reference_observation(
                    relative_path,
                    "provider_source",
                    provider_source,
                    target=external_key("terraform.provider", provider_source),
                    start_line=provider.start_line,
                )
            )

    for backend_type in _terraform_hcl_nested_block_labels(block.body, "backend"):
        observations.append(
            _terraform_hcl_observation(
                "terraform.backend",
                relative_path,
                confidence="heuristic",
                metadata={
                    "file_family": "tf",
                    "backend_type": backend_type,
                    "not_fetched": True,
                },
                name=backend_type,
                source_suffix=f"terraform-backend:{backend_type}",
                start_line=block.start_line,
            )
        )
    return observations

def _terraform_hcl_provider_observations(
    relative_path: str,
    block: _TerraformHclBlock,
    attributes: dict[str, _TerraformHclAttribute],
) -> list[RawObservation]:
    provider_name = block.labels[0] if block.labels else "unknown"
    alias = None
    if "alias" in attributes:
        alias = _terraform_hcl_literal_string(attributes["alias"].value)
    return [
        _terraform_hcl_observation(
            "terraform.provider",
            relative_path,
            confidence="heuristic",
            metadata={
                "file_family": "tf",
                "provider_name": provider_name,
                "alias": alias,
            },
            name=provider_name,
            start_line=block.start_line,
            end_line=block.end_line,
            source_suffix=f"terraform-provider:{provider_name}:{alias or 'default'}",
        )
    ]

def _terraform_hcl_resource_observations(
    relative_path: str,
    block: _TerraformHclBlock,
    attributes: dict[str, _TerraformHclAttribute],
) -> list[RawObservation]:
    resource_type = block.labels[0] if len(block.labels) >= 1 else "unknown"
    resource_name = block.labels[1] if len(block.labels) >= 2 else "unknown"
    observations = [
        _terraform_hcl_observation(
            "terraform.resource",
            relative_path,
            confidence="heuristic",
            metadata={
                "file_family": "tf",
                "resource_type": resource_type,
                "resource_name": resource_name,
                "provider_prefix": resource_type.split("_", 1)[0]
                if "_" in resource_type
                else resource_type,
                "count_present": "count" in attributes,
                "for_each_present": "for_each" in attributes,
                "lifecycle_present": _terraform_hcl_nested_block_count(
                    block.body,
                    "lifecycle",
                )
                > 0,
                "connection_present": _terraform_hcl_nested_block_count(
                    block.body,
                    "connection",
                )
                > 0,
                "provisioner_present": _terraform_hcl_nested_block_count(
                    block.body,
                    "provisioner",
                )
                > 0,
            },
            name=f"{resource_type}.{resource_name}",
            start_line=block.start_line,
            end_line=block.end_line,
            source_suffix=f"terraform-resource:{resource_type}:{resource_name}",
        )
    ]
    observations.extend(
        _terraform_hcl_reference_observations_from_attribute(
            relative_path,
            attributes.get("depends_on"),
            "depends_on",
        )
    )
    observations.extend(
        _terraform_hcl_reference_observations_from_attribute(
            relative_path,
            attributes.get("provider"),
            "provider_alias",
            target_kind="terraform.provider",
        )
    )
    return observations

def _terraform_hcl_data_observations(
    relative_path: str,
    block: _TerraformHclBlock,
) -> list[RawObservation]:
    data_source_type = block.labels[0] if len(block.labels) >= 1 else "unknown"
    data_source_name = block.labels[1] if len(block.labels) >= 2 else "unknown"
    return [
        _terraform_hcl_observation(
            "terraform.data_source",
            relative_path,
            confidence="heuristic",
            metadata={
                "file_family": "tf",
                "data_source_type": data_source_type,
                "data_source_name": data_source_name,
                "not_fetched": True,
            },
            name=f"{data_source_type}.{data_source_name}",
            start_line=block.start_line,
            end_line=block.end_line,
            source_suffix=f"terraform-data-source:{data_source_type}:{data_source_name}",
        )
    ]

def _terraform_hcl_module_observations(
    relative_path: str,
    block: _TerraformHclBlock,
    attributes: dict[str, _TerraformHclAttribute],
) -> list[RawObservation]:
    module_name = block.labels[0] if block.labels else "unknown"
    metadata: dict[str, Any] = {"file_family": "tf", "module_name": module_name}
    target = None
    observations: list[RawObservation] = []
    source = attributes.get("source")
    if source is not None:
        source_value = _terraform_hcl_literal_string(source.value)
        if source_value is not None:
            source_metadata, target, reference_kind = _terraform_hcl_module_source(
                relative_path,
                source_value,
            )
            metadata.update(source_metadata)
            observations.append(
                _terraform_hcl_reference_observation(
                    relative_path,
                    reference_kind,
                    source_value,
                    target=target,
                    start_line=source.start_line,
                    redacted=bool(source_metadata.get("redacted")),
                )
            )
        else:
            metadata.update(
                {
                    "source_expression_kind": _terraform_hcl_expression_kind(
                        source.value
                    ),
                    "dynamic": True,
                    "not_fetched": True,
                }
            )
    observations.insert(
        0,
        _terraform_hcl_observation(
            "terraform.module",
            relative_path,
            confidence="heuristic",
            metadata=metadata,
            name=module_name,
            target=target,
            start_line=block.start_line,
            end_line=block.end_line,
            source_suffix=f"terraform-module:{module_name}",
        ),
    )
    return observations

def _terraform_hcl_variable_observations(
    relative_path: str,
    block: _TerraformHclBlock,
    attributes: dict[str, _TerraformHclAttribute],
) -> list[RawObservation]:
    variable_name = block.labels[0] if block.labels else "unknown"
    default = attributes.get("default")
    type_attr = attributes.get("type")
    description = attributes.get("description")
    metadata: dict[str, Any] = {
        "file_family": "tf",
        "variable_name": variable_name,
        "default_present": default is not None,
        "validation_present": _terraform_hcl_nested_block_count(
            block.body,
            "validation",
        )
        > 0,
    }
    if type_attr is not None:
        metadata["type_expression_kind"] = _terraform_hcl_expression_kind(
            type_attr.value
        )
        metadata["type_summary"] = _terraform_hcl_expression_summary(type_attr.value)
    if default is not None:
        metadata["default_value_type"] = _terraform_hcl_value_type(default.value)
        metadata["default_expression_kind"] = _terraform_hcl_expression_kind(
            default.value
        )
    if "sensitive" in attributes:
        metadata["sensitive"] = _terraform_hcl_bool_literal(
            attributes["sensitive"].value
        )
    if description is not None:
        metadata.update(_terraform_hcl_text_presence_metadata("description", description.value))
    return [
        _terraform_hcl_observation(
            "terraform.variable",
            relative_path,
            confidence="heuristic",
            metadata=metadata,
            name=variable_name,
            start_line=block.start_line,
            end_line=block.end_line,
            source_suffix=f"terraform-variable:{variable_name}",
        )
    ]

def _terraform_hcl_output_observations(
    relative_path: str,
    block: _TerraformHclBlock,
    attributes: dict[str, _TerraformHclAttribute],
) -> list[RawObservation]:
    output_name = block.labels[0] if block.labels else "unknown"
    value = attributes.get("value")
    metadata: dict[str, Any] = {
        "file_family": "tf",
        "output_name": output_name,
        "value_expression_kind": _terraform_hcl_expression_kind(value.value)
        if value is not None
        else "unknown",
        "value_redacted": True,
    }
    if "sensitive" in attributes:
        metadata["sensitive"] = _terraform_hcl_bool_literal(
            attributes["sensitive"].value
        )
    if "description" in attributes:
        metadata.update(
            _terraform_hcl_text_presence_metadata(
                "description",
                attributes["description"].value,
            )
        )
    return [
        _terraform_hcl_observation(
            "terraform.output",
            relative_path,
            confidence="heuristic",
            metadata=metadata,
            name=output_name,
            start_line=block.start_line,
            end_line=block.end_line,
            source_suffix=f"terraform-output:{output_name}",
        )
    ]

def _terraform_hcl_local_observations(
    relative_path: str,
    attributes: list[_TerraformHclAttribute],
) -> list[RawObservation]:
    observations: list[RawObservation] = []
    for attribute in attributes[:TERRAFORM_HCL_MAX_ATTRIBUTES_PER_BLOCK]:
        redacted = _is_secret_key(attribute.name)
        observations.append(
            _terraform_hcl_observation(
                "terraform.local",
                relative_path,
                confidence="heuristic",
                metadata={
                    "file_family": "tf",
                    "local_name": attribute.name,
                    "expression_kind": "redacted"
                    if redacted
                    else _terraform_hcl_expression_kind(attribute.value),
                    "redacted": redacted,
                },
                name=attribute.name,
                start_line=attribute.start_line,
                source_suffix=f"terraform-local:{attribute.name}",
            )
        )
        if redacted:
            observations.append(
                _terraform_hcl_redaction_observation(
                    relative_path,
                    redaction_reason="secret-prone-terraform-local",
                    field_name=attribute.name,
                    start_line=attribute.start_line,
                )
            )
    return observations

def _terraform_hcl_move_like_observations(
    relative_path: str,
    kind: str,
    block: _TerraformHclBlock,
    attributes: dict[str, _TerraformHclAttribute],
    *,
    fields: tuple[str, ...],
) -> list[RawObservation]:
    metadata: dict[str, Any] = {"file_family": "tf"}
    for field in fields:
        attribute = attributes.get(field)
        if attribute is not None:
            metadata[f"{field}_summary"] = _terraform_hcl_expression_summary(
                attribute.value
            )
    return [
        _terraform_hcl_observation(
            kind,
            relative_path,
            confidence="heuristic",
            metadata=metadata,
            start_line=block.start_line,
            end_line=block.end_line,
            source_suffix=f"{kind.replace('.', '-')}:{block.start_line}",
        )
    ]

def _terraform_hcl_import_observations(
    relative_path: str,
    block: _TerraformHclBlock,
    attributes: dict[str, _TerraformHclAttribute],
) -> list[RawObservation]:
    target = attributes.get("to")
    import_id = attributes.get("id")
    metadata: dict[str, Any] = {
        "file_family": "tf",
        "id_redacted": import_id is not None,
    }
    if target is not None:
        metadata["to_summary"] = _terraform_hcl_expression_summary(target.value)
    if import_id is not None:
        metadata["id_expression_kind"] = _terraform_hcl_expression_kind(import_id.value)
        metadata["redacted"] = True
        metadata["redaction_reason"] = "terraform-import-id-sensitive-by-default"
    observations = [
        _terraform_hcl_observation(
            "terraform.import",
            relative_path,
            confidence="heuristic",
            metadata=metadata,
            start_line=block.start_line,
            end_line=block.end_line,
            source_suffix=f"terraform-import:{block.start_line}",
        )
    ]
    if import_id is not None:
        observations.append(
            _terraform_hcl_redaction_observation(
                relative_path,
                redaction_reason="terraform-import-id-sensitive-by-default",
                field_name="id",
                start_line=import_id.start_line,
            )
        )
    return observations
