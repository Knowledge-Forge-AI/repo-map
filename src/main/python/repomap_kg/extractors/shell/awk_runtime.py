"""AWK runtime-intent raw observation helpers."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from repomap_kg import __version__
from repomap_kg.observations.raw import RawObservation
from repomap_kg.extractors.shell.base import slug


EXTRACTOR = "repo-awk"
SECRET_NAME_PARTS = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "token",
        "key",
        "credential",
        "apikey",
        "pat",
        "authorization",
        "auth",
    }
)


def io_pipe_system_observations(
    relative_path: str,
    line_number: int,
    line: str,
    masked: str,
    dialect: str,
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    stripped = masked.strip()

    if re.search(r"\bgetline\b", masked):
        read_index = masked.find("<")
        pipe_index = masked.find("|")
        if read_index >= 0:
            target = target_info(line[read_index + 1 :], secret_source="file_target")
            observations.append(file_read_observation(relative_path, line_number, target, dialect))
            observations.append(
                redirect_observation(
                    relative_path,
                    line_number,
                    "<",
                    "file_read",
                    target,
                    dialect,
                )
            )
        if pipe_index >= 0 and pipe_index < masked.find("getline"):
            command = command_info(line[:pipe_index], secret_source="pipe_command")
            observations.append(pipe_read_observation(relative_path, line_number, command, dialect))
            observations.append(
                redirect_observation(
                    relative_path,
                    line_number,
                    "|",
                    "pipe_read",
                    command,
                    dialect,
                )
            )

    if re.match(r"^(print|printf)\b", stripped):
        redirect_index, operator = file_write_redirect(masked)
        if redirect_index is not None and operator is not None:
            target = target_info(line[redirect_index + len(operator) :], secret_source="file_target")
            observations.append(file_write_observation(relative_path, line_number, operator, target, dialect))
            observations.append(
                redirect_observation(
                    relative_path,
                    line_number,
                    operator,
                    "file_write",
                    target,
                    dialect,
                )
            )
        pipe_index = masked.find("|")
        if pipe_index >= 0:
            command = command_info(line[pipe_index + 1 :], secret_source="pipe_command")
            observations.append(pipe_write_observation(relative_path, line_number, command, dialect))
            observations.append(
                redirect_observation(
                    relative_path,
                    line_number,
                    "|",
                    "pipe_write",
                    command,
                    dialect,
                )
            )

    for args in call_argument_strings(line, masked, "system"):
        command = command_info(args, secret_source="system_call")
        observations.append(system_call_observation(relative_path, line_number, command, dialect))

    secret_observations: list[RawObservation] = []
    for observation in observations:
        source = secret_source_for_observation(observation)
        reason = observation.metadata.get("redaction_reason")
        if source is not None and reason:
            secret_observations.append(
                secret_like_observation(relative_path, line_number, source, str(reason), dialect)
            )
    observations.extend(secret_observations)
    return tuple(observations)


def file_read_observation(
    relative_path: str,
    line_number: int,
    target: dict[str, Any],
    dialect: str,
) -> RawObservation:
    metadata = runtime_metadata(
        dialect,
        {
            "target_kind": target["kind"],
            "target_display": target["display"],
            "resolution": target["resolution"],
            "redirect_operator": "<",
            "filesystem_checked": False,
            "file_opened": False,
            "raw_value_stored": target["raw_value_stored"],
            **target.get("extra", {}),
        },
    )
    return RawObservation(
        kind="awk.file_read",
        source_id=f"{relative_path}#awk-file-read:{line_number}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=target["display"],
        target=target["display"] if target["kind"] == "static" else None,
        confidence="heuristic",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=metadata,
    )


def file_write_observation(
    relative_path: str,
    line_number: int,
    operator: str,
    target: dict[str, Any],
    dialect: str,
) -> RawObservation:
    write_mode = "append" if operator == ">>" else "truncate" if operator == ">" else "unknown"
    metadata = runtime_metadata(
        dialect,
        {
            "target_kind": target["kind"],
            "target_display": target["display"],
            "resolution": target["resolution"],
            "redirect_operator": operator,
            "write_mode": write_mode,
            "filesystem_checked": False,
            "file_opened": False,
            "file_created": False,
            "file_mutated": False,
            "host_mutation_proven": False,
            "raw_value_stored": target["raw_value_stored"],
            **target.get("extra", {}),
        },
    )
    return RawObservation(
        kind="awk.file_write",
        source_id=f"{relative_path}#awk-file-write:{line_number}:{slug(operator)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=target["display"],
        target=target["display"] if target["kind"] == "static" else None,
        confidence="heuristic",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=metadata,
    )


def pipe_read_observation(
    relative_path: str,
    line_number: int,
    command: dict[str, Any],
    dialect: str,
) -> RawObservation:
    metadata = command_runtime_metadata(dialect, command, {"pipe_opened": False})
    return RawObservation(
        kind="awk.pipe_read",
        source_id=f"{relative_path}#awk-pipe-read:{line_number}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=command["display"],
        confidence="heuristic",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=metadata,
    )


def pipe_write_observation(
    relative_path: str,
    line_number: int,
    command: dict[str, Any],
    dialect: str,
) -> RawObservation:
    metadata = command_runtime_metadata(dialect, command, {"pipe_opened": False})
    return RawObservation(
        kind="awk.pipe_write",
        source_id=f"{relative_path}#awk-pipe-write:{line_number}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=command["display"],
        confidence="heuristic",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=metadata,
    )


def system_call_observation(
    relative_path: str,
    line_number: int,
    command: dict[str, Any],
    dialect: str,
) -> RawObservation:
    metadata = command_runtime_metadata(dialect, command, {})
    return RawObservation(
        kind="awk.system_call",
        source_id=f"{relative_path}#awk-system:{line_number}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=command["display"],
        confidence="heuristic",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=metadata,
    )


def redirect_observation(
    relative_path: str,
    line_number: int,
    operator: str,
    redirect_kind: str,
    target: dict[str, Any],
    dialect: str,
) -> RawObservation:
    metadata = runtime_metadata(
        dialect,
        {
            "redirect_operator": operator,
            "redirect_kind": redirect_kind,
            "target_kind": target["kind"],
            "target_display": target["display"],
            "filesystem_checked": False,
            "command_executed": False,
            "raw_value_stored": target["raw_value_stored"],
            **target.get("extra", {}),
        },
    )
    return RawObservation(
        kind="awk.redirect",
        source_id=f"{relative_path}#awk-redirect:{line_number}:{slug(redirect_kind)}:{slug(operator)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=operator,
        confidence="heuristic",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=metadata,
    )


def secret_like_observation(
    relative_path: str,
    line_number: int,
    secret_source: str,
    redaction_reason: str,
    dialect: str,
) -> RawObservation:
    return RawObservation(
        kind="awk.secret_like",
        source_id=f"{relative_path}#awk-secret:{line_number}:{slug(secret_source)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=secret_source,
        confidence="heuristic",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=awk_metadata(
            dialect,
            {
                "secret_source": secret_source,
                "redaction_reason": redaction_reason,
                "raw_value_stored": False,
            },
        ),
    )


def awk_metadata(dialect: str, metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "language": "awk",
        "dialect": dialect,
        "static_only": True,
        "awk_executed": False,
        "shell_executed": False,
        **metadata,
    }


def runtime_metadata(dialect: str, metadata: dict[str, Any]) -> dict[str, Any]:
    return awk_metadata(
        dialect,
        {
            "runtime_intent": True,
            "awk_executed": False,
            "shell_executed": False,
            "command_executed": False,
            "filesystem_checked": False,
            "file_opened": False,
            "host_mutation_proven": False,
            **metadata,
        },
    )


def command_runtime_metadata(
    dialect: str,
    command: dict[str, Any],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    return runtime_metadata(
        dialect,
        {
            "command_text_kind": command["kind"],
            "command_summary": command["display"],
            "command_executed": False,
            "shell_executed": False,
            "awk_executed": False,
            "host_mutation_proven": False,
            "raw_value_stored": command["raw_value_stored"],
            **command.get("extra", {}),
            **metadata,
        },
    )


def argument_count_for_statement(line: str, builtin: str) -> int | None:
    stripped = line.strip()
    if not stripped.startswith(builtin):
        return None
    remainder = stripped[len(builtin) :].strip()
    if not remainder:
        return 0
    if builtin == "getline":
        return 1
    return count_top_level_items(remainder)


def argument_count_for_call(masked: str, function_name: str) -> int | None:
    args = first_call_args(masked, function_name)
    if args is None:
        return None
    if not args.strip():
        return 0
    return count_top_level_items(args)


def call_argument_strings(line: str, masked: str, function_name: str) -> tuple[str, ...]:
    spans = call_arg_spans(masked, function_name)
    return tuple(line[start:end] for start, end in spans)


def first_call_args(masked: str, function_name: str) -> str | None:
    spans = call_arg_spans(masked, function_name)
    if not spans:
        return None
    start, end = spans[0]
    return masked[start:end]


def call_arg_spans(masked: str, function_name: str) -> tuple[tuple[int, int], ...]:
    spans: list[tuple[int, int]] = []
    for match in re.finditer(rf"\b{re.escape(function_name)}\s*\(", masked):
        open_index = masked.find("(", match.start())
        close_index = matching_paren(masked, open_index)
        if close_index is None:
            continue
        spans.append((open_index + 1, close_index))
    return tuple(spans)


def matching_paren(text: str, open_index: int) -> int | None:
    depth = 0
    for index in range(open_index, len(text)):
        char = text[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
    return None


def count_top_level_items(text: str) -> int:
    depth = 0
    count = 1
    saw_content = False
    for char in text:
        if char in "([{":
            depth += 1
        elif char in ")]}" and depth > 0:
            depth -= 1
        elif char == "," and depth == 0:
            count += 1
            continue
        if not char.isspace() and not (char == "," and depth == 0):
            saw_content = True
    return count if saw_content else 0


def file_write_redirect(masked: str) -> tuple[int | None, str | None]:
    append_index = masked.find(">>")
    truncate_index = re.search(r"(?<![<>=])>(?![>=])", masked)
    if append_index >= 0:
        return append_index, ">>"
    if truncate_index is not None:
        return truncate_index.start(), ">"
    return None, None


def target_info(expression: str, *, secret_source: str) -> dict[str, Any]:
    return value_intent_info(expression, secret_source=secret_source, static_label="static")


def command_info(expression: str, *, secret_source: str) -> dict[str, Any]:
    return value_intent_info(expression, secret_source=secret_source, static_label="static")


def value_intent_info(
    expression: str,
    *,
    secret_source: str,
    static_label: str,
) -> dict[str, Any]:
    stripped = trim_expression(expression)
    literal = unquote_literal(stripped)
    if literal is not None:
        if is_secret_like_text(literal):
            return {
                "kind": "redacted",
                "display": "[redacted]",
                "resolution": "redacted",
                "raw_value_stored": False,
                "extra": {
                    "redacted": True,
                    "redaction_reason": "secret-like-value",
                    "secret_source": secret_source,
                },
            }
        if len(literal) <= 96 and safe_static_target(literal):
            return {
                "kind": static_label,
                "display": literal,
                "resolution": "static",
                "raw_value_stored": True,
                "extra": {},
            }
        return {
            "kind": "unknown",
            "display": "[unknown]",
            "resolution": "unknown",
            "raw_value_stored": False,
            "extra": {"dynamic_reason": "unsupported_expression"},
        }
    if is_secret_like_text(stripped):
        return {
            "kind": "redacted",
            "display": "[redacted]",
            "resolution": "redacted",
            "raw_value_stored": False,
            "extra": {
                "redacted": True,
                "redaction_reason": "secret-like-value",
                "secret_source": secret_source,
            },
        }
    if stripped:
        return {
            "kind": "dynamic",
            "display": "[dynamic]",
            "resolution": "dynamic",
            "raw_value_stored": False,
            "extra": {"dynamic_reason": "computed_target"},
        }
    return {
        "kind": "unknown",
        "display": "[unknown]",
        "resolution": "unknown",
        "raw_value_stored": False,
        "extra": {"dynamic_reason": "unsupported_expression"},
    }


def trim_expression(expression: str) -> str:
    stripped = expression.strip()
    stripped = stripped.rstrip(";")
    return stripped.strip()


def unquote_literal(value: str) -> str | None:
    stripped = value.strip()
    if not quoted_literal(stripped):
        return None
    return stripped[1:-1]


def safe_static_target(value: str) -> bool:
    if not value or value.startswith(("/", "~")):
        return False
    parts = Path(value).parts
    return ".." not in parts


def resolved_include_path(relative_path: str, target: dict[str, Any]) -> str | None:
    if target["kind"] != "static":
        return None
    value = target["display"]
    if not safe_static_target(value):
        return None
    base = Path(relative_path).parent
    return str(base.joinpath(value).as_posix())


def is_secret_like_text(value: str) -> bool:
    lower = value.lower()
    parts = [part for part in re.split(r"[^a-z0-9]+", lower) if part]
    if any(part in SECRET_NAME_PARTS for part in parts):
        return True
    return any(
        marker in lower
        for marker in (
            "password",
            "passwd",
            "secret",
            "token",
            "credential",
            "apikey",
            "authorization",
        )
    )


def secret_source_for_observation(observation: RawObservation) -> str | None:
    if observation.kind == "awk.system_call" and observation.metadata.get("redacted"):
        return "system_call"
    if observation.kind in {"awk.pipe_read", "awk.pipe_write"} and observation.metadata.get("redacted"):
        return "pipe_command"
    if observation.kind in {"awk.file_read", "awk.file_write"} and observation.metadata.get("redacted"):
        return "file_target"
    if observation.kind in {"awk.include", "awk.extension"} and observation.metadata.get("redacted"):
        return "include_target"
    return None


def quoted_literal(value: str) -> bool:
    return (
        (value.startswith('"') and value.endswith('"'))
        or (value.startswith("'") and value.endswith("'"))
    )
