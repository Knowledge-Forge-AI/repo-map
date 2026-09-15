"""Atomic same-filesystem directory renames that never replace a destination."""

from __future__ import annotations

import ctypes
import errno
import os
import stat
import sys
from pathlib import Path
from typing import NamedTuple


_LINUX_AT_FDCWD = -100
_DARWIN_RENAME_EXCL = 0x00000004
_LINUX_RENAME_NOREPLACE = 0x00000001


class AtomicRenameError(RuntimeError):
    """The requested exact rename was unsafe or failed."""


class AtomicRenameCollision(AtomicRenameError):
    """The destination already exists and was not replaced."""


class AtomicRenameUnavailable(AtomicRenameError):
    """The host cannot prove atomic no-replace rename semantics."""


class PathIdentity(NamedTuple):
    device: int
    inode: int


class AtomicRenameResult(NamedTuple):
    source_device: int
    source_inode: int
    destination_device: int
    destination_inode: int


def atomic_rename_no_replace(
    source: Path,
    destination: Path,
    *,
    require_private_destination_parent: bool = True,
) -> AtomicRenameResult:
    """Rename one exact private directory without replacing any destination."""
    source = Path(source)
    destination = Path(destination)
    source_identity = _directory_identity(source, "source")
    destination_parent = _directory_identity(
        destination.parent,
        "destination parent",
        require_private=require_private_destination_parent,
    )
    if source_identity.device != destination_parent.device:
        raise AtomicRenameError("atomic rename would cross filesystems")
    _platform_rename_no_replace(source, destination)
    if source.exists() or source.is_symlink():
        raise AtomicRenameError("atomic rename source remains after mutation")
    destination_identity = _directory_identity(destination, "destination")
    if destination_identity != source_identity:
        raise AtomicRenameError("atomic rename identity readback failed")
    return AtomicRenameResult(
        source_identity.device,
        source_identity.inode,
        destination_identity.device,
        destination_identity.inode,
    )


def _directory_identity(
    path: Path,
    label: str,
    *,
    require_private: bool = False,
) -> PathIdentity:
    identity = _path_identity(path)
    metadata = os.lstat(path)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise AtomicRenameError(f"atomic rename {label} is not an exact directory")
    if require_private and metadata.st_mode & 0o077:
        raise AtomicRenameError("atomic rename destination parent is not private")
    return identity


def _path_identity(path: Path) -> PathIdentity:
    metadata = os.lstat(path)
    return PathIdentity(metadata.st_dev, metadata.st_ino)


def _platform_rename_no_replace(source: Path, destination: Path) -> None:
    if sys.platform == "darwin":
        result = _darwin_rename_no_replace(source, destination)
    elif sys.platform.startswith("linux"):
        result = _linux_rename_no_replace(source, destination)
    else:
        raise AtomicRenameUnavailable("atomic no-replace rename is unsupported")
    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
        raise AtomicRenameCollision("atomic rename destination already exists")
    if error_number == errno.EXDEV:
        raise AtomicRenameError("atomic rename would cross filesystems")
    if error_number in {errno.ENOSYS, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EINVAL}:
        raise AtomicRenameUnavailable("atomic no-replace rename is unsupported")
    raise AtomicRenameError(f"atomic no-replace rename failed with errno {error_number}")


def _darwin_rename_no_replace(source: Path, destination: Path) -> int:
    library = ctypes.CDLL(None, use_errno=True)
    try:
        rename = library.renamex_np
    except AttributeError as error:
        raise AtomicRenameUnavailable("renamex_np is unavailable") from error
    rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    return rename(os.fsencode(source), os.fsencode(destination), _DARWIN_RENAME_EXCL)


def _linux_rename_no_replace(source: Path, destination: Path) -> int:
    library = ctypes.CDLL(None, use_errno=True)
    try:
        rename = library.renameat2
    except AttributeError as error:
        raise AtomicRenameUnavailable("renameat2 is unavailable") from error
    rename.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    rename.restype = ctypes.c_int
    return rename(
        _LINUX_AT_FDCWD,
        os.fsencode(source),
        _LINUX_AT_FDCWD,
        os.fsencode(destination),
        _LINUX_RENAME_NOREPLACE,
    )


__all__ = [
    "AtomicRenameCollision",
    "AtomicRenameError",
    "AtomicRenameResult",
    "AtomicRenameUnavailable",
    "atomic_rename_no_replace",
]
