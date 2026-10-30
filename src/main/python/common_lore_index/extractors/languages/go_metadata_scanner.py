"""Line-oriented scanning for Go module and workspace directives."""

from __future__ import annotations

import shlex


DirectiveRecord = tuple[str, tuple[str, ...], int, str]


def scan_go_directives(content: str) -> tuple[DirectiveRecord, ...]:
    directives: list[DirectiveRecord] = []
    block: str | None = None
    block_line: int | None = None
    lines = content.splitlines()
    for line_number, raw_line in enumerate(lines, start=1):
        code, separator, comment = raw_line.partition("//")
        stripped = code.strip()
        comment_text = comment.strip() if separator else ""
        if not stripped:
            continue
        if block is not None:
            if stripped == ")":
                block = None
                block_line = None
                continue
            fields = _split_fields(stripped, line_number, directives)
            if fields is not None:
                directives.append((block, fields, line_number, comment_text))
            continue
        fields = _split_fields(stripped, line_number, directives)
        if fields is None:
            continue
        if len(fields) == 2 and fields[1] == "(":
            block = fields[0]
            block_line = line_number
            continue
        directives.append((fields[0], fields[1:], line_number, comment_text))
    if block is not None:
        directives.append(
            (
                "__parse_error__",
                ("unterminated-block", f"unterminated {block} block"),
                block_line or max(1, len(lines)),
                "",
            )
        )
    return tuple(directives)


def _split_fields(
    stripped: str,
    line_number: int,
    directives: list[DirectiveRecord],
) -> tuple[str, ...] | None:
    try:
        return tuple(shlex.split(stripped))
    except ValueError as error:
        directives.append(
            (
                "__parse_error__",
                ("invalid-quoting", str(error)),
                line_number,
                "",
            )
        )
        return None
