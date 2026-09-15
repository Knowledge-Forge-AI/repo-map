"""Exceptional-progress and interruption seams for safe-tree deletion."""

from __future__ import annotations

import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

import repomap_test_support.resource_safe_tree_delete as subject
from repomap_test_support.resource_safe_tree_failure import (
    SAFE_TREE_FAILURE_CATEGORIES,
    SafeTreeDeleteFailure,
)


def _root(tmp_path: Path) -> Path:
    tmp_path.chmod(0o700)
    (tmp_path / "r").mkdir(mode=0o700)
    return tmp_path


def _quarantine(tmp_path: Path) -> tuple[Path, Path]:
    root = _root(tmp_path)
    target = root / ".quarantine" / "repo-map_dev" / "run1"
    target.mkdir(mode=0o700, parents=True)
    return root, target


def _blocks(path: Path) -> int:
    return path.stat(follow_symlinks=False).st_blocks * 512


def test_r1a1_first_quarantine_open_failure_preserves_closed_carrier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, target = _quarantine(tmp_path)
    metadata = target.stat(follow_symlinks=False)
    monkeypatch.setattr(
        subject,
        "_open_directory",
        lambda _path: (_ for _ in ()).throw(PermissionError("refused")),
    )

    with pytest.raises(SafeTreeDeleteFailure) as raised:
        subject.delete_quarantine_tree(
            root,
            project="repo-map_dev",
            run_id="run1",
            expected_device=metadata.st_dev,
            expected_inode=metadata.st_ino,
            deadline=10.0,
            monotonic=lambda: 0.0,
        )

    assert raised.value.failure_category == "entry_open_error"
    assert raised.value.removed_inode_count == 0


def test_r1a2_later_quarantine_open_failure_closes_prior_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, target = _quarantine(tmp_path)
    metadata = target.stat(follow_symlinks=False)
    original_close = subject._close_descriptor
    closed: list[int] = []

    def close(descriptor: int) -> None:
        closed.append(descriptor)
        original_close(descriptor)

    monkeypatch.setattr(subject, "_close_descriptor", close)
    monkeypatch.setattr(
        subject,
        "_open_child_directory",
        lambda _fd, _name: (_ for _ in ()).throw(PermissionError("refused")),
    )

    with pytest.raises(SafeTreeDeleteFailure) as raised:
        subject.delete_quarantine_tree(
            root,
            project="repo-map_dev",
            run_id="run1",
            expected_device=metadata.st_dev,
            expected_inode=metadata.st_ino,
            deadline=10.0,
            monotonic=lambda: 0.0,
        )

    assert raised.value.failure_category == "entry_open_error"
    assert len(closed) == 1


@pytest.mark.parametrize("entry_kind", ["file", "directory"])
def test_r1a3_r1a4_remove_then_interrupt_credits_exact_progress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    entry_kind: str,
) -> None:
    root = _root(tmp_path)
    entry = root / "r" / "target"
    if entry_kind == "file":
        entry.write_bytes(b"public-safe")
        seam_name = "_unlink_entry"
    else:
        entry.mkdir(mode=0o700)
        seam_name = "_rmdir_entry"
    metadata = entry.stat(follow_symlinks=False)
    original = getattr(subject, seam_name)

    def remove_then_interrupt(parent_fd: int, name: str) -> None:
        original(parent_fd, name)
        raise KeyboardInterrupt

    monkeypatch.setattr(subject, seam_name, remove_then_interrupt)
    with pytest.raises(SafeTreeDeleteFailure) as raised:
        subject.delete_run_entry(
            root,
            name="target",
            expected_device=metadata.st_dev,
            expected_inode=metadata.st_ino,
            expected_mode=metadata.st_mode,
            deadline=10.0,
            monotonic=lambda: 0.0,
        )

    assert raised.value.failure_category == "interrupted"
    assert isinstance(raised.value.__cause__, KeyboardInterrupt)
    assert raised.value.removed_inode_count == 1
    assert raised.value.removed_allocated_bytes == metadata.st_blocks * 512
    assert not entry.exists()


def test_r1a5_concurrent_replacement_is_not_credited_or_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _root(tmp_path)
    entry = root / "r" / "target"
    entry.write_bytes(b"original")
    metadata = entry.stat(follow_symlinks=False)
    original = subject._unlink_entry

    def replace_then_interrupt(parent_fd: int, name: str) -> None:
        original(parent_fd, name)
        entry.write_bytes(b"replacement")
        raise KeyboardInterrupt

    monkeypatch.setattr(subject, "_unlink_entry", replace_then_interrupt)
    with pytest.raises(SafeTreeDeleteFailure) as raised:
        subject.delete_run_entry(
            root,
            name="target",
            expected_device=metadata.st_dev,
            expected_inode=metadata.st_ino,
            expected_mode=metadata.st_mode,
            deadline=10.0,
            monotonic=lambda: 0.0,
        )

    assert raised.value.failure_category == "interrupted"
    assert raised.value.removed_inode_count == 0
    assert entry.read_bytes() == b"replacement"


def test_x1_later_stat_failure_preserves_prior_child_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _root(tmp_path)
    entry = root / "r" / "target"
    entry.mkdir(mode=0o700)
    first = entry / "a-first"
    first.write_bytes(b"first")
    second = entry / "b-second"
    second.write_bytes(b"second")
    expected_bytes = _blocks(first)
    metadata = entry.stat(follow_symlinks=False)
    original_stat = subject._stat_entry

    def fail_second(parent_fd: int, name: str):
        if name == second.name and not first.exists():
            raise OSError("later stat failure")
        return original_stat(parent_fd, name)

    monkeypatch.setattr(subject, "_stat_entry", fail_second)
    with pytest.raises(SafeTreeDeleteFailure) as raised:
        subject.delete_run_entry(
            root,
            name=entry.name,
            expected_device=metadata.st_dev,
            expected_inode=metadata.st_ino,
            expected_mode=metadata.st_mode,
            deadline=10.0,
            monotonic=lambda: 0.0,
        )

    assert raised.value.failure_category == "entry_stat_error"
    assert raised.value.removed_inode_count == 1
    assert raised.value.removed_allocated_bytes == expected_bytes
    assert not first.exists() and second.exists()


@pytest.mark.parametrize("failure", ["open", "identity", "unsupported"])
def test_x2_x3_x4_later_boundary_failure_preserves_prior_progress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    root = _root(tmp_path)
    entry = root / "r" / "target"
    entry.mkdir(mode=0o700)
    first = entry / "a-first"
    first.write_bytes(b"first")
    second = entry / "b-second"
    if failure == "open":
        second.mkdir(mode=0o700)
    else:
        second.write_bytes(b"second")
    expected_bytes = _blocks(first)
    metadata = entry.stat(follow_symlinks=False)
    if failure == "open":
        original_open = subject._open_child_directory

        def open_child(parent_fd: int, name: str) -> int:
            if name == second.name and not first.exists():
                raise OSError("later open failure")
            return original_open(parent_fd, name)

        monkeypatch.setattr(subject, "_open_child_directory", open_child)
        expected_category = "entry_open_error"
    else:
        original_stat = subject._stat_entry
        second_calls = 0

        def stat_entry(parent_fd: int, name: str):
            nonlocal second_calls
            observed = original_stat(parent_fd, name)
            if name != second.name or first.exists():
                return observed
            second_calls += 1
            if failure == "unsupported":
                return SimpleNamespace(
                    st_dev=observed.st_dev,
                    st_ino=observed.st_ino,
                    st_mode=stat.S_IFCHR | 0o600,
                    st_blocks=observed.st_blocks,
                )
            if second_calls == 2:
                return SimpleNamespace(
                    st_dev=observed.st_dev,
                    st_ino=observed.st_ino + 1,
                    st_mode=observed.st_mode,
                    st_blocks=observed.st_blocks,
                )
            return observed

        monkeypatch.setattr(subject, "_stat_entry", stat_entry)
        expected_category = (
            "identity_changed" if failure == "identity" else "unsupported_kind"
        )

    with pytest.raises(SafeTreeDeleteFailure) as raised:
        subject.delete_run_entry(
            root,
            name=entry.name,
            expected_device=metadata.st_dev,
            expected_inode=metadata.st_ino,
            expected_mode=metadata.st_mode,
            deadline=10.0,
            monotonic=lambda: 0.0,
        )

    assert raised.value.failure_category == expected_category
    assert raised.value.removed_inode_count == 1
    assert raised.value.removed_allocated_bytes == expected_bytes
    assert not first.exists() and second.exists()


@pytest.mark.parametrize("entry_kind", ["file", "directory"])
def test_x5_x6_post_remove_durability_failure_keeps_credit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    entry_kind: str,
) -> None:
    root = _root(tmp_path)
    entry = root / "r" / "target"
    entry.write_bytes(b"payload") if entry_kind == "file" else entry.mkdir(mode=0o700)
    metadata = entry.stat(follow_symlinks=False)
    monkeypatch.setattr(
        subject,
        "_fsync_descriptor",
        lambda _fd: (_ for _ in ()).throw(OSError("sync failed")),
    )

    with pytest.raises(SafeTreeDeleteFailure) as raised:
        subject.delete_run_entry(
            root,
            name=entry.name,
            expected_device=metadata.st_dev,
            expected_inode=metadata.st_ino,
            expected_mode=metadata.st_mode,
            deadline=10.0,
            monotonic=lambda: 0.0,
        )

    assert raised.value.failure_category == "durability_error"
    assert raised.value.removed_inode_count == 1
    assert raised.value.removed_allocated_bytes == metadata.st_blocks * 512
    assert not entry.exists()


def test_x7_x8_recursive_progress_is_exact_once_and_zero_before_mutation(
    tmp_path: Path
) -> None:
    root = _root(tmp_path)
    entry = root / "r" / "target"
    nested = entry / "nested"
    nested.mkdir(mode=0o700, parents=True)
    first = nested / "a-first"
    first.write_bytes(b"first")
    first_bytes = _blocks(first)
    second = nested / "b-second"
    second.write_bytes(b"second")
    metadata = entry.stat(follow_symlinks=False)
    calls = 0

    def interrupt_second(_kind: str) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("later callback")

    with pytest.raises(SafeTreeDeleteFailure) as raised:
        subject.delete_run_entry(
            root,
            name=entry.name,
            expected_device=metadata.st_dev,
            expected_inode=metadata.st_ino,
            expected_mode=metadata.st_mode,
            deadline=10.0,
            monotonic=lambda: 0.0,
            before_remove=interrupt_second,
        )
    assert raised.value.removed_inode_count == 1
    assert raised.value.removed_allocated_bytes == first_bytes

    zero = root / "r" / "zero"
    zero.write_bytes(b"zero")
    zero_metadata = zero.stat(follow_symlinks=False)
    with pytest.raises(SafeTreeDeleteFailure) as zero_raised:
        subject.delete_run_entry(
            root,
            name=zero.name,
            expected_device=zero_metadata.st_dev,
            expected_inode=zero_metadata.st_ino,
            expected_mode=zero_metadata.st_mode,
            deadline=10.0,
            monotonic=lambda: 0.0,
            before_remove=lambda _kind: (_ for _ in ()).throw(RuntimeError()),
        )
    assert zero_raised.value.removed_inode_count == 0
    assert zero.exists()


def test_x9_x10_run_and_quarantine_use_same_closed_carrier(
    tmp_path: Path
) -> None:
    root, target = _quarantine(tmp_path)
    child = target / "child"
    child.write_bytes(b"payload")
    metadata = target.stat(follow_symlinks=False)

    with pytest.raises(SafeTreeDeleteFailure) as raised:
        subject.delete_quarantine_tree(
            root,
            project="repo-map_dev",
            run_id="run1",
            expected_device=metadata.st_dev,
            expected_inode=metadata.st_ino,
            deadline=10.0,
            monotonic=lambda: 0.0,
            before_remove=lambda _kind: (_ for _ in ()).throw(RuntimeError()),
        )

    assert raised.value.failure_category in SAFE_TREE_FAILURE_CATEGORIES
    assert raised.value.failure_category == "callback_error"
    assert raised.value.removed_inode_count == 0


def test_r1a13_safe_tree_tests_patch_module_local_seams_only() -> None:
    paths = (
        Path(__file__),
        Path(__file__).with_name("resource_safe_tree_delete.unit.test.py"),
    )
    forbidden = "monkeypatch.setattr(subject." + "os"
    for path in paths:
        assert forbidden not in path.read_text()
