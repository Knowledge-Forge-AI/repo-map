"""Filesystem authority checks for private refresh capabilities."""

from __future__ import annotations

import os
from pathlib import Path
import stat

from repomap_kg.coordinator._refresh_contracts import RefreshConfigurationError
from repomap_kg.coordinator.windows_security import (
    WindowsSecurityError,
    reject_reparse_path,
    validate_owner_private_acl,
)


def validate_private_directory(path: Path) -> None:
    try:
        if os.name == "nt":  # pragma: no cover - native Windows runner
            reject_reparse_path(path)
        details = path.lstat()
    except (OSError, WindowsSecurityError):
        raise ValueError("invalid refresh capability") from None
    if os.name == "nt":  # pragma: no cover - native Windows runner
        try:
            if not stat.S_ISDIR(details.st_mode):
                raise ValueError("invalid refresh capability")
            validate_owner_private_acl(path)
            return
        except WindowsSecurityError:
            raise ValueError("invalid refresh capability") from None
    if (
        not stat.S_ISDIR(details.st_mode)
        or details.st_uid != os.getuid()
        or stat.S_IMODE(details.st_mode) & 0o077
    ):
        raise ValueError("invalid refresh capability")


def validate_config_file(path: Path) -> None:
    try:
        if os.name == "nt":  # pragma: no cover - native Windows runner
            reject_reparse_path(path)
        details = path.lstat()
    except (OSError, WindowsSecurityError):
        raise ValueError("invalid refresh capability") from None
    if os.name == "nt":  # pragma: no cover - native Windows runner
        if not stat.S_ISREG(details.st_mode) or os.access(path, os.W_OK):
            raise ValueError("invalid refresh capability")
        return
    mode = stat.S_IMODE(details.st_mode)
    safe_file = stat.S_ISREG(details.st_mode) and not mode & 0o022
    safe_home = stat.S_ISDIR(details.st_mode) and not mode & 0o077
    if details.st_uid != os.getuid() or not (safe_file or safe_home):
        raise ValueError("invalid refresh capability")


def validate_psql(path: Path) -> None:
    validate_psql_lexical(path)
    try:
        if os.name == "nt":  # pragma: no cover - native Windows runner
            reject_reparse_path(path)
            target = path
        else:
            target = path.resolve(strict=True)
        details = target.stat()
    except (OSError, WindowsSecurityError):
        raise RefreshConfigurationError("invalid refresh capability") from None
    if (
        not stat.S_ISREG(details.st_mode)
        or (os.name != "nt" and stat.S_IMODE(details.st_mode) & 0o022)
        or not os.access(target, os.X_OK)
        or (os.name == "nt" and os.access(target, os.W_OK))
    ):
        raise RefreshConfigurationError("invalid refresh capability")


def validate_psql_lexical(
    path: Path, *, platform_name: str | None = None
) -> None:
    """Validate the approved invocation path without following indirection."""

    if (
        not isinstance(path, Path)
        or not path.is_absolute()
        or ".." in path.parts
        or not is_psql_executable_name(path, platform_name=platform_name)
    ):
        raise RefreshConfigurationError("invalid refresh capability")


def is_psql_executable_name(path: Path, *, platform_name: str | None = None) -> bool:
    """Return whether a path has the platform's approved PostgreSQL client name."""

    expected = "psql.exe" if (platform_name or os.name) == "nt" else "psql"
    return path.name.lower() == expected


def validate_search_path(paths: tuple[Path, ...]) -> None:
    try:
        if os.name == "nt":
            for path in paths:
                reject_reparse_path(path)
        details = [path.stat() for path in paths]
    except (OSError, WindowsSecurityError):
        raise ValueError("invalid refresh capability") from None
    if any(
        not stat.S_ISDIR(item.st_mode)
        or (os.name != "nt" and stat.S_IMODE(item.st_mode) & 0o022)
        or (os.name != "nt" and item.st_uid not in {0, os.getuid()})
        or (os.name == "nt" and os.access(path, os.W_OK))
        for path, item in zip(paths, details)
    ):
        raise ValueError("invalid refresh capability")


__all__ = [
    "is_psql_executable_name",
    "validate_config_file",
    "validate_private_directory",
    "validate_psql",
    "validate_psql_lexical",
    "validate_search_path",
]
