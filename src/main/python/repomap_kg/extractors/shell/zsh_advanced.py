"""Zsh advanced syntax observation helpers."""

from __future__ import annotations

import re
from typing import Any

from repomap_kg import __version__
from repomap_kg.extractors.shell.zsh_common import (
    EXTRACTOR,
    PLUGIN_MANAGER_NAMES,
    PROMPT_VARIABLES,
    has_command_substitution,
    is_dynamic_value,
    is_quoted_at,
    mask_quoted_text,
    redaction_for_name,
    redaction_for_value,
    safe_short_value,
    secret_like_observation,
    split_words,
    syntax_metadata,
    target_display,
    token_target_kind,
    zsh_metadata,
)
from repomap_kg.observations.raw import RawObservation
from repomap_kg.extractors.shell.base import slug


PARAMETER_EXPANSION_RE = re.compile(r"\$\{\(([^)]{1,40})\)([^}]*)\}")
ARRAY_ASSIGNMENT_RE = re.compile(
    r"^\s*(?:(local|typeset|readonly)\s+((?:-[A-Za-z]+\s+)*)?)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*\((.*)\)\s*$"
)
ASSOCIATIVE_DECLARATION_RE = re.compile(
    r"^\s*(local|typeset|readonly)\s+((?:-[A-Za-z]+\s+)*)?([A-Za-z_][A-Za-z0-9_]*)\s*$"
)


def array_assignment_observations(
    relative_path: str,
    line_number: int,
    line: str,
) -> tuple[RawObservation, ...]:
    parsed = parse_array_assignment(line)
    if parsed is None:
        return ()
    declaration, flags, variable, body = parsed
    if "-A" in flags:
        return ()
    elements = split_words(body)
    static_count = 0
    dynamic_count = 0
    redacted_count = 0
    for element in elements:
        redacted, _reason = redaction_for_value(element)
        if redacted:
            redacted_count += 1
        elif is_dynamic_value(element):
            dynamic_count += 1
        else:
            static_count += 1
    operation = "assign"
    if elements and elements[-1] in {f"${variable}", f"${{{variable}}}"}:
        operation = "prepend"
    elif elements and elements[0] in {f"${variable}", f"${{{variable}}}"}:
        operation = "append"
    metadata = syntax_metadata(
        {
            "variable": variable,
            "declaration_keyword": declaration,
            "flags": flags,
            "operation": operation,
            "element_count": len(elements),
            "static_element_count": static_count,
            "dynamic_element_count": dynamic_count,
            "redacted_element_count": redacted_count,
            "value_kind": "array",
            "raw_value_stored": False,
            "array_expanded": False,
            "runtime_state_known": False,
        }
    )
    observations: list[RawObservation] = [
        RawObservation(
            kind="zsh.array_assignment",
            source_id=f"{relative_path}#zsh-array:{line_number}:{slug(variable)}",
            path=relative_path,
            start_line=line_number,
            end_line=line_number,
            name=variable,
            confidence="extracted",
            extractor=EXTRACTOR,
            extractor_version=__version__,
            metadata=zsh_metadata(metadata),
        )
    ]
    if redacted_count or redaction_for_name(variable)[0]:
        observations.append(
            secret_like_observation(
                relative_path,
                line_number,
                variable,
                "array_element",
                "secret-like-value" if redacted_count else "secret-like-name",
            )
        )
    return tuple(observations)


def associative_array_observations(
    relative_path: str,
    line_number: int,
    line: str,
) -> tuple[RawObservation, ...]:
    parsed = parse_array_assignment(line)
    if parsed is None:
        declaration, flags, variable = parse_associative_declaration(line)
        if variable is None:
            return ()
        body = ""
    else:
        declaration, flags, variable, body = parsed
    if "-A" not in flags:
        return ()
    pairs = parse_associative_pairs(body)
    static_key_count = dynamic_key_count = redacted_key_count = 0
    static_value_count = dynamic_value_count = redacted_value_count = 0
    for key, value in pairs:
        key_redacted, _reason = redaction_for_value(key)
        value_redacted, _reason = redaction_for_value(value)
        if key_redacted:
            redacted_key_count += 1
        elif is_dynamic_value(key):
            dynamic_key_count += 1
        else:
            static_key_count += 1
        if value_redacted:
            redacted_value_count += 1
        elif is_dynamic_value(value):
            dynamic_value_count += 1
        else:
            static_value_count += 1
    metadata = syntax_metadata(
        {
            "variable": variable,
            "declaration_keyword": declaration,
            "flags": flags,
            "pair_count": len(pairs),
            "static_key_count": static_key_count,
            "dynamic_key_count": dynamic_key_count,
            "redacted_key_count": redacted_key_count,
            "static_value_count": static_value_count,
            "dynamic_value_count": dynamic_value_count,
            "redacted_value_count": redacted_value_count,
            "raw_value_stored": False,
            "array_expanded": False,
            "runtime_state_known": False,
        }
    )
    observations: list[RawObservation] = [
        RawObservation(
            kind="zsh.associative_array_assignment",
            source_id=f"{relative_path}#zsh-associative-array:{line_number}:{slug(variable)}",
            path=relative_path,
            start_line=line_number,
            end_line=line_number,
            name=variable,
            confidence="extracted",
            extractor=EXTRACTOR,
            extractor_version=__version__,
            metadata=zsh_metadata(metadata),
        )
    ]
    if redacted_key_count or redacted_value_count or redaction_for_name(variable)[0]:
        observations.append(
            secret_like_observation(
                relative_path,
                line_number,
                variable,
                "associative_array",
                "secret-like-value",
            )
        )
    return tuple(observations)


def parameter_expansion_observations(
    relative_path: str,
    line_number: int,
    line: str,
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    for index, match in enumerate(PARAMETER_EXPANSION_RE.finditer(line), start=1):
        if is_quoted_at(line, match.start()):
            continue
        flags = match.group(1)
        expression = match.group(2)
        summary = parameter_flag_summary(flags)
        parameter_name = visible_parameter_name(expression)
        redacted = False
        reason = ""
        if parameter_name is not None:
            redacted, reason = redaction_for_name(parameter_name)
        context = parameter_expansion_context(line)
        metadata: dict[str, Any] = syntax_metadata(
            {
                "parameter_name": None if redacted else parameter_name,
                "expansion_flags": summary,
                "flag_summary": summary,
                "context": context,
                "value_expanded": False,
                "command_executed": False,
                "raw_value_stored": False,
            }
        )
        if has_command_substitution(expression):
            metadata["dynamic_reason"] = "command_substitution"
        elif parameter_name is None:
            metadata["dynamic_reason"] = "computed_parameter"
        if redacted:
            metadata["redacted"] = True
            metadata["redaction_reason"] = reason
        observations.append(
            RawObservation(
                kind="zsh.parameter_expansion",
                source_id=f"{relative_path}#zsh-parameter-expansion:{line_number}:{index}:{slug(summary)}",
                path=relative_path,
                start_line=line_number,
                end_line=line_number,
                name=summary,
                confidence="heuristic",
                extractor=EXTRACTOR,
                extractor_version=__version__,
                metadata=zsh_metadata(metadata),
            )
        )
        if redacted:
            observations.append(
                secret_like_observation(
                    relative_path,
                    line_number,
                    parameter_name or "parameter",
                    "parameter_expansion",
                    reason,
                )
            )
    return tuple(observations)


def glob_and_path_observations(
    relative_path: str,
    line_number: int,
    line: str,
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    for token in glob_candidate_tokens(line):
        clean = clean_glob_token(token)
        if not clean or is_dynamic_value(clean):
            continue
        qualifier = glob_qualifier(clean)
        if qualifier is not None:
            observations.append(
                glob_qualifier_observation(relative_path, line_number, clean, qualifier)
            )
            observations.append(
                path_reference_observation(relative_path, line_number, clean, "qualified_glob")
            )
        feature = extended_glob_feature(clean, qualifier)
        if feature is not None:
            observations.append(
                extended_glob_observation(relative_path, line_number, clean, feature)
            )
            if qualifier is None:
                observations.append(
                    path_reference_observation(relative_path, line_number, clean, "glob")
                )
    return tuple(observations)


def zsh_specific_dynamic_observations(
    relative_path: str,
    line_number: int,
    line: str,
) -> tuple[RawObservation, ...]:
    stripped = line.strip()
    words = split_words(stripped)
    markers: list[str] = []
    if words and words[0] == "eval" and any(manager in stripped for manager in PLUGIN_MANAGER_NAMES):
        markers.append("plugin_manager_eval")
    if words and words[0] in {"zinit", "zplug", "antidote"}:
        if len(words) > 1 and words[1] in {"ice", "load"}:
            markers.append("plugin_loader")
    if re.match(r"^\s*(fpath|FPATH)\s*=\s*\(", stripped) and "$COMPUTED" in stripped:
        markers.append("computed_fpath")
    if has_unquoted_parameter_expansion(stripped):
        markers.append("parameter_expansion")
    if any(is_dynamic_glob_token(token) for token in glob_candidate_tokens(stripped)):
        markers.append("dynamic_glob")
    prompt_assignment = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)=", stripped)
    if (
        prompt_assignment is not None
        and prompt_assignment.group(1) in PROMPT_VARIABLES
        and is_dynamic_value(stripped)
    ):
        markers.append("dynamic_prompt")
    return tuple(
        zsh_dynamic_marker(relative_path, line_number, marker)
        for marker in dict.fromkeys(markers)
    )


def parse_array_assignment(line: str) -> tuple[str | None, list[str], str, str] | None:
    match = ARRAY_ASSIGNMENT_RE.match(line)
    if match is None:
        return None
    declaration = match.group(1)
    flags = split_words((match.group(2) or "").strip())
    variable = match.group(3)
    body = match.group(4)
    return declaration, flags, variable, body


def parse_associative_declaration(line: str) -> tuple[str | None, list[str], str | None]:
    match = ASSOCIATIVE_DECLARATION_RE.match(line)
    if match is None:
        return None, [], None
    declaration = match.group(1)
    flags = split_words((match.group(2) or "").strip())
    variable = match.group(3)
    if "-A" not in flags:
        return None, [], None
    return declaration, flags, variable


def parse_associative_pairs(body: str) -> list[tuple[str, str]]:
    if not body:
        return []
    words = split_words(body)
    pairs: list[tuple[str, str]] = []
    bracket_pairs = True
    for word in words:
        if not re.match(r"^\[[^]]+\]=", word):
            bracket_pairs = False
            break
    if bracket_pairs:
        for word in words:
            key, value = word.split("=", 1)
            pairs.append((key.removeprefix("[").removesuffix("]"), value))
        return pairs
    index = 0
    while index + 1 < len(words):
        pairs.append((words[index], words[index + 1]))
        index += 2
    return pairs


def parameter_flag_summary(flags: str) -> str:
    if flags.startswith("@f"):
        return "@f"
    if flags.startswith("j:"):
        return "j"
    for known in ("q", "U", "L", "u"):
        if flags == known:
            return known
    return "unknown"


def has_unquoted_parameter_expansion(line: str) -> bool:
    return any(
        not is_quoted_at(line, match.start())
        for match in PARAMETER_EXPANSION_RE.finditer(line)
    )


def visible_parameter_name(expression: str) -> str | None:
    cleaned = expression.strip().strip('"').strip("'")
    match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)$", cleaned)
    if match is None:
        return None
    return match.group(1)


def parameter_expansion_context(line: str) -> str:
    stripped = line.strip()
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", stripped):
        variable = stripped.split("=", 1)[0]
        if variable in PROMPT_VARIABLES:
            return "prompt"
        return "assignment"
    if stripped.startswith("zstyle "):
        return "zstyle"
    if split_words(stripped):
        return "command_argument"
    return "unknown"


def glob_candidate_tokens(line: str) -> list[str]:
    masked = mask_quoted_text(line)
    if "<<" in masked:
        masked = masked.split("<<", 1)[0]
    return split_words(masked.replace(";", " "))


def clean_glob_token(token: str) -> str:
    return token.strip().strip(";")


def glob_qualifier(token: str) -> str | None:
    if "$(" in token or not any(character in token for character in "*?"):
        return None
    match = re.search(r"\(([^()\s]+)\)$", token)
    if match is None:
        return None
    qualifier = match.group(1)
    if qualifier in {".", "/", "@", "N"} or qualifier.startswith(".om"):
        return qualifier
    return None


def extended_glob_feature(token: str, qualifier: str | None) -> str | None:
    if "$(" in token:
        return None
    if qualifier is not None:
        return "qualifier"
    if token.startswith("^") and any(character in token for character in "*?"):
        return "negation"
    if re.search(r"\([^)]*\|[^)]*\)", token):
        return "alternation"
    if "**" in token:
        return "recursive_glob"
    return None


def is_dynamic_glob_token(token: str) -> bool:
    return any(character in token for character in "*?") and is_dynamic_value(token)


def glob_qualifier_observation(
    relative_path: str,
    line_number: int,
    pattern: str,
    qualifier: str,
) -> RawObservation:
    pattern_display = safe_short_value(pattern) or "[unknown]"
    return RawObservation(
        kind="zsh.glob_qualifier",
        source_id=f"{relative_path}#zsh-glob-qualifier:{line_number}:{slug(pattern_display)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=qualifier,
        confidence="heuristic",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=zsh_metadata(
            syntax_metadata(
                {
                    "pattern_kind": "static",
                    "qualifier_summary": qualifier,
                    "glob_pattern_kind": glob_pattern_kind(pattern, qualifier),
                    "filesystem_checked": False,
                    "glob_expanded": False,
                    "target_count_known": False,
                    "raw_value_stored": False,
                }
            )
        ),
    )


def extended_glob_observation(
    relative_path: str,
    line_number: int,
    pattern: str,
    feature: str,
) -> RawObservation:
    pattern_display = safe_short_value(pattern) or "[unknown]"
    return RawObservation(
        kind="zsh.extended_glob",
        source_id=f"{relative_path}#zsh-extended-glob:{line_number}:{slug(feature + '-' + pattern_display)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=feature,
        confidence="heuristic",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=zsh_metadata(
            syntax_metadata(
                {
                    "pattern_summary": safe_short_value(pattern),
                    "feature": feature,
                    "glob_expanded": False,
                    "filesystem_checked": False,
                    "target_count_known": False,
                    "raw_value_stored": False,
                }
            )
        ),
    )


def path_reference_observation(
    relative_path: str,
    line_number: int,
    path_token: str,
    path_kind: str,
) -> RawObservation:
    target_kind = token_target_kind(path_token)
    display = target_display(path_token, target_kind)
    return RawObservation(
        kind="zsh.path_reference",
        source_id=f"{relative_path}#zsh-path-reference:{line_number}:{slug(path_kind + '-' + display)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=display,
        confidence="heuristic" if target_kind == "static" else "unknown",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=zsh_metadata(
            syntax_metadata(
                {
                    "path_kind": path_kind,
                    "target_kind": target_kind,
                    "path_display": display,
                    "filesystem_checked": False,
                    "file_opened": False,
                    "target_count_known": False,
                    "raw_value_stored": target_kind == "static" and len(path_token) <= 120,
                }
            )
        ),
    )


def glob_pattern_kind(pattern: str, qualifier: str) -> str:
    if "**" in pattern:
        return "recursive"
    if qualifier:
        return "qualified"
    if "." in pattern:
        return "suffix"
    return "unknown"


def zsh_dynamic_marker(
    relative_path: str,
    line_number: int,
    dynamic_reason: str,
) -> RawObservation:
    return RawObservation(
        kind="zsh.dynamic_invocation",
        source_id=f"{relative_path}#zsh-specific-dynamic:{line_number}:{slug(dynamic_reason)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=dynamic_reason,
        confidence="unknown",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=zsh_metadata(
            syntax_metadata(
                {
                    "dynamic_reason": dynamic_reason,
                    "target_kind": "dynamic",
                    "plugin_loaded": False,
                    "plugin_installed": False,
                    "network_called": False,
                    "command_executed": False,
                }
            )
        ),
    )
