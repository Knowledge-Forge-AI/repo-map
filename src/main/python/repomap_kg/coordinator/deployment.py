"""Per-home startup serialization and packaged-native deployment policy."""

from __future__ import annotations

import os
import stat
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from repomap_kg.ops.config_loading import OpsConfigError, load_ops_config_home


class CoordinatorDeploymentError(RuntimeError):
    """A bounded deployment refusal, without private runtime details."""


def require_native_mode(home: Path) -> None:
    try:
        mode = load_ops_config_home(home).runtime.coordinator_mode
    except (OpsConfigError, OSError, ValueError):
        raise CoordinatorDeploymentError("coordinator_service_config_unavailable") from None
    if mode != "native":
        raise CoordinatorDeploymentError("coordinator_service_requires_native_mode")


@contextmanager
def coordinator_startup_lock(home: Path, *, wait_seconds: float = 5.0) -> Iterator[None]:
    """Serialize supported launches; retain the lock inode across releases.

    The database singleton remains the backstop for explicit foreground and
    container restarts. No endpoint or credential artifacts are changed here.
    """
    from repomap_kg.coordinator._runtime_paths import CoordinatorModeError, coordinator_runtime_paths

    if os.name == "nt":
        from repomap_kg.service_package._artifacts_locking import _windows_mutation_lock
        from repomap_kg.service_package.artifacts import ServiceArtifactError

        try:
            directory, _, _ = coordinator_runtime_paths(home, create=True)
            with _windows_mutation_lock(directory / "startup.lock", set()):
                yield
        except (ServiceArtifactError, CoordinatorModeError):
            raise CoordinatorDeploymentError("coordinator_startup_lock_unavailable") from None
        return

    descriptor = -1
    try:
        import fcntl

        directory, _, _ = coordinator_runtime_paths(home, create=True)
        descriptor = os.open(directory / "startup.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        details = os.fstat(descriptor)
        if (not stat.S_ISREG(details.st_mode) or details.st_uid != os.getuid()
                or stat.S_IMODE(details.st_mode) != 0o600 or details.st_nlink != 1):
            raise CoordinatorDeploymentError("coordinator_startup_lock_unsafe")
        deadline = time.monotonic() + wait_seconds
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise CoordinatorDeploymentError("coordinator_startup_busy") from None
                time.sleep(0.05)
    except CoordinatorDeploymentError:
        if descriptor >= 0:
            os.close(descriptor)
        raise
    except (ImportError, OSError, RuntimeError):
        if descriptor >= 0:
            os.close(descriptor)
        raise CoordinatorDeploymentError("coordinator_startup_lock_unavailable") from None
    try:
        yield
    finally:
        os.close(descriptor)
