"""Public-safe preparation critical-path trace contract for SCALE28-FIX10."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class TraceContractError(ValueError):
    """One closed-schema trace-contract violation."""


class ClockDomain(StrEnum):
    """Clocks that may be ordered only inside their owning process."""

    PARENT_MONOTONIC = "parent_monotonic"
    WORKER_LOCAL_DURATION = "worker_local_duration"


class EvidenceKind(StrEnum):
    """Observed evidence is distinct from an expected result."""

    OBSERVED = "observed"
    EXPECTED = "expected"


class TraceCondition(StrEnum):
    """Frozen controlled comparison conditions."""

    QUIET = "quiet"
    CPU_CONTENTION = "bounded_cpu_contention"
    FILESYSTEM_CONTENTION = "bounded_filesystem_contention"
    CONNECTION_CHURN = "bounded_connection_churn"
    GATE_PRELUDE = "complete_gate_prelude"
    SECOND_ATTEMPT = "immediate_second_attempt_reacquisition"


PARENT_EVENTS = (
    "attempt_authority_created",
    "attempt_deadline_started",
    "process_spawn_requested",
    "process_started_parent_observed",
    "parent_frame_received",
    "parent_frame_validated",
    "ack_write_started",
    "ack_write_completed",
    "parent_receipt_received",
    "child_exit_observed",
    "process_tree_settled",
    "attempt_cleanup_started",
    "attempt_cleanup_completed",
    "next_attempt_authority_created",
)

WORKER_EVENTS = (
    "worker_entry",
    "worker_import_initialization_complete",
    "request_received",
    "request_decoded",
    "request_validated",
    "pgdata_walk_started",
    "pgdata_walk_completed",
    "filesystem_observation_started",
    "filesystem_observation_completed",
    "resource_baseline_assembled",
    "canonical_encoding_started",
    "canonical_encoding_completed",
    "digest_completed",
    "observation_frame_write_started",
    "observation_frame_write_completed",
    "child_ack_received",
    "receipt_created",
    "receipt_write_started",
    "receipt_write_completed",
)

POSTGRES_RESOURCE_CODES = ("temporary_bytes", "wal_bytes")
POSTGRES_EVENTS = tuple(
    f"postgres_resource_read_{edge}:{resource}"
    for resource in POSTGRES_RESOURCE_CODES
    for edge in ("started", "completed")
)
CLOSED_EVENTS = frozenset(PARENT_EVENTS + WORKER_EVENTS + POSTGRES_EVENTS)

PUBLIC_AGGREGATE_FIELDS = frozenset(
    {
        "attempt_wall_ms",
        "spawn_import_ms",
        "worker_preparation_ms",
        "worker_cpu_ms",
        "parent_wait_ms",
        "pgdata_walk_ms",
        "filesystem_observation_ms",
        "postgres_resource_reads_ms",
        "baseline_assembly_ms",
        "encoding_digest_ms",
        "observation_transfer_ms",
        "parent_validation_ms",
        "acknowledgement_ms",
        "receipt_ms",
        "process_settlement_ms",
        "cleanup_ms",
        "minimum_ms",
        "median_ms",
        "p95_ms",
        "maximum_ms",
        "threshold_crossings",
    }
)


@dataclass(frozen=True, slots=True)
class TraceEvent:
    """One privacy-safe event ordered only in its owning clock domain."""

    event: str
    attempt: int
    sequence: int
    clock_domain: ClockDomain
    evidence_kind: EvidenceKind = EvidenceKind.OBSERVED


def expected_clock_domain(event: str) -> ClockDomain:
    """Return the only clock domain allowed for a closed event."""

    if event in PARENT_EVENTS:
        return ClockDomain.PARENT_MONOTONIC
    if event in WORKER_EVENTS or event in POSTGRES_EVENTS:
        return ClockDomain.WORKER_LOCAL_DURATION
    raise TraceContractError("unknown preparation trace event")


def validate_aggregate_fields(field_names: tuple[str, ...]) -> None:
    """Reject private or free-form aggregate fields."""

    if not field_names or any(
        field not in PUBLIC_AGGREGATE_FIELDS for field in field_names
    ):
        raise TraceContractError("private or unknown aggregate field")


def validate_trace(events: tuple[TraceEvent, ...]) -> None:
    """Validate closed vocabulary, clock ownership, and attempt settlement."""

    if not events:
        raise TraceContractError("preparation trace is empty")
    seen: set[tuple[int, str]] = set()
    last_sequence: dict[tuple[int, ClockDomain], int] = {}
    for event in events:
        if event.attempt not in (1, 2) or event.sequence < 0:
            raise TraceContractError("invalid preparation trace position")
        if event.evidence_kind is not EvidenceKind.OBSERVED:
            raise TraceContractError("expected result presented as observed")
        if event.event not in CLOSED_EVENTS:
            raise TraceContractError("unknown preparation trace event")
        if event.clock_domain is not expected_clock_domain(event.event):
            raise TraceContractError("preparation trace clock-domain mismatch")
        identity = (event.attempt, event.event)
        if identity in seen:
            raise TraceContractError("duplicate preparation trace event")
        seen.add(identity)
        order_key = (event.attempt, event.clock_domain)
        previous = last_sequence.get(order_key, -1)
        if event.sequence <= previous:
            raise TraceContractError("non-monotonic local trace sequence")
        last_sequence[order_key] = event.sequence

    for attempt in {event.attempt for event in events}:
        if (attempt, "attempt_cleanup_completed") not in seen:
            raise TraceContractError("preparation attempt cleanup is missing")
    attempts = {event.attempt for event in events}
    if 2 in attempts:
        cleanup = next(
            event.sequence
            for event in events
            if event.attempt == 1
            and event.event == "attempt_cleanup_completed"
        )
        next_authority = next(
            (
                event.sequence
                for event in events
                if event.attempt == 2
                and event.event == "attempt_authority_created"
            ),
            None,
        )
        if next_authority is None or next_authority <= cleanup:
            raise TraceContractError(
                "attempt two begins before attempt-one cleanup"
            )


def compare_durations(
    left_domain: ClockDomain,
    right_domain: ClockDomain,
) -> None:
    """Reject absolute comparison across parent and worker clocks."""

    if left_domain is not right_domain:
        raise TraceContractError("absolute cross-process clock comparison")
