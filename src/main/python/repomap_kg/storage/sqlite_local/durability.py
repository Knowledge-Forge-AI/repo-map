"""Filesystem durability for SQLite Local persistence (POSIX hosts only).

REPOMAP-PRODUCT3-SQLITE-LOCAL7. A completed regular file is fsynced before it
is published under its final name, and the containing directory is fsynced
after the atomic link, rename or replace that published it. Those syncs are
part of a successful init, backup, restore or retained-record result: a
failure is never suppressed there. It is reported as one of two bounded,
path-free refusals:

* ``local-durability-unavailable``: the host or filesystem cannot provide a
  directory sync (not POSIX, no ``O_DIRECTORY``, or the directory open/sync
  answers ``EINVAL``/``ENOTSUP``/``EOPNOTSUPP``). Equivalent crash durability
  is not claimed.
* ``local-durability-failed``: any other sync error (``EIO``, ``ENOSPC``, ...).
  The preceding writes are not confirmed durable.

The primitive is POSIX ``fsync(2)``. On macOS that is not ``F_FULLFSYNC``, so
a drive write cache may still lose acknowledged writes on power loss; this
matches SQLite's default ``fullfsync=OFF``. The guarantee is ordered writes
and truthful outcomes, not survival of a crash before a sync returns.
"""

from __future__ import annotations

import errno
import os
from pathlib import Path

from repomap_kg.storage.sqlite_local.schema import LocalStoreError

DURABILITY_UNAVAILABLE = "local-durability-unavailable"
DURABILITY_FAILED = "local-durability-failed"
_UNSUPPORTED = frozenset({errno.EINVAL, errno.ENOTSUP, errno.EOPNOTSUPP})


def _supported() -> int:
    """Return ``O_DIRECTORY`` or refuse a host without directory sync semantics."""
    directory_flag = getattr(os, "O_DIRECTORY", None)
    if os.name != "posix" or directory_flag is None:
        raise LocalStoreError(DURABILITY_UNAVAILABLE, "directory sync is not supported")
    return int(directory_flag)


def _refusal(error: OSError, what: str) -> LocalStoreError:
    if error.errno in _UNSUPPORTED:
        return LocalStoreError(DURABILITY_UNAVAILABLE, f"{what} sync is not supported")
    return LocalStoreError(DURABILITY_FAILED, f"{what} sync failed")


def fsync_descriptor(descriptor: int, *, what: str = "file") -> None:
    """Sync one open descriptor; a failure is a bounded refusal."""
    try:
        os.fsync(descriptor)
    except OSError as error:
        raise _refusal(error, what) from None


def fsync_file(path: Path) -> None:
    """Sync a completed regular file's contents before it is published."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as error:
        raise _refusal(error, "file") from None
    try:
        fsync_descriptor(descriptor)
    finally:
        os.close(descriptor)


def fsync_directory(path: Path) -> None:
    """Sync a directory so a link, rename or removal inside it is durable."""
    flags = os.O_RDONLY | _supported() | os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise _refusal(error, "directory") from None
    try:
        fsync_descriptor(descriptor, what="directory")
    finally:
        os.close(descriptor)


def fsync_directory_chain(leaf: Path, ancestors: int) -> None:
    """Sync ``leaf`` and then ``ancestors`` parent levels, nearest first.

    ``leaf`` is resolved first so every synced level is a real directory and a
    symlinked or relative home cannot misdirect the chain.
    """
    current = leaf.resolve()
    for _ in range(ancestors + 1):
        fsync_directory(current)
        current = current.parent


__all__ = (
    "DURABILITY_FAILED",
    "DURABILITY_UNAVAILABLE",
    "fsync_descriptor",
    "fsync_directory",
    "fsync_directory_chain",
    "fsync_file",
)
