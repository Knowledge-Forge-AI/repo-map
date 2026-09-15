"""Bash command observation helpers."""

from __future__ import annotations

from typing import Any

from repomap_kg import __version__
from repomap_kg.extractors.shell.bash_common import (
    ASSIGNMENT_RE,
    EXTRACTOR,
    bash_metadata,
)
from repomap_kg.extractors.shell.bash_redirects import REDIRECT_OPERATORS
from repomap_kg.observations.raw import RawObservation
from repomap_kg.extractors.shell.base import slug


BUILTIN_COMMANDS = frozenset(
    {
        "cd",
        "pwd",
        "test",
        "[",
        "[[",
        "echo",
        "printf",
        "read",
        "type",
        "return",
        "exit",
        "shift",
    }
)
WRAPPER_COMMANDS = frozenset({"sudo", "env", "command", "builtin", "time", "nohup"})
EXTERNAL_COMMANDS = frozenset(
    {
        "apt-get",
        "awk",
        "bash",
        "brew",
        "cargo",
        "cmd",
        "crontab",
        "curl",
        "defaults",
        "diff",
        "docker",
        "docker-compose",
        "gem",
        "git",
        "go",
        "grep",
        "helm",
        "kubectl",
        "launchctl",
        "make",
        "npm",
        "pip",
        "python",
        "python3",
        "rsync",
        "sed",
        "security",
        "service",
        "sh",
        "sort",
        "spctl",
        "systemctl",
        "tar",
        "terraform",
        "uniq",
        "wget",
    }
)


def command_token_from_segment(
    tokens: list[str],
) -> tuple[int, list[tuple[str, str]], str] | None:
    overlays: list[tuple[str, str]] = []
    for index, token in enumerate(tokens):
        if token in REDIRECT_OPERATORS or token in {"<<", "<<-"}:
            continue
        if token.startswith("-"):
            continue
        if ASSIGNMENT_RE.match(token):
            match = ASSIGNMENT_RE.match(token)
            if match is not None:
                overlays.append((match.group(1), match.group(2)))
            continue
        if token.startswith("$") or token.startswith("`"):
            return None
        return index, overlays, normalize_command_token(token)
    return None


def normalize_command_token(token: str) -> str:
    return token.strip()


def command_source_id_for(
    relative_path: str,
    line_number: int,
    command_name: str,
    *,
    chain_index: int | None,
    pipeline_index: int | None,
) -> str:
    suffix = []
    if chain_index is not None:
        suffix.append(f"chain{chain_index}")
    if pipeline_index is not None:
        suffix.append(f"pipe{pipeline_index}")
    suffix_text = ":".join(suffix) if suffix else "single"
    return f"{relative_path}#bash-command:{line_number}:{suffix_text}:{slug(command_name)}"


def command_family(command_name: str) -> str:
    if command_name in WRAPPER_COMMANDS:
        return "wrapper"
    if command_name in BUILTIN_COMMANDS:
        return "builtin"
    if command_name in EXTERNAL_COMMANDS:
        return "external"
    return "unknown"


def wrapped_command_for(command_name: str, args: list[str]) -> str | None:
    if command_name == "sudo":
        return wrapped_command_for_sudo(args)
    if command_name == "env":
        return wrapped_command_for_env(args)
    if command_name in {"command", "builtin", "time", "nohup"}:
        return next_static_command(args)
    return None


def wrapped_command_for_sudo(args: list[str]) -> str | None:
    if args and args[0] == "env":
        return wrapped_command_for_env(args[1:])
    return next_static_command(args)


def wrapped_command_for_env(args: list[str]) -> str | None:
    remaining = [arg for arg in args if not ASSIGNMENT_RE.match(arg)]
    return next_static_command(remaining)


def next_static_command(args: list[str]) -> str | None:
    for arg in args:
        if arg.startswith("-") or arg in REDIRECT_OPERATORS:
            continue
        if arg.startswith("$"):
            return None
        return normalize_command_token(arg)
    return None


def command_context_metadata(
    *,
    chain_id: str | None,
    chain_index: int | None,
    pipeline_id: str | None,
    pipeline_index: int | None,
) -> dict[str, Any]:
    context: dict[str, Any] = {}
    if chain_id is not None:
        context["chain_id"] = chain_id
        context["chain_index"] = chain_index
    if pipeline_id is not None:
        context["pipeline_id"] = pipeline_id
        context["pipeline_index"] = pipeline_index
    return context


def command_observation(
    relative_path: str,
    line_number: int,
    command_source_id: str,
    command_name: str,
    family: str,
    *,
    overlays: list[tuple[str, str]],
    args: list[str],
    wrapped_command: str | None,
    context: dict[str, Any],
) -> RawObservation:
    metadata = {
        "original_token": command_name,
        "normalized_command": command_name,
        "command_family": family,
        "command_source_id": command_source_id,
        "assignment_overlay_count": len(overlays),
        "argument_count": len([arg for arg in args if arg not in REDIRECT_OPERATORS]),
    }
    if family == "wrapper":
        metadata["wrapper_command"] = command_name
    if wrapped_command is not None:
        metadata["wrapped_command"] = wrapped_command
    metadata.update(context)
    return RawObservation(
        kind="shell.command",
        source_id=command_source_id,
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=command_name,
        target=f"tool:{command_name}",
        confidence="heuristic",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=bash_metadata(metadata),
    )


def external_command_observation(
    relative_path: str,
    line_number: int,
    command_source_id: str,
    command_name: str,
    *,
    context: dict[str, Any],
) -> RawObservation:
    metadata = {
        "original_token": command_name,
        "normalized_command": command_name,
        "command_family": "external",
        "command_source_id": command_source_id,
    }
    metadata.update(context)
    return RawObservation(
        kind="shell.external_command",
        source_id=f"{command_source_id}:external",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=command_name,
        target=f"tool:{command_name}",
        confidence="heuristic",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=bash_metadata(metadata),
    )
