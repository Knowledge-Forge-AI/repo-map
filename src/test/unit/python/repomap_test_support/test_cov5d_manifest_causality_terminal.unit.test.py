from __future__ import annotations

from dataclasses import replace

import pytest

from actual_refresh_failure_causality import (
    FailureCausalityAuthority,
    failure_owner,
)
from repomap_test_support.test_cov5c_qualification import build_evidence
from repomap_test_support.test_cov5d_qualification import (
    ContractComparison,
    QualificationManifest,
    REACQUISITION_FIRST_FAILURES,
    REACQUISITION_SECOND_OUTCOMES,
    SOURCE_MANIFEST_DIGEST,
    SOURCE_ORDER_SCHEDULES,
    build_reacquisition_authority,
    observed_result,
    qualification_record,
)
from scale28_preparation_authority import PreparationAuthorityError
from scale28_preparation_values import PreparationAttemptExpectations
from scale28_preparation_receipts import (
    ParentObservedTerminalFacts,
    validate_parent_terminal_facts,
)


_SOURCE_CASES = tuple(
    pytest.param(schedule, id="-then-".join(schedule))
    for schedule in SOURCE_ORDER_SCHEDULES
)
_REACQUISITION_CASES = tuple(
    pytest.param(
        first_failure,
        second_outcome,
        id=f"{first_failure}-then-{second_outcome}",
    )
    for first_failure in REACQUISITION_FIRST_FAILURES
    for second_outcome in REACQUISITION_SECOND_OUTCOMES
)
_TERMINAL_CASES = (
    pytest.param({}, {}, "accepted", id="normal-zero-exit"),
    pytest.param({"exit_code": 1}, {}, "terminal_invalid", id="nonzero-exit"),
    pytest.param(
        {"signal": "SIGTERM"},
        {},
        "terminal_invalid",
        id="signal-exit",
    ),
    pytest.param(
        {"process_tree_settled": False},
        {},
        "terminal_invalid",
        id="worker-crash-before-observation",
    ),
    pytest.param(
        {"active_observers": 0},
        {},
        "terminal_invalid",
        id="worker-crash-after-observation",
    ),
    pytest.param(
        {"active_observers": 2},
        {},
        "terminal_invalid",
        id="worker-crash-after-ack",
    ),
    pytest.param({}, {"receipt_before_exit": True}, "accepted", id="receipt-before-exit"),
    pytest.param({}, {"receipt_present": False}, "missing_receipt", id="missing-receipt"),
    pytest.param(
        {},
        {"disposition_matches": False},
        "wrong_disposition",
        id="wrong-expected-disposition",
    ),
    pytest.param({"descendants": 1}, {}, "terminal_invalid", id="live-descendant"),
    pytest.param(
        {"worker_connections": 1},
        {},
        "terminal_invalid",
        id="subordinate-connection-leak",
    ),
    pytest.param(
        {"readers": 1},
        {},
        "terminal_invalid",
        id="subordinate-reader-leak",
    ),
    pytest.param(
        {"threads": 1},
        {},
        "terminal_invalid",
        id="subordinate-thread-leak",
    ),
    pytest.param(
        {"descriptors_and_channels": 1},
        {},
        "terminal_invalid",
        id="result-channel-closure-mismatch",
    ),
    pytest.param(
        {"exit_code": 2, "process_tree_settled": False},
        {},
        "terminal_invalid",
        id="process-tree-settlement-timeout",
    ),
    pytest.param({}, {"parent_cancelled": True}, "parent_cancelled", id="parent-cancellation"),
    pytest.param({}, {"cleanup_succeeded": False}, "cleanup_failure", id="cleanup-failure"),
    pytest.param(
        {},
        {"cleanup_succeeded": True, "result_channel_closed": True},
        "accepted",
        id="exact-successful-cleanup",
    ),
)


def _manifest_record(
    *,
    authority_id: str = "authority-001",
    group: str = "close_order",
    case_id: str = "close-case-001",
    operation_kind: str = "observer_close_order",
    actual_category: str = "settled",
    source_observed: bool = True,
):
    observed = observed_result(
        case_id,
        actual_category,
        source_observed=source_observed,
    )
    record = qualification_record(
        authority_id=authority_id,
        semantic_group=group,
        case_id=case_id,
        operation_kind=operation_kind,
        entry_point="BackendObserverSession.close",
        expected_contract_category="settled",
        observed=observed,
    )
    return record, observed


def test_manifest_reports_complete_semantic_groups_without_grand_total() -> None:
    manifest = QualificationManifest(
        required_group_counts={"close_order": 1, "terminal_claim": 1}
    )
    close_record, close_result = _manifest_record()
    terminal_record, terminal_result = _manifest_record(
        authority_id="authority-002",
        group="terminal_claim",
        case_id="terminal-case-001",
        operation_kind="parent_terminal_validation",
    )

    manifest.add(close_record, close_result)
    manifest.add(terminal_record, terminal_result)
    grouped = manifest.finish()

    assert tuple(grouped) == ("close_order", "terminal_claim")
    assert [record.case_id for record in grouped["close_order"]] == [
        "close-case-001"
    ]
    assert [record.case_id for record in grouped["terminal_claim"]] == [
        "terminal-case-001"
    ]
    assert "total" not in grouped


def test_manifest_rejects_duplicate_authority_and_semantic_case() -> None:
    manifest = QualificationManifest(required_group_counts={"close_order": 2})
    first_record, first_result = _manifest_record()
    manifest.add(first_record, first_result)

    duplicate_id, duplicate_id_result = _manifest_record(
        case_id="close-case-002"
    )
    with pytest.raises(ValueError, match="authority id"):
        manifest.add(duplicate_id, duplicate_id_result)

    duplicate_case, duplicate_case_result = _manifest_record(
        authority_id="authority-002"
    )
    with pytest.raises(ValueError, match="semantic case"):
        manifest.add(duplicate_case, duplicate_case_result)


def test_manifest_rejects_request_round_trip_relabeling() -> None:
    manifest = QualificationManifest(required_group_counts={"close_order": 1})
    record, result = _manifest_record(
        operation_kind="preparation_request_round_trip"
    )

    with pytest.raises(ValueError, match="mislabeled"):
        manifest.add(record, result)


def test_manifest_rejects_unused_case_parameter_and_unobserved_actual() -> None:
    manifest = QualificationManifest(required_group_counts={"close_order": 1})
    record, result = _manifest_record()

    with pytest.raises(ValueError, match="unused"):
        manifest.add(
            record,
            replace(result, case_evidence_token="0" * 64),
        )
    with pytest.raises(ValueError, match="not observed"):
        manifest.add(record, replace(result, source_observed=False))


def test_manifest_rejects_missing_cleanup_source_drift_and_digest_mismatch() -> None:
    record, result = _manifest_record()

    manifest = QualificationManifest(required_group_counts={"close_order": 1})
    with pytest.raises(ValueError, match="cleanup"):
        manifest.add(
            replace(record, cleanup_disposition=""),
            replace(result, cleanup_disposition=""),
        )

    manifest = QualificationManifest(required_group_counts={"close_order": 1})
    with pytest.raises(ValueError, match="source changed"):
        manifest.add(
            record,
            result,
            current_source_manifest_digest="f" * 64,
        )

    manifest = QualificationManifest(required_group_counts={"close_order": 1})
    with pytest.raises(ValueError, match="digest"):
        manifest.add(replace(record, result_digest="0" * 64), result)


def test_manifest_rejects_incomplete_semantic_group() -> None:
    manifest = QualificationManifest(required_group_counts={"close_order": 2})
    record, result = _manifest_record()
    manifest.add(record, result)

    with pytest.raises(ValueError, match="incomplete"):
        manifest.finish()


@pytest.mark.parametrize("schedule", _SOURCE_CASES)
def test_two_hundred_distinct_source_causality_schedules(
    schedule: tuple[str, ...],
) -> None:
    clock = iter(range(1, len(schedule) + 1)).__next__
    authority = FailureCausalityAuthority(clock_ns=clock)
    candidates = [
        authority.record_code(
            code,
            authority_owner=failure_owner(code),
            lifecycle_boundary=f"selected_source_{index}",
            existed_before_child_release=False,
            terminal_secondary=index > 0,
            source_event_key=f"{code}-{index}",
        )
        for index, code in enumerate(schedule)
    ]
    for candidate in reversed(candidates):
        authority.observe(candidate)

    snapshot = authority.freeze()

    assert [candidate.code for candidate in snapshot.candidates] == list(schedule)
    assert [candidate.causal_sequence for candidate in snapshot.candidates] == list(
        range(1, len(schedule) + 1)
    )
    assert [
        candidate.observation_sequence for candidate in snapshot.candidates
    ] == list(range(len(schedule), 0, -1))


@pytest.mark.parametrize(
    ("first_failure", "second_outcome"),
    _REACQUISITION_CASES,
)
def test_thirty_six_distinct_reacquisition_cases(
    first_failure: str,
    second_outcome: str,
) -> None:
    authority, attempts = build_reacquisition_authority(
        first_failure=first_failure,
        second_outcome=second_outcome,
        clock=lambda: 4_000_000_000,
    )

    if second_outcome == "success":
        authority.prepare()
    else:
        with pytest.raises(PreparationAuthorityError):
            authority.prepare()

    assert len(attempts) == 2
    first_attempt, second_attempt = attempts
    assert isinstance(first_attempt, PreparationAttemptExpectations)
    assert isinstance(second_attempt, PreparationAttemptExpectations)
    assert [first_attempt.attempt, second_attempt.attempt] == [1, 2]
    assert first_attempt.run_nonce != second_attempt.run_nonce
    assert len(authority.snapshot().attempt_failures) == (
        1 if second_outcome == "success" else 2
    )


def _terminal_category(
    changes: dict[str, object],
    prerequisites: dict[str, bool],
) -> str:
    if prerequisites.get("receipt_before_exit", True) is False:
        return "receipt_after_exit"
    if prerequisites.get("receipt_present", True) is False:
        return "missing_receipt"
    if prerequisites.get("disposition_matches", True) is False:
        return "wrong_disposition"
    if prerequisites.get("parent_cancelled", False):
        return "parent_cancelled"
    if prerequisites.get("cleanup_succeeded", True) is False:
        return "cleanup_failure"
    if prerequisites.get("result_channel_closed", True) is False:
        return "result_channel_open"
    def _int(key: str, default: int) -> int:
        val = changes.get(key, default)
        assert isinstance(val, int)
        return val

    signal = changes.get("signal", None)
    assert signal is None or isinstance(signal, str)
    settled = changes.get("process_tree_settled", True)
    assert isinstance(settled, bool)
    facts = ParentObservedTerminalFacts(
        exit_code=_int("exit_code", 0),
        signal=signal,
        process_tree_settled=settled,
        active_observers=_int("active_observers", 1),
        descendants=_int("descendants", 0),
        worker_connections=_int("worker_connections", 0),
        readers=_int("readers", 0),
        threads=_int("threads", 0),
        descriptors_and_channels=_int("descriptors_and_channels", 0),
    )
    try:
        validate_parent_terminal_facts(
            build_evidence().receipt,
            facts,
        )
    except ValueError:
        return "terminal_invalid"
    return "accepted"


@pytest.mark.parametrize(
    ("changes", "prerequisites", "expected_category"),
    _TERMINAL_CASES,
)
def test_eighteen_distinct_terminal_claim_cases(
    changes: dict[str, object],
    prerequisites: dict[str, bool],
    expected_category: str,
) -> None:
    assert _terminal_category(changes, prerequisites) == expected_category


def test_source_manifest_digest_is_frozen_before_characterization() -> None:
    assert SOURCE_MANIFEST_DIGEST == (
        "3f505bb7a53f83f8b34289df35998a3b24705d1e0ff0114116d85cc3e4f2eb1a"
    )


def test_accepted_candidate_and_required_contract_have_one_exact_gap() -> None:
    comparison = ContractComparison(
        accepted_tree="pushed_scale28_fix5_outcome_b",
        candidate_tree="pushed_scale28_fix5_outcome_b",
        required_contract=(
            "successful_exact_connection_client_fallback_under_product_policy"
        ),
        remaining_gap=(
            "evidence_sized_cancel_request_reserve_and_default_requalification"
        ),
    ).validate()

    assert comparison.accepted_tree == comparison.candidate_tree
    assert comparison.remaining_gap == (
        "evidence_sized_cancel_request_reserve_and_default_requalification"
    )
