"""Conservative JSONC normalization helpers for config extraction."""

from __future__ import annotations


class JsoncNormalizationError(ValueError):
    """Raised when conservative JSONC normalization cannot safely continue."""


def normalize_jsonc(content: str) -> str:
    without_comments = _strip_jsonc_comments(content)
    return _strip_jsonc_trailing_commas(without_comments)


def _strip_jsonc_comments(content: str) -> str:
    output: list[str] = []
    index = 0
    in_string = False
    escaped = False
    while index < len(content):
        character = content[index]
        next_character = content[index + 1] if index + 1 < len(content) else ""
        if in_string:
            output.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            index += 1
            continue
        if character == '"':
            in_string = True
            output.append(character)
            index += 1
            continue
        if character == "/" and next_character == "/":
            output.extend((" ", " "))
            index += 2
            while index < len(content) and content[index] not in "\r\n":
                output.append(" ")
                index += 1
            continue
        if character == "/" and next_character == "*":
            output.extend((" ", " "))
            index += 2
            closed = False
            while index < len(content):
                if content[index] == "*" and index + 1 < len(content) and content[index + 1] == "/":
                    output.extend((" ", " "))
                    index += 2
                    closed = True
                    break
                output.append("\n" if content[index] in "\r\n" else " ")
                index += 1
            if not closed:
                raise JsoncNormalizationError("unterminated block comment")
            continue
        output.append(character)
        index += 1
    if in_string:
        raise JsoncNormalizationError("unterminated string")
    return "".join(output)


def _strip_jsonc_trailing_commas(content: str) -> str:
    output: list[str] = []
    index = 0
    in_string = False
    escaped = False
    while index < len(content):
        character = content[index]
        if in_string:
            output.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            index += 1
            continue
        if character == '"':
            in_string = True
            output.append(character)
            index += 1
            continue
        if character == ",":
            lookahead = index + 1
            while lookahead < len(content) and content[lookahead].isspace():
                lookahead += 1
            if lookahead < len(content) and content[lookahead] in "}]":
                index += 1
                continue
        output.append(character)
        index += 1
    return "".join(output)
