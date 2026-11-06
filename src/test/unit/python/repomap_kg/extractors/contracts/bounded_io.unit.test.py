"""ADR 0154 bounded IO: names, limits, races and exact owned cleanup."""

from __future__ import annotations

import errno
import os
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest import mock

import pytest

from common_lore_index.extractors.contracts import bounded_io
from common_lore_index.extractors.contracts.bounded_io import (
    HARD_MAX_BYTES,
    BoundedIOError,
    FileIdentity,
    open_child_directory,
    open_directory,
    read_regular_file,
    remove_owned_file,
    write_new_regular_file,
)


@pytest.fixture
def directory(tmp_path: Path) -> Iterator[tuple[int, Path]]:
    fd = open_directory(tmp_path)
    try:
        yield fd, tmp_path
    finally:
        os.close(fd)


def test_shared_directory_is_refused_before_open_returns(tmp_path: Path) -> None:
    shared = tmp_path / "shared"
    shared.mkdir()
    shared.chmod(0o777)
    with pytest.raises(BoundedIOError) as raised:
        fd = open_directory(shared)
        os.close(fd)
    assert raised.value.code == "unsafe_directory"


def test_directory_requires_the_effective_owner(directory: tuple[int, Path]) -> None:
    fd, _ = directory
    observed = os.fstat(fd)
    foreign = SimpleNamespace(st_mode=observed.st_mode, st_uid=os.geteuid() + 1)
    with mock.patch.object(bounded_io.os, "fstat", return_value=foreign):
        with pytest.raises(BoundedIOError) as raised:
            read_regular_file(fd, "a.json", max_bytes=8)
    assert raised.value.code == "unsafe_directory"


def test_directory_mode_change_during_write_refuses_cleanup(directory: tuple[int, Path]) -> None:
    fd, root = directory

    def sharing_directory(_handle: int) -> None:
        root.chmod(0o777)
        raise OSError("interrupted owned write")

    try:
        with mock.patch.object(bounded_io.os, "fsync", side_effect=sharing_directory):
            with pytest.raises(BoundedIOError) as raised:
                write_new_regular_file(fd, "a.json", b"owned", max_bytes=8)
        assert raised.value.code == "cleanup_incomplete"
        assert (root / "a.json").read_bytes() == b"owned"
    finally:
        root.chmod(0o700)
        (root / "a.json").unlink(missing_ok=True)


@pytest.mark.parametrize("name", [
    "", ".", "..", "../escape", "a/b", ".hidden", "a\x00b", "a" * 129, "a..b", "-flag",
    b"name", None,
])
def test_names_must_be_one_fixed_component(directory: tuple[int, Path], name: Any) -> None:
    fd, root = directory
    for action in (lambda: write_new_regular_file(fd, name, b"x", max_bytes=8),
                   lambda: read_regular_file(fd, name, max_bytes=8)):
        with pytest.raises(BoundedIOError) as raised:
            action()
        assert raised.value.code == "invalid_name"
    assert list(root.iterdir()) == []


@pytest.mark.parametrize("limit", [0, -1, True, HARD_MAX_BYTES + 1, 1.0])
def test_limits_are_exact_positive_integers(directory: tuple[int, Path], limit: Any) -> None:
    fd, _ = directory
    with pytest.raises(BoundedIOError) as raised:
        write_new_regular_file(fd, "a.json", b"x", max_bytes=limit)
    assert raised.value.code == "invalid_limit"


def test_concurrent_growth_during_read_is_refused(directory: tuple[int, Path]) -> None:
    fd, root = directory
    write_new_regular_file(fd, "a.json", b"abc", max_bytes=64)
    real_read = os.read
    grown: list[bool] = []

    def growing_read(handle: int, size: int) -> bytes:
        chunk = real_read(handle, size)
        if chunk and not grown:
            grown.append(True)
            with (root / "a.json").open("ab") as writer:
                writer.write(b"more")
        return chunk

    with mock.patch.object(bounded_io.os, "read", side_effect=growing_read):
        with pytest.raises(BoundedIOError) as raised:
            read_regular_file(fd, "a.json", max_bytes=64)
    assert raised.value.code == "mutated"


def test_entry_substitution_after_read_is_refused(directory: tuple[int, Path]) -> None:
    fd, root = directory
    write_new_regular_file(fd, "a.json", b"abc", max_bytes=64)
    real_close = os.close
    swapped: list[bool] = []

    def swapping_close(handle: int) -> None:
        real_close(handle)
        if not swapped:
            swapped.append(True)
            (root / "a.json").unlink()
            (root / "a.json").write_bytes(b"abcdef")

    with mock.patch.object(bounded_io.os, "close", side_effect=swapping_close):
        with pytest.raises(BoundedIOError) as raised:
            read_regular_file(fd, "a.json", max_bytes=64)
    assert raised.value.code == "substituted"


def test_failed_write_removes_only_the_owned_inode(directory: tuple[int, Path]) -> None:
    fd, root = directory
    with mock.patch.object(bounded_io.os, "fsync", side_effect=OSError("disk")):
        with pytest.raises(OSError):
            write_new_regular_file(fd, "a.json", b"abc", max_bytes=64)
    assert list(root.iterdir()) == []


def test_foreign_entry_is_never_deleted_during_cleanup(directory: tuple[int, Path]) -> None:
    fd, root = directory

    def substitute(_handle: int) -> None:
        (root / "a.json").unlink()
        (root / "a.json").write_bytes(b"foreign")
        raise OSError("disk")

    with mock.patch.object(bounded_io.os, "fsync", side_effect=substitute):
        with pytest.raises(BoundedIOError) as raised:
            write_new_regular_file(fd, "a.json", b"abc", max_bytes=64)
    assert raised.value.code == "cleanup_incomplete"
    assert isinstance(raised.value.__cause__, OSError)
    assert (root / "a.json").read_bytes() == b"foreign"


def test_readback_mismatch_refuses_and_cleans_the_owned_file(directory: tuple[int, Path]) -> None:
    fd, root = directory
    with mock.patch.object(bounded_io, "read_regular_file", return_value=b"abd"):
        with pytest.raises(BoundedIOError) as raised:
            write_new_regular_file(fd, "a.json", b"abc", max_bytes=64)
    assert raised.value.code == "readback_mismatch"
    assert list(root.iterdir()) == []


@pytest.mark.parametrize("platform_errno", [errno.ELOOP, errno.ENOTDIR])
def test_directory_symlink_code_is_platform_independent(
    directory: tuple[int, Path], platform_errno: int
) -> None:
    fd, root = directory
    (root / "real").mkdir()
    (root / "link").symlink_to(root / "real", target_is_directory=True)
    (root / "plain").write_bytes(b"")
    refusal = OSError(platform_errno, "refused")
    with mock.patch.object(bounded_io.os, "open", side_effect=refusal):
        for action in (lambda: open_directory(root / "link"),
                       lambda: open_child_directory(fd, "link")):
            with pytest.raises(BoundedIOError) as raised:
                action()
            assert raised.value.code == "symlink_refused"
    with mock.patch.object(bounded_io.os, "open", side_effect=OSError(errno.ENOTDIR, "x")):
        with pytest.raises(BoundedIOError) as raised:
            open_child_directory(fd, "plain")
    assert raised.value.code == "not_directory"
    with pytest.raises(BoundedIOError) as raised:
        open_child_directory(fd, "link")
    assert raised.value.code == "symlink_refused"


def test_removal_requires_the_recorded_identity(directory: tuple[int, Path]) -> None:
    fd, root = directory
    identity = write_new_regular_file(fd, "a.json", b"abc", max_bytes=64)
    assert identity.size == 3 and identity.links == 1
    stale = FileIdentity(identity.device, identity.inode + 1, 3, 0, 0, 1)
    with pytest.raises(BoundedIOError) as raised:
        remove_owned_file(fd, "a.json", stale)
    assert raised.value.code == "cleanup_incomplete"
    assert (root / "a.json").read_bytes() == b"abc"
    remove_owned_file(fd, "a.json", identity)
    assert list(root.iterdir()) == []
    with pytest.raises(BoundedIOError):
        remove_owned_file(fd, "a.json", identity)



def test_invalid_descriptor_and_non_bytes_refuse_without_mutation(directory: tuple[int, Path]) -> None:
    fd, root = directory
    with pytest.raises(BoundedIOError) as bad_fd:
        read_regular_file(-1, "payload", max_bytes=8)
    assert bad_fd.value.code == "unsafe_directory"
    with pytest.raises(BoundedIOError) as bad_payload:
        write_new_regular_file(fd, "payload", cast(Any, bytearray(b"x")), max_bytes=8)
    assert bad_payload.value.code == "invalid_bytes"
    assert list(root.iterdir()) == []


def test_read_open_failure_retains_only_the_closed_code(directory: tuple[int, Path]) -> None:
    fd, _ = directory
    with mock.patch.object(bounded_io.os, "open", side_effect=OSError(errno.EACCES, "private detail")):
        with pytest.raises(BoundedIOError) as raised:
            read_regular_file(fd, "payload", max_bytes=8)
    assert raised.value.code == "open_failed"
    assert "private detail" not in str(raised.value)
