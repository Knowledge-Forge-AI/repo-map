"""Conservative static Bash raw observation extraction."""

from __future__ import annotations

import posixpath
import re
from typing import Any

from repomap_kg import __version__
from repomap_kg.extractors.shell.bash_arguments import (
    LONG_FLAGS_WITH_VALUE,
    SHORT_FLAGS_WITH_VALUE,
    argument_metadata,
    argument_observations,
    argument_redaction,
    command_argument_observation,
    long_argument_observation,
    short_argument_observation,
)
from repomap_kg.extractors.shell.bash_constructs import (
    TEST_OPERATORS,
    alias_observations,
    alias_redaction,
    alias_target_command_like,
    alias_target_summary,
    arithmetic_observation,
    arithmetic_observations,
    arithmetic_variables,
    array_assignment_observation,
    array_assignment_observations,
    associative_array_assignment_observation,
    case_pattern_observation,
    first_command_source_id,
    parse_alias_spec,
    parse_associative_entries,
    secret_like_observation,
    split_array_values,
    test_expression_observations,
    test_expression_spec,
    trap_handler_summary,
    trap_observations,
)
from repomap_kg.extractors.shell.bash_common import (
    ASSIGNMENT_RE,
    BACKTICK_SUB_RE,
    COMMAND_SUB_RE,
    EXTRACTOR,
    is_dynamic_value,
    SECRET_NAME_PARTS,
    SENSITIVE_ENV_NAMES,
    bash_metadata,
    redaction_for_name,
    redaction_for_value,
    safe_raw_line,
    split_words,
    value_kind,
)
from repomap_kg.extractors.shell.bash_identity import (
    BASH_PROFILE_FILENAMES,
    BASH_SHEBANG_RE,
    classification_evidence,
    is_bash_file_path,
    is_bash_shebang,
    shell_script_observation,
)
from repomap_kg.extractors.shell.bash_environment import (
    ENV_READ_RE,
    env_read_observations,
    env_write_observations,
    env_write_observations_for_value,
    parse_export_word as _bash_environment_parse_export_word,
)
from repomap_kg.extractors.shell.bash_commands import (
    WRAPPER_COMMANDS,
    command_context_metadata,
    command_family,
    command_observation,
    command_source_id_for,
    command_token_from_segment,
    external_command_observation,
    next_static_command,
    wrapped_command_for,
    wrapped_command_for_env,
    wrapped_command_for_sudo,
)
from repomap_kg.extractors.shell.bash_command_lines import (
    CHAIN_OPERATORS,
    PIPE_OPERATORS,
    SHELL_SYNTAX_WORDS,
    STRUCTURAL_COMMANDS,
    combine_redirect_tokens,
    command_chain_observation,
    command_line_observations,
    command_segment_observations,
    is_case_label,
    is_dynamic_assignment_only_line,
    is_dynamic_invocation_line,
    pipeline_observation,
    shell_tokens,
    should_skip_command_line,
    split_segments,
)
from repomap_kg.extractors.shell.bash_redirects import (
    PROFILE_PATH_FRAGMENTS,
    REDIRECT_OPERATORS,
    PendingHeredoc,
    extract_process_substitution_specs,
    extract_redirect_observations,
    heredoc_observation,
    heredoc_secret_like_observations,
    is_profile_like_target,
    process_substitution_observation,
    redirect_fd,
    redirect_metadata,
    redirect_observation,
)
from repomap_kg.extractors.shell.bash_side_effects import (
    ARCHIVE_COMMANDS,
    CONTAINER_MUTATIONS,
    FILE_READ_COMMANDS,
    FILE_WRITE_COMMANDS,
    INFRASTRUCTURE_MUTATIONS,
    NETWORK_COMMANDS,
    OWNERSHIP_COMMANDS,
    PACKAGE_MANAGERS,
    PACKAGE_MUTATING_OPERATIONS,
    PERMISSION_COMMANDS,
    SECURITY_POLICY_COMMANDS,
    SERVICE_MUTATIONS,
    archive_mutation_observations,
    command_after_env,
    command_after_prefix,
    command_side_effect_observations,
    container_operation_for,
    credential_operation,
    credential_target,
    effective_command_for_side_effect,
    file_effect_observation,
    file_effect_observation_from_metadata,
    file_mutation_observations,
    file_read_target,
    host_mutation_from_target_metadata,
    host_mutation_observation,
    is_credential_command,
    last_positional,
    network_call_observation,
    network_output_target,
    network_side_effect_observations,
    network_target,
    operational_host_mutations,
    option_value,
    package_name_for_operation,
    package_operation,
    package_side_effect_observations,
    positional_args,
    redirect_side_effect_observations,
    security_policy_operation,
    side_effect_observations,
    target_metadata,
)
from repomap_kg.observations.raw import RawObservation
from repomap_kg.extractors.shell.base import slug


FUNCTION_PARENS_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(\s*\)\s*\{")
FUNCTION_KEYWORD_RE = re.compile(
    r"^\s*function\s+([A-Za-z_][A-Za-z0-9_]*)(?:\s*\(\s*\))?\s*(?:\{|$)"
)
HEREDOC_RE = re.compile(r"(?<!<)<<(?!<)-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
CASE_START_RE = re.compile(r"^case\s+(?P<expression>.+?)\s+in\s*$")
DECLARATION_KEYWORDS = frozenset({"local", "declare", "readonly", "typeset"})
DYNAMIC_SOURCE_CHARS = frozenset("$`*?[")
def extract_bash_file_observations(
    relative_path: str,
    content: str,
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = [
        shell_script_observation(relative_path, content)
    ]
    current_function: str | None = None
    brace_depth = 0
    pending_heredoc: PendingHeredoc | None = None
    case_expression_kind: str | None = None
    case_branch_index = 0

    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        stripped = raw_line.strip()
        if pending_heredoc is not None:
            terminator = raw_line.lstrip("\t").strip() if pending_heredoc.tab_stripping else stripped
            if terminator == pending_heredoc.delimiter:
                observations.append(
                    heredoc_observation(relative_path, line_number, pending_heredoc)
                )
                pending_heredoc = None
                continue
            pending_heredoc.body_line_count += 1
            secret_observations = heredoc_secret_like_observations(
                relative_path,
                line_number,
                raw_line,
            )
            if secret_observations:
                pending_heredoc.secret_like_assignment_count += len(secret_observations)
                observations.extend(secret_observations)
            continue
        if not stripped or stripped.startswith("#"):
            continue

        function_match = FUNCTION_PARENS_RE.match(raw_line)
        function_syntax = "name_parens"
        if function_match is None:
            function_match = FUNCTION_KEYWORD_RE.match(raw_line)
            function_syntax = "function_keyword"
        if function_match is not None:
            function_name = function_match.group(1)
            observations.append(
                function_observation(
                    relative_path,
                    line_number,
                    raw_line,
                    function_name,
                    function_syntax,
                )
            )
            current_function = function_name
            brace_depth = raw_line.count("{") - raw_line.count("}")
            if brace_depth <= 0:
                current_function = None
                brace_depth = 0
            continue

        scope = "function" if current_function is not None else "file"
        case_start = CASE_START_RE.match(stripped)
        if case_start is not None:
            case_expression_kind = (
                "dynamic" if is_dynamic_value(case_start.group("expression")) else "static"
            )
            case_branch_index = 0
        elif stripped == "esac":
            case_expression_kind = None
            case_branch_index = 0
            continue
        elif case_expression_kind is not None and is_case_label(stripped):
            observations.append(
                case_pattern_observation(
                    relative_path,
                    line_number,
                    stripped,
                    case_branch_index,
                    case_expression_kind,
                )
            )
            case_branch_index += 1
            continue

        observations.extend(option_observations(relative_path, line_number, raw_line))
        observations.extend(source_observations(relative_path, line_number, raw_line))
        observations.extend(
            assignment_and_export_observations(
                relative_path,
                line_number,
                raw_line,
                scope=scope,
                function_name=current_function,
            )
        )
        observations.extend(alias_observations(relative_path, line_number, raw_line))
        observations.extend(array_assignment_observations(relative_path, line_number, raw_line))
        observations.extend(trap_observations(relative_path, line_number, raw_line))
        observations.extend(arithmetic_observations(relative_path, line_number, raw_line))
        observations.extend(test_expression_observations(relative_path, line_number, raw_line))
        observations.extend(env_read_observations(relative_path, line_number, raw_line))
        observations.extend(env_write_observations(relative_path, line_number, raw_line))
        observations.extend(
            command_substitution_observations(relative_path, line_number, raw_line)
        )
        observations.extend(
            dynamic_invocation_observations(relative_path, line_number, raw_line)
        )
        command_observations = command_line_observations(
            relative_path,
            line_number,
            raw_line,
        )
        observations.extend(command_observations)
        heredoc_match = HEREDOC_RE.search(raw_line)
        if heredoc_match is not None:
            pending_heredoc = PendingHeredoc(
                start_line=line_number,
                command_source_id=first_command_source_id(command_observations),
                delimiter=heredoc_match.group(2),
                delimiter_quoted=bool(heredoc_match.group(1)),
                tab_stripping="<<-" in raw_line,
            )

        if current_function is not None:
            brace_depth += raw_line.count("{") - raw_line.count("}")
            if brace_depth <= 0:
                current_function = None
                brace_depth = 0

    return tuple(observations)


def option_observations(
    relative_path: str,
    line_number: int,
    raw_line: str,
) -> tuple[RawObservation, ...]:
    words = split_words(raw_line)
    if not words:
        return ()
    if words[0] == "set":
        return tuple(
            shell_option_observation(relative_path, line_number, raw_line, option)
            for option in set_options(words[1:])
        )
    if words[0] == "shopt":
        return tuple(
            shopt_observation(relative_path, line_number, raw_line, operation, option)
            for operation, option in shopt_options(words[1:])
        )
    return ()


def set_options(words: list[str]) -> tuple[str, ...]:
    options: list[str] = []
    index = 0
    while index < len(words):
        word = words[index]
        if word.startswith("-") and not word.startswith("--"):
            for flag in word[1:]:
                if flag == "e":
                    options.append("errexit")
                elif flag == "u":
                    options.append("nounset")
                elif flag == "o" and index + 1 < len(words):
                    options.append(words[index + 1])
                    index += 1
        elif word == "pipefail":
            options.append("pipefail")
        index += 1
    return tuple(dict.fromkeys(options))


def shopt_options(words: list[str]) -> tuple[tuple[str, str], ...]:
    if not words:
        return ()
    operation = "unknown"
    if words[0] == "-s":
        operation = "enable"
        options = words[1:]
    elif words[0] == "-u":
        operation = "disable"
        options = words[1:]
    else:
        options = words
    return tuple((operation, option) for option in options)


def shell_option_observation(
    relative_path: str,
    line_number: int,
    raw_line: str,
    option: str,
) -> RawObservation:
    return RawObservation(
        kind="bash.shell_option",
        source_id=f"{relative_path}#bash-option:{line_number}:{slug(option)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=option,
        confidence="extracted",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=bash_metadata(
            {
                "option": option,
                "operation": "enable",
                "source_token": raw_line.strip(),
            }
        ),
    )

def shopt_observation(
    relative_path: str,
    line_number: int,
    raw_line: str,
    operation: str,
    option: str,
) -> RawObservation:
    return RawObservation(
        kind="bash.shopt",
        source_id=f"{relative_path}#bash-shopt:{line_number}:{slug(operation + '-' + option)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=option,
        confidence="extracted",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=bash_metadata(
            {
                "option": option,
                "operation": operation,
                "source_token": raw_line.strip(),
            }
        ),
    )


def function_observation(
    relative_path: str,
    line_number: int,
    raw_line: str,
    function_name: str,
    syntax: str,
) -> RawObservation:
    return RawObservation(
        kind="shell.function",
        source_id=f"{relative_path}#bash-function:{line_number}:{slug(function_name)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=function_name,
        confidence="extracted",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=bash_metadata(
            {
                "syntax": syntax,
                "raw": raw_line.strip(),
            }
        ),
    )


def source_observations(
    relative_path: str,
    line_number: int,
    raw_line: str,
) -> tuple[RawObservation, ...]:
    words = split_words(raw_line)
    if len(words) < 2 or words[0] not in {"source", "."}:
        return ()
    syntax = "source" if words[0] == "source" else "dot"
    source_path = words[1]
    target, metadata = source_target(relative_path, source_path)
    metadata.update(
        {
            "syntax": syntax,
            "source": source_path,
            "raw": raw_line.strip(),
        }
    )
    return (
        RawObservation(
            kind="shell.source",
            source_id=f"{relative_path}#bash-source:{line_number}:{slug(source_path)}",
            path=relative_path,
            start_line=line_number,
            end_line=line_number,
            name=source_path,
            target=target,
            confidence="heuristic",
            extractor=EXTRACTOR,
            extractor_version=__version__,
            metadata=bash_metadata(metadata),
        ),
    )


def source_target(relative_path: str, source_path: str) -> tuple[str | None, dict[str, Any]]:
    if (
        not source_path
        or source_path.startswith("/")
        or any(character in source_path for character in DYNAMIC_SOURCE_CHARS)
    ):
        return None, {
            "target_kind": "dynamic",
            "resolution": "dynamic",
            "dynamic_reason": "computed-source",
        }
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(relative_path), source_path))
    if resolved == "." or resolved.startswith("../"):
        return None, {
            "target_kind": "unknown",
            "resolution": "unknown",
            "unknown_reason": "repo-escaping-source",
        }
    return f"file:{resolved}", {
        "target_kind": "static",
        "resolution": "static",
        "resolved_path": resolved,
    }


def assignment_and_export_observations(
    relative_path: str,
    line_number: int,
    raw_line: str,
    *,
    scope: str,
    function_name: str | None,
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
            observations.append(
                export_observation(
                    relative_path,
                    line_number,
                    raw_line,
                    variable,
                    value,
                    scope=scope,
                    function_name=function_name,
                )
            )
            if value is not None:
                observations.extend(
                    assignment_observations_for_value(
                        relative_path,
                        line_number,
                        raw_line,
                        variable,
                        value,
                        declaration="export",
                        scope=scope,
                        function_name=function_name,
                    )
                )
        return tuple(observations)

    declaration = None
    assignment_words = words
    if words[0] in DECLARATION_KEYWORDS:
        declaration = words[0]
        assignment_words = [
            word for word in words[1:] if not word.startswith("-")
        ]
    for word in assignment_words:
        match = ASSIGNMENT_RE.match(word)
        if match is None:
            continue
        variable, value = match.group(1), match.group(2)
        if value.startswith("("):
            continue
        observations.extend(
            assignment_observations_for_value(
                relative_path,
                line_number,
                raw_line,
                variable,
                value,
                declaration=declaration,
                scope=scope,
                function_name=function_name,
            )
        )
    return tuple(observations)


def parse_export_word(word: str) -> tuple[str, str | None] | None:
    return _bash_environment_parse_export_word(word)


def assignment_observations_for_value(
    relative_path: str,
    line_number: int,
    raw_line: str,
    variable: str,
    value: str,
    *,
    declaration: str | None,
    scope: str,
    function_name: str | None,
) -> tuple[RawObservation, ...]:
    redacted, reason = redaction_for_name(variable)
    metadata: dict[str, Any] = {
        "variable": variable,
        "declaration": declaration,
        "scope": scope,
        "value_kind": value_kind(value),
        "value_present": True,
        "redacted": redacted,
        "raw_value_stored": not redacted,
        "raw": safe_raw_line(raw_line, variable, redacted),
    }
    if function_name is not None:
        metadata["function"] = function_name
    if redacted:
        metadata["redaction_reason"] = reason
    else:
        metadata["value"] = value
    assignment = RawObservation(
        kind="shell.assignment",
        source_id=f"{relative_path}#bash-assignment:{line_number}:{slug(variable)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=variable,
        confidence="extracted",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=bash_metadata(metadata),
    )
    if not redacted:
        return (assignment,)
    return (
        assignment,
        secret_like_observation(
            relative_path,
            line_number,
            variable,
            "assignment",
            reason,
        ),
    )


def export_observation(
    relative_path: str,
    line_number: int,
    raw_line: str,
    variable: str,
    value: str | None,
    *,
    scope: str,
    function_name: str | None,
) -> RawObservation:
    redacted, reason = redaction_for_name(variable)
    metadata: dict[str, Any] = {
        "variable": variable,
        "scope": scope,
        "value_kind": "omitted" if value is None else value_kind(value),
        "value_present": value is not None,
        "redacted": redacted if value is not None else False,
        "raw_value_stored": value is not None and not redacted,
        "raw": safe_raw_line(raw_line, variable, value is not None and redacted),
    }
    if function_name is not None:
        metadata["function"] = function_name
    if value is not None and redacted:
        metadata["redaction_reason"] = reason
    elif value is not None:
        metadata["value"] = value
    return RawObservation(
        kind="shell.export",
        source_id=f"{relative_path}#bash-export:{line_number}:{slug(variable)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=variable,
        confidence="extracted",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=bash_metadata(metadata),
    )


def command_substitution_observations(
    relative_path: str,
    line_number: int,
    raw_line: str,
) -> tuple[RawObservation, ...]:
    observations = []
    if COMMAND_SUB_RE.search(raw_line):
        observations.append(
            dynamic_marker(
                "shell.command_substitution",
                relative_path,
                line_number,
                "command-substitution",
                "command_substitution",
            )
        )
    if BACKTICK_SUB_RE.search(raw_line):
        observations.append(
            dynamic_marker(
                "shell.command_substitution",
                relative_path,
                line_number,
                "backtick-command-substitution",
                "command_substitution",
            )
        )
    return tuple(observations)


def dynamic_invocation_observations(
    relative_path: str,
    line_number: int,
    raw_line: str,
) -> tuple[RawObservation, ...]:
    stripped = raw_line.strip()
    markers: list[tuple[str, str]] = []
    if re.match(r"^eval(?:\s|$)", stripped):
        markers.append(("eval", "eval"))
    if re.match(r"^command\s+eval(?:\s|$)", stripped):
        markers.append(("command_eval", "eval"))
    if re.match(r"^\$[A-Za-z_][A-Za-z0-9_]*(?:\s|$)", stripped):
        markers.append(("variable_command", "variable-command"))
    if re.match(r'^"?\$[A-Za-z_][A-Za-z0-9_]*"?(?:\s|$)', stripped):
        markers.append(("variable_command", "variable-command"))
    if re.match(r'^"?\$\{[A-Za-z_][A-Za-z0-9_]*\[@\]\}"?(?:\s|$)', stripped):
        markers.append(("array_command", "array-command"))
    if re.match(r"^bash\s+-c(?:\s|$)", stripped):
        markers.append(("bash_c", "bash-c"))
    if re.match(r"^sh\s+-c(?:\s|$)", stripped):
        markers.append(("sh_c", "sh-c"))
    if re.search(r"\$\{![^}]+\}", stripped):
        markers.append(("indirect_expansion", "indirect-expansion"))
    if re.search(r"\$\{[^}]+/[^\}]+\}", stripped):
        markers.append(("parameter_expansion", "parameter-expansion"))
    markers = list(dict.fromkeys(markers))
    return tuple(
        dynamic_marker(
            "shell.dynamic_invocation",
            relative_path,
            line_number,
            reason,
            invocation_kind,
        )
        for invocation_kind, reason in markers
    )


def dynamic_marker(
    kind: str,
    relative_path: str,
    line_number: int,
    dynamic_reason: str,
    invocation_kind: str,
) -> RawObservation:
    return RawObservation(
        kind=kind,
        source_id=f"{relative_path}#{kind}:{line_number}:{slug(dynamic_reason)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=dynamic_reason,
        confidence="unknown",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=bash_metadata(
            {
                "resolution": "dynamic",
                "dynamic_reason": dynamic_reason,
                "invocation_kind": invocation_kind,
                "target_kind": "dynamic",
                "target_display": "[dynamic]",
                "inner_modeled": False,
            }
        ),
    )
