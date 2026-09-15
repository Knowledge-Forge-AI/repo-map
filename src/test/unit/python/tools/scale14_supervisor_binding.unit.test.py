from __future__ import annotations
import pytest
from repomap_kg.storage.staging_event_transport import StagingEventFrame
from repomap_kg.storage.staging_operation_events import (
    StagingOperationEventCategory,
)
from scale14_actual_refresh_supervisor import (
    ActualRefreshSupervisor,
    ProtectedLaunchLimits,
)
from scale15_terminal_contracts import (
    ControlFailureCode,
)

from src.test.unit.python.tools.scale14_supervisor_test_fakes import (
    _phase,
    _operation,
    _authority,
    _expectation,
    _Channel,
    _LiveUntilSignalProcess,
    _TimeoutChannel,
    _Resources,
    _Backend,
    _Startup,
)

from src.test.unit.python.tools.scale14_supervisor_test_fixtures import (
    _Clock,
    _terminal,
)


def test_scale16_supervisor_rejects_owned_backend_before_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []
    channel = _TimeoutChannel(
        [StagingEventFrame(1, "phase", _phase("started", 10))]
    )
    process = _LiveUntilSignalProcess(channel)
    resources = _Resources()
    backend = _Backend(order)
    monkeypatch.setattr(backend, 'summary', lambda: {
        "observer": 1,
        "postgres_internal": 1,
        "direct_owned_client": 1,
    })
    supervisor = ActualRefreshSupervisor(
        process,
        channel,
        resources,
        backend,
        terminal_reader=lambda _expectation: _terminal(published=False),
        cleanup_verifier=lambda state: state.cleanup_state,
        terminal_backend_reader=lambda: {"observer": 1},
        limits=ProtectedLaunchLimits(30, 30, 30, 30),
        storage_baseline=resources.capture_baseline(),
        prelaunch_expectation=_expectation(),
        startup=_Startup(order),
        clock_ns=_Clock(),
    )

    result = supervisor.run()

    assert result.primary_control_failure is ControlFailureCode.LAUNCH_AUTHORITY_LATE
    assert result.signal_count == 1


def test_scale16_supervisor_rejects_canonicalization_before_binding() -> None:
    order: list[str] = []
    channel = _Channel(
        [
            StagingEventFrame(
                1,
                "phase",
                _phase("started", 10, "refresh.canonicalization"),
            )
        ]
    )
    process = _LiveUntilSignalProcess(channel)
    resources = _Resources()
    supervisor = ActualRefreshSupervisor(
        process,
        channel,
        resources,
        _Backend(order),
        terminal_reader=lambda _expectation: _terminal(published=False),
        cleanup_verifier=lambda state: state.cleanup_state,
        limits=ProtectedLaunchLimits(30, 30, 30, 30),
        storage_baseline=resources.capture_baseline(),
        prelaunch_expectation=_expectation(),
        startup=_Startup(order),
        clock_ns=_Clock(),
    )

    result = supervisor.run()

    assert result.primary_control_failure is ControlFailureCode.LAUNCH_AUTHORITY_LATE
    assert result.signal_count == 1


def test_scale16_transport_failure_before_binding_remains_unbound(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []
    channel = _TimeoutChannel([])
    def fail_receive(**kwargs):
        readiness = kwargs.get("readiness")
        if readiness is not None:
            readiness()
        raise OSError("transport unavailable")

    monkeypatch.setattr(channel, 'receive', fail_receive)
    process = _LiveUntilSignalProcess(channel)
    resources = _Resources()
    supervisor = ActualRefreshSupervisor(
        process,
        channel,
        resources,
        _Backend(order),
        terminal_reader=lambda _expectation: _terminal(published=False),
        cleanup_verifier=lambda state: state.cleanup_state,
        limits=ProtectedLaunchLimits(30, 30, 30, 30),
        storage_baseline=resources.capture_baseline(),
        prelaunch_expectation=_expectation(),
        startup=_Startup(order),
        clock_ns=_Clock(),
    )

    result = supervisor.run()

    assert result.primary_control_failure is ControlFailureCode.EVENT_TRANSPORT_FAILED
    assert result.launch_binding_state == "launch_authority_missing"
    assert result.launch_binding_match == "unbound"
    assert result.signal_count == 1


def test_validate_before_ack_preserves_operation_attribution_failure() -> None:
    order: list[str] = []
    payload = _operation(StagingOperationEventCategory.STARTED, 12)
    payload["operation_code"] = "invalid.operation"
    channel = _Channel(
        [
            StagingEventFrame(1, "authority", _authority()),
            StagingEventFrame(2, "operation", payload),
        ]
    )
    process = _LiveUntilSignalProcess(channel)
    resources = _Resources()
    supervisor = ActualRefreshSupervisor(
        process,
        channel,
        resources,
        _Backend(order),
        terminal_reader=lambda _expectation: _terminal(published=False),
        cleanup_verifier=lambda state: state.cleanup_state,
        limits=ProtectedLaunchLimits(30, 30, 30, 30),
        storage_baseline=resources.capture_baseline(),
        prelaunch_expectation=_expectation(),
        startup=_Startup(order),
        clock_ns=_Clock(),
    )

    result = supervisor.run()

    assert result.primary_control_failure is (
        ControlFailureCode.OPERATION_ATTRIBUTION_UNKNOWN
    )
    assert result.signal_count == 1
