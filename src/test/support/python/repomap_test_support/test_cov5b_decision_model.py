"""Public-safe decision model for TEST-COV5B observer authority options."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable


@dataclass(frozen=True)
class DeadlineEnvelope:
    """One strict server, client, cancellation, caller deadline envelope."""

    server_ms: int
    client_ms: int
    cancel_request_ms: int
    caller_ms: int
    reserve_ms: int

    def __post_init__(self) -> None:
        values = (
            self.server_ms,
            self.client_ms,
            self.cancel_request_ms,
            self.caller_ms,
            self.reserve_ms,
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for value in values
        ):
            raise ValueError("deadline envelope is invalid")
        if (
            self.client_ms - self.server_ms < self.reserve_ms
            or self.caller_ms - self.client_ms
            < self.cancel_request_ms + self.reserve_ms
        ):
            raise ValueError("deadline envelope is invalid")

    @property
    def minimum_operation_ms(self) -> int:
        """Return the complete operation budget required before dispatch."""

        return self.server_ms + self.cancel_request_ms + (2 * self.reserve_ms)


@dataclass(frozen=True)
class EnvelopeQualification:
    """Return one bounded feasibility result without raw timing evidence."""

    accepted: bool
    reasons: tuple[str, ...]
    minimum_handoff_ms: int


def qualify_envelope(
    envelope: DeadlineEnvelope,
    *,
    handoff_ceiling_ms: int,
    configured_sql_lower_bound_ms: int,
    transient_settlement_ms: int,
) -> EnvelopeQualification:
    """Evaluate SQL containment and stable ownership under one ceiling."""

    inputs = (
        handoff_ceiling_ms,
        configured_sql_lower_bound_ms,
        transient_settlement_ms,
    )
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value <= 0
        for value in inputs
    ):
        raise ValueError("qualification input is invalid")
    minimum_handoff_ms = (
        transient_settlement_ms + (2 * envelope.minimum_operation_ms)
    )
    reasons: list[str] = []
    if envelope.server_ms < configured_sql_lower_bound_ms:
        reasons.append("configured_sql_exceeds_server_budget")
    if minimum_handoff_ms > handoff_ceiling_ms:
        reasons.append("stable_ownership_exceeds_handoff_ceiling")
    if envelope.caller_ms >= handoff_ceiling_ms:
        reasons.append("caller_deadline_exceeds_handoff_ceiling")
    return EnvelopeQualification(
        not reasons,
        tuple(reasons),
        minimum_handoff_ms,
    )


@dataclass(frozen=True)
class AuthorityEvent:
    """One source-created authority event and its causal sequence."""

    name: str
    source_sequence: int

    def __post_init__(self) -> None:
        if (
            not self.name
            or isinstance(self.source_sequence, bool)
            or not isinstance(self.source_sequence, int)
            or self.source_sequence < 1
        ):
            raise ValueError("authority event is invalid")


def project_source_order(
    source_events: Iterable[AuthorityEvent],
    observation_order: Iterable[str],
) -> tuple[str, ...]:
    """Project causal order independently of observation scheduling."""

    events = tuple(source_events)
    observed = tuple(observation_order)
    names = tuple(event.name for event in events)
    if len(set(names)) != len(names) or set(observed) != set(names):
        raise ValueError("authority event set is invalid")
    if len(observed) != len(names):
        raise ValueError("authority observation order is invalid")
    return tuple(
        event.name
        for event in sorted(events, key=lambda item: item.source_sequence)
    )


class DecisionOption(str, Enum):
    """Operator choices that can resolve the characterized ceiling conflict."""

    CEILING_INCREASE = "ceiling_increase"
    ISOLATED_AUTHORITY = "isolated_authority"


_COMMON_ACCEPTANCE_REQUIREMENTS = (
    "bounded_bootstrap_fault_matrix",
    "real_timeout_hierarchy",
    "five_hundred_source_order_permutations",
    "four_owning_configured_paths",
    "fifteen_mixed_campaigns",
    "three_fresh_public_rehearsals",
    "prior_publication_failure_rehearsal",
    "four_complete_repository_gates",
    "exact_cleanup",
)


def decision_acceptance_requirements(
    option: DecisionOption,
) -> tuple[str, ...]:
    """Return the exact additive acceptance requirements for one option."""

    if option is DecisionOption.CEILING_INCREASE:
        specific = (
            "authorized_handoff_ceiling",
            "configured_tail_latency_budget",
        )
    elif option is DecisionOption.ISOLATED_AUTHORITY:
        specific = (
            "bounded_worker_lifetime",
            "atomic_release_ownership_contract",
        )
    else:
        raise ValueError("decision option is invalid")
    return specific + _COMMON_ACCEPTANCE_REQUIREMENTS
