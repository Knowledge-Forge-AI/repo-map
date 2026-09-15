from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from repomap_test_support.test_cov5g_fix1_projection import (
    ObservationPoint,
    ProjectionSchedule,
    PublicationOrder,
    RequestResult,
    projection_schedules,
    run_projection_schedule,
)
from scale28_observer_deadlines import (
    ObserverCancellationRequestOutcome,
    ObserverCancellationState,
)


_EXPECTED_LIMITATION = {
    RequestResult.SUCCESS: None,
    RequestResult.TIMEOUT: "cancellation_timeout",
    RequestResult.TRANSPORT_FAILURE: "cancellation_failure",
}
_EXPECTED_OUTCOME = {
    RequestResult.SUCCESS: "request_succeeded",
    RequestResult.TIMEOUT: "request_timed_out",
    RequestResult.TRANSPORT_FAILURE: "request_failed",
}
_TWELVE_PROJECTION_CASES = tuple(
    ProjectionSchedule(
        order,
        request_result,
        snapshot_at,
        ObservationPoint.BOTH_TERMINAL,
    )
    for order in PublicationOrder
    for request_result in RequestResult
    for snapshot_at in (
        ObservationPoint.BOTH_ACTIVE,
        ObservationPoint.BETWEEN_RESULTS,
    )
)
_ALL_SCHEDULES = projection_schedules()


def _ten_schedules(
    *,
    order: PublicationOrder,
    result: RequestResult | None = None,
    exclude_result: RequestResult | None = None,
) -> tuple[ProjectionSchedule, ...]:
    selected = tuple(
        schedule
        for schedule in _ALL_SCHEDULES
        if schedule.order is order
        and (result is None or schedule.request_result is result)
        and (
            exclude_result is None
            or schedule.request_result is not exclude_result
        )
    )
    assert len(selected) >= 10
    return selected[:10]


_FORTY_PUBLICATION_SCHEDULES = (
    _ten_schedules(
        order=PublicationOrder.REQUEST_FIRST,
        exclude_result=RequestResult.TRANSPORT_FAILURE,
    )
    + _ten_schedules(
        order=PublicationOrder.OPERATION_FIRST,
        exclude_result=RequestResult.TRANSPORT_FAILURE,
    )
    + _ten_schedules(
        order=PublicationOrder.REQUEST_FIRST,
        result=RequestResult.TRANSPORT_FAILURE,
    )
    + _ten_schedules(
        order=PublicationOrder.OPERATION_FIRST,
        result=RequestResult.TRANSPORT_FAILURE,
    )
)


@pytest.mark.parametrize(
    "schedule",
    _TWELVE_PROJECTION_CASES,
    ids=lambda schedule: schedule.case_id,
)
def test_twelve_distinct_immutable_projection_semantics(
    schedule: ProjectionSchedule,
) -> None:
    observation = run_projection_schedule(schedule)
    error = observation.error
    boundary = error.observer_boundary
    timeout_mechanism = error.observer_timeout_mechanism
    limitation = error.observer_cancellation_limitation

    assert boundary is not None
    assert boundary.value == (
        "observer_operation_execution_timeout"
    )
    assert timeout_mechanism is not None
    assert timeout_mechanism.value == "client_cancel_fallback"
    if schedule.order is PublicationOrder.REQUEST_FIRST:
        assert (
            limitation.value if limitation is not None else None
        ) == _EXPECTED_LIMITATION[schedule.request_result]
    else:
        assert limitation is None
    assert observation.terminal_snapshot.cancellation.request_outcome.value == (
        _EXPECTED_OUTCOME[schedule.request_result]
    )
    assert (
        observation.error_fields_before_later_publication
        == observation.error_fields_after_later_publication
    )


@pytest.mark.parametrize(
    "schedule",
    _FORTY_PUBLICATION_SCHEDULES,
    ids=lambda schedule: schedule.case_id,
)
def test_forty_deterministic_publication_order_schedules(
    schedule: ProjectionSchedule,
) -> None:
    observation = run_projection_schedule(schedule)
    sequence = observation.sequence
    request_index = sequence.index("request_published")
    operation_index = sequence.index("operation_published")

    if schedule.order is PublicationOrder.REQUEST_FIRST:
        assert request_index < operation_index
        assert observation.between_snapshot.cancellation.request_in_flight is False
        assert observation.between_snapshot.operation_in_flight is True
    else:
        assert operation_index < request_index
        assert observation.between_snapshot.cancellation.request_in_flight is True
        assert observation.between_snapshot.operation_in_flight is False
    assert observation.terminal_snapshot.cancellation.operation_settled is True
    assert observation.terminal_snapshot.cancellation.request_in_flight is False
    assert observation.terminal_snapshot.cancellation.close_eligible is True
    assert observation.close_while_active is False
    assert observation.close_count == 1


def test_earlier_and_later_snapshots_are_independently_immutable() -> None:
    observation = run_projection_schedule(
        ProjectionSchedule(
            PublicationOrder.OPERATION_FIRST,
            RequestResult.TIMEOUT,
            ObservationPoint.BETWEEN_RESULTS,
            ObservationPoint.BOTH_ACTIVE,
        )
    )
    earlier = observation.between_snapshot
    later = observation.terminal_snapshot

    assert earlier.cancellation.request_in_flight is True
    assert earlier.cancellation.request_outcome.value == "not_requested"
    assert later.cancellation.request_in_flight is False
    assert later.cancellation.request_outcome.value == "request_timed_out"
    assert earlier.cancellation.request_in_flight is True
    with pytest.raises(FrozenInstanceError):
        setattr(earlier, "close_begun", False)
    with pytest.raises(FrozenInstanceError):
        setattr(earlier.cancellation, "request_in_flight", False)


def test_projection_and_snapshot_repr_expose_no_private_ordering_values() -> None:
    observation = run_projection_schedule(
        ProjectionSchedule(
            PublicationOrder.REQUEST_FIRST,
            RequestResult.TRANSPORT_FAILURE,
            ObservationPoint.BETWEEN_RESULTS,
            ObservationPoint.BETWEEN_RESULTS,
        )
    )
    error = observation.error
    rendered = f"{error!r} {observation.terminal_snapshot!r}"

    assert not hasattr(error, "publication_sequence")
    assert not hasattr(error, "connection")
    assert not hasattr(error, "backend")
    assert "bounded cancellation transport failure" not in rendered
    assert "request_published" not in rendered


def test_duplicate_request_result_is_idempotent_and_conflict_fails_closed() -> None:
    active = ObserverCancellationState(
        operation_timeout_created=True,
        cancellation_requested=True,
        request_in_flight=True,
        operation_settled=False,
    )
    timed_out = active.record_request_outcome(
        ObserverCancellationRequestOutcome.REQUEST_TIMED_OUT
    )

    assert (
        timed_out.record_request_outcome(
            ObserverCancellationRequestOutcome.REQUEST_TIMED_OUT
        )
        is timed_out
    )
    with pytest.raises(
        ValueError,
        match="observer cancellation outcome conflicts",
    ):
        timed_out.record_request_outcome(
            ObserverCancellationRequestOutcome.REQUEST_FAILED
        )
