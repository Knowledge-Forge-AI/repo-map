"""Selection rule ``rust-pilot-selection-v1`` over the legacy inventory (spec 4).

A selected input is a discovered path ending in ``.rs`` (case-sensitive) that
the parent opens itself as a regular, non-symlink file under the root through
descriptor-relative no-follow IO, whose bytes are stable while read, whose
SHA-256 equals the discovery ``content_hash`` and which is strict UTF-8. The
legacy ``file`` observation is never changed by selection.
"""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from common_lore_index.graph.discovery_records import FileInfo

MAX_INPUT_BYTES = 1_048_576
SELECTION_OUTCOMES = frozenset({"selected", "selection_refused", "resource_bound_exceeded",
                                "source_changed", "input_not_utf8"})
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC


@dataclass(frozen=True)
class SelectionRecord:
    """One ``.rs`` path's selection outcome; bytes are retained only when selected."""

    path: str
    outcome: str
    discovery_sha256: str
    data: bytes | None
    build_script_name: bool

    @property
    def input_sha256(self) -> str | None:
        return None if self.data is None else hashlib.sha256(self.data).hexdigest()


class _Refused(Exception):
    def __init__(self, outcome: str) -> None:
        super().__init__(outcome)
        self.outcome = outcome


def _components(relative: str) -> list[str]:
    parts = relative.split("/")
    if (not relative or relative.startswith("/") or "\\" in relative or "\x00" in relative
            or any(part in ("", ".", "..") for part in parts)):
        raise _Refused("selection_refused")
    return parts


def _identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns


def _read_no_follow(root_fd: int, relative: str) -> bytes:
    parts = _components(relative)
    opened: list[int] = []
    try:
        current = root_fd
        for part in parts[:-1]:
            try:
                current = os.open(part, _DIR_FLAGS, dir_fd=current)
            except OSError:
                raise _Refused("selection_refused") from None
            opened.append(current)
        try:
            fd = os.open(parts[-1], _READ_FLAGS, dir_fd=current)
        except OSError:
            raise _Refused("selection_refused") from None
        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode):
                raise _Refused("selection_refused")
            if before.st_size > MAX_INPUT_BYTES:
                raise _Refused("resource_bound_exceeded")
            chunks: list[bytes] = []
            total = 0
            while total <= MAX_INPUT_BYTES:
                chunk = os.read(fd, min(65_536, MAX_INPUT_BYTES + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
            if total > MAX_INPUT_BYTES:
                raise _Refused("resource_bound_exceeded")
            after = os.fstat(fd)
        finally:
            os.close(fd)
        try:
            entry = os.stat(parts[-1], dir_fd=current, follow_symlinks=False)
        except OSError:
            raise _Refused("source_changed") from None
        if not (_identity(before) == _identity(after) == _identity(entry)) or total != before.st_size:
            raise _Refused("source_changed")
        return b"".join(chunks)
    finally:
        for fd in reversed(opened):
            os.close(fd)


def select_one(root_fd: int, info: FileInfo) -> SelectionRecord:
    build_script = info.path.rsplit("/", 1)[-1] == "build.rs"
    try:
        data = _read_no_follow(root_fd, info.path)
        if hashlib.sha256(data).hexdigest() != info.content_hash:
            raise _Refused("source_changed")
        data.decode("utf-8")
    except _Refused as refusal:
        return SelectionRecord(info.path, refusal.outcome, info.content_hash, None, build_script)
    except UnicodeDecodeError:
        return SelectionRecord(info.path, "input_not_utf8", info.content_hash, None, build_script)
    return SelectionRecord(info.path, "selected", info.content_hash, data, build_script)


def select_inputs(root: Path | str, file_infos: Sequence[FileInfo]) -> tuple[SelectionRecord, ...]:
    """Apply the selection rule to one discovered inventory, one record per ``.rs`` path."""

    root_fd = os.open(os.fspath(root), os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        records: list[SelectionRecord] = []
        seen: set[str] = set()
        for info in file_infos:
            if type(info) is not FileInfo or not info.path.endswith(".rs"):
                continue
            if info.path in seen:
                records.append(SelectionRecord(info.path, "selection_refused", info.content_hash, None,
                                               info.path.rsplit("/", 1)[-1] == "build.rs"))
                continue
            seen.add(info.path)
            records.append(select_one(root_fd, info))
        return tuple(records)
    finally:
        os.close(root_fd)
