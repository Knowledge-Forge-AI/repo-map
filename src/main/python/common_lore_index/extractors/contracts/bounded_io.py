"""Bounded no-follow, descriptor-relative regular-file IO.

Callers own a directory descriptor and pass fixed single-component names.
Writes use exclusive creation and finish with a stable-stat readback proof.
Reads refuse symlinks, non-regular files, extra links, oversized data and
concurrent mutation. Cleanup removes only the exact inode this module created;
an entry that no longer matches it is reported, never deleted.

Directories must be owned by the effective user and inaccessible to group or
other users. The owner and privileged host processes are trusted: check then
unlink is not atomic against a hostile process with that same authority.
"""

from __future__ import annotations

import errno
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from common_lore_index.extractors.contracts.vocabulary import ContractError

NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
HARD_MAX_BYTES = 1_048_576
_READ_CHUNK = 65_536
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_CREATE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC


class BoundedIOError(ContractError):
    """Categorical filesystem refusal; the message is the closed code only."""


@dataclass(frozen=True)
class FileIdentity:
    """Stable identity of one regular file observed through its descriptor."""

    device: int
    inode: int
    size: int
    modified_ns: int
    changed_ns: int
    links: int

    @classmethod
    def from_stat(cls, value: os.stat_result) -> FileIdentity:
        return cls(value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns,
                   value.st_ctime_ns, value.st_nlink)

    def same_inode(self, value: os.stat_result) -> bool:
        return (self.device, self.inode) == (value.st_dev, value.st_ino)


def require_name(name: object) -> str:
    """Validate one fixed path component: no separators, dots or traversal."""

    if not isinstance(name, str) or type(name) is not str:
        raise BoundedIOError("invalid_name")
    if NAME_PATTERN.fullmatch(name) is None or ".." in name:
        raise BoundedIOError("invalid_name")
    return name


def _require_limit(max_bytes: object) -> int:
    if not isinstance(max_bytes, int) or type(max_bytes) is not int:
        raise BoundedIOError("invalid_limit")
    if not 0 < max_bytes <= HARD_MAX_BYTES:
        raise BoundedIOError("invalid_limit")
    return max_bytes


def _open_error(error: OSError) -> BoundedIOError:
    if error.errno == errno.EEXIST:
        return BoundedIOError("target_exists")
    if error.errno in (errno.ELOOP, errno.EMLINK):
        return BoundedIOError("symlink_refused")
    if error.errno == errno.ENOENT:
        return BoundedIOError("missing")
    if error.errno == errno.ENOTDIR:
        return BoundedIOError("not_directory")
    return BoundedIOError("open_failed")


def _directory_error(error: OSError, target: str, dir_fd: int | None) -> BoundedIOError:
    """Classify a refused directory open the same way on Linux and macOS.

    With ``O_DIRECTORY|O_NOFOLLOW`` Linux reports a final symlink as ``ENOTDIR``
    while macOS reports ``ELOOP``; a no-follow ``lstat`` keeps one code.
    """

    if error.errno == errno.ENOTDIR:
        try:
            mode = os.stat(target, dir_fd=dir_fd, follow_symlinks=False).st_mode
        except OSError:
            mode = 0
        if stat.S_ISLNK(mode):
            return BoundedIOError("symlink_refused")
    return _open_error(error)


def open_directory(path: Path | str) -> int:
    """Open an existing private owned directory without following its symlink."""

    target = os.fspath(path)
    try:
        fd = os.open(target, _DIRECTORY_FLAGS)
    except OSError as error:
        raise _directory_error(error, target, None) from None
    return _validated_directory(fd)


def _require_private_directory(dir_fd: int) -> None:
    if type(dir_fd) is not int or dir_fd < 0:
        raise BoundedIOError("unsafe_directory")
    try:
        current = os.fstat(dir_fd)
    except OSError:
        raise BoundedIOError("unsafe_directory") from None
    if (not stat.S_ISDIR(current.st_mode) or current.st_uid != os.geteuid()
            or stat.S_IMODE(current.st_mode) & 0o077):
        raise BoundedIOError("unsafe_directory")


def _validated_directory(fd: int) -> int:
    try:
        _require_private_directory(fd)
    except BaseException:
        os.close(fd)
        raise
    return fd


def open_child_directory(dir_fd: int, name: str) -> int:
    """Open one existing child directory relative to ``dir_fd`` without following."""

    _require_private_directory(dir_fd)
    child = require_name(name)
    try:
        fd = os.open(child, _DIRECTORY_FLAGS, dir_fd=dir_fd)
    except OSError as error:
        raise _directory_error(error, child, dir_fd) from None
    return _validated_directory(fd)


def read_regular_file(dir_fd: int, name: str, *, max_bytes: int) -> bytes:
    """Read one bounded regular file and prove it was stable while read."""

    _require_private_directory(dir_fd)
    limit = _require_limit(max_bytes)
    try:
        fd = os.open(require_name(name), _READ_FLAGS, dir_fd=dir_fd)
    except OSError as error:
        raise _open_error(error) from None
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise BoundedIOError("not_regular")
        if before.st_nlink != 1:
            raise BoundedIOError("linked_file")
        if before.st_size > limit:
            raise BoundedIOError("oversized")
        chunks: list[bytes] = []
        total = 0
        while total <= limit:
            chunk = os.read(fd, min(_READ_CHUNK, limit + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        if total > limit:
            raise BoundedIOError("oversized")
        identity = FileIdentity.from_stat(before)
        if FileIdentity.from_stat(os.fstat(fd)) != identity or total != identity.size:
            raise BoundedIOError("mutated")
    finally:
        os.close(fd)
    _require_entry(dir_fd, name, identity)
    return b"".join(chunks)


def _require_entry(dir_fd: int, name: str, identity: FileIdentity) -> None:
    try:
        current = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        raise BoundedIOError("substituted") from None
    if FileIdentity.from_stat(current) != identity:
        raise BoundedIOError("substituted")


def write_new_regular_file(
    dir_fd: int, name: str, data: bytes, *, max_bytes: int
) -> FileIdentity:
    """Exclusively create, write, sync and read back one bounded regular file.

    On any failure after creation the exact created inode is removed. If the
    directory entry no longer names that inode, nothing is deleted and the
    refusal code is ``cleanup_incomplete``.
    """

    _require_private_directory(dir_fd)
    limit = _require_limit(max_bytes)
    name = require_name(name)
    if type(data) is not bytes:
        raise BoundedIOError("invalid_bytes")
    if len(data) > limit:
        raise BoundedIOError("oversized")
    try:
        fd = os.open(name, _CREATE_FLAGS, 0o600, dir_fd=dir_fd)
    except OSError as error:
        raise _open_error(error) from None
    try:
        created = os.fstat(fd)
    except OSError:
        os.close(fd)  # the created inode cannot be identified, so it is not removed
        raise BoundedIOError("cleanup_incomplete") from None
    try:
        _write_all(fd, data, created)
    except BaseException as error:
        os.close(fd)
        _cleanup_or_raise(dir_fd, name, created, error)
        raise
    os.close(fd)
    try:
        if read_regular_file(dir_fd, name, max_bytes=limit) != data:
            raise BoundedIOError("readback_mismatch")
        current = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    except BaseException as error:
        _cleanup_or_raise(dir_fd, name, created, error)
        raise
    if not (stat.S_ISREG(current.st_mode) and FileIdentity.from_stat(created).same_inode(current)):
        substituted = BoundedIOError("substituted")
        _cleanup_or_raise(dir_fd, name, created, substituted)
        raise substituted
    return FileIdentity.from_stat(current)


def _write_all(fd: int, data: bytes, created: os.stat_result) -> None:
    if not stat.S_ISREG(created.st_mode) or created.st_nlink != 1:
        raise BoundedIOError("not_regular")
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise BoundedIOError("short_write")
        view = view[written:]
    os.fsync(fd)
    after = os.fstat(fd)
    if not FileIdentity.from_stat(created).same_inode(after) or after.st_size != len(data):
        raise BoundedIOError("mutated")


def remove_owned_file(dir_fd: int, name: str, identity: FileIdentity) -> None:
    """Remove ``name`` only while it still names the exact recorded inode."""

    _require_private_directory(dir_fd)
    name = require_name(name)
    try:
        current = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        raise BoundedIOError("cleanup_incomplete") from None
    if (identity.device, identity.inode) != (current.st_dev, current.st_ino):
        raise BoundedIOError("cleanup_incomplete")
    try:
        os.unlink(name, dir_fd=dir_fd)
    except OSError:
        raise BoundedIOError("cleanup_incomplete") from None


def _cleanup_or_raise(
    dir_fd: int, name: str, created: os.stat_result, cause: BaseException
) -> None:
    try:
        remove_owned_file(dir_fd, name, FileIdentity.from_stat(created))
    except BoundedIOError:
        raise BoundedIOError("cleanup_incomplete") from cause
