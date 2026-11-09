"""Canonical path binding shared by governed graph-local selections.

The helper deliberately has no discovery, artifact, or operations imports.
It preserves the incumbent ``classify_path`` expression while keeping the
capture-only sealing path outside the native graph-discovery closure.
"""

from __future__ import annotations

from pathlib import Path


def canonical_relative_path(repository_root: Path, file_path: Path) -> str:
    """Return the incumbent resolved, repository-relative POSIX path."""

    return file_path.resolve().relative_to(repository_root).as_posix()


__all__ = ("canonical_relative_path",)
