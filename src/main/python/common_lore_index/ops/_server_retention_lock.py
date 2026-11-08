"""One stable advisory lock for Server retained-attempt metadata."""

from __future__ import annotations

from contextlib import contextmanager
import errno
import fcntl
import os
from pathlib import Path
import stat
from typing import Iterator

from common_lore_index.coordinator._portable_materialization import (
    OwnedDirectoryIdentity,
    _remove_attempt_root,
)

LOCK_NAME = ".server-retention.lock"


class RetentionLockError(ValueError):
    """The Server retention namespace or lock is unsafe/unavailable."""


class RetentionLockBusy(RetentionLockError):
    """Another cooperating process owns the nonblocking retention lock."""


def server_attempts_parent(path: Path) -> Path | None:
    """Return the Server attempts namespace for a direct record or attempt."""
    candidate = (
        path.parent
        if path.name == "portable-result.json" and path.parent.name == "attempts"
        else path.parent.parent
        if path.name == "portable-result.json"
        else path.parent
    )
    if candidate.name == "attempts" and candidate.parent.name == "portable-publication":
        return candidate
    return None


def _check_namespace(parent: Path) -> None:
    if parent.name != "attempts" or parent.parent.name != "portable-publication":
        raise RetentionLockError("not a Server retention namespace")
    for index, path in enumerate((parent.parent, parent)):
        details = path.lstat()
        if (
            not stat.S_ISDIR(details.st_mode)
            or details.st_uid != os.getuid()
            or (stat.S_IMODE(details.st_mode) != 0o700 if index else stat.S_IMODE(details.st_mode) & 0o022)
            or path.resolve() != path.absolute()
        ):
            raise RetentionLockError("retention namespace is unsafe")


class ServerRetentionLock:
    """Owner-private, nonblocking flock whose inode is never removed."""

    def __init__(self, parent: Path) -> None:
        self.parent = parent
        self.path = parent.parent / LOCK_NAME
        self._descriptor: int | None = None

    def __enter__(self) -> "ServerRetentionLock":
        _check_namespace(self.parent)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        descriptor: int | None = None
        primary: BaseException | None = None
        try:
            try:
                expected = self.path.lstat()
            except FileNotFoundError:
                expected = None
            descriptor = os.open(self.path, flags, 0o600)
            details = os.fstat(descriptor)
            observed = self.path.lstat()
            if (
                not stat.S_ISREG(details.st_mode)
                or details.st_uid != os.getuid()
                or details.st_nlink != 1
                or stat.S_IMODE(details.st_mode) != 0o600
                or expected is not None
                and (expected.st_dev, expected.st_ino) != (details.st_dev, details.st_ino)
                or (observed.st_dev, observed.st_ino) != (details.st_dev, details.st_ino)
            ):
                raise RetentionLockError("retention lock is unsafe")
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            busy = RetentionLockBusy("retention lock is busy")
            primary = busy
            raise busy from error
        except RetentionLockError as error:
            primary = error
            raise
        except OSError as error:
            if error.errno in (errno.EACCES, errno.EAGAIN):
                busy = RetentionLockBusy("retention lock is busy")
                primary = busy
                raise busy from error
            unavailable = RetentionLockError("retention lock is unavailable")
            primary = unavailable
            raise unavailable from error
        except BaseException as error:
            primary = error
            raise
        finally:
            if primary is not None and descriptor is not None:
                try:
                    os.close(descriptor)
                except BaseException as secondary:
                    try:
                        primary.add_note(f"retention lock close failure: {type(secondary).__name__}")
                    except BaseException:
                        pass
                descriptor = None
        self._descriptor = descriptor
        return self

    def __exit__(self, exc_type: object, exc: BaseException | None, traceback: object) -> None:
        descriptor = self._descriptor
        self._descriptor = None
        if descriptor is None:
            return
        secondary: BaseException | None = None
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        except BaseException as error:
            secondary = error
        try:
            os.close(descriptor)
        except BaseException as error:
            if secondary is None:
                secondary = error
        if secondary is not None:
            if exc is not None:
                try:
                    exc.add_note(f"retention lock cleanup failure: {type(secondary).__name__}")
                except BaseException:
                    pass
            else:
                raise secondary


@contextmanager
def retention_lock_for(path: Path) -> Iterator[None]:
    """Lock Server records while leaving SQLite Local retention unchanged."""
    parent = server_attempts_parent(path)
    if parent is None:
        yield
    else:
        with ServerRetentionLock(parent):
            yield


def remove_server_attempt(
    root: Path, identity: OwnedDirectoryIdentity | None = None
) -> None:
    """Remove one capture-error attempt while holding the stable Server lock."""
    parent = server_attempts_parent(root)
    if parent is None:
        raise RetentionLockError("not a Server attempt")
    with ServerRetentionLock(parent):
        _remove_attempt_root(root, identity)


__all__ = (
    "LOCK_NAME",
    "RetentionLockBusy",
    "RetentionLockError",
    "ServerRetentionLock",
    "remove_server_attempt",
    "retention_lock_for",
    "server_attempts_parent",
)
