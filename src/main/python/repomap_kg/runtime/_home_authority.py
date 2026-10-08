"""Owner-private setup directories and generated credential file authority."""

from __future__ import annotations

import os
from pathlib import Path
import stat

from repomap_kg.coordinator._refresh_capability_io import validate_private_directory
from repomap_kg.coordinator.windows_security import (
    WindowsSecurityError, apply_owner_private_acl, reject_reparse_path,
    validate_owner_private_acl,
)


def ensure_private_directory(path: Path) -> bool:
    """Create privately or validate existing authority; never repair its mode."""
    try:
        if os.name == "nt":
            reject_reparse_path(path)
        try:
            path.mkdir(mode=0o700, parents=True)
        except FileExistsError:
            created = False
        else:
            created = True
            if os.name == "nt":
                apply_owner_private_acl(path)
        validate_private_directory(path)
        return created
    except (OSError, ValueError, WindowsSecurityError):
        raise ValueError("repo-map-home-unsafe") from None


def validate_private_file(path: Path, details: os.stat_result | None = None) -> None:
    """Require an ordinary owner-private file, including opened-file metadata."""
    try:
        if os.name == "nt":
            reject_reparse_path(path)
            validate_owner_private_acl(path)
        details = path.lstat() if details is None else details
    except (OSError, WindowsSecurityError):
        raise ValueError("generated-local-admin-credential-unsafe") from None
    if not stat.S_ISREG(details.st_mode) or (
        os.name != "nt" and (
            details.st_uid != os.getuid() or stat.S_IMODE(details.st_mode) & 0o077
        )
    ):
        raise ValueError("generated-local-admin-credential-unsafe")


def create_private_file(path: Path, text: str) -> None:
    """Create exclusively with privacy established before any secret is written."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        with os.fdopen(os.open(path, flags, 0o600), "w", encoding="utf-8") as stream:
            if os.name == "nt":
                reject_reparse_path(path)
                apply_owner_private_acl(path)
            validate_private_file(path, os.fstat(stream.fileno()))
            stream.write(text)
    except (OSError, ValueError, WindowsSecurityError):
        raise ValueError("generated-local-admin-credential-unsafe") from None


def read_private_runtime_env(home: Path) -> str:
    """Bounded non-following read of setup's private runtime credential file."""
    try:
        validate_private_directory(home)
        validate_private_directory(home / "runtime")
        path = home / "runtime" / ".env"
        validate_private_file(path)
        before = path.lstat()
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        with os.fdopen(os.open(path, flags), "rb") as stream:
            opened = os.fstat(stream.fileno())
            validate_private_file(path, opened)
            if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
                raise ValueError("changed credential authority")
            data = stream.read(65537)
        if len(data) > 65536:
            raise ValueError("oversized credential authority")
        return data.decode("utf-8")
    except (OSError, ValueError, WindowsSecurityError):
        raise ValueError("generated-local-admin-credential-unsafe") from None
