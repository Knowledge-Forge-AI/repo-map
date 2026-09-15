"""Maintenance-only exact legacy advisory-index parent hardening."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable

from repomap_test_support.resource_lifecycle_claim import (
    ClaimRegistry,
    MaintenanceHandle,
)
from repomap_test_support.resource_index_layout import (
    ALLOWED_PROJECT_INDEX_ENTRIES,
)


class IndexParentModeState(str, Enum):
    PRIVATE_READY = "private_ready"
    LEGACY_0755_HARDENABLE = "legacy_0755_hardenable"
    UNSAFE_MODE = "unsafe_mode"
    UNSAFE_OWNER = "unsafe_owner"
    UNSAFE_SYMLINK = "unsafe_symlink"
    UNSAFE_TYPE = "unsafe_type"
    UNSAFE_DEVICE = "unsafe_device"
    UNSAFE_PATH = "unsafe_path"
    IDENTITY_CHANGED = "identity_changed"
    SURROUNDING_AUTHORITY_UNSAFE = "surrounding_authority_unsafe"


class IndexParentModeError(RuntimeError):
    category = "index_parent_mode_refused"

    def __init__(
        self,
        message: str,
        *,
        state: IndexParentModeState,
        hardening_performed: bool = False,
        failure_stage: str | None = None,
        failure_errno: int | None = None,
    ) -> None:
        self.state = state
        self.hardening_performed = hardening_performed
        self.failure_stage = failure_stage
        self.failure_errno = failure_errno
        super().__init__(message)


@dataclass(frozen=True)
class DirectoryIdentity:
    device: int
    inode: int
    owner: int
    mode: int


@dataclass(frozen=True)
class IndexParentModeAssessment:
    state: IndexParentModeState
    scratch_root: Path
    index_parent: Path
    project_index: Path
    records_path: Path
    scratch_identity: DirectoryIdentity | None
    index_parent_identity: DirectoryIdentity | None
    project_identity: DirectoryIdentity | None
    records_identity: DirectoryIdentity | None


@dataclass(frozen=True)
class IndexParentHardeningResult:
    before_state: IndexParentModeState
    after_state: IndexParentModeState
    action: str
    changed_count: int


def _lstat(path: Path):
    return path.lstat()


def _entry_names(path: Path) -> frozenset[str]:
    return frozenset(entry.name for entry in path.iterdir())


def assess_index_parent_mode(
    scratch_root: Path,
) -> IndexParentModeAssessment:
    """Classify the fixed parent without acquiring or writing authority."""
    scratch = Path(scratch_root)
    parent = scratch / ".index"
    project_index = parent / "repo-map_dev"
    records = project_index / "runs"
    paths = (scratch, parent, project_index, records)
    if not scratch.is_absolute():
        return _assessment(IndexParentModeState.UNSAFE_PATH, paths, (None,) * 4)
    try:
        scratch_meta = _lstat(scratch)
        parent_meta = _lstat(parent)
    except OSError:
        return _assessment(
            IndexParentModeState.SURROUNDING_AUTHORITY_UNSAFE,
            paths,
            (None,) * 4,
        )
    leading_identities = (_identity(scratch_meta), _identity(parent_meta))
    if not _private_directory_metadata(scratch_meta):
        return _assessment(
            IndexParentModeState.SURROUNDING_AUTHORITY_UNSAFE,
            paths,
            (*leading_identities, None, None),
        )
    if stat.S_ISLNK(parent_meta.st_mode):
        return _assessment(
            IndexParentModeState.UNSAFE_SYMLINK,
            paths,
            (*leading_identities, None, None),
        )
    if not stat.S_ISDIR(parent_meta.st_mode):
        return _assessment(
            IndexParentModeState.UNSAFE_TYPE,
            paths,
            (*leading_identities, None, None),
        )
    if parent_meta.st_uid != os.getuid():
        return _assessment(
            IndexParentModeState.UNSAFE_OWNER,
            paths,
            (*leading_identities, None, None),
        )
    if parent_meta.st_dev != scratch_meta.st_dev:
        return _assessment(
            IndexParentModeState.UNSAFE_DEVICE,
            paths,
            (*leading_identities, None, None),
        )
    parent_mode = stat.S_IMODE(parent_meta.st_mode)
    if parent_mode not in {0o700, 0o755}:
        return _assessment(
            IndexParentModeState.UNSAFE_MODE,
            paths,
            (*leading_identities, None, None),
        )
    try:
        project_meta = _lstat(project_index)
        records_meta = _lstat(records)
    except OSError:
        return _assessment(
            IndexParentModeState.SURROUNDING_AUTHORITY_UNSAFE,
            paths,
            (*leading_identities, None, None),
        )
    metadata = (scratch_meta, parent_meta, project_meta, records_meta)
    identities = tuple(_identity(value) for value in metadata)
    if not all(
        _private_directory_metadata(value)
        and value.st_dev == scratch_meta.st_dev
        for value in (project_meta, records_meta)
    ):
        return _assessment(
            IndexParentModeState.SURROUNDING_AUTHORITY_UNSAFE, paths, identities
        )
    try:
        entries = _entry_names(project_index)
        reread = tuple(_lstat(path) for path in paths)
    except OSError:
        return _assessment(
            IndexParentModeState.SURROUNDING_AUTHORITY_UNSAFE, paths, identities
        )
    if entries - ALLOWED_PROJECT_INDEX_ENTRIES:
        return _assessment(
            IndexParentModeState.SURROUNDING_AUTHORITY_UNSAFE, paths, identities
        )
    if tuple(_identity(value) for value in reread) != identities:
        return _assessment(IndexParentModeState.IDENTITY_CHANGED, paths, identities)
    state = (
        IndexParentModeState.PRIVATE_READY
        if parent_mode == 0o700
        else IndexParentModeState.LEGACY_0755_HARDENABLE
    )
    return _assessment(state, paths, identities)


def harden_legacy_index_parent_mode(
    assessment: IndexParentModeAssessment,
    registry: ClaimRegistry,
    maintenance: MaintenanceHandle,
    *,
    checkpoint: Callable[[str], None] | None = None,
) -> IndexParentHardeningResult:
    """Narrow exactly one assessed directory descriptor from 0755 to 0700."""
    if not isinstance(assessment, IndexParentModeAssessment):
        raise IndexParentModeError(
            "index parent assessment is invalid",
            state=IndexParentModeState.UNSAFE_PATH,
        )
    registry.require_maintenance(maintenance)
    if (
        registry.project != "repo-map_dev"
        or Path(registry.scratch_root) != assessment.scratch_root
    ):
        raise IndexParentModeError(
            "index parent authority is invalid",
            state=IndexParentModeState.UNSAFE_PATH,
        )
    current = assess_index_parent_mode(assessment.scratch_root)
    if current != assessment:
        raise IndexParentModeError(
            "index parent identity changed",
            state=IndexParentModeState.IDENTITY_CHANGED,
        )
    if current.state is IndexParentModeState.PRIVATE_READY:
        return IndexParentHardeningResult(
            current.state, current.state, "already_private", 0
        )
    if current.state is not IndexParentModeState.LEGACY_0755_HARDENABLE:
        raise IndexParentModeError(
            "index parent mode is not repairable", state=current.state
        )
    if checkpoint is not None:
        checkpoint("before_open")
    descriptors: list[int] = []
    hardening_performed = False
    failure_stage = "open_scratch"
    try:
        scratch_fd = _open_directory(str(current.scratch_root))
        descriptors.append(scratch_fd)
        failure_stage = "open_index_parent"
        parent_fd = _open_directory(".index", dir_fd=scratch_fd)
        descriptors.append(parent_fd)
        failure_stage = "open_project_index"
        project_fd = _open_directory("repo-map_dev", dir_fd=parent_fd)
        descriptors.append(project_fd)
        failure_stage = "open_records"
        records_fd = _open_directory("runs", dir_fd=project_fd)
        descriptors.append(records_fd)
        failure_stage = "validate_descriptors"
        _validate_descriptors(
            current, scratch_fd, parent_fd, project_fd, records_fd
        )
        if checkpoint is not None:
            checkpoint("before_fchmod")
        failure_stage = "fchmod"
        os.fchmod(parent_fd, 0o700)
        hardening_performed = True
        failure_stage = "post_fchmod_fstat"
        changed = os.fstat(parent_fd)
        if (
            _identity(changed)
            != _with_mode(current.index_parent_identity, 0o700)
        ):
            raise IndexParentModeError(
                "index parent identity changed",
                state=IndexParentModeState.IDENTITY_CHANGED,
                hardening_performed=True,
            )
        try:
            os.fsync(parent_fd)
        except OSError:
            pass
    except IndexParentModeError:
        raise
    except OSError as error:
        raise IndexParentModeError(
            "index parent hardening failed",
            state=IndexParentModeState.SURROUNDING_AUTHORITY_UNSAFE,
            hardening_performed=hardening_performed,
            failure_stage=failure_stage,
            failure_errno=error.errno,
        ) from error
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
    after = assess_index_parent_mode(current.scratch_root)
    if (
        after.state is not IndexParentModeState.PRIVATE_READY
        or after.index_parent_identity
        != _with_mode(current.index_parent_identity, 0o700)
        or after.scratch_identity != current.scratch_identity
        or after.project_identity != current.project_identity
        or after.records_identity != current.records_identity
    ):
        raise IndexParentModeError(
            "index parent identity changed",
            state=IndexParentModeState.IDENTITY_CHANGED,
            hardening_performed=True,
        )
    return IndexParentHardeningResult(
        current.state, after.state, "legacy_0755_hardened", 1
    )


def _private_directory_metadata(value) -> bool:
    return (
        not stat.S_ISLNK(value.st_mode)
        and stat.S_ISDIR(value.st_mode)
        and value.st_uid == os.getuid()
        and stat.S_IMODE(value.st_mode) == 0o700
    )


def _identity(value) -> DirectoryIdentity:
    return DirectoryIdentity(
        value.st_dev,
        value.st_ino,
        value.st_uid,
        stat.S_IMODE(value.st_mode),
    )


def _with_mode(
    identity: DirectoryIdentity | None, mode: int
) -> DirectoryIdentity | None:
    if identity is None:
        return None
    return DirectoryIdentity(
        identity.device, identity.inode, identity.owner, mode
    )


def _assessment(state, paths, identities) -> IndexParentModeAssessment:
    return IndexParentModeAssessment(state, *paths, *identities)


def _open_directory(path: str, *, dir_fd: int | None = None) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    return os.open(path, flags, dir_fd=dir_fd)


def _validate_descriptors(
    assessment: IndexParentModeAssessment,
    scratch_fd: int,
    parent_fd: int,
    project_fd: int,
    records_fd: int,
) -> None:
    descriptor_identities = tuple(
        _identity(os.fstat(descriptor))
        for descriptor in (scratch_fd, parent_fd, project_fd, records_fd)
    )
    expected = (
        assessment.scratch_identity,
        assessment.index_parent_identity,
        assessment.project_identity,
        assessment.records_identity,
    )
    relative = (
        _identity(os.stat(".index", dir_fd=scratch_fd, follow_symlinks=False)),
        _identity(os.stat("repo-map_dev", dir_fd=parent_fd, follow_symlinks=False)),
        _identity(os.stat("runs", dir_fd=project_fd, follow_symlinks=False)),
    )
    path_parent = _identity(_lstat(assessment.index_parent))
    if (
        descriptor_identities != expected
        or relative != expected[1:]
        or path_parent != expected[1]
        or frozenset(os.listdir(project_fd)) - ALLOWED_PROJECT_INDEX_ENTRIES
    ):
        raise IndexParentModeError(
            "index parent identity changed",
            state=IndexParentModeState.IDENTITY_CHANGED,
        )


__all__ = [
    "DirectoryIdentity",
    "IndexParentHardeningResult",
    "IndexParentModeAssessment",
    "IndexParentModeError",
    "IndexParentModeState",
    "assess_index_parent_mode",
    "harden_legacy_index_parent_mode",
]
