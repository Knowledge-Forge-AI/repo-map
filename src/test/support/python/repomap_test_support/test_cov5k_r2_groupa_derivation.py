"""Group-A expectation table, derivation, and public diagnostic values."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GroupAContract:
    """One closed real-preparation expectation row."""

    intents: tuple[str, ...]
    raw_outcomes: tuple[str, ...]
    raw_categories: tuple[str, ...]
    raw_boundaries: tuple[str, ...]
    projection: str


def _row(
    intents: tuple[str, ...],
    raw_categories: tuple[str, ...],
    raw_boundaries: tuple[str, ...],
    projection: str,
) -> GroupAContract:
    outcomes = tuple(
        "success" if value == "none" else "failure" for value in raw_categories
    )
    return GroupAContract(
        intents,
        outcomes,
        raw_categories,
        raw_boundaries,
        projection,
    )


GROUP_A_CONTRACTS = {
    "attempt_one_success": _row(
        ("success",), ("none",), ("none",), "released",
    ),
    "resource_failure_second_success": _row(
        ("resource", "success"), ("resource_unavailable", "none"),
        ("container_rss_read", "none"), "released",
    ),
    "timeout_second_success": _row(
        ("timeout", "success"), ("preparation_timeout", "none"),
        ("worker", "none"), "released",
    ),
    "two_generic_worker_failures": _row(
        ("generic_worker_failure", "generic_worker_failure"),
        ("worker_failed", "worker_failed"), ("worker", "worker"), "refused",
    ),
    "generic_worker_failure_then_timeout": _row(
        ("generic_worker_failure", "timeout"),
        ("worker_failed", "preparation_timeout"), ("worker", "worker"), "refused",
    ),
    "timeout_then_generic_worker_failure": _row(
        ("timeout", "generic_worker_failure"),
        ("preparation_timeout", "worker_failed"), ("worker", "worker"), "refused",
    ),
    "two_timeouts": _row(
        ("timeout", "timeout"), ("preparation_timeout", "preparation_timeout"),
        ("worker", "worker"), "refused",
    ),
    "retry_gate_refusal": _row(
        ("timeout",), ("preparation_timeout",), ("worker",),
        "refused",
    ),
    "final_refused_projection": _row(
        ("success",), ("none",), ("none",), "refused",
    ),
}


_RAW_PAIRS = {
    ("success", "none", "none"): "success",
    ("failure", "resource_unavailable", "container_rss_read"): "resource",
    ("failure", "preparation_timeout", "worker"): "timeout",
    ("failure", "worker_failed", "worker"): "generic_worker_failure",
    ("failure", "cleanup_limitation", "process_settlement"): "cleanup",
}
_PUBLIC_VALUES = frozenset(
    {
        "success", "failure", "none", "resource_unavailable", "resource",
        "container_rss_read", "preparation_timeout", "worker", "worker_failed",
        "generic_worker_failure", "cleanup_limitation", "process_settlement",
        "timeout", "cleanup", "matched", "scenario_contract_mismatch",
        "unexpected_raw_category", "worker_result", "worker_failure_notice",
        "parent_attempt_deadline", "released", "refused", "settled",
        "retry_observed", "retry_not_observed_after_failure",
        "retry_not_observed_after_parent_settlement_failure",
        "retry_not_applicable_after_success", "failed", "unrecognized",
        "not_observable_at_parent_attempt_boundary",
        "observed_sender_closed_without_notice", "captured",
        "parent_attempt_settlement",
        "unprepared", "preparing", "observation_received",
        "observation_acknowledged", "receipt_received", "receipt_validated",
        "worker_settled", "freshness_validated", "final_readiness_open",
        "transient_ownership_clear", "stable_sample_one",
        "stable_sample_two", "ready_to_release", "child_released",
    }
)

_RELEASE_LIFECYCLE_SUFFIX = (
    "observation_received",
    "observation_acknowledged",
    "receipt_received",
    "receipt_validated",
    "worker_settled",
    "freshness_validated",
    "final_readiness_open",
    "transient_ownership_clear",
    "stable_sample_one",
    "stable_sample_two",
    "ready_to_release",
    "child_released",
    "settled",
)
_HEALTHY_REFUSAL_LIFECYCLE_SUFFIX = (
    "observation_received",
    "observation_acknowledged",
    "receipt_received",
    "receipt_validated",
    "worker_settled",
    "freshness_validated",
    "refused",
    "settled",
)
_FAILED_REFUSAL_LIFECYCLE_SUFFIX = ("refused", "settled")


def derive_expected_group_a_state_history(
    raw_attempts: tuple[tuple[str, str, str], ...],
    projection: str,
) -> tuple[str, ...] | None:
    """Derive one closed lifecycle history from raw attempts and projection."""

    if not raw_attempts or any(len(attempt) != 3 for attempt in raw_attempts):
        return None
    outcomes = tuple(attempt[0] for attempt in raw_attempts)
    if any(outcome not in {"success", "failure"} for outcome in outcomes):
        return None
    if outcomes[-1] == "success":
        suffix = {
            "released": _RELEASE_LIFECYCLE_SUFFIX,
            "refused": _HEALTHY_REFUSAL_LIFECYCLE_SUFFIX,
        }.get(projection)
    elif projection == "refused" and all(
        outcome == "failure" for outcome in outcomes
    ):
        suffix = _FAILED_REFUSAL_LIFECYCLE_SUFFIX
    else:
        suffix = None
    if suffix is None:
        return None
    return (
        ("unprepared",)
        + ("preparing",) * len(raw_attempts)
        + suffix
    )


def canonical_attempt_category(outcome: str, category: str, boundary: str) -> str:
    """Interpret one already-observed raw worker result without scenario input."""

    return _RAW_PAIRS.get((outcome, category, boundary), "unexpected_raw_category")


def _raw_attempts(
    raw_outcomes: tuple[str, ...],
    raw_categories: tuple[str, ...],
    raw_boundaries: tuple[str, ...],
) -> tuple[tuple[str, str, str], ...]:
    if len({len(raw_outcomes), len(raw_categories), len(raw_boundaries)}) != 1:
        return ()
    return tuple(
        zip(raw_outcomes, raw_categories, raw_boundaries, strict=True)
    )


def derive_observed_retry_disposition(
    raw_outcomes: tuple[str, ...],
    raw_categories: tuple[str, ...],
    raw_boundaries: tuple[str, ...],
    state_history: tuple[str, ...],
) -> str:
    """Describe only whether runtime evidence shows a retry occurred."""

    raw_attempts = _raw_attempts(
        raw_outcomes, raw_categories, raw_boundaries
    )
    if (
        len(raw_attempts) != state_history.count("preparing")
        or not raw_attempts
    ):
        return "unrecognized"
    if any(
        canonical_attempt_category(*raw) == "unexpected_raw_category"
        for raw in raw_attempts
    ):
        return "unrecognized"
    if len(raw_outcomes) > 1:
        return "retry_observed"
    if raw_attempts == (
        ("failure", "cleanup_limitation", "process_settlement"),
    ):
        return "retry_not_observed_after_parent_settlement_failure"
    if raw_outcomes[0] == "success":
        return "retry_not_applicable_after_success"
    if raw_outcomes[0] == "failure":
        return "retry_not_observed_after_failure"
    return "unrecognized"


def derive_observed_group_a_contract_category(
    raw_outcomes: tuple[str, ...],
    raw_categories: tuple[str, ...],
    raw_boundaries: tuple[str, ...],
    state_history: tuple[str, ...],
    projection: str,
    maximum_attempts: int,
) -> str:
    """Derive the result category from runtime facts and frozen policy."""

    raw_attempts = _raw_attempts(
        raw_outcomes, raw_categories, raw_boundaries
    )
    if (
        not raw_attempts
        or len(raw_attempts) != state_history.count("preparing")
        or len(raw_outcomes) > maximum_attempts
        or not state_history
        or state_history[-1] != "settled"
        or projection not in {"released", "refused"}
    ):
        return "unrecognized"
    if any(
        canonical_attempt_category(*raw) == "unexpected_raw_category"
        for raw in raw_attempts
    ):
        return "unrecognized"
    expected_history = derive_expected_group_a_state_history(
        raw_attempts, projection
    )
    if expected_history is None or state_history != expected_history:
        return "unrecognized"
    if raw_outcomes[-1] == "success":
        return "success" if projection == "released" else "refused"
    if (
        projection == "refused"
        and all(outcome == "failure" for outcome in raw_outcomes)
    ):
        # The failed/refused distinction is owned by the actual frozen
        # maximum-attempt authority, not a Group-A expected value.
        return "failed" if len(raw_outcomes) == maximum_attempts else "refused"
    return "unrecognized"


def derive_forced_tail_policy(
    raw_categories: tuple[str, ...],
) -> tuple[bool, bool]:
    """Return observed tail requirement and kill form without scenario input."""

    required = "preparation_timeout" in raw_categories
    force_kill = raw_categories.count("preparation_timeout") >= 2
    return required, force_kill


def derive_observed_cleanup_disposition(
    raw_categories: tuple[str, ...],
) -> str:
    """Derive cleanup disposition from observed worker categories."""

    if "cleanup_limitation" in raw_categories:
        return "limited"
    if any(category != "none" for category in raw_categories):
        return "completed"
    if raw_categories:
        return "not_required"
    return "unrecognized"


def _safe_sequence(value: object) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        return ("unrecognized",)
    return tuple(
        item
        if isinstance(item, str) and item in _PUBLIC_VALUES
        else "unrecognized"
        for item in value
    )


def group_a_public_context(evidence) -> dict[str, object]:
    """Return a bounded projection suitable for assertion diagnostics."""

    observed = dict(evidence.observed_fields)
    events = dict(evidence.observed_product_events)
    fields = (
        "raw_worker_outcomes", "raw_worker_categories", "raw_worker_boundaries",
        "interpreted_evidence_origins", "scenario_injection_intents",
        "canonical_attempt_outcomes", "canonical_attempt_categories",
        "scenario_contract_categories",
    )
    projection = observed.get("final_projection_category", "unrecognized")
    context: dict[str, object] = {
        "attempt_count": len(observed.get("attempt_ids", ())),
        "final_projection": (
            projection if projection in {"released", "refused"} else "unrecognized"
        ),
        "state_history": _safe_sequence(events.get("preparation_state_history", ())),
        "attempt_elapsed_ms": (
            observed.get("attempt_elapsed_ms")
            if isinstance(observed.get("attempt_elapsed_ms"), int)
            else None
        ),
        "observed_contract_category": observed.get(
            "observed_contract_category", "unrecognized"
        ),
        "retry_disposition": observed.get(
            "retry_disposition", "unrecognized"
        ),
    }
    for field in fields:
        context[field] = _safe_sequence(observed.get(field, ()))
    return context
