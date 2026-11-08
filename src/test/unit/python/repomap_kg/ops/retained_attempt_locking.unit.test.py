"""Server retained-attempt lock custody and namespace admission."""

from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

import pytest

from common_lore_index.ops import _server_retention_lock as locking


def _namespace(tmp_path: Path, *, anchor_mode: int = 0o755) -> Path:
    anchor = tmp_path / "portable-publication"
    anchor.mkdir(mode=anchor_mode)
    anchor.chmod(anchor_mode)
    attempts = anchor / "attempts"
    attempts.mkdir(mode=0o700)
    attempts.chmod(0o700)
    return attempts


def test_legacy_server_anchor_and_private_children_admit_stable_lock(
    tmp_path: Path,
) -> None:
    attempts = _namespace(tmp_path)
    lock = locking.ServerRetentionLock(attempts)

    with lock:
        assert lock.path == attempts.parent / locking.LOCK_NAME
        details = lock.path.lstat()
        assert details.st_uid == os.getuid()
        assert details.st_nlink == 1
        assert details.st_mode & 0o777 == 0o600

    assert lock.path.exists()


@pytest.mark.parametrize("anchor_mode", [0o775, 0o777])
def test_writable_anchor_refuses_without_creating_lock(
    tmp_path: Path, anchor_mode: int,
) -> None:
    attempts = _namespace(tmp_path, anchor_mode=anchor_mode)
    lock = locking.ServerRetentionLock(attempts)

    with pytest.raises(locking.RetentionLockError, match="namespace"):
        lock.__enter__()
    assert not lock.path.exists()


def test_symlinked_anchor_refuses(tmp_path: Path) -> None:
    real = _namespace(tmp_path)
    alias = tmp_path / "portable-publication"
    real.parent.rename(tmp_path / "real-publication")
    alias.symlink_to(tmp_path / "real-publication", target_is_directory=True)

    with pytest.raises(locking.RetentionLockError, match="namespace"):
        locking.ServerRetentionLock(alias / "attempts").__enter__()


def test_fstat_failure_closes_open_lock_descriptor(tmp_path: Path) -> None:
    attempts = _namespace(tmp_path)
    lock = locking.ServerRetentionLock(attempts)
    failure = OSError("injected fstat failure")
    real_close = os.close

    with mock.patch.object(locking.os, "fstat", side_effect=failure):
        with mock.patch.object(locking.os, "close", wraps=real_close) as close:
            with pytest.raises(locking.RetentionLockError, match="unavailable"):
                lock.__enter__()
    assert close.call_count == 1
    assert lock._descriptor is None


def test_busy_flock_closes_open_lock_descriptor_and_preserves_lock_file(
    tmp_path: Path,
) -> None:
    attempts = _namespace(tmp_path)
    lock = locking.ServerRetentionLock(attempts)
    real_close = os.close

    with mock.patch("fcntl.flock", side_effect=BlockingIOError()):
        with mock.patch.object(locking.os, "close", wraps=real_close) as close:
            with pytest.raises(locking.RetentionLockBusy):
                lock.__enter__()
    assert close.call_count == 1
    assert lock.path.exists()


def test_noncanonical_namespace_path_refuses(tmp_path: Path) -> None:
    attempts = _namespace(tmp_path)
    path_with_parent = attempts.parent / ".." / attempts.name

    with pytest.raises(locking.RetentionLockError, match="namespace"):
        locking.ServerRetentionLock(path_with_parent).__enter__()


def test_real_competing_open_is_busy_and_releases_only_its_descriptor(tmp_path: Path) -> None:
    attempts = _namespace(tmp_path)
    first = locking.ServerRetentionLock(attempts)
    with first:
        identity = first.path.stat().st_ino
        with pytest.raises(locking.RetentionLockBusy):
            with locking.ServerRetentionLock(attempts):
                pytest.fail("a competing open acquired the held retention lock")
        assert first.path.stat().st_ino == identity
        assert first._descriptor is not None
        assert os.fstat(first._descriptor).st_ino == identity
    with locking.ServerRetentionLock(attempts) as acquired:
        assert acquired.path.stat().st_ino == identity


def test_missing_server_lock_capability_refuses_before_lockfile_creation(tmp_path: Path) -> None:
    attempts = _namespace(tmp_path)
    lock = locking.ServerRetentionLock(attempts)
    original_import = __import__

    def without_fcntl(name, *args, **kwargs):
        if name == "fcntl":
            raise ImportError("fixture denies POSIX capability")
        return original_import(name, *args, **kwargs)

    with mock.patch("builtins.__import__", side_effect=without_fcntl):
        with pytest.raises(locking.RetentionLockError, match="capability is unavailable"):
            lock.__enter__()
    assert lock._descriptor is None
    assert not lock.path.exists()
