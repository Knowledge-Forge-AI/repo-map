from __future__ import annotations
from repomap_kg.storage.staging_event_transport import StagingEventFrame
from repomap_kg.storage.staging_operation_events import (
    StagingOperationEventCategory,
)
from scale14_actual_refresh_supervisor import (
    ActualRefreshSupervisor,
    ProtectedLaunchLimits,
)
from scale15_terminal_contracts import (
    CleanupState,
    PublicationState,
    StageState,
    TerminalReadback,
    BoundRefreshExpectation,
)

from src.test.unit.python.tools.scale14_supervisor_test_fakes import (
    _phase,
    _operation,
    _authority,
    _expectation,
    _Channel,
    _Process,
    _Resources,
    _Backend,
    _Startup,
    _PreparationAuthority,
)


class _Clock:
    def __init__(self):
        self.value = 1_000_000_000

    def __call__(self):
        self.value += 1_000_000
        return self.value


class _CrossingClock:
    def __init__(self):
        self.value = 0

    def __call__(self):
        self.value += 2_000_000_000
        return self.value


class _CancellationChannel(_Channel):
    def __init__(self):
        super().__init__([StagingEventFrame(1, "phase", _phase("started", 10))])
        self.process = None
        self.post_signal_timeout = False
        self.terminal_sent = False

    def receive(self, *, timeout_seconds, validator=None, readiness=None):
        if readiness is not None:
            readiness()
        if self.frames:
            frame = self.frames.pop(0)
            if validator is not None:
                validator(frame)
            return frame
        if self.process is not None and self.process.signals and not self.terminal_sent:
            if not self.post_signal_timeout:
                self.post_signal_timeout = True
                raise TimeoutError
            self.terminal_sent = True
            frame = StagingEventFrame(2, "phase", _phase("cancelled", 20))
            if validator is not None:
                validator(frame)
            return frame
        raise TimeoutError


class _CancellationProcess(_Process):
    def poll(self):
        return 1 if self.channel.terminal_sent else None


class _CrossingResources(_Resources):
    def __init__(self):
        super().__init__()
        self.index = 0

    def capture(self, *, force=False):
        samples = (
            (17 * 1024**3, 0, 0),
            (18 * 1024**3, 9 * 1024**3, 0),
            (18 * 1024**3, 9 * 1024**3, 3 * 1024**3),
        )
        storage, wal, temporary = samples[min(self.index, 2)]
        self.index += 1
        sample = super().capture(force=force)
        sample.values["postgresql_pgdata_allocated_delta"] = storage
        sample.values["wal_upper_bound_delta"] = wal
        sample.values["temporary_byte_upper_bound_delta"] = temporary
        return sample


def _terminal(*, published: bool) -> TerminalReadback:
    return TerminalReadback(
        PublicationState.PUBLISHED if published else PublicationState.NOT_PUBLISHED,
        (
            StageState.PUBLISHED_RECONCILED
            if published
            else StageState.FAILED_RECONCILED
        ),
        CleanupState.ELIGIBLE,
        {
            "files": 1 if published else 0,
            "raw_observations": 1 if published else 0,
            "canonical_nodes": 0,
            "canonical_edges": 0,
            "canonical_evidence": 0,
            "canonical_node_evidence": 0,
            "canonical_edge_evidence": 0,
        },
        "0" * 64,
        1,
        1 if published else None,
    )


def _success_supervisor(order, *, hybrid_preparation=False):
    channel = _Channel(
        [
            StagingEventFrame(
                0,
                "measurement",
                {"category": "family_preparation", "value": 1},
            ),
            StagingEventFrame(1, "phase", _phase("started", 10)),
            StagingEventFrame(2, "authority", _authority()),
            StagingEventFrame(
                3,
                "operation",
                _operation(StagingOperationEventCategory.STARTED, 12),
            ),
            StagingEventFrame(
                4,
                "operation",
                _operation(StagingOperationEventCategory.COMPLETED, 16),
            ),
            StagingEventFrame(5, "phase", _phase("completed", 20)),
        ]
    )
    process = _Process(channel)
    resources = _Resources(order)
    storage_baseline = resources.capture_baseline()
    preparation_authority = (
        _PreparationAuthority(order, resources.capture(force=False))
        if hybrid_preparation
        else None
    )
    supervisor = ActualRefreshSupervisor(
        process,
        channel,
        resources,
        _Backend(order),
        terminal_reader=lambda expectation: (
            isinstance(expectation, BoundRefreshExpectation)
            and order.append("receipt")
            or _terminal(published=True)
        ),
        cleanup_verifier=lambda state: order.append("cleanup")
        or state.cleanup_state,
        terminal_backend_reader=lambda: order.append("terminal-backend")
        or {"observer": 1, "postgres_internal": 1},
        limits=ProtectedLaunchLimits(30, 30, 30, 30),
        storage_baseline=storage_baseline,
        prelaunch_expectation=_expectation(),
        startup=_Startup(order),
        preparation_authority=preparation_authority,
        clock_ns=_Clock(),
    )
    return supervisor, channel, process, resources
