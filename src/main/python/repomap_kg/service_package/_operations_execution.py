"""Native command execution and directory preparation for service operations."""

from __future__ import annotations

from collections.abc import Callable

from repomap_kg.service_package.contract import ServicePackageSpec
from repomap_kg.service_package.platforms import NativeServiceAdapter
from repomap_kg.service_package.results import ServiceActionResult

_ACTIONS = frozenset(
    {
        "install",
        "status",
        "start",
        "stop",
        "restart",
        "upgrade",
        "uninstall",
        "render",
        "validate",
    }
)
_MUTATING_ACTIONS = frozenset(
    {"install", "start", "stop", "restart", "upgrade", "uninstall"}
)


class ServicePackageError(RuntimeError):
    """A bounded native service-package operation failed."""


CommandRunner = Callable[[tuple[str, ...]], int]
HealthProbe = Callable[[ServicePackageSpec], bool]




def _return_code(value: object) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return_code = getattr(value, "returncode", None)
    if isinstance(return_code, int) and not isinstance(return_code, bool):
        return return_code
    raise TypeError("native manager returned an invalid result")


class _CoordinatorExecutionBase:
    """Base execution and lifecycle state management for native service operations."""

    spec: ServicePackageSpec
    adapter: NativeServiceAdapter
    runner: CommandRunner
    health_probe: HealthProbe

    def _native_state(self) -> tuple[bool, bool | None]:
        self._require_native_manager()
        active = self._probe(
            self.adapter.active_probe_argv(),
            self.adapter.inactive_return_codes(),
        )
        enabled_argv = self.adapter.enabled_probe_argv()
        enabled = (
            self._probe(enabled_argv, self.adapter.disabled_return_codes())
            if enabled_argv is not None
            else None
        )
        return active, enabled

    def _require_native_manager(self) -> None:
        try:
            return_code = _return_code(self.runner(self.adapter.manager_probe_argv()))
        except Exception:
            raise ServicePackageError("native_service_manager_unavailable") from None
        if return_code != 0:
            raise ServicePackageError("native_service_manager_unavailable")

    def _probe(
        self,
        argv: tuple[str, ...],
        false_return_codes: frozenset[int],
    ) -> bool:
        try:
            return_code = _return_code(self.runner(argv))
        except Exception:
            raise ServicePackageError("native_service_manager_unavailable") from None
        if return_code == 0:
            return True
        if return_code in false_return_codes:
            return False
        raise ServicePackageError("native_service_probe_failed")

    def _run_commands(self, commands: tuple[tuple[str, ...], ...]) -> None:
        for argv in commands:
            try:
                return_code = _return_code(self.runner(argv))
            except Exception:
                raise ServicePackageError("native_service_manager_unavailable") from None
            if return_code != 0:
                raise ServicePackageError("native_service_command_failed")



    def _restore_native_state(self, active: bool, enabled: bool | None) -> None:
        if enabled:
            self._run_commands(self.adapter.enable_commands())
        if active:
            self._run_commands(self.adapter.start_commands())

    def _suspend_native_state(
        self,
        active: bool,
        enabled: bool | None,
        *,
        action: str,
        disable_unknown: bool,
    ) -> tuple[bool, bool]:
        stopped = False
        disabled = False
        try:
            if active:
                self._run_commands(self.adapter.stop_commands())
                stopped = True
            if enabled or (enabled is None and disable_unknown):
                self._run_commands(self.adapter.disable_commands())
                disabled = True
        except ServicePackageError:
            try:
                self._restore_native_state(stopped, disabled)
            except ServicePackageError:
                raise ServicePackageError(f"{action}_rollback_failed") from None
            raise ServicePackageError(f"{action}_rolled_back") from None
        return stopped, disabled

    def _result(
        self,
        action: str,
        *,
        installed: bool | None = None,
        active: bool | None = None,
        enabled: bool | None = None,
        ready: bool | None = None,
        changed: bool = False,
    ) -> ServiceActionResult:
        return ServiceActionResult(
            action=action,
            platform=self.adapter.platform_name,
            artifact=self.adapter.artifact_kind,
            service_identity=self.spec.service_identity,
            installed=installed,
            active=active,
            enabled=enabled,
            ready=ready,
            changed=changed,
        )
