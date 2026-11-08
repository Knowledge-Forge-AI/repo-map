"""Repository traversal selection, re-exported unchanged by ``graph.discovery``.

``selected_files`` is the incumbent ``discover_repository`` selection loop over
any ``os.walk``-shaped top-down walk, so the default ``os.walk`` route and the
metered governed walker share one ordering and filtering implementation.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
import fnmatch
from pathlib import Path, PurePosixPath
from typing import Sequence


IGNORED_DIR_NAMES = frozenset(
    {
        ".git",
        ".direnv",
        ".hg",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".serena",
        ".terraform",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "htmlcov",
        "node_modules",
    }
)
DEFAULT_DISCOVERY_EXCLUDE_PATHS = tuple(sorted(IGNORED_DIR_NAMES))


def normalize_discovery_exclude_paths(
    exclude_paths: Sequence[str] = (),
) -> tuple[str, ...]:
    normalized: list[str] = []
    for exclude_path in exclude_paths:
        if not isinstance(exclude_path, str):
            raise ValueError("exclude path must be a string")
        candidate = exclude_path.strip().replace("\\", "/")
        while candidate.startswith("./"):
            candidate = candidate[2:]
        candidate = candidate.rstrip("/")
        parsed = PurePosixPath(candidate)
        if not candidate or parsed.is_absolute() or ".." in parsed.parts:
            raise ValueError("exclude path must stay relative to the repository root")
        normalized.append(candidate)
    return tuple(normalized)


def _matches_glob(relative_path: str, pattern: str) -> bool:
    candidate = relative_path
    while candidate:
        if fnmatch.fnmatchcase(candidate, pattern):
            return True
        if "/" not in candidate:
            break
        candidate = candidate.rsplit("/", 1)[0]
    return False


def _is_excluded_relative_path(
    relative_path: str,
    exclude_paths: Sequence[str],
) -> bool:
    relative_path = relative_path.strip("/")
    if not relative_path:
        return False
    parts = relative_path.split("/")
    for exclude_path in exclude_paths:
        if any(marker in exclude_path for marker in "*?["):
            if _matches_glob(relative_path, exclude_path):
                return True
            continue
        if "/" not in exclude_path and exclude_path in parts:
            return True
        if relative_path == exclude_path or relative_path.startswith(
            f"{exclude_path}/"
        ):
            return True
    return False


def _relative_posix_path(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _resolved_path_stays_under(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root)
    except ValueError:
        return False
    return True


def selected_files(
    repository_root: Path,
    configured_excludes: Sequence[str],
    walk: Iterable[tuple[str, list[str], list[str]]],
) -> Iterator[Path]:
    """Yield selected regular files in incumbent order, pruning ``dirnames`` in place."""

    for directory, dirnames, filenames in walk:
        directory_path = Path(directory)
        kept_dirnames = []
        for dirname in sorted(dirnames):
            dir_path = directory_path / dirname
            relative_dir = _relative_posix_path(repository_root, dir_path)
            if dir_path.is_symlink() and not _resolved_path_stays_under(
                repository_root, dir_path
            ):
                continue
            if dirname in IGNORED_DIR_NAMES or _is_excluded_relative_path(
                relative_dir, configured_excludes
            ):
                continue
            kept_dirnames.append(dirname)
        dirnames[:] = kept_dirnames
        for filename in sorted(filenames):
            file_path = directory_path / filename
            relative_file = _relative_posix_path(repository_root, file_path)
            if file_path.is_symlink() and not _resolved_path_stays_under(
                repository_root, file_path
            ):
                continue
            if not file_path.is_file():
                continue
            if _is_excluded_relative_path(relative_file, configured_excludes):
                continue
            yield file_path


__all__ = (
    "DEFAULT_DISCOVERY_EXCLUDE_PATHS",
    "IGNORED_DIR_NAMES",
    "_is_excluded_relative_path",
    "_matches_glob",
    "_relative_posix_path",
    "_resolved_path_stays_under",
    "normalize_discovery_exclude_paths",
    "selected_files",
)
