"""Descriptor-bound source body streaming for portable artifact sealing."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
import errno
import hashlib
import os
from pathlib import Path
import stat


_CHUNK_SIZE = 1024 * 1024


class SourceUnsealableError(ValueError):
    """A selected source path cannot be copied as a safe regular file."""


def _signature(details: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        details.st_mode,
        details.st_size,
        details.st_mtime_ns,
        details.st_ctime_ns,
        details.st_ino,
        details.st_dev,
    )


def _flags(*, directory: bool) -> int:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    if directory:
        flags |= getattr(os, "O_DIRECTORY", 0)
    else:
        flags |= getattr(os, "O_NONBLOCK", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    return flags


def _supports_dir_fd() -> bool:
    return os.open in getattr(os, "supports_dir_fd", ())


def _validate_regular(details: os.stat_result) -> None:
    if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
        raise SourceUnsealableError("source inventory is not sealable")


def _validate_directory(details: os.stat_result) -> None:
    if not stat.S_ISDIR(details.st_mode):
        raise SourceUnsealableError("source inventory is not sealable")


def _open_anchored(
    root: Path, parts: tuple[str, ...]
) -> tuple[int, os.stat_result, Callable[[], bool] | None]:
    directory = os.open(root, _flags(directory=True))
    try:
        _validate_directory(os.fstat(directory))
        for component in parts[:-1]:
            child = os.open(component, _flags(directory=True), dir_fd=directory)
            os.close(directory)
            directory = child
            _validate_directory(os.fstat(directory))
        descriptor = os.open(parts[-1], _flags(directory=False), dir_fd=directory)
    except OSError as error:
        if getattr(error, "errno", None) in {errno.ELOOP, errno.ENOTDIR}:
            raise SourceUnsealableError("source inventory is not sealable") from error
        raise
    finally:
        try:
            os.close(directory)
        except OSError:
            pass
    try:
        opened = os.fstat(descriptor)
        _validate_regular(opened)
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor, opened, None


def _open_fallback(
    root: Path, parts: tuple[str, ...]
) -> tuple[int, os.stat_result, Callable[[], bool]]:
    parent = root
    for component in parts[:-1]:
        candidate = parent / component
        details = candidate.lstat()
        _validate_directory(details)
        if candidate.is_symlink():
            raise SourceUnsealableError("source inventory is not sealable")
        parent = candidate
    candidate = parent / parts[-1]
    before = candidate.lstat()
    if candidate.is_symlink():
        raise SourceUnsealableError("source inventory is not sealable")
    _validate_regular(before)
    try:
        resolved = candidate.resolve(strict=True)
        if not resolved.is_relative_to(root):
            raise SourceUnsealableError("source inventory is not sealable")
        parent_before = parent.lstat()
    except FileNotFoundError as error:
        raise ValueError("source changed while sealing") from error
    try:
        descriptor = os.open(candidate, _flags(directory=False))
    except OSError as error:
        if getattr(error, "errno", None) in {errno.ELOOP, errno.ENOTDIR}:
            raise SourceUnsealableError("source inventory is not sealable") from error
        raise
    try:
        opened = os.fstat(descriptor)
        if _signature(before) != _signature(opened):
            raise ValueError("source changed while sealing")
        _validate_regular(opened)
    except BaseException:
        os.close(descriptor)
        raise

    def identity_is_stable() -> bool:
        try:
            current = candidate.lstat()
            current_parent = parent.lstat()
            resolved_current = candidate.resolve(strict=True)
        except OSError:
            return False
        return (
            resolved_current.is_relative_to(root)
            and _signature(current) == _signature(before)
            and _signature(current_parent) == _signature(parent_before)
        )

    return descriptor, opened, identity_is_stable


def _open_source(
    root: Path, relative_path: str
) -> tuple[int, os.stat_result, Callable[[], bool] | None]:
    parts = tuple(relative_path.split("/"))
    if not parts or any(not part or part in {".", ".."} for part in parts):
        raise SourceUnsealableError("source inventory is not sealable")
    if _supports_dir_fd():
        return _open_anchored(root, parts)
    return _open_fallback(root, parts)


class _SourceBody(Iterator[bytes]):
    def __init__(
        self,
        descriptor: int,
        opened: os.stat_result,
        *,
        expected_size: int,
        expected_digest: str,
        expected_executable: bool,
        identity_check: Callable[[], bool] | None = None,
    ) -> None:
        self._descriptor = descriptor
        self._opened = opened
        self._expected_size = expected_size
        self._expected_digest = expected_digest
        self._expected_executable = expected_executable
        self._identity_check = identity_check
        self._digest = hashlib.sha256()
        self._size = 0
        self.complete = False
        if opened.st_size != expected_size or bool(opened.st_mode & 0o111) != expected_executable:
            raise ValueError("source changed while sealing")

    def __iter__(self) -> "_SourceBody":
        return self

    def __next__(self) -> bytes:
        remaining = self._expected_size - self._size
        if remaining == 0:
            return self._finish()
        try:
            chunk = os.read(self._descriptor, min(_CHUNK_SIZE, remaining))
        except OSError as error:
            raise ValueError("source changed while sealing") from error
        if chunk:
            self._size += len(chunk)
            if self._size > self._expected_size:
                raise ValueError("source changed while sealing")
            self._digest.update(chunk)
            return chunk
        return self._finish()

    def _finish(self) -> bytes:
        try:
            after = os.fstat(self._descriptor)
        except OSError as error:
            raise ValueError("source changed while sealing") from error
        if (
            _signature(self._opened) != _signature(after)
            or not stat.S_ISREG(after.st_mode)
            or after.st_nlink != 1
            or self._size != self._expected_size
            or self._digest.hexdigest() != self._expected_digest
            or bool(after.st_mode & 0o111) != self._expected_executable
            or (
                self._identity_check is not None
                and not self._identity_check()
            )
        ):
            raise ValueError("source changed while sealing")
        self.complete = True
        raise StopIteration

    def close(self) -> None:
        if self._descriptor < 0:
            return
        descriptor = self._descriptor
        self._descriptor = -1
        try:
            os.close(descriptor)
        except OSError as error:
            raise ValueError("source changed while sealing") from error


@contextmanager
def open_source_body(
    root: Path,
    relative_path: str,
    *,
    expected_size: int,
    expected_digest: str,
    expected_executable: bool,
) -> Iterator[_SourceBody]:
    descriptor, opened, identity_check = _open_source(root, relative_path)
    try:
        body = _SourceBody(
            descriptor,
            opened,
            expected_size=expected_size,
            expected_digest=expected_digest,
            expected_executable=expected_executable,
            identity_check=identity_check,
        )
    except BaseException:
        os.close(descriptor)
        raise
    failed = False
    try:
        yield body
    except BaseException:
        failed = True
        raise
    finally:
        try:
            body.close()
        except BaseException:
            if not failed:
                raise
        finally:
            if not failed and not body.complete:
                raise ValueError("source changed while sealing")


__all__ = ["SourceUnsealableError", "open_source_body"]
