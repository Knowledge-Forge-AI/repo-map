from __future__ import annotations
from repomap_kg.storage.staging_event_transport import StagingEventFrame
from scale14_actual_refresh_supervisor import (
    ActualRefreshSupervisor,
    ProtectedLaunchLimits,
)
from scale15_terminal_contracts import (
    ControlFailureCode,
    PublicationState,
    TerminalCategory,
)

from src.test.unit.python.tools.scale14_supervisor_test_fakes import (
    _phase,
    _authority,
    _expectation,
    _Channel,
    _Process,
    _LiveUntilSignalProcess,
    _Resources,
    _Backend,
    _Startup,
)

from src.test.unit.python.tools.scale14_supervisor_test_fixtures import (
    _Clock,
    _terminal,
    _success_supervisor,
)


def test_actual_supervisor_composes_lifecycle_quiescence_and_receipt_first() -> None:
    order: list[str] = []
    supervisor, channel, process, resources = _success_supervisor(order)

    result = supervisor.run()

    assert result.terminal_category is TerminalCategory.COMPLETED
    assert result.child_exit_code == 0
    assert result.signal_count == 0
    assert result.phase_sequence == ("refresh.source_discovery",)
    assert result.operation_sequence == ("merge.files",)
    assert result.publication_state is PublicationState.PUBLISHED
    assert resources.baselined is True
    assert resources.terminal_forces[-1] is True
    assert resources.closed is True
    assert order.index("resource-close") < order.index("backend-quiescent")
    assert order.index("backend-quiescent") < order.index("terminal-backend")
    assert order.index("terminal-backend") < order.index("receipt")
    assert order.index("receipt") < order.index("cleanup")
    assert channel.closed is True
    assert process.signals == []


def test_actual_supervisor_keeps_final_hybrid_release_in_parent() -> None:
    order: list[str] = []
    supervisor, _channel, _process, _resources = _success_supervisor(
        order,
        hybrid_preparation=True,
    )

    result = supervisor.run()

    assert result.terminal_category is TerminalCategory.COMPLETED
    assert order.count("stable-sample") == 2
    assert order.index("backend-startup-summary:3.4") < order.index("preparation")
    assert order.index("preparation") < order.index("final-readiness")
    assert order.index("transient-clear") < order.index("stable-sample")
    assert order.index("ready-to-release") < order.index("child-released")
    assert order.index("child-released") < order.index(
        "preparation-child-released"
    )
    assert order[-1] == "preparation-settled"


def test_actual_supervisor_releases_after_every_parent_authority_is_ready() -> None:
    order: list[str] = []
    supervisor, _channel, _process, _resources = _success_supervisor(order)

    supervisor.run()

    assert order[:9] == [
        "storage-baseline-ready",
        "backend-start",
        "backend-startup-summary",
        "backend-observer-ready",
        "resource-authorities-ready",
        "event-receiver-ready",
        "failure-collector-ready",
        "child-released",
        "monitoring",
    ]


def test_scale16_supervisor_rejects_missing_binding_on_child_success() -> None:
    order: list[str] = []
    channel = _Channel([StagingEventFrame(1, "phase", _phase("started", 10))])
    process = _Process(channel)
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

    assert result.primary_control_failure is ControlFailureCode.LAUNCH_AUTHORITY_MISSING


def test_scale16_supervisor_rejects_duplicate_binding_without_replacement() -> None:
    order: list[str] = []
    channel = _Channel(
        [
            StagingEventFrame(1, "authority", _authority()),
            StagingEventFrame(2, "authority", _authority(12)),
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

    assert result.primary_control_failure is ControlFailureCode.LAUNCH_AUTHORITY_DUPLICATE
    assert result.signal_count == 1
    assert "direct-scale16" not in str(result.to_payload())
