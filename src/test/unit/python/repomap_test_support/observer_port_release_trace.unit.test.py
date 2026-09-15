from repomap_test_support.observer_trace import (
    SUPERVISED_CYCLE_TRACE_CAPACITY,
    ObserverTraceKind,
    ObserverTraceRecorder,
    observe_port_release,
)


def test_port_release_observes_exact_fake_shutdown_boundaries() -> None:
    ticks = iter(range(10, 200, 10))
    recorder = ObserverTraceRecorder(clock_ns=lambda: next(ticks))
    calls = []
    probes = iter((False, False, True))

    result = observe_port_release(
        recorder,
        port_token="port-1",
        shutdown=lambda: calls.append("shutdown"),
        container_stopped=lambda: calls.append("container-stopped"),
        container_removed=lambda: calls.append("container-removed"),
        network_removed=lambda: calls.append("network-removed"),
        process_settled=lambda: calls.append("process-settled"),
        bindable_probe=lambda: next(probes),
        immediate_exact_cleanup_probe=lambda: False,
        final_exact_cleanup_probe=lambda: True,
        max_probes=3,
    )

    assert result.probes == 3
    assert result.immediate_selected_port_bindable is False
    assert result.immediate_exact_cleanup_proved is False
    assert result.eventual_selected_port_bindable is True
    assert result.final_exact_live_resource_cleanup is True
    assert calls == [
        "shutdown",
        "container-stopped",
        "container-removed",
        "network-removed",
        "process-settled",
    ]
    events = recorder.snapshot().events
    assert {event.port_token for event in events} == {"port-1"}
    kinds = [event.kind for event in events]
    assert kinds == [
        ObserverTraceKind.PORT_STOP_REQUESTED,
        ObserverTraceKind.PORT_CONTAINER_STOPPED,
        ObserverTraceKind.PORT_CONTAINER_REMOVED,
        ObserverTraceKind.PORT_NETWORK_REMOVED,
        ObserverTraceKind.PORT_PROCESS_SETTLED,
        ObserverTraceKind.PORT_BINDABLE,
    ]


def test_port_and_exact_cleanup_facts_are_independent() -> None:
    recorder = ObserverTraceRecorder()

    result = observe_port_release(
        recorder,
        port_token="port-1",
        shutdown=lambda: None,
        container_stopped=lambda: None,
        container_removed=lambda: None,
        network_removed=lambda: None,
        process_settled=lambda: None,
        bindable_probe=lambda: False,
        immediate_exact_cleanup_probe=lambda: True,
        final_exact_cleanup_probe=lambda: False,
    )

    assert result.immediate_selected_port_bindable is False
    assert result.immediate_exact_cleanup_proved is True
    assert result.eventual_selected_port_bindable is False
    assert result.final_exact_live_resource_cleanup is False

    released_port_with_live_resource = observe_port_release(
        ObserverTraceRecorder(),
        port_token="port-1",
        shutdown=lambda: None,
        container_stopped=lambda: None,
        container_removed=lambda: None,
        network_removed=lambda: None,
        process_settled=lambda: None,
        bindable_probe=lambda: True,
        immediate_exact_cleanup_probe=lambda: False,
        final_exact_cleanup_probe=lambda: False,
    )

    assert released_port_with_live_resource.immediate_selected_port_bindable is True
    assert released_port_with_live_resource.immediate_exact_cleanup_proved is False
    assert released_port_with_live_resource.eventual_selected_port_bindable is True
    assert released_port_with_live_resource.final_exact_live_resource_cleanup is False


def test_supervised_cycle_capacity_is_explicit_and_pre_registered() -> None:
    recorder = ObserverTraceRecorder.for_supervised_cycle()

    assert recorder.capacity_pre_registered is True
    assert recorder.configured_capacity == SUPERVISED_CYCLE_TRACE_CAPACITY
    assert recorder.configured_capacity != ObserverTraceRecorder().configured_capacity
    assert recorder.capacity_metadata() == {
        "configured_capacity": SUPERVISED_CYCLE_TRACE_CAPACITY,
        "retained_events": 0,
        "remaining_capacity": SUPERVISED_CYCLE_TRACE_CAPACITY,
        "overflowed": False,
    }
