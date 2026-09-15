"""Terraform JSON/HCL/tfvars configuration raw observation extraction."""

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
from repomap_kg.extractors.config.terraform_json import (
    _terraform_block_names,
    _terraform_json_observations,
    _terraform_named_block_observations,
    _terraform_reference_observation,
    _terraform_tfvars_observations,
)
from repomap_kg.graph.keys import external_key
from repomap_kg.observations.raw import RawObservation
from repomap_kg.extractors.config.terraform_hcl_observations import (
    TERRAFORM_HCL_FORMAT,
    TERRAFORM_HCL_MAX_FILE_BYTES,
    TERRAFORM_HCL_MAX_REFERENCES,
    TERRAFORM_HCL_PARSER,
    TERRAFORM_HCL_PROFILE,
    TERRAFORM_HCL_TFVARS_PROFILE,
    _extractor_name,
    _generic_helper,
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
from repomap_kg.extractors.config.terraform_hcl_profiles import (
    _terraform_hcl_block_profile_observations,
    _terraform_hcl_data_observations,
    _terraform_hcl_import_observations,
    _terraform_hcl_local_observations,
    _terraform_hcl_module_observations,
    _terraform_hcl_move_like_observations,
    _terraform_hcl_output_observations,
    _terraform_hcl_provider_observations,
    _terraform_hcl_resource_observations,
    _terraform_hcl_scan_blocks,
    _terraform_hcl_terraform_block_observations,
    _terraform_hcl_top_level_attributes,
    _terraform_hcl_variable_observations,
)


def _extract_terraform_hcl_observations(
    relative_path: str,
    content: str,
) -> tuple[RawObservation, ...]:
    diagnostics: list[RawObservation] = []
    observations: list[RawObservation] = []
    encoded_size = len(content.encode("utf-8"))
    observations.append(
        _terraform_hcl_observation(
            "terraform.file",
            relative_path,
            metadata={
                "file_family": "tf",
                "parser": TERRAFORM_HCL_PARSER,
                "byte_count": encoded_size,
            },
            source_suffix="terraform-file",
        )
    )
    if encoded_size > TERRAFORM_HCL_MAX_FILE_BYTES:
        observations.append(
            _terraform_hcl_parse_error_observation(
                relative_path,
                error_kind="terraform-file-byte-limit",
                message="Terraform HCL file exceeds conservative byte limit",
                recovered=False,
            )
        )
        return tuple(observations)

    blocks, block_diagnostics = _terraform_hcl_scan_blocks(relative_path, content)
    observations.extend(block_diagnostics)
    for block in blocks:
        observations.append(_terraform_hcl_block_observation(relative_path, block))
        observations.extend(_terraform_hcl_block_profile_observations(relative_path, block))
    return tuple(observations)

def _extract_terraform_hcl_tfvars_observations(
    relative_path: str,
    content: str,
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    encoded_size = len(content.encode("utf-8"))
    observations.append(
        _terraform_hcl_observation(
            "terraform.file",
            relative_path,
            profile=TERRAFORM_HCL_TFVARS_PROFILE,
            metadata={
                "file_family": "tfvars",
                "parser": TERRAFORM_HCL_PARSER,
                "byte_count": encoded_size,
                "all_values_sensitive": True,
            },
            source_suffix="terraform-file",
        )
    )
    if encoded_size > TERRAFORM_HCL_MAX_FILE_BYTES:
        observations.append(
            _terraform_hcl_parse_error_observation(
                relative_path,
                error_kind="terraform-file-byte-limit",
                message="Terraform tfvars file exceeds conservative byte limit",
                recovered=False,
            )
        )
        return tuple(observations)

    attributes, diagnostics = _terraform_hcl_top_level_attributes(
        relative_path,
        content,
        base_line=1,
    )
    observations.extend(diagnostics)
    for attribute in attributes:
        value_type = _terraform_hcl_value_type(attribute.value)
        observations.append(
            _terraform_hcl_observation(
                "terraform.variable",
                relative_path,
                profile=TERRAFORM_HCL_TFVARS_PROFILE,
                confidence="heuristic",
                metadata={
                    "file_family": "tfvars",
                    "variable_name": attribute.name,
                    "value_type": value_type,
                    "value_shape": {"type": value_type},
                    "redacted": True,
                    "redaction_reason": "tfvars-sensitive-by-default",
                },
                name=attribute.name,
                start_line=attribute.start_line,
                source_suffix=f"terraform-variable:{attribute.name}",
            )
        )
        observations.append(
            _terraform_hcl_redaction_observation(
                relative_path,
                redaction_reason="tfvars-sensitive-by-default",
                field_name=attribute.name,
                start_line=attribute.start_line,
            )
        )
    return tuple(observations)
