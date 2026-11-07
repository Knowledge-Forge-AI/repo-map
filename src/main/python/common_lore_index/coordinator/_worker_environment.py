"""Shared environment policy for allowlisted coordinator workers."""

from __future__ import annotations

import os
from pathlib import Path


def add_windows_runtime_environment(  # pragma: no cover - native Windows runner
    environment: dict[str, str],
) -> None:
    """Add the minimum Windows runtime environment to a worker launch."""

    if os.name != "nt":
        return
    system_root = os.environ.get("SystemRoot")
    if not system_root:
        raise RuntimeError("windows_runtime_environment_unavailable")
    environment["SystemRoot"] = system_root


def build_portable_worker_environment(
    *, workspace_root: Path, python_path: Path | None = None
) -> dict[str, str]:
    """Return the closed environment for a database-independent worker."""

    environment = {
        "HOME": str(workspace_root),
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": "",
        "TMPDIR": str(workspace_root),
    }
    if python_path is not None:
        environment["PYTHONPATH"] = str(python_path)
    add_windows_runtime_environment(environment)
    return environment
