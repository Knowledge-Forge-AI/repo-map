"""Explicit operator actions for portable native coordinator packaging."""

from __future__ import annotations


from repomap_kg.service_package._operations_execution import (
    CommandRunner as CommandRunner,
    HealthProbe as HealthProbe,
    ServicePackageError as ServicePackageError,
    _ACTIONS as _ACTIONS,
    _CoordinatorExecutionBase,
    _MUTATING_ACTIONS as _MUTATING_ACTIONS,
    _return_code as _return_code,
)
from repomap_kg.service_package.artifacts import (
    OwnedArtifact as OwnedArtifact,
    ServiceArtifactError as ServiceArtifactError,
    ensure_owner_directory as ensure_owner_directory,
    ensure_private_directory as ensure_private_directory,
    inspect_owned_artifact as default_inspect_owned_artifact,
    install_owned_artifact as default_install_owned_artifact,
    remove_owned_artifact as default_remove_owned_artifact,
    replace_owned_artifact as default_replace_owned_artifact,
    require_owner_directory as require_owner_directory,
    restore_owned_artifact as default_restore_owned_artifact,
    service_mutation_lock as service_mutation_lock,
)
from repomap_kg.service_package.contract import ServicePackageSpec
from repomap_kg.service_package.platforms import NativeServiceAdapter
from repomap_kg.service_package.results import (
    ServiceActionResult as ServiceActionResult,
)

# Explicit re-exports for test compatibility
inspect_owned_artifact = default_inspect_owned_artifact
install_owned_artifact = default_install_owned_artifact
remove_owned_artifact = default_remove_owned_artifact
replace_owned_artifact = default_replace_owned_artifact
restore_owned_artifact = default_restore_owned_artifact




class CoordinatorServiceOperations(_CoordinatorExecutionBase):
    """Own native mutations without leaking service-manager semantics upward."""

    def __init__(
        self,
        spec: ServicePackageSpec,
        adapter: NativeServiceAdapter,
        *,
        runner: CommandRunner,
        health_probe: HealthProbe,
    ) -> None:
        self.spec = spec
        self.adapter = adapter
        self.runner = runner
        self.health_probe = health_probe

    def run(self, action: str) -> ServiceActionResult | str:
        if action not in _ACTIONS:
            raise ServicePackageError("service_action_unsupported")
        if action == "render":
            return self._render().decode("utf-8")
        operation = getattr(self, f"_{action}")
        if action not in _MUTATING_ACTIONS:
            return operation()
        if action == "install":
            self._prepare_directories()
        elif not self.adapter.target_path.parent.exists():
            return operation()
        try:
            with service_mutation_lock(self.adapter.target_path):
                return operation()
        except ServiceArtifactError as error:
            raise ServicePackageError(str(error)) from None

    def _render(self) -> bytes:
        content = self.adapter.render(self.spec)
        try:
            self.adapter.validate(content, self.spec)
        except ValueError:
            raise ServicePackageError("service_definition_invalid") from None
        return content

    def _validate(self) -> ServiceActionResult:
        self._render()
        existing = self._inspect()
        if existing is not None:
            self._require_current(existing)
        return self._result("validate", installed=existing is not None)

    def _install(self) -> ServiceActionResult:
        content = self._render()
        self._prepare_directories()
        install_fn = install_owned_artifact
        restore_fn = restore_owned_artifact
        try:
            install_fn(
                self.adapter.target_path,
                content,
                self.adapter.recognizes,
            )
            self._run_commands(self.adapter.reload_commands())
        except ServiceArtifactError as error:
            raise ServicePackageError(str(error)) from None
        except ServicePackageError:
            try:
                restore_fn(
                    self.adapter.target_path,
                    None,
                    self.adapter.recognizes,
                )
                self._run_commands(self.adapter.reload_commands())
            except (ServiceArtifactError, ServicePackageError):
                raise ServicePackageError("service_install_rollback_failed") from None
            raise ServicePackageError("service_install_rolled_back") from None
        return self._result(
            "install",
            installed=True,
            active=False,
            enabled=False if self.adapter.enabled_probe_argv() is not None else None,
            changed=True,
        )

    def _start(self) -> ServiceActionResult:
        self._require_installed_current()
        active, enabled = self._native_state()
        enable_requested = enabled is not True and bool(self.adapter.enable_commands())
        enabled_changed = enabled is False and enable_requested
        try:
            if enable_requested:
                self._run_commands(self.adapter.enable_commands())
            if not active:
                self._run_commands(self.adapter.start_commands())
        except ServicePackageError:
            try:
                if enabled_changed:
                    self._run_commands(self.adapter.disable_commands())
            except ServicePackageError:
                raise ServicePackageError("service_start_rollback_failed") from None
            raise ServicePackageError("service_start_failed") from None
        return self._result(
            "start",
            installed=True,
            active=True,
            enabled=True if self.adapter.enable_commands() else None,
            changed=enable_requested or not active,
        )

    def _stop(self) -> ServiceActionResult:
        self._require_installed_current()
        active, enabled = self._native_state()
        if active:
            self._run_commands(self.adapter.stop_commands())
        if enabled is not False and self.adapter.disable_commands():
            self._run_commands(self.adapter.disable_commands())
        return self._result(
            "stop",
            installed=True,
            active=False,
            enabled=False if self.adapter.disable_commands() else None,
            changed=bool(active or enabled),
        )

    def _restart(self) -> ServiceActionResult:
        self._require_installed_current()
        self._run_commands(self.adapter.restart_commands())
        return self._result(
            "restart",
            installed=True,
            active=True,
            enabled=None,
            changed=True,
        )

    def _status(self) -> ServiceActionResult:
        existing = self._inspect()
        if existing is None:
            return self._result(
                "status",
                installed=False,
                active=False,
                enabled=False if self.adapter.enabled_probe_argv() is not None else None,
                ready=False,
            )
        active, enabled = self._native_state()
        ready = False
        if active:
            try:
                ready = bool(self.health_probe(self.spec))
            except Exception:
                ready = False
        return self._result(
            "status",
            installed=True,
            active=active,
            enabled=enabled,
            ready=ready,
        )

    def _upgrade(self) -> ServiceActionResult:
        content = self._render()
        prior = self._require_installed()
        active, enabled = self._native_state()
        stopped, disabled = self._suspend_native_state(
            active,
            enabled,
            action="service_upgrade",
            disable_unknown=False,
        )
        replace_fn = replace_owned_artifact
        try:
            replace_fn(
                self.adapter.target_path,
                content,
                self.adapter.recognizes,
            )
        except ServiceArtifactError as error:
            try:
                self._restore_native_state(stopped, disabled)
            except ServicePackageError:
                raise ServicePackageError("service_upgrade_rollback_failed") from None
            raise ServicePackageError(str(error)) from None
        try:
            self._run_commands(self.adapter.reload_commands())
            if enabled:
                self._run_commands(self.adapter.enable_commands())
            if active:
                self._run_commands(self.adapter.start_commands())
        except ServicePackageError:
            self._rollback_upgrade(prior, stopped, disabled)
            raise ServicePackageError("service_upgrade_rolled_back") from None
        return self._result(
            "upgrade",
            installed=True,
            active=active,
            enabled=enabled,
            changed=True,
        )

    def _uninstall(self) -> ServiceActionResult:
        prior = self._inspect()
        if prior is None:
            return self._result(
                "uninstall",
                installed=False,
                active=False,
                enabled=False if self.adapter.enabled_probe_argv() is not None else None,
            )
        active, enabled = self._native_state()
        stopped, disabled = self._suspend_native_state(
            active,
            enabled,
            action="service_uninstall",
            disable_unknown=True,
        )
        remove_fn = remove_owned_artifact
        restore_fn = restore_owned_artifact
        try:
            remove_fn(self.adapter.target_path, self.adapter.recognizes)
            self._run_commands(self.adapter.reload_commands())
        except (ServiceArtifactError, ServicePackageError):
            try:
                restore_fn(
                    self.adapter.target_path,
                    prior,
                    self.adapter.recognizes,
                )
                self._run_commands(self.adapter.reload_commands())
                self._restore_native_state(stopped, disabled)
            except (ServiceArtifactError, ServicePackageError):
                raise ServicePackageError("service_uninstall_rollback_failed") from None
            raise ServicePackageError("service_uninstall_rolled_back") from None
        return self._result(
            "uninstall",
            installed=False,
            active=False,
            enabled=False if self.adapter.disable_commands() else None,
            changed=True,
        )

    def _inspect(self) -> OwnedArtifact | None:
        inspect_fn = inspect_owned_artifact
        try:
            return inspect_fn(
                self.adapter.target_path,
                self.adapter.recognizes,
            )
        except ServiceArtifactError as error:
            raise ServicePackageError(str(error)) from None

    def _require_installed(self) -> OwnedArtifact:
        existing = self._inspect()
        if existing is None:
            raise ServicePackageError("service_definition_missing")
        return existing

    def _require_current(self, existing: OwnedArtifact) -> None:
        try:
            self.adapter.validate(existing.content, self.spec)
        except ValueError:
            raise ServicePackageError("service_definition_upgrade_required") from None

    def _require_installed_current(self) -> OwnedArtifact:
        existing = self._require_installed()
        self._require_current(existing)
        return existing


    def _prepare_directories(self) -> None:
        req_owner_fn = require_owner_directory
        ens_priv_fn = ensure_private_directory
        ens_owner_fn = ensure_owner_directory
        try:
            req_owner_fn(self.spec.repo_map_home)
            ens_priv_fn(self.spec.runtime_directory)
            ens_owner_fn(self.adapter.user_home)
            ens_owner_fn(self.adapter.target_path.parent)
        except ServiceArtifactError as error:
            raise ServicePackageError(str(error)) from None
        try:
            self.adapter.target_path.parent.resolve(strict=True).relative_to(
                self.adapter.user_home.resolve(strict=True)
            )
        except (OSError, ValueError):
            raise ServicePackageError("service_directory_unsafe") from None

    def _rollback_upgrade(
        self,
        prior: OwnedArtifact,
        active: bool,
        enabled: bool | None,
    ) -> None:
        restore_fn = restore_owned_artifact
        try:
            restore_fn(
                self.adapter.target_path,
                prior,
                self.adapter.recognizes,
            )
            self._run_commands(self.adapter.reload_commands())
            self._restore_native_state(active, enabled)
        except (ServiceArtifactError, ServicePackageError):
            raise ServicePackageError("service_upgrade_rollback_failed") from None


__all__ = [
    "CoordinatorServiceOperations",
    "ServiceActionResult",
    "ServicePackageError",
]
