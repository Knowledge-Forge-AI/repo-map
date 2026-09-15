"""Structured lifecycle for the bounded synthetic coordinator service."""

from __future__ import annotations

from collections.abc import Callable
import os
from pathlib import Path
import secrets
import threading

from repomap_kg.coordinator._coordinator_protocols import (
    DesiredReconciler as _DesiredReconciler,
    RequestResolver,
    ServiceCoordinator as _Coordinator,
    ServiceStore as _Store,
    TransportFactory,
    _Transport,
)
from repomap_kg.coordinator._service_endpoints import (
    _create_private_token,
    _endpoint_names,
    _remove_stale_endpoint,
    _validate_runtime_directory,
)
from repomap_kg.coordinator._service_handlers import ServiceHandlersMixin
from repomap_kg.coordinator.limits import DEFAULT_LIMITS, CoordinatorLimits
from repomap_kg.coordinator.transport import (
    LocalRequestDispatcher,
    LoopbackTcpService,
    UnixSocketService,
)

_HEALTH_SCHEMA_VERSION = 1


def default_transport_factory(platform_name: str | None = None) -> TransportFactory:
    """Select a native endpoint adapter without changing coordinator semantics."""

    return LoopbackTcpService if (platform_name or os.name) == "nt" else UnixSocketService


class CoordinatorService(ServiceHandlersMixin):
    """Own service tasks, endpoint credentials, and orderly shutdown."""

    def __init__(
        self,
        coordinator: _Coordinator,
        store: _Store,
        runtime_directory: Path,
        *,
        request_resolver: RequestResolver | None = None,
        limits: CoordinatorLimits = DEFAULT_LIMITS,
        transport_factory: TransportFactory | None = None,
        desired_reconciler: _DesiredReconciler | None = None,
        readiness_probe: Callable[[], bool] | None = None,
        idle_poll_seconds: float = 0.1,
        heartbeat_seconds: float = 10.0,
        wait_seconds: float = 1.0,
    ) -> None:
        directory = Path(runtime_directory)
        _validate_runtime_directory(directory)
        if (
            idle_poll_seconds <= 0
            or heartbeat_seconds <= 0
            or wait_seconds <= 0
            or wait_seconds > 30
        ):
            raise ValueError("service timing configuration is invalid")
        self._coordinator = coordinator
        self._store = store
        self._request_resolver = request_resolver or self._resolve_synthetic_request
        self._limits = limits
        self._transport_factory = transport_factory or default_transport_factory()
        self._desired_reconciler = desired_reconciler
        self._readiness_probe = readiness_probe
        self._idle_poll = idle_poll_seconds
        self._heartbeat = heartbeat_seconds
        self._wait_seconds = wait_seconds
        endpoint_name, credential_name = _endpoint_names()
        self.socket_path = directory / endpoint_name
        self.token_path = directory / credential_name
        coordinator_instance_id = getattr(coordinator, "_instance_id", None)
        self._instance_id = (
            coordinator_instance_id
            if isinstance(coordinator_instance_id, str)
            else secrets.token_urlsafe(16)
        )
        self._fencing_epoch = 1
        self._transport: _Transport | None = None
        self._claim_thread: threading.Thread | None = None
        self._heartbeat_thread: threading.Thread | None = None
        self._desired_reconciler_started = False
        self._stop = threading.Event()
        self._state_lock = threading.Lock()
        self._state = "stopped"

    def start(self, reconcile_startup: Callable[[], object]) -> None:
        with self._state_lock:
            if self._state != "stopped":
                raise RuntimeError("coordinator service is already started")
            self._state = "starting"
        coordinator_started = False
        token_created = False
        descriptor_endpoint = self.socket_path == self.token_path
        try:
            startup_epoch = self._coordinator.startup(reconcile_startup)
            if (
                isinstance(startup_epoch, int)
                and not isinstance(startup_epoch, bool)
                and startup_epoch > 0
            ):
                self._fencing_epoch = startup_epoch
            coordinator_started = True
            if descriptor_endpoint:
                _remove_stale_endpoint(self.socket_path, descriptor_expected=True)
                token = secrets.token_urlsafe(32)
            else:
                _remove_stale_endpoint(self.socket_path, socket_expected=True)
                _remove_stale_endpoint(self.token_path, socket_expected=False)
                token = _create_private_token(self.token_path)
                token_created = True
            dispatcher = LocalRequestDispatcher(
                token,
                self._handlers(),
                max_in_flight=self._limits.max_in_flight_requests,
            )
            transport_kwargs: dict[str, object] = {
                "max_connections": self._limits.max_client_connections,
            }
            if descriptor_endpoint:
                transport_kwargs.update(
                    auth_token=token,
                    instance_id=self._instance_id,
                    fencing_epoch=self._fencing_epoch,
                )
            self._transport = self._transport_factory(
                self.socket_path, dispatcher, **transport_kwargs
            )
            self._stop.clear()
            self._claim_thread = threading.Thread(
                target=self._run_claims,
                name="coordinator-service-loop",
            )
            self._heartbeat_thread = threading.Thread(
                target=self._run_heartbeat,
                name="coordinator-service-heartbeat",
            )
            self._claim_thread.start()
            self._heartbeat_thread.start()
            if self._desired_reconciler is not None:
                self._desired_reconciler_started = True
                self._desired_reconciler.start()
            self._transport.__enter__()
            with self._state_lock:
                if self._state == "degraded":
                    raise RuntimeError("coordinator service task failed")
                self._state = "ready"
        except BaseException:
            self._stop.set()
            if self._desired_reconciler_started:
                try:
                    if (reconciler := self._desired_reconciler) is not None:
                        reconciler.stop()
                finally:
                    self._desired_reconciler_started = False
            if self._transport is not None:
                self._transport.__exit__(None, None, None)
                self._transport = None
            for thread in (self._claim_thread, self._heartbeat_thread):
                if thread is not None and thread.is_alive():
                    thread.join()
            self._claim_thread = None
            self._heartbeat_thread = None
            if token_created:
                _remove_stale_endpoint(self.token_path, socket_expected=False)
            elif descriptor_endpoint:
                _remove_stale_endpoint(
                    self.socket_path,
                    descriptor_expected=True,
                    expected_instance_id=self._instance_id,
                    expected_fencing_epoch=self._fencing_epoch,
                )
            if coordinator_started:
                self._coordinator.shutdown()
            with self._state_lock:
                self._state = "stopped"
            raise

    def stop(self) -> None:
        with self._state_lock:
            if self._state == "stopped":
                return
            self._state = "stopping"
        failure: BaseException | None = None
        try:
            if self._desired_reconciler_started:
                try:
                    if (reconciler := self._desired_reconciler) is not None:
                        reconciler.stop()
                finally:
                    self._desired_reconciler_started = False
        except BaseException as error:
            failure = error
        try:
            if self._transport is not None:
                self._transport.__exit__(None, None, None)
                self._transport = None
        except BaseException as error:
            failure = error
        self._stop.set()
        for name in ("_claim_thread", "_heartbeat_thread"):
            thread = getattr(self, name)
            if thread is not None:
                thread.join()
                setattr(self, name, None)
        try:
            self._coordinator.shutdown()
        except BaseException as error:
            if failure is None:
                failure = error
        finally:
            endpoints = (
                ((self.socket_path, False, True),)
                if self.socket_path == self.token_path
                else (
                    (self.token_path, False, False),
                    (self.socket_path, True, False),
                )
            )
            for path, socket_expected, descriptor_expected in endpoints:
                try:
                    _remove_stale_endpoint(
                        path,
                        socket_expected=socket_expected,
                        descriptor_expected=descriptor_expected,
                        expected_instance_id=(
                            self._instance_id if descriptor_expected else None
                        ),
                        expected_fencing_epoch=(
                            self._fencing_epoch if descriptor_expected else None
                        ),
                    )
                except BaseException as error:
                    if failure is None:
                        failure = error
            with self._state_lock:
                self._state = "stopped"
        if failure is not None:
            raise failure

    def health(self) -> dict[str, object]:
        storage_status = "not_reported"
        if self._readiness_probe is not None:
            try:
                storage_status = (
                    "ready" if self._readiness_probe() else "schema_upgrading"
                )
            except Exception:
                storage_status = "unavailable"
        with self._state_lock:
            status = (
                "not_ready"
                if self._state == "ready"
                and storage_status in {"schema_upgrading", "unavailable"}
                else self._state
            )
            ownership_status = (
                "owned"
                if self._state in {"starting", "ready", "stopping"}
                else "not_owned"
                if self._state == "stopped"
                else "not_reported"
            )
            payload: dict[str, object] = {
                "health_schema_version": _HEALTH_SCHEMA_VERSION,
                "status": status,
                "service": {"status": self._state},
                "ownership": {"status": ownership_status},
                "queue": {"status": "not_reported"},
                "workers": {"status": "not_reported"},
                "publication": {"status": "not_reported"},
                "transport": {
                    "status": "ready"
                    if self._transport is not None
                    else "stopped"
                },
                "storage": {"status": storage_status},
            }
            if self._desired_reconciler is not None:
                try:
                    payload["polling"] = self._desired_reconciler.health()
                except Exception:
                    payload["polling"] = {"status": "degraded"}
            else:
                payload["polling"] = {"status": "not_configured"}
            return payload

    def _run_claims(self) -> None:
        try:
            while not self._stop.is_set():
                result = self._coordinator.run_once()
                if result in {"idle", "saturated"}:
                    self._stop.wait(self._idle_poll)
        except Exception:
            self._degrade()

    def _run_heartbeat(self) -> None:
        try:
            while not self._stop.wait(self._heartbeat):
                if not self._coordinator.heartbeat():
                    raise RuntimeError("coordinator ownership was lost")
        except Exception:
            self._degrade()

    def _degrade(self) -> None:
        with self._state_lock:
            if self._state in {"starting", "ready"}:
                self._state = "degraded"
        self._stop.set()


__all__ = ["CoordinatorService", "default_transport_factory"]
