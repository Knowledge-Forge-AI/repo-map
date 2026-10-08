"""SQLite Local filesystem durability helper (LOCAL7).

Sync failures are injected with fakes (no real filesystem is damaged). A host
or filesystem without directory sync semantics is a bounded, path-free
``local-durability-unavailable`` refusal; any other sync error is
``local-durability-failed``; neither is ever suppressed by the helper. A chain
resolves its leaf first, so a relative or symlinked path syncs the real
directories, nearest first.
"""

from __future__ import annotations

import errno
import os
from pathlib import Path
from typing import Any

import pytest

from repomap_kg.storage.sqlite_local import durability
from repomap_kg.storage.sqlite_local.durability import (
    DURABILITY_FAILED,
    DURABILITY_UNAVAILABLE,
    fsync_descriptor,
    fsync_directory,
    fsync_directory_chain,
    fsync_file,
)
from repomap_kg.storage.sqlite_local.schema import LocalStoreError


def _refusal(call: Any, *args: Any) -> str:
    with pytest.raises(LocalStoreError) as caught:
        call(*args)
    # A translated OSError is never chained into the (path-carrying) original.
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None or caught.value.__suppress_context__
    return str(caught.value)


def _failing_fsync(code: int) -> Any:
    def fsync(_descriptor: int) -> None:
        raise OSError(code, os.strerror(code))

    return fsync


def test_real_file_and_directory_sync_succeed(tmp_path: Path) -> None:
    target = tmp_path / "file"
    target.write_bytes(b"data")
    fsync_file(target)
    fsync_directory(tmp_path)
    fsync_directory_chain(tmp_path, 1)


@pytest.mark.parametrize(
    ("code", "expected"),
    (
        (errno.EIO, f"{DURABILITY_FAILED}: directory sync failed"),
        (errno.ENOSPC, f"{DURABILITY_FAILED}: directory sync failed"),
        (errno.EINVAL, f"{DURABILITY_UNAVAILABLE}: directory sync is not supported"),
        (errno.ENOTSUP, f"{DURABILITY_UNAVAILABLE}: directory sync is not supported"),
    ),
)
def test_directory_sync_errors_are_classified_and_never_suppressed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int, expected: str
) -> None:
    monkeypatch.setattr(os, "fsync", _failing_fsync(code))
    assert _refusal(fsync_directory, tmp_path) == expected


def test_file_sync_failure_is_not_suppressed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "file"
    target.write_bytes(b"data")
    monkeypatch.setattr(os, "fsync", _failing_fsync(errno.EIO))
    assert _refusal(fsync_file, target) == f"{DURABILITY_FAILED}: file sync failed"
    descriptor = os.open(target, os.O_RDONLY)
    try:
        assert _refusal(fsync_descriptor, descriptor) == f"{DURABILITY_FAILED}: file sync failed"
    finally:
        os.close(descriptor)


@pytest.mark.parametrize(
    ("code", "expected"),
    ((errno.EOPNOTSUPP, DURABILITY_UNAVAILABLE), (errno.EACCES, DURABILITY_FAILED), (errno.ENOENT, DURABILITY_FAILED)),
)
def test_directory_open_errors_are_classified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int, expected: str
) -> None:
    def refuse(*_args: object, **_kwargs: object) -> int:
        raise OSError(code, os.strerror(code), str(tmp_path))

    monkeypatch.setattr(os, "open", refuse)
    message = _refusal(fsync_directory, tmp_path)
    assert message.startswith(f"{expected}: ") and str(tmp_path) not in message


def test_host_without_directory_sync_is_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(os, "O_DIRECTORY")
    assert _refusal(fsync_directory, tmp_path) == f"{DURABILITY_UNAVAILABLE}: directory sync is not supported"
    monkeypatch.undo()
    monkeypatch.setattr(durability.os, "name", "nt")
    assert _refusal(fsync_directory, tmp_path) == f"{DURABILITY_UNAVAILABLE}: directory sync is not supported"


def test_a_symlink_is_not_synced_as_a_directory(tmp_path: Path) -> None:
    (tmp_path / "real").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "real")
    assert _refusal(fsync_directory, tmp_path / "link").startswith(f"{DURABILITY_FAILED}: ")


def test_chain_resolves_relative_and_symlinked_leaves_nearest_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = tmp_path / "home" / "state" / "graphs"
    real.mkdir(parents=True)
    (tmp_path / "alias").symlink_to(tmp_path / "home")
    synced: list[Path] = []
    monkeypatch.setattr(durability, "fsync_directory", synced.append)
    fsync_directory_chain(tmp_path / "alias" / "state" / "graphs", 2)
    base = tmp_path.resolve()
    assert synced == [base / "home" / "state" / "graphs", base / "home" / "state", base / "home"]
    synced.clear()
    monkeypatch.chdir(tmp_path / "home")
    fsync_directory_chain(Path("state") / "graphs", 0)
    assert synced == [base / "home" / "state" / "graphs"]


def test_chain_stops_at_the_first_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "a" / "b").mkdir(parents=True)
    synced: list[Path] = []

    def fail_second(path: Path) -> None:
        synced.append(path)
        if len(synced) == 2:
            raise LocalStoreError(DURABILITY_FAILED, "directory sync failed")

    monkeypatch.setattr(durability, "fsync_directory", fail_second)
    with pytest.raises(LocalStoreError) as caught:
        fsync_directory_chain(tmp_path / "a" / "b", 2)
    assert caught.value.code == DURABILITY_FAILED and len(synced) == 2
