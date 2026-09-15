from __future__ import annotations

import pytest

from repomap_kg.storage.staging_operation_contracts import operation_descriptor
from repomap_kg.storage.staging_operation_events import (
    StagingOperationEvent,
    StagingOperationEventCategory,
)
from scale12_operation_state import (
    ActiveOperationState,
    OperationAttributionError,
)


def _start(code: str, sequence: int = 1, offset: int = 10) -> StagingOperationEvent:
    return StagingOperationEvent.started(
        operation_descriptor(code), sequence, offset
    )


def _terminal(
    code: str,
    sequence: int = 1,
    offset: int = 20,
    category: StagingOperationEventCategory = (
        StagingOperationEventCategory.COMPLETED
    ),
) -> StagingOperationEvent:
    return StagingOperationEvent.terminal(
        operation_descriptor(code),
        sequence,
        category,
        offset,
        offset - 10,
    )


def test_scale12_operation_state_reports_exact_active_snapshot() -> None:
    state = ActiveOperationState()
    state.accept(_start("merge.files"))

    snapshot = state.snapshot(15)

    assert snapshot.attribution == "exact"
    assert snapshot.active_operations == ("merge.files",)
    assert snapshot.most_specific_active_operation == "merge.files"
    assert snapshot.enclosing_operation_group == "merge"
    assert snapshot.active_elapsed_ns == 5
    assert snapshot.transport_healthy is True


def test_scale12_operation_state_rejects_invalid_event_and_loses_attribution() -> None:
    state = ActiveOperationState()
    with pytest.raises(OperationAttributionError, match="event type is invalid"):
        state.accept({"operation_code": "merge.files"})
    snapshot = state.snapshot(0)
    assert snapshot.attribution == "operation_attribution_unknown"
    assert snapshot.transport_healthy is False


@pytest.mark.parametrize(
    "category",
    (
        StagingOperationEventCategory.COMPLETED,
        StagingOperationEventCategory.FAILED,
        StagingOperationEventCategory.CANCELLED,
    ),
)
def test_scale12_operation_state_accepts_one_terminal_and_clears_active(
    category: StagingOperationEventCategory,
) -> None:
    state = ActiveOperationState()
    state.accept(_start("guard.publication_prepare"))
    state.accept(_terminal("guard.publication_prepare", category=category))

    snapshot = state.snapshot(21)

    assert snapshot.active_operations == ()
    assert snapshot.most_specific_active_operation is None
    assert state.completed_sequence == 1


def test_scale12_operation_state_rejects_nested_or_duplicate_start() -> None:
    state = ActiveOperationState()
    state.accept(_start("merge.files"))

    with pytest.raises(OperationAttributionError, match="active"):
        state.accept(_start("merge.raw_observations"))

    assert state.attribution == "operation_attribution_unknown"


@pytest.mark.parametrize(
    "event",
    (
        _terminal("merge.files"),
        _start("merge.files", sequence=2),
    ),
)
def test_scale12_operation_state_rejects_terminal_without_start_or_gap(
    event: StagingOperationEvent,
) -> None:
    state = ActiveOperationState()

    with pytest.raises(OperationAttributionError):
        state.accept(event)


def test_scale12_operation_state_rejects_mismatched_or_duplicate_terminal() -> None:
    state = ActiveOperationState()
    state.accept(_start("merge.files"))
    with pytest.raises(OperationAttributionError, match="terminal"):
        state.accept(_terminal("merge.raw_observations"))

    complete = ActiveOperationState()
    complete.accept(_start("merge.files"))
    complete.accept(_terminal("merge.files"))
    with pytest.raises(OperationAttributionError, match="terminal"):
        complete.accept(_terminal("merge.files"))


def test_scale12_operation_state_rejects_out_of_order_event_or_sample() -> None:
    state = ActiveOperationState()
    state.accept(_start("merge.files", offset=10))

    with pytest.raises(OperationAttributionError, match="offset"):
        state.snapshot(9)


def test_scale12_operation_state_close_requires_no_open_operation() -> None:
    state = ActiveOperationState()
    state.accept(_start("merge.files"))
    with pytest.raises(
        OperationAttributionError,
        match=(
            "operation lifecycle ended while active: "
            "code=merge.files, sequence=1"
        ),
    ):
        state.close()

    complete = ActiveOperationState()
    complete.accept(_start("merge.files"))
    complete.accept(_terminal("merge.files"))
    complete.close()
    with pytest.raises(OperationAttributionError, match="closed"):
        complete.accept(_start("merge.raw_observations", sequence=2, offset=30))
