"""Executable public-safe trace authority for SCALE28-FIX11."""

from __future__ import annotations

from typing import Mapping


from repomap_test_support.scale28_fix11_trace_values import (
    TraceContractError as TraceContractError,
    ClockDomain as ClockDomain,
    TraceVariant as TraceVariant,
    TerminalCategory as TerminalCategory,
    CleanupState as CleanupState,
    TraceEvent as TraceEvent,
    VariantContract as VariantContract,
)


PARENT_SUCCESS_EVENTS = (
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
)

PARENT_TERMINAL_EVENTS = (
    "parent_preparation_timeout",
    "observation_transport_failed",
    "acknowledgement_failed",
    "receipt_failed",
    "process_settlement_failed",
    "attempt_cleanup_limited",
)

PARENT_EVENTS = PARENT_SUCCESS_EVENTS + PARENT_TERMINAL_EVENTS

WORKER_SUCCESS_EVENTS = (
    "worker_entry",
    "worker_import_initialization_complete",
    "request_received",
    "request_decoded",
    "request_validated",
    "pgdata_walk_started",
    "pgdata_walk_completed",
    "filesystem_observation_started",
    "filesystem_observation_completed",
    "postgres_resource_read_started:temporary_bytes",
    "postgres_resource_read_completed:temporary_bytes",
    "postgres_resource_read_started:wal_bytes",
    "postgres_resource_read_completed:wal_bytes",
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

WORKER_TERMINAL_EVENTS = ("worker_source_failure",)
WORKER_EVENTS = WORKER_SUCCESS_EVENTS + WORKER_TERMINAL_EVENTS
CLOSED_EVENTS = frozenset(PARENT_EVENTS + WORKER_EVENTS)
TERMINAL_EVENTS = frozenset(PARENT_TERMINAL_EVENTS + WORKER_TERMINAL_EVENTS)
POST_FAILURE_PARENT_EVENTS = frozenset(
    {
        "child_exit_observed",
        "process_tree_settled",
        "attempt_cleanup_started",
        "attempt_cleanup_completed",
        "attempt_cleanup_limited",
    }
)
SUCCESSFUL_ATTEMPT_EVENTS = frozenset(
    PARENT_SUCCESS_EVENTS + WORKER_SUCCESS_EVENTS
)


_ATTEMPT_PREFIX = frozenset(
    {
        "attempt_authority_created",
        "attempt_deadline_started",
        "process_spawn_requested",
    }
)
_COMPLETED_CLEANUP = frozenset(
    {"attempt_cleanup_started", "attempt_cleanup_completed"}
)
_LIMITED_CLEANUP = frozenset(
    {"attempt_cleanup_started", "attempt_cleanup_limited"}
)


def _single_failure_contract(
    terminal_event: str,
    category: TerminalCategory,
) -> VariantContract:
    return VariantContract(
        required_by_attempt={
            1: _ATTEMPT_PREFIX | _COMPLETED_CLEANUP | {terminal_event}
        },
        prohibited_events=TERMINAL_EVENTS - {terminal_event},
        ordering_edges=(
            ("attempt_authority_created", "attempt_deadline_started"),
            ("attempt_deadline_started", "process_spawn_requested"),
            ("attempt_cleanup_started", "attempt_cleanup_completed"),
        ),
        allowed_categories_by_attempt={1: frozenset({category})},
        cleanup_by_attempt={1: CleanupState.COMPLETED},
        attempt_two_permitted=False,
    )


_SUCCESS_CONTRACT = VariantContract(
    required_by_attempt={1: SUCCESSFUL_ATTEMPT_EVENTS},
    prohibited_events=TERMINAL_EVENTS,
    ordering_edges=tuple(zip(PARENT_SUCCESS_EVENTS, PARENT_SUCCESS_EVENTS[1:]))
    + tuple(zip(WORKER_SUCCESS_EVENTS, WORKER_SUCCESS_EVENTS[1:])),
    allowed_categories_by_attempt={1: frozenset({TerminalCategory.SUCCESS})},
    cleanup_by_attempt={1: CleanupState.COMPLETED},
    attempt_two_permitted=False,
)

_TIMEOUT_REQUIRED = (
    _ATTEMPT_PREFIX
    | _COMPLETED_CLEANUP
    | {"parent_preparation_timeout"}
)

VARIANT_CONTRACTS = {
    TraceVariant.SUCCESSFUL_ATTEMPT: _SUCCESS_CONTRACT,
    TraceVariant.SOURCE_RESOURCE_FAILURE: _single_failure_contract(
        "worker_source_failure",
        TerminalCategory.RESOURCE_READER_UNAVAILABLE,
    ),
    TraceVariant.PREPARATION_TIMEOUT: _single_failure_contract(
        "parent_preparation_timeout",
        TerminalCategory.PREPARATION_TIMEOUT,
    ),
    TraceVariant.OBSERVATION_TRANSPORT_FAILURE: _single_failure_contract(
        "observation_transport_failed",
        TerminalCategory.OBSERVATION_FAILURE,
    ),
    TraceVariant.ACKNOWLEDGEMENT_FAILURE: _single_failure_contract(
        "acknowledgement_failed",
        TerminalCategory.ACKNOWLEDGEMENT_FAILURE,
    ),
    TraceVariant.RECEIPT_FAILURE: _single_failure_contract(
        "receipt_failed",
        TerminalCategory.RECEIPT_FAILURE,
    ),
    TraceVariant.PROCESS_SETTLEMENT_FAILURE: _single_failure_contract(
        "process_settlement_failed",
        TerminalCategory.PROCESS_SETTLEMENT_FAILURE,
    ),
    TraceVariant.CLEANUP_LIMITATION: VariantContract(
        required_by_attempt={
            1: _ATTEMPT_PREFIX
            | _LIMITED_CLEANUP
            | {"attempt_cleanup_limited"}
        },
        prohibited_events=(
            TERMINAL_EVENTS - {"attempt_cleanup_limited"}
        )
        | {"attempt_cleanup_completed"},
        ordering_edges=(
            ("attempt_authority_created", "attempt_deadline_started"),
            ("attempt_deadline_started", "process_spawn_requested"),
            ("attempt_cleanup_started", "attempt_cleanup_limited"),
        ),
        allowed_categories_by_attempt={
            1: frozenset({TerminalCategory.CLEANUP_LIMITATION})
        },
        cleanup_by_attempt={1: CleanupState.LIMITED},
        attempt_two_permitted=False,
    ),
    TraceVariant.TWO_ATTEMPT_SUCCESS: VariantContract(
        required_by_attempt={
            1: _TIMEOUT_REQUIRED,
            2: SUCCESSFUL_ATTEMPT_EVENTS,
        },
        prohibited_events=TERMINAL_EVENTS
        - {"parent_preparation_timeout"},
        ordering_edges=(),
        allowed_categories_by_attempt={
            1: frozenset({TerminalCategory.PREPARATION_TIMEOUT}),
            2: frozenset({TerminalCategory.SUCCESS}),
        },
        cleanup_by_attempt={
            1: CleanupState.COMPLETED,
            2: CleanupState.COMPLETED,
        },
        attempt_two_permitted=True,
    ),
    TraceVariant.TWO_ATTEMPT_TERMINAL_FAILURE: VariantContract(
        required_by_attempt={1: _TIMEOUT_REQUIRED, 2: _TIMEOUT_REQUIRED},
        prohibited_events=TERMINAL_EVENTS
        - {"parent_preparation_timeout"},
        ordering_edges=(),
        allowed_categories_by_attempt={
            1: frozenset({TerminalCategory.PREPARATION_TIMEOUT}),
            2: frozenset({TerminalCategory.PREPARATION_TIMEOUT}),
        },
        cleanup_by_attempt={
            1: CleanupState.COMPLETED,
            2: CleanupState.COMPLETED,
        },
        attempt_two_permitted=True,
    ),
}


def _expected_clock(event: str) -> ClockDomain:
    if event in PARENT_EVENTS:
        return ClockDomain.PARENT_MONOTONIC
    if event in WORKER_EVENTS:
        return ClockDomain.WORKER_LOCAL_DURATION
    raise TraceContractError("unknown preparation trace event")


def _event_sequence(
    events: tuple[TraceEvent, ...],
    attempt: int,
    event_name: str,
) -> int:
    try:
        return next(
            event.sequence
            for event in events
            if event.attempt == attempt and event.event == event_name
        )
    except StopIteration as exc:
        raise TraceContractError("required event is missing") from exc


def validate_trace_variant(
    events: tuple[TraceEvent, ...],
    variant: TraceVariant,
    *,
    terminal_categories: Mapping[int, TerminalCategory],
    cleanup_states: Mapping[int, CleanupState],
) -> None:
    """Validate one enacted trace against one closed FIX11 variant."""

    if not events:
        raise TraceContractError("preparation trace is empty")
    contract = VARIANT_CONTRACTS[variant]
    seen: set[tuple[int, str]] = set()
    last_parent_sequence = -1
    last_worker_sequence: dict[int, int] = {}
    by_attempt: dict[int, set[str]] = {}
    for event in events:
        if event.attempt not in (1, 2) or event.sequence < 0:
            raise TraceContractError("invalid preparation trace position")
        if event.event not in CLOSED_EVENTS:
            raise TraceContractError("unknown preparation trace event")
        if event.clock_domain is not _expected_clock(event.event):
            raise TraceContractError("preparation trace clock-domain mismatch")
        identity = (event.attempt, event.event)
        if identity in seen:
            raise TraceContractError("duplicate preparation trace event")
        seen.add(identity)
        by_attempt.setdefault(event.attempt, set()).add(event.event)
        if event.clock_domain is ClockDomain.PARENT_MONOTONIC:
            if event.sequence <= last_parent_sequence:
                raise TraceContractError("non-monotonic global parent sequence")
            last_parent_sequence = event.sequence
        else:
            previous = last_worker_sequence.get(event.attempt, -1)
            if event.sequence <= previous:
                raise TraceContractError(
                    "non-monotonic worker-local sequence"
                )
            last_worker_sequence[event.attempt] = event.sequence

    if 2 in by_attempt and not contract.attempt_two_permitted:
        if "attempt_cleanup_limited" in by_attempt.get(1, set()):
            raise TraceContractError(
                "attempt two prohibited after cleanup limitation"
            )
        raise TraceContractError("attempt two is prohibited for trace variant")
    if "attempt_cleanup_limited" in by_attempt.get(1, set()) and 2 in by_attempt:
        raise TraceContractError("attempt two prohibited after cleanup limitation")
    if 2 in by_attempt:
        cleanup = _event_sequence(
            events,
            1,
            "attempt_cleanup_completed",
        )
        next_authority = _event_sequence(
            events,
            2,
            "attempt_authority_created",
        )
        if next_authority <= cleanup:
            raise TraceContractError(
                "attempt two begins before attempt-one cleanup"
            )

    for attempt, event_names in by_attempt.items():
        source_names = (
            event_names
            & TERMINAL_EVENTS
            - {"attempt_cleanup_limited"}
        )
        for source_name in source_names:
            source_sequence = _event_sequence(
                events,
                attempt,
                source_name,
            )
            source_clock = _expected_clock(source_name)
            for event in events:
                if (
                    event.attempt != attempt
                    or event.clock_domain is not source_clock
                    or event.sequence <= source_sequence
                ):
                    continue
                if (
                    source_clock is ClockDomain.PARENT_MONOTONIC
                    and event.event in POST_FAILURE_PARENT_EVENTS
                ):
                    continue
                raise TraceContractError(
                    "work event occurs after source failure"
                )

    for attempt, required in contract.required_by_attempt.items():
        missing = required - by_attempt.get(attempt, set())
        if missing:
            raise TraceContractError("required event is missing")
    if any(
        event.event in contract.prohibited_events
        for event in events
    ):
        raise TraceContractError("prohibited event is present")
    for attempt, allowed in contract.allowed_categories_by_attempt.items():
        if terminal_categories.get(attempt) not in allowed:
            raise TraceContractError("terminal category is not allowed")
    if dict(cleanup_states) != dict(contract.cleanup_by_attempt):
        raise TraceContractError("cleanup terminal state does not match")

    for attempt in contract.required_by_attempt:
        for earlier, later in contract.ordering_edges:
            if (
                earlier in by_attempt.get(attempt, set())
                and later in by_attempt.get(attempt, set())
                and _event_sequence(events, attempt, earlier)
                >= _event_sequence(events, attempt, later)
            ):
                raise TraceContractError("required ordering edge is violated")
