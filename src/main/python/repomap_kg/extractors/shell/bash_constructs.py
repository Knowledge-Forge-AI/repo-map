"""Bash advanced construct observation helpers."""

from __future__ import annotations

import re

from repomap_kg import __version__
from repomap_kg.extractors.shared.observations import (
    secret_like_observation as build_secret_like_observation,
)
from repomap_kg.extractors.shell.bash_command_lines import STRUCTURAL_COMMANDS
from repomap_kg.extractors.shell.bash_commands import (
    BUILTIN_COMMANDS,
    EXTERNAL_COMMANDS,
    normalize_command_token,
)
from repomap_kg.extractors.shell.bash_common import (
    ARRAY_ASSIGNMENT_RE,
    EXTRACTOR,
    bash_metadata,
    is_dynamic_value,
    redaction_for_name,
    redaction_for_value,
    split_words,
)
from repomap_kg.observations.raw import RawObservation
from repomap_kg.extractors.shell.base import slug


TEST_OPERATORS = frozenset({"-f", "-d", "-n", "-z", "=", "!="})


def secret_like_observation(
    relative_path: str,
    line_number: int,
    name: str,
    secret_source: str,
    reason: str,
) -> RawObservation:
    return build_secret_like_observation(
        relative_path=relative_path,
        line_number=line_number,
        name=name,
        secret_source=secret_source,
        reason=reason,
        source_prefix="bash",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata_builder=bash_metadata,
        slugger=slug,
    )


def alias_observations(
    relative_path: str,
    line_number: int,
    raw_line: str,
) -> tuple[RawObservation, ...]:
    stripped = raw_line.strip()
    if not stripped.startswith("alias "):
        return ()
    words = split_words(stripped)
    if not words or words[0] != "alias":
        return ()
    observations: list[RawObservation] = []
    for index, spec in enumerate(words[1:]):
        alias_name, target = parse_alias_spec(spec)
        if alias_name is None:
            alias_name = "[dynamic]"
            target = None
        dynamic = is_dynamic_value(spec) or alias_name == "[dynamic]"
        target_redacted, redaction_reason = alias_redaction(alias_name, target)
        metadata = {
            "alias_name": alias_name if not dynamic else "[dynamic]",
            "target_summary": alias_target_summary(target, dynamic, target_redacted),
            "target_kind": "dynamic" if dynamic else "static",
            "target_redacted": target_redacted,
            "target_value_stored": bool(target and not dynamic and not target_redacted),
            "raw_value_stored": bool(target and not dynamic and not target_redacted),
            "command_like_target": bool(target and alias_target_command_like(target)),
            "expansion_modeled": False,
            "definition_scope": "file",
            "resolution": "dynamic" if dynamic else "static",
        }
        if redaction_reason:
            metadata["redaction_reason"] = redaction_reason
        source_alias = alias_name if not dynamic else "dynamic-alias"
        observations.append(
            RawObservation(
                kind="bash.alias",
                source_id=(
                    f"{relative_path}#bash-alias:{line_number}:"
                    f"{index}:{slug(source_alias)}"
                ),
                path=relative_path,
                start_line=line_number,
                end_line=line_number,
                name=alias_name if not dynamic else "[dynamic]",
                confidence="unknown" if dynamic else "heuristic",
                extractor=EXTRACTOR,
                extractor_version=__version__,
                metadata=bash_metadata(metadata),
            )
        )
        if target_redacted:
            observations.append(
                secret_like_observation(
                    relative_path,
                    line_number,
                    alias_name,
                    "alias-target",
                    redaction_reason or "secret-like-value",
                )
            )
    return tuple(observations)


def parse_alias_spec(spec: str) -> tuple[str | None, str | None]:
    if "=" not in spec:
        return spec if not spec.startswith("$") else None, None
    name, target = spec.split("=", 1)
    if not name or name.startswith("$") or "$" in name:
        return None, None
    return name, target


def alias_target_summary(
    target: str | None,
    dynamic: bool,
    redacted: bool,
) -> str | None:
    if dynamic:
        return "[dynamic]"
    if target is None:
        return None
    if redacted:
        return "[redacted]"
    words = split_words(target)
    if not words:
        return target[:80]
    return " ".join(words[:3])


def alias_target_command_like(target: str) -> bool:
    words = split_words(target)
    if not words:
        return False
    command = normalize_command_token(words[0])
    return (
        command in BUILTIN_COMMANDS
        or command in EXTERNAL_COMMANDS
        or command in STRUCTURAL_COMMANDS
    )


def alias_redaction(alias_name: str, target: str | None) -> tuple[bool, str]:
    name_redacted, reason = redaction_for_name(alias_name)
    if name_redacted:
        return True, reason
    return redaction_for_value(target or "")


def array_assignment_observations(
    relative_path: str,
    line_number: int,
    raw_line: str,
) -> tuple[RawObservation, ...]:
    stripped = raw_line.strip()
    match = ARRAY_ASSIGNMENT_RE.match(stripped)
    if match is None:
        return ()
    variable = match.group("name")
    body = match.group("body")
    declaration = match.group("declaration")
    flags = (match.group("flags") or "").split()
    operation = "append" if match.group("operation") == "+=" else "assign"
    associative = "-A" in flags
    if associative:
        observation = associative_array_assignment_observation(
            relative_path,
            line_number,
            variable,
            body,
            declaration,
            operation,
        )
    else:
        observation = array_assignment_observation(
            relative_path,
            line_number,
            variable,
            body,
            declaration,
            operation,
        )
    observations = [observation]
    if observation.metadata.get("redacted_item_count", 0) > 0:
        observations.append(
            secret_like_observation(
                relative_path,
                line_number,
                variable,
                "array-assignment",
                "secret-like-name-or-key",
            )
        )
    return tuple(observations)


def array_assignment_observation(
    relative_path: str,
    line_number: int,
    variable: str,
    body: str,
    declaration: str | None,
    operation: str,
) -> RawObservation:
    values = split_array_values(body)
    redacted_variable, variable_reason = redaction_for_name(variable)
    safe_values: list[str] = []
    static_count = 0
    dynamic_count = 0
    redacted_count = 0
    for value in values:
        redacted_value, _ = redaction_for_value(value)
        if redacted_variable or redacted_value:
            redacted_count += 1
            continue
        if is_dynamic_value(value):
            dynamic_count += 1
            continue
        static_count += 1
        if len(safe_values) < 5:
            safe_values.append(value)
    metadata = {
        "variable": variable,
        "declaration": declaration,
        "operation": operation,
        "item_count": len(values),
        "static_item_count": static_count,
        "dynamic_item_count": dynamic_count,
        "redacted_item_count": redacted_count,
        "values_summary": safe_values,
        "expansion_modeled": False,
        "redacted": redacted_variable or redacted_count > 0,
        "raw_value_stored": not redacted_variable and redacted_count == 0,
    }
    if redacted_variable:
        metadata["redaction_reason"] = variable_reason
    return RawObservation(
        kind="bash.array_assignment",
        source_id=f"{relative_path}#bash-array:{line_number}:{slug(variable)}:{operation}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=variable,
        confidence="heuristic",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=bash_metadata(metadata),
    )


def associative_array_assignment_observation(
    relative_path: str,
    line_number: int,
    variable: str,
    body: str,
    declaration: str | None,
    operation: str,
) -> RawObservation:
    entries = parse_associative_entries(body)
    redacted_variable, variable_reason = redaction_for_name(variable)
    known_keys: list[str] = []
    redacted_keys: list[str] = []
    dynamic_value_count = 0
    redacted_count = 0
    for key, value in entries:
        key_redacted, _ = redaction_for_name(key)
        value_redacted, _ = redaction_for_value(value)
        if redacted_variable or key_redacted or value_redacted:
            redacted_keys.append(key)
            redacted_count += 1
            continue
        known_keys.append(key)
        if is_dynamic_value(value):
            dynamic_value_count += 1
    metadata = {
        "variable": variable,
        "declaration": declaration,
        "operation": operation,
        "key_count": len(entries),
        "known_keys": known_keys,
        "redacted_keys": redacted_keys,
        "dynamic_value_count": dynamic_value_count,
        "redacted_item_count": redacted_count,
        "expansion_modeled": False,
        "redacted": redacted_variable or redacted_count > 0,
        "raw_value_stored": not redacted_variable and redacted_count == 0,
    }
    if redacted_variable:
        metadata["redaction_reason"] = variable_reason
    return RawObservation(
        kind="bash.associative_array_assignment",
        source_id=f"{relative_path}#bash-assoc-array:{line_number}:{slug(variable)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=variable,
        confidence="heuristic",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=bash_metadata(metadata),
    )


def split_array_values(body: str) -> list[str]:
    return split_words(body)


def parse_associative_entries(body: str) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    for word in split_words(body):
        match = re.match(r"^\[([^\]]+)\]=(.*)$", word)
        if match is not None:
            entries.append((match.group(1), match.group(2)))
    return entries


def trap_observations(
    relative_path: str,
    line_number: int,
    raw_line: str,
) -> tuple[RawObservation, ...]:
    words = split_words(raw_line.strip())
    if not words or words[0] != "trap":
        return ()
    handler = words[1] if len(words) > 1 else None
    events = words[2:] if len(words) > 2 else []
    handler_kind = "unknown"
    if handler == "-":
        handler_kind = "reset"
        handler = None
    elif handler is not None:
        handler_kind = "dynamic" if is_dynamic_value(handler) else "static"
    handler_redacted, redaction_reason = redaction_for_value(handler or "")
    metadata = {
        "events": events,
        "handler_kind": handler_kind,
        "handler_summary": trap_handler_summary(handler, handler_kind, handler_redacted),
        "handler_redacted": handler_redacted,
        "handler_value_stored": bool(
            handler and handler_kind == "static" and not handler_redacted
        ),
        "executes_at_parse_time": False,
    }
    if redaction_reason:
        metadata["redaction_reason"] = redaction_reason
    observations: list[RawObservation] = [
        RawObservation(
            kind="bash.trap",
            source_id=(
                f"{relative_path}#bash-trap:{line_number}:"
                f"{slug('-'.join(events) or 'unknown')}"
            ),
            path=relative_path,
            start_line=line_number,
            end_line=line_number,
            name=events[0] if events else "unknown",
            confidence="heuristic" if handler_kind != "unknown" else "unknown",
            extractor=EXTRACTOR,
            extractor_version=__version__,
            metadata=bash_metadata(metadata),
        )
    ]
    if handler_redacted:
        observations.append(
            secret_like_observation(
                relative_path,
                line_number,
                "trap",
                "trap-handler",
                redaction_reason or "secret-like-value",
            )
        )
    return tuple(observations)


def trap_handler_summary(
    handler: str | None,
    handler_kind: str,
    redacted: bool,
) -> str | None:
    if handler_kind == "reset":
        return None
    if handler_kind == "dynamic":
        return "[dynamic]"
    if handler is None:
        return None
    if redacted:
        return "[redacted]"
    words = split_words(handler)
    if not words:
        return handler[:80]
    return " ".join(words[:3])


def arithmetic_observations(
    relative_path: str,
    line_number: int,
    raw_line: str,
) -> tuple[RawObservation, ...]:
    stripped = raw_line.strip()
    specs: list[tuple[str, str]] = []
    for expression in re.findall(r"\$\(\((.*?)\)\)", stripped):
        specs.append(("expansion", expression.strip()))
    command_match = re.match(r"^\(\((.*?)\)\)\s*$", stripped)
    if command_match is not None:
        specs.append(("command", command_match.group(1).strip()))
    let_match = re.match(r"^let\s+(.+)$", stripped)
    if let_match is not None:
        specs.append(("let", let_match.group(1).strip()))
    observations = [
        arithmetic_observation(relative_path, line_number, form, expression)
        for form, expression in specs
    ]
    return tuple(observations)


def arithmetic_observation(
    relative_path: str,
    line_number: int,
    form: str,
    expression: str,
) -> RawObservation:
    expression_redacted, redaction_reason = redaction_for_value(expression)
    metadata = {
        "form": form,
        "variables": arithmetic_variables(expression),
        "expression_summary": "[redacted]" if expression_redacted else expression[:80],
        "expression_redacted": expression_redacted,
        "expression_modeled": False,
    }
    if redaction_reason:
        metadata["redaction_reason"] = redaction_reason
    return RawObservation(
        kind="bash.arithmetic",
        source_id=f"{relative_path}#bash-arithmetic:{line_number}:{form}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=form,
        confidence="heuristic",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=bash_metadata(metadata),
    )


def arithmetic_variables(expression: str) -> list[str]:
    variables: list[str] = []
    for match in re.finditer(r"\b[A-Za-z_][A-Za-z0-9_]*\b", expression):
        token = match.group(0)
        if token not in variables:
            variables.append(token)
    return variables


def test_expression_observations(
    relative_path: str,
    line_number: int,
    raw_line: str,
) -> tuple[RawObservation, ...]:
    stripped = raw_line.strip()
    spec = test_expression_spec(stripped)
    if spec is None:
        return ()
    form, expression = spec
    words = split_words(expression)
    operator = next((word for word in words if word in TEST_OPERATORS), None)
    operands = [
        word
        for word in words
        if word not in TEST_OPERATORS and word not in {"[", "]", "[[", "]]", "test"}
    ]
    dynamic_operands = [word for word in operands if is_dynamic_value(word)]
    metadata = {
        "form": form,
        "operator": operator,
        "operand_count": len(operands),
        "static_operand_count": len(operands) - len(dynamic_operands),
        "dynamic_operand_count": len(dynamic_operands),
        "expression_modeled": False,
    }
    return (
        RawObservation(
            kind="bash.test_expression",
            source_id=f"{relative_path}#bash-test:{line_number}:{form}",
            path=relative_path,
            start_line=line_number,
            end_line=line_number,
            name=form,
            confidence="heuristic",
            extractor=EXTRACTOR,
            extractor_version=__version__,
            metadata=bash_metadata(metadata),
        ),
    )


def test_expression_spec(stripped: str) -> tuple[str, str] | None:
    bracket_match = re.search(r"\[\s+(.+?)\s+\](?:\s*;?\s*then)?$", stripped)
    if bracket_match is not None and stripped.startswith(("if [", "[")):
        return "bracket", bracket_match.group(1)
    double_match = re.search(r"\[\[\s+(.+?)\s+\]\](?:\s*;?\s*then)?$", stripped)
    if double_match is not None and stripped.startswith(("if [[", "[[")):
        return "double_bracket", double_match.group(1)
    if stripped.startswith("test "):
        return "test_builtin", stripped.removeprefix("test ").strip()
    return None


def case_pattern_observation(
    relative_path: str,
    line_number: int,
    stripped: str,
    branch_index: int,
    case_expression_kind: str,
) -> RawObservation:
    pattern = stripped[:-1].strip()
    redacted, redaction_reason = redaction_for_value(pattern)
    metadata = {
        "pattern": "[redacted]" if redacted else pattern,
        "pattern_redacted": redacted,
        "branch_index": branch_index,
        "case_expression_kind": case_expression_kind,
        "executes_at_parse_time": False,
    }
    if redaction_reason:
        metadata["redaction_reason"] = redaction_reason
    return RawObservation(
        kind="bash.case_pattern",
        source_id=f"{relative_path}#bash-case-pattern:{line_number}:{branch_index}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name="[redacted]" if redacted else pattern,
        confidence="heuristic",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=bash_metadata(metadata),
    )


def first_command_source_id(
    observations: tuple[RawObservation, ...],
) -> str | None:
    for observation in observations:
        if observation.kind == "shell.command":
            return observation.source_id
    return None
