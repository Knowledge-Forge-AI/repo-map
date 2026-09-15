"""Observed cleanup facts for test-owned observer runtime resources."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from repomap_test_support.observer_trace_evidence import (
    ObserverTraceEvent,
    ObserverTraceKind,
    _PORT_TOKEN_PATTERN,
)


class _TraceRecorder(Protocol):
    def record(
        self,
        kind: ObserverTraceKind,
        *,
        duration_from_ns: int | None = None,
        **values: object,
    ) -> ObserverTraceEvent | None: ...


@dataclass(frozen=True, slots=True)
class PortReleaseObservation:
    probes: int
    release_interval_ns: int | None
    immediate_selected_port_bindable: bool
    immediate_exact_cleanup_proved: bool
    eventual_selected_port_bindable: bool
    final_exact_live_resource_cleanup: bool


def observe_port_release(
    recorder: _TraceRecorder,
    *,
    port_token: str,
    shutdown: Callable[[], object],
    container_stopped: Callable[[], object],
    container_removed: Callable[[], object],
    network_removed: Callable[[], object],
    process_settled: Callable[[], object],
    bindable_probe: Callable[[], bool],
    immediate_exact_cleanup_probe: Callable[[], bool],
    final_exact_cleanup_probe: Callable[[], bool],
    max_probes: int = 1,
) -> PortReleaseObservation:
    """Observe port release separately from exact live-resource cleanup."""
    if (
        _PORT_TOKEN_PATTERN.fullmatch(port_token) is None
        or isinstance(max_probes, bool)
        or max_probes < 1
    ):
        raise ValueError("port release observation is invalid")
    started = recorder.record(
        ObserverTraceKind.PORT_STOP_REQUESTED,
        port_token=port_token,
        detail="completed",
    )
    shutdown()
    container_stopped()
    recorder.record(
        ObserverTraceKind.PORT_CONTAINER_STOPPED,
        port_token=port_token,
        detail="completed",
    )
    container_removed()
    recorder.record(
        ObserverTraceKind.PORT_CONTAINER_REMOVED,
        port_token=port_token,
        detail="completed",
    )
    network_removed()
    recorder.record(
        ObserverTraceKind.PORT_NETWORK_REMOVED,
        port_token=port_token,
        detail="completed",
    )
    process_settled()
    recorder.record(
        ObserverTraceKind.PORT_PROCESS_SETTLED,
        port_token=port_token,
        detail="completed",
    )
    immediate_cleanup = immediate_exact_cleanup_probe()
    immediate_bindable = False
    for probe in range(1, max_probes + 1):
        bindable = bindable_probe()
        if probe == 1:
            immediate_bindable = bindable
        if bindable:
            event = recorder.record(
                ObserverTraceKind.PORT_BINDABLE,
                port_token=port_token,
                duration_from_ns=(started.monotonic_ns if started else None),
                detail="completed",
            )
            return PortReleaseObservation(
                probes=probe,
                release_interval_ns=(event.duration_ns if event else None),
                immediate_selected_port_bindable=immediate_bindable,
                immediate_exact_cleanup_proved=immediate_cleanup,
                eventual_selected_port_bindable=True,
                final_exact_live_resource_cleanup=final_exact_cleanup_probe(),
            )
    return PortReleaseObservation(
        probes=max_probes,
        release_interval_ns=None,
        immediate_selected_port_bindable=immediate_bindable,
        immediate_exact_cleanup_proved=immediate_cleanup,
        eventual_selected_port_bindable=False,
        final_exact_live_resource_cleanup=final_exact_cleanup_probe(),
    )


__all__ = ["PortReleaseObservation", "observe_port_release"]
