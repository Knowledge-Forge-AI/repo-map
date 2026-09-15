"""Public-safe reproducible decision model for SCALE28-ADR1."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class EvidenceSizedHandoffOutcome(str, Enum):
    """Closed outcomes for the fixed SCALE28-ADR1 evidence campaign."""

    EVIDENCE_SIZED_CANDIDATE = "evidence_sized_candidate"
    OPERATOR_GUARD_EXCEEDED = "operator_guard_exceeded"


_FIXED_OWNING_AREA_COUNTS = (
    ("SCALE14", 15),
    ("SCALE23", 15),
    ("SCALE28", 15),
    ("SCALE28-FIX1", 15),
)


@dataclass(frozen=True)
class EvidenceSizedHandoffInputs:
    """Public-safe bounded inputs from the fixed SCALE28-ADR1 campaign."""

    connection_bootstrap_max_ms: int
    sql_tail_ms: int
    resource_local_overhead_max_ms: int
    resource_settlement_max_ms: int
    event_readiness_max_ms: int
    transient_clear_max_ms: int
    complete_handoff_max_ms: int
    scheduling_and_ipc_margin_ms: int
    modeled_floor_ms: int
    operator_guard_ms: int
    cold_handoffs: int
    loaded_handoffs: int
    transient_settlements: int
    owning_area_counts: tuple[tuple[str, int], ...]
    valid_outliers_removed: int
    stable_sample_count: int
    resource_statement_count: int
    dynamic_tuning: bool

    def __post_init__(self) -> None:
        positive_values = (
            self.connection_bootstrap_max_ms,
            self.sql_tail_ms,
            self.resource_local_overhead_max_ms,
            self.resource_settlement_max_ms,
            self.event_readiness_max_ms,
            self.transient_clear_max_ms,
            self.complete_handoff_max_ms,
            self.scheduling_and_ipc_margin_ms,
            self.modeled_floor_ms,
            self.operator_guard_ms,
            self.cold_handoffs,
            self.loaded_handoffs,
            self.transient_settlements,
            self.stable_sample_count,
            self.resource_statement_count,
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for value in positive_values
        ):
            raise ValueError("evidence-sized handoff input is invalid")
        if (
            isinstance(self.valid_outliers_removed, bool)
            or not isinstance(self.valid_outliers_removed, int)
            or self.valid_outliers_removed != 0
        ):
            raise ValueError("valid observation removal is forbidden")
        if self.stable_sample_count < 2:
            raise ValueError("two stable ownership samples are required")
        if self.resource_statement_count != 2:
            raise ValueError("two startup resource statements are required")
        if self.dynamic_tuning is not False:
            raise ValueError("dynamic tuning is forbidden")
        if (
            self.cold_handoffs != 30
            or self.loaded_handoffs != 60
            or self.transient_settlements != 30
            or self.owning_area_counts != _FIXED_OWNING_AREA_COUNTS
        ):
            raise ValueError("fixed measurement campaign is incomplete")

    @property
    def signature(self) -> tuple[object, ...]:
        """Return the complete immutable input identity for recomputation."""

        return (
            self.connection_bootstrap_max_ms,
            self.sql_tail_ms,
            self.resource_local_overhead_max_ms,
            self.resource_settlement_max_ms,
            self.event_readiness_max_ms,
            self.transient_clear_max_ms,
            self.complete_handoff_max_ms,
            self.scheduling_and_ipc_margin_ms,
            self.modeled_floor_ms,
            self.operator_guard_ms,
            self.cold_handoffs,
            self.loaded_handoffs,
            self.transient_settlements,
            self.owning_area_counts,
            self.valid_outliers_removed,
            self.stable_sample_count,
            self.resource_statement_count,
            self.dynamic_tuning,
        )


@dataclass(frozen=True)
class EvidenceSizedHandoffDecision:
    """Reproducible bounded decision without raw timing observations."""

    connection_establishment_budget_ms: int
    server_statement_timeout_ms: int
    client_cancellation_trigger_ms: int
    cancellation_request_timeout_ms: int
    caller_operation_deadline_ms: int
    observer_settlement_deadline_ms: int
    resource_local_budget_ms: int
    resource_settlement_budget_ms: int
    event_readiness_budget_ms: int
    transient_settlement_budget_ms: int
    component_sum_ms: int
    measured_handoff_bound_ms: int
    modeled_floor_ms: int
    selected_handoff_ceiling_ms: int
    operator_guard_ms: int
    outcome: EvidenceSizedHandoffOutcome
    option_one_authorized: bool
    production_value_authorized: bool
    mandatory_successor: str
    scale29_authorized: bool
    input_signature: tuple[object, ...]

    def is_frozen_candidate(self, candidate_ms: int) -> bool:
        """Return whether a value is the exact formula result above the floor."""

        return (
            not isinstance(candidate_ms, bool)
            and isinstance(candidate_ms, int)
            and candidate_ms > self.modeled_floor_ms
            and candidate_ms == self.selected_handoff_ceiling_ms
        )

    def is_authorized_candidate(self, candidate_ms: int) -> bool:
        """Return whether the frozen value also passes the architecture guard."""

        return self.is_frozen_candidate(candidate_ms) and self.option_one_authorized

    def matches_inputs(self, inputs: EvidenceSizedHandoffInputs) -> bool:
        """Reject reuse of a derivation after any fixed input changes."""

        return self.input_signature == inputs.signature


def _round_up(value: int, quantum: int) -> int:
    return ((value + quantum - 1) // quantum) * quantum


def _ten_percent_ceil(value: int) -> int:
    return (value + 9) // 10


def derive_evidence_sized_handoff(
    inputs: EvidenceSizedHandoffInputs,
) -> EvidenceSizedHandoffDecision:
    """Apply the pre-registered SCALE28-ADR1 integer-millisecond formula."""

    operation_margin = _round_up(
        max(25, _ten_percent_ceil(inputs.sql_tail_ms)),
        10,
    )
    server_timeout = _round_up(inputs.sql_tail_ms + operation_margin, 10)
    client_trigger = server_timeout + 20
    cancellation_timeout = 20
    caller_deadline = client_trigger + cancellation_timeout

    connection_margin = _round_up(
        max(25, _ten_percent_ceil(inputs.connection_bootstrap_max_ms)),
        10,
    )
    connection_budget = _round_up(
        inputs.connection_bootstrap_max_ms + connection_margin,
        10,
    )
    local_margin = _round_up(
        max(10, _ten_percent_ceil(inputs.resource_local_overhead_max_ms)),
        10,
    )
    local_budget = _round_up(
        inputs.resource_local_overhead_max_ms + local_margin,
        10,
    )
    settlement_margin = _round_up(
        max(25, _ten_percent_ceil(inputs.resource_settlement_max_ms)),
        10,
    )
    settlement_budget = _round_up(
        inputs.resource_settlement_max_ms + settlement_margin,
        10,
    )
    event_margin = _round_up(
        max(10, _ten_percent_ceil(inputs.event_readiness_max_ms)),
        10,
    )
    event_budget = _round_up(inputs.event_readiness_max_ms + event_margin, 10)
    transient_margin = _round_up(
        max(25, _ten_percent_ceil(inputs.transient_clear_max_ms)),
        10,
    )
    transient_budget = _round_up(
        max(50, inputs.transient_clear_max_ms + transient_margin),
        10,
    )
    component_sum = (
        local_budget
        + inputs.resource_statement_count * caller_deadline
        + settlement_budget
        + event_budget
        + transient_budget
        + inputs.stable_sample_count * caller_deadline
        + inputs.scheduling_and_ipc_margin_ms
    )
    measured_handoff_bound = (
        inputs.complete_handoff_max_ms + inputs.scheduling_and_ipc_margin_ms
    )
    selected = _round_up(
        max(component_sum, measured_handoff_bound, inputs.modeled_floor_ms + 1),
        50,
    )
    guard_exceeded = selected > inputs.operator_guard_ms
    outcome = (
        EvidenceSizedHandoffOutcome.OPERATOR_GUARD_EXCEEDED
        if guard_exceeded
        else EvidenceSizedHandoffOutcome.EVIDENCE_SIZED_CANDIDATE
    )
    return EvidenceSizedHandoffDecision(
        connection_establishment_budget_ms=connection_budget,
        server_statement_timeout_ms=server_timeout,
        client_cancellation_trigger_ms=client_trigger,
        cancellation_request_timeout_ms=cancellation_timeout,
        caller_operation_deadline_ms=caller_deadline,
        observer_settlement_deadline_ms=caller_deadline,
        resource_local_budget_ms=local_budget,
        resource_settlement_budget_ms=settlement_budget,
        event_readiness_budget_ms=event_budget,
        transient_settlement_budget_ms=transient_budget,
        component_sum_ms=component_sum,
        measured_handoff_bound_ms=measured_handoff_bound,
        modeled_floor_ms=inputs.modeled_floor_ms,
        selected_handoff_ceiling_ms=selected,
        operator_guard_ms=inputs.operator_guard_ms,
        outcome=outcome,
        option_one_authorized=not guard_exceeded,
        production_value_authorized=False,
        mandatory_successor=(
            "bounded_revised_or_process_isolated_startup_authority"
            if guard_exceeded
            else "scale28_fix4"
        ),
        scale29_authorized=False,
        input_signature=inputs.signature,
    )
