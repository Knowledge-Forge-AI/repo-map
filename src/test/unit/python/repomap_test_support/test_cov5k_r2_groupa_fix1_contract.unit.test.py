from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from repomap_test_support.test_cov5k_r2_fix2_catalog import build_closed_catalog
from repomap_test_support.test_cov5k_r2_fix2_encoding import canonical_digest
from repomap_test_support.test_cov5k_r2_fix2_evidence import (
    ExecutorEvidenceError,
    verify_executor_evidence,
)
from repomap_test_support.test_cov5k_r2_groupa_contract import (
    GROUP_A_CONTRACTS,
    derive_expected_group_a_state_history,
    derive_observed_group_a_contract_category,
)
from repomap_test_support.test_cov5k_r2_fix2_preparation import (
    _EnactedAttempt,
    execute_preparation_state_path,
)
from repomap_test_support.test_cov5k_r2_fix2_preparation_observations import (
    AttemptObservation,
)
from scale28_preparation_worker import (
    PreparationWorkerAttempt,
    PreparationWorkerError,
    PreparationWorkerResult,
)


CASES = (
    "attempt_one_success",
    "resource_failure_second_success",
    "timeout_second_success",
    "two_generic_worker_failures",
    "generic_worker_failure_then_timeout",
    "timeout_then_generic_worker_failure",
    "two_timeouts",
    "retry_gate_refusal",
    "final_refused_projection",
)


def test_corr2_real_group_a_inventory_uses_migrated_ids() -> None:
    entries = build_closed_catalog()
    group_a = tuple(
        entry.case_id
        for entry in sorted(entries, key=lambda item: item.condition_id)
        if entry.semantic_group == "A"
    )
    assert group_a == (
        "attempt_one_success",
        "resource_failure_second_success",
        "timeout_second_success",
        "two_generic_worker_failures",
        "generic_worker_failure_then_timeout",
        "timeout_then_generic_worker_failure",
        "two_timeouts",
        "retry_gate_refusal",
        "final_refused_projection",
    )
    assert len(entries) == 1698
    assert tuple(
        entry.case_id
        for entry in entries
        if entry.semantic_group == "PARENT_SETTLEMENT"
    ) == ("parent_settlement_cleanup_limitation_no_retry",)


def test_corr2_resource_and_source_contract_pairs_are_migrated() -> None:
    resource = GROUP_A_CONTRACTS["resource_failure_second_success"]
    assert resource.raw_categories == ("resource_unavailable", "none")
    assert resource.raw_boundaries == ("container_rss_read", "none")
    assert "two_source_failures" not in GROUP_A_CONTRACTS
    assert "source_failure_then_timeout" not in GROUP_A_CONTRACTS
    assert "timeout_then_source_failure" not in GROUP_A_CONTRACTS
    assert GROUP_A_CONTRACTS[
        "two_generic_worker_failures"
    ].raw_categories == ("worker_failed", "worker_failed")
    assert GROUP_A_CONTRACTS[
        "generic_worker_failure_then_timeout"
    ].raw_categories == ("worker_failed", "preparation_timeout")
    assert GROUP_A_CONTRACTS[
        "timeout_then_generic_worker_failure"
    ].raw_categories == ("preparation_timeout", "worker_failed")
    assert all(
        contract.raw_boundaries == ("worker", "worker")
        for case_id, contract in GROUP_A_CONTRACTS.items()
        if "generic_worker_failure" in case_id
    )

EXPECTED_ATTEMPTS = {
    "attempt_one_success": 1,
    "resource_failure_second_success": 2,
    "timeout_second_success": 2,
    "two_generic_worker_failures": 2,
    "generic_worker_failure_then_timeout": 2,
    "timeout_then_generic_worker_failure": 2,
    "two_timeouts": 2,
    "retry_gate_refusal": 1,
    "final_refused_projection": 1,
}

EXPECTED_RAW = {
    "attempt_one_success": ("none",),
    "resource_failure_second_success": ("resource_unavailable", "none"),
    "timeout_second_success": ("preparation_timeout", "none"),
    "two_generic_worker_failures": ("worker_failed", "worker_failed"),
    "generic_worker_failure_then_timeout": ("worker_failed", "preparation_timeout"),
    "timeout_then_generic_worker_failure": ("preparation_timeout", "worker_failed"),
    "two_timeouts": ("preparation_timeout", "preparation_timeout"),
    "retry_gate_refusal": ("preparation_timeout",),
    "final_refused_projection": ("none",),
}

EXPECTED_CANONICAL = {
    "attempt_one_success": ("success",),
    "resource_failure_second_success": ("resource", "success"),
    "timeout_second_success": ("timeout", "success"),
    "two_generic_worker_failures": ("generic_worker_failure", "generic_worker_failure"),
    "generic_worker_failure_then_timeout": ("generic_worker_failure", "timeout"),
    "timeout_then_generic_worker_failure": ("timeout", "generic_worker_failure"),
    "two_timeouts": ("timeout", "timeout"),
    "retry_gate_refusal": ("timeout",),
    "final_refused_projection": ("success",),
}

EXPECTED_PROJECTION = {
    case: "released" if case in {
        "attempt_one_success",
        "resource_failure_second_success",
        "timeout_second_success",
    } else "refused"
    for case in CASES
}


def _entry(case_id: str):
    return next(
        entry
        for entry in build_closed_catalog()
        if entry.semantic_group == "A" and entry.case_id == case_id
    )


def _field(evidence, name: str, value: object):
    fields = tuple(
        (field, value if field == name else original)
        for field, original in evidence.observed_fields
    )
    if name not in dict(fields):
        fields += ((name, value),)
    return replace(evidence, observed_fields=fields)


def _event(evidence, name: str, value: object):
    events = tuple(
        (field, value if field == name else original)
        for field, original in evidence.observed_product_events
    )
    return replace(evidence, observed_product_events=events)


def _rebind(evidence):
    unsigned = replace(evidence, result_digest="")
    digest = canonical_digest(
        {
            "authority_id": unsigned.authority_id,
            "frozen_parameter_digest": unsigned.frozen_parameter_digest,
            "observed_enacted_parameter_digest": (
                unsigned.observed_enacted_parameter_digest
            ),
            "owner": unsigned.owner_entry_evidence,
            "scenario_program_identity": unsigned.scenario_program_identity,
            "observed_product_events": unsigned.observed_product_events,
            "observed_fields": unsigned.observed_fields,
        }
    )
    return replace(unsigned, result_digest=digest)


@pytest.fixture(scope="module")
def group_a_results(tmp_path_factory):
    root = tmp_path_factory.mktemp("groupa-fix1-contract")
    return {
        case_id: execute_preparation_state_path(root / case_id, _entry(case_id))
        for case_id in CASES
    }


class _SuccessResult(PreparationWorkerResult):
    def __init__(self) -> None:
        pass


class _FailureAttempt(PreparationWorkerAttempt):
    def __init__(self, category: str, boundary: str) -> None:
        self.category = category
        self.boundary = boundary

    def run(self) -> PreparationWorkerResult:
        raise PreparationWorkerError(
            "public-safe deterministic failure",
            category=self.category,
            boundary=self.boundary,
        )


class _SuccessAttempt(PreparationWorkerAttempt):
    def __init__(self) -> None:
        pass

    def run(self) -> PreparationWorkerResult:
        return _SuccessResult()


def test_unexpected_worker_category_is_not_laundered() -> None:
    attempt = _EnactedAttempt(_FailureAttempt("worker_failed", "worker"), "resource")
    with pytest.raises(PreparationWorkerError) as captured:
        attempt.run()
    assert (captured.value.category, captured.value.boundary) == (
        "worker_failed",
        "worker",
    )


def test_unexpected_worker_success_has_distinct_contract_category() -> None:
    attempt = _EnactedAttempt(_SuccessAttempt(), "resource")
    with pytest.raises(PreparationWorkerError) as captured:
        attempt.run()
    assert (captured.value.category, captured.value.boundary) == (
        "scenario_contract_mismatch",
        "scenario_injection",
    )


def test_interpreted_evidence_origin_follows_worker_report() -> None:
    observations: list[AttemptObservation] = []
    attempt = _EnactedAttempt(
        _FailureAttempt("worker_failed", "worker"),
        "resource",
        observations,
    )
    with pytest.raises(PreparationWorkerError):
        attempt.run()
    assert observations[0].interpreted_evidence_origin == "worker_failure_notice"
    assert observations[0].scenario_intent == "resource"
    assert observations[0].raw_category == "worker_failed"


@pytest.mark.parametrize("case_id", CASES)
def test_each_case_rejects_wrong_attempt_count(group_a_results, case_id: str) -> None:
    evidence = group_a_results[case_id]
    attempt_ids = tuple(dict(evidence.observed_fields)["attempt_ids"])
    wrong = attempt_ids[:-1] if len(attempt_ids) == 2 else attempt_ids + ("extra",)
    broken = _rebind(_field(evidence, "attempt_ids", wrong))
    with pytest.raises(ExecutorEvidenceError, match="attempt count"):
        verify_executor_evidence(_entry(case_id), broken)


@pytest.mark.parametrize("case_id", CASES)
def test_each_case_rejects_wrong_raw_failure_sequence(
    group_a_results, case_id: str
) -> None:
    evidence = group_a_results[case_id]
    wrong = tuple("unrecognized" for _ in EXPECTED_RAW[case_id])
    broken = _rebind(_field(evidence, "raw_worker_categories", wrong))
    with pytest.raises(ExecutorEvidenceError, match="parent raw authority"):
        verify_executor_evidence(_entry(case_id), broken)


@pytest.mark.parametrize("case_id", CASES)
def test_each_case_rejects_wrong_canonical_sequence(
    group_a_results, case_id: str
) -> None:
    evidence = group_a_results[case_id]
    wrong = tuple("unexpected_raw_category" for _ in EXPECTED_CANONICAL[case_id])
    broken = _rebind(_field(evidence, "canonical_attempt_categories", wrong))
    with pytest.raises(ExecutorEvidenceError, match="canonical category"):
        verify_executor_evidence(_entry(case_id), broken)


@pytest.mark.parametrize("case_id", CASES)
def test_each_case_rejects_wrong_projection(group_a_results, case_id: str) -> None:
    evidence = group_a_results[case_id]
    wrong = "refused" if EXPECTED_PROJECTION[case_id] == "released" else "released"
    broken = _rebind(_field(evidence, "final_projection_category", wrong))
    with pytest.raises(ExecutorEvidenceError, match="final projection"):
        verify_executor_evidence(_entry(case_id), broken)


def test_a10_requires_ordered_healthy_refusal(group_a_results) -> None:
    evidence = group_a_results["final_refused_projection"]
    broken = _event(
        evidence,
        "preparation_state_history",
        ("unprepared", "preparing", "refused", "settled"),
    )
    with pytest.raises(ExecutorEvidenceError, match="healthy refusal"):
        verify_executor_evidence(_entry("final_refused_projection"), _rebind(broken))


@pytest.mark.parametrize(
    "mutation",
    (
        "missing_unprepared",
        "unknown_state",
        "duplicate_settled",
        "duplicate_worker_settled",
        "swapped_observation_states",
        "released_then_refused",
    ),
)
def test_digest_rebound_lifecycle_mutations_are_rejected(
    group_a_results, mutation: str
) -> None:
    evidence = group_a_results["attempt_one_success"]
    history = tuple(
        dict(evidence.observed_product_events)["preparation_state_history"]
    )
    if mutation == "missing_unprepared":
        mutated = history[1:]
    elif mutation == "unknown_state":
        mutated = history[:2] + ("future_state",) + history[2:]
    elif mutation == "duplicate_settled":
        mutated = history + ("settled",)
    elif mutation == "duplicate_worker_settled":
        index = history.index("worker_settled")
        mutated = history[:index + 1] + history[index:]
    elif mutation == "swapped_observation_states":
        first = history.index("observation_received")
        second = history.index("observation_acknowledged")
        mutable = list(history)
        mutable[first], mutable[second] = mutable[second], mutable[first]
        mutated = tuple(mutable)
    else:
        settled = history.index("settled")
        mutated = history[:settled] + ("refused",) + history[settled:]
    broken = _rebind(_event(evidence, "preparation_state_history", mutated))
    with pytest.raises(ExecutorEvidenceError, match="lifecycle"):
        verify_executor_evidence(_entry("attempt_one_success"), broken)


def test_expected_lifecycle_history_fails_closed_for_impossible_family() -> None:
    assert derive_expected_group_a_state_history(
        (
            ("success", "none", "none"),
            ("failure", "worker_failed", "worker"),
        ),
        "refused",
    ) is None


def test_runtime_category_fails_closed_for_malformed_lifecycle() -> None:
    assert derive_observed_group_a_contract_category(
        ("success",),
        ("none",),
        ("none",),
        ("unprepared", "preparing", "future_state", "settled"),
        "released",
        2,
    ) == "unrecognized"


@pytest.mark.parametrize(
    "case_id",
    ("attempt_one_success", "final_refused_projection", "retry_gate_refusal"),
)
def test_valid_lifecycle_families_remain_accepted(group_a_results, case_id: str):
    verify_executor_evidence(_entry(case_id), group_a_results[case_id])


@pytest.mark.parametrize("case_id", CASES)
def test_all_real_group_a_histories_remain_accepted(
    group_a_results, case_id: str
) -> None:
    verify_executor_evidence(_entry(case_id), group_a_results[case_id])


def test_scoped_assertions_retain_public_safe_group_a_context() -> None:
    root = Path("src/test/unit/python/repomap_test_support")
    sources = (
        (root / "test_cov5k_r2_fix3_enactment.unit.test.py").read_text(),
        (root / "test_cov5k_r2_fix3_review2_reproductions.unit.test.py").read_text(),
    )
    assert all("group_a_public_context" in source for source in sources)
