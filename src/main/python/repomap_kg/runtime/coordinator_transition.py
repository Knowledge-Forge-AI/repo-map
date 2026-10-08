"""Read-only native endpoint classification for local deployment transitions."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from repomap_kg.coordinator.client import CoordinatorClientError, LocalCoordinatorClient
from repomap_kg.runtime._plan_records import LocalRuntimeDiagnostic, LocalRuntimeError


def native_coordinator_state(home: Path) -> str:
    """Authenticate activity; unavailable or partial artifacts remain unknown.

    Startup callers hold the per-home lock so unpublished packaged startup
    cannot be mistaken for inactivity. Checked status is a point-in-time probe.
    """
    from repomap_kg.coordinator._runtime_paths import coordinator_runtime_paths

    try:
        directory, endpoint, credential = coordinator_runtime_paths(home)
        try:
            details = directory.lstat()
        except FileNotFoundError:
            return "inactive"
        if not stat.S_ISDIR(details.st_mode):
            return "unknown"
        if os.name == "nt":
            from repomap_kg.coordinator.windows_security import reject_reparse_path, validate_owner_private_acl
            reject_reparse_path(directory)
            validate_owner_private_acl(directory)
        elif details.st_uid != os.getuid() or stat.S_IMODE(details.st_mode) != 0o700:
            return "unknown"
        present = [path.exists() or path.is_symlink() for path in (endpoint, credential)]
        if not any(present):
            return "inactive"
        if not all(present):
            return "unknown"
        details = endpoint.lstat()
        if os.name != "nt" and (not stat.S_ISSOCK(details.st_mode) or details.st_uid != os.getuid()):
            return "unknown"
        health = LocalCoordinatorClient(endpoint, credential, timeout_seconds=1.0).health()
        status = health.get("status")
        return "active" if isinstance(status, str) and status in {"ready", "degraded", "starting", "stopped"} else "unknown"
    except (OSError, ValueError, RuntimeError, CoordinatorClientError):
        return "unknown"


def native_transition_diagnostic(state: str) -> LocalRuntimeDiagnostic | None:
    if state == "inactive":
        return None
    if state == "active":
        return LocalRuntimeDiagnostic(
            "error", "native-coordinator-active", "runtime.coordinator_mode",
            "Stop the native coordinator service before container startup.",
        )
    return LocalRuntimeDiagnostic(
        "error", "native-coordinator-state-unknown", "runtime.coordinator_mode",
        "Native coordinator activity is unknown. Restore native mode, use supported "
        "service stop, start, then stop to recover stale endpoints, and retry; unsafe artifacts require operator repair.",
    )


def require_native_inactive(home: Path) -> str:
    state = native_coordinator_state(home)
    diagnostic = native_transition_diagnostic(state)
    if diagnostic is not None:
        raise LocalRuntimeError((diagnostic,))
    return state
