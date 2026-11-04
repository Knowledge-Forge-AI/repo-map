"""Bounded, nonblocking regular-file reads for inert component artifacts."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import os
from pathlib import Path
import stat
from types import MappingProxyType

from retrieval_semantic_pair_artifacts import digest_bytes, refuse


MAX_COMPONENT_MEMBER_BYTES = 32 * 1024 * 1024
MODEL_MEMBERS = (
    "declaration.json", "report.json", "source-manifest.json", "sources.zip",
    "terminal.json",
)


def owned_path(value: object) -> Path:
    """Require an absolute path with no symlink ancestor or traversal."""
    if not isinstance(value, (str, os.PathLike)):
        raise refuse("component_path")
    try:
        path = Path(value)
        unsafe = not path.is_absolute() or ".." in path.parts or any(
            parent.is_symlink() for parent in path.parents
        )
    except (TypeError, ValueError, OSError):
        raise refuse("component_path") from None
    if unsafe:
        raise refuse("component_path")
    return path


def file_identity(value: os.stat_result) -> tuple[int, ...]:
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


@dataclass(frozen=True)
class FileSnapshot:
    """Internal bytes and filesystem identity; never serialized in a dossier."""

    path: Path
    raw: bytes
    identity: tuple[int, ...]
    limit: int

    @property
    def binding(self) -> dict[str, object]:
        return {"sha256": digest_bytes(self.raw), "length": len(self.raw)}


def capture_file(value: object, *, limit: int = MAX_COMPONENT_MEMBER_BYTES) -> FileSnapshot:
    """Refuse special files before opening and again before any read."""
    path = owned_path(value)
    if type(limit) is not int or not 0 < limit <= MAX_COMPONENT_MEMBER_BYTES:
        raise refuse("component_limit")
    descriptor = None
    try:
        initial = path.lstat()
        if not stat.S_ISREG(initial.st_mode):
            raise refuse("component_file_unsafe")
        if not 0 <= initial.st_size <= limit:
            raise refuse("component_file_size")
        flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or file_identity(initial) != file_identity(opened):
            raise refuse("component_file_changed")
        chunks: list[bytes] = []
        remaining = opened.st_size
        while remaining:
            part = os.read(descriptor, min(remaining, 1024 * 1024))
            if not part:
                raise refuse("component_file_changed")
            chunks.append(part)
            remaining -= len(part)
        if file_identity(opened) != file_identity(os.fstat(descriptor)) or (
            file_identity(opened) != file_identity(path.lstat())
        ):
            raise refuse("component_file_changed")
        return FileSnapshot(path, b"".join(chunks), file_identity(opened), limit)
    except (OSError, ValueError) as error:
        if hasattr(error, "code"):
            raise
        raise refuse("component_file_unreadable") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def verify_unchanged(snapshots: Iterable[FileSnapshot]) -> None:
    """Re-read across composed builders; this does not promise atomic snapshots."""
    for previous in snapshots:
        current = capture_file(previous.path, limit=previous.limit)
        if previous.identity != current.identity or previous.raw != current.raw:
            raise refuse("component_source_changed")


def _directory_members(root: Path) -> tuple[int, int]:
    try:
        info = root.lstat()
        if not stat.S_ISDIR(info.st_mode):
            raise refuse("component_directory_unsafe")
        names: set[str] = set()
        with os.scandir(root) as entries:
            for entry in entries:
                names.add(entry.name)
                if len(names) > len(MODEL_MEMBERS):
                    raise refuse("component_members")
        if names != set(MODEL_MEMBERS):
            raise refuse("component_members")
        return info.st_dev, info.st_ino
    except OSError:
        raise refuse("component_directory_unreadable") from None


def capture_model_members(value: object) -> tuple[FileSnapshot, ...]:
    root = owned_path(value)
    identity = _directory_members(root)
    snapshots = tuple(capture_file(root / name) for name in MODEL_MEMBERS)
    if any(not item.raw for item in snapshots):
        raise refuse("component_file_size")
    if _directory_members(root) != identity:
        raise refuse("component_source_changed")
    verify_unchanged(snapshots)
    return snapshots


def read_model_members(value: object) -> Mapping[str, bytes]:
    """Read exactly five complete members without executing their content."""
    return MappingProxyType({item.path.name: item.raw for item in capture_model_members(value)})


__all__ = [
    "FileSnapshot", "MAX_COMPONENT_MEMBER_BYTES", "MODEL_MEMBERS",
    "capture_file", "capture_model_members", "file_identity", "owned_path",
    "read_model_members", "verify_unchanged",
]
