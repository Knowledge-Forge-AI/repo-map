from __future__ import annotations

from pathlib import Path

import pytest

from repomap_test_support.test_cov5g_r1_characterization import (
    Condition,
    FIX1_COMMIT,
    FROZEN_POLICY_DIGEST,
    PROTOCOL,
    RequestObservation,
    RequestOutcome,
    aggregate,
    nearest_rank,
    verify_source_freeze,
)
from repomap_test_support.test_cov5f_characterization import (
    ACCEPTED_POLICY,
    FROZEN_ACCEPTED_POLICY_DIGEST,
    OPERATION_CLASS_CASES,
)


_REPOSITORY_ROOT = Path(__file__).resolve().parents[5]


def _observation(
    case_number: int,
    request_ms: float,
    outcome: RequestOutcome = RequestOutcome.SUCCESS,
) -> RequestObservation:
    return RequestObservation(
        cohort="A",
        condition=Condition.QUIET,
        case_number=case_number,
        request_elapsed_ms=request_ms,
        request_outcome=outcome,
        operation_elapsed_ms=request_ms + 450,
        operation_outcome="query_canceled",
        request_settled=True,
        operation_settled=True,
        close_eligible=True,
        close_count=1,
        backend_disappeared=True,
        cleanup_succeeded=True,
        projection_order="request_first",
    )


def test_r1_freezes_fix1_source_policy_and_protocol() -> None:
    assert FIX1_COMMIT == "46f826a321ea158e2edb1ed13f1d6ee5e560567c"
    with pytest.raises(ValueError, match="production source changed"):
        verify_source_freeze(_REPOSITORY_ROOT)
    assert FROZEN_POLICY_DIGEST == FROZEN_ACCEPTED_POLICY_DIGEST
    assert ACCEPTED_POLICY.digest == FROZEN_POLICY_DIGEST
    assert PROTOCOL.total_operations == 500
    assert len(Condition) == 5
    assert PROTOCOL.thresholds_ms == (
        40,
        80,
        120,
        160,
        200,
        250,
        500,
        1_000,
        2_000,
    )


@pytest.mark.parametrize(
    ("percentile", "expected"),
    ((50, 3.0), (90, 5.0), (95, 5.0), (99, 5.0), (100, 5.0)),
)
def test_nearest_rank_is_frozen_without_interpolation(
    percentile: int,
    expected: float,
) -> None:
    assert nearest_rank((5.0, 1.0, 4.0, 2.0, 3.0), percentile) == expected


def test_aggregate_counts_limitations_as_every_lower_threshold_exceedance() -> None:
    observations = (
        _observation(1, 20),
        _observation(2, 100),
        _observation(3, 2_000, RequestOutcome.TIMEOUT),
        _observation(4, 2_000, RequestOutcome.TRANSPORT_FAILURE),
        _observation(5, 2_000, RequestOutcome.CENSORED),
    )

    result = aggregate(observations)

    assert result.sample_count == 5
    assert (result.successes, result.timeouts) == (2, 1)
    assert (result.transport_failures, result.censored) == (1, 1)
    assert dict(result.threshold_exceedances)[40] == 4
    assert dict(result.threshold_exceedances)[120] == 3
    assert dict(result.threshold_exceedances)[2_000] == 3
    assert result.rule_of_three(40) is None


def test_zero_exceedance_rule_of_three_uses_all_valid_samples() -> None:
    result = aggregate(
        _observation(index, float(index))
        for index in range(1, 6)
    )

    assert result.sample_count == 5
    assert result.rule_of_three(40) == pytest.approx(0.6)
    assert result.cleanup_failures == 0


def test_operation_class_and_sql_use_remain_independent() -> None:
    cases = {case.operation: case for case in OPERATION_CLASS_CASES}

    assert cases["connection_registration"].operation_class == (
        "connection_startup"
    )
    assert cases["connection_registration"].issues_sql is True
    assert cases["summary_and_identity_validation"].operation_class == (
        "serialization_only"
    )
    assert cases["summary_and_identity_validation"].issues_sql is False
    assert cases["startup_active_summary"].operation_class == "sql_bounded"
    assert cases["startup_active_summary"].issues_sql is True
    assert cases["close_and_request_settlement"].operation_class == "settlement"
    assert cases["close_and_request_settlement"].issues_sql is False
