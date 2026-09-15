"""Read-only safe-tree inspection orchestration."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from repomap_test_support.resource_safe_tree_failure import SafeTreeDeleteError
from repomap_test_support.resource_safe_tree_delete_support import (
    Progress,
    RunEntryInspection,
    SafeTreeInspection,
)


class _InspectContents(Protocol):
    def __call__(
        self,
        directory_fd: int,
        *,
        root_device: int,
        progress: Progress,
    ) -> None: ...


@dataclass(frozen=True)
class InspectionHooks:
    safe_run_id: Callable[[str], str]
    nonnegative_int: Callable[[int, str], int]
    require_host_contract: Callable[[], None]
    validated_entry_name: Callable[[str], str]
    validated_scratch_root: Callable[[Path], Path]
    open_directory: Callable[[Path], int]
    open_child_directory: Callable[[int, str], int]
    fstat: Callable[[int], os.stat_result]
    stat_entry: Callable[[int, str], os.stat_result]
    list_directory: Callable[[int], list[str]]
    allocated_bytes: Callable[[os.stat_result], int]
    require_deletable_kind: Callable[[int], None]
    close_descriptor: Callable[[int], None]
    inspect_contents: _InspectContents


def inspect_run_entry(
    scratch_root: Path,
    name: str,
    *,
    hooks: InspectionHooks,
) -> RunEntryInspection:
    """Inspect one exact immediate ``r`` entry without following links."""
    hooks.require_host_contract()
    name = hooks.validated_entry_name(name)
    root_fd = hooks.open_directory(hooks.validated_scratch_root(scratch_root))
    runs_fd = entry_fd = None
    try:
        runs_fd = hooks.open_child_directory(root_fd, "r")
        root_metadata = hooks.fstat(root_fd)
        metadata = hooks.stat_entry(runs_fd, name)
        if metadata.st_dev != root_metadata.st_dev:
            raise SafeTreeDeleteError("foreign-device run entry refused")
        progress = Progress(hooks.allocated_bytes(metadata), 1)
        if stat.S_ISDIR(metadata.st_mode):
            entry_fd = hooks.open_child_directory(runs_fd, name)
            observed = hooks.fstat(entry_fd)
            if (observed.st_dev, observed.st_ino, observed.st_mode) != (
                metadata.st_dev,
                metadata.st_ino,
                metadata.st_mode,
            ):
                raise SafeTreeDeleteError("run entry identity changed")
            hooks.inspect_contents(
                entry_fd, root_device=root_metadata.st_dev, progress=progress
            )
        else:
            hooks.require_deletable_kind(metadata.st_mode)
        return RunEntryInspection(
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_mode,
            progress.allocated_bytes,
            progress.inode_count,
        )
    except SafeTreeDeleteError:
        raise
    except OSError as error:
        raise SafeTreeDeleteError("run entry inspection failed") from error
    finally:
        for descriptor in (entry_fd, runs_fd, root_fd):
            if descriptor is not None:
                try:
                    hooks.close_descriptor(descriptor)
                except OSError:
                    pass


def inspect_quarantine_tree(
    scratch_root: Path,
    *,
    project: str,
    run_id: str,
    expected_device: int,
    expected_inode: int,
    hooks: InspectionHooks,
) -> SafeTreeInspection:
    """Validate the whole target before COMMITTED without following links."""
    hooks.require_host_contract()
    root_fd = hooks.open_directory(hooks.validated_scratch_root(scratch_root))
    quarantine_fd = project_fd = run_fd = None
    try:
        quarantine_fd = hooks.open_child_directory(root_fd, ".quarantine")
        project_fd = hooks.open_child_directory(
            quarantine_fd, hooks.safe_run_id(project)
        )
        run_fd = hooks.open_child_directory(project_fd, hooks.safe_run_id(run_id))
        metadata = hooks.fstat(run_fd)
        if (metadata.st_dev, metadata.st_ino) != (
            hooks.nonnegative_int(expected_device, "quarantine device"),
            hooks.nonnegative_int(expected_inode, "quarantine inode"),
        ):
            raise SafeTreeDeleteError("quarantine root identity changed")
        progress = Progress(hooks.allocated_bytes(metadata), 1)
        hooks.inspect_contents(
            run_fd, root_device=metadata.st_dev, progress=progress
        )
        return SafeTreeInspection(progress.allocated_bytes, progress.inode_count)
    finally:
        for descriptor in (run_fd, project_fd, quarantine_fd, root_fd):
            if descriptor is not None:
                try:
                    hooks.close_descriptor(descriptor)
                except OSError:
                    pass


def quarantine_root_absent(
    scratch_root: Path,
    *,
    project: str,
    run_id: str,
    hooks: InspectionHooks,
) -> bool:
    """Observe absence through the same fixed no-follow ancestry."""
    hooks.require_host_contract()
    root_fd = hooks.open_directory(hooks.validated_scratch_root(scratch_root))
    quarantine_fd = project_fd = None
    try:
        quarantine_fd = hooks.open_child_directory(root_fd, ".quarantine")
        project_fd = hooks.open_child_directory(
            quarantine_fd, hooks.safe_run_id(project)
        )
        try:
            hooks.stat_entry(project_fd, hooks.safe_run_id(run_id))
        except FileNotFoundError:
            return True
        return False
    except OSError as error:
        raise SafeTreeDeleteError("quarantine absence readback failed") from error
    finally:
        for descriptor in (project_fd, quarantine_fd, root_fd):
            if descriptor is not None:
                try:
                    hooks.close_descriptor(descriptor)
                except OSError:
                    pass


def inspect_contents(
    directory_fd: int,
    *,
    root_device: int,
    progress: Progress,
    hooks: InspectionHooks,
) -> None:
    try:
        names = sorted(hooks.list_directory(directory_fd))
    except OSError as error:
        raise SafeTreeDeleteError("quarantine directory listing failed") from error
    for name in names:
        if name in {".", ".."} or "/" in name or "\0" in name:
            raise SafeTreeDeleteError("quarantine entry name is unsafe")
        metadata = hooks.stat_entry(directory_fd, name)
        mode = metadata.st_mode
        if metadata.st_dev != root_device:
            raise SafeTreeDeleteError("foreign-device entry refused")
        if stat.S_ISDIR(mode):
            child_fd = hooks.open_child_directory(directory_fd, name)
            try:
                observed = hooks.fstat(child_fd)
                if (observed.st_dev, observed.st_ino) != (
                    metadata.st_dev,
                    metadata.st_ino,
                ):
                    raise SafeTreeDeleteError("quarantine directory identity changed")
                progress.allocated_bytes += hooks.allocated_bytes(observed)
                progress.inode_count += 1
                hooks.inspect_contents(
                    child_fd, root_device=root_device, progress=progress
                )
            finally:
                hooks.close_descriptor(child_fd)
            continue
        if stat.S_ISBLK(mode) or stat.S_ISCHR(mode):
            raise SafeTreeDeleteError("unsupported special entry refused")
        if not (
            stat.S_ISREG(mode)
            or stat.S_ISLNK(mode)
            or stat.S_ISFIFO(mode)
            or stat.S_ISSOCK(mode)
        ):
            raise SafeTreeDeleteError("unclassifiable quarantine entry refused")
        progress.allocated_bytes += hooks.allocated_bytes(metadata)
        progress.inode_count += 1
