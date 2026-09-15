"""Terraform HCL block and attribute scanning helpers."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from repomap_kg.extractors.config.terraform_hcl_helpers import (
    TERRAFORM_HCL_BLOCK_HEADER_PATTERN,
    _terraform_hcl_brace_delta,
    _terraform_hcl_collection_delta,
    _terraform_hcl_labels,
    _terraform_hcl_strip_comment,
)
from repomap_kg.observations.raw import RawObservation


_TerraformHclParseErrorObservation = Callable[..., RawObservation]


TERRAFORM_HCL_BLOCK_TYPES = frozenset(
    (
        "terraform",
        "provider",
        "resource",
        "data",
        "module",
        "variable",
        "output",
        "locals",
        "moved",
        "import",
        "check",
        "removed",
    )
)

TERRAFORM_HCL_MAX_BLOCKS = 256

TERRAFORM_HCL_MAX_ATTRIBUTES_PER_BLOCK = 128

TERRAFORM_HCL_MAX_DIAGNOSTICS = 64

TERRAFORM_HCL_ATTRIBUTE_PATTERN = re.compile(
    r"^\s*(?P<name>[A-Za-z_][A-Za-z0-9_-]*)\s*=\s*(?P<value>.*)$"
)


@dataclass(frozen=True)
class _TerraformHclBlock:
    block_type: str
    labels: tuple[str, ...]
    body: str
    start_line: int
    end_line: int


@dataclass(frozen=True)
class _TerraformHclAttribute:
    name: str
    value: str
    start_line: int


def _terraform_hcl_scan_blocks(
    relative_path: str,
    content: str,
    *,
    parse_error_observation: _TerraformHclParseErrorObservation,
) -> tuple[list[_TerraformHclBlock], list[RawObservation]]:
    blocks: list[_TerraformHclBlock] = []
    diagnostics: list[RawObservation] = []
    lines = content.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = _terraform_hcl_strip_comment(line).strip()
        match = TERRAFORM_HCL_BLOCK_HEADER_PATTERN.match(stripped)
        if match is None or match.group("block_type") not in TERRAFORM_HCL_BLOCK_TYPES:
            index += 1
            continue
        if len(blocks) >= TERRAFORM_HCL_MAX_BLOCKS:
            diagnostics.append(
                parse_error_observation(
                    relative_path,
                    error_kind="terraform-block-limit",
                    message="Terraform HCL block limit reached",
                    start_line=index + 1,
                    recovered=True,
                )
            )
            break

        block_type = match.group("block_type")
        labels = _terraform_hcl_labels(match.group("labels"))
        start_line = index + 1
        depth = _terraform_hcl_brace_delta(line)
        body_lines: list[str] = []
        index += 1
        if depth <= 0:
            blocks.append(
                _TerraformHclBlock(
                    block_type=block_type,
                    labels=labels,
                    body="",
                    start_line=start_line,
                    end_line=start_line,
                )
            )
            continue
        while index < len(lines) and depth > 0:
            body_line = lines[index]
            depth += _terraform_hcl_brace_delta(body_line)
            if depth > 0:
                body_lines.append(body_line)
            index += 1
        if depth > 0:
            diagnostics.append(
                parse_error_observation(
                    relative_path,
                    error_kind="terraform-unclosed-block",
                    message="Terraform HCL block is missing a closing brace",
                    start_line=start_line,
                    recovered=True,
                )
            )
            end_line = len(lines)
        else:
            end_line = index
        blocks.append(
            _TerraformHclBlock(
                block_type=block_type,
                labels=labels,
                body="\n".join(body_lines),
                start_line=start_line,
                end_line=end_line,
            )
        )
    return blocks, diagnostics[:TERRAFORM_HCL_MAX_DIAGNOSTICS]


def _terraform_hcl_top_level_attributes(
    relative_path: str,
    content: str,
    *,
    base_line: int,
    parse_error_observation: _TerraformHclParseErrorObservation,
) -> tuple[list[_TerraformHclAttribute], list[RawObservation]]:
    attributes: list[_TerraformHclAttribute] = []
    diagnostics: list[RawObservation] = []
    lines = content.splitlines()
    nested_block_depth = 0
    index = 0
    while index < len(lines):
        raw_line = lines[index]
        stripped_line = _terraform_hcl_strip_comment(raw_line).strip()
        line_number = base_line + index
        if not stripped_line:
            index += 1
            continue
        if nested_block_depth > 0:
            nested_block_depth += _terraform_hcl_brace_delta(raw_line)
            nested_block_depth = max(nested_block_depth, 0)
            index += 1
            continue
        match = TERRAFORM_HCL_ATTRIBUTE_PATTERN.match(stripped_line)
        if match is None:
            block_match = TERRAFORM_HCL_BLOCK_HEADER_PATTERN.match(stripped_line)
            if block_match is not None:
                nested_block_depth += _terraform_hcl_brace_delta(raw_line)
                nested_block_depth = max(nested_block_depth, 0)
            index += 1
            continue
        if len(attributes) >= TERRAFORM_HCL_MAX_ATTRIBUTES_PER_BLOCK:
            diagnostics.append(
                parse_error_observation(
                    relative_path,
                    error_kind="terraform-attribute-limit",
                    message="Terraform HCL attribute limit reached",
                    start_line=line_number,
                    recovered=True,
                )
            )
            break
        name = match.group("name")
        value_lines = [match.group("value")]
        depth = _terraform_hcl_collection_delta(match.group("value"))
        index += 1
        while index < len(lines) and depth > 0:
            continuation = lines[index]
            value_lines.append(continuation.strip())
            depth += _terraform_hcl_collection_delta(continuation)
            index += 1
        attributes.append(
            _TerraformHclAttribute(
                name=name,
                value="\n".join(value_lines).strip(),
                start_line=line_number,
            )
        )
    return attributes, diagnostics[:TERRAFORM_HCL_MAX_DIAGNOSTICS]
