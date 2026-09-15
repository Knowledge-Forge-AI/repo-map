"""Inventory-bound deletion orchestration for the safe-tree facade."""

from __future__ import annotations

import math
import os
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, NoReturn, Protocol, TypeVar

from repomap_test_support.resource_safe_tree_failure import (
    SafeTreeDeleteError,
    SafeTreeDeleteFailure,
)
from repomap_test_support.resource_safe_tree_pin import EntryPin
from repomap_test_support.resource_safe_tree_delete_support import (
    Progress,
    SafeTreeDeleteResult,
)


_T = TypeVar("_T")


class _DeleteCall(Protocol):
    def __call__(
        self,
        category: str,
        progress: Progress,
        action: Callable[[], _T],
    ) -> _T: ...


class _DeleteContents(Protocol):
    def __call__(
        self,
        directory_fd: int,
        *,
        root_device: int,
        deadline: float,
        monotonic: Callable[[], float],
        before_remove: Callable[[str], None] | None,
        progress: Progress,
    ) -> bool: ...


class _RemoveAndCredit(Protocol):
    def __call__(
        self,
        category: str,
        progress: Progress,
        *,
        parent_fd: int,
        name: str,
        metadata: os.stat_result,
        action: Callable[[], None],
    ) -> None: ...


class _RequireEntryIdentity(Protocol):
    def __call__(
        self,
        parent_fd: int,
        name: str,
        expected: os.stat_result,
        progress: Progress,
        pin: EntryPin | None = None,
    ) -> None: ...


@dataclass(frozen=True)
class DeleteHooks:
    safe_run_id: Callable[[str], str]
    nonnegative_int: Callable[[int, str], int]
    require_host_contract: Callable[[], None]
    validated_entry_name: Callable[[str], str]
    validated_scratch_root: Callable[[Path], Path]
    open_directory: Callable[[Path], int]
    open_child_directory: Callable[[int, str], int]
    fstat: Callable[[int], os.stat_result]
    stat_entry: Callable[[int, str], os.stat_result]
    entry_kind: Callable[[int], str]
    require_deletable_kind: Callable[[int], None]
    delete_call: _DeleteCall
    raise_delete_failure: Callable[
        [str, Progress, BaseException | None], NoReturn
    ]
    unexpected_category: Callable[[BaseException], str]
    delete_contents: _DeleteContents
    sync: Callable[[int, Progress], None]
    require_entry_identity: _RequireEntryIdentity
    remove_and_credit: _RemoveAndCredit
    rmdir_entry: Callable[[int, str], None]
    unlink_entry: Callable[[int, str], None]
    close_descriptor: Callable[[int], None]


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
    hooks: DeleteHooks,
) -> SafeTreeDeleteResult:
    """Delete one inventory-bound immediate ``r`` entry."""
    hooks.require_host_contract()
    name = hooks.validated_entry_name(name)
    expected = (
        hooks.nonnegative_int(expected_device, "run entry device"),
        hooks.nonnegative_int(expected_inode, "run entry inode"),
        hooks.nonnegative_int(expected_mode, "run entry mode"),
    )
    if pin is not None and (pin.device, pin.inode, pin.mode) != expected:
        raise SafeTreeDeleteError("run entry pin does not match the inventory")
    if type(deadline) not in {int, float} or not math.isfinite(float(deadline)):
        raise SafeTreeDeleteError("deletion deadline is invalid")
    progress = Progress()
    root_fd = runs_fd = entry_fd = None
    try:
        root_fd = hooks.delete_call(
            "entry_open_error",
            progress,
            lambda: hooks.open_directory(hooks.validated_scratch_root(scratch_root)),
        )
        runs_fd = hooks.delete_call(
            "entry_open_error",
            progress,
            lambda: hooks.open_child_directory(root_fd, "r"),
        )
        root_metadata = hooks.delete_call(
            "entry_stat_error", progress, lambda: hooks.fstat(root_fd)
        )
        metadata = hooks.delete_call(
            "entry_stat_error",
            progress,
            lambda: hooks.stat_entry(runs_fd, name),
        )
        if metadata.st_dev != expected[0]:
            hooks.raise_delete_failure("identity_changed", progress, None)
        if (metadata.st_ino, metadata.st_mode) != expected[1:]:
            hooks.raise_delete_failure("identity_changed", progress, None)
        if metadata.st_dev != root_metadata.st_dev:
            hooks.raise_delete_failure("cross_device_refused", progress, None)
        if stat.S_ISDIR(metadata.st_mode):
            entry_fd = hooks.delete_call(
                "entry_open_error",
                progress,
                lambda: hooks.open_child_directory(runs_fd, name),
            )
            observed = hooks.delete_call(
                "entry_stat_error", progress, lambda: hooks.fstat(entry_fd)
            )
            if (observed.st_dev, observed.st_ino, observed.st_mode) != expected:
                hooks.raise_delete_failure("identity_changed", progress, None)
            if not hooks.delete_contents(
                entry_fd,
                root_device=root_metadata.st_dev,
                deadline=float(deadline),
                monotonic=monotonic,
                before_remove=before_remove,
                progress=progress,
            ):
                hooks.sync(entry_fd, progress)
                hooks.sync(runs_fd, progress)
                return SafeTreeDeleteResult(
                    False,
                    progress.allocated_bytes,
                    progress.inode_count,
                    "wall_time_limit",
                )
            if monotonic() >= deadline:
                hooks.sync(entry_fd, progress)
                hooks.sync(runs_fd, progress)
                return SafeTreeDeleteResult(
                    False,
                    progress.allocated_bytes,
                    progress.inode_count,
                    "wall_time_limit",
                )
            if before_remove is not None:
                hooks.delete_call(
                    "callback_error", progress, lambda: before_remove("directory")
                )
            hooks.require_entry_identity(runs_fd, name, metadata, progress, pin)
            hooks.remove_and_credit(
                "rmdir_error",
                progress,
                parent_fd=runs_fd,
                name=name,
                metadata=metadata,
                action=lambda: hooks.rmdir_entry(runs_fd, name),
            )
        else:
            try:
                hooks.require_deletable_kind(metadata.st_mode)
            except SafeTreeDeleteError as error:
                hooks.raise_delete_failure("unsupported_kind", progress, error)
            if monotonic() >= deadline:
                hooks.sync(runs_fd, progress)
                return SafeTreeDeleteResult(
                    False,
                    progress.allocated_bytes,
                    progress.inode_count,
                    "wall_time_limit",
                )
            if before_remove is not None:
                hooks.delete_call(
                    "callback_error",
                    progress,
                    lambda: before_remove(hooks.entry_kind(metadata.st_mode)),
                )
            hooks.require_entry_identity(runs_fd, name, metadata, progress, pin)
            hooks.remove_and_credit(
                "unlink_error",
                progress,
                parent_fd=runs_fd,
                name=name,
                metadata=metadata,
                action=lambda: hooks.unlink_entry(runs_fd, name),
            )
        hooks.sync(runs_fd, progress)
        return SafeTreeDeleteResult(
            True, progress.allocated_bytes, progress.inode_count, "deleted"
        )
    except SafeTreeDeleteFailure:
        raise
    except BaseException as error:
        hooks.raise_delete_failure(hooks.unexpected_category(error), progress, error)
    finally:
        for descriptor in (entry_fd, runs_fd, root_fd):
            if descriptor is not None:
                try:
                    hooks.close_descriptor(descriptor)
                except OSError:
                    pass


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
    hooks: DeleteHooks,
) -> SafeTreeDeleteResult:
    """Delete only ``.quarantine/<project>/<run_id>`` beneath one exact root."""
    hooks.require_host_contract()
    root = hooks.validated_scratch_root(scratch_root)
    project = hooks.safe_run_id(project)
    run_id = hooks.safe_run_id(run_id)
    expected = (
        hooks.nonnegative_int(expected_device, "quarantine device"),
        hooks.nonnegative_int(expected_inode, "quarantine inode"),
    )
    if type(deadline) not in {int, float}:
        raise SafeTreeDeleteError("deletion deadline is invalid")
    progress = Progress()
    root_fd = quarantine_fd = project_fd = run_fd = None
    try:
        root_fd = hooks.delete_call(
            "entry_open_error", progress, lambda: hooks.open_directory(root)
        )
        quarantine_fd = hooks.delete_call(
            "entry_open_error",
            progress,
            lambda: hooks.open_child_directory(root_fd, ".quarantine"),
        )
        project_fd = hooks.delete_call(
            "entry_open_error",
            progress,
            lambda: hooks.open_child_directory(quarantine_fd, project),
        )
        run_fd = hooks.delete_call(
            "entry_open_error",
            progress,
            lambda: hooks.open_child_directory(project_fd, run_id),
        )
        metadata = hooks.delete_call(
            "entry_stat_error", progress, lambda: hooks.fstat(run_fd)
        )
        if (metadata.st_dev, metadata.st_ino) != expected:
            hooks.raise_delete_failure("identity_changed", progress, None)
        if not hooks.delete_contents(
            run_fd,
            root_device=metadata.st_dev,
            deadline=float(deadline),
            monotonic=monotonic,
            before_remove=before_remove,
            progress=progress,
        ):
            hooks.sync(run_fd, progress)
            return SafeTreeDeleteResult(
                False,
                progress.allocated_bytes,
                progress.inode_count,
                "wall_time_limit",
            )
        if monotonic() >= deadline:
            hooks.sync(run_fd, progress)
            return SafeTreeDeleteResult(
                False,
                progress.allocated_bytes,
                progress.inode_count,
                "wall_time_limit",
            )
        if before_remove is not None:
            hooks.delete_call(
                "callback_error", progress, lambda: before_remove("directory")
            )
        hooks.require_entry_identity(project_fd, run_id, metadata, progress)
        hooks.remove_and_credit(
            "rmdir_error",
            progress,
            parent_fd=project_fd,
            name=run_id,
            metadata=metadata,
            action=lambda: hooks.rmdir_entry(project_fd, run_id),
        )
        hooks.sync(project_fd, progress)
        try:
            hooks.stat_entry(project_fd, run_id)
        except FileNotFoundError:
            pass
        except OSError as error:
            hooks.raise_delete_failure("entry_stat_error", progress, error)
        else:
            hooks.raise_delete_failure(
                "post_delete_verification_error", progress, None
            )
        return SafeTreeDeleteResult(
            True,
            progress.allocated_bytes,
            progress.inode_count,
            "deleted",
        )
    except SafeTreeDeleteFailure:
        raise
    except BaseException as error:
        hooks.raise_delete_failure(hooks.unexpected_category(error), progress, error)
    finally:
        for descriptor in (run_fd, project_fd, quarantine_fd, root_fd):
            if descriptor is not None:
                try:
                    hooks.close_descriptor(descriptor)
                except OSError:
                    pass
