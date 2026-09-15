"""Token and pipeline helpers for conservative PowerShell extraction."""

from __future__ import annotations

import re

from repomap_kg.extractors.shell.powershell_common import _is_dynamic_token

TOKEN_PATTERN = re.compile(r'"[^"]*"|\'[^\']*\'|@\{|@\w+|&&|\|\||[|;{}=]|\S+')


def _collect_pipeline_lines(lines: list[str], start_index: int) -> tuple[list[str], int]:
    collected: list[str] = []
    index = start_index
    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped:
            break
        collected.append(stripped)
        if not stripped.endswith("|"):
            break
        index += 1
    return collected, index


def _pipeline_segments(lines: list[str]) -> list[str]:
    segments: list[str] = []
    for line in lines:
        for segment in line.split("|"):
            stripped = segment.strip()
            if stripped:
                segments.append(stripped)
    return segments


def _command_tokens(segment: str) -> list[str]:
    return [token.rstrip(",;") for token in TOKEN_PATTERN.findall(segment.strip()) if token.strip()]


def _has_pipeline_separator(stripped: str) -> bool:
    return "|" in stripped and "||" not in stripped


def _starts_pipeline(stripped: str) -> bool:
    return stripped.startswith("|")


def _token_has_argument_value(token: str) -> bool:
    return not (
        token.startswith("-")
        or token in {"|", ";", "&&", "||", "}", "="}
        or token.startswith("@") and token != "@{"
    )


def _token_is_positional_argument(token: str) -> bool:
    return not (
        token.startswith("-")
        or token in {"|", ";", "&&", "||", "{", "}", "=", "@{"}
        or token.startswith("@")
    )


def _argument_value_kind(token: str) -> str:
    if token == "@{":
        return "hashtable"
    if _is_dynamic_token(token):
        return "dynamic"
    return "static"


def _skip_hashtable(tokens: list[str], start_index: int) -> int:
    depth = 0
    index = start_index
    while index < len(tokens):
        token = tokens[index]
        if token == "@{":
            depth += 1
        elif token == "}":
            depth -= 1
            if depth <= 0:
                return index + 1
        index += 1
    return index
