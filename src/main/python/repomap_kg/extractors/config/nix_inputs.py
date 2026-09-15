"""Static flake input extraction without exposing input source values."""

from __future__ import annotations

import re
from typing import Any

from repomap_kg import __version__
from repomap_kg.extractors.config.nix_common import (
    EXTRACTOR_NAME,
    IDENTIFIER_PATTERN,
    slug,
)
from repomap_kg.observations.raw import RawObservation


INPUTS_ATTRSET_START_PATTERN = re.compile(r"^\s*inputs\s*=\s*\{")
INPUT_FIELD_PATTERN = re.compile(
    rf"^\s*(?P<name>{IDENTIFIER_PATTERN})"
    r"\.(?P<field>url|follows)\s*=\s*(?P<expr>[^;]+)"
)
NESTED_INPUT_START_PATTERN = re.compile(
    rf"^\s*(?P<name>{IDENTIFIER_PATTERN})\s*=\s*\{{"
)
NESTED_INPUT_FIELD_PATTERN = re.compile(
    r"^\s*(?P<field>url|follows)\s*=\s*(?P<expr>[^;]+)"
)


def extract_flake_input_observations(
    relative_path: str,
    content: str,
) -> tuple[RawObservation, ...]:
    records: dict[str, dict[str, Any]] = {}
    in_inputs = False
    inputs_depth = 0
    nested_input_name: str | None = None

    for line_number, line in enumerate(content.splitlines(), start=1):
        if not in_inputs:
            if INPUTS_ATTRSET_START_PATTERN.search(line) is None:
                continue
            in_inputs = True
            inputs_depth = line.count("{") - line.count("}")
            continue

        if inputs_depth <= 0:
            in_inputs = False
            nested_input_name = None
            continue

        field_match = INPUT_FIELD_PATTERN.match(line)
        if field_match is not None:
            _record_flake_input_field(
                records,
                field_match.group("name"),
                field_match.group("field"),
                field_match.group("expr"),
                line_number,
            )
        elif nested_input_name is not None:
            nested_field_match = NESTED_INPUT_FIELD_PATTERN.match(line)
            if nested_field_match is not None:
                _record_flake_input_field(
                    records,
                    nested_input_name,
                    nested_field_match.group("field"),
                    nested_field_match.group("expr"),
                    line_number,
                )
        else:
            nested_match = NESTED_INPUT_START_PATTERN.match(line)
            if nested_match is not None:
                nested_input_name = nested_match.group("name")

        if nested_input_name is not None and "};" in line:
            nested_input_name = None
        inputs_depth += line.count("{") - line.count("}")
        if inputs_depth <= 0:
            in_inputs = False
            nested_input_name = None

    return tuple(
        _flake_input_observation(relative_path, input_name, record)
        for input_name, record in records.items()
    )


def _record_flake_input_field(
    records: dict[str, dict[str, Any]],
    input_name: str,
    field: str,
    expression: str,
    line_number: int,
) -> None:
    record = records.setdefault(
        input_name,
        {
            "line_number": line_number,
            "has_url": False,
            "has_follows": False,
            "source_type": "unknown",
        },
    )
    record["line_number"] = min(record["line_number"], line_number)
    if field == "url":
        record["has_url"] = True
        if record["source_type"] in {"unknown", "follows"}:
            record["source_type"] = _categorize_flake_input_source(expression)
        return
    record["has_follows"] = True
    record["source_type"] = "follows"


def _flake_input_observation(
    relative_path: str,
    input_name: str,
    record: dict[str, Any],
) -> RawObservation:
    line_number = record["line_number"]
    has_url = bool(record["has_url"])
    has_follows = bool(record["has_follows"])
    return RawObservation(
        kind="nix.flake_input",
        source_id=f"{relative_path}#nix-flake-input:{line_number}:{slug(input_name)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=input_name,
        confidence="heuristic",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata={
            "input_name": input_name,
            "syntax": "inputs-attrset",
            "has_url": has_url,
            "has_follows": has_follows,
            "source_redacted": has_url or has_follows,
            "source_type": record["source_type"],
        },
    )


def _categorize_flake_input_source(expression: str) -> str:
    normalized = expression.strip().strip('"').strip("'").lower()
    if normalized.startswith("github:") or "github.com" in normalized:
        return "github"
    if normalized.startswith("git+") or normalized.startswith("git:"):
        return "git"
    if (
        normalized.startswith("path:")
        or normalized.startswith("./")
        or normalized.startswith("../")
    ):
        return "path"
    if normalized.endswith((".tar.gz", ".tgz", ".tar.xz", ".zip")):
        return "tarball"
    if "${" in normalized:
        return "dynamic"
    return "unknown"
