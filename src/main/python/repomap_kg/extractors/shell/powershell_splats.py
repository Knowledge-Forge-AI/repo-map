"""PowerShell splat assignment and usage observations."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from repomap_kg import __version__
from repomap_kg.extractors.shell.powershell_common import (
    EXTRACTOR_NAME,
    _is_secret_like_name,
    _secret_like_observation,
    slug,
)
from repomap_kg.extractors.shell.powershell_tokens import _argument_value_kind
from repomap_kg.observations.raw import RawObservation


@dataclass(frozen=True)
class SplatAssignment:
    variable_name: str
    source_id: str
    known_keys: tuple[str, ...]
    redacted_keys: tuple[str, ...]
    contains_dynamic_values: bool
    key_count: int


def _splat_assignment_from_lines(
    relative_path: str,
    lines: list[str],
    start_index: int,
) -> tuple[RawObservation | None, int, tuple[RawObservation, ...]]:
    match = re.match(
        r"^\s*\$(?P<name>[A-Za-z_][0-9A-Za-z_]*)\s*=\s*@\{\s*$",
        lines[start_index],
    )
    if match is None:
        return None, start_index, ()
    variable_name = match.group("name")
    known_keys: list[str] = []
    redacted_keys: list[str] = []
    contains_dynamic_values = False
    secret_like: list[RawObservation] = []
    index = start_index + 1
    while index < len(lines):
        stripped = lines[index].strip()
        if stripped.startswith("}"):
            break
        key_match = re.match(
            r"^(?P<key>[A-Za-z_][0-9A-Za-z_]*)\s*=\s*(?P<value>.+?)\s*$",
            stripped,
        )
        if key_match is not None:
            key = key_match.group("key")
            value_token = key_match.group("value").rstrip(",").strip()
            if _is_secret_like_name(key):
                redacted_keys.append(key)
                secret_like.append(
                    _secret_like_observation(
                        relative_path,
                        index + 1,
                        f"{variable_name}.{key}",
                        secret_source="splat_assignment",
                        reason="secret-like splat key",
                    )
                )
            else:
                known_keys.append(key)
            if _argument_value_kind(value_token) == "dynamic":
                contains_dynamic_values = True
        index += 1
    metadata = {
        "splat_variable": variable_name,
        "key_count": len(known_keys) + len(redacted_keys),
        "known_keys": known_keys,
        "redacted_keys": redacted_keys,
        "contains_dynamic_values": contains_dynamic_values,
        "expansion_modeled": False,
        "static_only": True,
        "powershell_executed": False,
    }
    return (
        RawObservation(
            kind="powershell.splat_assignment",
            source_id=f"{relative_path}#splat-assignment:{start_index + 1}:{slug(variable_name)}",
            path=relative_path,
            start_line=start_index + 1,
            end_line=index + 1,
            name=variable_name,
            confidence="heuristic",
            extractor=EXTRACTOR_NAME,
            extractor_version=__version__,
            metadata=metadata,
        ),
        index,
        tuple(secret_like),
    )


def _splat_observation(
    relative_path: str,
    line_number: int,
    splat_name: str,
    *,
    command_name: str,
    command_source_id: str,
    pipeline_id: str | None,
    pipeline_index: int | None,
    assignment: SplatAssignment | None = None,
) -> RawObservation:
    metadata: dict[str, Any] = {
        "splat_variable": splat_name,
        "command_name": command_name,
        "command_source_id": command_source_id,
        "expansion_modeled": False,
        "static_only": True,
        "powershell_executed": False,
    }
    if pipeline_id is not None:
        metadata["pipeline_id"] = pipeline_id
        metadata["pipeline_index"] = pipeline_index
    if assignment is not None:
        metadata.update(
            {
                "assignment_source_id": assignment.source_id,
                "known_keys": list(assignment.known_keys),
                "redacted_keys": list(assignment.redacted_keys),
                "contains_dynamic_values": assignment.contains_dynamic_values,
                "assignment_key_count": assignment.key_count,
            }
        )
    return RawObservation(
        kind="powershell.splat",
        source_id=f"{relative_path}#splat:{line_number}:{slug(command_name)}:{slug(splat_name)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=splat_name,
        confidence="heuristic",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
    )
