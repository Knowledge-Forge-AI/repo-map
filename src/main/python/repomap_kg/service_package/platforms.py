"""Explicit platform selection for native user-service adapters."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol

from repomap_kg.service_package.contract import ServicePackageSpec
from repomap_kg.service_package.launchd import LaunchdUserAdapter
from repomap_kg.service_package.systemd import SystemdUserAdapter


class NativeServiceUnavailable(RuntimeError):
    """The selected platform has no proven native service adapter."""


class NativeServiceAdapter(Protocol):
    """Closed behavior required from a native user-service adapter."""

    @property
    def user_home(self) -> Path: ...

    @property
    def uid(self) -> int: ...

    @property
    def platform_name(self) -> str: ...

    @property
    def artifact_kind(self) -> str: ...

    @property
    def target_path(self) -> Path: ...

    def render(self, spec: ServicePackageSpec) -> bytes: ...

    def validate(self, content: bytes, spec: ServicePackageSpec) -> None: ...

    def recognizes(self, content: bytes) -> bool: ...

    def semantic_values(self, spec: ServicePackageSpec) -> dict[str, object]: ...

    def manager_probe_argv(self) -> tuple[str, ...]: ...

    def inactive_return_codes(self) -> frozenset[int]: ...

    def disabled_return_codes(self) -> frozenset[int]: ...

    def active_probe_argv(self) -> tuple[str, ...]: ...

    def enabled_probe_argv(self) -> tuple[str, ...] | None: ...

    def reload_commands(self) -> tuple[tuple[str, ...], ...]: ...

    def enable_commands(self) -> tuple[tuple[str, ...], ...]: ...

    def disable_commands(self) -> tuple[tuple[str, ...], ...]: ...

    def start_commands(self) -> tuple[tuple[str, ...], ...]: ...

    def stop_commands(self) -> tuple[tuple[str, ...], ...]: ...

    def restart_commands(self) -> tuple[tuple[str, ...], ...]: ...


def select_service_adapter(
    platform_name: str,
    *,
    user_home: Path,
    uid: int,
) -> NativeServiceAdapter:
    """Select one native adapter without cross-platform fallback."""

    raw_home = os.fspath(user_home)
    if "\x00" in raw_home or not Path(raw_home).is_absolute():
        raise ValueError("service_user_home_invalid")
    if not isinstance(uid, int) or isinstance(uid, bool) or uid < 0:
        raise ValueError("service_user_identity_invalid")
    normalized_home = Path(raw_home).resolve(strict=False)
    if platform_name == "darwin":
        return LaunchdUserAdapter(user_home=normalized_home, uid=uid)
    if platform_name == "linux":
        return SystemdUserAdapter(user_home=normalized_home, uid=uid)
    if platform_name == "win32":
        raise NativeServiceUnavailable("native_service_adapter_pending_windows")
    raise NativeServiceUnavailable("native_service_manager_unsupported")


__all__ = [
    "NativeServiceAdapter",
    "NativeServiceUnavailable",
    "select_service_adapter",
]
