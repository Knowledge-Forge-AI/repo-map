"""Deterministic TEST-COV5G-R1 containment case identities."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from repomap_test_support.test_cov5g_fix1_projection import (
    ObservationPoint,
    ProjectionSchedule,
    PublicationOrder,
    RequestResult,
)


_SAME_PROCESS_SEMANTICS = (
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
)


@dataclass(frozen=True, slots=True)
class SameProcessCase:
    """One distinct semantic containment schedule."""

    case_id: str
    semantic: str
    schedule: ProjectionSchedule


def same_process_cases() -> tuple[SameProcessCase, ...]:
    """Return forty distinct barrier/publication schedules."""

    cases: list[SameProcessCase] = []
    for index in range(40):
        order = tuple(PublicationOrder)[index % 2]
        request_result = tuple(RequestResult)[(index // 2) % 3]
        snapshot_at = tuple(ObservationPoint)[(index // 6) % 3]
        close_at = tuple(ObservationPoint)[(index // 18) % 3]
        close_before_snapshot = (index // 3) % 2 == 1
        schedule = ProjectionSchedule(
            order,
            request_result,
            snapshot_at,
            close_at,
            close_before_snapshot,
        )
        semantic = _SAME_PROCESS_SEMANTICS[index % len(_SAME_PROCESS_SEMANTICS)]
        cases.append(
            SameProcessCase(
                case_id=f"same-process-{index + 1:02d}-{semantic}",
                semantic=semantic,
                schedule=schedule,
            )
        )
    if len({case.schedule.case_id for case in cases}) != 40:
        raise AssertionError("same-process schedules are not distinct")
    return tuple(cases)


class ProcessRequestMode(str, Enum):
    """A test-seam cancellation-request behavior in the child."""

    SUCCESS = "success"
    TIMEOUT = "timeout"
    TRANSPORT_FAILURE = "transport_failure"
    HELD = "held"


class ParentAction(str, Enum):
    """The parent-owned terminal containment action."""

    COOPERATIVE_STOP = "cooperative_stop"
    FORCED_TERMINATION = "forced_termination"
    CHANNEL_CLOSE = "channel_close"
    PARENT_CANCELLATION = "parent_cancellation"
    LIVE_DESCENDANT_REFUSAL = "live_descendant_refusal"


@dataclass(frozen=True, slots=True)
class ProcessContainmentCase:
    """One spawn-safe process-containment feasibility case."""

    case_id: str
    request_mode: ProcessRequestMode
    operation_held: bool
    parent_action: ParentAction


_PROCESS_CASE_SHAPE = (
    (ProcessRequestMode.SUCCESS, False, ParentAction.COOPERATIVE_STOP),
    (ProcessRequestMode.SUCCESS, True, ParentAction.FORCED_TERMINATION),
    (ProcessRequestMode.TIMEOUT, False, ParentAction.COOPERATIVE_STOP),
    (ProcessRequestMode.TIMEOUT, True, ParentAction.FORCED_TERMINATION),
    (
        ProcessRequestMode.TRANSPORT_FAILURE,
        False,
        ParentAction.COOPERATIVE_STOP,
    ),
    (
        ProcessRequestMode.TRANSPORT_FAILURE,
        True,
        ParentAction.FORCED_TERMINATION,
    ),
    (ProcessRequestMode.HELD, True, ParentAction.FORCED_TERMINATION),
    (ProcessRequestMode.HELD, True, ParentAction.CHANNEL_CLOSE),
    (ProcessRequestMode.SUCCESS, True, ParentAction.PARENT_CANCELLATION),
    (
        ProcessRequestMode.SUCCESS,
        True,
        ParentAction.LIVE_DESCENDANT_REFUSAL,
    ),
)


def process_containment_cases() -> tuple[ProcessContainmentCase, ...]:
    """Return twenty distinct process-feasibility cases."""

    return tuple(
        ProcessContainmentCase(
            case_id=(
                f"process-{index + 1:02d}-{request_mode.value}-"
                f"{'operation-held' if operation_held else 'operation-settles'}-"
                f"{parent_action.value}"
            ),
            request_mode=request_mode,
            operation_held=operation_held,
            parent_action=parent_action,
        )
        for index, (request_mode, operation_held, parent_action) in enumerate(
            _PROCESS_CASE_SHAPE * 2
        )
    )
