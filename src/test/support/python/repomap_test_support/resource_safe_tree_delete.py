"""Descriptor-relative, non-following deletion of one ``.quarantine`` run."""

from __future__ import annotations

import os
import stat
import time
from pathlib import Path
from typing import Callable, TypeVar

from repomap_test_support.resource_safe_tree_delete_inspection import (
    InspectionHooks,
    inspect_contents as _inspect_contents_impl,
    inspect_quarantine_tree as _inspect_quarantine_tree,
    inspect_run_entry as _inspect_run_entry,
    quarantine_root_absent as _quarantine_root_absent,
)
from repomap_test_support.resource_safe_tree_delete_operations import (
    DeleteHooks,
    delete_quarantine_tree as _delete_quarantine_tree,
    delete_run_entry as _delete_run_entry,
)
from repomap_test_support.resource_safe_tree_delete_support import (
    Progress as _Progress,
    RunEntryInspection as RunEntryInspection,
    SafeTreeDeleteResult as SafeTreeDeleteResult,
    SafeTreeInspection as SafeTreeInspection,
    allocated_bytes as _allocated_bytes,
    close_descriptor as _close_descriptor,
    entry_kind as _entry_kind,
    fstat as _fstat,
    fsync_descriptor as _fsync_descriptor,
    known_category as _known_category,
    list_directory as _list_directory,
    open_child_directory as _open_child_directory,
    open_directory as _open_directory,
    raise_delete_failure as _raise_delete_failure,
    require_deletable_kind as _require_deletable_kind,
    require_host_contract as _require_host_contract,
    rmdir_entry as _rmdir_entry,
    stat_entry as _stat_entry,
    unexpected_category as _unexpected_category,
    unlink_entry as _unlink_entry,
    validated_entry_name as _validated_entry_name,
    validated_scratch_root as _validated_scratch_root,
)
from repomap_test_support.resource_index_records import safe_run_id
from repomap_test_support.resource_safe_tree_failure import (
    SafeTreeDeleteError,
    SafeTreeDeleteFailure,
    SafeTreeDeleteUnavailable,
)
from repomap_test_support.resource_safe_tree_pin import EntryPin, pinned_identity
from repomap_test_support.resource_validation import nonnegative_int


_T = TypeVar("_T")


def _delete_hooks() -> DeleteHooks:
    return DeleteHooks(
        safe_run_id=safe_run_id,
        nonnegative_int=nonnegative_int,
        require_host_contract=_require_host_contract,
        validated_entry_name=_validated_entry_name,
        validated_scratch_root=_validated_scratch_root,
        open_directory=_open_directory,
        open_child_directory=_open_child_directory,
        fstat=_fstat,
        stat_entry=_stat_entry,
        entry_kind=_entry_kind,
        require_deletable_kind=_require_deletable_kind,
        delete_call=_delete_call,
        raise_delete_failure=_raise_delete_failure,
        unexpected_category=_unexpected_category,
        delete_contents=_delete_contents,
        sync=_sync,
        require_entry_identity=_require_entry_identity,
        remove_and_credit=_remove_and_credit,
        rmdir_entry=_rmdir_entry,
        unlink_entry=_unlink_entry,
        close_descriptor=_close_descriptor,
    )


def _inspection_hooks() -> InspectionHooks:
    return InspectionHooks(
        safe_run_id=safe_run_id,
        nonnegative_int=nonnegative_int,
        require_host_contract=_require_host_contract,
        validated_entry_name=_validated_entry_name,
        validated_scratch_root=_validated_scratch_root,
        open_directory=_open_directory,
        open_child_directory=_open_child_directory,
        fstat=_fstat,
        stat_entry=_stat_entry,
        list_directory=_list_directory,
        allocated_bytes=_allocated_bytes,
        require_deletable_kind=_require_deletable_kind,
        close_descriptor=_close_descriptor,
        inspect_contents=_inspect_contents,
    )


def inspect_run_entry(scratch_root: Path, name: str) -> RunEntryInspection:
    return _inspect_run_entry(scratch_root, name, hooks=_inspection_hooks())


def delete_run_entry(
    scratch_root: Path,
    *,
    name: str,
    expected_device: int,
    expected_inode: int,
    expected_mode: int,
    deadline: float,
    monotonic: Callable[[], float] = time.monotonic,
    before_remove: Callable[[str], None] | None = None,
    pin: EntryPin | None = None,
) -> SafeTreeDeleteResult:
    return _delete_run_entry(
        scratch_root,
        name=name,
        expected_device=expected_device,
        expected_inode=expected_inode,
        expected_mode=expected_mode,
        deadline=deadline,
        monotonic=monotonic,
        before_remove=before_remove,
        pin=pin,
        hooks=_delete_hooks(),
    )


def inspect_quarantine_tree(
    scratch_root: Path,
    *,
    project: str,
    run_id: str,
    expected_device: int,
    expected_inode: int,
) -> SafeTreeInspection:
    return _inspect_quarantine_tree(
        scratch_root,
        project=project,
        run_id=run_id,
        expected_device=expected_device,
        expected_inode=expected_inode,
        hooks=_inspection_hooks(),
    )


def delete_quarantine_tree(
    scratch_root: Path,
    *,
    project: str,
    run_id: str,
    expected_device: int,
    expected_inode: int,
    deadline: float,
    monotonic: Callable[[], float] = time.monotonic,
    before_remove: Callable[[str], None] | None = None,
) -> SafeTreeDeleteResult:
    """Delete one exact ".quarantine" run through the local facade seams."""
    return _delete_quarantine_tree(
        scratch_root,
        project=project,
        run_id=run_id,
        expected_device=expected_device,
        expected_inode=expected_inode,
        deadline=deadline,
        monotonic=monotonic,
        before_remove=before_remove,
        hooks=_delete_hooks(),
    )


def quarantine_root_absent(
    scratch_root: Path,
    *,
    project: str,
    run_id: str,
) -> bool:
    return _quarantine_root_absent(
        scratch_root,
        project=project,
        run_id=run_id,
        hooks=_inspection_hooks(),
    )


def _delete_contents(
    directory_fd: int,
    *,
    root_device: int,
    deadline: float,
    monotonic: Callable[[], float],
    before_remove: Callable[[str], None] | None,
    progress: _Progress,
) -> bool:
    names = _delete_call(
        "directory_list_error", progress, lambda: sorted(_list_directory(directory_fd))
    )
    for name in names:
        if name in {".", ".."} or "/" in name or "\0" in name:
            _raise_delete_failure("unexpected_safe_tree_error", progress, None)
        if _delete_call("callback_error", progress, monotonic) >= deadline:
            return False
        metadata = _delete_call(
            "entry_stat_error", progress, lambda: _stat_entry(directory_fd, name)
        )
        mode = metadata.st_mode
        if stat.S_ISDIR(mode):
            if metadata.st_dev != root_device:
                _raise_delete_failure("cross_device_refused", progress, None)
            child_fd = _delete_call(
                "entry_open_error",
                progress,
                lambda: _open_child_directory(directory_fd, name),
            )
            try:
                child_metadata = _delete_call(
                    "entry_stat_error", progress, lambda: _fstat(child_fd)
                )
                if (
                    child_metadata.st_dev != root_device
                    or (child_metadata.st_dev, child_metadata.st_ino)
                    != (metadata.st_dev, metadata.st_ino)
                ):
                    _raise_delete_failure("identity_changed", progress, None)
                if not _delete_contents(
                    child_fd,
                    root_device=root_device,
                    deadline=deadline,
                    monotonic=monotonic,
                    before_remove=before_remove,
                    progress=progress,
                ):
                    _sync(child_fd, progress)
                    return False
                if _delete_call("callback_error", progress, monotonic) >= deadline:
                    _sync(child_fd, progress)
                    return False
                if before_remove is not None:
                    _delete_call(
                        "callback_error", progress, lambda: before_remove("directory")
                    )
                _require_entry_identity(directory_fd, name, child_metadata, progress)
                _remove_and_credit(
                    "rmdir_error",
                    progress,
                    parent_fd=directory_fd,
                    name=name,
                    metadata=child_metadata,
                    action=lambda: _rmdir_entry(directory_fd, name),
                )
                _sync(directory_fd, progress)
            finally:
                try:
                    _close_descriptor(child_fd)
                except OSError:
                    pass
            continue
        if stat.S_ISBLK(mode) or stat.S_ISCHR(mode):
            _raise_delete_failure("unsupported_kind", progress, None)
        if not (
            stat.S_ISREG(mode)
            or stat.S_ISLNK(mode)
            or stat.S_ISFIFO(mode)
            or stat.S_ISSOCK(mode)
        ):
            _raise_delete_failure("unsupported_kind", progress, None)
        if metadata.st_dev != root_device:
            _raise_delete_failure("cross_device_refused", progress, None)
        if before_remove is not None:
            _delete_call(
                "callback_error", progress, lambda: before_remove(_entry_kind(mode))
            )
        _require_entry_identity(directory_fd, name, metadata, progress)
        _remove_and_credit(
            "unlink_error",
            progress,
            parent_fd=directory_fd,
            name=name,
            metadata=metadata,
            action=lambda: _unlink_entry(directory_fd, name),
        )
        _sync(directory_fd, progress)
    return True


def _inspect_contents(
    directory_fd: int,
    *,
    root_device: int,
    progress: _Progress,
) -> None:
    _inspect_contents_impl(
        directory_fd,
        root_device=root_device,
        progress=progress,
        hooks=_inspection_hooks(),
    )


def _require_entry_identity(
    parent_fd: int,
    name: str,
    expected: os.stat_result,
    progress: _Progress,
    pin: EntryPin | None = None,
) -> None:
    observed = _delete_call(
        "entry_stat_error", progress, lambda: _stat_entry(parent_fd, name)
    )
    identity = (observed.st_dev, observed.st_ino, observed.st_mode)
    if identity != (expected.st_dev, expected.st_ino, expected.st_mode):
        _raise_delete_failure("identity_changed", progress, None)
    if pin is not None and identity != _delete_call(
        "entry_stat_error", progress, lambda: pinned_identity(pin)
    ):
        _raise_delete_failure("identity_changed", progress, None)


def _sync(descriptor: int, progress: _Progress) -> None:
    try:
        _fsync_descriptor(descriptor)
    except BaseException as error:
        _raise_delete_failure(_known_category(error, "durability_error"), progress, error)


def _delete_call(
    category: str, progress: _Progress, action: Callable[[], _T]
) -> _T:
    try:
        return action()
    except SafeTreeDeleteFailure:
        raise
    except BaseException as error:
        _raise_delete_failure(_known_category(error, category), progress, error)


def _remove_and_credit(
    category: str,
    progress: _Progress,
    *,
    parent_fd: int,
    name: str,
    metadata: os.stat_result,
    action: Callable[[], None],
) -> None:
    try:
        action()
    except SafeTreeDeleteFailure:
        raise
    except BaseException as error:
        if not isinstance(error, Exception) and _entry_absent(parent_fd, name):
            _credit_removal(progress, metadata)
        _raise_delete_failure(_known_category(error, category), progress, error)
    _credit_removal(progress, metadata)


def _entry_absent(parent_fd: int, name: str) -> bool:
    try:
        _stat_entry(parent_fd, name)
    except FileNotFoundError:
        return True
    except BaseException:
        return False
    return False


def _credit_removal(progress: _Progress, metadata: os.stat_result) -> None:
    progress.allocated_bytes += _allocated_bytes(metadata)
    progress.inode_count += 1


__all__ = [
    "RunEntryInspection", "SafeTreeDeleteError", "SafeTreeDeleteFailure",
    "SafeTreeDeleteResult", "SafeTreeDeleteUnavailable", "SafeTreeInspection",
    "delete_quarantine_tree", "delete_run_entry", "inspect_quarantine_tree",
    "inspect_run_entry", "quarantine_root_absent",
]
