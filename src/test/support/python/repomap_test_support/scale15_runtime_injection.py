"""Public-safe disposable SCALE15 runtime test injection and fault simulation."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from actual_refresh_failure_causality import FailureCausalityAuthority
from repomap_kg.storage.backend_observer import BackendOwnershipObserver
from repomap_kg.storage.backend_telemetry_contracts import ConnectionTelemetryEvent
from repomap_kg.storage.staging_event_transport import (
    StagingEventFrame,
)
from scale14_backend_monitor import BackendMonitorError
from scale14_backend_monitor_events import MonitorObserverProtocol
from scale15_terminal_contracts import ControlFailure, ControlFailureCode


class _InjectedChannel:
    def __init__(
        self,
        channel,
        injection: str | None,
        target: str | None,
    ) -> None:
        self._channel = channel
        self._injection = injection
        self._target = target
        self._fail_next = False
        self.target_seen = False

    def receive(
        self,
        *,
        timeout_seconds: float,
        validator: Callable[[StagingEventFrame], None] | None = None,
        readiness: Callable[[], None] | None = None,
    ) -> StagingEventFrame:
        if self._fail_next:
            self._fail_next = False
            error = OSError("injected transport loss")
            setattr(error, "test_injected", True)
            raise error
        accepted: list[StagingEventFrame] = []

        def validate(frame: StagingEventFrame) -> None:
            transformed = frame
            if (
                frame.category == "operation"
                and frame.payload.get("operation_code") == self._target
            ):
                if self._injection == "event_transport_failed":
                    self._fail_next = True
                elif self._injection == "operation_attribution_unknown":
                    payload = dict(frame.payload)
                    payload["operation_code"] = "invalid.operation"
                    transformed = StagingEventFrame(
                        frame.sequence, frame.category, payload
                    )
            if validator is not None:
                validator(transformed)
            lifecycle_code = transformed.payload.get(
                "phase_code"
            ) or transformed.payload.get("operation_code")
            if (
                transformed.payload.get("event_category") == "started"
                and lifecycle_code == self._target
            ):
                self.target_seen = True
            accepted.append(transformed)

        self._channel.receive(
            timeout_seconds=timeout_seconds,
            validator=validate,
            readiness=readiness,
        )
        return accepted[0]

    def close(self) -> None:
        self._channel.close()


class _InjectedBackend:
    def __init__(
        self,
        backend,
        injection: str | None,
        channel,
        *,
        failure_causality: FailureCausalityAuthority | None = None,
        startup_ambient_connection = None,
    ) -> None:
        self._backend = backend
        self._injection = injection
        self._channel = channel
        self._failure_causality = failure_causality
        self._startup_ambient_connection = startup_ambient_connection

    def __getattr__(self, name: str):
        return getattr(self._backend, name)

    def startup_summary(
        self,
        *,
        timeout_seconds: float = 0.5,
    ) -> Mapping[str, int]:
        try:
            summary = self._backend.startup_summary(
                timeout_seconds=timeout_seconds,
            )
        finally:
            if self._startup_ambient_connection is not None:
                self._startup_ambient_connection.close()
        if self._injection != "startup_ambient_client":
            return summary
        if summary.get("ambient_client", 0) < 1:
            raise AssertionError("startup ambient client was not observed")
        return summary

    def summary(self) -> dict[str, int]:
        if (
            self._injection == "backend_telemetry_failed"
            and self._channel.target_seen
        ):
            error = BackendMonitorError(
                "injected telemetry loss",
                category="backend_telemetry_failed",
            )
            setattr(error, "test_injected", True)
            if self._failure_causality is not None:
                self._failure_causality.record_exception(
                    error,
                    code="backend_telemetry_failed",
                    authority_owner="backend_ownership",
                    lifecycle_boundary="active_backend_telemetry",
                    existed_before_child_release=False,
                    test_injected=True,
                )
            raise error
        summary = dict(self._backend.summary())
        if (
            self._injection == "ambient_client_detected"
            and self._channel.target_seen
        ):
            summary["ambient_client"] = 1
        return summary


class _InjectedObserver(MonitorObserverProtocol):
    def __init__(
        self,
        observer: BackendOwnershipObserver,
        injection: str | None,
        channel: _InjectedChannel,
    ) -> None:
        self._observer = observer
        self._injection = injection
        self._channel = channel
        self._summary_failed = False
        self._event_failed = False

    def __getattr__(self, name: str) -> object:
        return getattr(self._observer, name)

    def register_connection(self, connection: object) -> object:
        return self._observer.register_connection(connection)

    def public_summary(self, connection: object) -> Mapping[str, int]:
        if self._channel.target_seen and not self._summary_failed:
            if self._injection == "observer_active_summary_failed":
                self._summary_failed = True
                error = RuntimeError("injected observer summary failure")
                setattr(error, "test_injected", True)
                raise error
            if self._injection == "observer_connection_lost":
                self._summary_failed = True
                close = getattr(connection, "close", None)
                if callable(close):
                    close()
                error = RuntimeError("injected observer connection loss")
                setattr(error, "test_injected", True)
                raise error
        return self._observer.public_summary(connection)

    def consume_pipe_event(
        self,
        event: ConnectionTelemetryEvent,
        connection: object,
        acknowledgement_fd: int,
    ) -> None:
        if (
            self._injection == "observer_event_apply_failed"
            and self._channel.target_seen
            and not self._event_failed
        ):
            self._event_failed = True
            error = RuntimeError("injected observer event failure")
            setattr(error, "test_injected", True)
            raise error
        self._observer.consume_pipe_event(
            event, connection, acknowledgement_fd
        )


class _InjectedResources:
    def __init__(
        self,
        resources,
        injection: str | None,
        channel: _InjectedChannel,
        *,
        failure_causality: FailureCausalityAuthority | None = None,
    ) -> None:
        self._resources = resources
        self._injection = injection
        self._channel = channel
        self._failure_causality = failure_causality

    def capture(self, *, force: bool = False):
        if (
            self._injection == "resource_reader_unavailable"
            and self._channel.target_seen
            and not force
        ):
            error = ControlFailure(ControlFailureCode.RESOURCE_READER_UNAVAILABLE)
            setattr(error, "test_injected", True)
            if self._failure_causality is not None:
                self._failure_causality.record_exception(
                    error,
                    code="resource_reader_unavailable",
                    authority_owner="resource_sampling",
                    lifecycle_boundary="active_resource_read",
                    existed_before_child_release=False,
                    test_injected=True,
                )
            raise error
        return self._resources.capture(force=force)

    def settle_startup(self):
        settle = getattr(self._resources, "settle_startup", None)
        if callable(settle):
            return settle()
        return None

    def accept_preparation_baseline(self, baseline):
        return self._resources.accept_preparation_baseline(baseline)

    def close(self) -> None:
        self._resources.close()


__all__ = [
    "_InjectedBackend",
    "_InjectedChannel",
    "_InjectedObserver",
    "_InjectedResources",
]
