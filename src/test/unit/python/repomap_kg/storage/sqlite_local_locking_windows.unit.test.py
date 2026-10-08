"""SQLite Local Windows graph-lock algorithm: deterministic contract tests (LOCAL10).

NOT native Windows evidence. ``_WindowsBackend`` runs over real files on this
host with an injected fake ``msvcrt`` that models one exclusive byte-0 region
per file for any descriptor and asserts every call is at offset 0 for one byte.
Proven here: create-or-validate without writing (a zero-length or legacy file
locks unchanged), contention, independence, release, the read-only never-create
probe, error translation and descriptor closing, and bounded refusal of unsafe
lock paths. Not provable here, and carried as native-qualification items: the
``st_dev``/``st_ino`` identity Windows reports for ``lstat`` versus ``fstat``,
``os.open``'s default sharing mode (a second open must succeed so contention
appears at the lock call), reparse-point attributes and lock release timing
after process death.
"""

from __future__ import annotations

import errno
import os
from pathlib import Path
from typing import Any

import pytest

from repomap_kg.storage.sqlite_local.locking import _locked, _WindowsBackend
from repomap_kg.storage.sqlite_local.schema import LocalStoreError

IN_PROGRESS = "graph-publication-in-progress"
NOT_PRIVATE = "graph-database-unavailable: graph lock file is not private"


class FakeMsvcrt:
    """``msvcrt.locking`` semantics: one exclusive byte-0 region per file, any descriptor."""

    LK_UNLCK, LK_NBLCK = 0, 2

    def __init__(self, fail: dict[int, int] | None = None) -> None:
        self.held: dict[tuple[int, int], int] = {}
        self.fail = fail or {}

    def locking(self, descriptor: int, mode: int, nbytes: int) -> None:
        assert nbytes == 1 and os.lseek(descriptor, 0, os.SEEK_CUR) == 0
        if mode in self.fail:
            raise OSError(self.fail[mode], "injected")
        details = os.fstat(descriptor)
        key = (details.st_dev, details.st_ino)
        if mode == self.LK_NBLCK:
            if key in self.held:
                raise OSError(errno.EACCES, "locked")
            self.held[key] = descriptor
        elif self.held.pop(key, None) != descriptor:
            raise OSError(errno.EACCES, "not held")


def _code(caught: pytest.ExceptionInfo[LocalStoreError]) -> str:
    return str(caught.value)


def _store(tmp_path: Path) -> Path:
    store = tmp_path / "graphs"
    store.mkdir(mode=0o700)
    return store


def _opened(monkeypatch: pytest.MonkeyPatch) -> list[tuple[int, int]]:
    """Record every ``(flags, descriptor)`` the owner opens."""
    opened: list[tuple[int, int]] = []
    original = os.open

    def spy(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        descriptor = original(path, flags, *args, **kwargs)
        opened.append((flags, descriptor))
        return descriptor

    monkeypatch.setattr(os, "open", spy)
    return opened


def _closed(descriptor: int) -> bool:
    try:
        os.fstat(descriptor)
    except OSError as error:
        return error.errno == errno.EBADF
    return False


def _windows(fake: FakeMsvcrt | None = None) -> _WindowsBackend:
    return _WindowsBackend(fake or FakeMsvcrt())


def test_windows_mutation_creates_an_empty_file_and_never_writes(tmp_path: Path) -> None:
    lock = _store(tmp_path) / "g.sqlite3.publish.lock"
    backend = _windows()
    with _locked(lock, backend, create=True) as held:
        assert held is True and lock.stat().st_size == 0
    assert lock.read_bytes() == b""


@pytest.mark.parametrize("content", (b"", b"\x00legacy-bytes\xff" * 3))
def test_windows_existing_lock_files_lock_without_change(tmp_path: Path, content: bytes) -> None:
    lock = _store(tmp_path) / "g.sqlite3.publish.lock"
    lock.write_bytes(content)
    os.utime(lock, ns=(1_000_000_000, 1_000_000_000))
    backend = _windows()
    for create in (True, False):
        with _locked(lock, backend, create=create) as held:
            assert held is True
    assert lock.read_bytes() == content and lock.stat().st_mtime_ns == 1_000_000_000


def test_windows_contention_independence_and_release(tmp_path: Path) -> None:
    store = _store(tmp_path)
    one, two = store / "one.sqlite3.publish.lock", store / "two.sqlite3.publish.lock"
    backend = _windows()
    with _locked(one, backend, create=True):
        for create in (True, False):
            with pytest.raises(LocalStoreError) as caught, _locked(one, backend, create=create):
                pass
            assert _code(caught) == IN_PROGRESS
        with _locked(two, backend, create=True):
            pass
    with _locked(one, backend, create=True):
        pass


def test_windows_probe_never_creates_and_opens_read_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = _store(tmp_path)
    lock = store / "g.sqlite3.publish.lock"
    opened = _opened(monkeypatch)
    backend = _windows()
    with _locked(lock, backend, create=False) as held:
        assert held is False
    assert list(store.iterdir()) == [] and opened == []
    lock.write_bytes(b"")
    with _locked(lock, backend, create=False) as held:
        assert held is True
    assert [flags & (os.O_RDWR | os.O_WRONLY | os.O_CREAT | os.O_TRUNC) for flags, _ in opened] == [0]
    assert all(_closed(descriptor) for _, descriptor in opened)


@pytest.mark.parametrize(("mode", "error", "outcome"), [
    (FakeMsvcrt.LK_NBLCK, errno.EDEADLK, IN_PROGRESS),
    (FakeMsvcrt.LK_NBLCK, errno.EBADF, "propagates"),
    (FakeMsvcrt.LK_NBLCK, errno.EINVAL, "propagates"),
    (FakeMsvcrt.LK_UNLCK, errno.EINVAL, "released"),
])
def test_windows_error_translation_always_closes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: int, error: int, outcome: str
) -> None:
    lock = _store(tmp_path) / "g.sqlite3.publish.lock"
    opened = _opened(monkeypatch)
    backend = _windows(FakeMsvcrt({mode: error}))
    if outcome == "released":
        with _locked(lock, backend, create=True):
            pass
    else:
        with pytest.raises((LocalStoreError, OSError)) as caught, _locked(lock, backend, create=True):
            pass
        raised = caught.value
        if outcome == IN_PROGRESS:
            assert isinstance(raised, LocalStoreError) and str(raised) == IN_PROGRESS
        else:
            assert isinstance(raised, OSError) and raised.errno == error
    assert opened and all(_closed(descriptor) for _, descriptor in opened)


@pytest.mark.parametrize("kind", ("symlink", "directory", "two-links", "swapped"))
@pytest.mark.parametrize("create", (True, False))
def test_windows_unsafe_lock_paths_refuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, create: bool
) -> None:
    store = _store(tmp_path)
    lock = store / "g.sqlite3.publish.lock"
    other = store / "other"
    other.write_bytes(b"")
    if kind == "symlink":
        lock.symlink_to(other)
    elif kind == "directory":
        lock.mkdir()
    elif kind == "two-links":
        os.link(other, lock)
    else:
        lock.write_bytes(b"")
        original = os.lstat
        monkeypatch.setattr(os, "lstat", lambda path, *a, **k: original(other if Path(path) == lock else path))
    opened = _opened(monkeypatch)
    with pytest.raises(LocalStoreError) as caught, _locked(lock, _windows(), create=create):
        pass
    assert _code(caught) == NOT_PRIVATE
    assert all(_closed(descriptor) for _, descriptor in opened)
    assert other.read_bytes() == b""
