"""Private per-home coordinator endpoint paths below every coordinator mode."""

from __future__ import annotations

import os
from pathlib import Path
import stat

from repomap_kg.coordinator.windows_security import (
    WindowsSecurityError,
    apply_owner_private_acl,
    reject_reparse_path,
    validate_owner_private_acl,
)


class CoordinatorModeError(RuntimeError):
    """Bounded coordinator-mode failure with no direct fallback."""


def coordinator_runtime_paths(
    repo_map_home: str | Path,
    *,
    create: bool = False,
) -> tuple[Path, Path, Path]:
    """Return the private endpoint paths derived from one RepoMap-owned home."""

    runtime_directory = Path(repo_map_home).expanduser() / "coordinator"
    endpoint_name, credential_name = _coordinator_endpoint_names()
    if create:
        try:
            os.mkdir(runtime_directory, mode=0o700)
        except FileExistsError:
            pass
        except OSError:
            raise CoordinatorModeError("coordinator_runtime_unavailable") from None
        try:
            if os.name == "nt":  # pragma: no cover - native Windows runner
                reject_reparse_path(runtime_directory)
            details = runtime_directory.lstat()
        except (OSError, WindowsSecurityError):
            raise CoordinatorModeError("coordinator_runtime_unavailable") from None
        if os.name == "nt":  # pragma: no cover - native Windows runner
            try:
                if not stat.S_ISDIR(details.st_mode):
                    raise CoordinatorModeError("coordinator_runtime_unsafe")
                apply_owner_private_acl(runtime_directory)
                validate_owner_private_acl(runtime_directory)
            except WindowsSecurityError:
                raise CoordinatorModeError("coordinator_runtime_unsafe") from None
            return (
                runtime_directory,
                runtime_directory / endpoint_name,
                runtime_directory / credential_name,
            )
        if (
            not stat.S_ISDIR(details.st_mode)
            or details.st_uid != os.getuid()
            or stat.S_IMODE(details.st_mode) != 0o700
        ):
            raise CoordinatorModeError("coordinator_runtime_unsafe")
    return (
        runtime_directory,
        runtime_directory / endpoint_name,
        runtime_directory / credential_name,
    )


def _coordinator_endpoint_names(platform_name: str | None = None) -> tuple[str, str]:
    if (platform_name or os.name) == "nt":
        return "coordinator.endpoint.json", "coordinator.endpoint.json"
    return "coordinator.sock", "coordinator.token"


# The public owner remains ``local_mode``; keep its reprs and pickles stable.
CoordinatorModeError.__module__ = "repomap_kg.coordinator.local_mode"
