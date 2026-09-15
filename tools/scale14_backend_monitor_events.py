"""Telemetry events, protocols, and stream consumption for SCALE14."""

from __future__ import annotations

from threading import Event
from typing import Callable, Mapping, Protocol
from typing_extensions import TypeVar

from actual_refresh_failure_causality import FailureCausalityAuthority
from repomap_kg.storage.backend_telemetry import TelemetryEventKind
from repomap_kg.storage.backend_telemetry_contracts import ConnectionTelemetryEvent
from scale28_backend_observer_session import (
    BackendMonitorError,
    BackendObserverProtocol,
    BackendObserverSession,
    ObserverFailureBoundary,
    ObserverSessionState,
)
from scale28_observer_deadlines import ObserverOperationClass


class MonitorObserverProtocol(BackendObserverProtocol, Protocol):
    """Structural contract for backend observer implementations."""

    def consume_pipe_event(
        self,
        event: ConnectionTelemetryEvent,
        connection: object,
        acknowledgement_fd: int,
        /,
    ) -> None:
        ...

    def public_summary(
        self,
        connection: object,
        /,
    ) -> Mapping[str, int]:
        ...


_StreamT_contra = TypeVar("_StreamT_contra", contravariant=True)
_StreamT = TypeVar("_StreamT")


class EventReaderProtocol(Protocol[_StreamT_contra]):
    """Structural contract for telemetry event reader callables."""

    def __call__(
        self,
        stream: _StreamT_contra,
        *,
        readiness: Callable[[], None],
    ) -> ConnectionTelemetryEvent | None:
        ...


_StreamObserverT = TypeVar(
    "_StreamObserverT",
    bound=MonitorObserverProtocol,
)


def consume_telemetry_stream(
    *,
    event_reader: EventReaderProtocol[_StreamT],
    event_stream: _StreamT,
    reader_ready: Event,
    session: BackendObserverSession[_StreamObserverT],
    acknowledgement_fd: int,
    ownership_changed: Event,
    ready: Event,
    startup_settled: Event,
    failure_causality: FailureCausalityAuthority | None,
    child_released: Callable[[], bool] | None,
    handoff_timeout: float,
) -> BaseException | None:
    """Consume pipe events until EOF or unrecoverable error."""
    failure: BaseException | None = None
    try:
        while True:
            event = event_reader(
                event_stream,
                readiness=reader_ready.set,
            )
            if event is None:
                return None
            session.run(
                ObserverFailureBoundary.EVENT_APPLY,
                lambda observer, connection: observer.consume_pipe_event(
                    event,
                    connection,
                    acknowledgement_fd,
                ),
                allowed_states=(ObserverSessionState.ACTIVE,),
                operation_class=ObserverOperationClass.SQL_BOUNDED,
                timeout_seconds=handoff_timeout,
            )
            ownership_changed.set()
            if event.event in {TelemetryEventKind.CONNECTION_READY, "ready"}:
                ready.set()
                startup_settled.set()
    except BaseException as error:
        if isinstance(error, BackendMonitorError):
            failure = error
        else:
            failure = BackendMonitorError(
                "backend telemetry failed",
                category="backend_telemetry_failed",
            )
            failure.__cause__ = error
        if failure_causality is not None and not isinstance(
            error, BackendMonitorError
        ):
            released = (
                True
                if child_released is None
                else child_released()
            )
            failure_causality.record_exception(
                failure,
                code="backend_telemetry_failed",
                authority_owner="backend_ownership",
                lifecycle_boundary=(
                    "active_backend_telemetry" if released else "startup"
                ),
                existed_before_child_release=not released,
                test_injected=bool(getattr(error, "test_injected", False)),
            )
        return failure

