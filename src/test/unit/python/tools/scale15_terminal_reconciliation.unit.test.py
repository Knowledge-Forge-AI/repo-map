from __future__ import annotations

from types import SimpleNamespace


from repomap_kg.storage.staging_event_transport import StagingEventFrame
from scale14_actual_refresh_supervisor import (
    ActualRefreshSupervisor,
    ProtectedLaunchLimits,
)
from actual_refresh_startup import StartupState
from scale15_terminal_contracts import (
    CleanupState,
    ControlFailure,
    ControlFailureCode,
    PublicationState,
    ReconciliationStatus,
    StageState,
    TerminalCategory,
    TerminalReadback,
)


def _phase(category: str, sequence: int) -> StagingEventFrame:
    return StagingEventFrame(
        sequence,
        "phase",
        {
            "schema_version": 1,
            "attempt_local_sequence": 1,
            "phase_code": "refresh.source_discovery",
            "event_category": category,
            "monotonic_offset_ns": sequence * 10,
            "duration_ns_or_null": None if category == "started" else 10,
            "terminal_category_or_null": (
                None if category == "started" else category
            ),
            "process_cpu_duration_ns_or_null": None,
        },
    )


class _Channel:
    def __init__(self, frames=(), *, failure: BaseException | None = None):
        self.frames = list(frames)
        self.failure = failure

    def receive(self, *, timeout_seconds, validator=None, readiness=None):
        if readiness is not None:
            readiness()
        if self.frames:
            frame = self.frames.pop(0)
            if validator is not None:
                validator(frame)
            return frame
        if self.failure is not None:
            raise self.failure
        raise EOFError

    def close(self):
        pass

class _Process:
    def __init__(self, channel, *, never_exits: bool = False):
        self.channel = channel
        self.never_exits = never_exits
        self.signals: list[int] = []

    def poll(self):
        if self.never_exits:
            return None
        if self.signals:
            return 1
        return 0 if not self.channel.frames else None

    def send_signal(self, value):
        self.signals.append(value)


class _LiveUntilSignalProcess(_Process):
    def poll(self):
        return 1 if self.signals else None


class _Clock:
    def __init__(self, step=1_000_000):
        self.value = 0
        self.step = step

    def __call__(self):
        self.value += self.step
        return self.value


class _Resources:
    def __init__(self, *, live_failure: bool = False, terminal_failure=False):
        self.live_failure = live_failure
        self.terminal_failure = terminal_failure
        self.terminal_count = 0

    def capture(self, *, force=False):
        if force:
            self.terminal_count += 1
        if (force and self.terminal_failure) or (not force and self.live_failure):
            raise ControlFailure(ControlFailureCode.RESOURCE_READER_UNAVAILABLE)
        return SimpleNamespace(
            values={
                "client_peak_rss_bytes": 1,
                "owned_postgresql_process_group_rss_bytes": 1,
                "temporary_byte_upper_bound_delta": 0,
                "wal_upper_bound_delta": 0,
                "concurrent_profiles": 1,
                "postgresql_pgdata_allocated_delta": 0,
                "postgresql_pgdata_backing_free_bytes": 1024,
                "postgresql_pgdata_reader_elapsed_ns": 1,
            },
            availability={
                "client_peak_rss_bytes": "available",
                "owned_postgresql_process_group_rss_bytes": "available",
                "temporary_byte_upper_bound_delta": "available",
                "wal_upper_bound_delta": "available",
                "concurrent_profiles": "available",
                "postgresql_pgdata_allocated_delta": "available",
                "postgresql_pgdata_backing_free_bytes": "available",
                "postgresql_pgdata_reader_elapsed_ns": "available",
            },
        )


class _Backend:
    def __init__(self, *, quiescence_failure=False):
        self.quiescence_failure = quiescence_failure

    def start(self):
        pass

    def summary(self):
        return {"observer": 1}

    def startup_summary(self):
        return {"observer": 1}

    def release_when_ready(self, release, summary_validator):
        summary = {"observer": 1}
        summary_validator(summary)
        release()
        return summary

    def wait_quiescent(self, timeout_seconds):
        if self.quiescence_failure:
            raise RuntimeError("private backend detail")
        return {"observer": 1}

    def close(self):
        pass

    def close_with_timeout(self, timeout_seconds):
        assert timeout_seconds > 0
        self.close()


class _Startup:
    def __init__(self, release_event) -> None:
        self.release_event = release_event
        self.state = StartupState.CONSTRUCTED

    @property
    def released(self):
        return self.state in {StartupState.CHILD_RELEASED, StartupState.MONITORING}

    def mark_storage_baseline_ready(self):
        self.state = StartupState.STORAGE_BASELINE_READY

    def mark_backend_observer_ready(self):
        self.state = StartupState.BACKEND_OBSERVER_READY

    def mark_resource_authorities_ready(self):
        self.state = StartupState.RESOURCE_AUTHORITIES_READY

    def mark_event_receiver_ready(self):
        self.state = StartupState.EVENT_RECEIVER_READY

    def mark_failure_collector_ready(self):
        self.state = StartupState.FAILURE_COLLECTOR_READY

    def release(self):
        self.state = StartupState.CHILD_RELEASED
        self.release_event.set()

    def mark_monitoring(self):
        self.state = StartupState.MONITORING

    def fail(self):
        self.state = StartupState.FAILED
        self.release_event.set()

    def close(self):
        self.state = StartupState.CLOSED


class _ReleaseAwareEOFChannel(_Channel):
    def __init__(self):
        from threading import Event

        super().__init__(())
        self.release_event = Event()

    def receive(self, *, timeout_seconds, validator=None, readiness=None):
        del validator
        if readiness is not None:
            readiness()
        if not self.release_event.wait(timeout_seconds):
            raise TimeoutError
        raise EOFError


def _baseline():
    return SimpleNamespace(
        metric_code="postgresql_pgdata_allocated_delta",
        scope="owned_postgresql_pgdata",
        baseline_bytes=1,
        current_bytes=1,
        delta_bytes=0,
        free_bytes=1024,
        availability="available",
        sampling_elapsed_ns=1,
    )


def _readback() -> TerminalReadback:
    return TerminalReadback(
        PublicationState.PUBLISHED,
        StageState.PUBLISHED_RECONCILED,
        CleanupState.ELIGIBLE,
        {
            "files": 1,
            "raw_observations": 1,
            "canonical_nodes": 0,
            "canonical_edges": 0,
            "canonical_evidence": 0,
            "canonical_node_evidence": 0,
            "canonical_edge_evidence": 0,
        },
        "0" * 64,
        1,
        1,
    )


def _supervisor(
    *,
    channel=None,
    process=None,
    resources=None,
    backend=None,
    terminal_reader=_readback,
    cleanup_verifier=lambda state: state.cleanup_state,
    terminal_backend_reader=lambda: {"observer": 1},
    clock=None,
    startup=None,
):
    channel = channel or _Channel((_phase("started", 1), _phase("completed", 2)))
    process = process or _Process(channel)
    resources = resources or _Resources()
    return ActualRefreshSupervisor(
        process,
        channel,
        resources,
        backend or _Backend(),
        terminal_reader=terminal_reader,
        cleanup_verifier=cleanup_verifier,
        terminal_backend_reader=terminal_backend_reader,
        limits=ProtectedLaunchLimits(30, 30, 30, 30),
        storage_baseline=_baseline(),
        clock_ns=clock or _Clock(),
        poll_interval_seconds=0.01,
        signal_grace_seconds=1,
        waiter=lambda _seconds: None,
        startup=startup,
    ), process, resources


def test_receipt_failure_still_reconciles_every_available_terminal_authority() -> None:
    def fail_receipt():
        raise RuntimeError("private receipt detail")

    supervisor, process, resources = _supervisor(terminal_reader=fail_receipt)

    result = supervisor.run()

    assert result.primary_control_failure is ControlFailureCode.RECEIPT_READBACK_FAILED
    assert ControlFailureCode.STAGE_RECONCILIATION_UNPROVED in result.secondary_failures
    assert result.backend_quiescent is True
    assert result.terminal_resource_available is True
    assert resources.terminal_count == 1
    assert process.signals == []


def test_cleanup_refusal_is_a_closed_terminal_failure() -> None:
    def refuse_cleanup(_state):
        raise RuntimeError("private cleanup detail")

    supervisor, _, _ = _supervisor(cleanup_verifier=refuse_cleanup)

    result = supervisor.run()

    assert result.primary_control_failure is (
        ControlFailureCode.CLEANUP_ELIGIBILITY_UNPROVED
    )
    assert result.reconciliation_status is ReconciliationStatus.UNRECONCILED


def test_failed_live_backend_is_replaced_by_fresh_terminal_authority() -> None:
    supervisor, _, _ = _supervisor(backend=_Backend(quiescence_failure=True))

    result = supervisor.run()

    assert result.primary_control_failure is (
        ControlFailureCode.BACKEND_QUIESCENCE_TIMEOUT
    )
    assert result.backend_quiescent is True
    assert result.terminal_category is (
        TerminalCategory.CONTROL_FAILURE_CANCELLED_RECONCILED
    )


def test_terminal_backend_failure_remains_unreconciled() -> None:
    def fail_terminal_backend():
        raise RuntimeError("private observer detail")

    supervisor, _, _ = _supervisor(
        terminal_backend_reader=fail_terminal_backend
    )

    result = supervisor.run()

    assert result.primary_control_failure is (
        ControlFailureCode.BACKEND_QUIESCENCE_TIMEOUT
    )
    assert result.backend_quiescent is False
    assert result.reconciliation_status is ReconciliationStatus.UNRECONCILED
