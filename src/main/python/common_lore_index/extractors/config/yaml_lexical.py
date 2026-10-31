"""Lexical helpers for the conservative YAML parser."""

from __future__ import annotations

import re
from typing import Any


class YamlParseError(ValueError):
    """Raised when conservative YAML parsing cannot safely continue."""

    def __init__(
        self,
        message: str,
        *,
        error_kind: str = "malformed-yaml",
        line_number: int | None = None,
    ) -> None:
        super().__init__(message)
        self.error_kind = error_kind
        self.line_number = line_number


def _strip_yaml_comment(line: str) -> str:
    output: list[str] = []
    quote: str | None = None
    escaped = False
    for index, character in enumerate(line):
        if quote is not None:
            output.append(character)
            if escaped:
                escaped = False
            elif character == "\\" and quote == '"':
                escaped = True
            elif character == quote:
                quote = None
            continue
        if character in ("'", '"'):
            quote = character
            output.append(character)
            continue
        if character == "#" and (index == 0 or line[index - 1].isspace()):
            break
        output.append(character)
    return "".join(output)


def _yaml_first_token(text: str) -> tuple[str | None, str]:
    stripped = text.strip()
    if not stripped:
        return None, ""
    parts = stripped.split(None, 1)
    token = parts[0]
    rest = parts[1].strip() if len(parts) > 1 else ""
    return token, rest


def _split_yaml_mapping_pair(text: str, line_number: int) -> tuple[str, str]:
    index = _yaml_mapping_colon_index(text)
    if index is None:
        raise YamlParseError("expected YAML mapping pair", line_number=line_number)
    key_text = text[:index].strip()
    if not key_text:
        raise YamlParseError("YAML mapping key is empty", line_number=line_number)
    key = _unquote_yaml_scalar(key_text)
    if not isinstance(key, str):
        key = str(key)
    return key, text[index + 1 :].strip()


def _looks_like_yaml_mapping_pair(text: str) -> bool:
    return _yaml_mapping_colon_index(text) is not None


def _yaml_mapping_colon_index(text: str) -> int | None:
    quote: str | None = None
    escaped = False
    for index, character in enumerate(text):
        if quote is not None:
            if escaped:
                escaped = False
            elif character == "\\" and quote == '"':
                escaped = True
            elif character == quote:
                quote = None
            continue
        if character in ("'", '"'):
            quote = character
            continue
        if character == ":":
            next_character = text[index + 1] if index + 1 < len(text) else ""
            if not next_character or next_character.isspace():
                return index
    return None


def _split_yaml_inline_items(text: str, line_number: int) -> tuple[str, ...]:
    items: list[str] = []
    start = 0
    quote: str | None = None
    escaped = False
    depth = 0
    for index, character in enumerate(text):
        if quote is not None:
            if escaped:
                escaped = False
            elif character == "\\" and quote == '"':
                escaped = True
            elif character == quote:
                quote = None
            continue
        if character in ("'", '"'):
            quote = character
            continue
        if character in "[{":
            depth += 1
            continue
        if character in "]}":
            depth -= 1
            if depth < 0:
                raise YamlParseError(
                    "malformed YAML inline collection",
                    line_number=line_number,
                )
            continue
        if character == "," and depth == 0:
            item = text[start:index].strip()
            if item:
                items.append(item)
            start = index + 1
    tail = text[start:].strip()
    if tail:
        items.append(tail)
    return tuple(items)


def _parse_yaml_plain_scalar(text: str) -> Any:
    unquoted = _unquote_yaml_scalar(text)
    if unquoted != text:
        return unquoted
    normalized = text.lower()
    if normalized in ("true", "false"):
        return normalized == "true"
    if normalized in ("null", "~"):
        return None
    if re.fullmatch(r"[-+]?[0-9]+", text):
        try:
            return int(text)
        except ValueError:
            return text
    if re.fullmatch(r"[-+]?[0-9]+\.[0-9]+", text):
        try:
            return float(text)
        except ValueError:
            return text
    return text


def _unquote_yaml_scalar(text: str) -> Any:
    stripped = text.strip()
    if (
        len(stripped) >= 2
        and stripped[0] == stripped[-1]
        and stripped[0] in ("'", '"')
    ):
        body = stripped[1:-1]
        if stripped[0] == '"':
            try:
                return bytes(body, "utf-8").decode("unicode_escape")
            except UnicodeDecodeError:
                return body
        return body.replace("''", "'")
    return text
