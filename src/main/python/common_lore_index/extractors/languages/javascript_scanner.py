"""Scanner utilities for JavaScript extraction."""

from __future__ import annotations

import re


CLASS_RE = re.compile(
    r"""^\s*(?:export\s+)?class\s+(?P<name>[A-Za-z_$][\w$]*)(?:\s+extends\s+(?P<superclass>[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)?))?"""
)
METHOD_RE = re.compile(
    r"""^\s*(?:async\s+)?(?P<name>[A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{?"""
)


def _strip_line_comment(line: str) -> str:
    if "sourceMappingURL=" in line:
        return line
    quote: str | None = None
    escaped = False
    for index, char in enumerate(line):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char in ("'", '"', "`"):
            if quote is None:
                quote = char
            elif quote == char:
                quote = None
            continue
        if char == "/" and quote is None and line[index : index + 2] == "//":
            return line[:index]
    return line


def _is_react_class(superclass: str | None) -> bool:
    return superclass in ("React.Component", "Component")


def _looks_like_non_method(line: str) -> bool:
    return line.startswith(("if ", "for ", "while ", "switch ", "catch ", "function "))


def _update_class_stack(class_stack: list[tuple[str, str, int]], line: str) -> None:
    if not class_stack:
        return
    name, key, depth = class_stack[-1]
    depth += _brace_delta(line)
    if depth <= 0 and "}" in line:
        class_stack.pop()
        return
    class_stack[-1] = (name, key, depth)


def _brace_delta(line: str) -> int:
    return line.count("{") - line.count("}")
