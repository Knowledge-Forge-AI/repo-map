"""Terraform HCL text, expression, and module-source helpers."""

from __future__ import annotations

import posixpath
import re
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from repomap_kg.extractors.config.generic_profile_helpers import _stable_text_sha256
from repomap_kg.extractors.config.generic_values import _is_url
from repomap_kg.graph.keys import external_key, file_key, unknown_key


TERRAFORM_HCL_MAX_METADATA_STRING = 160

TERRAFORM_HCL_BLOCK_HEADER_PATTERN = re.compile(
    r'^\s*(?P<block_type>[A-Za-z_][A-Za-z0-9_-]*)'
    r'(?P<labels>(?:\s+"(?:[^"\\]|\\.)*")*)\s*\{'
)

TERRAFORM_HCL_TRAVERSAL_PATTERN = re.compile(
    r"\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_*-]+)+\b"
)


def _terraform_hcl_labels(label_text: str) -> tuple[str, ...]:
    return tuple(
        bytes(match.group(1), "utf-8").decode("unicode_escape")
        for match in re.finditer(r'"((?:[^"\\]|\\.)*)"', label_text)
    )


def _terraform_hcl_brace_delta(line: str) -> int:
    return _terraform_hcl_delimiter_delta(line, openings="{", closings="}")


def _terraform_hcl_collection_delta(line: str) -> int:
    return _terraform_hcl_delimiter_delta(line, openings="{[(", closings="}])")


def _terraform_hcl_delimiter_delta(
    line: str,
    *,
    openings: str,
    closings: str,
) -> int:
    stripped = _terraform_hcl_strip_comment(line)
    depth = 0
    in_string = False
    escape = False
    for character in stripped:
        if escape:
            escape = False
            continue
        if character == "\\" and in_string:
            escape = True
            continue
        if character == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if character in openings:
            depth += 1
        elif character in closings:
            depth -= 1
    return depth


def _terraform_hcl_strip_comment(line: str) -> str:
    in_string = False
    escape = False
    index = 0
    while index < len(line):
        character = line[index]
        if escape:
            escape = False
            index += 1
            continue
        if character == "\\" and in_string:
            escape = True
            index += 1
            continue
        if character == '"':
            in_string = not in_string
            index += 1
            continue
        if not in_string and character == "#":
            return line[:index]
        if not in_string and line[index : index + 2] == "//":
            return line[:index]
        index += 1
    return line


def _terraform_hcl_nested_block_body(content: str, block_type: str) -> str | None:
    lines = content.splitlines()
    for index, line in enumerate(lines):
        stripped = _terraform_hcl_strip_comment(line).strip()
        match = TERRAFORM_HCL_BLOCK_HEADER_PATTERN.match(stripped)
        if match is None or match.group("block_type") != block_type:
            continue
        depth = _terraform_hcl_brace_delta(line)
        body_lines: list[str] = []
        index += 1
        while index < len(lines) and depth > 0:
            nested_line = lines[index]
            depth += _terraform_hcl_brace_delta(nested_line)
            if depth > 0:
                body_lines.append(nested_line)
            index += 1
        return "\n".join(body_lines)
    return None


def _terraform_hcl_nested_block_labels(content: str, block_type: str) -> tuple[str, ...]:
    labels: list[str] = []
    for line in content.splitlines():
        stripped = _terraform_hcl_strip_comment(line).strip()
        match = TERRAFORM_HCL_BLOCK_HEADER_PATTERN.match(stripped)
        if match is None or match.group("block_type") != block_type:
            continue
        block_labels = _terraform_hcl_labels(match.group("labels"))
        if block_labels:
            labels.append(block_labels[0])
    return tuple(labels)


def _terraform_hcl_nested_block_count(content: str, block_type: str) -> int:
    count = 0
    for line in content.splitlines():
        stripped = _terraform_hcl_strip_comment(line).strip()
        match = TERRAFORM_HCL_BLOCK_HEADER_PATTERN.match(stripped)
        if match is not None and match.group("block_type") == block_type:
            count += 1
    return count


def _terraform_hcl_collection_body(value: str) -> str | None:
    stripped = value.strip()
    if not (stripped.startswith("{") and stripped.endswith("}")):
        return None
    return stripped[1:-1]


def _terraform_hcl_module_source(
    relative_path: str,
    source: str,
) -> tuple[dict[str, Any], str, str]:
    if _terraform_hcl_credentialed_url(source):
        return (
            {
                "source_kind": "remote",
                "not_fetched": True,
                "redacted": True,
                "redaction_reason": "credentialed-terraform-module-source",
            },
            external_key("terraform.module", "redacted-module-source"),
            "module_source",
        )
    local_target = _terraform_hcl_local_path_target(relative_path, source)
    if local_target is not None:
        return (
            {
                "source_kind": "local",
                "source_summary": _terraform_hcl_bounded_string(source),
                "not_fetched": True,
            },
            local_target,
            "module_source_local",
        )
    return (
        {
            "source_kind": "remote",
            "source_summary": _terraform_hcl_bounded_string(source),
            "not_fetched": True,
        },
        external_key("terraform.module", source),
        "module_source",
    )


def _terraform_hcl_local_path_target(relative_path: str, source: str) -> str | None:
    if source.startswith("/") or _is_url(source) or source.startswith(("git::", "ssh://")):
        return None
    if not (source.startswith("./") or source.startswith("../")):
        return None
    base_dir = PurePosixPath(relative_path).parent
    candidate = posixpath.normpath((base_dir / source).as_posix())
    if candidate == "." or candidate.startswith("../") or candidate == "..":
        return unknown_key("file", "repo-escaping-terraform-module-source")
    if PurePosixPath(candidate).is_absolute():
        return unknown_key("file", "repo-escaping-terraform-module-source")
    return file_key(candidate)


def _terraform_hcl_reference_names(value: str) -> tuple[str, ...]:
    names = []
    for match in TERRAFORM_HCL_TRAVERSAL_PATTERN.finditer(value):
        names.append(match.group(0))
    return tuple(dict.fromkeys(names))


def _terraform_hcl_literal_string(value: str) -> str | None:
    stripped = value.strip()
    match = re.match(r'^"((?:[^"\\]|\\.)*)"$', stripped, flags=re.DOTALL)
    if match is None:
        return None
    return bytes(match.group(1), "utf-8").decode("unicode_escape")


def _terraform_hcl_bool_literal(value: str) -> bool | None:
    stripped = value.strip().lower()
    if stripped == "true":
        return True
    if stripped == "false":
        return False
    return None


def _terraform_hcl_value_type(value: str) -> str:
    kind = _terraform_hcl_expression_kind(value)
    if kind == "literal_string":
        return "string"
    if kind == "literal_number":
        return "number"
    if kind == "literal_bool":
        return "boolean"
    if kind == "literal_null":
        return "null"
    stripped = value.strip()
    if stripped.startswith("{"):
        return "object"
    if stripped.startswith("["):
        return "array"
    return "expression"


def _terraform_hcl_expression_kind(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        return "unknown"
    literal = _terraform_hcl_literal_string(stripped)
    if literal is not None:
        if "${" in literal:
            return "template_interpolation"
        return "literal_string"
    lowered = stripped.lower()
    if lowered in ("true", "false"):
        return "literal_bool"
    if lowered == "null":
        return "literal_null"
    if re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", stripped):
        return "literal_number"
    if stripped.startswith(("{", "[")):
        return "collection_shape"
    if "${" in stripped:
        return "template_interpolation"
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s*\(", stripped):
        return "function_call"
    if "?" in stripped and ":" in stripped:
        return "conditional"
    if TERRAFORM_HCL_TRAVERSAL_PATTERN.fullmatch(stripped):
        return "traversal_reference"
    if "dynamic " in stripped or stripped.startswith("dynamic"):
        return "dynamic_block"
    return "unknown"


def _terraform_hcl_expression_summary(value: str) -> str:
    kind = _terraform_hcl_expression_kind(value)
    if kind in (
        "literal_string",
        "literal_number",
        "literal_bool",
        "literal_null",
        "traversal_reference",
    ):
        literal = _terraform_hcl_literal_string(value)
        if literal is not None:
            return _terraform_hcl_bounded_string(literal)
        return _terraform_hcl_bounded_string(value.strip())
    return kind


def _terraform_hcl_text_presence_metadata(key: str, value: str) -> dict[str, Any]:
    literal = _terraform_hcl_literal_string(value)
    text = literal if literal is not None else value.strip()
    return {
        f"{key}_present": True,
        f"{key}_length": len(text),
        f"{key}_sha256": _stable_text_sha256(text),
    }


def _terraform_hcl_credentialed_url(value: str) -> bool:
    candidate = value.removeprefix("git::")
    parsed = urlsplit(candidate)
    if parsed.scheme in ("http", "https", "ssh", "git") and (
        parsed.username is not None or parsed.password is not None
    ):
        return True
    return bool(re.search(r"://[^/\s:@]+:[^/\s@]+@", candidate))


def _terraform_hcl_bounded_string(value: str) -> str:
    if len(value) <= TERRAFORM_HCL_MAX_METADATA_STRING and all(
        character.isprintable() for character in value
    ):
        return value
    return f"<string:{len(value)}>"


def _is_terraform_hcl_file_name(relative_path: str) -> bool:
    name = PurePosixPath(relative_path).name.lower()
    return name.endswith(".tf") and not name.endswith(".tf.json")


def _is_terraform_tfvars_hcl_file_name(relative_path: str) -> bool:
    name = PurePosixPath(relative_path).name.lower()
    return (
        name == "terraform.tfvars"
        or name.endswith(".auto.tfvars")
        or (name.endswith(".tfvars") and not name.endswith(".tfvars.json"))
    )
