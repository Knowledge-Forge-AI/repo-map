"""The one SQLite Local graph lock owner (REPOMAP-PRODUCT3-SQLITE-LOCAL10).

Every Local mutation (init, refresh, backup, restore, upgrade and
``sqlite-cleanup --yes``) serializes on one exclusive, non-blocking,
interprocess lock per logical graph: the sibling ``<name>.publish.lock`` file,
never the database file. The lock file's bytes are never read or written and
are not publication authority. Contention is ``graph-publication-in-progress``;
the operating system releases the lock when its descriptor closes or its
process dies. Descriptors come from ``os.open`` and are not inherited by
spawned children (PEP 446).

* :func:`hold_graph_lock` (mutation owners): create or validate the lock file,
  then lock it.
* :func:`probe_graph_lock` (cleanup dry run): never create a missing lock file;
  an existing one is validated, opened read-only and locked the same way, never
  written, and never upgraded to a mutation lock.

The platform primitive is chosen from ``os.name`` at call time and imported
lazily, so importing this module (and the SQLite Local package) never imports
``fcntl``. POSIX uses ``flock``. Windows uses ``msvcrt.locking`` on byte 0,
which may lie past end of file, so a zero-length lock file is locked without
writing it; that backend is contract-tested only, not natively qualified. Any
other platform, or a missing primitive, refuses ``local-locking-unavailable``
rather than running unlocked. No environment value selects a backend.
"""

from __future__ import annotations

import errno
import importlib
import os
import stat
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from types import ModuleType
from typing import Any, Protocol

from repomap_kg.storage.sqlite_local.schema import (
    DATABASE_UNAVAILABLE,
    PUBLICATION_IN_PROGRESS,
    LocalStoreError,
)

LOCKING_UNAVAILABLE = "local-locking-unavailable"
_WINDOWS_CONTENTION = frozenset({errno.EACCES, errno.EDEADLK, getattr(errno, "EDEADLOCK", errno.EDEADLK)})


def lock_path(database: Path) -> Path:
    return database.with_name(database.name + ".publish.lock")


def _not_private() -> LocalStoreError:
    return LocalStoreError(DATABASE_UNAVAILABLE, "graph lock file is not private")


class _Backend(Protocol):
    def open_lock(self, path: Path, *, create: bool) -> int | None:
        """A validated descriptor; ``None`` only when ``create`` is false and the file is absent."""

    def try_lock(self, descriptor: int) -> bool:
        """Take the exclusive lock without blocking; ``False`` only on contention."""

    def unlock(self, descriptor: int) -> None: ...


class _PosixBackend:
    def __init__(self, fcntl: Any) -> None:
        self._fcntl = fcntl

    def open_lock(self, path: Path, *, create: bool) -> int | None:
        # O_NONBLOCK only keeps a planted FIFO from hanging the open.
        access = os.O_RDWR | os.O_CREAT if create else os.O_RDONLY
        try:
            descriptor = os.open(path, access | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        except FileNotFoundError:
            if create:
                raise
            return None
        except OSError as error:
            if error.errno in (errno.ELOOP, errno.EISDIR):
                raise _not_private() from None
            raise
        try:
            details = os.fstat(descriptor)
            if not stat.S_ISREG(details.st_mode) or details.st_uid != os.getuid() or details.st_nlink != 1:
                raise _not_private()
            if create:
                os.fchmod(descriptor, 0o600)
        except BaseException:
            os.close(descriptor)
            raise
        return descriptor

    def try_lock(self, descriptor: int) -> bool:
        try:
            self._fcntl.flock(descriptor, self._fcntl.LOCK_EX | self._fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True

    def unlock(self, descriptor: int) -> None:
        self._fcntl.flock(descriptor, self._fcntl.LOCK_UN)


class _WindowsBackend:
    """``msvcrt.locking`` on byte 0; there is no uid, so ownership stays with the store's privacy checks."""

    def __init__(self, msvcrt: Any) -> None:
        self._msvcrt = msvcrt
        self._flags = getattr(os, "O_BINARY", 0) | getattr(os, "O_NOINHERIT", 0)

    def open_lock(self, path: Path, *, create: bool) -> int | None:
        for _ in range(2):
            try:
                before = os.lstat(path)
            except FileNotFoundError:
                if not create:
                    return None
                try:
                    created = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL | self._flags, 0o600)
                except FileExistsError:
                    continue
                return self._validated(created, None)
            if not _plain_file(before):
                raise _not_private()
            access = os.O_RDWR if create else os.O_RDONLY
            return self._validated(os.open(path, access | self._flags), before)
        raise _not_private()

    @staticmethod
    def _validated(descriptor: int, before: os.stat_result | None) -> int:
        try:
            details = os.fstat(descriptor)
            if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1 or (
                before is not None and (details.st_dev, details.st_ino) != (before.st_dev, before.st_ino)
            ):
                raise _not_private()
        except BaseException:
            os.close(descriptor)
            raise
        return descriptor

    def try_lock(self, descriptor: int) -> bool:
        os.lseek(descriptor, 0, os.SEEK_SET)
        try:
            self._msvcrt.locking(descriptor, self._msvcrt.LK_NBLCK, 1)
        except OSError as error:
            if error.errno in _WINDOWS_CONTENTION:
                return False
            raise
        return True

    def unlock(self, descriptor: int) -> None:
        with suppress(OSError):  # closing the descriptor releases the region anyway
            os.lseek(descriptor, 0, os.SEEK_SET)
            self._msvcrt.locking(descriptor, self._msvcrt.LK_UNLCK, 1)


def _plain_file(details: os.stat_result) -> bool:
    reparse = getattr(details, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    return stat.S_ISREG(details.st_mode) and not reparse


def _load(load: Callable[[str], ModuleType], name: str, primitive: str) -> ModuleType:
    try:
        module = load(name)
    except ImportError:
        raise LocalStoreError(LOCKING_UNAVAILABLE, "the graph lock primitive is unavailable") from None
    if not hasattr(module, primitive):
        raise LocalStoreError(LOCKING_UNAVAILABLE, "the graph lock primitive is unavailable")
    return module


def _backend_for(os_name: str, *, load: Callable[[str], ModuleType] = importlib.import_module) -> _Backend:
    """The lock backend for ``os_name``; an unsupported platform never runs unlocked."""
    if os_name == "posix":
        return _PosixBackend(_load(load, "fcntl", "flock"))
    if os_name == "nt":
        return _WindowsBackend(_load(load, "msvcrt", "locking"))
    raise LocalStoreError(LOCKING_UNAVAILABLE, "graph locking is not supported on this platform")


@contextmanager
def _locked(path: Path, backend: _Backend, *, create: bool) -> Iterator[bool]:
    descriptor = backend.open_lock(path, create=create)
    if descriptor is None:
        yield False
        return
    try:
        if not backend.try_lock(descriptor):
            raise LocalStoreError(PUBLICATION_IN_PROGRESS)
        try:
            yield True
        finally:
            backend.unlock(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def hold_graph_lock(database: Path) -> Iterator[None]:
    """Hold ``database``'s graph lock for a mutation or refuse immediately.

    The caller has created or verified the private store directory.
    """
    with _locked(lock_path(database), _backend_for(os.name), create=True):
        yield


@contextmanager
def probe_graph_lock(database: Path) -> Iterator[bool]:
    """Hold an existing graph lock read-only; yield ``False`` (nothing held or created) when absent."""
    with _locked(lock_path(database), _backend_for(os.name), create=False) as held:
        yield held


__all__ = (
    "LOCKING_UNAVAILABLE",
    "hold_graph_lock",
    "lock_path",
    "probe_graph_lock",
)
