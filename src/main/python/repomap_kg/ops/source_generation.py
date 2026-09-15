"""Bounded content-aware source inventory generation for polling."""

from __future__ import annotations

from dataclasses import dataclass
import fnmatch
import hashlib
import os
from pathlib import Path
import stat
import time
from threading import Event
from typing import Callable, Sequence

from repomap_kg.coordinator.windows_security import (
    WindowsPathError,
    WindowsSecurityError,
    reject_reparse_path,
    validate_supported_windows_path,
)
from repomap_kg.graph.discovery import (
    DEFAULT_DISCOVERY_EXCLUDE_PATHS,
    normalize_discovery_exclude_paths,
)
from repomap_kg.ops.generations import source_generation_records


@dataclass(frozen=True)
class SourceGenerationLimits:
    """Conservative bounds for one polling inventory."""

    max_files: int = 10_000
    max_file_bytes: int = 16 * 1024 * 1024
    max_total_bytes: int = 512 * 1024 * 1024
    chunk_bytes: int = 1024 * 1024
    max_file_retries: int = 2
    max_path_chars: int = 1024
    timeout_seconds: float = 30.0

    def validate(self) -> "SourceGenerationLimits":
        if (
            self.max_files <= 0
            or self.max_file_bytes <= 0
            or self.max_total_bytes <= 0
            or self.chunk_bytes <= 0
            or self.max_file_retries < 0
            or self.max_path_chars <= 0
            or self.timeout_seconds <= 0
        ):
            raise ValueError("source generation limits are invalid")
        return self


DEFAULT_SOURCE_GENERATION_LIMITS = SourceGenerationLimits()


@dataclass(frozen=True)
class SourceGenerationResult:
    """Private generation evidence with bounded public projection."""

    category: str
    generation: str | None
    file_count: int
    total_bytes: int

    def to_public(self) -> dict[str, int | str]:
        """Return path-free bounded polling diagnostics."""

        return {
            "category": self.category,
            "file_count": self.file_count,
            "total_bytes": self.total_bytes,
        }


class _Cancelled(Exception):
    pass


class _LimitExceeded(Exception):
    pass


class _SourceUnavailable(Exception):
    pass


class _SourceInvalid(Exception):
    pass


class _SourceTimeout(Exception):
    pass


class _SourceUnstable(Exception):
    pass


def scan_source_generation(
    root: Path | str,
    *,
    exclude_paths: Sequence[str] = (),
    limits: SourceGenerationLimits = DEFAULT_SOURCE_GENERATION_LIMITS,
    cancel_event: Event | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> SourceGenerationResult:
    """Scan one configured root without loading the repository into memory."""

    limits.validate()
    started = monotonic()
    deadline = started + limits.timeout_seconds
    file_count = 0
    total_bytes = 0
    records: list[tuple[str, str, str]] = []
    try:
        repository_root = _validate_root(Path(root), limits)
        excludes = normalize_discovery_exclude_paths(exclude_paths)
        excluded = tuple(DEFAULT_DISCOVERY_EXCLUDE_PATHS) + excludes
        total_bytes = _scan_directory(
            repository_root,
            repository_root,
            excluded,
            limits,
            cancel_event,
            monotonic,
            deadline,
            records,
        )
        file_count = len(records)
        for _, _, _digest in records:
            _check_cancel_or_timeout(cancel_event, monotonic, deadline)
        return SourceGenerationResult(
            "ready",
            source_generation_records(records),
            file_count,
            total_bytes,
        )
    except _Cancelled:
        return SourceGenerationResult("cancelled", None, file_count, total_bytes)
    except _SourceTimeout:
        return SourceGenerationResult("source_timeout", None, file_count, total_bytes)
    except _SourceUnstable:
        return SourceGenerationResult("source_unstable", None, file_count, total_bytes)
    except _LimitExceeded:
        return SourceGenerationResult("source_limit_exceeded", None, file_count, total_bytes)
    except _SourceInvalid:
        return SourceGenerationResult("source_invalid", None, file_count, total_bytes)
    except _SourceUnavailable:
        return SourceGenerationResult("source_unavailable", None, file_count, total_bytes)
    except (OSError, UnicodeError):
        return SourceGenerationResult("source_unavailable", None, file_count, total_bytes)
    except (ValueError, WindowsPathError, WindowsSecurityError):
        return SourceGenerationResult("source_invalid", None, file_count, total_bytes)


def _validate_root(root: Path, limits: SourceGenerationLimits) -> Path:
    raw = os.fspath(root)
    if os.name == "nt":  # pragma: no cover - native Windows workflow
        validate_supported_windows_path(raw)
    try:
        details = root.lstat()
    except FileNotFoundError as error:
        raise _SourceUnavailable from error
    except OSError as error:
        raise _SourceUnavailable from error
    if root.is_symlink() or not stat.S_ISDIR(details.st_mode):
        raise _SourceInvalid
    if os.name == "nt":  # pragma: no cover - native Windows workflow
        reject_reparse_path(root)
    resolved = root.resolve()
    if len(os.fspath(resolved)) > limits.max_path_chars:
        raise _LimitExceeded
    if os.name == "nt":  # pragma: no cover - native Windows workflow
        reject_reparse_path(resolved)
    return resolved


def _scan_directory(
    root: Path,
    directory: Path,
    excludes: Sequence[str],
    limits: SourceGenerationLimits,
    cancel_event: Event | None,
    monotonic: Callable[[], float],
    deadline: float,
    records: list[tuple[str, str, str]],
) -> int:
    total_bytes = 0
    try:
        directory_before = directory.stat()
    except OSError as error:
        raise _SourceUnavailable from error
    try:
        with os.scandir(directory) as iterator:
            entries = sorted(iterator, key=lambda entry: entry.name)
    except OSError as error:
        raise _SourceUnavailable from error
    for entry in entries:
        _check_cancel_or_timeout(cancel_event, monotonic, deadline)
        path = Path(entry.path)
        relative = path.relative_to(root).as_posix()
        if len(relative) > limits.max_path_chars:
            raise _LimitExceeded
        if _is_excluded(relative, excludes):
            continue
        try:
            details = entry.stat(follow_symlinks=False)
        except OSError as error:
            raise _SourceUnavailable from error
        if entry.is_symlink() or _is_reparse(details):
            raise _SourceInvalid
        if stat.S_ISDIR(details.st_mode):
            try:
                current = path.lstat()
            except OSError as error:
                raise _SourceUnavailable from error
            if path.is_symlink() or _is_reparse(current):
                raise _SourceInvalid
            total_bytes += _scan_directory(
                root,
                path,
                excludes,
                limits,
                cancel_event,
                monotonic,
                deadline,
                records,
            )
            if total_bytes > limits.max_total_bytes:
                raise _LimitExceeded
            continue
        if not stat.S_ISREG(details.st_mode):
            raise _SourceInvalid
        if len(records) >= limits.max_files:
            raise _LimitExceeded
        stable = _read_stable_file(
            path,
            limits,
            cancel_event,
            monotonic,
            deadline,
        )
        if stable is None:
            raise _SourceUnstable
        digest, size = stable
        total_bytes += size
        if total_bytes > limits.max_total_bytes:
            raise _LimitExceeded
        records.append((relative, "file", digest))
    try:
        directory_after = directory.stat()
    except OSError as error:
        raise _SourceUnavailable from error
    if _directory_signature(directory_before) != _directory_signature(directory_after):
        raise _SourceUnstable
    return total_bytes


def _read_stable_file(
    path: Path,
    limits: SourceGenerationLimits,
    cancel_event: Event | None,
    monotonic: Callable[[], float],
    deadline: float,
) -> tuple[str, int] | None:
    for _attempt in range(limits.max_file_retries + 1):
        _check_cancel_or_timeout(cancel_event, monotonic, deadline)
        try:
            before_lstat = path.lstat()
            if path.is_symlink() or _is_reparse(before_lstat):
                raise _SourceInvalid
            before = path.stat()
            if before.st_size > limits.max_file_bytes:
                raise _LimitExceeded
            digest = hashlib.sha256()
            flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
            flags |= getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(path, flags)
            with os.fdopen(descriptor, "rb") as source:
                while True:
                    _check_cancel_or_timeout(cancel_event, monotonic, deadline)
                    chunk = source.read(limits.chunk_bytes)
                    if not chunk:
                        break
                    digest.update(chunk)
            after = path.stat()
        except _LimitExceeded:
            raise
        except (OSError, UnicodeError) as error:
            raise _SourceUnavailable from error
        if after.st_size > limits.max_file_bytes:
            raise _LimitExceeded
        after_lstat = path.lstat()
        if path.is_symlink() or _is_reparse(after_lstat):
            raise _SourceInvalid
        if _file_signature(before) == _file_signature(after):
            return digest.hexdigest(), after.st_size
    return None


def _file_signature(details: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        details.st_mode,
        details.st_size,
        details.st_mtime_ns,
        details.st_ctime_ns,
        details.st_ino,
    )


def _directory_signature(details: os.stat_result) -> tuple[int, int, int, int]:
    return (
        details.st_mode,
        details.st_mtime_ns,
        details.st_ctime_ns,
        details.st_ino,
    )


def _is_reparse(details: os.stat_result) -> bool:
    return bool(getattr(details, "st_file_attributes", 0) & 0x400)


def _is_excluded(relative: str, excludes: Sequence[str]) -> bool:
    parts = relative.split("/")
    for pattern in excludes:
        if any(marker in pattern for marker in "*?["):
            candidate = relative
            while candidate:
                if fnmatch.fnmatchcase(candidate, pattern):
                    return True
                if "/" not in candidate:
                    break
                candidate = candidate.rsplit("/", 1)[0]
            continue
        if "/" not in pattern and pattern in parts:
            return True
        if relative == pattern or relative.startswith(f"{pattern}/"):
            return True
    return False


def _check_cancel_or_timeout(
    cancel_event: Event | None,
    monotonic: Callable[[], float],
    deadline: float,
) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise _Cancelled
    if monotonic() >= deadline:
        raise _SourceTimeout


__all__ = [
    "DEFAULT_SOURCE_GENERATION_LIMITS",
    "SourceGenerationLimits",
    "SourceGenerationResult",
    "scan_source_generation",
]
