"""Shared Python extractor constants and AST helpers."""

from __future__ import annotations

import ast
import re


EXTRACTOR_NAME = "repo-python"
SLUG_PATTERN = re.compile(r"[^0-9A-Za-z_.]+")


def end_line(node: ast.AST) -> int:
    lineno = getattr(node, "end_lineno", None)
    if isinstance(lineno, int) and lineno > 0:
        return lineno
    return node.lineno


def slug(value: str) -> str:
    return SLUG_PATTERN.sub("-", value).strip("-") or "unknown"
