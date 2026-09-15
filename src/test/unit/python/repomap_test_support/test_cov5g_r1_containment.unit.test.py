from __future__ import annotations

import pytest

from repomap_test_support.test_cov5g_fix1_projection import (
    PublicationOrder,
    RequestResult,
    run_projection_schedule,
)
from repomap_test_support.test_cov5g_r1_containment import (
    ParentAction,
    ProcessRequestMode,
    process_containment_cases,
    same_process_cases,
)


_SAME_PROCESS_CASES = same_process_cases()
_PROCESS_CASES = process_containment_cases()


@pytest.mark.parametrize(
    "case",
    _SAME_PROCESS_CASES,
    ids=lambda case: case.case_id,
)
def test_forty_same_process_containment_schedules(case) -> None:
    observation = run_projection_schedule(case.schedule)
    sequence = observation.sequence
    request_index = sequence.index("request_published")
    operation_index = sequence.index("operation_published")

    if case.schedule.order is PublicationOrder.REQUEST_FIRST:
        assert request_index < operation_index
    else:
        assert operation_index < request_index
    expected_outcome = {
        RequestResult.SUCCESS: "request_succeeded",
        RequestResult.TIMEOUT: "request_timed_out",
        RequestResult.TRANSPORT_FAILURE: "request_failed",
    }[case.schedule.request_result]
    assert (
        observation.terminal_snapshot.cancellation.request_outcome.value
        == expected_outcome
    )
    assert observation.terminal_snapshot.cancellation.operation_settled is True
    assert observation.terminal_snapshot.cancellation.close_eligible is True
    assert observation.close_while_active is False
    assert observation.close_count == 1


def test_same_process_manifest_covers_every_required_semantic() -> None:
    semantics = {case.semantic for case in _SAME_PROCESS_CASES}

    assert len(_SAME_PROCESS_CASES) == 40
    assert len({case.case_id for case in _SAME_PROCESS_CASES}) == 40
    assert semantics == {
        "request_success_before_operation_return",
        "operation_return_before_request_success",
        "request_timeout_while_operation_active",
        "request_timeout_then_query_canceled",
        "transport_failure_then_operation_return",
        "local_close_while_request_active",
        "close_after_request_settled_operation_active",
        "operation_settled_before_request",
        "both_settled_before_close",
        "settlement_ceiling_reached",
        "fresh_terminal_readback_live_limitation",
        "duplicate_close",
        "request_first_immutable_projection",
        "operation_first_immutable_projection",
    }


@pytest.mark.parametrize(
    "case",
    _PROCESS_CASES,
    ids=lambda case: case.case_id,
)
def test_twenty_process_containment_case_contracts(case) -> None:
    assert case.request_mode in ProcessRequestMode
    assert case.parent_action in ParentAction
    if case.request_mode is ProcessRequestMode.HELD:
        assert case.operation_held is True
        assert case.parent_action in {
            ParentAction.FORCED_TERMINATION,
            ParentAction.CHANNEL_CLOSE,
        }
    if case.parent_action is ParentAction.LIVE_DESCENDANT_REFUSAL:
        assert case.operation_held is True


def test_process_manifest_covers_required_feasibility_boundaries() -> None:
    assert len(_PROCESS_CASES) == 20
    assert len({case.case_id for case in _PROCESS_CASES}) == 20
    assert {case.request_mode for case in _PROCESS_CASES} == set(
        ProcessRequestMode
    )
    assert {case.parent_action for case in _PROCESS_CASES} == set(ParentAction)
    assert any(case.operation_held for case in _PROCESS_CASES)
    assert any(not case.operation_held for case in _PROCESS_CASES)
