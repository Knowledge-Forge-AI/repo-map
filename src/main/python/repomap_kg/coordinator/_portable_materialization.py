"""Safe, attempt-owned materialization of verified snapshot artifacts."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import secrets
import stat
from collections.abc import Callable

from repomap_kg.artifacts.manifest import PortableSnapshotManifest
from repomap_kg.artifacts.store import ArtifactStore
from repomap_kg.coordinator._refresh_capability_io import validate_private_directory


@dataclass(frozen=True)
class OwnedDirectoryIdentity:
    device: int
    inode: int
    owner_uid: int


@dataclass(frozen=True)
class MaterializedView:
    attempt_root: Path
    attempt_identity: OwnedDirectoryIdentity
    binding_roots: dict[str, Path]
    materialized_bytes: int


class MaterializedWorkspace:
    """Materialize only validated regular files and remove the exact owned root."""

    def __init__(
        self,
        store: ArtifactStore,
        manifest: PortableSnapshotManifest,
        workspace_root: Path,
        *,
        job_id: str,
        attempt: int,
        max_artifact_bytes: int | None = None,
        cancel_check: Callable[[], None] | None = None,
    ) -> None:
        self._store = store
        self._manifest = manifest
        self._workspace_root = workspace_root
        self._job_id = job_id
        self._attempt = attempt
        self._max_artifact_bytes = max_artifact_bytes
        self._cancel_check = cancel_check
        self._view: MaterializedView | None = None

    def __enter__(self) -> MaterializedView:
        validate_private_directory(self._workspace_root)
        token = secrets.token_hex(16)
        attempt_root = self._workspace_root / f"attempt-{self._attempt}-{token}"
        attempt_root.mkdir(mode=0o700)
        attempt_identity = _directory_identity(attempt_root)
        roots = {
            binding.binding_id: attempt_root / f"binding-{index:04d}"
            for index, binding in enumerate(self._manifest.bindings)
        }
        try:
            for root in roots.values():
                root.mkdir(mode=0o700)
            total = 0
            for entry in self._manifest.entries:
                if self._cancel_check is not None:
                    self._cancel_check()
                root = roots[entry.binding_id]
                destination = root.joinpath(*entry.source_relative_path.split("/"))
                destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                bound = (
                    entry.reference.size_bytes
                    if self._max_artifact_bytes is None
                    else min(self._max_artifact_bytes, entry.reference.size_bytes)
                )
                data = self._store.read(
                    entry.reference,
                    max_bytes=bound,
                )
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
                if hasattr(os, "O_NOFOLLOW"):
                    flags |= os.O_NOFOLLOW
                descriptor = os.open(destination, flags, 0o600)
                try:
                    view = memoryview(data)
                    while view:
                        written = os.write(descriptor, view)
                        if written <= 0:
                            raise OSError("artifact write failed")
                        view = view[written:]
                finally:
                    os.close(descriptor)
                if destination.read_bytes() != data:
                    raise OSError("artifact verification failed")
                destination.chmod(0o500 if entry.executable else 0o400)
                total += len(data)
            self._view = MaterializedView(
                attempt_root, attempt_identity, roots, total
            )
            return self._view
        except BaseException:
            _remove_materialized_root(attempt_root, attempt_identity)
            raise

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._view is not None:
            _remove_materialized_root(
                self._view.attempt_root, self._view.attempt_identity
            )


def _directory_identity(root: Path) -> OwnedDirectoryIdentity:
    details = root.lstat()
    if not stat.S_ISDIR(details.st_mode) or stat.S_ISLNK(details.st_mode):
        raise RuntimeError("portable cleanup root is not an owned directory")
    return OwnedDirectoryIdentity(details.st_dev, details.st_ino, details.st_uid)


def _remove_attempt_root(
    root: Path,
    expected: OwnedDirectoryIdentity | None = None,
) -> None:
    try:
        observed = _directory_identity(root)
    except FileNotFoundError:
        return
    if expected is not None and observed != expected:
        raise RuntimeError("portable cleanup root identity changed")
    parent_descriptor = os.open(root.parent, os.O_RDONLY | os.O_DIRECTORY)
    root_descriptor: int | None = None
    try:
        root_descriptor = os.open(
            root.name,
            os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent_descriptor,
        )
        opened = os.fstat(root_descriptor)
        opened_identity = OwnedDirectoryIdentity(
            opened.st_dev, opened.st_ino, opened.st_uid
        )
        if opened_identity != observed:
            raise RuntimeError("portable cleanup root identity changed")
        _remove_owned_children(root_descriptor)
        os.fchmod(root_descriptor, 0o700)
        os.close(root_descriptor)
        root_descriptor = None
        final = os.stat(root.name, dir_fd=parent_descriptor, follow_symlinks=False)
        final_identity = OwnedDirectoryIdentity(final.st_dev, final.st_ino, final.st_uid)
        if final_identity != observed or not stat.S_ISDIR(final.st_mode):
            raise RuntimeError("portable cleanup root identity changed")
        os.rmdir(root.name, dir_fd=parent_descriptor)
    finally:
        if root_descriptor is not None:
            os.close(root_descriptor)
        os.close(parent_descriptor)


def _remove_owned_children(directory_descriptor: int) -> None:
    with os.scandir(directory_descriptor) as entries:
        for entry in entries:
            details = entry.stat(follow_symlinks=False)
            if stat.S_ISREG(details.st_mode) and details.st_nlink == 1:
                descriptor = os.open(
                    entry.name,
                    os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=directory_descriptor,
                )
                try:
                    opened = os.fstat(descriptor)
                    if (opened.st_dev, opened.st_ino) != (
                        details.st_dev,
                        details.st_ino,
                    ):
                        raise RuntimeError("portable cleanup node identity changed")
                    os.fchmod(descriptor, 0o600)
                finally:
                    os.close(descriptor)
                os.unlink(entry.name, dir_fd=directory_descriptor)
            elif stat.S_ISDIR(details.st_mode) and not stat.S_ISLNK(details.st_mode):
                child = os.open(
                    entry.name,
                    os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=directory_descriptor,
                )
                try:
                    opened = os.fstat(child)
                    if (opened.st_dev, opened.st_ino) != (
                        details.st_dev,
                        details.st_ino,
                    ):
                        raise RuntimeError("portable cleanup node identity changed")
                    _remove_owned_children(child)
                    os.fchmod(child, 0o700)
                finally:
                    os.close(child)
                os.rmdir(entry.name, dir_fd=directory_descriptor)
            else:
                raise RuntimeError("portable cleanup encountered unexpected node")


def _remove_materialized_root(
    root: Path,
    expected: OwnedDirectoryIdentity,
) -> None:
    try:
        if _directory_identity(root) != expected:
            raise RuntimeError("portable cleanup root identity changed")
    except FileNotFoundError:
        return
    _remove_materialized_children(root)
    if _directory_identity(root) != expected:
        raise RuntimeError("portable cleanup root identity changed")
    root.chmod(0o700)
    root.rmdir()


def _remove_materialized_children(root: Path) -> None:
    with os.scandir(root) as entries:
        for entry in entries:
            path = root / entry.name
            details = entry.stat(follow_symlinks=False)
            if stat.S_ISREG(details.st_mode) and details.st_nlink == 1:
                path.chmod(0o600)
                path.unlink()
            elif stat.S_ISDIR(details.st_mode) and not stat.S_ISLNK(details.st_mode):
                _remove_materialized_children(path)
                path.chmod(0o700)
                path.rmdir()
            else:
                raise RuntimeError("portable cleanup encountered unexpected node")


__all__ = [
    "MaterializedView",
    "MaterializedWorkspace",
    "OwnedDirectoryIdentity",
    "_directory_identity",
    "_remove_attempt_root",
]
