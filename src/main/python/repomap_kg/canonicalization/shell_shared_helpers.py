"""Shared shell canonicalization helpers."""

from __future__ import annotations

import posixpath


def _safe_relative_shell_target(source_path: str, target: str) -> str | None:
    if (
        target.startswith(("/", "~"))
        or "$" in target
        or "`" in target
        or target.startswith("[")
    ):
        return None
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(source_path), target))
    if resolved == "." or resolved.startswith("../"):
        return None
    return resolved
