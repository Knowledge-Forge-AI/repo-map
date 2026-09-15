"""Shared Bats extractor context, metadata, and redaction helpers."""

from __future__ import annotations

import posixpath
import re
import shlex
from dataclasses import dataclass
from typing import Any

from repomap_kg import __version__
from repomap_kg.observations.raw import RawObservation
from repomap_kg.extractors.shell.base import slug


EXTRACTOR = "repo-bats"
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


@dataclass
class BatsContext:
    test_context: str
    test_case_name: str | None = None
    test_case_name_redacted: bool = False
    brace_depth: int = 0


def assertion_mode(arguments: list[str]) -> str:
    if "--partial" in arguments:
        return "partial"
    if "--regexp" in arguments or "--regex" in arguments:
        return "regex"
    if arguments:
        return "exact"
    return "unknown"


def assertion_expected_value(arguments: list[str]) -> str | None:
    values = [argument for argument in arguments if not argument.startswith("--")]
    if not values:
        return None
    if values[0] in {"$status", "${status}"} and len(values) > 1:
        return values[1]
    return values[-1]


def expected_value_metadata(value: str | None) -> tuple[str, dict[str, Any], str | None]:
    if value is None:
        return "omitted", {"raw_value_stored": False, "redacted": False}, None
    redacted, reason = redaction_for_value(value)
    if redacted:
        return (
            "redacted",
            {
                "raw_value_stored": False,
                "redacted": True,
                "redaction_reason": reason,
            },
            reason or "secret-like-value",
        )
    if is_dynamic_value(value):
        return (
            "dynamic",
            {
                "raw_value_stored": False,
                "redacted": False,
                "dynamic_reason": "computed-value",
            },
            None,
        )
    metadata: dict[str, Any] = {"raw_value_stored": True, "redacted": False}
    if len(value) <= 80:
        metadata["expected_value_summary"] = value
    else:
        metadata["raw_value_stored"] = False
        metadata["expected_value_summary"] = "[long]"
    return "static", metadata, None


def status_expectation_from_assertion(
    assertion_name: str,
    arguments: list[str],
) -> tuple[int | None, bool | None, str] | None:
    if assertion_name == "assert_success":
        return (0, True, "assertion")
    if assertion_name == "assert_failure":
        return (None, False, "assertion")
    if assertion_name == "assert_equal":
        values = [argument for argument in arguments if not argument.startswith("--")]
        if len(values) >= 2 and values[0] in {"$status", "${status}"}:
            try:
                status = int(values[1])
            except ValueError:
                return None
            return (status, status == 0, "equality")
    return None


def context_metadata(context: BatsContext) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "test_context": context.test_context,
        "test_intent": True,
        "command_executed": False,
    }
    if context.test_case_name is not None:
        metadata["test_case_name"] = context.test_case_name
        metadata["test_case_name_redacted"] = context.test_case_name_redacted
    return metadata


def secret_like_observation(
    relative_path: str,
    line_number: int,
    name: str,
    secret_context: str,
    reason: str,
    context: BatsContext,
) -> RawObservation:
    return RawObservation(
        kind="shell.secret_like",
        source_id=f"{relative_path}#bats-secret:{line_number}:{slug(secret_context + '-' + name)}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=name,
        confidence="heuristic",
        extractor=EXTRACTOR,
        extractor_version=__version__,
        metadata=bats_metadata(
            {
                "secret_context": secret_context,
                "redacted": True,
                "redaction_reason": reason,
                "raw_value_stored": False,
                **context_metadata(context),
            }
        ),
    )


def secret_like_argument_observations(
    relative_path: str,
    line_number: int,
    arguments: list[str],
    context: BatsContext,
    *,
    secret_context: str,
) -> tuple[RawObservation, ...]:
    observations = []
    previous_flag_secret = False
    previous_flag_name = ""
    for argument in arguments:
        flag_secret = is_secret_like_flag(argument)
        redacted, reason = redaction_for_value(argument)
        if flag_secret:
            observations.append(
                secret_like_observation(
                    relative_path,
                    line_number,
                    argument.split("=", 1)[0],
                    secret_context,
                    reason or "secret-like-argument",
                    context,
                )
            )
        elif previous_flag_secret and redacted:
            observations.append(
                secret_like_observation(
                    relative_path,
                    line_number,
                    previous_flag_name or "[redacted]",
                    secret_context,
                    reason or "secret-like-argument",
                    context,
                )
            )
        previous_flag_secret = flag_secret and "=" not in argument
        previous_flag_name = argument.split("=", 1)[0] if previous_flag_secret else ""
    return tuple(observations)


def is_secret_like_flag(argument: str) -> bool:
    normalized = argument.lower().lstrip("-")
    return normalized in {"password", "passwd", "token", "api-key", "authorization"}


def is_helper_like_command(command_token: str) -> bool:
    command_name = posixpath.basename(command_token)
    return command_name.startswith("helper_") or command_name.endswith("_helper")


def split_words(raw_line: str) -> list[str]:
    try:
        lexer = shlex.shlex(raw_line, posix=True)
        lexer.whitespace_split = True
        lexer.commenters = "#"
        return list(lexer)
    except ValueError:
        return []


def bats_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "dialect": "bats",
        "test_framework": "bats",
        "static_only": True,
        "shell_executed": False,
        "bats_executed": False,
        **metadata,
    }


def is_dynamic_value(value: str) -> bool:
    return "$" in value or "`" in value


def redaction_for_value(value: str) -> tuple[bool, str | None]:
    normalized = re.sub(r"[^a-z0-9]+", " ", value.lower()).split()
    compact = re.sub(r"[^a-z0-9]+", "", value.lower())
    for part in SECRET_NAME_PARTS:
        if part in {"key", "pat"}:
            if part in normalized:
                return True, "secret-like-value"
            continue
        if part in normalized:
            return True, "secret-like-value"
        if part in {
            "apikey",
            "password",
            "passwd",
            "secret",
            "token",
            "credential",
            "authorization",
        } and part in compact:
            return True, "secret-like-value"
    return False, None
