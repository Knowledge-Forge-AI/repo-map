"""Conservative static zsh raw observation extraction."""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from typing import Any

from repomap_kg import __version__
from repomap_kg.extractors.shell.zsh_common import (
    DYNAMIC_TARGET_CHARS,
    EXTRACTOR,
    PLUGIN_MANAGER_NAMES,
    PROMPT_VARIABLES,
    SECRET_NAME_PARTS,
    ZSH_STARTUP_FILENAMES,
    assignment_operation,
    brace_delta,
    configuration_metadata,
    has_command_substitution,
    is_dynamic_value,
    is_quoted_at,
    mask_quoted_text,
    parse_export_word,
    plugin_metadata,
    redaction_for_assignment,
    redaction_for_name,
    redaction_for_value,
    safe_short_value,
    secret_like_observation,
    side_effect_metadata,
    split_words,
    strip_inline_comment,
    strip_wrapping_quotes,
    syntax_metadata,
    target_display,
    token_target_kind,
    value_kind,
    zsh_metadata,
)
from repomap_kg.extractors.shell.zsh_identity import (
    ZSH_COMPLETION_PATH_PARTS,
    ZSH_SHEBANG_RE,
    ZSH_STARTUP_ORDER,
    classification_evidence,
    completion_function_observations,
    file_type,
    has_completion_content_evidence,
    is_zsh_completion_candidate,
    is_zsh_file_path,
    is_zsh_shebang,
    is_zsh_startup_file_path,
    startup_file_observation,
    zsh_script_observation,
)
from repomap_kg.extractors.shell.zsh_advanced import (
    ASSOCIATIVE_DECLARATION_RE,
    ARRAY_ASSIGNMENT_RE,
    PARAMETER_EXPANSION_RE,
    array_assignment_observations,
    associative_array_observations,
    clean_glob_token,
    extended_glob_feature,
    extended_glob_observation,
    glob_and_path_observations,
    glob_candidate_tokens,
    glob_pattern_kind,
    glob_qualifier,
    glob_qualifier_observation,
    has_unquoted_parameter_expansion,
    is_dynamic_glob_token,
    parameter_expansion_context,
    parameter_expansion_observations,
    parameter_flag_summary,
    parse_array_assignment,
    parse_associative_declaration,
    parse_associative_pairs,
    path_reference_observation,
    visible_parameter_name,
    zsh_dynamic_marker,
    zsh_specific_dynamic_observations,
)
from repomap_kg.extractors.shell.zsh_commands import (
    ASSIGNMENT_RE,
    COMMAND_WRAPPERS,
    CONTROL_KEYWORDS,
    EXTERNAL_COMMANDS,
    ZSH_BUILTINS,
    command_family,
    first_command_index,
    is_case_label_line,
    is_command_token,
    is_dynamic_command_token,
    should_skip_command_syntax,
    split_command_segments,
    words_without_redirects,
    wrapped_command_index,
)
from repomap_kg.extractors.shell.zsh_command_observations import (
    command_argument_metadata,
    command_argument_observations,
    command_chain_observation,
    heredoc_observation,
    pipeline_observation,
    redirect_observation,
    redirect_observations,
)
from repomap_kg.extractors.shell.zsh_command_scanning import (
    command_observation,
    command_observations_for_segment,
    command_substitution_observations,
    command_syntax_observations,
    dynamic_invocation_observations,
    dynamic_marker,
    external_command_observation,
    redirect_file_intent_observations,
    side_effect_intent_observations,
    zsh3_advanced_observations,
)
from repomap_kg.extractors.shell.zsh_configuration import (
    autoload_observations,
    bindkey_observations,
    compinit_observations,
    fpath_observations,
    oh_my_zsh_plugin_array_observations,
    plugin_manager_command_observations,
    plugin_manager_observation,
    plugin_observation,
    plugin_theme_prompt_observations,
    theme_prompt_observations,
    zmodload_observations,
    zsh2_configuration_observations,
    zstyle_observations,
)
from repomap_kg.extractors.shell.zsh_side_effects import (
    FILESYSTEM_MUTATION_COMMANDS,
    NETWORK_COMMANDS,
    PACKAGE_MANAGER_COMMANDS,
    env_intent_observations,
    env_observation,
    env_reads_from_value,
    file_intent_observation,
    filesystem_mutation_intent_observations,
    first_package_target,
    first_staticish_target,
    host_mutation_intent_observation,
    network_intent_observations,
    package_manager_intent_observations,
    package_operation,
)
from repomap_kg.observations.raw import RawObservation
from repomap_kg.extractors.shell.base import slug


FUNCTION_PARENS_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(\s*\)\s*\{")
FUNCTION_KEYWORD_RE = re.compile(
    r"^\s*function\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?:\(\s*\))?\s*\{"
)
HEREDOC_RE = re.compile(r"(?<!<)<<(?!<)-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
COMMAND_SUB_RE = re.compile(r"\$\(")
BACKTICK_SUB_RE = re.compile(r"`")
HOOK_FUNCTIONS = frozenset({"precmd", "preexec", "chpwd"})


@dataclass
class PendingHeredoc:
    delimiter: str
    tab_stripping: bool
    start_line: int
    body_line_count: int = 0


def extract_zsh_file_observations(
    relative_path: str,
    content: str,
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = [
        zsh_script_observation(relative_path, content)
    ]
    startup = startup_file_observation(relative_path)
    if startup is not None:
        observations.append(startup)
    observations.extend(completion_function_observations(relative_path, content))

    pending_heredoc: PendingHeredoc | None = None
    current_function: str | None = None
    brace_depth = 0

    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        stripped = raw_line.strip()
        if pending_heredoc is not None:
            terminator = raw_line.lstrip("\t").strip() if pending_heredoc.tab_stripping else stripped
            if terminator == pending_heredoc.delimiter:
                observations.append(
                    heredoc_observation(
                        relative_path,
                        pending_heredoc.start_line,
                        line_number,
                        pending_heredoc.delimiter,
                        pending_heredoc.body_line_count,
                    )
                )
                pending_heredoc = None
            else:
                pending_heredoc.body_line_count += 1
            continue
        if not stripped or stripped.startswith("#"):
            continue

        line = strip_inline_comment(raw_line).rstrip()
        stripped = line.strip()
        if not stripped:
            continue

        function_match = FUNCTION_PARENS_RE.match(line)
        function_syntax = "name_parens"
        if function_match is None:
            function_match = FUNCTION_KEYWORD_RE.match(line)
            function_syntax = "function_keyword"
        if function_match is not None:
            function_name = function_match.group(1)
            observations.append(
                function_observation(
                    relative_path,
                    line_number,
                    function_name,
                    function_syntax,
                )
            )
            current_function = function_name
            brace_depth = brace_delta(line)
            if brace_depth <= 0:
                current_function = None
                brace_depth = 0
            continue

        scope = "function" if current_function is not None else "file"
        observations.extend(option_observations(relative_path, line_number, line))
        source_items = source_observations(relative_path, line_number, line)
        observations.extend(source_items)
        observations.extend(
            assignment_and_export_observations(
                relative_path,
                line_number,
                line,
                scope=scope,
                function_name=current_function,
            )
        )
        observations.extend(
            command_substitution_observations(relative_path, line_number, line)
        )
        observations.extend(
            dynamic_invocation_observations(
                relative_path,
                line_number,
                line,
                source_items=source_items,
            )
        )
        observations.extend(zsh2_configuration_observations(relative_path, line_number, line))
        observations.extend(
            command_syntax_observations(relative_path, line_number, line)
        )
        observations.extend(zsh3_advanced_observations(relative_path, line_number, line))
        heredoc_match = HEREDOC_RE.search(line)
        if heredoc_match is not None:
            pending_heredoc = PendingHeredoc(
                delimiter=heredoc_match.group(2),
                tab_stripping="<<-" in line,
                start_line=line_number,
            )

        if current_function is not None:
            brace_depth += brace_delta(line)
            if brace_depth <= 0:
                current_function = None
                brace_depth = 0

    if pending_heredoc is not None:
        observations.append(
            heredoc_observation(
                relative_path,
                pending_heredoc.start_line,
                pending_heredoc.start_line,
                pending_heredoc.delimiter,
                pending_heredoc.body_line_count,
                unterminated=True,
            )
        )

    return tuple(observations)


def option_observations(
    relative_path: str,
    line_number: int,
    line: str,
) -> tuple[RawObservation, ...]:
    words = split_words(line)
    if not words:
        return ()
    observations: list[RawObservation] = []
    if words[0] == "setopt":
        observations.extend(
            option_observation(relative_path, line_number, option, "set", "setopt")
            for option in words[1:]
            if not option.startswith("-")
        )
    elif words[0] == "unsetopt":
        observations.extend(
            option_observation(relative_path, line_number, option, "unset", "unsetopt")
            for option in words[1:]
            if not option.startswith("-")
        )
    elif words[0] == "emulate" and any(word == "zsh" for word in words[1:]):
        option_scope = "function_local" if "-L" in words[1:] else "file"
        observations.append(
            option_observation(
                relative_path,
                line_number,
                "zsh",
                "emulate",
                "emulate",
                option_scope=option_scope,
            )
        )
    return tuple(observations)


def option_observation(
    relative_path: str,
    line_number: int,
    option_name: str,
    operation: str,
    source_form: str,
    *,
    option_scope: str = "file",
) -> RawObservation:
    return RawObservation(
        kind="zsh.option",
        source_id=f"{relative_path}#zsh-option:{line_number}:{slug(operation + '-' + option_name)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=option_name,
        confidence="extracted",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=zsh_metadata(
            {
                "option_name": option_name,
                "operation": operation,
                "option_scope": option_scope,
                "runtime_option_state_known": False,
                "source_form": source_form,
            }
        ),
    )


def function_observation(
    relative_path: str,
    line_number: int,
    function_name: str,
    syntax: str,
) -> RawObservation:
    metadata: dict[str, Any] = {
        "function_name": function_name,
        "syntax": syntax,
        "body_modeled": False,
    }
    if function_name in HOOK_FUNCTIONS:
        metadata["zsh_function_kind"] = "hook"
    return RawObservation(
        kind="shell.function",
        source_id=f"{relative_path}#zsh-function:{line_number}:{slug(function_name)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=function_name,
        confidence="extracted",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=zsh_metadata(metadata),
    )


def assignment_and_export_observations(
    relative_path: str,
    line_number: int,
    line: str,
    *,
    scope: str,
    function_name: str | None,
) -> tuple[RawObservation, ...]:
    words = split_words(line)
    if not words:
        return ()
    observations: list[RawObservation] = []
    if words[0] == "export":
        for word in words[1:]:
            parsed = parse_export_word(word)
            if parsed is None:
                continue
            variable, value = parsed
            export = export_observation(
                relative_path,
                line_number,
                variable,
                value,
                scope=scope,
                function_name=function_name,
            )
            observations.append(export)
            if value is not None:
                observations.extend(secret_observations_for(export, line_number))
        return tuple(observations)

    declaration = None
    assignment_words = [line.strip()]
    if words[0] in {"typeset", "local", "readonly"}:
        declaration = words[0]
        assignment_words = [word for word in words[1:] if not word.startswith("-")]
    for word in assignment_words:
        match = ASSIGNMENT_RE.match(word)
        if match is None:
            continue
        variable, value = match.group(1), match.group(2).strip()
        assignment = assignment_observation(
            relative_path,
            line_number,
            variable,
            value,
            declaration=declaration,
            scope=scope,
            function_name=function_name,
        )
        observations.append(assignment)
        observations.extend(secret_observations_for(assignment, line_number))
    return tuple(observations)



def assignment_observation(
    relative_path: str,
    line_number: int,
    variable: str,
    value: str,
    *,
    declaration: str | None,
    scope: str,
    function_name: str | None,
) -> RawObservation:
    redacted, reason = redaction_for_assignment(variable, value)
    metadata: dict[str, Any] = {
        "variable": variable,
        "operation": assignment_operation(variable, value),
        "declaration_keyword": declaration,
        "scope": scope,
        "value_kind": "redacted" if redacted else value_kind(value),
        "value_present": True,
        "redacted": redacted,
        "raw_value_stored": not redacted,
    }
    if function_name is not None:
        metadata["function"] = function_name
    if redacted:
        metadata["redaction_reason"] = reason
    else:
        metadata["value"] = strip_wrapping_quotes(value)
    return RawObservation(
        kind="shell.assignment",
        source_id=f"{relative_path}#zsh-assignment:{line_number}:{slug(variable)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=variable,
        confidence="extracted",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=zsh_metadata(metadata),
    )


def export_observation(
    relative_path: str,
    line_number: int,
    variable: str,
    value: str | None,
    *,
    scope: str,
    function_name: str | None,
) -> RawObservation:
    redacted, reason = redaction_for_assignment(variable, value or "")
    metadata: dict[str, Any] = {
        "variable": variable,
        "operation": "export",
        "scope": scope,
        "value_kind": "omitted" if value is None else ("redacted" if redacted else value_kind(value)),
        "value_present": value is not None,
        "redacted": redacted if value is not None else False,
        "raw_value_stored": value is not None and not redacted,
    }
    if function_name is not None:
        metadata["function"] = function_name
    if value is not None and redacted:
        metadata["redaction_reason"] = reason
    elif value is not None:
        metadata["value"] = strip_wrapping_quotes(value)
    return RawObservation(
        kind="shell.export",
        source_id=f"{relative_path}#zsh-export:{line_number}:{slug(variable)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=variable,
        confidence="extracted",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=zsh_metadata(metadata),
    )


def secret_observations_for(
    observation: RawObservation,
    line_number: int,
) -> tuple[RawObservation, ...]:
    if not observation.metadata.get("redacted"):
        return ()
    reason = str(observation.metadata.get("redaction_reason") or "secret-like-value")
    return (
        secret_like_observation(
            observation.path,
            line_number,
            observation.name or "unknown",
            "export" if observation.kind == "shell.export" else "assignment",
            reason,
        ),
    )


def source_observations(
    relative_path: str,
    line_number: int,
    line: str,
) -> tuple[RawObservation, ...]:
    words = split_words(line)
    if len(words) < 2 or words[0] not in {"source", "."}:
        return ()
    syntax = "source" if words[0] == "source" else "dot"
    target_token = words[1]
    target, metadata = source_target(relative_path, target_token)
    metadata.update(
        {
            "syntax": syntax,
            "target_token": target_display(target_token, metadata["target_kind"]),
            "source_executed": False,
            "file_read": False,
        }
    )
    observations: list[RawObservation] = [
        RawObservation(
            kind="shell.source",
            source_id=f"{relative_path}#zsh-source:{line_number}:{slug(metadata['target_kind'] + '-' + target_token)}",
            path=relative_path,
            start_line=line_number,
            end_line=line_number,
            name=metadata["target_display"],
            target=target,
            confidence="heuristic" if metadata["target_kind"] == "static" else "unknown",
            extractor=EXTRACTOR,
            extractor_version=__version__,
            metadata=zsh_metadata(metadata),
        )
    ]
    if metadata.get("redacted"):
        observations.append(
            secret_like_observation(
                relative_path,
                line_number,
                "source",
                "source-target",
                str(metadata.get("redaction_reason") or "secret-like-value"),
            )
        )
    return tuple(observations)


def source_target(relative_path: str, target_token: str) -> tuple[str | None, dict[str, Any]]:
    redacted, reason = redaction_for_value(target_token)
    if redacted:
        return None, {
            "target_kind": "redacted",
            "target_display": "[redacted]",
            "resolution": "unknown",
            "redacted": True,
            "redaction_reason": reason,
            "raw_value_stored": False,
        }
    if (
        not target_token
        or target_token.startswith("/")
        or target_token.startswith("~")
        or any(character in target_token for character in DYNAMIC_TARGET_CHARS)
    ):
        return None, {
            "target_kind": "dynamic",
            "target_display": "[dynamic]",
            "resolution": "dynamic",
            "dynamic_reason": "computed_source",
            "redacted": False,
            "raw_value_stored": False,
        }
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(relative_path), target_token))
    if resolved == "." or resolved.startswith("../"):
        return None, {
            "target_kind": "unknown",
            "target_display": "[unknown]",
            "resolution": "unknown",
            "unknown_reason": "repo-escaping-source",
            "redacted": False,
            "raw_value_stored": False,
        }
    return f"file:{resolved}", {
        "target_kind": "static",
        "target_display": target_token,
        "resolution": "static",
        "resolved_path": resolved,
        "redacted": False,
        "raw_value_stored": True,
    }
