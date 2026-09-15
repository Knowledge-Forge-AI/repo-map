"""Current-platform service-package API and native process boundary."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

from repomap_kg.coordinator.client import CoordinatorClientError, LocalCoordinatorClient
from repomap_kg.coordinator.local_mode import coordinator_runtime_paths
from repomap_kg.service_package.contract import (
    ServicePackageSpec,
    build_service_inspection_spec,
    build_service_package_spec,
)
from repomap_kg.service_package.operations import (
    CoordinatorServiceOperations,
    ServiceActionResult,
    ServicePackageError,
)
from repomap_kg.service_package.platforms import (
    NativeServiceUnavailable,
    select_service_adapter,
)


_MANAGER_ENVIRONMENT_ALLOWLIST = (
    "DBUS_SESSION_BUS_ADDRESS",
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "XDG_RUNTIME_DIR",
)


def run_coordinator_service_action(
    action: str,
    repo_map_home: str | Path,
) -> ServiceActionResult | str:
    """Run one explicit native user-service action for the current platform."""

    try:
        adapter = select_service_adapter(
            sys.platform,
            user_home=Path.home(),
            uid=getattr(os, "getuid", lambda: 0)(),
        )
        if action in {"status", "uninstall"}:
            spec = build_service_inspection_spec(repo_map_home)
        else:
            spec = build_service_package_spec(repo_map_home)
    except (ValueError, RuntimeError, NativeServiceUnavailable) as error:
        raise ServicePackageError(str(error)) from None
    operations = CoordinatorServiceOperations(
        spec,
        adapter,
        runner=_run_manager_command,
        health_probe=_coordinator_health,
    )
    return operations.run(action)


def format_service_action_table(result: ServiceActionResult) -> str:
    """Format one bounded service-package action without private values."""

    values = result.as_dict()
    lines = ["RepoMap coordinator service"]
    for name in (
        "action",
        "platform",
        "artifact",
        "result",
        "installed",
        "active",
        "enabled",
        "ready",
        "changed",
    ):
        lines.append(f"{name}={values[name]}")
    return "\n".join(lines)


def _run_manager_command(argv: tuple[str, ...]) -> int:
    environment = {
        name: os.environ[name]
        for name in _MANAGER_ENVIRONMENT_ALLOWLIST
        if name in os.environ
    }
    try:
        completed = subprocess.run(
            argv,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            shell=False,
            env=environment,
        )
    except (OSError, subprocess.SubprocessError):
        raise ServicePackageError("native_service_manager_unavailable") from None
    return completed.returncode


def _coordinator_health(spec: ServicePackageSpec) -> bool:
    _, socket_path, token_path = coordinator_runtime_paths(spec.repo_map_home)
    try:
        payload = LocalCoordinatorClient(
            socket_path,
            token_path,
            timeout_seconds=2.0,
        ).health()
    except (CoordinatorClientError, OSError, ValueError):
        return False
    return isinstance(payload, Mapping) and payload.get("status") == "ready"


__all__ = ["format_service_action_table", "run_coordinator_service_action"]
