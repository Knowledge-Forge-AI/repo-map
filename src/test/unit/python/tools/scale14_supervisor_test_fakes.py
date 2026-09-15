from __future__ import annotations
from types import SimpleNamespace
from actual_refresh_startup import ActualRefreshStartup
from repomap_kg.storage.authority import AttemptNumber, JobId, PublicationGenerations
from repomap_kg.storage.publication import RunPublicationAttempt
from repomap_kg.storage.staging_launch_authority import DirectLaunchAuthorityEvent
from repomap_kg.storage.staging_operation_contracts import operation_descriptor
from repomap_kg.storage.staging_operation_events import (
    StagingOperationEvent,
    StagingOperationEventCategory,
)
from scale15_terminal_contracts import (
    ExpectedRefreshAuthority,
)


def _phase(category: str, offset: int, code: str = "refresh.source_discovery"):
    terminal = category if category != "started" else None
    return {
        "schema_version": 1,
        "attempt_local_sequence": 1,
        "phase_code": code,
        "event_category": category,
        "monotonic_offset_ns": offset,
        "duration_ns_or_null": None if terminal is None else 10,
        "terminal_category_or_null": terminal,
        "process_cpu_duration_ns_or_null": None,
    }


def _operation(category: StagingOperationEventCategory, offset: int):
    descriptor = operation_descriptor("merge.files")
    if category is StagingOperationEventCategory.STARTED:
        event = StagingOperationEvent.started(descriptor, 1, offset)
    else:
        event = StagingOperationEvent.terminal(descriptor, 1, category, offset, 4)
    return event.to_payload()


def _authority(offset: int = 11):
    return DirectLaunchAuthorityEvent.from_attempt(
        RunPublicationAttempt(JobId("direct-scale16"), AttemptNumber(1)),
        offset,
    ).to_payload()


def _expectation():
    return ExpectedRefreshAuthority(
        "repo1:public-fixture",
        "public-fixture",
        PublicationGenerations(
            "sg1:source", "cg1:config", "eg1:extractor", "kg1:canonicalizer"
        ),
        "direct",
        True,
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
    ).validate()


class _Channel:
    def __init__(self, frames):
        self.frames = list(frames)
        self.closed = False

    def receive(self, *, timeout_seconds, validator=None, readiness=None):
        if readiness is not None:
            readiness()
        if self.frames:
            frame = self.frames.pop(0)
            if validator is not None:
                validator(frame)
            return frame
        raise EOFError

    def close(self):
        self.closed = True


class _Process:
    def __init__(self, channel, exit_code=0):
        self.channel = channel
        self.exit_code = exit_code
        self.signals = []

    def poll(self):
        return self.exit_code if not self.channel.frames else None

    def send_signal(self, value):
        self.signals.append(value)


class _LiveUntilSignalProcess(_Process):
    def poll(self):
        return 1 if self.signals else None


class _TimeoutChannel(_Channel):
    def receive(self, *, timeout_seconds, validator=None, readiness=None):
        if readiness is not None:
            readiness()
        if self.frames:
            frame = self.frames.pop(0)
            if validator is not None:
                validator(frame)
            return frame
        raise TimeoutError


class _Resources:
    def __init__(self, order=None):
        self.baselined = False
        self.terminal_forces = []
        self.order = order
        self.closed = False

    def capture_baseline(self):
        self.baselined = True
        return SimpleNamespace(
            metric_code="postgresql_pgdata_allocated_delta",
            scope="owned_postgresql_pgdata",
            baseline_bytes=1,
            current_bytes=1,
            delta_bytes=0,
            free_bytes=100 * 1024**3,
            availability="available",
            sampling_elapsed_ns=1,
        )

    def capture(self, *, force=False):
        self.terminal_forces.append(force)
        return SimpleNamespace(
            values={
                "client_peak_rss_bytes": 1,
                "owned_postgresql_process_group_rss_bytes": 1,
                "postgresql_container_rss_upper_bound": None,
                "temporary_byte_upper_bound_delta": 0,
                "wal_upper_bound_delta": 0,
                "concurrent_profiles": 1,
                "postgresql_pgdata_allocated_delta": 0,
                "postgresql_pgdata_backing_free_bytes": 100 * 1024**3,
                "postgresql_pgdata_reader_elapsed_ns": 1,
            },
            availability={
                "client_peak_rss_bytes": "available",
                "owned_postgresql_process_group_rss_bytes": "available",
                "postgresql_container_rss_upper_bound": "unavailable",
                "temporary_byte_upper_bound_delta": "available",
                "wal_upper_bound_delta": "available",
                "concurrent_profiles": "available",
                "postgresql_pgdata_allocated_delta": "available",
                "postgresql_pgdata_backing_free_bytes": "available",
                "postgresql_pgdata_reader_elapsed_ns": "available",
            },
        )

    def close(self):
        self.closed = True
        if self.order is not None:
            self.order.append("resource-close")

    def accept_preparation_baseline(self, baseline):
        assert baseline.backing_free_bytes == 100 * 1024**3
        if self.order is not None:
            self.order.append("preparation-baseline-accepted")


class _Backend:
    def __init__(self, order):
        self.order = order

    def start(self):
        self.order.append("backend-start")

    def startup_summary(self, *, timeout_seconds=None):
        event = (
            "backend-startup-summary"
            if timeout_seconds is None
            else f"backend-startup-summary:{timeout_seconds}"
        )
        self.order.append(event)
        return {"observer": 1, "postgres_internal": 1}

    def release_when_ready(
        self,
        release,
        summary_validator,
        *,
        stable_sample=None,
        stable_samples=None,
        before_release=None,
        timeout_seconds=None,
        initial_stable_sample_ns=None,
    ):
        assert timeout_seconds is None or 0 < timeout_seconds <= 0.6
        summary_validator({"observer": 1, "postgres_internal": 1})
        if stable_sample is not None:
            stable_sample()
            stable_sample()
        if stable_samples is not None:
            first = (
                1_000_000_000
                if initial_stable_sample_ns is None
                else initial_stable_sample_ns
            )
            stable_samples(first, max(first + 1_000_000, 1_001_000_000))
        if before_release is not None:
            before_release()
        release()

    def summary(self):
        return {"observer": 1, "postgres_internal": 1}

    def pre_release_summary(self, *, timeout_seconds=0.6):
        assert 0 < timeout_seconds <= 0.6
        return {"observer": 1, "postgres_internal": 1}

    def wait_quiescent(self, timeout_seconds):
        self.order.append("backend-quiescent")
        return {"observer": 1, "postgres_internal": 1}

    def close(self):
        self.order.append("backend-close")

    def close_with_timeout(self, timeout_seconds):
        assert timeout_seconds > 0
        self.close()


class _Startup(ActualRefreshStartup):
    def __init__(self, order):
        self.order = order
        self._released = False

    @property
    def released(self) -> bool:
        return self._released

    def mark_storage_baseline_ready(self):
        self.order.append("storage-baseline-ready")

    def mark_backend_observer_ready(self):
        self.order.append("backend-observer-ready")

    def mark_resource_authorities_ready(self):
        self.order.append("resource-authorities-ready")

    def mark_event_receiver_ready(self):
        self.order.append("event-receiver-ready")

    def mark_failure_collector_ready(self):
        self.order.append("failure-collector-ready")

    def release(self):
        self._released = True
        self.order.append("child-released")

    def mark_monitoring(self):
        self.order.append("monitoring")

    def fail(self):
        self.order.append("startup-failed")

    def close(self):
        self.order.append("startup-closed")


class _PreparationAuthority:
    def __init__(self, order, sample):
        self.order = order
        self.sample = sample
        self.sample.baseline = SimpleNamespace(
            allocated_delta_bytes=0,
            backing_free_bytes=100 * 1024**3,
            pgdata_reader_elapsed_ns=1,
        )

    @property
    def startup_handoff_timeout_seconds(self):
        return 3.4

    @property
    def final_release_remaining_seconds(self):
        return 0.6

    def prepare(self):
        self.order.append("preparation")
        return self.sample

    def open_final_readiness(self):
        self.order.append("final-readiness")

    def mark_transient_ownership_clear(self):
        self.order.append("transient-clear")

    def mark_stable_sample(self):
        self.order.append("stable-sample")

    def mark_stable_samples(self, first_parent_ns, second_parent_ns):
        assert first_parent_ns <= second_parent_ns
        self.order.extend(("stable-sample", "stable-sample"))

    def mark_ready_to_release(self):
        self.order.append("ready-to-release")

    def mark_child_released(self):
        self.order.append("preparation-child-released")

    def refuse(self):
        self.order.append("preparation-refused")

    def settle(self):
        self.order.append("preparation-settled")
