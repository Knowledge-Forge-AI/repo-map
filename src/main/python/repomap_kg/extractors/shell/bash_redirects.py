"""Bash redirect, process-substitution, and heredoc observation helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from repomap_kg import __version__
from repomap_kg.extractors.shared.observations import (
    secret_like_observation as build_secret_like_observation,
)
from repomap_kg.extractors.shell.bash_arguments import argument_value_kind
from repomap_kg.extractors.shell.bash_common import (
    ASSIGNMENT_RE,
    EXTRACTOR,
    bash_metadata,
    redaction_for_name,
)
from repomap_kg.observations.raw import RawObservation
from repomap_kg.extractors.shell.base import slug


REDIRECT_OPERATORS = frozenset({">", ">>", "<", "2>", "2>>", "2>&1", "&>", "<<<"})
PROFILE_PATH_FRAGMENTS = frozenset(
    {".bashrc", ".bash_profile", ".profile", "/etc/profile", "/etc/bash.bashrc"}
)


@dataclass
class PendingHeredoc:
    start_line: int
    command_source_id: str | None
    delimiter: str
    delimiter_quoted: bool
    tab_stripping: bool
    body_line_count: int = 0
    secret_like_assignment_count: int = 0


def extract_process_substitution_specs(tokens: list[str]) -> tuple[list[str], list[str]]:
    directions: list[str] = []
    output: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in {"<(", ">("}:
            direction = "input" if token == "<(" else "output"
            directions.append(direction)
            output.append(f"[process-substitution:{direction}]")
            depth = 1
            index += 1
            while index < len(tokens) and depth > 0:
                if tokens[index] in {"<(", ">("}:
                    depth += 1
                elif tokens[index] == ")":
                    depth -= 1
                index += 1
            continue
        output.append(token)
        index += 1
    return directions, output


def process_substitution_observation(
    relative_path: str,
    line_number: int,
    *,
    command_source_id: str | None,
    direction: str,
) -> RawObservation:
    metadata: dict[str, Any] = {
        "direction": direction,
        "inner_modeled": False,
        "dynamic_reason": "process-substitution",
        "resolution": "dynamic",
    }
    if command_source_id is not None:
        metadata["command_source_id"] = command_source_id
    return RawObservation(
        kind="shell.process_substitution",
        source_id=f"{relative_path}#bash-process-substitution:{line_number}:{direction}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=f"{direction}-process-substitution",
        confidence="unknown",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=bash_metadata(metadata),
    )


def extract_redirect_observations(
    relative_path: str,
    line_number: int,
    tokens: list[str],
    *,
    command_source_id: str,
) -> tuple[list[RawObservation], list[str]]:
    observations: list[RawObservation] = []
    cleaned: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in {"<<", "<<-"}:
            index += 2
            continue
        if token in REDIRECT_OPERATORS:
            target = None
            consumed = 1
            if token not in {"2>&1"} and index + 1 < len(tokens):
                target = tokens[index + 1]
                consumed = 2
            observations.append(
                redirect_observation(
                    relative_path,
                    line_number,
                    command_source_id,
                    token,
                    target,
                )
            )
            index += consumed
            continue
        cleaned.append(token)
        index += 1
    return observations, cleaned


def redirect_observation(
    relative_path: str,
    line_number: int,
    command_source_id: str,
    operator: str,
    target: str | None,
) -> RawObservation:
    metadata = redirect_metadata(command_source_id, operator, target)
    return RawObservation(
        kind="shell.redirect",
        source_id=f"{command_source_id}:redirect:{slug(operator)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=operator,
        confidence="heuristic",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=bash_metadata(metadata),
    )


def redirect_metadata(
    command_source_id: str,
    operator: str,
    target: str | None,
) -> dict[str, Any]:
    mode = {
        ">": "truncate",
        ">>": "append",
        "<": "read",
        "2>": "truncate",
        "2>>": "append",
        "2>&1": "duplicate",
        "&>": "truncate",
        "<<<": "here_string",
    }.get(operator, "unknown")
    target_kind = "none"
    target_display = None
    value_kind = "omitted"
    raw_value_stored = False
    target_profile_like = False
    if operator == "2>&1":
        target_kind = "fd"
        target_display = "1"
        value_kind = "static"
        raw_value_stored = True
    elif target is not None:
        target_profile_like = is_profile_like_target(target)
        value_kind = argument_value_kind(target)
        if value_kind in {"dynamic", "command_substitution", "process_substitution"}:
            target_kind = "dynamic"
            target_display = "[dynamic]"
            raw_value_stored = False
        else:
            target_kind = "static"
            target_display = target
            raw_value_stored = True
    return {
        "command_source_id": command_source_id,
        "operator": operator,
        "fd": redirect_fd(operator),
        "mode": mode,
        "target_kind": target_kind,
        "target_display": target_display,
        "target_redacted": False,
        "raw_value_stored": raw_value_stored,
        "value_kind": value_kind,
        "target_profile_like": target_profile_like,
    }


def is_profile_like_target(target: str) -> bool:
    return any(fragment in target for fragment in PROFILE_PATH_FRAGMENTS)


def redirect_fd(operator: str) -> str | None:
    match = re.match(r"^([0-9]+)", operator)
    if match is not None:
        return match.group(1)
    if operator == "<":
        return "0"
    if operator in {">", ">>", "&>", "<<<"}:
        return "1"
    return None


def heredoc_observation(
    relative_path: str,
    end_line: int,
    pending: PendingHeredoc,
) -> RawObservation:
    metadata: dict[str, Any] = {
        "command_source_id": pending.command_source_id,
        "delimiter": pending.delimiter,
        "delimiter_quoted": pending.delimiter_quoted,
        "tab_stripping": pending.tab_stripping,
        "body_line_count": pending.body_line_count,
        "secret_like_assignment_count": pending.secret_like_assignment_count,
        "raw_body_stored": False,
        "expansion_mode": "literal" if pending.delimiter_quoted else "expandable",
    }
    return RawObservation(
        kind="shell.heredoc",
        source_id=f"{relative_path}#bash-heredoc:{pending.start_line}:{slug(pending.delimiter)}",
        path=relative_path,
        start_line=pending.start_line,
        end_line=end_line,
        name=pending.delimiter,
        confidence="heuristic",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=bash_metadata(metadata),
    )


def heredoc_secret_like_observations(
    relative_path: str,
    line_number: int,
    raw_line: str,
) -> tuple[RawObservation, ...]:
    match = ASSIGNMENT_RE.match(raw_line.strip())
    if match is None:
        return ()
    variable = match.group(1)
    redacted, reason = redaction_for_name(variable)
    if not redacted:
        return ()
    return (
        build_secret_like_observation(
            relative_path=relative_path,
            line_number=line_number,
            name=variable,
            secret_source="heredoc",
            reason=reason,
            source_prefix="bash",
            extractor=EXTRACTOR,
            extractor_version=__version__,
            metadata_builder=bash_metadata,
            slugger=slug,
        ),
    )
