"""Bounded resource policy for the synthetic coordinator pilot."""

from __future__ import annotations

from dataclasses import dataclass, fields


def _is_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def valid_counter(value: object, limits: CoordinatorLimits) -> bool:
    """Return whether a public counter is an in-range non-boolean integer."""

    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 <= value <= limits.max_counter
    )


@dataclass(frozen=True)
class CoordinatorLimits:
    """Validated coordinator limits selected at process startup."""

    max_nonterminal_jobs: int = 256
    max_queued_manual_jobs_per_graph: int = 8
    manual_claim_burst: int = 3
    max_running_workers: int = 4
    max_running_mutating_workers: int = 2
    max_running_read_operations: int = 4
    max_client_connections: int = 32
    max_in_flight_requests: int = 64
    watcher_hint_buffer_size: int = 256
    progress_counter_delta: int = 10
    progress_min_interval_seconds: int = 1
    heartbeat_seconds: int = 10
    claim_deadline_seconds: int = 30
    graph_lease_duration_seconds: int = 60
    lease_renewal_interval_seconds: int = 10
    cancel_deadline_seconds: int = 10
    process_deadline_seconds: int = 60
    max_retry_attempts: int = 3
    max_retry_backoff_seconds: int = 300
    terminal_retention_seconds: int = 7 * 24 * 60 * 60
    cleanup_batch_size: int = 64
    max_protocol_line_bytes: int = 1024 * 1024
    max_diagnostic_bytes: int = 16 * 1024
    max_array_items: int = 32
    max_identifier_chars: int = 128
    max_summary_chars: int = 512
    max_counter: int = 2**31 - 1

    def validate(self, *, hard_maxima: CoordinatorLimits) -> None:
        """Reject invalid values and unsafe relationships before startup."""

        for field in fields(self):
            value = getattr(self, field.name)
            maximum = getattr(hard_maxima, field.name)
            if not _is_positive_int(value):
                raise ValueError(f"{field.name} must be a positive integer")
            if not _is_positive_int(maximum) or value > maximum:
                raise ValueError(f"{field.name} exceeds its hard maximum")

        relationships = (
            (
                self.max_running_mutating_workers <= self.max_running_workers,
                "mutating workers cannot exceed all running workers",
            ),
            (
                self.max_running_read_operations <= self.max_running_workers,
                "read operations cannot exceed all running workers",
            ),
            (
                self.max_in_flight_requests >= self.max_client_connections,
                "in-flight requests cannot be below client connections",
            ),
            (
                self.max_diagnostic_bytes <= self.max_protocol_line_bytes,
                "diagnostics cannot exceed a protocol line",
            ),
            (
                self.max_retry_backoff_seconds >= self.heartbeat_seconds,
                "maximum retry backoff cannot be below the heartbeat interval",
            ),
            (
                self.cleanup_batch_size <= self.max_nonterminal_jobs,
                "cleanup batch cannot exceed the bounded working set",
            ),
            (
                self.claim_deadline_seconds >= self.heartbeat_seconds,
                "claim deadline cannot be below the heartbeat interval",
            ),
            (
                self.lease_renewal_interval_seconds < self.graph_lease_duration_seconds,
                "lease renewal interval must be below the lease duration",
            ),
            (
                self.process_deadline_seconds >= self.cancel_deadline_seconds,
                "process deadline cannot be below the cancel deadline",
            ),
        )
        for valid, message in relationships:
            if not valid:
                raise ValueError(message)


HARD_MAX_LIMITS = CoordinatorLimits(
    max_nonterminal_jobs=4096,
    max_queued_manual_jobs_per_graph=64,
    manual_claim_burst=32,
    max_running_workers=32,
    max_running_mutating_workers=16,
    max_running_read_operations=32,
    max_client_connections=256,
    max_in_flight_requests=1024,
    watcher_hint_buffer_size=4096,
    progress_counter_delta=10_000,
    progress_min_interval_seconds=60,
    heartbeat_seconds=60,
    claim_deadline_seconds=300,
    graph_lease_duration_seconds=600,
    lease_renewal_interval_seconds=60,
    cancel_deadline_seconds=120,
    process_deadline_seconds=600,
    max_retry_attempts=10,
    max_retry_backoff_seconds=3600,
    terminal_retention_seconds=90 * 24 * 60 * 60,
    cleanup_batch_size=4096,
    max_protocol_line_bytes=1024 * 1024,
    max_diagnostic_bytes=64 * 1024,
    max_array_items=256,
    max_identifier_chars=256,
    max_summary_chars=4096,
    max_counter=2**63 - 1,
)

DEFAULT_LIMITS = CoordinatorLimits()
HARD_MAX_LIMITS.validate(hard_maxima=HARD_MAX_LIMITS)
DEFAULT_LIMITS.validate(hard_maxima=HARD_MAX_LIMITS)

# Foreground startup may have to wait for an abruptly terminated singleton's
# full lease, then acquire ownership and complete bounded startup recovery.
DEFAULT_COORDINATOR_STARTUP_WAIT_SECONDS = (
    DEFAULT_LIMITS.graph_lease_duration_seconds + 15
)
