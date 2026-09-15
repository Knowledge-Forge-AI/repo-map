"""PowerShell script and module structure observation helpers."""

from __future__ import annotations

import re
from typing import Any

from repomap_kg import __version__
from repomap_kg.extractors.shell.powershell_common import (
    EXTRACTOR_NAME,
    _is_dynamic_token,
    _is_secret_like_name,
    _redacted_token_summary,
    _resolve_static_path,
    _secret_like_observation,
    _strip_quotes,
    slug,
)
from repomap_kg.extractors.shell.powershell_tokens import _command_tokens
from repomap_kg.observations.raw import RawObservation


FUNCTION_PATTERN = re.compile(
    r"^\s*function\s+(?:(?P<scope>global|local|private|script):)?"
    r"(?P<name>[A-Za-z_][0-9A-Za-z_-]*)\b",
    re.IGNORECASE,
)
REQUIRES_PATTERN = re.compile(
    r"^\s*#requires\s+-(?P<name>[A-Za-z][0-9A-Za-z_-]*)"
    r"(?:\s+(?P<value>.+?))?\s*$",
    re.IGNORECASE,
)
USING_MODULE_PATTERN = re.compile(
    r"^\s*using\s+module\s+(?P<target>.+?)\s*$",
    re.IGNORECASE,
)
IMPORT_MODULE_PATTERN = re.compile(
    r"^\s*Import-Module\b(?P<args>.+?)\s*$",
    re.IGNORECASE,
)
DOT_SOURCE_PATTERN = re.compile(r"^\s*\.\s+(?P<target>.+?)\s*$")
CALL_OPERATOR_PATTERN = re.compile(r"^\s*&\s+(?P<target>.+?)\s*$")
INVOKE_EXPRESSION_PATTERN = re.compile(r"^\s*Invoke-Expression\b(?P<args>.*)$", re.IGNORECASE)
PARAM_START_PATTERN = re.compile(r"\bparam\s*\(", re.IGNORECASE)
PARAM_NAME_PATTERN = re.compile(
    r"(?P<prefix>(?:\[[^\]]+\]\s*)*)\$\s*(?P<name>[A-Za-z_][0-9A-Za-z_]*)",
    re.MULTILINE,
)
ASSIGNMENT_PATTERN = re.compile(r"^\s*\$(?P<name>[A-Za-z_][0-9A-Za-z_]*)\s*=")


def _static_scan_lines(content: str) -> list[str]:
    lines = content.splitlines()
    sanitized: list[str] = []
    in_block_comment = False
    in_here_string: str | None = None
    for line in lines:
        stripped = line.strip()
        if in_here_string is not None:
            sanitized.append("")
            if stripped == in_here_string:
                in_here_string = None
            continue
        if in_block_comment:
            sanitized.append("")
            if "#>" in line:
                in_block_comment = False
            continue
        if "<#" in line:
            sanitized.append(line[: line.index("<#")] if line.index("<#") > 0 else "")
            if "#>" not in line[line.index("<#") + 2 :]:
                in_block_comment = True
            continue
        here_match = re.search(r"@(?P<quote>['\"])\s*$", line)
        if here_match is not None:
            sanitized.append("")
            in_here_string = f"{here_match.group('quote')}@"
            continue
        sanitized.append(line)
    return sanitized


def _extract_script_or_module_observations(
    relative_path: str,
    content: str,
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    lines = _static_scan_lines(content)
    active_function: str | None = None
    active_depth = 0
    index = 0
    while index < len(lines):
        line_number = index + 1
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            index += 1
            continue
        function_line = False

        requires = REQUIRES_PATTERN.match(line)
        if requires is not None:
            observations.append(
                _requires_observation(
                    relative_path,
                    line_number,
                    requires.group("name"),
                    (requires.group("value") or "").strip(),
                )
            )

        using_module = USING_MODULE_PATTERN.match(line)
        if using_module is not None:
            observations.append(
                _module_reference_observation(
                    "powershell.using_module",
                    relative_path,
                    line_number,
                    using_module.group("target"),
                    syntax="using module",
                )
            )

        function_match = FUNCTION_PATTERN.match(line)
        if function_match is not None:
            function_line = True
            active_function = function_match.group("name")
            active_depth = _brace_delta(line)
            observations.append(
                _function_observation(
                    relative_path,
                    line_number,
                    active_function,
                    scope_prefix=function_match.group("scope"),
                )
            )

        import_module = IMPORT_MODULE_PATTERN.match(line)
        if import_module is not None:
            observations.append(
                _module_reference_observation(
                    "powershell.import_module",
                    relative_path,
                    line_number,
                    _first_argument(import_module.group("args")),
                    syntax="Import-Module",
                )
            )

        dot_source = DOT_SOURCE_PATTERN.match(line)
        if dot_source is not None:
            observations.append(
                _dot_source_or_dynamic_observation(
                    relative_path,
                    line_number,
                    dot_source.group("target"),
                )
            )

        call_operator = CALL_OPERATOR_PATTERN.match(line)
        if call_operator is not None:
            call_target = call_operator.group("target").strip()
            target_kind = "dynamic" if _is_dynamic_token(call_target) else "static"
            observations.append(
                _dynamic_invocation_observation(
                    relative_path,
                    line_number,
                    "call-operator",
                    call_target,
                    reason=(
                        "call-operator-dynamic-target"
                        if target_kind == "dynamic"
                        else "call-operator-static-target"
                    ),
                    invocation_kind="call_operator",
                    target_kind=target_kind,
                )
            )

        invoke_expression = INVOKE_EXPRESSION_PATTERN.match(line)
        if invoke_expression is not None:
            observations.append(
                _dynamic_invocation_observation(
                    relative_path,
                    line_number,
                    "Invoke-Expression",
                    invoke_expression.group("args").strip(),
                    reason="invoke-expression",
                    invocation_kind="invoke_expression",
                    target_kind="dynamic",
                )
            )

        assignment = ASSIGNMENT_PATTERN.match(line)
        if assignment is not None and _is_secret_like_name(assignment.group("name")):
            observations.append(
                _secret_like_observation(
                    relative_path,
                    line_number,
                    assignment.group("name"),
                    secret_source="assignment",
                    reason="secret-like assignment name",
                )
            )

        param_match = PARAM_START_PATTERN.search(line)
        if param_match is not None:
            block, end_index = _collect_parenthesized_block(lines, index, param_match.start())
            observations.extend(
                _param_observations(
                    relative_path,
                    line_number,
                    end_index + 1,
                    block,
                    function_name=active_function,
                )
            )
            index = end_index

        if active_function is not None:
            if not function_line:
                active_depth += _brace_delta(line)
            if active_depth <= 0:
                active_function = None
                active_depth = 0
        index += 1
    return tuple(observations)


def _requires_observation(
    relative_path: str,
    line_number: int,
    name: str,
    value: str,
) -> RawObservation:
    metadata: dict[str, Any] = {
        "directive": name,
        "static_only": True,
    }
    if value:
        metadata["value"] = _strip_quotes(value)
    return RawObservation(
        kind="powershell.requires",
        source_id=f"{relative_path}#requires:{line_number}:{slug(name)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=name,
        confidence="extracted",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
    )


def _function_observation(
    relative_path: str,
    line_number: int,
    name: str,
    *,
    scope_prefix: str | None,
) -> RawObservation:
    metadata: dict[str, Any] = {"static_only": True}
    if scope_prefix:
        metadata["scope_prefix"] = scope_prefix.lower()
    return RawObservation(
        kind="powershell.function",
        source_id=f"{relative_path}#function:{line_number}:{slug(name)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=name,
        target=f"powershell.function:{relative_path}:{name}",
        confidence="extracted",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
    )


def _param_observations(
    relative_path: str,
    start_line: int,
    end_line: int,
    block: str,
    *,
    function_name: str | None,
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    scope = "function" if function_name else "file"
    for match in PARAM_NAME_PATTERN.finditer(block):
        name = match.group("name")
        metadata: dict[str, Any] = {
            "scope": scope,
            "static_only": True,
        }
        if function_name is not None:
            metadata["function"] = function_name
        parameter_type = _parameter_type(match.group("prefix"))
        if parameter_type is not None:
            metadata["type"] = parameter_type
        if _is_secret_like_name(name):
            metadata["redacted"] = True
            metadata["redaction_reason"] = "secret-like parameter name"
        observations.append(
            RawObservation(
                kind="powershell.param",
                source_id=f"{relative_path}#param:{start_line}:{scope}:{slug(name)}",
                path=relative_path,
                start_line=start_line,
                end_line=end_line,
                name=name,
                target=f"powershell.param:{relative_path}:{scope}:{name}",
                confidence="extracted",
                extractor=EXTRACTOR_NAME,
                extractor_version=__version__,
                metadata=metadata,
            )
        )
        if _is_secret_like_name(name):
            observations.append(
                _secret_like_observation(
                    relative_path,
                    start_line,
                    name,
                    secret_source="parameter",
                    reason="secret-like parameter name",
                    end_line=end_line,
                )
            )
    return tuple(observations)


def _module_reference_observation(
    kind: str,
    relative_path: str,
    line_number: int,
    target_token: str,
    *,
    syntax: str,
) -> RawObservation:
    token = _strip_quotes(target_token)
    target, metadata = _reference_target_metadata(relative_path, token)
    metadata.update({"syntax": syntax, "static_only": True})
    return RawObservation(
        kind=kind,
        source_id=f"{relative_path}#{kind.rsplit('.', 1)[1]}:{line_number}:{slug(token)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=token,
        target=target,
        confidence=metadata.pop("confidence", "heuristic"),
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
    )


def _dot_source_or_dynamic_observation(
    relative_path: str,
    line_number: int,
    target_token: str,
) -> RawObservation:
    token = _strip_quotes(target_token)
    target, metadata = _reference_target_metadata(relative_path, token)
    if target is None:
        return _dynamic_invocation_observation(
            relative_path,
            line_number,
            "dot-source",
            token,
            reason="dynamic-dot-source-target",
            invocation_kind="dot_source",
            target_kind="dynamic",
        )
    metadata.update({"syntax": "dot-source", "static_only": True})
    return RawObservation(
        kind="powershell.dot_source",
        source_id=f"{relative_path}#dot-source:{line_number}:{slug(token)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=token,
        target=target,
        confidence=metadata.pop("confidence", "heuristic"),
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata=metadata,
    )


def _dynamic_invocation_observation(
    relative_path: str,
    line_number: int,
    name: str,
    token: str,
    *,
    reason: str,
    invocation_kind: str = "unknown",
    target_kind: str | None = None,
) -> RawObservation:
    target_kind = target_kind or ("dynamic" if _is_dynamic_token(token) else "static")
    target_display = (
        "[dynamic]"
        if target_kind != "static"
        else _static_invocation_target_display(token)
    )
    return RawObservation(
        kind="powershell.dynamic_invocation",
        source_id=f"{relative_path}#dynamic:{line_number}:{slug(name)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=name,
        confidence="unknown",
        extractor=EXTRACTOR_NAME,
        extractor_version=__version__,
        metadata={
            "original_token_redacted": _redacted_token_summary(token),
            "invocation_kind": invocation_kind,
            "target_kind": target_kind,
            "target_display": target_display,
            "target_redacted": target_kind != "static",
            "resolution": "dynamic",
            "dynamic_reason": reason,
            "static_only": True,
            "powershell_executed": False,
        },
    )


def _static_invocation_target_display(token: str) -> str:
    tokens = _command_tokens(token)
    if tokens:
        return _strip_quotes(tokens[0])
    return _strip_quotes(token)


def _first_argument(arguments: str) -> str:
    tokens = re.findall(r'"[^"]*"|\'[^\']*\'|\S+', arguments.strip())
    if not tokens:
        return ""
    if tokens[0].lower() == "-name" and len(tokens) > 1:
        return tokens[1]
    return tokens[0]


def _reference_target_metadata(
    relative_path: str,
    token: str,
) -> tuple[str | None, dict[str, Any]]:
    resolved = _resolve_static_path(relative_path, token)
    if resolved is not None:
        return (
            f"file:{resolved}",
            {
                "reference": token,
                "resolved_path": resolved,
                "resolution": "static",
                "confidence": "heuristic",
            },
        )
    if _is_dynamic_token(token):
        return None, {
            "reference_redacted": _redacted_token_summary(token),
            "resolution": "dynamic",
            "confidence": "unknown",
        }
    return (
        f"module:{token}",
        {
            "reference": token,
            "resolution": "module-name",
            "confidence": "heuristic",
        },
    )


def _collect_parenthesized_block(
    lines: list[str],
    start_index: int,
    param_start: int,
) -> tuple[str, int]:
    collected = []
    depth = 0
    index = start_index
    while index < len(lines):
        line = lines[index]
        segment = line[param_start:] if index == start_index else line
        collected.append(segment)
        depth += segment.count("(") - segment.count(")")
        if depth <= 0:
            break
        index += 1
    return "\n".join(collected), index


def _parameter_type(prefix: str) -> str | None:
    bracket_values = [item.strip("[]") for item in re.findall(r"\[[^\]]+\]", prefix)]
    type_values = [
        item
        for item in bracket_values
        if not item.lower().startswith("parameter(")
        and not item.lower().startswith("cmdletbinding(")
    ]
    return type_values[-1] if type_values else None


def _brace_delta(line: str) -> int:
    return line.count("{") - line.count("}")
