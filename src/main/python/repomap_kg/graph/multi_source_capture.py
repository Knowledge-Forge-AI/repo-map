"""Physical file capture, hashing, and inventory collection for multi-source graphs."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
import hashlib
import os
from pathlib import Path
import stat
import sys

from repomap_kg.graph.discovery import discover_repository
from repomap_kg.graph.discovery_records import FileInfo
from repomap_kg.graph.multi_source import (
    SnapshotManifestEntry,
    SourceKind,
    SourceSnapshot,
)
from repomap_kg.ops.config_binding_records import OpsGraphSourceBindingConfig
from repomap_kg.ops.config_records import OpsGraphConfig


class MultiSourceCaptureError(ValueError):
    """Public-safe fail-closed multi-source capture error."""

    def __init__(self, message: str, *, category: str = "source_capture") -> None:
        self.category = category
        super().__init__(message)


class _SourceUnavailable(Exception):
    """A configured source could not be opened or no longer exists."""


class _SourceChanged(Exception):
    """A selected source entry changed while it was being captured."""


class _SourceCapture(Exception):
    """A source entry could not be captured safely."""


class _SourceInvalid(Exception):
    """A source inventory contains an unsupported or unsafe entry."""


@dataclass(frozen=True)
class _CapturedSource:
    config: OpsGraphSourceBindingConfig
    root: Path
    files: tuple[FileInfo, ...]
    snapshot: SourceSnapshot
    file_sizes: tuple[tuple[str, int], ...]
    staged_root: Path | None = None


def _manifest(
    root: Path,
    files: Sequence[FileInfo],
    sizes: Mapping[str, int] | None = None,
) -> tuple[SnapshotManifestEntry, ...]:
    return tuple(
        SnapshotManifestEntry(
            item.path,
            item.content_hash,
            (sizes[item.path] if sizes is not None else (root / item.path).stat().st_size),
            item.executable,
        )
        for item in files
    )


def _file_signature(details: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        details.st_mode,
        details.st_size,
        details.st_mtime_ns,
        details.st_ctime_ns,
        details.st_ino,
        details.st_dev,
    )


def _read_stable_file(
    path: Path,
    *,
    stage_path: Path | None = None,
) -> tuple[str, int, bool]:
    """Read one regular file while binding content, size, and executable mode.

    The descriptor is opened without following the final symlink and is
    checked before and after the read.  A staged copy is written from the same
    descriptor when full semantic capture requests one.
    """

    for _attempt in range(3):
        descriptor: int | None = None
        try:
            before = path.lstat()
            if path.is_symlink() or not stat.S_ISREG(before.st_mode):
                raise _SourceInvalid
            flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
            flags |= getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(path, flags)
            opened = os.fstat(descriptor)
            if _file_signature(before) != _file_signature(opened):
                os.close(descriptor)
                descriptor = None
                continue
            digest = hashlib.sha256()
            destination = None
            if stage_path is not None:
                stage_path.parent.mkdir(parents=True, exist_ok=True)
                destination = stage_path.open("wb")
            try:
                with os.fdopen(descriptor, "rb", closefd=True) as source:
                    descriptor = None
                    while True:
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        digest.update(chunk)
                        if destination is not None:
                            destination.write(chunk)
                    after = os.fstat(source.fileno())
            finally:
                if destination is not None:
                    destination.close()
            if _file_signature(opened) != _file_signature(after):
                if stage_path is not None:
                    stage_path.unlink(missing_ok=True)
                continue
            if stage_path is not None:
                stage_path.chmod(0o555 if bool(after.st_mode & 0o111) else 0o444)
            return digest.hexdigest(), after.st_size, bool(after.st_mode & 0o111)
        except _SourceInvalid:
            raise
        except FileNotFoundError as error:
            raise _SourceChanged from error
        except PermissionError as error:
            raise _SourceCapture from error
        except OSError as error:
            raise _SourceCapture from error
        finally:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
    raise _SourceChanged


def _capture_files(
    root: Path,
    discovered: Sequence[FileInfo],
    *,
    stage_root: Path | None = None,
) -> tuple[tuple[FileInfo, ...], tuple[tuple[str, int], ...]]:
    files: list[FileInfo] = []
    sizes: list[tuple[str, int]] = []
    for item in discovered:
        relative = Path(item.path)
        if relative.is_absolute() or ".." in relative.parts:
            raise _SourceInvalid
        stage_path = stage_root / item.path if stage_root is not None else None
        digest, size, executable = _read_stable_file(
            root / item.path,
            stage_path=stage_path,
        )
        files.append(replace(item, content_hash=digest, executable=executable))
        sizes.append((item.path, size))
    return tuple(files), tuple(sizes)


def _inventory_error(error: Exception) -> MultiSourceCaptureError:
    if isinstance(error, _SourceUnavailable):
        return MultiSourceCaptureError("source unavailable", category="source_unavailable")
    if isinstance(error, _SourceChanged):
        return MultiSourceCaptureError(
            "source binding changed during capture", category="source_changed"
        )
    if isinstance(error, _SourceInvalid):
        return MultiSourceCaptureError("source inventory is invalid", category="source_invalid")
    return MultiSourceCaptureError("source capture failed", category="source_capture")


def _capture_inventory(
    graph: OpsGraphConfig,
    *,
    stage_root: Path | None = None,
    discover_fn: Callable[..., Sequence[FileInfo]] | None = None,
) -> tuple[_CapturedSource, ...]:
    bindings = graph.effective_source_bindings
    if (
        not graph.explicit_source_bindings
        or not bindings
        or any(not item.enabled for item in bindings)
        or any(
            item.source_kind not in {SourceKind.FOLDER, SourceKind.GIT_WORKING_TREE}
            for item in bindings
        )
    ):
        raise MultiSourceCaptureError(
            "source binding inventory is unsupported", category="source_invalid"
        )
    if discover_fn is None:
        facade = sys.modules.get("repomap_kg.graph.multi_source_pipeline")
        discover_fn = (
            getattr(facade, "discover_repository", discover_repository)
            if facade is not None
            else discover_repository
        )
    captured: list[_CapturedSource] = []
    for binding in sorted(bindings, key=lambda item: item.binding_id):
        root = Path(binding.root_path_expanded)
        try:
            if not root.is_dir():
                raise _SourceUnavailable
            discovered = tuple(
                discover_fn(root, exclude_paths=binding.exclude_paths)
            )
            binding_stage_root = (
                stage_root / binding.alias if stage_root is not None else None
            )
            files, sizes = _capture_files(
                root,
                discovered,
                stage_root=binding_stage_root,
            )
            snapshot = SourceSnapshot.create(
                binding.domain_binding(graph.id),
                manifest_entries=_manifest(root, files, dict(sizes)),
                git_commit=None,
                git_tree=None,
                ignore_policy_id="ignore1:declared-selection",
                metadata_identity="meta1:content-manifest-v1",
            )
        except MultiSourceCaptureError:
            raise
        except FileNotFoundError as error:
            raise _inventory_error(_SourceUnavailable()) from error
        except OSError as error:
            raise _inventory_error(_SourceCapture()) from error
        except ValueError as error:
            raise _inventory_error(_SourceInvalid()) from error
        except (_SourceUnavailable, _SourceChanged, _SourceCapture, _SourceInvalid) as error:
            raise _inventory_error(error) from error
        captured.append(
            _CapturedSource(
                binding,
                root,
                files,
                snapshot,
                sizes,
                binding_stage_root,
            )
        )
    return tuple(captured)


__all__ = [
    "MultiSourceCaptureError",
    "_CapturedSource",
    "_capture_files",
    "_capture_inventory",
    "_file_signature",
    "_inventory_error",
    "_manifest",
    "_read_stable_file",
]
