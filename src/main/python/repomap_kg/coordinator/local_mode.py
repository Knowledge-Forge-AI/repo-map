"""Explicit local coordinator launch and configured-refresh client boundary."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
import os
from pathlib import Path
import secrets
import shutil
import signal
import stat
from threading import Event, current_thread, main_thread
import time
from types import FrameType
from typing import Protocol

_SignalHandler = (
    Callable[[int, FrameType | None], object] | int | signal.Handlers | None
)


class _CoordinatorRuntime(Protocol):
    def ready_payload(self) -> Mapping[str, object]: ...
    def health(self) -> Mapping[str, object]: ...
    def stop(self) -> None: ...


class RuntimeFactory(Protocol):
    def __call__(
        self, repo_map_home: str | Path, /, *, psql_path: str | Path | None = None
    ) -> _CoordinatorRuntime: ...


class _CoordinatorClient(Protocol):
    def submit(self, request: Mapping[str, object]) -> Mapping[str, object]: ...
    def wait(self, job_id: str) -> Mapping[str, object]: ...


from repomap_kg.coordinator.client import LocalCoordinatorClient
from repomap_kg.coordinator._refresh_capability_io import validate_psql
from repomap_kg.coordinator.configured_refresh import (
    ConfiguredRefreshResolver,
    build_configured_refresh_coordinator,
)
from repomap_kg.coordinator.contracts import TERMINAL_JOB_STATES
from repomap_kg.coordinator.desired_state import DesiredStateReconciler
from repomap_kg.coordinator.local_lifecycle import (
    CoordinatorControlError,
    LocalControlAuthority,
    derived_control_database as _derived_control_database,
)
from repomap_kg.coordinator.service import CoordinatorService
from repomap_kg.coordinator.polling import PollingScheduler
from repomap_kg.coordinator.startup_recovery import StartupRecoveryReport
from repomap_kg.coordinator.windows_security import (
    WindowsSecurityError,
    apply_owner_private_acl,
    reject_reparse_path,
    validate_owner_private_acl,
)
from repomap_kg.runtime.database_role_contract import (
    REFRESH_PUBLICATION_ROLE,
    read_role_secrets,
)


_MAX_WAIT_SECONDS = 86_400


class CoordinatorModeError(RuntimeError):
    """Bounded coordinator-mode failure with no direct fallback."""


@dataclass
class LocalCoordinatorRuntime:
    """One started foreground coordinator and its bounded startup result."""

    service: CoordinatorService
    recovery: StartupRecoveryReport

    def ready_payload(self) -> dict[str, object]:
        return {
            "command": "coordinator-serve",
            "mode": "coordinator",
            "result": "ready",
            "startup_recovery": asdict(self.recovery),
        }

    def health(self) -> Mapping[str, object]:
        return self.service.health()

    def stop(self) -> None:
        self.service.stop()


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


def derived_control_database(graph_database: str) -> str:
    """Preserve the ASYNC9 local-mode helper and its bounded error contract."""

    try:
        return _derived_control_database(graph_database)
    except CoordinatorControlError as error:
        raise CoordinatorModeError(str(error)) from None


def start_configured_coordinator(
    repo_map_home: str | Path,
    *,
    psql_path: str | Path | None = None,
) -> LocalCoordinatorRuntime:
    """Start one configured foreground service against an existing control schema."""

    home = Path(repo_map_home).expanduser()
    service: CoordinatorService | None = None
    try:
        authority = LocalControlAuthority(home, capability="coordinator")
        psql = _resolve_psql_executable(psql_path)
        store = authority.control_store()
        store.check_schema_version()
        runtime_directory, _, _ = coordinator_runtime_paths(home, create=True)
        role_secrets = read_role_secrets(home / "runtime" / ".env")
        resolver = ConfiguredRefreshResolver(
            home,
            psql,
            postgres_user=REFRESH_PUBLICATION_ROLE,
            postgres_password=role_secrets.refresh_publication,
        )
        coordinator = build_configured_refresh_coordinator(
            store,
            f"local-{secrets.token_hex(16)}",
            resolver,
            runtime_directory,
        )
        desired_reconciler = DesiredStateReconciler(resolver, store)
        polling_scheduler = PollingScheduler(resolver, desired_reconciler)
        service = CoordinatorService(
            coordinator,
            store,
            runtime_directory,
            request_resolver=resolver.resolve_request,
            desired_reconciler=polling_scheduler,
            readiness_probe=store.maintenance_ready,
        )
        service.start(coordinator.recover_startup)
        recovery = coordinator.startup_recovery_report
        if not isinstance(recovery, StartupRecoveryReport):
            raise CoordinatorModeError("coordinator_start_failed")
        return LocalCoordinatorRuntime(service, recovery)
    except CoordinatorModeError:
        if service is not None:
            _stop_failed_service(service)
        raise
    except Exception:
        if service is not None:
            _stop_failed_service(service)
        raise CoordinatorModeError("coordinator_start_failed") from None


def serve_configured_coordinator(
    repo_map_home: str | Path,
    ready_callback: Callable[[Mapping[str, object]], object],
    *,
    psql_path: str | Path | None = None,
    startup_wait_seconds: int = 0,
    stop_event: Event | None = None,
    runtime_factory: RuntimeFactory = start_configured_coordinator,
) -> None:
    """Own one foreground runtime until an orderly local stop is requested."""

    if (
        not isinstance(startup_wait_seconds, int)
        or isinstance(startup_wait_seconds, bool)
        or not 0 <= startup_wait_seconds <= 300
    ):
        raise CoordinatorModeError("coordinator_start_wait_invalid")
    deadline = time.monotonic() + startup_wait_seconds
    while True:
        try:
            if psql_path is None:
                runtime = runtime_factory(repo_map_home)
            else:
                runtime = runtime_factory(repo_map_home, psql_path=psql_path)
            break
        except CoordinatorModeError as error:
            remaining = deadline - time.monotonic()
            if str(error) != "coordinator_start_failed" or remaining <= 0:
                raise
            time.sleep(min(1.0, remaining))
    event = stop_event or Event()
    previous_handlers: dict[signal.Signals, _SignalHandler] = {}
    can_install_handlers = stop_event is None and current_thread() is main_thread()
    if can_install_handlers:
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[sig] = signal.getsignal(sig)
            signal.signal(sig, lambda _number, _frame: event.set())
    try:
        ready_callback(runtime.ready_payload())
        while not event.wait(0.25):
            if runtime.health().get("status") != "ready":
                raise CoordinatorModeError("coordinator_service_degraded")
    finally:
        try:
            try:
                runtime.stop()
            except Exception:
                raise CoordinatorModeError("coordinator_stop_failed") from None
        finally:
            for sig, handler in previous_handlers.items():
                if handler is not None:
                    signal.signal(sig, handler)


def _resolve_psql_executable(
    psql_path: str | Path | None,
    *,
    platform_name: str | None = None,
) -> Path:
    value = shutil.which("psql") if psql_path is None else os.fspath(psql_path)
    if value is None:
        raise CoordinatorModeError("coordinator_psql_unavailable")
    try:
        if "\x00" in value:
            raise ValueError
        lexical = Path(value)
        expected_name = "psql.exe" if (platform_name or os.name) == "nt" else "psql"
        if (
            not lexical.is_absolute()
            or ".." in lexical.parts
            or lexical.name.lower() != expected_name
        ):
            raise ValueError
        validate_psql(lexical)
    except (OSError, TypeError, ValueError):
        raise CoordinatorModeError("coordinator_psql_unavailable") from None
    return lexical


def run_coordinator_refresh(
    repo_map_home: str | Path,
    graph_id: str,
    idempotency_key: str,
    *,
    wait_timeout_seconds: int = 3_600,
    client_factory: Callable[[Path, Path], _CoordinatorClient] = LocalCoordinatorClient,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, object]:
    """Submit one durable configured refresh and wait for a terminal state."""

    if not 1 <= wait_timeout_seconds <= _MAX_WAIT_SECONDS:
        raise CoordinatorModeError("coordinator_wait_invalid")
    _, socket_path, token_path = coordinator_runtime_paths(repo_map_home)
    client = client_factory(socket_path, token_path)
    request = {
        "schema_version": 1,
        "job_kind": "refresh_graph",
        "graph_id": graph_id,
        "request_id": idempotency_key,
        "idempotency_key": idempotency_key,
        "priority": "manual",
        "operation_options": {"reason": "operator-request"},
    }
    submitted = client.submit(request)
    job_id = _required_text(submitted, "job_id")
    replayed = submitted.get("replayed")
    if not isinstance(replayed, bool):
        raise CoordinatorModeError("coordinator_response_invalid")
    deadline = monotonic() + wait_timeout_seconds
    while True:
        status = client.wait(job_id)
        state = _required_text(status, "state")
        if state in TERMINAL_JOB_STATES:
            return {
                "command": "refresh-graph",
                "mode": "coordinator",
                "result": "success" if state == "succeeded" else "failure",
                "replayed": replayed,
                "job": dict(status),
            }
        if monotonic() >= deadline:
            raise CoordinatorModeError("coordinator_wait_timeout")


def format_coordinator_refresh_table(payload: Mapping[str, object]) -> str:
    """Format one bounded coordinator terminal result for shell users."""

    job = payload.get("job")
    if not isinstance(job, Mapping):
        raise CoordinatorModeError("coordinator_response_invalid")
    return "\n".join(
        (
            "RepoMap coordinator refresh result",
            "field | value",
            f"result | {_required_text(payload, 'result')}",
            f"job_id | {_required_text(job, 'job_id')}",
            f"graph_id | {_required_text(job, 'graph_id')}",
            f"state | {_required_text(job, 'state')}",
            f"replayed | {str(payload.get('replayed')).lower()}",
        )
    )


def _stop_failed_service(service: CoordinatorService) -> None:
    try:
        service.stop()
    except Exception:
        raise CoordinatorModeError("coordinator_cleanup_failed") from None


def _required_text(payload: Mapping[str, object], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise CoordinatorModeError("coordinator_response_invalid")
    return value


__all__ = [
    "CoordinatorModeError",
    "LocalCoordinatorRuntime",
    "coordinator_runtime_paths",
    "derived_control_database",
    "format_coordinator_refresh_table",
    "run_coordinator_refresh",
    "serve_configured_coordinator",
    "start_configured_coordinator",
]
