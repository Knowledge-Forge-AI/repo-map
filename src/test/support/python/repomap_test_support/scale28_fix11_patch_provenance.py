from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from pathlib import PurePosixPath
import re
import shlex
from typing import Callable, Iterable


_DIFF_HEADER = "diff --git "
_INDEX_PATTERN = re.compile(
    r"index ([0-9a-f]+)\.\.([0-9a-f]+)(?: ([0-7]{6}))?"
)
_HUNK_PATTERN = re.compile(
    r"@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@(?: .*)?"
)
_FULL_OBJECT_PATTERN = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_BINARY_RECORD_PATTERN = re.compile(r"(?:literal|delta) \d+")


class PatchParseError(ValueError):
    """Raised when a Git patch cannot establish a closed safe manifest."""


class PatchOperation(str, Enum):
    MODIFY = "modify"
    ADD = "add"
    DELETE = "delete"
    RENAME = "rename"
    COPY = "copy"


@dataclass(frozen=True)
class PatchEntry:
    operation: PatchOperation
    old_path: str | None
    new_path: str | None
    old_mode: str | None
    new_mode: str | None
    old_object_id: str | None
    new_object_id: str | None
    binary: bool


@dataclass
class _EntryBuilder:
    diff_old_path: str
    diff_new_path: str
    old_path: str | None = None
    new_path: str | None = None
    old_mode: str | None = None
    new_mode: str | None = None
    index_mode: str | None = None
    old_object_id: str | None = None
    new_object_id: str | None = None
    new_file: bool = False
    deleted_file: bool = False
    rename_from: str | None = None
    rename_to: str | None = None
    copy_from: str | None = None
    copy_to: str | None = None
    binary: bool = False
    has_text_hunk: bool = False


def _strip_diff_prefix(path: str) -> str:
    if path.startswith(("a/", "b/")):
        return path[2:]
    return path


def _marker_path(value: str) -> str | None:
    if value == "/dev/null":
        return None
    return _strip_diff_prefix(shlex.split(value)[0])


def _validate_path(path: str) -> None:
    pure = PurePosixPath(path)
    if pure.is_absolute() or path.startswith("/"):
        raise PatchParseError(f"absolute path rejected: {path!r}")
    if ".." in pure.parts:
        raise PatchParseError(f"path traversal rejected: {path!r}")
    if not path or "\\" in path:
        raise PatchParseError(f"invalid patch path: {path!r}")


def _set_mode(
    builder: _EntryBuilder,
    field: str,
    mode: str,
) -> None:
    current = getattr(builder, field)
    if current is not None and current != mode:
        raise PatchParseError(f"conflicting mode records for {field}")
    setattr(builder, field, mode)


def _consume_hunk(lines: list[str], start: int) -> int:
    match = _HUNK_PATTERN.fullmatch(lines[start])
    if match is None:
        raise PatchParseError("partial text hunk")
    old_remaining = int(match.group(1) or "1")
    new_remaining = int(match.group(2) or "1")
    position = start + 1
    while old_remaining or new_remaining:
        if position >= len(lines):
            raise PatchParseError("partial text hunk")
        line = lines[position]
        if line.startswith("\\ No newline at end of file"):
            position += 1
            continue
        if not line:
            raise PatchParseError("partial text hunk")
        marker = line[0]
        if marker == " ":
            old_remaining -= 1
            new_remaining -= 1
        elif marker == "-":
            old_remaining -= 1
        elif marker == "+":
            new_remaining -= 1
        else:
            raise PatchParseError("partial text hunk")
        if old_remaining < 0 or new_remaining < 0:
            raise PatchParseError("partial text hunk")
        position += 1
    if (
        position < len(lines)
        and lines[position].startswith("\\ No newline at end of file")
    ):
        position += 1
    return position


def _consume_binary_payload(lines: list[str], start: int) -> int:
    position = start
    record_count = 0
    while position < len(lines):
        if not _BINARY_RECORD_PATTERN.fullmatch(lines[position]):
            raise PatchParseError("unexpected patch trailer")
        record_count += 1
        position += 1
        payload_count = 0
        while position < len(lines) and lines[position]:
            if _BINARY_RECORD_PATTERN.fullmatch(lines[position]):
                break
            payload_count += 1
            position += 1
        if payload_count == 0:
            raise PatchParseError("missing binary payload")
        while position < len(lines) and not lines[position]:
            position += 1
    if record_count == 0:
        raise PatchParseError("missing binary payload")
    return position


def _parse_diff_header(line: str) -> _EntryBuilder:
    try:
        parts = shlex.split(line)
    except ValueError as exc:
        raise PatchParseError("invalid diff header quoting") from exc
    if len(parts) != 4 or parts[:2] != ["diff", "--git"]:
        raise PatchParseError("invalid diff header")
    old_path = _strip_diff_prefix(parts[2])
    new_path = _strip_diff_prefix(parts[3])
    _validate_path(old_path)
    _validate_path(new_path)
    return _EntryBuilder(old_path, new_path)


def _parse_entry(lines: list[str]) -> PatchEntry:
    builder = _parse_diff_header(lines[0])
    position = 1
    while position < len(lines):
        line = lines[position]
        if not line:
            position += 1
            continue
        if line.startswith("index "):
            match = _INDEX_PATTERN.fullmatch(line)
            if match is None:
                raise PatchParseError("invalid index record")
            builder.old_object_id, builder.new_object_id = match.group(1, 2)
            builder.index_mode = match.group(3)
        elif line.startswith("old mode "):
            _set_mode(builder, "old_mode", line.removeprefix("old mode "))
        elif line.startswith("new mode "):
            _set_mode(builder, "new_mode", line.removeprefix("new mode "))
        elif line.startswith("new file mode "):
            builder.new_file = True
            _set_mode(
                builder,
                "new_mode",
                line.removeprefix("new file mode "),
            )
        elif line.startswith("deleted file mode "):
            builder.deleted_file = True
            _set_mode(
                builder,
                "old_mode",
                line.removeprefix("deleted file mode "),
            )
        elif line.startswith("rename from "):
            builder.rename_from = line.removeprefix("rename from ")
        elif line.startswith("rename to "):
            builder.rename_to = line.removeprefix("rename to ")
        elif line.startswith("copy from "):
            builder.copy_from = line.removeprefix("copy from ")
        elif line.startswith("copy to "):
            builder.copy_to = line.removeprefix("copy to ")
        elif line.startswith(("similarity index ", "dissimilarity index ")):
            if not line.endswith("%"):
                raise PatchParseError("invalid similarity record")
        elif line.startswith("--- "):
            builder.old_path = _marker_path(line.removeprefix("--- "))
        elif line.startswith("+++ "):
            builder.new_path = _marker_path(line.removeprefix("+++ "))
        elif line == "GIT binary patch":
            builder.binary = True
            position = _consume_binary_payload(lines, position + 1)
            break
        elif line.startswith("@@ "):
            builder.has_text_hunk = True
            position = _consume_hunk(lines, position)
            continue
        elif line.startswith((" ", "+", "-", "\\")):
            raise PatchParseError("partial text hunk")
        else:
            raise PatchParseError("unexpected patch trailer")
        position += 1
    return _finalize_entry(builder)


def _finalize_entry(builder: _EntryBuilder) -> PatchEntry:
    if builder.rename_from is not None or builder.rename_to is not None:
        if builder.rename_from is None or builder.rename_to is None:
            raise PatchParseError("partial rename record")
        operation = PatchOperation.RENAME
        old_path, new_path = builder.rename_from, builder.rename_to
    elif builder.copy_from is not None or builder.copy_to is not None:
        if builder.copy_from is None or builder.copy_to is None:
            raise PatchParseError("partial copy record")
        operation = PatchOperation.COPY
        old_path, new_path = builder.copy_from, builder.copy_to
    elif builder.new_file:
        operation = PatchOperation.ADD
        old_path, new_path = None, builder.new_path or builder.diff_new_path
    elif builder.deleted_file:
        operation = PatchOperation.DELETE
        old_path, new_path = builder.old_path or builder.diff_old_path, None
    else:
        operation = PatchOperation.MODIFY
        old_path = builder.old_path or builder.diff_old_path
        new_path = builder.new_path or builder.diff_new_path
    for path in (old_path, new_path):
        if path is not None:
            _validate_path(path)
    old_mode = builder.old_mode or builder.index_mode
    new_mode = builder.new_mode or builder.index_mode
    if builder.index_mode is not None:
        if old_mode != builder.index_mode or new_mode != builder.index_mode:
            raise PatchParseError("conflicting mode records")
    if builder.new_file:
        old_mode = None
        if builder.old_object_id and set(builder.old_object_id) != {"0"}:
            raise PatchParseError("new file has nonzero old object")
        builder.old_object_id = None
    if builder.deleted_file:
        new_mode = None
        if builder.new_object_id and set(builder.new_object_id) != {"0"}:
            raise PatchParseError("deleted file has nonzero new object")
        builder.new_object_id = None
    content_changed = (
        builder.old_object_id is not None
        and builder.new_object_id is not None
        and builder.old_object_id != builder.new_object_id
    )
    if (
        operation is PatchOperation.MODIFY
        and content_changed
        and not builder.binary
        and not builder.has_text_hunk
    ):
        raise PatchParseError("partial text patch")
    return PatchEntry(
        operation=operation,
        old_path=old_path,
        new_path=new_path,
        old_mode=old_mode,
        new_mode=new_mode,
        old_object_id=builder.old_object_id,
        new_object_id=builder.new_object_id,
        binary=builder.binary,
    )


def parse_git_patch(
    patch: bytes,
    *,
    expected_path_count: int | None = None,
) -> tuple[PatchEntry, ...]:
    """Parse a bounded Git patch into one closed ordered path manifest."""

    try:
        text = patch.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PatchParseError("patch is not UTF-8 Git patch text") from exc
    lines = text.splitlines()
    if not lines or not lines[0].startswith(_DIFF_HEADER):
        raise PatchParseError("partial parse: missing diff header")
    starts = [
        index
        for index, line in enumerate(lines)
        if line.startswith(_DIFF_HEADER)
    ]
    entries = tuple(
        _parse_entry(lines[start:end])
        for start, end in zip(starts, starts[1:] + [len(lines)])
    )
    output_paths: set[str] = set()
    for entry in entries:
        output_path = entry.new_path or entry.old_path
        if output_path in output_paths:
            raise PatchParseError(f"duplicate output path: {output_path}")
        if output_path is None:
            raise PatchParseError("entry has no output path")
        output_paths.add(output_path)
    if expected_path_count is not None and len(entries) != expected_path_count:
        raise PatchParseError(
            f"changed path count {len(entries)} != {expected_path_count}"
        )
    return entries


ObjectResolver = Callable[[str], Iterable[str]]


def _resolve_object(prefix: str | None, resolver: ObjectResolver) -> str | None:
    if prefix is None:
        return None
    matches = tuple(dict.fromkeys(resolver(prefix)))
    if not matches:
        raise PatchParseError(f"unresolved old object: {prefix}")
    if len(matches) != 1:
        raise PatchParseError(f"ambiguous abbreviated object ID: {prefix}")
    (resolved,) = matches
    if _FULL_OBJECT_PATTERN.fullmatch(resolved) is None:
        raise PatchParseError(f"invalid resolved object ID: {resolved}")
    return resolved


def resolve_object_ids(
    entries: Iterable[PatchEntry],
    resolver: ObjectResolver,
) -> tuple[PatchEntry, ...]:
    """Resolve every abbreviated old and new object ID uniquely."""

    return tuple(
        replace(
            entry,
            old_object_id=_resolve_object(entry.old_object_id, resolver),
            new_object_id=_resolve_object(entry.new_object_id, resolver),
        )
        for entry in entries
    )


def resolve_old_object_ids(
    entries: Iterable[PatchEntry],
    resolver: ObjectResolver,
) -> tuple[PatchEntry, ...]:
    """Resolve preimage object IDs before patch-created objects exist."""

    return tuple(
        replace(
            entry,
            old_object_id=_resolve_object(entry.old_object_id, resolver),
        )
        for entry in entries
    )
