"""Bounded file metadata helpers used by repository discovery."""

from __future__ import annotations

import hashlib
from pathlib import Path


def first_line(path: Path) -> str:
    try:
        with path.open(encoding="utf-8") as handle:
            return handle.readline().strip()
    except UnicodeDecodeError:
        return ""


def content_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = ["content_hash", "first_line"]
