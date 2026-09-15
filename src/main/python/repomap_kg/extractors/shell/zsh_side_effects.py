"""Zsh side-effect intent observation helpers."""

from __future__ import annotations

import re

from repomap_kg import __version__
from repomap_kg.extractors.shell.zsh_common import (
    EXTRACTOR,
    parse_export_word,
    side_effect_metadata,
    split_words,
    target_display,
    token_target_kind,
    zsh_metadata,
)
from repomap_kg.observations.raw import RawObservation
from repomap_kg.extractors.shell.base import slug


FILESYSTEM_MUTATION_COMMANDS = frozenset({"mkdir", "rm", "touch", "chmod", "chown", "mv", "cp"})
NETWORK_COMMANDS = frozenset({"curl", "wget"})
PACKAGE_MANAGER_COMMANDS = frozenset({"brew", "npm", "pip", "pipx", "cargo", "go"})


def env_intent_observations(
    relative_path: str,
    line_number: int,
    line: str,
) -> tuple[RawObservation, ...]:
    words = split_words(line)
    if not words or words[0] != "export":
        return ()
    observations: list[RawObservation] = []
    for word in words[1:]:
        parsed = parse_export_word(word)
        if parsed is None:
            continue
        variable, value = parsed
        observations.append(env_observation(relative_path, line_number, "shell.env_write", variable, "export"))
        if value:
            for read_name in env_reads_from_value(value):
                observations.append(env_observation(relative_path, line_number, "shell.env_read", read_name, "export_value"))
    return tuple(observations)


def env_reads_from_value(value: str) -> list[str]:
    names: list[str] = []
    for match in re.finditer(r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))", value):
        name = match.group(1) or match.group(2)
        if name:
            names.append(name)
    return list(dict.fromkeys(names))


def env_observation(
    relative_path: str,
    line_number: int,
    kind: str,
    variable: str,
    operation: str,
) -> RawObservation:
    return RawObservation(
        kind=kind,
        source_id=f"{relative_path}#zsh-{kind.split('.')[-1]}:{line_number}:{slug(variable + '-' + operation)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=variable,
        target=f"env:{variable}",
        confidence="heuristic",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=zsh_metadata(side_effect_metadata(relative_path, {"variable": variable, "operation": operation})),
    )


def filesystem_mutation_intent_observations(
    relative_path: str,
    line_number: int,
    command: str,
    args: list[str],
    segment_index: int,
) -> tuple[RawObservation, ...]:
    target = first_staticish_target(args)
    target_kind = token_target_kind(target or "")
    target_display_value = target_display(target or "", target_kind)
    mutation_category = "permission_mutation" if command in {"chmod", "chown"} else "file_write"
    observations = [
        file_intent_observation(relative_path, line_number, "shell.file_write", command, target_display_value, target_kind),
        host_mutation_intent_observation(relative_path, line_number, command, mutation_category, target_display_value, target_kind, segment_index),
    ]
    if command == "cp" and args:
        source = first_staticish_target(args[:-1])
        if source:
            observations.append(
                file_intent_observation(relative_path, line_number, "shell.file_read", command, target_display(source, token_target_kind(source)), token_target_kind(source))
            )
    return tuple(observations)


def network_intent_observations(
    relative_path: str,
    line_number: int,
    command: str,
    args: list[str],
    segment_index: int,
) -> tuple[RawObservation, ...]:
    target = first_staticish_target(args)
    target_kind = token_target_kind(target or "")
    target_display_value = target_display(target or "", target_kind)
    return (
        RawObservation(
            kind="shell.network_call",
            source_id=f"{relative_path}#zsh-network-intent:{line_number}:{segment_index}:{slug(command + '-' + target_display_value)}",
            path=relative_path,
            start_line=line_number,
            end_line=line_number,
            name=command,
            confidence="heuristic" if target_kind == "static" else "unknown",
            extractor=EXTRACTOR,
            extractor_version=__version__,
            metadata=zsh_metadata(
                side_effect_metadata(
                    relative_path,
                    {
                        "command_name": command,
                        "operation": "network_call",
                        "target_kind": target_kind,
                        "target_display": target_display_value,
                        "network_called": False,
                    },
                )
            ),
        ),
    )


def package_manager_intent_observations(
    relative_path: str,
    line_number: int,
    command: str,
    args: list[str],
    segment_index: int,
) -> tuple[RawObservation, ...]:
    operation = package_operation(command, args)
    if operation not in {"install", "add"}:
        return ()
    package = first_package_target(command, args)
    target_kind = token_target_kind(package or "")
    target_display_value = target_display(package or "", target_kind)
    package_observation = RawObservation(
        kind="shell.package_manager",
        source_id=f"{relative_path}#zsh-package-intent:{line_number}:{segment_index}:{slug(command + '-' + operation)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=command,
        confidence="heuristic",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=zsh_metadata(
            side_effect_metadata(
                relative_path,
                {
                    "command_name": command,
                    "operation": operation,
                    "target_kind": target_kind,
                    "target_display": target_display_value,
                    "package_manager_executed": False,
                },
            )
        ),
    )
    mutation = host_mutation_intent_observation(
        relative_path,
        line_number,
        command,
        "package_management",
        target_display_value,
        target_kind,
        segment_index,
    )
    return (package_observation, mutation)


def file_intent_observation(
    relative_path: str,
    line_number: int,
    kind: str,
    operation: str,
    target_display_value: str,
    target_kind: str,
) -> RawObservation:
    return RawObservation(
        kind=kind,
        source_id=f"{relative_path}#zsh-{kind.split('.')[-1]}-intent:{line_number}:{slug(operation + '-' + target_display_value)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=target_display_value,
        confidence="heuristic" if target_kind == "static" else "unknown",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=zsh_metadata(
            side_effect_metadata(
                relative_path,
                {
                    "operation": operation,
                    "target_kind": target_kind,
                    "target_display": target_display_value,
                },
            )
        ),
    )


def host_mutation_intent_observation(
    relative_path: str,
    line_number: int,
    command: str,
    mutation_category: str,
    target_display_value: str,
    target_kind: str,
    segment_index: int,
) -> RawObservation:
    return RawObservation(
        kind="shell.host_mutation",
        source_id=f"{relative_path}#zsh-host-mutation-intent:{line_number}:{segment_index}:{slug(command + '-' + mutation_category)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=mutation_category,
        confidence="heuristic",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=zsh_metadata(
            side_effect_metadata(
                relative_path,
                {
                    "mutation_category": mutation_category,
                    "operation": command,
                    "command_name": command,
                    "target_kind": target_kind,
                    "target_display": target_display_value,
                    "destructive": command == "rm",
                    "host_mutation_proven": False,
                },
            )
        ),
    )


def first_staticish_target(args: list[str]) -> str | None:
    for arg in reversed(args):
        if arg == "--" or arg.startswith("-"):
            continue
        return arg
    return None


def package_operation(command: str, args: list[str]) -> str:
    if command == "go" and len(args) >= 1 and args[0] == "install":
        return "install"
    if any(arg == "install" for arg in args):
        return "install"
    if command == "cargo" and any(arg == "install" for arg in args):
        return "install"
    return "unknown"


def first_package_target(command: str, args: list[str]) -> str | None:
    if command == "go":
        return args[1] if len(args) > 1 and args[0] == "install" else None
    for index, arg in enumerate(args):
        if arg == "install" and index + 1 < len(args):
            return args[index + 1]
    return first_staticish_target(args)
