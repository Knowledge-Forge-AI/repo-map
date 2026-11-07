"""Closed ADR0123 byte projection of one moved product source file.

Python owners change only by token spans: exact ``repomap_kg`` NAME tokens, the
same closed root rewrite inside string literals, and the root package's selected
installed-name constants. Comments, whitespace, newlines and look-alikes stay
byte-identical. Every other product resource passes through unchanged.
"""

from __future__ import annotations

import ast
import io
import tokenize
from types import MappingProxyType

from ci.retained_python_namespace_contract import (
    NEW_ROOT,
    OLD_PREFIX,
    OLD_ROOT,
    NamespaceProjectionError,
    rewrite_namespace_text,
    rewrite_product_path,
)


ROOT_INIT_PATH = f"{OLD_PREFIX}__init__.py"
# Durable legacy spellings: the legacy-module classifier and historical capture matching.
DURABLE_LITERALS = MappingProxyType({
    f"{OLD_PREFIX}service_package/contract.py": OLD_ROOT,
    f"{OLD_PREFIX}storage/sqlite_local/summary_queries.py": f"%{OLD_ROOT}%",
    f"{OLD_PREFIX}storage/sql_summaries_python.py": "OR payload_json->>'path' LIKE '%repomap_kg%')), ",
})
INSTALLED_NAME_LITERALS = MappingProxyType({
    "DISTRIBUTION_NAME": ("repomap-kg", "common-lore-index"),
    "PREFERRED_CLI": ("repomap-kg", "cloe"),
})
_MIDDLE_TYPES = frozenset(
    getattr(tokenize, name) for name in ("FSTRING_MIDDLE", "TSTRING_MIDDLE") if hasattr(tokenize, name)
)
_Edit = tuple[int, int, str]


def _physical_lines(data: bytes) -> int:
    return data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)


def _decode(data: bytes) -> str:
    try:
        encoding, _ = tokenize.detect_encoding(io.BytesIO(data).readline)
    except SyntaxError as error:
        raise NamespaceProjectionError("Python source encoding is invalid") from error
    if encoding != "utf-8":
        raise NamespaceProjectionError("Python source is not plain UTF-8")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise NamespaceProjectionError("Python source is not valid UTF-8") from error
    if "\r" in text.replace("\r\n", ""):
        raise NamespaceProjectionError("Python source has a bare carriage return")
    return text


def _tokens(text: str) -> list[tokenize.TokenInfo]:
    try:
        ast.parse(text)
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (SyntaxError, ValueError, tokenize.TokenError) as error:
        raise NamespaceProjectionError("Python source does not tokenize") from error
    if any(token.type == tokenize.ERRORTOKEN for token in tokens):
        raise NamespaceProjectionError("Python source does not tokenize")
    return tokens


def _line_starts(text: str) -> list[int]:
    starts = [0]
    for line in io.StringIO(text).readlines():
        starts.append(starts[-1] + len(line))
    return starts


def _span(token: tokenize.TokenInfo, starts: list[int]) -> tuple[int, int]:
    return starts[token.start[0] - 1] + token.start[1], starts[token.end[0] - 1] + token.end[1]


def _literal(source: str) -> str | bytes:
    try:
        value = ast.literal_eval(source)
    except (SyntaxError, ValueError) as error:
        raise NamespaceProjectionError("string token is not a closed literal") from error
    if not isinstance(value, (str, bytes)):
        raise NamespaceProjectionError("string token is not a closed literal")
    return value


def _rewrite_value(value: str | bytes) -> str | bytes:
    if isinstance(value, bytes):
        return rewrite_namespace_text(value.decode("latin-1")).encode("latin-1")
    return rewrite_namespace_text(value)


def _installed_name_edits(tokens: list[tokenize.TokenInfo], starts: list[int], text: str) -> dict[int, _Edit]:
    found: dict[str, int] = {}
    for index, token in enumerate(tokens[:-3]):
        if token.type != tokenize.NAME or token.string not in INSTALLED_NAME_LITERALS or token.start[1] != 0:
            continue
        operator, literal, terminator = tokens[index + 1:index + 4]
        if (
            operator.string != "="
            or literal.type != tokenize.STRING
            or terminator.type not in {tokenize.NEWLINE, tokenize.COMMENT}
            or token.string in found
        ):
            raise NamespaceProjectionError("installed-name constant is not one closed literal assignment")
        found[token.string] = index + 2
    if set(found) != set(INSTALLED_NAME_LITERALS):
        raise NamespaceProjectionError("installed-name constants are incomplete")
    edits: dict[int, _Edit] = {}
    for name, index in found.items():
        old, new = INSTALLED_NAME_LITERALS[name]
        start, end = _span(tokens[index], starts)
        source = text[start:end]
        replacement = source.replace(old, new)
        if _literal(source) != old or source.count(old) != 1 or _literal(replacement) != new:
            raise NamespaceProjectionError("installed-name constant has an unexpected value")
        edits[index] = (start, end, replacement)
    return edits


def _string_edit(source: str, start: int, end: int) -> list[_Edit]:
    replacement = rewrite_namespace_text(source)
    if _literal(replacement) != _rewrite_value(_literal(source)):
        raise NamespaceProjectionError("string escape hides a namespace spelling")
    return [] if replacement == source else [(start, end, replacement)]


def _middle_edit(token: tokenize.TokenInfo, source: str, start: int, end: int) -> list[_Edit]:
    # Exact decoded-literal equality below validates escapes and doubled braces.
    replacement = rewrite_namespace_text(source)
    return [] if replacement == source else [(start, end, replacement)]


def _formatted_literals(text: str) -> tuple[str, ...]:
    return tuple(piece.value for node in ast.walk(ast.parse(text)) if isinstance(node, ast.JoinedStr)
                 for piece in node.values if isinstance(piece, ast.Constant) and isinstance(piece.value, str))


def _project_formatted_literal(path: str, value: str) -> str:
    durable = DURABLE_LITERALS.get(path)
    if durable is not None:
        # Adjacent ordinary SQL tokens can be folded into one JoinedStr constant.
        return durable.join(rewrite_namespace_text(part) for part in value.split(durable))
    return rewrite_namespace_text(value)


def _token_edits(path: str, tokens: list[tokenize.TokenInfo], starts: list[int], text: str) -> list[_Edit]:
    installed = _installed_name_edits(tokens, starts, text) if path == ROOT_INIT_PATH else {}
    durable = DURABLE_LITERALS.get(path)
    kept = 0
    edits = list(installed.values())
    for index, token in enumerate(tokens):
        start, end = _span(token, starts)
        source = text[start:end]
        if token.type == tokenize.NAME:
            if token.string == NEW_ROOT:
                raise NamespaceProjectionError("predecessor source already names the successor root")
            if token.string == OLD_ROOT:
                edits.append((start, end, NEW_ROOT))
        elif token.type == tokenize.STRING and index not in installed:
            if durable is not None and _literal(source) == durable:
                kept += 1
                continue
            edits.extend(_string_edit(source, start, end))
        elif token.type in _MIDDLE_TYPES:
            edits.extend(_middle_edit(token, source, start, end))
    if durable is not None and kept != 1:
        raise NamespaceProjectionError("durable legacy literal is missing or ambiguous")
    return edits


def project_source_bytes(path: str, data: bytes) -> bytes:
    """Return the exact successor bytes for one predecessor product file."""
    rewrite_product_path(path)
    if not isinstance(data, bytes):
        raise NamespaceProjectionError("source payload is not bytes")
    if not path.endswith(".py"):
        return data
    text = _decode(data)
    tokens = _tokens(text)
    starts = _line_starts(text)
    projected = text
    previous = len(text) + 1
    for start, end, replacement in sorted(_token_edits(path, tokens, starts, text), reverse=True):
        if end > previous:
            raise NamespaceProjectionError("namespace token edits overlap")
        projected = projected[:start] + replacement + projected[end:]
        previous = start
    result = projected.encode("utf-8")
    if _physical_lines(result) != _physical_lines(data):
        raise NamespaceProjectionError("namespace projection changed the physical line count")
    _tokens(projected)
    expected_literals = tuple(_project_formatted_literal(path, value) for value in _formatted_literals(text))
    if _formatted_literals(projected) != expected_literals:
        raise NamespaceProjectionError("formatted string escape hides a namespace spelling")
    return result


__all__ = [
    "DURABLE_LITERALS",
    "INSTALLED_NAME_LITERALS",
    "ROOT_INIT_PATH",
    "project_source_bytes",
]
