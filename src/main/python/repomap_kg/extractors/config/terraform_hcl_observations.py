"""Terraform HCL observation construction and redaction helpers."""

from __future__ import annotations

from typing import Any

from repomap_kg import __version__
from repomap_kg.extractors.config.terraform_hcl_helpers import (
    _terraform_hcl_bounded_string,
    _terraform_hcl_credentialed_url,
    _terraform_hcl_literal_string,
    _terraform_hcl_reference_names,
)
from repomap_kg.extractors.config.terraform_hcl_scan import (
    _TerraformHclAttribute,
    _TerraformHclBlock,
)
from repomap_kg.graph.keys import external_key
from repomap_kg.observations.raw import RawObservation

def _generic_helper(name: str) -> Any:
    from repomap_kg.extractors.config import generic_contracts as generic

    return getattr(generic, name)


def _profile_observation(*args: Any, **kwargs: Any) -> RawObservation:
    return _generic_helper("_profile_observation")(*args, **kwargs)


def _extractor_name() -> str:
    return _generic_helper("EXTRACTOR_NAME")


def _safe_value_summary(value: Any) -> Any:
    return _generic_helper("_safe_value_summary")(value)


def _stable_text_sha256(value: str) -> str:
    return _generic_helper("_stable_text_sha256")(value)


def _value_shape(value: Any) -> Any:
    return _generic_helper("_value_shape")(value)


def _value_type(value: Any) -> str:
    return _generic_helper("_value_type")(value)


def _is_secret_key(value: str) -> bool:
    return _generic_helper("_is_secret_key")(value)


def _is_url(value: str) -> bool:
    return _generic_helper("_is_url")(value)


TERRAFORM_HCL_FORMAT = "terraform-hcl"

TERRAFORM_HCL_PROFILE = "terraform"

TERRAFORM_HCL_TFVARS_PROFILE = "terraform_tfvars"

TERRAFORM_HCL_PARSER = "repo-terraform-hcl-shallow-scanner"

TERRAFORM_HCL_MAX_FILE_BYTES = 1_048_576

TERRAFORM_HCL_MAX_REFERENCES = 512

def _terraform_hcl_block_observation(
    relative_path: str,
    block: _TerraformHclBlock,
) -> RawObservation:
    return _terraform_hcl_observation(
        "terraform.block",
        relative_path,
        metadata={
            "file_family": "tf",
            "block_type": block.block_type,
            "labels": list(block.labels),
        },
        name=".".join((block.block_type, *block.labels)),
        start_line=block.start_line,
        end_line=block.end_line,
        source_suffix=(
            f"terraform-block:{block.block_type}:"
            f"{_stable_text_sha256('|'.join(block.labels))[:16]}:{block.start_line}"
        ),
    )

def _terraform_hcl_observation(
    kind: str,
    relative_path: str,
    *,
    metadata: dict[str, Any],
    profile: str = TERRAFORM_HCL_PROFILE,
    confidence: str = "extracted",
    name: str | None = None,
    target: str | None = None,
    start_line: int | None = None,
    end_line: int | None = None,
    source_suffix: str | None = None,
) -> RawObservation:
    full_metadata = {
        "format": TERRAFORM_HCL_FORMAT,
        "profile": profile,
        **metadata,
    }
    return RawObservation(
        kind=kind,
        source_id=f"{relative_path}#{source_suffix or kind.replace('.', '-')}",
        path=relative_path,
        start_line=start_line,
        end_line=end_line if end_line is not None else start_line,
        name=name,
        target=target,
        confidence=confidence,
        extractor=_extractor_name(),
        extractor_version=__version__,
        metadata=full_metadata,
    )

def _terraform_hcl_reference_observations_from_attribute(
    relative_path: str,
    attribute: _TerraformHclAttribute | None,
    reference_kind: str,
    *,
    target_kind: str = "terraform.reference",
) -> list[RawObservation]:
    if attribute is None:
        return []
    observations: list[RawObservation] = []
    for reference in _terraform_hcl_reference_names(attribute.value):
        observations.append(
            _terraform_hcl_reference_observation(
                relative_path,
                reference_kind,
                reference,
                target=external_key(target_kind, reference),
                start_line=attribute.start_line,
            )
        )
        if len(observations) >= TERRAFORM_HCL_MAX_REFERENCES:
            observations.append(
                _terraform_hcl_parse_error_observation(
                    relative_path,
                    error_kind="terraform-reference-limit",
                    message="Terraform HCL reference limit reached",
                    start_line=attribute.start_line,
                    recovered=True,
                )
            )
            break
    return observations

def _terraform_hcl_reference_observation(
    relative_path: str,
    reference_kind: str,
    raw_value: str,
    *,
    target: str,
    start_line: int | None = None,
    redacted: bool = False,
) -> RawObservation:
    metadata = {
        "file_family": "tf",
        "reference_kind": reference_kind,
        "not_fetched": True,
        "redacted": redacted,
    }
    if not redacted:
        metadata["raw_value_summary"] = _terraform_hcl_bounded_string(raw_value)
    return _terraform_hcl_observation(
        "terraform.reference",
        relative_path,
        confidence="heuristic",
        metadata=metadata,
        target=target,
        start_line=start_line,
        source_suffix=(
            f"terraform-reference:{reference_kind}:"
            f"{_stable_text_sha256(raw_value)[:16]}"
        ),
    )

def _terraform_hcl_redaction_observation(
    relative_path: str,
    *,
    redaction_reason: str,
    field_name: str | None = None,
    start_line: int | None = None,
) -> RawObservation:
    metadata: dict[str, Any] = {
        "file_family": "tf",
        "redaction_reason": redaction_reason,
        "redacted": True,
    }
    if field_name is not None:
        metadata["field_name"] = field_name
    return _terraform_hcl_observation(
        "terraform.redaction",
        relative_path,
        confidence="heuristic",
        metadata=metadata,
        start_line=start_line,
        source_suffix=(
            f"terraform-redaction:{redaction_reason}:"
            f"{_stable_text_sha256(field_name or 'document')[:16]}:"
            f"{start_line or 'document'}"
        ),
    )

def _terraform_hcl_parse_error_observation(
    relative_path: str,
    *,
    error_kind: str,
    message: str,
    start_line: int | None = None,
    recovered: bool,
) -> RawObservation:
    return _terraform_hcl_observation(
        "terraform.parse_error",
        relative_path,
        confidence="unknown",
        metadata={
            "file_family": "tf",
            "parser": TERRAFORM_HCL_PARSER,
            "error_kind": error_kind,
            "message_summary": message[:120],
            "recovered": recovered,
        },
        start_line=start_line,
        source_suffix=f"terraform-parse-error:{error_kind}:{start_line or 'document'}",
    )

def _terraform_hcl_attribute_redactions(
    relative_path: str,
    attributes: list[_TerraformHclAttribute],
) -> list[RawObservation]:
    observations: list[RawObservation] = []
    for attribute in attributes:
        literal = _terraform_hcl_literal_string(attribute.value)
        if _is_secret_key(attribute.name):
            observations.append(
                _terraform_hcl_redaction_observation(
                    relative_path,
                    redaction_reason="secret-prone-terraform-attribute",
                    field_name=attribute.name,
                    start_line=attribute.start_line,
                )
            )
        elif literal is not None and _terraform_hcl_credentialed_url(literal):
            observations.append(
                _terraform_hcl_redaction_observation(
                    relative_path,
                    redaction_reason="credentialed-terraform-url",
                    field_name=attribute.name,
                    start_line=attribute.start_line,
                )
            )
    return observations
