"""Inventory-time kernel pinning for identity-bound safe deletion.

An inventory that records only ``(st_dev, st_ino, st_mode)`` cannot tell an
inventoried object apart from a different object created at the same pathname
afterwards: ext4 reuses a freed inode number immediately, for every deletable
kind, so the replacement presents a byte-identical identity. Holding an open
descriptor keeps the inventoried inode allocated even after its name is
removed, which makes that number unavailable to the replacement and turns the
recorded identity back into a sound discriminator.

A pin narrows the inventory-to-decision window structurally. It does not make
name-based removal atomic: POSIX offers no unlink-by-inode, so a replacement
arriving between the last identity check and the syscall is still removed by
name. Callers must not claim more than the mechanism provides.
"""

from __future__ import annotations

import errno
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from repomap_test_support.resource_safe_tree_failure import SafeTreeDeleteError


# Kinds the host declines to open are left unpinned rather than refused: Darwin
# cannot open an AF_UNIX socket by any flag combination, and its filesystems
# allocate file IDs monotonically, so the recorded identity stands alone there.
UNPINNABLE_ERRNOS = frozenset(
    {errno.EOPNOTSUPP, errno.ENOTSUP, errno.EPERM, errno.EACCES}
)
# O_PATH pins any kind without read authority; Darwin has no equivalent.
PORTABLE_PIN_FLAGS = (
    os.O_PATH | os.O_NOFOLLOW if hasattr(os, "O_PATH") else None
)


@dataclass
class EntryPin:
    """One open kernel reference holding an inventoried object allocated."""

    descriptor: int | None
    device: int
    inode: int
    mode: int


def pin_run_entry(scratch_root: Path, name: str) -> EntryPin | None:
    """Pin one immediate ``r`` entry through the fixed no-follow ancestry."""
    root_fd = _open_directory(scratch_root)
    runs_fd = None
    try:
        runs_fd = _open_directory("r", parent_fd=root_fd)
        return pin_child(runs_fd, name)
    finally:
        for descriptor in (runs_fd, root_fd):
            if descriptor is not None:
                _close(descriptor)


def pin_child(parent_fd: int, name: str) -> EntryPin | None:
    """Pin one child without following it, identifying it from its handle."""
    flags = PORTABLE_PIN_FLAGS
    if flags is None:
        flags = _kind_pin_flags(_child_mode(parent_fd, name))
    if flags is None:
        return None
    try:
        descriptor = os.open(name, flags, dir_fd=parent_fd)
    except OSError as error:
        if error.errno in UNPINNABLE_ERRNOS:
            return None
        raise SafeTreeDeleteError("run entry pin failed") from error
    try:
        observed = os.fstat(descriptor)
    except OSError as error:
        _close(descriptor)
        raise SafeTreeDeleteError("run entry pin inspection failed") from error
    return EntryPin(
        descriptor, observed.st_dev, observed.st_ino, observed.st_mode
    )


def pinned_identity(pin: EntryPin) -> tuple[int, int, int]:
    """Re-read the pinned object, proving the pin is live at this point."""
    if pin.descriptor is None:
        raise SafeTreeDeleteError("run entry pin is no longer live")
    try:
        observed = os.fstat(pin.descriptor)
    except OSError as error:
        raise SafeTreeDeleteError("run entry pin readback failed") from error
    return observed.st_dev, observed.st_ino, observed.st_mode


def close_pin(pin: EntryPin | None) -> None:
    """Release one pin exactly once; repeat and absent releases are no-ops."""
    if pin is None or pin.descriptor is None:
        return
    descriptor, pin.descriptor = pin.descriptor, None
    _close(descriptor)


def _child_mode(parent_fd: int, name: str) -> int:
    try:
        return os.stat(name, dir_fd=parent_fd, follow_symlinks=False).st_mode
    except OSError as error:
        raise SafeTreeDeleteError("run entry pin stat failed") from error


def _kind_pin_flags(mode: int) -> int | None:
    """Choose Darwin pin flags.

    Every kind carries ``O_NONBLOCK``: the mode is read before the open, so a
    same-path kind swap in that window must never block the opener.
    """
    if stat.S_ISDIR(mode):
        return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK
    if stat.S_ISLNK(mode):
        symlink_flag = getattr(os, "O_SYMLINK", None)
        if symlink_flag is None:
            return None
        return symlink_flag | os.O_NONBLOCK
    if stat.S_ISFIFO(mode):
        return os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW
    if stat.S_ISREG(mode):
        return os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    return None


def _open_directory(path: Path | str, *, parent_fd: int | None = None) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        return os.open(path, flags, dir_fd=parent_fd)
    except OSError as error:
        raise SafeTreeDeleteError("safe pin directory open failed") from error


def _close(descriptor: int) -> None:
    try:
        os.close(descriptor)
    except OSError:
        pass


__all__ = [
    "PORTABLE_PIN_FLAGS",
    "UNPINNABLE_ERRNOS",
    "EntryPin",
    "close_pin",
    "pin_child",
    "pin_run_entry",
    "pinned_identity",
]
