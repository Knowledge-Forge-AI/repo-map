"""Shared data types and descriptor-relative primitives for safe deletion."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from repomap_test_support.resource_safe_tree_failure import (
    SafeTreeDeleteError,
    SafeTreeDeleteFailure,
    SafeTreeDeleteUnavailable,
)
from repomap_test_support.resource_validation import nonnegative_int


@dataclass(frozen=True)
class SafeTreeDeleteResult:
    completed: bool
    removed_allocated_bytes: int
    removed_inode_count: int
    stop_reason: str


@dataclass(frozen=True)
class SafeTreeInspection:
    allocated_bytes: int
    inode_count: int


@dataclass(frozen=True)
class RunEntryInspection:
    device: int
    inode: int
    mode: int
    allocated_bytes: int
    inode_count: int


@dataclass
class Progress:
    allocated_bytes: int = 0
    inode_count: int = 0


def validated_scratch_root(path: Path) -> Path:
    root = Path(path)
    if not root.is_absolute():
        raise SafeTreeDeleteError("selected scratch root must be absolute")
    try:
        metadata = root.stat(follow_symlinks=False)
        resolved = root.resolve(strict=True)
    except OSError as error:
        raise SafeTreeDeleteError("selected scratch root is unavailable") from error
    if (
        root.is_symlink()
        or resolved != root
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
    ):
        raise SafeTreeDeleteError("selected scratch root identity is unsafe")
    return root


def open_directory(path: Path) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        return os.open(path, flags)
    except OSError as error:
        raise SafeTreeDeleteError("safe directory open failed") from error


def open_child_directory(parent_fd: int, name: str) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        return os.open(name, flags, dir_fd=parent_fd)
    except OSError as error:
        raise SafeTreeDeleteError("safe child directory open failed") from error


def require_host_contract() -> None:
    required = (os.open, os.stat, os.unlink, os.rmdir)
    if not hasattr(os, "O_DIRECTORY") or not hasattr(os, "O_NOFOLLOW"):
        raise SafeTreeDeleteUnavailable("no-follow directory opens are unavailable")
    if any(operation not in os.supports_dir_fd for operation in required):
        raise SafeTreeDeleteUnavailable("descriptor-relative deletion is unavailable")


def allocated_bytes(metadata: os.stat_result) -> int:
    return nonnegative_int(getattr(metadata, "st_blocks", 0), "allocated blocks") * 512


def entry_kind(mode: int) -> str:
    if stat.S_ISREG(mode):
        return "regular_file"
    if stat.S_ISLNK(mode):
        return "symlink"
    if stat.S_ISFIFO(mode):
        return "fifo"
    return "socket"


def require_deletable_kind(mode: int) -> None:
    if stat.S_ISBLK(mode) or stat.S_ISCHR(mode):
        raise SafeTreeDeleteError("unsupported special entry refused")
    if not (
        stat.S_ISREG(mode)
        or stat.S_ISLNK(mode)
        or stat.S_ISFIFO(mode)
        or stat.S_ISSOCK(mode)
    ):
        raise SafeTreeDeleteError("unclassifiable run entry refused")


def validated_entry_name(name: str) -> str:
    if (
        type(name) is not str
        or not name
        or name in {".", ".."}
        or "/" in name
        or "\0" in name
    ):
        raise SafeTreeDeleteError("run entry name is unsafe")
    return name


def list_directory(descriptor: int) -> list[str]:
    return os.listdir(descriptor)


def stat_entry(parent_fd: int, name: str) -> os.stat_result:
    return os.stat(name, dir_fd=parent_fd, follow_symlinks=False)


def fstat(descriptor: int) -> os.stat_result:
    return os.fstat(descriptor)


def unlink_entry(parent_fd: int, name: str) -> None:
    os.unlink(name, dir_fd=parent_fd)


def rmdir_entry(parent_fd: int, name: str) -> None:
    os.rmdir(name, dir_fd=parent_fd)


def fsync_descriptor(descriptor: int) -> None:
    os.fsync(descriptor)


def close_descriptor(descriptor: int) -> None:
    os.close(descriptor)


def known_category(error: BaseException, category: str) -> str:
    return category if isinstance(error, Exception) else "interrupted"


def unexpected_category(error: BaseException) -> str:
    return known_category(error, "unexpected_safe_tree_error")


def raise_delete_failure(
    category: str,
    progress: Progress,
    cause: BaseException | None = None,
) -> NoReturn:
    failure = SafeTreeDeleteFailure(
        removed_allocated_bytes=progress.allocated_bytes,
        removed_inode_count=progress.inode_count,
        failure_category=category,
    )
    if cause is None:
        raise failure
    raise failure from cause
