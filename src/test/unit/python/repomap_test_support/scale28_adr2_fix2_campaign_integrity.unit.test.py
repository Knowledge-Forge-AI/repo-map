from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from repomap_test_support.scale28_adr2_campaign_results import (
    ObservedPreparationCleanup,
    PreparationCaseExpectation,
    PreparationCaseFailure,
    PreparationCaseObservation,
    assert_case_expectation,
    exercise_and_observe_case,
)


def _observation(
    *,
    release_occurred: bool = False,
    terminal_state: str = "settled",
    open_connections: int = 0,
) -> PreparationCaseObservation:
    return PreparationCaseObservation(
        release_occurred=release_occurred,
        state_machine_terminal_state=terminal_state,
        process_exit_code=0,
        process_signal=None,
        cleanup=ObservedPreparationCleanup(
            process_tree_settled=True,
            worker_connection_count=open_connections,
            reader_count=0,
            thread_count=0,
            descriptor_channel_count=0,
        ),
        frame_count=1,
        acknowledgement_count=1,
        receipt_count=0,
        attempt=1,
        generation_class="unit-fixture",
    )


def _raise_failure(
    category: str = "observer_failed",
    boundary: str = "active_observer",
    *,
    secondaries: tuple[str, ...] = (),
) -> None:
    raise PreparationCaseFailure(
        category=category,
        source_boundary=boundary,
        state_machine_terminal_state="settled",
        secondary_categories=secondaries,
    )


def _result(
    *,
    operation=lambda: _raise_failure(),
    observation: PreparationCaseObservation | None = None,
):
    return exercise_and_observe_case(
        case_id="campaign-integrity-001",
        cohort="original_fault",
        scenario="observer_failure",
        operation=operation,
        observe=lambda: observation or _observation(),
    )


def _expectation() -> PreparationCaseExpectation:
    return PreparationCaseExpectation(
        first_causal_category="observer_failed",
        source_boundary="active_observer",
        release_decision="refused",
        state_machine_terminal_state="settled",
        cleanup_complete=True,
    )


def test_structured_failure_is_observed_before_expectation_comparison() -> None:
    result = _result()

    assert_case_expectation(result, _expectation())
    assert result.first_causal_category == "observer_failed"
    assert result.source_boundary == "active_observer"
    assert result.secondary_categories == ()
    assert result.release_decision == "refused"
    assert result.cleanup_complete is True


def test_unrelated_value_error_is_not_accepted_as_a_campaign_rejection() -> None:
    def unrelated_failure() -> None:
        raise ValueError("unrelated parsing bug")

    with pytest.raises(ValueError, match="unrelated parsing bug"):
        _result(operation=unrelated_failure)


def test_right_category_from_wrong_boundary_fails_exact_comparison() -> None:
    result = _result(
        operation=lambda: _raise_failure(
            "observer_failed",
            "receipt_decode",
        )
    )

    with pytest.raises(AssertionError, match="observed result"):
        assert_case_expectation(result, _expectation())


def test_incomplete_cleanup_is_measured_and_fails_expectation() -> None:
    result = _result(observation=_observation(open_connections=1))

    assert result.cleanup_complete is False
    assert result.worker_connection_count == 1
    with pytest.raises(AssertionError, match="observed result"):
        assert_case_expectation(result, _expectation())


def test_release_after_pre_release_failure_fails_expectation() -> None:
    result = _result(observation=_observation(release_occurred=True))

    with pytest.raises(AssertionError, match="observed result"):
        assert_case_expectation(result, _expectation())


def test_secondary_category_cannot_be_substituted_as_primary() -> None:
    result = _result(
        operation=lambda: _raise_failure(
            "cleanup_failed",
            "cleanup_settlement",
            secondaries=("observer_failed",),
        )
    )

    assert result.first_causal_category == "cleanup_failed"
    assert result.secondary_categories == ("observer_failed",)
    with pytest.raises(AssertionError, match="observed result"):
        assert_case_expectation(result, _expectation())


def test_no_emitted_failure_category_cannot_satisfy_fault_expectation() -> None:
    result = _result(operation=lambda: None)

    assert result.first_causal_category == "complete"
    with pytest.raises(AssertionError, match="observed result"):
        assert_case_expectation(result, _expectation())


def test_terminal_state_must_match_the_emitting_failure_authority() -> None:
    with pytest.raises(ValueError, match="terminal state differs"):
        _result(observation=_observation(terminal_state="refused"))


def test_observed_result_is_frozen_and_serializes_no_expectation() -> None:
    result = _result()

    with pytest.raises(FrozenInstanceError):
        result.first_causal_category = "complete"
    projection = result.to_mapping()
    projection["first_causal_category"] = "complete"
    projection["expected_category"] = "observer_failed"
    del projection["source_boundary"]

    assert result.first_causal_category == "observer_failed"
    assert "expected_category" not in result.to_mapping()


def test_cleanup_result_cannot_be_hardcoded_against_measured_counts() -> None:
    result = _result()

    with pytest.raises(ValueError, match="not derived"):
        replace(
            result,
            worker_connection_count=1,
            cleanup_complete=True,
        )
