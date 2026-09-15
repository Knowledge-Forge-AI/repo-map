"""Bash command-line segmentation and command observation helpers."""

from __future__ import annotations

import re
import shlex

from repomap_kg import __version__
from repomap_kg.extractors.shell.bash_arguments import argument_observations
from repomap_kg.extractors.shell.bash_commands import (
    command_context_metadata,
    command_family,
    command_observation,
    command_source_id_for,
    command_token_from_segment,
    external_command_observation,
    wrapped_command_for,
)
from repomap_kg.extractors.shell.bash_common import (
    ARRAY_ASSIGNMENT_RE,
    ASSIGNMENT_RE,
    EXTRACTOR,
    bash_metadata,
)
from repomap_kg.extractors.shell.bash_redirects import (
    extract_process_substitution_specs,
    extract_redirect_observations,
    process_substitution_observation,
)
from repomap_kg.extractors.shell.bash_side_effects import side_effect_observations
from repomap_kg.observations.raw import RawObservation


STRUCTURAL_COMMANDS = frozenset(
    {
        "export",
        "source",
        ".",
        "set",
        "shopt",
        "alias",
        "trap",
        "let",
        "local",
        "declare",
        "readonly",
        "typeset",
    }
)
SHELL_SYNTAX_WORDS = frozenset(
    {
        "case",
        "do",
        "done",
        "elif",
        "else",
        "esac",
        "fi",
        "for",
        "if",
        "in",
        "then",
        "until",
        "while",
        "{",
        "}",
    }
)
CHAIN_OPERATORS = frozenset({"&&", "||"})
PIPE_OPERATORS = frozenset({"|", "|&"})


def command_line_observations(
    relative_path: str,
    line_number: int,
    raw_line: str,
) -> tuple[RawObservation, ...]:
    stripped = raw_line.strip()
    if should_skip_command_line(stripped):
        return ()
    tokens = shell_tokens(raw_line)
    if not tokens:
        return ()
    tokens = combine_redirect_tokens(tokens)
    observations: list[RawObservation] = []
    chain_segments, chain_operators = split_segments(tokens, CHAIN_OPERATORS)
    chain_id = None
    if chain_operators:
        chain_id = f"{relative_path}#bash-chain:{line_number}"
        observations.append(
            command_chain_observation(
                relative_path,
                line_number,
                chain_id,
                chain_operators,
                len(chain_segments),
            )
        )
    for chain_index, chain_segment in enumerate(chain_segments):
        pipeline_segments, pipeline_operators = split_segments(
            chain_segment,
            PIPE_OPERATORS,
        )
        pipeline_id = None
        if pipeline_operators:
            pipeline_id = f"{relative_path}#bash-pipeline:{line_number}:{chain_index}"
            observations.append(
                pipeline_observation(
                    relative_path,
                    line_number,
                    pipeline_id,
                    pipeline_operators,
                    len(pipeline_segments),
                )
            )
        for pipeline_index, pipeline_segment in enumerate(pipeline_segments):
            observations.extend(
                command_segment_observations(
                    relative_path,
                    line_number,
                    pipeline_segment,
                    chain_id=chain_id,
                    chain_index=chain_index if chain_id is not None else None,
                    pipeline_id=pipeline_id,
                    pipeline_index=pipeline_index if pipeline_id is not None else None,
                )
            )
    return tuple(observations)


def should_skip_command_line(stripped: str) -> bool:
    if not stripped or stripped.startswith("#"):
        return True
    if stripped in {"{", "}", ";;", ";&", ";;&"}:
        return True
    if stripped.startswith(("alias ", "trap ", "let ")):
        return True
    if ARRAY_ASSIGNMENT_RE.match(stripped) is not None:
        return True
    if re.match(r"^\(\(.*\)\)\s*$", stripped):
        return True
    if is_dynamic_invocation_line(stripped):
        return True
    if is_dynamic_assignment_only_line(stripped):
        return True
    if is_case_label(stripped):
        return True
    return False


def is_dynamic_invocation_line(stripped: str) -> bool:
    return bool(
        re.match(r"^eval(?:\s|$)", stripped)
        or re.match(r"^command\s+eval(?:\s|$)", stripped)
        or re.match(r"^\$[A-Za-z_][A-Za-z0-9_]*(?:\s|$)", stripped)
        or re.match(r'^"?\$[A-Za-z_][A-Za-z0-9_]*"?(?:\s|$)', stripped)
        or re.match(r'^"?\$\{[A-Za-z_][A-Za-z0-9_]*\[@\]\}"?(?:\s|$)', stripped)
        or re.match(r"^bash\s+-c(?:\s|$)", stripped)
        or re.match(r"^sh\s+-c(?:\s|$)", stripped)
    )


def is_dynamic_assignment_only_line(stripped: str) -> bool:
    match = ASSIGNMENT_RE.match(stripped)
    if match is None:
        return False
    value = match.group(2)
    return value.startswith(("`", "$("))


def is_case_label(stripped: str) -> bool:
    if not stripped.endswith(")"):
        return False
    if stripped.startswith(("if ", "while ", "for ", "function ")):
        return False
    return bool(re.match(r"^[A-Za-z0-9_.*?|-]+\)$", stripped))


def shell_tokens(raw_line: str) -> list[str]:
    try:
        lexer = shlex.shlex(raw_line, posix=True, punctuation_chars="|&;<>()")
        lexer.whitespace_split = True
        lexer.commenters = ""
        return list(lexer)
    except ValueError:
        return []


def combine_redirect_tokens(tokens: list[str]) -> list[str]:
    combined: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if (
            token.isdigit()
            and index + 2 < len(tokens)
            and tokens[index + 1] == ">&"
            and tokens[index + 2].isdigit()
        ):
            combined.append(f"{token}>&{tokens[index + 2]}")
            index += 3
            continue
        if (
            token.isdigit()
            and index + 1 < len(tokens)
            and tokens[index + 1] in {">", ">>", "<"}
        ):
            combined.append(f"{token}{tokens[index + 1]}")
            index += 2
            continue
        combined.append(token)
        index += 1
    return combined


def split_segments(
    tokens: list[str],
    operators: frozenset[str],
) -> tuple[list[list[str]], list[str]]:
    segments: list[list[str]] = [[]]
    found: list[str] = []
    for token in tokens:
        if token in operators:
            found.append(token)
            segments.append([])
            continue
        segments[-1].append(token)
    return [segment for segment in segments if segment], found


def command_chain_observation(
    relative_path: str,
    line_number: int,
    chain_id: str,
    operators: list[str],
    segment_count: int,
) -> RawObservation:
    return RawObservation(
        kind="shell.command_chain",
        source_id=chain_id,
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name="command-chain",
        confidence="heuristic",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=bash_metadata(
            {
                "chain_id": chain_id,
                "segment_count": segment_count,
                "operators": operators,
                "control_flow_modeled": False,
            }
        ),
    )


def pipeline_observation(
    relative_path: str,
    line_number: int,
    pipeline_id: str,
    operators: list[str],
    segment_count: int,
) -> RawObservation:
    return RawObservation(
        kind="shell.pipeline",
        source_id=pipeline_id,
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name="pipeline",
        confidence="heuristic",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=bash_metadata(
            {
                "pipeline_id": pipeline_id,
                "segment_count": segment_count,
                "operators": operators,
                "object_or_byte_flow_modeled": False,
            }
        ),
    )


def command_segment_observations(
    relative_path: str,
    line_number: int,
    tokens: list[str],
    *,
    chain_id: str | None,
    chain_index: int | None,
    pipeline_id: str | None,
    pipeline_index: int | None,
) -> tuple[RawObservation, ...]:
    if not tokens:
        return ()
    process_observation_specs, tokens = extract_process_substitution_specs(tokens)
    command_token_info = command_token_from_segment(tokens)
    if command_token_info is None:
        return tuple(
            process_substitution_observation(
                relative_path,
                line_number,
                command_source_id=None,
                direction=direction,
            )
            for direction in process_observation_specs
        )
    command_index, overlays, command_name = command_token_info
    if command_name in STRUCTURAL_COMMANDS or command_name in SHELL_SYNTAX_WORDS:
        return ()
    command_source_id = command_source_id_for(
        relative_path,
        line_number,
        command_name,
        chain_index=chain_index,
        pipeline_index=pipeline_index,
    )
    redirect_observations, tokens_without_redirects = extract_redirect_observations(
        relative_path,
        line_number,
        tokens,
        command_source_id=command_source_id,
    )
    command_index, overlays, command_name = command_token_from_segment(
        tokens_without_redirects
    ) or command_token_info
    if command_name in STRUCTURAL_COMMANDS or command_name in SHELL_SYNTAX_WORDS:
        return tuple(redirect_observations)
    args = tokens_without_redirects[command_index + 1 :]
    family = command_family(command_name)
    wrapped_command = wrapped_command_for(command_name, args) if family == "wrapper" else None
    context = command_context_metadata(
        chain_id=chain_id,
        chain_index=chain_index,
        pipeline_id=pipeline_id,
        pipeline_index=pipeline_index,
    )
    observations: list[RawObservation] = []
    observations.append(
        command_observation(
            relative_path,
            line_number,
            command_source_id,
            command_name,
            family,
            overlays=overlays,
            args=args,
            wrapped_command=wrapped_command,
            context=context,
        )
    )
    if family == "external":
        observations.append(
            external_command_observation(
                relative_path,
                line_number,
                command_source_id,
                command_name,
                context=context,
            )
        )
    observations.extend(redirect_observations)
    for direction in process_observation_specs:
        observations.append(
            process_substitution_observation(
                relative_path,
                line_number,
                command_source_id=command_source_id,
                direction=direction,
            )
        )
    observations.extend(
        argument_observations(
            relative_path,
            line_number,
            command_source_id,
            command_name,
            overlays=overlays,
            args=args,
            context=context,
        )
    )
    observations.extend(
        side_effect_observations(
            relative_path,
            line_number,
            command_source_id,
            command_name,
            overlays=overlays,
            args=args,
            redirects=redirect_observations,
            context=context,
            wrapped_command=wrapped_command,
        )
    )
    return tuple(observations)
