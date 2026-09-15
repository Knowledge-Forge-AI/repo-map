from __future__ import annotations

from dataclasses import replace

import pytest

from repomap_test_support.scale28_fix11_preparation_trace import (
    CLOSED_EVENTS,
    PARENT_EVENTS,
    SUCCESSFUL_ATTEMPT_EVENTS,
    VARIANT_CONTRACTS,
    WORKER_EVENTS,
    CleanupState,
    ClockDomain,
    TerminalCategory,
    TraceContractError,
    TraceEvent,
    TraceVariant,
    validate_trace_variant,
)


_EXPECTED_TERMINALS = {
    "worker_source_failure",
    "parent_preparation_timeout",
    "observation_transport_failed",
    "acknowledgement_failed",
    "receipt_failed",
    "process_settlement_failed",
    "attempt_cleanup_limited",
}


def _parent(event: str, attempt: int, sequence: int) -> TraceEvent:
    return TraceEvent(event, attempt, sequence, ClockDomain.PARENT_MONOTONIC)


def _worker(event: str, attempt: int, sequence: int) -> TraceEvent:
    return TraceEvent(
        event,
        attempt,
        sequence,
        ClockDomain.WORKER_LOCAL_DURATION,
    )


def _successful_attempt(
    attempt: int = 1,
    *,
    parent_start: int = 0,
) -> tuple[TraceEvent, ...]:
    parent_events = (
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
    worker_events = (
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
    return tuple(
        _parent(event, attempt, parent_start + sequence)
        for sequence, event in enumerate(parent_events)
    ) + tuple(
        _worker(event, attempt, sequence)
        for sequence, event in enumerate(worker_events)
    )


def test_fix11_contract_supersedes_ambiguous_attempt_event() -> None:
    assert "next_attempt_authority_created" not in CLOSED_EVENTS
    assert PARENT_EVENTS.count("attempt_authority_created") == 1
    assert _EXPECTED_TERMINALS <= CLOSED_EVENTS
    assert len(VARIANT_CONTRACTS) == 10
    assert set(VARIANT_CONTRACTS) == set(TraceVariant)


def test_fix11_success_requires_complete_enacted_path() -> None:
    trace = _successful_attempt()
    assert {event.event for event in trace} == SUCCESSFUL_ATTEMPT_EVENTS

    validate_trace_variant(
        trace,
        TraceVariant.SUCCESSFUL_ATTEMPT,
        terminal_categories={1: TerminalCategory.SUCCESS},
        cleanup_states={1: CleanupState.COMPLETED},
    )


def test_fix11_parent_sequence_is_global_and_worker_sequence_may_reset() -> None:
    first = (
        _parent("attempt_authority_created", 1, 0),
        _parent("attempt_deadline_started", 1, 1),
        _parent("process_spawn_requested", 1, 2),
        _parent("process_started_parent_observed", 1, 3),
        _worker("worker_entry", 1, 0),
        _worker("worker_import_initialization_complete", 1, 1),
        _parent("parent_preparation_timeout", 1, 4),
        _parent("attempt_cleanup_started", 1, 5),
        _parent("attempt_cleanup_completed", 1, 6),
    )
    second = _successful_attempt(2, parent_start=7)
    validate_trace_variant(
        first + second,
        TraceVariant.TWO_ATTEMPT_SUCCESS,
        terminal_categories={
            1: TerminalCategory.PREPARATION_TIMEOUT,
            2: TerminalCategory.SUCCESS,
        },
        cleanup_states={
            1: CleanupState.COMPLETED,
            2: CleanupState.COMPLETED,
        },
    )

    reset_parent = tuple(
        replace(event, sequence=event.sequence - 7)
        if event.attempt == 2 and event.clock_domain is ClockDomain.PARENT_MONOTONIC
        else event
        for event in first + second
    )
    with pytest.raises(TraceContractError, match="global parent"):
        validate_trace_variant(
            reset_parent,
            TraceVariant.TWO_ATTEMPT_SUCCESS,
            terminal_categories={
                1: TerminalCategory.PREPARATION_TIMEOUT,
                2: TerminalCategory.SUCCESS,
            },
            cleanup_states={
                1: CleanupState.COMPLETED,
                2: CleanupState.COMPLETED,
            },
        )


def test_fix11_cleanup_limitation_prohibits_attempt_two() -> None:
    limited = (
        _parent("attempt_authority_created", 1, 0),
        _parent("attempt_deadline_started", 1, 1),
        _parent("process_spawn_requested", 1, 2),
        _parent("attempt_cleanup_started", 1, 3),
        _parent("attempt_cleanup_limited", 1, 4),
        _parent("attempt_authority_created", 2, 5),
    )
    with pytest.raises(TraceContractError, match="cleanup limitation"):
        validate_trace_variant(
            limited,
            TraceVariant.CLEANUP_LIMITATION,
            terminal_categories={1: TerminalCategory.CLEANUP_LIMITATION},
            cleanup_states={1: CleanupState.LIMITED},
        )


@pytest.mark.parametrize(
    ("variant", "terminal_event", "category"),
    (
        (
            TraceVariant.SOURCE_RESOURCE_FAILURE,
            "worker_source_failure",
            TerminalCategory.RESOURCE_READER_UNAVAILABLE,
        ),
        (
            TraceVariant.PREPARATION_TIMEOUT,
            "parent_preparation_timeout",
            TerminalCategory.PREPARATION_TIMEOUT,
        ),
        (
            TraceVariant.OBSERVATION_TRANSPORT_FAILURE,
            "observation_transport_failed",
            TerminalCategory.OBSERVATION_FAILURE,
        ),
        (
            TraceVariant.ACKNOWLEDGEMENT_FAILURE,
            "acknowledgement_failed",
            TerminalCategory.ACKNOWLEDGEMENT_FAILURE,
        ),
        (
            TraceVariant.RECEIPT_FAILURE,
            "receipt_failed",
            TerminalCategory.RECEIPT_FAILURE,
        ),
        (
            TraceVariant.PROCESS_SETTLEMENT_FAILURE,
            "process_settlement_failed",
            TerminalCategory.PROCESS_SETTLEMENT_FAILURE,
        ),
    ),
)
def test_fix11_failure_variants_require_exact_source_terminal(
    variant: TraceVariant,
    terminal_event: str,
    category: TerminalCategory,
) -> None:
    event_factory = (
        _worker if terminal_event == "worker_source_failure" else _parent
    )
    trace = (
        _parent("attempt_authority_created", 1, 0),
        _parent("attempt_deadline_started", 1, 1),
        _parent("process_spawn_requested", 1, 2),
        event_factory(terminal_event, 1, 0 if event_factory is _worker else 3),
        _parent("attempt_cleanup_started", 1, 4),
        _parent("attempt_cleanup_completed", 1, 5),
    )
    validate_trace_variant(
        trace,
        variant,
        terminal_categories={1: category},
        cleanup_states={1: CleanupState.COMPLETED},
    )

    wrong_terminal = tuple(
        replace(
            event,
            event=(
                "worker_source_failure"
                if terminal_event == "parent_preparation_timeout"
                else "parent_preparation_timeout"
            ),
        )
        if event.event == terminal_event
        else event
        for event in trace
    )
    with pytest.raises(TraceContractError):
        validate_trace_variant(
            wrong_terminal,
            variant,
            terminal_categories={1: category},
            cleanup_states={1: CleanupState.COMPLETED},
        )


def test_fix11_rejects_semantic_success_without_enacted_events() -> None:
    with pytest.raises(TraceContractError, match="required event"):
        validate_trace_variant(
            (
                _parent("attempt_authority_created", 1, 0),
                _parent("attempt_cleanup_completed", 1, 1),
            ),
            TraceVariant.SUCCESSFUL_ATTEMPT,
            terminal_categories={1: TerminalCategory.SUCCESS},
            cleanup_states={1: CleanupState.COMPLETED},
        )


@pytest.mark.parametrize(
    "late_event",
    (
        _parent("parent_frame_validated", 1, 4),
        _worker("canonical_encoding_started", 1, 1),
    ),
)
def test_fix11_failure_rejects_work_after_source_terminal(
    late_event: TraceEvent,
) -> None:
    source_event = (
        _parent("parent_preparation_timeout", 1, 3)
        if late_event.clock_domain is ClockDomain.PARENT_MONOTONIC
        else _worker("worker_source_failure", 1, 0)
    )
    variant = (
        TraceVariant.PREPARATION_TIMEOUT
        if source_event.clock_domain is ClockDomain.PARENT_MONOTONIC
        else TraceVariant.SOURCE_RESOURCE_FAILURE
    )
    category = (
        TerminalCategory.PREPARATION_TIMEOUT
        if variant is TraceVariant.PREPARATION_TIMEOUT
        else TerminalCategory.RESOURCE_READER_UNAVAILABLE
    )
    trace = (
        _parent("attempt_authority_created", 1, 0),
        _parent("attempt_deadline_started", 1, 1),
        _parent("process_spawn_requested", 1, 2),
        source_event,
        late_event,
        _parent("attempt_cleanup_started", 1, 5),
        _parent("attempt_cleanup_completed", 1, 6),
    )

    with pytest.raises(TraceContractError, match="after source failure"):
        validate_trace_variant(
            trace,
            variant,
            terminal_categories={1: category},
            cleanup_states={1: CleanupState.COMPLETED},
        )


def test_fix11_closed_clock_ownership_is_total() -> None:
    assert set(PARENT_EVENTS).isdisjoint(WORKER_EVENTS)
    assert CLOSED_EVENTS == set(PARENT_EVENTS) | set(WORKER_EVENTS)
