"""Zsh command-line observation builders."""

from __future__ import annotations

import re
from typing import Any

from repomap_kg import __version__
from repomap_kg.extractors.shell.zsh_common import (
    EXTRACTOR,
    is_dynamic_value,
    redaction_for_value,
    secret_like_observation,
    split_words,
    target_display,
    token_target_kind,
    zsh_metadata,
)
from repomap_kg.extractors.shell.zsh_commands import redirect_mode
from repomap_kg.observations.raw import RawObservation
from repomap_kg.extractors.shell.base import slug


def command_argument_observations(
    relative_path: str,
    line_number: int,
    command_name: str,
    arguments: list[str],
    *,
    segment_index: int,
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    for index, argument in enumerate(arguments, start=1):
        if argument in {"|", "&&", "||"}:
            continue
        metadata = command_argument_metadata(command_name, argument, index)
        observations.append(
            RawObservation(
                kind="shell.command_argument",
                source_id=f"{relative_path}#zsh-command-argument:{line_number}:{segment_index}:{index}:{slug(command_name + '-' + metadata['argument_display'])}",
                path=relative_path,
                start_line=line_number,
                end_line=line_number,
                name=metadata["argument_display"],
                confidence="heuristic",
                extractor=EXTRACTOR,
                extractor_version=__version__,
                metadata=zsh_metadata(metadata),
            )
        )
        if metadata.get("redacted"):
            observations.append(
                secret_like_observation(
                    relative_path,
                    line_number,
                    command_name,
                    "command_argument",
                    str(metadata.get("redaction_reason") or "secret-like-value"),
                )
            )
    return tuple(observations)


def command_argument_metadata(command_name: str, argument: str, index: int) -> dict[str, Any]:
    redacted, reason = redaction_for_value(argument)
    dynamic = is_dynamic_value(argument)
    if redacted:
        display = "[redacted]"
        raw_value_stored = False
        argument_kind = "redacted"
    elif dynamic:
        display = "[dynamic]"
        raw_value_stored = False
        argument_kind = "dynamic"
    else:
        display = argument
        raw_value_stored = True
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", argument):
            argument_kind = "assignment_overlay"
        elif argument.startswith("--"):
            argument_kind = "long_flag"
        elif argument.startswith("-") and argument != "-":
            argument_kind = "short_flag"
        else:
            argument_kind = "positional"
    metadata: dict[str, Any] = {
        "command_name": command_name,
        "argument_index": index,
        "argument_kind": argument_kind,
        "argument_display": display,
        "raw_value_stored": raw_value_stored,
        "redacted": redacted,
        "command_executed": False,
    }
    if redacted:
        metadata["redaction_reason"] = reason
    elif dynamic:
        metadata["dynamic_reason"] = "dynamic_argument"
    else:
        metadata["value"] = argument
    return metadata


def redirect_observations(
    relative_path: str,
    line_number: int,
    line: str,
) -> tuple[RawObservation, ...]:
    words = split_words(line)
    observations: list[RawObservation] = []
    index = 0
    redirect_index = 0
    while index < len(words):
        word = words[index]
        if word in {"2>&1"}:
            redirect_index += 1
            observations.append(
                redirect_observation(relative_path, line_number, redirect_index, word, None)
            )
        elif word in {">", ">>", "<", "2>", "2>>", "&>", "<<<"}:
            target_token = words[index + 1] if index + 1 < len(words) else ""
            redirect_index += 1
            observations.append(
                redirect_observation(
                    relative_path,
                    line_number,
                    redirect_index,
                    word,
                    target_token,
                )
            )
            index += 1
        index += 1
    return tuple(observations)


def redirect_observation(
    relative_path: str,
    line_number: int,
    redirect_index: int,
    operator: str,
    target_token: str | None,
) -> RawObservation:
    mode = redirect_mode(operator)
    target_kind = "unknown" if target_token is None else token_target_kind(target_token)
    display = "fd:1" if operator == "2>&1" else target_display(target_token or "", target_kind)
    metadata = {
        "redirect_operator": operator,
        "mode": mode,
        "target_kind": target_kind,
        "target_display": display,
        "raw_value_stored": target_kind == "static",
        "file_read": False,
        "file_write": False,
        "command_executed": False,
    }
    target = f"file:{target_token}" if target_token and target_kind == "static" else None
    return RawObservation(
        kind="shell.redirect",
        source_id=f"{relative_path}#zsh-redirect:{line_number}:{redirect_index}:{slug(operator + '-' + display)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=display,
        target=target,
        confidence="heuristic" if target_kind == "static" else "unknown",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=zsh_metadata(metadata),
    )


def heredoc_observation(
    relative_path: str,
    start_line: int,
    end_line: int,
    delimiter: str,
    body_line_count: int,
    *,
    unterminated: bool = False,
) -> RawObservation:
    return RawObservation(
        kind="shell.heredoc",
        source_id=f"{relative_path}#zsh-heredoc:{start_line}:{slug(delimiter)}",
        path=relative_path,
        start_line=start_line,
        end_line=end_line,
        name="heredoc",
        confidence="heuristic",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=zsh_metadata(
            {
                "delimiter": delimiter,
                "raw_body_stored": False,
                "body_line_count": body_line_count,
                "unterminated": unterminated,
                "command_executed": False,
            }
        ),
    )


def pipeline_observation(
    relative_path: str,
    line_number: int,
    segment_count: int,
    operators: list[str],
) -> RawObservation:
    return RawObservation(
        kind="shell.pipeline",
        source_id=f"{relative_path}#zsh-pipeline:{line_number}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name="pipeline",
        confidence="heuristic",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=zsh_metadata(
            {
                "segment_count": segment_count,
                "operators": [operator for operator in operators if operator == "|"],
                "object_or_byte_flow_modeled": False,
                "control_flow_modeled": False,
                "command_executed": False,
            }
        ),
    )


def command_chain_observation(
    relative_path: str,
    line_number: int,
    segment_count: int,
    operators: list[str],
) -> RawObservation:
    return RawObservation(
        kind="shell.command_chain",
        source_id=f"{relative_path}#zsh-command-chain:{line_number}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name="command-chain",
        confidence="heuristic",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=zsh_metadata(
            {
                "segment_count": segment_count,
                "operators": operators,
                "control_flow_modeled": False,
                "command_executed": False,
            }
        ),
    )
