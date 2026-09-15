"""Environment observation support for conservative Bash extraction."""

from __future__ import annotations

import re
from typing import Any

from repomap_kg import __version__
from repomap_kg.extractors.shell.base import slug
from repomap_kg.extractors.shell.bash_common import (
    ASSIGNMENT_RE,
    EXTRACTOR,
    bash_metadata,
    redaction_for_name,
    split_words,
    value_kind,
)
from repomap_kg.extractors.shell.bash_constructs import secret_like_observation
from repomap_kg.observations.raw import RawObservation


ENV_READ_RE = re.compile(
    r"\$(?:\{(?P<braced>[A-Za-z_][A-Za-z0-9_]*)(?:[^}]*)?\}|"
    r"(?P<bare>[A-Za-z_][A-Za-z0-9_]*))"
)


def parse_export_word(word: str) -> tuple[str, str | None] | None:
    if "=" in word:
        variable, value = word.split("=", 1)
    else:
        variable, value = word, None
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", variable):
        return None
    return variable, value


def env_read_observations(
    relative_path: str,
    line_number: int,
    raw_line: str,
) -> tuple[RawObservation, ...]:
    seen: set[str] = set()
    observations: list[RawObservation] = []
    for match in ENV_READ_RE.finditer(raw_line):
        variable = match.group("braced") or match.group("bare")
        if variable in seen:
            continue
        seen.add(variable)
        redacted, reason = redaction_for_name(variable)
        metadata: dict[str, Any] = {
            "variable": variable,
            "operation": "read",
            "target_kind": "env",
            "redacted": redacted,
            "raw_value_stored": False,
        }
        if redacted:
            metadata["redaction_reason"] = reason
        observations.append(
            RawObservation(
                kind="shell.env_read",
                source_id=(
                    f"{relative_path}#bash-env-read:{line_number}:{slug(variable)}"
                ),
                path=relative_path,
                start_line=line_number,
                end_line=line_number,
                name=variable,
                target=f"env:{variable}",
                confidence="heuristic",
                extractor=EXTRACTOR,
                extractor_version=__version__,
                metadata=bash_metadata(metadata),
            )
        )
    return tuple(observations)


def env_write_observations(
    relative_path: str,
    line_number: int,
    raw_line: str,
) -> tuple[RawObservation, ...]:
    words = split_words(raw_line)
    if not words:
        return ()
    observations: list[RawObservation] = []
    if words[0] == "export":
        for word in words[1:]:
            export = parse_export_word(word)
            if export is None:
                continue
            variable, value = export
            observations.extend(
                env_write_observations_for_value(
                    relative_path,
                    line_number,
                    variable,
                    value,
                    scope="export",
                    operation="export",
                )
            )
        return tuple(observations)
    if words[0] == "env":
        for word in words[1:]:
            match = ASSIGNMENT_RE.match(word)
            if match is None:
                break
            observations.extend(
                env_write_observations_for_value(
                    relative_path,
                    line_number,
                    match.group(1),
                    match.group(2),
                    scope="process_overlay",
                    operation="env-overlay",
                )
            )
        return tuple(observations)
    for word in words:
        match = ASSIGNMENT_RE.match(word)
        if match is None:
            break
        observations.extend(
            env_write_observations_for_value(
                relative_path,
                line_number,
                match.group(1),
                match.group(2),
                scope="process_overlay",
                operation="assignment-overlay",
            )
        )
    return tuple(observations)


def env_write_observations_for_value(
    relative_path: str,
    line_number: int,
    variable: str,
    value: str | None,
    *,
    scope: str,
    operation: str,
) -> tuple[RawObservation, ...]:
    redacted, reason = redaction_for_name(variable)
    metadata: dict[str, Any] = {
        "variable": variable,
        "operation": operation,
        "scope": scope,
        "value_kind": "omitted" if value is None else value_kind(value),
        "value_present": value is not None,
        "redacted": redacted if value is not None else False,
        "raw_value_stored": value is not None and not redacted,
    }
    if value is not None and redacted:
        metadata["redaction_reason"] = reason
    elif value is not None:
        metadata["value"] = value
    observation = RawObservation(
        kind="shell.env_write",
        source_id=(
            f"{relative_path}#bash-env-write:{line_number}:"
            f"{slug(operation + '-' + variable)}"
        ),
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=variable,
        target=f"env:{variable}",
        confidence="heuristic",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=bash_metadata(metadata),
    )
    if value is None or not redacted:
        return (observation,)
    return (
        observation,
        secret_like_observation(
            relative_path,
            line_number,
            variable,
            "env_write",
            reason,
        ),
    )
