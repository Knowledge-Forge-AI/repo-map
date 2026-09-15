"""PowerShell module manifest tokenization and value parsing helpers."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


@dataclass(frozen=True)
class ManifestToken:
    kind: str
    text: str
    line: int


@dataclass(frozen=True)
class ManifestValue:
    kind: str
    value: Any = None
    items: tuple["ManifestValue", ...] = ()
    entries: tuple[tuple[str, "ManifestValue"], ...] = ()
    start_line: int = 0
    end_line: int = 0
    unknown_reason: str | None = None


def _parse_manifest_document(content: str) -> ManifestValue | None:
    tokens = _manifest_tokens(content)
    for index, token in enumerate(tokens):
        if token.kind == "hashtable_start":
            value, _ = _parse_manifest_hashtable(tokens, index)
            return value
    return None


def _manifest_tokens(content: str) -> tuple[ManifestToken, ...]:
    tokens: list[ManifestToken] = []
    line = 1
    index = 0
    while index < len(content):
        char = content[index]
        if char == "\n":
            line += 1
            index += 1
            continue
        if char.isspace():
            index += 1
            continue
        if char == "#":
            while index < len(content) and content[index] != "\n":
                index += 1
            continue
        if content.startswith("@{", index):
            tokens.append(ManifestToken("hashtable_start", "@{", line))
            index += 2
            continue
        if content.startswith("@(", index):
            tokens.append(ManifestToken("array_start", "@(", line))
            index += 2
            continue
        if char in "{}()=;,":
            kind = {
                "{": "lbrace",
                "}": "rbrace",
                "(": "lparen",
                ")": "rparen",
                "=": "equals",
                ";": "separator",
                ",": "separator",
            }[char]
            tokens.append(ManifestToken(kind, char, line))
            index += 1
            continue
        if char in {"'", '"'}:
            token, index, line = _manifest_string_token(content, index, line)
            tokens.append(token)
            continue
        start = index
        while index < len(content):
            if content[index].isspace() or content[index] in "{}()=;,#":
                break
            index += 1
        text = content[start:index]
        normalized = text.lower()
        if normalized in {"$true", "$false"}:
            tokens.append(ManifestToken("bool", normalized, line))
        elif normalized == "$null":
            tokens.append(ManifestToken("null", normalized, line))
        elif re.fullmatch(r"-?[0-9]+", text):
            tokens.append(ManifestToken("int", text, line))
        elif text.startswith("$"):
            tokens.append(ManifestToken("variable", text, line))
        else:
            tokens.append(ManifestToken("identifier", text, line))
    return tuple(tokens)


def _manifest_string_token(
    content: str,
    start: int,
    line: int,
) -> tuple[ManifestToken, int, int]:
    quote = content[start]
    index = start + 1
    value_parts: list[str] = []
    while index < len(content):
        char = content[index]
        if char == "\n":
            line += 1
        if char == quote:
            if quote == "'" and index + 1 < len(content) and content[index + 1] == "'":
                value_parts.append("'")
                index += 2
                continue
            text = "".join(value_parts)
            kind = "string"
            if quote == '"' and ("$" in text or "`" in text):
                kind = "unknown_string"
            return ManifestToken(kind, text, line), index + 1, line
        value_parts.append(char)
        index += 1
    return ManifestToken("unknown_string", "".join(value_parts), line), index, line


def _parse_manifest_hashtable(
    tokens: tuple[ManifestToken, ...],
    start_index: int,
) -> tuple[ManifestValue, int]:
    start_line = tokens[start_index].line
    entries: list[tuple[str, ManifestValue]] = []
    index = start_index + 1
    end_line = start_line
    while index < len(tokens):
        token = tokens[index]
        end_line = token.line
        if token.kind == "rbrace":
            return (
                ManifestValue(
                    "hashtable",
                    entries=tuple(entries),
                    start_line=start_line,
                    end_line=end_line,
                ),
                index + 1,
            )
        if token.kind == "separator":
            index += 1
            continue
        if token.kind not in {"identifier", "string"}:
            index += 1
            continue
        key = token.text
        if index + 1 >= len(tokens) or tokens[index + 1].kind != "equals":
            index += 1
            continue
        value, index = _parse_manifest_value(tokens, index + 2)
        entries.append((key, value))
    return (
        ManifestValue(
            "hashtable",
            entries=tuple(entries),
            start_line=start_line,
            end_line=end_line,
        ),
        index,
    )


def _parse_manifest_array(
    tokens: tuple[ManifestToken, ...],
    start_index: int,
) -> tuple[ManifestValue, int]:
    start_line = tokens[start_index].line
    items: list[ManifestValue] = []
    index = start_index + 1
    end_line = start_line
    while index < len(tokens):
        token = tokens[index]
        end_line = token.line
        if token.kind == "rparen":
            return (
                ManifestValue(
                    "array",
                    items=tuple(items),
                    start_line=start_line,
                    end_line=end_line,
                ),
                index + 1,
            )
        if token.kind == "separator":
            index += 1
            continue
        value, index = _parse_manifest_value(tokens, index)
        items.append(value)
    return (
        ManifestValue(
            "array",
            items=tuple(items),
            start_line=start_line,
            end_line=end_line,
        ),
        index,
    )


def _parse_manifest_value(
    tokens: tuple[ManifestToken, ...],
    index: int,
) -> tuple[ManifestValue, int]:
    if index >= len(tokens):
        return ManifestValue("unknown", unknown_reason="missing-value"), index
    token = tokens[index]
    if token.kind == "string":
        return (
            ManifestValue(
                "string",
                value=token.text,
                start_line=token.line,
                end_line=token.line,
            ),
            index + 1,
        )
    if token.kind == "unknown_string":
        return (
            ManifestValue(
                "unknown",
                start_line=token.line,
                end_line=token.line,
                unknown_reason="dynamic-string",
            ),
            index + 1,
        )
    if token.kind == "bool":
        return (
            ManifestValue(
                "bool",
                value=token.text == "$true",
                start_line=token.line,
                end_line=token.line,
            ),
            index + 1,
        )
    if token.kind == "int":
        return (
            ManifestValue(
                "int",
                value=int(token.text),
                start_line=token.line,
                end_line=token.line,
            ),
            index + 1,
        )
    if token.kind == "null":
        return (
            ManifestValue(
                "null",
                value=None,
                start_line=token.line,
                end_line=token.line,
            ),
            index + 1,
        )
    if token.kind == "array_start":
        return _parse_manifest_array(tokens, index)
    if token.kind == "hashtable_start":
        return _parse_manifest_hashtable(tokens, index)
    reason = "unsupported-manifest-value"
    if token.kind == "variable":
        reason = "dynamic-variable"
    if token.kind == "lparen":
        next_index = _skip_parenthesized_manifest_expression(tokens, index)
    else:
        next_index = index + 1
    return (
        ManifestValue(
            "unknown",
            start_line=token.line,
            end_line=tokens[next_index - 1].line if next_index > index else token.line,
            unknown_reason=reason,
        ),
        next_index,
    )


def _skip_parenthesized_manifest_expression(
    tokens: tuple[ManifestToken, ...],
    start_index: int,
) -> int:
    depth = 0
    index = start_index
    while index < len(tokens):
        token = tokens[index]
        if token.kind == "lparen":
            depth += 1
        elif token.kind == "rparen":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return index
