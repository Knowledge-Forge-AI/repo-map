"""Physical file capture, hashing, and inventory collection for multi-source graphs."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
import hashlib
import os
from pathlib import Path
import stat
import sys
from typing import TYPE_CHECKING, Any

from common_lore_index.artifacts.sealing_governance import SealingBudgetExceeded

from common_lore_index.graph._capture_contracts import (
    MultiSourceCaptureError, _SourceCapture, _SourceChanged, _SourceInvalid,
    _SourceUnavailable, _file_signature,
)
from common_lore_index.graph.discovery import discover_repository
from common_lore_index.graph.discovery_records import FileInfo
from common_lore_index.graph.multi_source import (
    SnapshotManifestEntry,
    SourceKind,
    SourceSnapshot,
)
from common_lore_index.ops.config_binding_records import OpsGraphSourceBindingConfig
from common_lore_index.ops.config_records import OpsGraphConfig

if TYPE_CHECKING:
    from common_lore_index.artifacts._sealing_meter import SealingMeter


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
            flags |= getattr(os, "O_NONBLOCK", 0)
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
    io_meter: SealingMeter | None = None,
) -> tuple[tuple[FileInfo, ...], tuple[tuple[str, int], ...]]:
    if io_meter is not None and stage_root is not None:
        raise ValueError("metered capture never stages semantic copies")
    files: list[FileInfo] = []
    sizes: list[tuple[str, int]] = []
    for item in discovered:
        relative = Path(item.path)
        if relative.is_absolute() or ".." in relative.parts:
            raise _SourceInvalid
        stage_path = stage_root / item.path if stage_root is not None else None
        if io_meter is not None:
            from common_lore_index.graph._metered_capture import read_stable_file_metered

            digest, size, executable = read_stable_file_metered(root / item.path, io_meter)
        else:
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
    io_meter: SealingMeter | None = None,
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
        facade = sys.modules.get("common_lore_index.graph.multi_source_pipeline")
        discover_fn = (
            getattr(facade, "discover_repository", discover_repository)
            if facade is not None
            else discover_repository
        )
    # Metered keywords are forwarded only for an explicit meter (default seams).
    # The caller binds the meter to discovery hooks so graph.discovery stays
    # free of artifacts imports (D12 Rust-qualification closure).
    metered: dict[str, Any] = {} if io_meter is None else {"io_meter": io_meter}
    discover_metered: dict[str, Any] = {}
    if io_meter is not None:
        from common_lore_index.graph._metered_discovery import MeteredDiscoveryHooks

        discover_metered["io_hooks"] = MeteredDiscoveryHooks(io_meter)
    captured: list[_CapturedSource] = []
    for binding in sorted(bindings, key=lambda item: item.binding_id):
        root = Path(binding.root_path_expanded)
        try:
            if not root.is_dir():
                raise _SourceUnavailable
            discovered = tuple(
                discover_fn(root, exclude_paths=binding.exclude_paths, **discover_metered)
            )
            binding_stage_root = (
                stage_root / binding.alias if stage_root is not None else None
            )
            files, sizes = _capture_files(
                root,
                discovered,
                stage_root=binding_stage_root,
                **metered,
            )
            snapshot = SourceSnapshot.create(
                binding.domain_binding(graph.id),
                manifest_entries=_manifest(root, files, dict(sizes)),
                git_commit=None,
                git_tree=None,
                ignore_policy_id="ignore1:declared-selection",
                metadata_identity="meta1:content-manifest-v1",
            )
        except (MultiSourceCaptureError, SealingBudgetExceeded):
            raise  # A7: a governed refusal never becomes a capture category
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
