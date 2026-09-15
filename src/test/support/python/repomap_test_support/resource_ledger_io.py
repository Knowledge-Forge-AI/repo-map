"""Restrictive atomic JSON persistence for private test-resource evidence."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any


class PrivateJsonError(RuntimeError):
    """Private evidence is missing, unsafe, or malformed."""


def read_private_json(path: Path) -> dict[str, Any]:
    path = Path(path)
    _require_link_safe_parent(path.parent)
    if path.is_symlink() or not path.is_file():
        raise PrivateJsonError("private evidence must be a plain file")
    try:
        metadata = path.stat(follow_symlinks=False)
    except OSError as error:
        raise PrivateJsonError("private evidence metadata is unreadable") from error
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise PrivateJsonError("private evidence identity is unsafe")
    if metadata.st_mode & 0o077:
        raise PrivateJsonError("private evidence mode is not restrictive")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise PrivateJsonError("private evidence is not valid JSON") from error
    if not isinstance(payload, dict):
        raise PrivateJsonError("private evidence must be a JSON object")
    return payload


def write_private_json(path: Path, payload: dict[str, Any]) -> None:
    path = Path(path)
    _require_link_safe_parent(path.parent)
    temporary = path.with_name(f".{path.name}.tmp")
    data = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(temporary, flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_private_json_exclusive(path: Path, payload: dict[str, Any]) -> None:
    """Create one immutable private JSON record without following links."""
    path = Path(path)
    _require_link_safe_parent(path.parent)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _require_link_safe_parent(path.parent)
    if path.parent.is_symlink() or not path.parent.is_dir():
        raise PrivateJsonError("private evidence parent is unsafe")
    if path.parent.stat(follow_symlinks=False).st_mode & 0o077:
        raise PrivateJsonError("private evidence parent mode is not restrictive")
    data = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def _require_link_safe_parent(parent: Path) -> None:
    absolute = parent if parent.is_absolute() else Path.cwd() / parent
    for candidate in (absolute, *absolute.parents):
        if candidate.is_symlink():
            raise PrivateJsonError("private evidence parent is unsafe")


__all__ = [
    "PrivateJsonError",
    "read_private_json",
    "write_private_json",
    "write_private_json_exclusive",
]
