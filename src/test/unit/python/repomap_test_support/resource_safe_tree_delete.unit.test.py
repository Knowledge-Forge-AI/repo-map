"""No-follow descriptor deletion contracts without real byte removal."""

from __future__ import annotations

import inspect
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

import repomap_test_support.resource_safe_tree_delete as subject
from repomap_test_support.resource_safe_tree_delete import (
    SafeTreeDeleteError,
    SafeTreeDeleteFailure,
    inspect_quarantine_tree,
)


def _root(tmp_path: Path) -> tuple[Path, Path]:
    tmp_path.chmod(0o700)
    target = tmp_path / ".quarantine" / "repo-map_dev" / "run1"
    target.mkdir(mode=0o700, parents=True)
    return tmp_path, target


def _metadata(mode: int, *, inode: int, device: int = 1, blocks: int = 1):
    return SimpleNamespace(
        st_mode=mode,
        st_ino=inode,
        st_dev=device,
        st_blocks=blocks,
    )


def test_real_inspection_is_read_only_and_accepts_nested_links_fifo(
    tmp_path: Path,
) -> None:
    root, target = _root(tmp_path)
    nested = target / "nested"
    nested.mkdir(mode=0o700)
    (nested / "file.txt").write_text("public-safe")
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_text("unchanged")
    (target / "external-link").symlink_to(sentinel)
    fifo = target / "pipe"
    os.mkfifo(fifo, 0o600)
    metadata = target.stat(follow_symlinks=False)

    measured = inspect_quarantine_tree(
        root,
        project="repo-map_dev",
        run_id="run1",
        expected_device=metadata.st_dev,
        expected_inode=metadata.st_ino,
    )

    assert measured.inode_count == 5
    assert sentinel.read_text() == "unchanged"
    assert target.is_dir() and fifo.exists()


def test_symlinked_scratch_or_quarantine_root_is_refused(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    with pytest.raises(SafeTreeDeleteError, match="scratch root"):
        inspect_quarantine_tree(
            alias,
            project="repo-map_dev",
            run_id="run1",
            expected_device=1,
            expected_inode=1,
        )

    root, target = _root(real)
    quarantine = root / ".quarantine"
    moved = root / "quarantine-real"
    quarantine.rename(moved)
    quarantine.symlink_to(moved, target_is_directory=True)
    metadata = target.stat(follow_symlinks=False)
    with pytest.raises(SafeTreeDeleteError, match="child directory"):
        inspect_quarantine_tree(
            root,
            project="repo-map_dev",
            run_id="run1",
            expected_device=metadata.st_dev,
            expected_inode=metadata.st_ino,
        )


def test_swapped_root_identity_is_refused_before_mutation(tmp_path: Path) -> None:
    root, target = _root(tmp_path)
    metadata = target.stat(follow_symlinks=False)
    with pytest.raises(SafeTreeDeleteError, match="identity changed"):
        inspect_quarantine_tree(
            root,
            project="repo-map_dev",
            run_id="run1",
            expected_device=metadata.st_dev,
            expected_inode=metadata.st_ino + 1,
        )


def test_descriptor_relative_worker_unlinks_closed_safe_entry_classes(
    monkeypatch,
) -> None:
    entries = {
        "file": _metadata(stat.S_IFREG | 0o600, inode=2),
        "link": _metadata(stat.S_IFLNK | 0o777, inode=3),
        "fifo": _metadata(stat.S_IFIFO | 0o600, inode=4),
        "socket": _metadata(stat.S_IFSOCK | 0o600, inode=5),
        "sub": _metadata(stat.S_IFDIR | 0o700, inode=6),
    }
    removed = []
    monkeypatch.setattr(
        subject, "_list_directory", lambda fd: list(entries) if fd == 10 else []
    )
    monkeypatch.setattr(subject, "_stat_entry", lambda _fd, name: entries[name])
    monkeypatch.setattr(subject, "_open_child_directory", lambda _fd, _name: 11)
    monkeypatch.setattr(subject, "_fstat", lambda _fd: entries["sub"])
    monkeypatch.setattr(
        subject,
        "_unlink_entry",
        lambda _fd, name: removed.append(("unlink", name)),
    )
    monkeypatch.setattr(
        subject,
        "_rmdir_entry",
        lambda _fd, name: removed.append(("rmdir", name)),
    )
    monkeypatch.setattr(subject, "_sync", lambda _fd, _progress: None)
    monkeypatch.setattr(subject, "_close_descriptor", lambda _fd: None)
    progress = subject._Progress()

    completed = subject._delete_contents(
        10,
        root_device=1,
        deadline=10,
        monotonic=lambda: 0,
        before_remove=None,
        progress=progress,
    )

    assert completed is True
    assert removed == [
        ("unlink", "fifo"),
        ("unlink", "file"),
        ("unlink", "link"),
        ("unlink", "socket"),
        ("rmdir", "sub"),
    ]
    assert progress.inode_count == 5


@pytest.mark.parametrize(
    ("metadata", "expected_category"),
    [
        (_metadata(stat.S_IFCHR | 0o600, inode=2), "unsupported_kind"),
        (_metadata(stat.S_IFBLK | 0o600, inode=2), "unsupported_kind"),
        (
            _metadata(stat.S_IFDIR | 0o700, inode=2, device=2),
            "cross_device_refused",
        ),
    ],
)
def test_special_or_foreign_device_entries_refuse_before_unlink(
    monkeypatch, metadata, expected_category
) -> None:
    removed = []
    monkeypatch.setattr(subject, "_list_directory", lambda _fd: ["unsafe"])
    monkeypatch.setattr(subject, "_stat_entry", lambda _fd, _name: metadata)
    monkeypatch.setattr(
        subject, "_unlink_entry", lambda _fd, _name: removed.append(True)
    )
    with pytest.raises(SafeTreeDeleteFailure) as raised:
        subject._delete_contents(
            10,
            root_device=1,
            deadline=10,
            monotonic=lambda: 0,
            before_remove=None,
            progress=subject._Progress(),
        )
    assert raised.value.failure_category == expected_category
    assert raised.value.removed_allocated_bytes == 0
    assert raised.value.removed_inode_count == 0
    assert removed == []


def test_r3a6_absence_observation_error_is_conservative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path
    root.chmod(0o700)
    (root / "r").mkdir(mode=0o700)
    entry = root / "r" / "target"
    entry.write_bytes(b"public-safe")
    metadata = entry.stat(follow_symlinks=False)
    original_unlink = subject._unlink_entry
    original_stat = subject._stat_entry
    removed = False

    def remove_then_interrupt(parent_fd: int, name: str) -> None:
        nonlocal removed
        original_unlink(parent_fd, name)
        removed = True
        raise KeyboardInterrupt

    def fail_absence_observation(parent_fd: int, name: str):
        if removed:
            raise OSError("bounded observation failure")
        return original_stat(parent_fd, name)

    monkeypatch.setattr(subject, "_unlink_entry", remove_then_interrupt)
    monkeypatch.setattr(subject, "_stat_entry", fail_absence_observation)
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

    assert raised.value.failure_category == "interrupted"
    assert raised.value.removed_allocated_bytes == 0
    assert raised.value.removed_inode_count == 0
    assert not entry.exists()


def test_wall_limit_stops_at_descriptor_boundary_without_removal(monkeypatch) -> None:
    removed = []
    monkeypatch.setattr(subject, "_list_directory", lambda _fd: ["file"])
    monkeypatch.setattr(
        subject, "_unlink_entry", lambda _fd, _name: removed.append(True)
    )
    assert subject._delete_contents(
        10,
        root_device=1,
        deadline=10,
        monotonic=lambda: 10,
        before_remove=None,
        progress=subject._Progress(),
    ) is False
    assert removed == []


def test_deletion_owner_has_no_arbitrary_path_shell_or_broad_fallback() -> None:
    signature = inspect.signature(subject.delete_quarantine_tree)
    source = inspect.getsource(subject)
    assert "target" not in signature.parameters
    assert "rmtree" not in source
    assert "shutil" not in source
    assert "subprocess" not in source
    assert "system(" not in source
    assert '".quarantine"' in source


def test_external_sibling_and_link_target_are_not_descriptor_targets() -> None:
    stat_source = inspect.getsource(subject._stat_entry)
    unlink_source = inspect.getsource(subject._unlink_entry)
    rmdir_source = inspect.getsource(subject._rmdir_entry)
    deletion_source = inspect.getsource(subject._delete_contents)

    assert "dir_fd=parent_fd" in stat_source
    assert "follow_symlinks=False" in stat_source
    assert "dir_fd=parent_fd" in unlink_source
    assert "dir_fd=parent_fd" in rmdir_source
    assert "_stat_entry(directory_fd, name)" in deletion_source
    assert "_unlink_entry(directory_fd, name)" in deletion_source
    assert "_rmdir_entry(directory_fd, name)" in deletion_source
    assert "resolve(" not in deletion_source
    assert "readlink" not in deletion_source
