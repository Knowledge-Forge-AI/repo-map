"""Command and side-effect scanning for conservative zsh extraction."""

from __future__ import annotations

import re
from typing import Any

from repomap_kg import __version__
from repomap_kg.extractors.shell.base import slug
from repomap_kg.extractors.shell.zsh_advanced import (
    array_assignment_observations,
    associative_array_observations,
    glob_and_path_observations,
    parameter_expansion_observations,
    zsh_specific_dynamic_observations,
)
from repomap_kg.extractors.shell.zsh_command_observations import (
    command_argument_observations,
    command_chain_observation,
    pipeline_observation,
    redirect_observations,
)
from repomap_kg.extractors.shell.zsh_commands import (
    COMMAND_WRAPPERS,
    command_family,
    first_command_index,
    is_command_token,
    is_dynamic_command_token,
    should_skip_command_syntax,
    split_command_segments,
    words_without_redirects,
    wrapped_command_index,
)
from repomap_kg.extractors.shell.zsh_common import (
    EXTRACTOR,
    PLUGIN_MANAGER_NAMES,
    has_command_substitution,
    is_dynamic_value,
    split_words,
    zsh_metadata,
)
from repomap_kg.extractors.shell.zsh_side_effects import (
    FILESYSTEM_MUTATION_COMMANDS,
    NETWORK_COMMANDS,
    PACKAGE_MANAGER_COMMANDS,
    env_intent_observations,
    file_intent_observation,
    filesystem_mutation_intent_observations,
    network_intent_observations,
    package_manager_intent_observations,
)
from repomap_kg.observations.raw import RawObservation


def command_syntax_observations(
    relative_path: str,
    line_number: int,
    line: str,
) -> tuple[RawObservation, ...]:
    stripped = line.strip()
    if should_skip_command_syntax(stripped):
        return ()
    segments, operators = split_command_segments(stripped)
    observations: list[RawObservation] = []
    observations.extend(redirect_observations(relative_path, line_number, stripped))
    if operators:
        if "|" in operators:
            observations.append(
                pipeline_observation(relative_path, line_number, len(segments), operators)
            )
        chain_ops = [operator for operator in operators if operator in {"&&", "||"}]
        if chain_ops:
            observations.append(
                command_chain_observation(
                    relative_path,
                    line_number,
                    len(segments),
                    chain_ops,
                )
            )
    for index, segment in enumerate(segments, start=1):
        observations.extend(
            command_observations_for_segment(
                relative_path,
                line_number,
                segment,
                index,
            )
        )
    return tuple(observations)


def command_observations_for_segment(
    relative_path: str,
    line_number: int,
    segment: str,
    segment_index: int,
) -> tuple[RawObservation, ...]:
    words = words_without_redirects(segment)
    if not words:
        return ()
    first_index = first_command_index(words)
    if first_index is None:
        return ()
    command_name = words[first_index]
    if is_dynamic_command_token(command_name) or not is_command_token(command_name):
        return ()
    observations: list[RawObservation] = []
    wrapper_command = command_name if command_name in COMMAND_WRAPPERS else None
    wrapped_index = wrapped_command_index(words, first_index) if wrapper_command else None
    wrapped_command = words[wrapped_index] if wrapped_index is not None else None
    command = command_observation(
        relative_path,
        line_number,
        segment_index,
        command_name,
        words[first_index + 1 :],
        wrapper_command=wrapper_command,
        wrapped_command=wrapped_command,
    )
    observations.append(command)
    if command.metadata["command_family"] == "external":
        observations.append(
            external_command_observation(
                relative_path,
                line_number,
                segment_index,
                command_name,
            )
        )
    argument_start = first_index + 1
    observations.extend(
        command_argument_observations(
            relative_path,
            line_number,
            command_name,
            words[argument_start:],
            segment_index=segment_index,
        )
    )
    if wrapped_index is not None and wrapped_command and is_command_token(wrapped_command):
        wrapped_args = words[wrapped_index + 1 :]
        wrapped = command_observation(
            relative_path,
            line_number,
            segment_index,
            wrapped_command,
            wrapped_args,
            wrapper_command=wrapper_command,
            wrapped_command=None,
            source_id_suffix="wrapped",
        )
        observations.append(wrapped)
        if wrapped.metadata["command_family"] == "external":
            observations.append(
                external_command_observation(
                    relative_path,
                    line_number,
                    segment_index,
                    wrapped_command,
                    source_id_suffix="wrapped",
                )
            )
    return tuple(observations)


def command_observation(
    relative_path: str,
    line_number: int,
    segment_index: int,
    command_name: str,
    arguments: list[str],
    *,
    wrapper_command: str | None,
    wrapped_command: str | None,
    source_id_suffix: str = "command",
) -> RawObservation:
    family = command_family(command_name)
    metadata: dict[str, Any] = {
        "command_name": command_name,
        "original_token": command_name,
        "command_family": family,
        "argument_count": len(arguments),
        "command_executed": False,
        "configuration_intent": command_name in PLUGIN_MANAGER_NAMES
        or command_name in {"zstyle", "zmodload", "bindkey", "compinit", "autoload"},
    }
    if wrapper_command is not None:
        metadata["wrapper_command"] = wrapper_command
    if wrapped_command is not None and not is_dynamic_value(wrapped_command):
        metadata["wrapped_command"] = wrapped_command
    return RawObservation(
        kind="shell.command",
        source_id=(
            f"{relative_path}#zsh-command:{line_number}:{segment_index}:"
            f"{source_id_suffix}:{slug(command_name)}"
        ),
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=command_name,
        confidence="heuristic",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=zsh_metadata(metadata),
    )


def external_command_observation(
    relative_path: str,
    line_number: int,
    segment_index: int,
    command_name: str,
    *,
    source_id_suffix: str = "command",
) -> RawObservation:
    return RawObservation(
        kind="shell.external_command",
        source_id=(
            f"{relative_path}#zsh-external-command:{line_number}:{segment_index}:"
            f"{source_id_suffix}:{slug(command_name)}"
        ),
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=command_name,
        target=f"tool:{command_name}",
        confidence="heuristic",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=zsh_metadata(
            {
                "command_name": command_name,
                "original_token": command_name,
                "command_family": "external",
                "command_executed": False,
            }
        ),
    )


def zsh3_advanced_observations(
    relative_path: str,
    line_number: int,
    line: str,
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    observations.extend(array_assignment_observations(relative_path, line_number, line))
    observations.extend(associative_array_observations(relative_path, line_number, line))
    observations.extend(parameter_expansion_observations(relative_path, line_number, line))
    observations.extend(glob_and_path_observations(relative_path, line_number, line))
    observations.extend(
        zsh_specific_dynamic_observations(relative_path, line_number, line)
    )
    observations.extend(side_effect_intent_observations(relative_path, line_number, line))
    return tuple(observations)


def side_effect_intent_observations(
    relative_path: str,
    line_number: int,
    line: str,
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    observations.extend(env_intent_observations(relative_path, line_number, line))
    observations.extend(
        redirect_file_intent_observations(relative_path, line_number, line)
    )
    for segment_index, segment in enumerate(split_command_segments(line)[0], start=1):
        words = words_without_redirects(segment)
        first = first_command_index(words)
        if first is None:
            continue
        command = words[first]
        if command in COMMAND_WRAPPERS:
            wrapped = wrapped_command_index(words, first)
            if wrapped is None:
                continue
            command = words[wrapped]
            args = words[wrapped + 1 :]
        else:
            args = words[first + 1 :]
        if command in FILESYSTEM_MUTATION_COMMANDS:
            observations.extend(
                filesystem_mutation_intent_observations(
                    relative_path,
                    line_number,
                    command,
                    args,
                    segment_index,
                )
            )
        elif command in NETWORK_COMMANDS:
            observations.extend(
                network_intent_observations(
                    relative_path,
                    line_number,
                    command,
                    args,
                    segment_index,
                )
            )
        elif command in PACKAGE_MANAGER_COMMANDS:
            observations.extend(
                package_manager_intent_observations(
                    relative_path,
                    line_number,
                    command,
                    args,
                    segment_index,
                )
            )
    return tuple(observations)


def redirect_file_intent_observations(
    relative_path: str,
    line_number: int,
    line: str,
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    for redirect in redirect_observations(relative_path, line_number, line):
        operator = str(redirect.metadata.get("redirect_operator") or "")
        target_display_value = str(
            redirect.metadata.get("target_display") or "[unknown]"
        )
        target_kind = str(redirect.metadata.get("target_kind") or "unknown")
        if operator == "<":
            observations.append(
                file_intent_observation(
                    relative_path,
                    line_number,
                    "shell.file_read",
                    "redirect_read",
                    target_display_value,
                    target_kind,
                )
            )
        elif operator in {">", ">>", "2>", "2>>", "&>"}:
            observations.append(
                file_intent_observation(
                    relative_path,
                    line_number,
                    "shell.file_write",
                    "redirect_write",
                    target_display_value,
                    target_kind,
                )
            )
    return tuple(observations)


def command_substitution_observations(
    relative_path: str,
    line_number: int,
    line: str,
) -> tuple[RawObservation, ...]:
    if not has_command_substitution(line):
        return ()
    return (
        RawObservation(
            kind="shell.command_substitution",
            source_id=f"{relative_path}#zsh-command-substitution:{line_number}",
            path=relative_path,
            start_line=line_number,
            end_line=line_number,
            name="command-substitution",
            confidence="heuristic",
            extractor=EXTRACTOR,
            extractor_version=__version__,
            metadata=zsh_metadata(
                {
                    "inner_modeled": False,
                    "command_executed": False,
                    "dynamic_reason": "command-substitution",
                }
            ),
        ),
    )


def dynamic_invocation_observations(
    relative_path: str,
    line_number: int,
    line: str,
    *,
    source_items: tuple[RawObservation, ...],
) -> tuple[RawObservation, ...]:
    stripped = line.strip()
    words = split_words(stripped)
    markers: list[tuple[str, str]] = []
    if words and words[0] == "eval":
        markers.append(("eval", "eval"))
        if any(manager in stripped for manager in PLUGIN_MANAGER_NAMES):
            markers.append(("plugin_manager_eval", "plugin-manager-eval"))
    if re.match(r"^\$[A-Za-z_][A-Za-z0-9_]*(?:\s|$)", stripped):
        markers.append(("variable_command", "variable-command"))
    if re.match(r'^"?\$\{[A-Za-z_][A-Za-z0-9_]*\[@\]\}"?(?:\s|$)', stripped):
        markers.append(("array_command", "array-command"))
    if words and words[0] in {"source", "."} and source_items:
        if source_items[0].metadata.get("target_kind") != "static":
            markers.append(("computed_source", "computed-source"))
    if words and words[0] == "autoload" and any(
        is_dynamic_value(word) for word in words[1:]
    ):
        markers.append(("computed_autoload", "computed-autoload"))
    markers = list(dict.fromkeys(markers))
    return tuple(
        dynamic_marker(relative_path, line_number, reason, invocation_kind)
        for reason, invocation_kind in markers
    )


def dynamic_marker(
    relative_path: str,
    line_number: int,
    dynamic_reason: str,
    invocation_kind: str,
) -> RawObservation:
    return RawObservation(
        kind="shell.dynamic_invocation",
        source_id=f"{relative_path}#zsh-dynamic:{line_number}:{slug(dynamic_reason)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=dynamic_reason,
        confidence="unknown",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=zsh_metadata(
            {
                "resolution": "dynamic",
                "dynamic_reason": dynamic_reason,
                "invocation_kind": invocation_kind,
                "target_kind": "dynamic",
                "target_display": "[dynamic]",
                "plugins_loaded": False,
            }
        ),
    )
