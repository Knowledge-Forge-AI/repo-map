"""Owned temporary directories using the portable worker's existing no-follow cleanup."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import stat
import tempfile
import weakref
from types import TracebackType


@dataclass(frozen=True)
class OwnedDirectoryIdentity:
    device: int
    inode: int
    owner_uid: int


def _directory_identity(root: Path) -> OwnedDirectoryIdentity:
    details = root.lstat()
    if not stat.S_ISDIR(details.st_mode) or stat.S_ISLNK(details.st_mode):
        raise RuntimeError("portable cleanup root is not an owned directory")
    return OwnedDirectoryIdentity(details.st_dev, details.st_ino, details.st_uid)


def _remove_materialized_root(
    root: Path,
    expected: OwnedDirectoryIdentity,
) -> None:
    try:
        if _directory_identity(root) != expected:
            raise RuntimeError("portable cleanup root identity changed")
    except FileNotFoundError:
        return
    _remove_materialized_children(root)
    if _directory_identity(root) != expected:
        raise RuntimeError("portable cleanup root identity changed")
    root.chmod(0o700)
    root.rmdir()


def _remove_materialized_children(root: Path) -> None:
    with os.scandir(root) as entries:
        for entry in entries:
            path = root / entry.name
            details = entry.stat(follow_symlinks=False)
            if stat.S_ISREG(details.st_mode) and details.st_nlink == 1:
                path.chmod(0o600)
                path.unlink()
            elif stat.S_ISDIR(details.st_mode) and not stat.S_ISLNK(details.st_mode):
                _remove_materialized_children(path)
                path.chmod(0o700)
                path.rmdir()
            else:
                raise RuntimeError("portable cleanup encountered unexpected node")


class OwnedTemporaryDirectory:
    """Internal TemporaryDirectory surface with identity-checked path operations."""

    def __init__(self, *, prefix: str, dir: str | None = None) -> None:
        self._root = Path(tempfile.mkdtemp(prefix=prefix, dir=dir)).resolve()
        self._identity = _directory_identity(self._root)
        self.name = str(self._root)
        self._finalizer = weakref.finalize(self, _remove_materialized_root, self._root, self._identity)

    def cleanup(self) -> None:
        self._finalizer.detach()
        _remove_materialized_root(self._root, self._identity)

    def __enter__(self) -> str:
        return self.name

    def __exit__(self, exc_type: type[BaseException] | None,
                 exc: BaseException | None, traceback: TracebackType | None) -> None:
        self.cleanup()
