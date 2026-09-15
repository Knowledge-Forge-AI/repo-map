"""Independent Group-A verification for real preparation evidence."""

from __future__ import annotations

from repomap_test_support.test_cov5k_r2_groupa_derivation import (
    GroupAContract as GroupAContract,
    _row as _row,
    GROUP_A_CONTRACTS as GROUP_A_CONTRACTS,
    _RAW_PAIRS as _RAW_PAIRS,
    _PUBLIC_VALUES as _PUBLIC_VALUES,
    _RELEASE_LIFECYCLE_SUFFIX as _RELEASE_LIFECYCLE_SUFFIX,
    _HEALTHY_REFUSAL_LIFECYCLE_SUFFIX as _HEALTHY_REFUSAL_LIFECYCLE_SUFFIX,
    _FAILED_REFUSAL_LIFECYCLE_SUFFIX as _FAILED_REFUSAL_LIFECYCLE_SUFFIX,
    derive_expected_group_a_state_history as derive_expected_group_a_state_history,
    canonical_attempt_category as canonical_attempt_category,
    _raw_attempts as _raw_attempts,
    derive_observed_retry_disposition as derive_observed_retry_disposition,
    derive_observed_group_a_contract_category as derive_observed_group_a_contract_category,
    derive_forced_tail_policy as derive_forced_tail_policy,
    derive_observed_cleanup_disposition as derive_observed_cleanup_disposition,
    _safe_sequence as _safe_sequence,
    group_a_public_context as group_a_public_context,
)


class GroupAContractViolation(ValueError):
    """Raised when real evidence differs from the independent case table."""


def verify_parent_settlement_contract(entry, evidence) -> None:
    """Verify the one parent-owned cleanup slot without rejoining Group A."""

    observed = dict(evidence.observed_fields)
    events = dict(evidence.observed_product_events)
    expected_raw = (("failure", "cleanup_limitation", "process_settlement"),)
    raw_attempts = _raw_attempts(
        tuple(observed.get("raw_worker_outcomes", ())),
        tuple(observed.get("raw_worker_categories", ())),
        tuple(observed.get("raw_worker_boundaries", ())),
    )
    parent_facts = tuple(observed.get("parent_observed_attempt_facts", ()))
    attempt_ids = tuple(observed.get("attempt_ids", ()))
    checks = (
        (
            entry.semantic_group == "PARENT_SETTLEMENT"
            and entry.case_id == "parent_settlement_cleanup_limitation_no_retry",
            "catalog identity",
        ),
        (len(attempt_ids) == 1 and len(set(attempt_ids)) == 1, "attempt identity"),
        (raw_attempts == expected_raw, "raw parent failure"),
        (
            tuple(fact[0] for fact in parent_facts) == attempt_ids
            and tuple(tuple(fact[1:]) for fact in parent_facts) == raw_attempts,
            "parent raw authority",
        ),
        (
            tuple(observed.get("child_local_exception_states", ()))
            == ("not_observable_at_parent_attempt_boundary",),
            "child-local explicit absence",
        ),
        (
            tuple(observed.get("wire_failure_notice_states", ()))
            == ("not_observable_at_parent_attempt_boundary",),
            "wire explicit absence",
        ),
        (
            tuple(observed.get("public_projection_facts", ())) == raw_attempts,
            "public projection consistency",
        ),
        (
            tuple(observed.get("authority_attempt_failures", ()))
            == (("cleanup_limitation", "process_settlement"),),
            "authority failure",
        ),
        (observed.get("authority_attempt_count") == 1, "attempt count"),
        (observed.get("retry_observed") is False, "retry absence"),
        (
            observed.get("retry_disposition")
            == "retry_not_observed_after_parent_settlement_failure",
            "retry disposition",
        ),
        (
            tuple(observed.get("scenario_injection_intents", ())) == ("cleanup",)
            and tuple(observed.get("canonical_attempt_categories", ()))
            == ("cleanup",)
            and tuple(observed.get("scenario_contract_categories", ()))
            == ("matched",),
            "scenario classification",
        ),
        (
            tuple(observed.get("interpreted_evidence_origins", ()))
            == ("parent_attempt_settlement",),
            "parent origin",
        ),
        (observed.get("cleanup_disposition") == "limited", "cleanup disposition"),
        (observed.get("final_projection_category") == "refused", "projection"),
        (observed.get("observed_contract_category") == "refused", "category"),
        (
            tuple(events.get("preparation_state_history", ()))
            == ("unprepared", "preparing", "refused", "settled"),
            "lifecycle",
        ),
        (
            all(
                observed.get(field) is None
                for field in (
                    "forced_tail_signal",
                    "forced_tail_pid",
                    "forced_tail_returncode",
                    "forced_tail_stdout_closed",
                )
            ),
            "forced-tail absence",
        ),
    )
    for passed, label in checks:
        if not passed:
            raise GroupAContractViolation(f"parent-settlement {label} mismatch")


def verify_group_a_contract(entry, evidence) -> None:
    """Verify independent runtime, lifecycle, and projection expectations."""

    contract = GROUP_A_CONTRACTS.get(entry.case_id)
    if contract is None:
        raise GroupAContractViolation("Group-A case is absent from the closed contract")
    observed = dict(evidence.observed_fields)
    events = dict(evidence.observed_product_events)
    history = tuple(events.get("preparation_state_history", ()))
    attempt_ids = tuple(observed.get("attempt_ids", ()))
    resource_ids = tuple(observed.get("resource_ids", ()))
    raw_outcomes = tuple(observed.get("raw_worker_outcomes", ()))
    raw_categories = tuple(observed.get("raw_worker_categories", ()))
    raw_boundaries = tuple(observed.get("raw_worker_boundaries", ()))
    parent_facts = tuple(observed.get("parent_observed_attempt_facts", ()))
    child_states = tuple(observed.get("child_local_exception_states", ()))
    wire_states = tuple(observed.get("wire_failure_notice_states", ()))
    public_facts = tuple(observed.get("public_projection_facts", ()))
    raw_attempts = _raw_attempts(
        raw_outcomes, raw_categories, raw_boundaries
    )
    canonical_categories = tuple(
        canonical_attempt_category(*raw) for raw in raw_attempts
    )
    attempt_sequences = tuple(
        tuple(observed.get(field, ()))
        for field in (
            "raw_worker_outcomes",
            "raw_worker_categories",
            "raw_worker_boundaries",
            "parent_observed_attempt_facts",
            "child_local_exception_states",
            "wire_failure_notice_states",
            "public_projection_facts",
            "scenario_injection_intents",
            "canonical_attempt_outcomes",
            "canonical_attempt_categories",
            "scenario_contract_categories",
        )
    )
    expected_failures = tuple(
        (category, boundary)
        for outcome, category, boundary in raw_attempts
        if outcome == "failure"
    )
    maximum_attempts = observed.get("maximum_attempts")
    derived_retry = derive_observed_retry_disposition(
        raw_outcomes, raw_categories, raw_boundaries, history
    )
    derived_category = derive_observed_group_a_contract_category(
        raw_outcomes,
        raw_categories,
        raw_boundaries,
        history,
        str(observed.get("final_projection_category")),
        maximum_attempts if isinstance(maximum_attempts, int) else 0,
    )
    checks = (
        (
            all(
                len(sequence) == len(contract.intents)
                for sequence in (attempt_ids, resource_ids, *attempt_sequences)
            ),
            "attempt count",
        ),
        (len(set(attempt_ids)) == len(attempt_ids), "attempt identity"),
        (
            tuple(fact[0] for fact in parent_facts) == attempt_ids,
            "parent attempt identity",
        ),
        (
            tuple(tuple(fact[1:]) for fact in parent_facts) == raw_attempts,
            "parent raw authority",
        ),
        (
            public_facts == raw_attempts,
            "public projection consistency",
        ),
        (
            set(child_states) == {"not_observable_at_parent_attempt_boundary"},
            "child-local explicit absence",
        ),
        (
            set(wire_states) == {"not_observable_at_parent_attempt_boundary"},
            "wire explicit absence",
        ),
        (raw_outcomes == contract.raw_outcomes, "raw worker outcome"),
        (raw_categories == contract.raw_categories, "raw worker category"),
        (raw_boundaries == contract.raw_boundaries, "raw worker boundary"),
        (
            tuple(observed.get("scenario_injection_intents", ()))
            == contract.intents,
            "scenario intent",
        ),
        (
            tuple(observed.get("canonical_attempt_outcomes", ()))
            == raw_outcomes,
            "canonical outcome",
        ),
        (
            tuple(observed.get("canonical_attempt_categories", ()))
            == canonical_categories,
            "canonical category",
        ),
        (
            tuple(observed.get("scenario_contract_categories", ()))
            == tuple("matched" for _ in contract.intents),
            "scenario contract",
        ),
        (
            tuple(observed.get("authority_attempt_failures", ()))
            == expected_failures,
            "authority attempt failures",
        ),
        (
            observed.get("authority_attempt_count")
            == history.count("preparing")
            == len(attempt_ids),
            "authority attempt count",
        ),
        (
            tuple(observed.get("failure_sources", ()))
            == tuple(category for category, _boundary in expected_failures),
            "failure source",
        ),
        (
            observed.get("final_projection_category") == contract.projection,
            "final projection",
        ),
        (
            observed.get("cleanup_disposition")
            == derive_observed_cleanup_disposition(raw_categories),
            "cleanup disposition",
        ),
        (
            observed.get("retry_disposition") == derived_retry,
            "retry disposition",
        ),
    )
    for passed, label in checks:
        if not passed:
            raise GroupAContractViolation(f"Group-A {label} mismatch")

    expected_history = derive_expected_group_a_state_history(
        raw_attempts, contract.projection
    )
    if expected_history is None or history != expected_history:
        if contract.projection == "released":
            label = "release lifecycle"
        elif raw_outcomes and raw_outcomes[-1] == "success":
            label = "healthy refusal"
        else:
            label = "failed refusal"
        raise GroupAContractViolation(f"Group-A {label} is unproved")

    category_checks = (
        (
            observed.get("observed_contract_category") == derived_category,
            "observed contract category",
        ),
        (
            derived_category == entry.expected_contract_category,
            "expected contract category",
        ),
    )
    for passed, label in category_checks:
        if not passed:
            raise GroupAContractViolation(f"Group-A {label} mismatch")

    tail_required, force_kill = derive_forced_tail_policy(raw_categories)
    if tail_required:
        signal_name = observed.get("forced_tail_signal")
        expected_returncode = -9 if force_kill else -15
        expected_signal = "SIGKILL" if force_kill else "SIGTERM"
        if not (
            observed.get("forced_tail_stdout_closed") is True
            and isinstance(observed.get("forced_tail_pid"), int)
            and observed["forced_tail_pid"] > 0
            and signal_name == expected_signal
            and observed.get("forced_tail_returncode") == expected_returncode
        ):
            raise GroupAContractViolation("Group-A forced-tail lifecycle mismatch")
    elif any(
        observed.get(field) is not None
        for field in (
            "forced_tail_signal",
            "forced_tail_pid",
            "forced_tail_returncode",
            "forced_tail_stdout_closed",
        )
    ):
        raise GroupAContractViolation("Group-A unexpected forced-tail evidence")
