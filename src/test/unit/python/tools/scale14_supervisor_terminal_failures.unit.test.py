from __future__ import annotations
from types import SimpleNamespace
import pytest
from repomap_kg.storage.staging_event_transport import StagingEventFrame
from scale14_actual_refresh_supervisor import (
    ActualRefreshSupervisor,
    ProtectedLaunchLimits,
)
from scale15_terminal_contracts import (
    ControlFailureCode,
    ReconciliationStatus,
)

from src.test.unit.python.tools.scale14_supervisor_test_fakes import (
    _phase,
    _Channel,
    _Process,
    _LiveUntilSignalProcess,
    _TimeoutChannel,
    _Resources,
    _Backend,
)

from src.test.unit.python.tools.scale14_supervisor_test_fixtures import (
    _Clock,
    _CrossingClock,
    _CancellationChannel,
    _CancellationProcess,
    _CrossingResources,
    _terminal,
)


def test_actual_supervisor_fails_closed_on_open_lifecycle() -> None:
    order: list[str] = []
    channel = _Channel(
        [StagingEventFrame(1, "phase", _phase("started", 10))]
    )
    process = _Process(channel)
    supervisor = ActualRefreshSupervisor(
        process,
        channel,
        _Resources(),
        _Backend(order),
        terminal_reader=lambda: _terminal(published=True),
        cleanup_verifier=lambda state: state.cleanup_state,
        terminal_backend_reader=lambda: {"observer": 1},
        limits=ProtectedLaunchLimits(30, 30, 30, 30),
        storage_baseline=_Resources().capture_baseline(),
        clock_ns=_Clock(),
    )

    result = supervisor.run()

    assert result.primary_control_failure is ControlFailureCode.LIFECYCLE_INCOMPLETE
    assert result.reconciliation_status is ReconciliationStatus.RECONCILED
    assert len(process.signals) <= 1
    assert channel.closed is True


def test_actual_supervisor_requires_terminal_resource_sample(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []
    channel = _Channel(
        [
            StagingEventFrame(1, "phase", _phase("started", 10)),
            StagingEventFrame(2, "phase", _phase("completed", 20)),
        ]
    )
    process = _Process(channel)
    resources = _Resources()
    monkeypatch.setattr(resources, 'capture', lambda **_kwargs: None)
    supervisor = ActualRefreshSupervisor(
        process,
        channel,
        resources,
        _Backend(order),
        terminal_reader=lambda: _terminal(published=True),
        cleanup_verifier=lambda state: state.cleanup_state,
        terminal_backend_reader=lambda: {"observer": 1},
        limits=ProtectedLaunchLimits(30, 30, 30, 30),
        storage_baseline=resources.capture_baseline(),
        clock_ns=_Clock(),
    )

    result = supervisor.run()

    assert result.primary_control_failure is (
        ControlFailureCode.TERMINAL_RESOURCE_UNAVAILABLE
    )
    assert result.terminal_resource_available is False
    assert process.signals == []


def test_live_backend_observation_does_not_depend_on_resource_cadence(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []
    channel = _Channel([])
    resources = _Resources()
    monkeypatch.setattr(resources, 'capture', lambda **_kwargs: None)
    backend = _Backend(order)
    def observed_summary():
        order.append("backend-summary")
        return {"observer": 1, "postgres_internal": 1}

    monkeypatch.setattr(backend, 'summary', observed_summary)
    supervisor = ActualRefreshSupervisor(
        _Process(channel),
        channel,
        resources,
        backend,
        terminal_reader=lambda: _terminal(published=False),
        cleanup_verifier=lambda state: state.cleanup_state,
        limits=ProtectedLaunchLimits(30, 30, 30, 30),
        storage_baseline=resources.capture_baseline(),
        clock_ns=_Clock(),
    )

    supervisor._observe(2, 1, terminal=False)

    assert order == ["backend-summary"]


@pytest.mark.parametrize("category", ("ambient_client", "unknown"))
def test_actual_supervisor_signals_once_on_nonexclusive_backend(category: str, monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []
    channel = _TimeoutChannel(
        [StagingEventFrame(1, "phase", _phase("started", 10))]
    )
    process = _LiveUntilSignalProcess(channel)
    backend = _Backend(order)
    monkeypatch.setattr(backend, 'summary', lambda: {"observer": 1, category: 1})
    supervisor = ActualRefreshSupervisor(
        process,
        channel,
        _Resources(),
        backend,
        terminal_reader=lambda: _terminal(published=False),
        cleanup_verifier=lambda state: state.cleanup_state,
        terminal_backend_reader=lambda: {"observer": 1},
        limits=ProtectedLaunchLimits(30, 30, 30, 30),
        storage_baseline=_Resources().capture_baseline(),
        clock_ns=_Clock(),
    )

    result = supervisor.run()

    assert len(process.signals) == 1
    assert result.primary_control_failure is (
        ControlFailureCode.AMBIENT_CLIENT_DETECTED
        if category == "ambient_client"
        else ControlFailureCode.BACKEND_OWNERSHIP_UNKNOWN
    )
    assert result.reconciliation_status is ReconciliationStatus.RECONCILED


def test_actual_supervisor_signals_once_when_storage_baseline_is_unavailable() -> None:
    order: list[str] = []
    channel = _Channel(
        [StagingEventFrame(1, "phase", _phase("started", 10))]
    )
    process = _LiveUntilSignalProcess(channel)
    storage_baseline = SimpleNamespace(
        metric_code="postgresql_pgdata_allocated_delta",
        scope="owned_postgresql_pgdata",
        baseline_bytes=None,
        current_bytes=None,
        delta_bytes=None,
        free_bytes=None,
        availability="unavailable",
        sampling_elapsed_ns=1,
    )

    supervisor = ActualRefreshSupervisor(
            process,
            channel,
            _Resources(),
            _Backend(order),
            terminal_reader=lambda: _terminal(published=False),
            cleanup_verifier=lambda state: state.cleanup_state,
            terminal_backend_reader=lambda: {"observer": 1},
            limits=ProtectedLaunchLimits(30, 30, 30, 30),
            storage_baseline=storage_baseline,
            clock_ns=_Clock(),
        )

    result = supervisor.run()

    assert len(process.signals) == 1
    assert result.primary_control_failure is (
        ControlFailureCode.RESOURCE_READER_UNAVAILABLE
    )


def test_actual_supervisor_retains_simultaneous_later_and_terminal_crossings() -> None:
    order: list[str] = []
    channel = _CancellationChannel()
    process = _CancellationProcess(channel, exit_code=1)
    channel.process = process
    supervisor = ActualRefreshSupervisor(
        process,
        channel,
        _CrossingResources(),
        _Backend(order),
        terminal_reader=lambda: _terminal(published=False),
        cleanup_verifier=lambda state: state.cleanup_state,
        terminal_backend_reader=lambda: {"observer": 1},
        limits=ProtectedLaunchLimits(100, 1, 100, 100),
        storage_baseline=_Resources().capture_baseline(),
        clock_ns=_CrossingClock(),
        poll_interval_seconds=1.0,
    )

    result = supervisor.run()
    metrics = {
        metric.metric_code: metric
        for metric in result.threshold_evaluation.metrics
    }

    assert result.signal_count == 1
    assert result.active_boundary_at_stop == "refresh.source_discovery"
    assert metrics["phase_elapsed_seconds"].crossed_before_cancel is True
    assert metrics["postgresql_pgdata_allocated_delta"].crossed_before_cancel is True
    assert metrics["wal_upper_bound_delta"].crossed_after_cancel is True
    assert metrics["temporary_byte_upper_bound_delta"].crossed_terminal is True
