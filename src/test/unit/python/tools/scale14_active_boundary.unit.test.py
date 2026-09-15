from __future__ import annotations

import pytest

from repomap_kg.storage.staging_operation_contracts import operation_descriptor
from repomap_kg.storage.staging_operation_events import (
    StagingOperationEvent,
    StagingOperationEventCategory,
)
from scale14_active_boundary import ActiveBoundaryError, ActiveBoundaryState


def _phase(sequence: int, code: str, category: str, offset: int):
    terminal = category if category != "started" else None
    return {
        "schema_version": 1,
        "attempt_local_sequence": sequence,
        "phase_code": code,
        "event_category": category,
        "monotonic_offset_ns": offset,
        "duration_ns_or_null": None if terminal is None else offset - 10,
        "terminal_category_or_null": terminal,
        "process_cpu_duration_ns_or_null": None,
    }


def _operation(
    code: str,
    category: StagingOperationEventCategory,
    offset: int,
    sequence: int,
    started_offset: int,
):
    descriptor = operation_descriptor(code)
    if category is StagingOperationEventCategory.STARTED:
        event = StagingOperationEvent.started(descriptor, sequence, offset)
    else:
        event = StagingOperationEvent.terminal(
            descriptor,
            sequence,
            category,
            offset,
            offset - started_offset,
        )
    return event.to_payload()


def test_active_boundary_prefers_operation_and_tracks_exact_elapsed() -> None:
    state = ActiveBoundaryState(idle_limit_ns=50)
    state.accept_phase(_phase(1, "refresh.source_discovery", "started", 10))
    state.accept_operation(
        _operation(
            "merge.files",
            StagingOperationEventCategory.STARTED,
            12,
            1,
            12,
        )
    )

    snapshot = state.snapshot(20)

    assert snapshot.attribution == "merge.files"
    assert snapshot.phase_code == "refresh.source_discovery"
    assert snapshot.phase_elapsed_ns == 10
    assert snapshot.operation_code == "merge.files"
    assert snapshot.operation_elapsed_ns == 8
    assert snapshot.final_transaction_elapsed_ns is None


def test_active_boundary_final_transaction_clock_has_exact_endpoints() -> None:
    state = ActiveBoundaryState(idle_limit_ns=50)
    state.accept_operation(
        _operation(
            "guard.publication_prepare",
            StagingOperationEventCategory.STARTED,
            100,
            1,
            100,
        )
    )
    assert state.snapshot(110).final_transaction_elapsed_ns == 10
    state.accept_operation(
        _operation(
            "guard.publication_prepare",
            StagingOperationEventCategory.COMPLETED,
            120,
            1,
            100,
        )
    )
    state.accept_operation(
        _operation(
            "transaction.commit",
            StagingOperationEventCategory.STARTED,
            130,
            2,
            130,
        )
    )
    assert state.snapshot(140).final_transaction_elapsed_ns == 40
    state.accept_operation(
        _operation(
            "transaction.commit",
            StagingOperationEventCategory.COMPLETED,
            150,
            2,
            130,
        )
    )
    assert state.snapshot(151).final_transaction_elapsed_ns is None


def test_active_boundary_enforces_two_poll_idle_limit() -> None:
    state = ActiveBoundaryState(idle_limit_ns=50)
    state.accept_phase(_phase(1, "refresh.source_discovery", "started", 10))
    state.accept_phase(_phase(1, "refresh.source_discovery", "completed", 20))

    assert state.snapshot(70).attribution == "between_boundaries"
    with pytest.raises(ActiveBoundaryError, match="idle"):
        state.snapshot(71)


def test_active_boundary_does_not_start_idle_clock_before_first_event() -> None:
    state = ActiveBoundaryState(idle_limit_ns=50)

    assert state.snapshot(51).attribution == "between_boundaries"
    assert state.snapshot(5_000).attribution == "between_boundaries"


def test_active_boundary_fails_closed_on_invalid_operation_payload() -> None:
    state = ActiveBoundaryState()

    with pytest.raises(ActiveBoundaryError, match="operation"):
        state.accept_operation({"schema_version": 1})

    assert state.snapshot(1).attribution == "operation_attribution_unknown"


def test_active_boundary_close_requires_closed_phase_and_operation() -> None:
    state = ActiveBoundaryState()
    state.accept_operation(
        _operation(
            "merge.files",
            StagingOperationEventCategory.STARTED,
            10,
            1,
            10,
        )
    )

    with pytest.raises(ActiveBoundaryError, match="operation"):
        state.close()
