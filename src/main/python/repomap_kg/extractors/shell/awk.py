"""Conservative static awk raw observation extraction."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from repomap_kg import __version__
from repomap_kg.extractors.shell.awk_calls import (
    BUILTIN_FAMILIES,
    FUNCTION_RE,
    STATEMENT_BUILTINS,
    awk2_observations,
    awk_metadata,
    builtin_call_observation,
    builtin_call_observations,
    include_extension_observations,
    user_function_call_observations,
)
from repomap_kg.extractors.shell.awk_runtime import (
    EXTRACTOR,
    SECRET_NAME_PARTS,
    argument_count_for_call,
    argument_count_for_statement,
    call_arg_spans,
    call_argument_strings,
    command_info,
    command_runtime_metadata,
    count_top_level_items,
    file_read_observation,
    file_write_observation,
    file_write_redirect,
    first_call_args,
    io_pipe_system_observations,
    is_secret_like_text,
    matching_paren,
    pipe_read_observation,
    pipe_write_observation,
    redirect_observation,
    resolved_include_path,
    runtime_metadata,
    safe_static_target,
    secret_like_observation,
    secret_source_for_observation,
    system_call_observation,
    target_info,
    trim_expression,
    unquote_literal,
    value_intent_info,
)
from repomap_kg.observations.raw import RawObservation
from repomap_kg.extractors.shell.base import slug


AWK_SHEBANG_RE = re.compile(r"^#!.*(?:^|/|\s)(?P<dialect>gawk|mawk|nawk|awk)(?:\s|$)")
ASSIGNMENT_RE = re.compile(
    r"(?<![=!<>])\b(?P<var>[A-Za-z_][A-Za-z0-9_]*)\s*"
    r"(?P<op>\+\+|--|\+=|-=|\*=|/=|=(?!=))\s*(?P<value>.*)$"
)
FIELD_RE = re.compile(r"\$(?P<field>0|[1-9][0-9]*|NF|\([^)]+\)|[A-Za-z_][A-Za-z0-9_]*)")
SPECIAL_VARIABLES = frozenset(
    {
        "FS",
        "OFS",
        "RS",
        "ORS",
        "NR",
        "FNR",
        "NF",
        "FILENAME",
        "ARGC",
        "ARGV",
        "ENVIRON",
        "RSTART",
        "RLENGTH",
    }
)
GawkFeature = tuple[str, str]
GAWK_FEATURE_PATTERNS: tuple[GawkFeature, ...] = (
    ("gawk:@include", r"^\s*@include\b"),
    ("gawk:@load", r"^\s*@load\b"),
    ("gawk:BEGINFILE", r"\bBEGINFILE\b"),
    ("gawk:ENDFILE", r"\bENDFILE\b"),
    ("gawk:gensub", r"\bgensub\s*\("),
    ("gawk:FPAT", r"\bFPAT\b"),
    ("gawk:PROCINFO", r"\bPROCINFO\b"),
    ("gawk:SYMTAB", r"\bSYMTAB\b"),
)


def is_awk_shebang(line: str) -> bool:
    return bool(AWK_SHEBANG_RE.match(line.strip()))


def extract_awk_file_observations(
    relative_path: str,
    content: str,
) -> tuple[RawObservation, ...]:
    dialect = detect_awk_dialect(relative_path, content)
    function_definitions = collect_function_definitions(relative_path, content)
    observations: list[RawObservation] = [
        awk_program_observation(relative_path, content, dialect)
    ]
    block_depth = 0
    current_context = "file"

    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        stripped_for_comment = raw_line.lstrip()
        if not stripped_for_comment or stripped_for_comment.startswith("#"):
            continue

        line = strip_inline_comment(raw_line).rstrip()
        stripped = line.strip()
        if not stripped:
            continue

        masked = mask_strings(line)
        top_level = block_depth <= 0
        block_context = context_for_top_level_line(line, masked) if top_level else None
        call_context = block_context or current_context
        if top_level:
            observations.extend(
                top_level_observations(relative_path, line_number, line, masked, dialect)
            )
        observations.extend(
            assignment_observations(relative_path, line_number, line, masked, dialect)
        )
        observations.extend(
            field_and_record_observations(relative_path, line_number, line, masked, dialect)
        )
        observations.extend(
            dynamic_expression_observations(
                relative_path,
                line_number,
                line,
                masked,
                top_level=top_level,
                dialect=dialect,
            )
        )
        observations.extend(
            awk2_observations(
                relative_path,
                line_number,
                line,
                masked,
                dialect,
                call_context,
                function_definitions,
            )
        )
        new_depth = max(0, block_depth + brace_delta(masked))
        if top_level and new_depth > 0 and block_context is not None:
            current_context = block_context
        elif new_depth == 0:
            current_context = "file"
        block_depth = new_depth

    return tuple(observations)


def top_level_observations(
    relative_path: str,
    line_number: int,
    line: str,
    masked: str,
    dialect: str,
) -> tuple[RawObservation, ...]:
    stripped = line.strip()
    observations: list[RawObservation] = []
    if re.match(r"^BEGIN\b", stripped):
        observations.append(block_observation(relative_path, line_number, "begin", dialect))
        return tuple(observations)
    if re.match(r"^END\b", stripped):
        observations.append(block_observation(relative_path, line_number, "end", dialect))
        return tuple(observations)
    if FUNCTION_RE.match(stripped):
        observations.append(function_observation(relative_path, line_number, line, dialect))
        return tuple(observations)
    if stripped.startswith("@") or re.match(r"^(BEGINFILE|ENDFILE)\b", stripped):
        return ()
    pattern = pattern_from_line(stripped, masked.strip())
    if pattern is not None:
        observations.append(
            pattern_action_observation(relative_path, line_number, pattern, masked, dialect)
        )
    return tuple(observations)


def awk_program_observation(relative_path: str, content: str, dialect: str) -> RawObservation:
    lines = content.splitlines()
    first = lines[0].strip() if lines else ""
    metadata = awk_metadata(
        dialect,
        {
            "file_type": "awk",
            "shebang": first if first.startswith("#!") else None,
            "classification_evidence": classification_evidence(relative_path, content),
            "parser": "stdlib-static-scanner",
        },
    )
    return RawObservation(
        kind="awk.program",
        source_id=f"{relative_path}#awk-program",
        path=relative_path,
        name=relative_path,
        confidence="extracted",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=metadata,
    )


def classification_evidence(relative_path: str, content: str) -> list[str]:
    first = content.splitlines()[0].strip() if content.splitlines() else ""
    evidence: list[str] = []
    if Path(relative_path).suffix == ".awk":
        evidence.append("extension")
    shebang_match = AWK_SHEBANG_RE.match(first)
    if shebang_match is not None:
        evidence.append("shebang")
        if shebang_match.group("dialect") == "gawk":
            evidence.append("shebang:gawk")
    for feature, pattern in GAWK_FEATURE_PATTERNS:
        if re.search(pattern, content, flags=re.MULTILINE):
            evidence.append(feature)
    return evidence


def detect_awk_dialect(relative_path: str, content: str) -> str:
    evidence = classification_evidence(relative_path, content)
    if any(item == "shebang:gawk" or item.startswith("gawk:") for item in evidence):
        return "gawk"
    return "awk"


def block_observation(
    relative_path: str,
    line_number: int,
    block_kind: str,
    dialect: str,
) -> RawObservation:
    kind = f"awk.{block_kind}"
    metadata = awk_metadata(
        dialect,
        {
            "block_kind": block_kind,
            "pattern_kind": block_kind,
            "action_present": True,
            "action_modeled": False,
        },
    )
    return RawObservation(
        kind=kind,
        source_id=f"{relative_path}#awk-{block_kind}:{line_number}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=block_kind.upper(),
        confidence="extracted",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=metadata,
    )


def function_observation(
    relative_path: str,
    line_number: int,
    line: str,
    dialect: str,
) -> RawObservation:
    match = FUNCTION_RE.match(line.strip())
    assert match is not None
    function_name = match.group("name")
    parameters, local_parameters = split_function_parameters(match.group("params"))
    metadata = awk_metadata(
        dialect,
        {
            "function_name": function_name,
            "parameters": parameters,
            "local_parameters": local_parameters,
            "body_modeled": False,
        },
    )
    return RawObservation(
        kind="awk.function",
        source_id=f"{relative_path}#awk-function:{line_number}:{slug(function_name)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=function_name,
        confidence="extracted",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=metadata,
    )


def pattern_action_observation(
    relative_path: str,
    line_number: int,
    pattern: str,
    masked: str,
    dialect: str,
) -> RawObservation:
    action_present = "{" in masked
    pattern_summary = pattern.strip()
    metadata = awk_metadata(
        dialect,
        {
            "pattern_kind": pattern_kind(pattern_summary),
            "pattern_summary": pattern_summary or None,
            "action_present": action_present,
            "action_modeled": False,
        },
    )
    return RawObservation(
        kind="awk.pattern_action",
        source_id=f"{relative_path}#awk-pattern:{line_number}:{slug(pattern_summary or 'empty')}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=pattern_summary or "[empty]",
        confidence="heuristic",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=metadata,
    )


def assignment_observations(
    relative_path: str,
    line_number: int,
    line: str,
    masked: str,
    dialect: str,
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    match = ASSIGNMENT_RE.search(masked)
    if match is None:
        return ()
    variable = match.group("var")
    if variable in {"if", "for", "while", "print", "printf", "return"}:
        return ()
    operation = operation_name(match.group("op"))
    value = line[match.start("value") :].strip()
    redacted, reason = redaction_for_name(variable)
    metadata: dict[str, Any] = {
        "variable": variable,
        "operation": operation,
        "value_kind": value_kind(value),
        "special_variable": variable in SPECIAL_VARIABLES,
        "redacted": redacted,
        "raw_value_stored": not redacted,
    }
    if redacted:
        metadata["redaction_reason"] = reason
    else:
        summary = safe_value_summary(value)
        if summary is not None:
            metadata["value_summary"] = summary
    observations.append(
        RawObservation(
            kind="awk.variable_assignment",
            source_id=f"{relative_path}#awk-assignment:{line_number}:{slug(variable)}",
            path=relative_path,
            start_line=line_number,
            end_line=line_number,
            name=variable,
            confidence="extracted",
            extractor=EXTRACTOR,
            extractor_version=__version__,
            metadata=awk_metadata(dialect, metadata),
        )
    )
    if redacted:
        observations.append(
            secret_like_observation(
                relative_path,
                line_number,
                "variable_assignment",
                reason or "secret-like-name",
                dialect,
            )
        )
    return tuple(observations)


def field_and_record_observations(
    relative_path: str,
    line_number: int,
    line: str,
    masked: str,
    dialect: str,
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    for index, match in enumerate(FIELD_RE.finditer(masked)):
        field = match.group("field")
        if field == "0":
            observations.append(record_observation(relative_path, line_number, "$0", dialect))
            continue
        metadata: dict[str, Any] = {}
        name = f"${field}"
        confidence = "extracted"
        target: str | None = None
        if field.isdigit():
            metadata = {"reference_kind": "field", "field_number": int(field)}
        elif field == "NF":
            metadata = {"reference_kind": "field", "field_name": "NF"}
        else:
            confidence = "heuristic"
            metadata = {
                "reference_kind": "dynamic_field",
                "resolution": "dynamic",
                "dynamic_reason": "dynamic_field",
            }
            name = "[dynamic]"
        observations.append(
            RawObservation(
                kind="awk.field_reference",
                source_id=f"{relative_path}#awk-field:{line_number}:{index}:{slug(name)}",
                path=relative_path,
                start_line=line_number,
                end_line=line_number,
                name=name,
                target=target,
                confidence=confidence,
                extractor=EXTRACTOR,
                extractor_version=__version__,
                metadata=awk_metadata(dialect, metadata),
            )
        )
    for variable in sorted(special_variables_in(masked)):
        observations.append(record_observation(relative_path, line_number, variable, dialect))
    return tuple(observations)


def record_observation(
    relative_path: str,
    line_number: int,
    name: str,
    dialect: str,
) -> RawObservation:
    if name == "$0":
        metadata = {"reference_kind": "record"}
    else:
        metadata = {"reference_kind": "special_variable", "variable": name}
    return RawObservation(
        kind="awk.record_reference",
        source_id=f"{relative_path}#awk-record:{line_number}:{slug(name)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=name,
        confidence="extracted",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=awk_metadata(dialect, metadata),
    )


def dynamic_expression_observations(
    relative_path: str,
    line_number: int,
    line: str,
    masked: str,
    *,
    top_level: bool,
    dialect: str,
) -> tuple[RawObservation, ...]:
    reasons: set[str] = set()
    if re.search(r"\$\([^)]*\)", masked) or re.search(r"\$[A-Za-z_][A-Za-z0-9_]*", masked):
        reasons.add("dynamic_field")
    if re.search(r"~\s*[A-Za-z_][A-Za-z0-9_]*\b", masked):
        reasons.add("dynamic_regex")
    assignment = ASSIGNMENT_RE.search(masked)
    if assignment is not None:
        variable = assignment.group("var")
        value = line[assignment.start("value") :].strip()
        masked_value = masked[assignment.start("value") :].strip()
        if has_string_concatenation(masked_value):
            reasons.add("string_concatenation")
        if variable.endswith(("_file", "_path", "_target")) and is_dynamic_value(masked_value):
            reasons.add("computed_target")
        if variable == "command" and is_dynamic_value(masked_value):
            reasons.add("computed_target")
        if "ENVIRON[" in masked_value or "ENVIRON[" in value:
            reasons.add("computed_target")
    if top_level and re.match(r"^(@include|@load|BEGINFILE|ENDFILE)\b", masked.strip()):
        reasons.add("unsupported_gawk_extension")
    if "gensub" in masked or "PROCINFO" in masked or "FPAT" in masked or "SYMTAB" in masked:
        reasons.add("unsupported_gawk_extension")
    return tuple(
        dynamic_expression_observation(relative_path, line_number, reason, dialect)
        for reason in sorted(reasons)
    )


def dynamic_expression_observation(
    relative_path: str,
    line_number: int,
    reason: str,
    dialect: str,
) -> RawObservation:
    return RawObservation(
        kind="awk.dynamic_expression",
        source_id=f"{relative_path}#awk-dynamic:{line_number}:{slug(reason)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name="[dynamic]",
        confidence="heuristic",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=awk_metadata(
            dialect,
            {
                "resolution": "dynamic",
                "dynamic_reason": reason,
            },
        ),
    )


def collect_function_definitions(relative_path: str, content: str) -> dict[str, str]:
    definitions: dict[str, str] = {}
    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        stripped = strip_inline_comment(raw_line).strip()
        match = FUNCTION_RE.match(stripped)
        if match is None:
            continue
        function_name = match.group("name")
        definitions[function_name] = (
            f"{relative_path}#awk-function:{line_number}:{slug(function_name)}"
        )
    return definitions


def context_for_top_level_line(line: str, masked: str) -> str | None:
    stripped = line.strip()
    if re.match(r"^BEGIN\b", stripped):
        return "begin"
    if re.match(r"^END\b", stripped):
        return "end"
    if FUNCTION_RE.match(stripped):
        return "function"
    if pattern_from_line(stripped, masked.strip()) is not None:
        return "pattern_action"
    return None


def strip_inline_comment(line: str) -> str:
    quote: str | None = None
    escaped = False
    for index, char in enumerate(line):
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote is not None:
            escaped = True
            continue
        if char in {"'", '"'}:
            if quote is None:
                quote = char
            elif quote == char:
                quote = None
            continue
        if char == "#" and quote is None:
            return line[:index]
    return line


def mask_strings(line: str) -> str:
    result: list[str] = []
    quote: str | None = None
    escaped = False
    for char in line:
        if escaped:
            result.append(" ")
            escaped = False
            continue
        if char == "\\" and quote is not None:
            result.append(" ")
            escaped = True
            continue
        if char in {"'", '"'}:
            if quote is None:
                quote = char
                result.append(char)
                continue
            if quote == char:
                quote = None
                result.append(char)
                continue
        result.append(" " if quote is not None else char)
    return "".join(result)


def brace_delta(masked_line: str) -> int:
    return masked_line.count("{") - masked_line.count("}")


def pattern_from_line(stripped: str, masked_stripped: str) -> str | None:
    if not stripped:
        return None
    if re.match(r"^(print|printf|return|next|getline|close|system)\b", masked_stripped):
        return None
    brace_index = masked_stripped.find("{")
    if brace_index >= 0:
        return stripped[:brace_index].strip()
    if ASSIGNMENT_RE.search(masked_stripped):
        return None
    if looks_like_actionless_pattern(masked_stripped):
        return stripped.strip()
    return None


def looks_like_actionless_pattern(masked: str) -> bool:
    if not masked or masked in {"}", "{"}:
        return False
    if masked.startswith("/"):
        return True
    return bool(
        re.search(r"\b(NR|FNR|NF|FILENAME)\b", masked)
        and re.search(r"(==|!=|<=|>=|<|>|~|!~)", masked)
    )


def pattern_kind(pattern: str) -> str:
    if not pattern:
        return "empty"
    if "," in pattern:
        return "range"
    if pattern.startswith("/") and pattern.endswith("/"):
        return "regex"
    if pattern.startswith("/"):
        return "regex"
    if any(operator in pattern for operator in ("==", "!=", "<=", ">=", "<", ">", "~", "!~")):
        return "expression"
    return "unknown"


def split_function_parameters(params: str) -> tuple[list[str], list[str]]:
    boundary = re.search(r",\s{2,}", params)
    if boundary is None:
        return parse_param_names(params), []
    public_part = params[: boundary.start()]
    local_part = params[boundary.end() :]
    return parse_param_names(public_part), parse_param_names(local_part)


def parse_param_names(params: str) -> list[str]:
    names = []
    for item in params.split(","):
        name = item.strip()
        if not name:
            continue
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
            names.append(name)
    return names


def operation_name(operator: str) -> str:
    return {
        "=": "assign",
        "+=": "add_assign",
        "-=": "sub_assign",
        "*=": "mul_assign",
        "/=": "div_assign",
        "++": "increment",
        "--": "decrement",
    }.get(operator, "unknown")


def value_kind(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        return "unknown"
    if stripped.startswith("$0"):
        return "record"
    if stripped.startswith("$"):
        return "field"
    if re.match(r"^-?[0-9]+(?:\.[0-9]+)?$", stripped):
        return "number"
    if quoted_literal(stripped):
        return "string"
    if "ENVIRON[" in stripped or "$" in stripped:
        return "dynamic"
    return "unknown"


def quoted_literal(value: str) -> bool:
    return (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    )


def safe_value_summary(value: str) -> str | None:
    stripped = value.strip()
    if not stripped or len(stripped) > 80:
        return None
    return stripped


def special_variables_in(masked: str) -> set[str]:
    variables = set()
    for variable in SPECIAL_VARIABLES:
        if re.search(rf"\b{re.escape(variable)}\b", masked):
            variables.add(variable)
    return variables


def has_string_concatenation(masked_value: str) -> bool:
    return bool(re.search(r'"\s+[A-Za-z_]|"\s+ENVIRON|\]\s*"', masked_value))


def is_dynamic_value(value: str) -> bool:
    return "ENVIRON[" in value or "$" in value or any(char in value for char in "[]()")


def redaction_for_name(name: str) -> tuple[bool, str | None]:
    lower = name.lower()
    parts = [part for part in re.split(r"[^a-z0-9]+", lower) if part]
    if any(part in SECRET_NAME_PARTS for part in parts):
        return True, "secret-like-name"
    if any(marker in lower for marker in ("password", "passwd", "secret", "token", "credential", "apikey", "authorization")):
        return True, "secret-like-name"
    if lower.endswith("_key") or lower == "key":
        return True, "secret-like-name"
    return False, None
