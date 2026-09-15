"""Bash command argument observation helpers."""

from __future__ import annotations

from typing import Any

from repomap_kg import __version__
from repomap_kg.extractors.shell.bash_common import (
    BACKTICK_SUB_RE,
    COMMAND_SUB_RE,
    EXTRACTOR,
    bash_metadata,
)
from repomap_kg.observations.raw import RawObservation
from repomap_kg.extractors.shell.base import slug


LONG_FLAGS_WITH_VALUE = frozenset(
    {
        "api-key",
        "authorization",
        "header",
        "namespace",
        "output",
        "password",
        "passwd",
        "token",
    }
)
SHORT_FLAGS_WITH_VALUE = frozenset({"H", "o", "p", "u", "w"})


def argument_observations(
    relative_path: str,
    line_number: int,
    command_source_id: str,
    command_name: str,
    *,
    overlays: list[tuple[str, str]],
    args: list[str],
    context: dict[str, Any],
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    for overlay_index, (name, value) in enumerate(overlays):
        metadata = argument_metadata(
            command_source_id,
            command_name,
            argument_name=name,
            argument_position=overlay_index,
            argument_form="assignment_overlay",
            value=value,
        )
        metadata.update(context)
        observations.append(
            command_argument_observation(
                relative_path,
                line_number,
                command_source_id,
                name,
                overlay_index,
                metadata,
            )
        )
    positional_index = 0
    index = 0
    while index < len(args):
        token = args[index]
        if token.startswith("--"):
            observation, consumed = long_argument_observation(
                relative_path,
                line_number,
                command_source_id,
                command_name,
                token,
                args[index + 1] if index + 1 < len(args) else None,
                context,
            )
            observations.append(observation)
            index += consumed
            continue
        if token.startswith("-") and token != "-":
            observation, consumed = short_argument_observation(
                relative_path,
                line_number,
                command_source_id,
                command_name,
                token,
                args[index + 1] if index + 1 < len(args) else None,
                context,
            )
            observations.append(observation)
            index += consumed
            continue
        metadata = argument_metadata(
            command_source_id,
            command_name,
            argument_name=None,
            argument_position=positional_index,
            argument_form="positional",
            value=token,
        )
        metadata.update(context)
        observations.append(
            command_argument_observation(
                relative_path,
                line_number,
                command_source_id,
                f"positional-{positional_index}",
                positional_index,
                metadata,
            )
        )
        positional_index += 1
        index += 1
    return tuple(observations)


def long_argument_observation(
    relative_path: str,
    line_number: int,
    command_source_id: str,
    command_name: str,
    token: str,
    next_token: str | None,
    context: dict[str, Any],
) -> tuple[RawObservation, int]:
    name_value = token[2:]
    if "=" in name_value:
        name, value = name_value.split("=", 1)
        consumed = 1
        form = "long"
    elif name_value in LONG_FLAGS_WITH_VALUE and next_token is not None:
        name, value = name_value, next_token
        consumed = 2
        form = "long"
    else:
        name, value = name_value, None
        consumed = 1
        form = "switch"
    metadata = argument_metadata(
        command_source_id,
        command_name,
        argument_name=name,
        argument_position=None,
        argument_form=form,
        value=value,
    )
    metadata.update(context)
    return (
        command_argument_observation(
            relative_path,
            line_number,
            command_source_id,
            name,
            0,
            metadata,
        ),
        consumed,
    )


def short_argument_observation(
    relative_path: str,
    line_number: int,
    command_source_id: str,
    command_name: str,
    token: str,
    next_token: str | None,
    context: dict[str, Any],
) -> tuple[RawObservation, int]:
    name = token[1:]
    if name in SHORT_FLAGS_WITH_VALUE and next_token is not None:
        value = next_token
        consumed = 2
        form = "short"
    else:
        value = None
        consumed = 1
        form = "short"
    metadata = argument_metadata(
        command_source_id,
        command_name,
        argument_name=name,
        argument_position=None,
        argument_form=form,
        value=value,
    )
    metadata.update(context)
    return (
        command_argument_observation(
            relative_path,
            line_number,
            command_source_id,
            name,
            0,
            metadata,
        ),
        consumed,
    )


def argument_metadata(
    command_source_id: str,
    command_name: str,
    *,
    argument_name: str | None,
    argument_position: int | None,
    argument_form: str,
    value: str | None,
) -> dict[str, Any]:
    redacted, reason = argument_redaction(command_name, argument_name, value)
    metadata: dict[str, Any] = {
        "command_source_id": command_source_id,
        "command_name": command_name,
        "argument_name": argument_name,
        "argument_position": argument_position,
        "argument_form": argument_form,
        "value_kind": "redacted" if redacted else argument_value_kind(value),
        "redacted": redacted,
        "raw_value_stored": value is not None and not redacted,
    }
    if redacted:
        metadata["redaction_reason"] = reason
    elif value is not None:
        metadata["value"] = value
    return metadata


def command_argument_observation(
    relative_path: str,
    line_number: int,
    command_source_id: str,
    argument_key: str,
    argument_index: int,
    metadata: dict[str, Any],
) -> RawObservation:
    return RawObservation(
        kind="shell.command_argument",
        source_id=f"{command_source_id}:arg:{argument_index}:{slug(argument_key)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=argument_key,
        confidence="heuristic",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=bash_metadata(metadata),
    )


def argument_redaction(
    command_name: str,
    argument_name: str | None,
    value: str | None,
) -> tuple[bool, str]:
    if argument_name is not None:
        normalized = argument_name.lower().replace("_", "-")
        if normalized in {
            "api-key",
            "authorization",
            "password",
            "passwd",
            "token",
        }:
            return True, "secret-like-argument-name"
        if normalized == "h" and value is not None and "authorization:" in value.lower():
            return True, "authorization-header"
    if (
        command_name in {"curl", "wget"}
        and argument_name == "u"
        and value is not None
        and ":" in value
    ):
        return True, "credential-shaped-argument"
    if command_name == "security" and argument_name == "w" and value is not None:
        return True, "credential-shaped-argument"
    if value is not None and "authorization:" in value.lower():
        return True, "authorization-header"
    return False, ""


def argument_value_kind(value: str | None) -> str:
    if value is None:
        return "omitted"
    if value.startswith("[process-substitution:"):
        return "process_substitution"
    if COMMAND_SUB_RE.search(value) or BACKTICK_SUB_RE.search(value):
        return "command_substitution"
    if value.startswith("$") or "${" in value:
        return "dynamic"
    if any(character in value for character in "*?["):
        return "glob"
    return "static"
