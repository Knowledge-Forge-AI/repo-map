"""Existing strict D12 grant JSON/file IO; no authority policy or new dependency."""

from __future__ import annotations

import errno
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any

class D12SystemGrantError(RuntimeError):
    """Raised when the Route B system build grant or admission proof fails closed."""


def _no_dup_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, val in pairs:
        if key in out:
            raise D12SystemGrantError(f"duplicate JSON key is forbidden: {key!r}")
        out[key] = val
    return out


def loads_strict_json_object(raw_bytes: bytes, *, label: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw_bytes.decode("utf-8"), object_pairs_hook=_no_dup_pairs)
    except D12SystemGrantError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise D12SystemGrantError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(parsed, dict):
        raise D12SystemGrantError(f"{label} root must be a JSON object")
    return parsed


def read_regular_json_object(
    path: Path, *, label: str, max_bytes: int,
    require_mode_0600: bool = False, require_parent_mode_0700: bool = False,
) -> tuple[dict[str, Any], bytes, str]:
    if require_parent_mode_0700:
        try:
            parent_st = path.parent.lstat()
        except OSError as exc:
            raise D12SystemGrantError(f"{label} parent missing: {path.parent}") from exc
        if not stat.S_ISDIR(parent_st.st_mode) or stat.S_IMODE(parent_st.st_mode) != 0o700:
            raise D12SystemGrantError(f"{label} parent directory must be a non-symlink 0700 dir: {path.parent}")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError as exc:
        raise D12SystemGrantError(f"{label} file not found: {path}") from exc
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise D12SystemGrantError(f"{label} must not be a symlink: {path}") from exc
        raise D12SystemGrantError(f"cannot open {label} {path}: {exc}") from exc
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise D12SystemGrantError(f"{label} is not a regular file: {path}")
        if require_mode_0600 and stat.S_IMODE(st.st_mode) != 0o600:
            raise D12SystemGrantError(f"{label} must have mode 0600, got {oct(stat.S_IMODE(st.st_mode))}: {path}")
        if st.st_size <= 0 or st.st_size > max_bytes:
            raise D12SystemGrantError(f"{label} byte size {st.st_size} outside 1..{max_bytes}: {path}")
        with os.fdopen(fd, "rb", closefd=False) as handle:
            raw = handle.read(max_bytes + 1)
    finally:
        os.close(fd)
    if len(raw) > max_bytes:
        raise D12SystemGrantError(f"{label} exceeds {max_bytes} bytes: {path}")
    parsed = loads_strict_json_object(raw, label=label)
    return parsed, raw, hashlib.sha256(raw).hexdigest()
