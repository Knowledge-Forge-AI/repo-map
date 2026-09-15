from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from repomap_test_support.test_cov5g_r1_characterization import (
    Condition,
    RequestObservation,
    RequestOutcome,
)
from repomap_test_support.test_cov5k_r2_timing_qualification import (
    CANCELLATION_REQUEST_TIMING_CLAIM,
    NON_SUCCESS_MANIFEST_LIMIT,
    TimingQualificationDisposition,
    TimingQualificationReceipt,
    TimingRuntimeIdentity,
    build_non_success_manifest,
    decide_timing_qualification,
    verify_portable_observation,
    verify_timing_qualification_acceptance,
)


def _identity(**changes: str) -> TimingRuntimeIdentity:
    values = {
        "os_family": "SyntheticOS",
        "os_release": "1.0",
        "machine_architecture": "synthetic64",
        "python_implementation": "CPython",
        "python_version": "3.13.15",
        "psycopg_version": "3.2.12",
        "psycopg_implementation": "c",
        "libpq_version": "180004",
        "postgresql_server_version": "160014",
        "transport_class": "loopback_tcp",
    }
    values.update(changes)
    return TimingRuntimeIdentity(**values)


def _receipt(identity: TimingRuntimeIdentity) -> TimingQualificationReceipt:
    return TimingQualificationReceipt(
        claim=CANCELLATION_REQUEST_TIMING_CLAIM,
        phase_id="SYNTHETIC-TIMING-QUALIFICATION1",
        outcome="A",
        runtime_identity=identity,
        receipt_digest="a" * 64,
    )


def _observation(
    *,
    cohort: str,
    condition: Condition,
    case_number: int,
    request_outcome: RequestOutcome = RequestOutcome.SUCCESS,
    operation_outcome: str = "query_canceled",
) -> RequestObservation:
    return RequestObservation(
        cohort=cohort,
        condition=condition,
        case_number=case_number,
        request_elapsed_ms=25.125,
        request_outcome=request_outcome,
        operation_elapsed_ms=475.125,
        operation_outcome=operation_outcome,
        request_settled=True,
        operation_settled=True,
        close_eligible=True,
        close_count=1,
        backend_disappeared=True,
        cleanup_succeeded=True,
        projection_order="request_first",
    )


def _campaign(
    non_success: RequestOutcome | None = None,
    *,
    operation_outcome: str = "query_canceled",
) -> tuple[RequestObservation, ...]:
    observations = tuple(
        _observation(
            cohort=cohort,
            condition=condition,
            case_number=case_number,
            request_outcome=(
                non_success
                if non_success is not None
                and cohort == "A"
                and condition is Condition.QUIET
                and case_number == 1
                else RequestOutcome.SUCCESS
            ),
            operation_outcome=operation_outcome,
        )
        for cohort in ("A", "B")
        for condition in Condition
        for case_number in range(1, 51)
    )
    assert len(observations) == 500
    return observations


def test_matching_accepted_identity_accepts_500_successes() -> None:
    identity = _identity()
    decision = decide_timing_qualification(identity, _receipt(identity))

    assessment = verify_timing_qualification_acceptance(
        decision,
        _campaign(),
    )

    assert decision.disposition is TimingQualificationDisposition.QUALIFIED
    assert assessment.timing_acceptance_applied is True
    assert assessment.timing_qualification_accepted is True
    assert assessment.non_success_count == 0


def test_portable_safety_accepts_ordinary_completion() -> None:
    observation = replace(
        _campaign()[0],
        operation_outcome="ordinary_completion",
    )

    assert verify_portable_observation(observation) is observation


@pytest.mark.parametrize(
    "outcome",
    (
        RequestOutcome.TIMEOUT,
        RequestOutcome.TRANSPORT_FAILURE,
        RequestOutcome.CENSORED,
    ),
    ids=("timeout", "transport_failure", "censored"),
)
def test_matching_accepted_identity_rejects_each_non_success(
    outcome: RequestOutcome,
) -> None:
    identity = _identity()
    decision = decide_timing_qualification(identity, _receipt(identity))

    with pytest.raises(AssertionError, match=outcome.value):
        verify_timing_qualification_acceptance(
            decision,
            _campaign(outcome),
        )


def test_matching_accepted_identity_rejects_ordinary_completion() -> None:
    identity = _identity()
    decision = decide_timing_qualification(identity, _receipt(identity))
    observations = _campaign()
    observations = (
        replace(observations[0], operation_outcome="ordinary_completion"),
        *observations[1:],
    )

    with pytest.raises(AssertionError, match="ordinary_completion"):
        verify_timing_qualification_acceptance(decision, observations)


def test_unqualified_identity_cannot_earn_timing_credit() -> None:
    decision = decide_timing_qualification(_identity(), None)

    assessment = verify_timing_qualification_acceptance(
        decision,
        _campaign(),
    )

    assert decision.disposition is TimingQualificationDisposition.UNQUALIFIED
    assert assessment.timing_acceptance_applied is False
    assert assessment.timing_qualification_accepted is None


@pytest.mark.parametrize(
    "receipt",
    (
        replace(
            _receipt(_identity()),
            runtime_identity=_identity(os_release="2.0"),
        ),
        replace(_receipt(_identity()), receipt_digest="a" * 63),
        replace(
            _receipt(_identity()),
            claim=CANCELLATION_REQUEST_TIMING_CLAIM + "-changed",
        ),
        replace(_receipt(_identity()), outcome="B"),
        replace(_receipt(_identity()), phase_id=""),
    ),
    ids=(
        "runtime_identity",
        "receipt_digest",
        "claim",
        "outcome",
        "phase_id",
    ),
)
def test_timing_decision_requires_exact_receipt_match(
    receipt: TimingQualificationReceipt,
) -> None:
    decision = decide_timing_qualification(_identity(), receipt)

    assert decision.disposition is TimingQualificationDisposition.UNQUALIFIED
    assert decision.accepted_receipt_phase_id is None
    assert decision.accepted_receipt_digest is None


def test_timing_acceptance_requires_exact_sample_count() -> None:
    decision = decide_timing_qualification(_identity(), None)

    with pytest.raises(AssertionError, match="sample count changed"):
        verify_timing_qualification_acceptance(
            decision,
            _campaign()[:-1],
        )


def test_unqualified_non_success_is_retained_as_characterization() -> None:
    decision = decide_timing_qualification(_identity(), None)
    observations = _campaign(RequestOutcome.TIMEOUT)

    assessment = verify_timing_qualification_acceptance(
        decision,
        observations,
    )

    assert assessment.sample_count == 500
    assert assessment.non_success_count == 1
    assert assessment.timing_qualification_accepted is None
    assert observations[0].request_outcome is RequestOutcome.TIMEOUT


def test_unqualified_ordinary_completion_is_retained_as_characterization() -> None:
    decision = decide_timing_qualification(_identity(), None)
    observations = _campaign()
    observations = (
        replace(observations[0], operation_outcome="ordinary_completion"),
        *observations[1:],
    )

    assessment = verify_timing_qualification_acceptance(
        decision,
        observations,
    )
    manifest = build_non_success_manifest(observations)

    assert assessment.timing_acceptance_applied is False
    assert assessment.timing_qualification_accepted is None
    assert assessment.non_success_count == 1
    assert manifest.total_non_successes == 1
    assert manifest.entries[0].request_outcome == RequestOutcome.SUCCESS.value
    assert manifest.entries[0].operation_outcome == "ordinary_completion"


@pytest.mark.parametrize(
    ("observation", "field"),
    (
        (replace(_campaign()[0], request_settled=False), "request_settled"),
        (replace(_campaign()[0], operation_settled=False), "operation_settled"),
        (replace(_campaign()[0], close_eligible=False), "close_eligible"),
        (replace(_campaign()[0], close_count=0), "close_count"),
        (replace(_campaign()[0], close_count=2), "close_count"),
        (replace(_campaign()[0], backend_disappeared=False), "backend_disappeared"),
        (replace(_campaign()[0], cleanup_succeeded=False), "cleanup_succeeded"),
    ),
    ids=(
        "request_not_settled",
        "operation_not_settled",
        "close_ineligible",
        "not_closed",
        "closed_twice",
        "backend_present",
        "cleanup_failed",
    ),
)
def test_portable_safety_rejects_each_structural_failure(
    observation: RequestObservation,
    field: str,
) -> None:
    with pytest.raises(AssertionError, match=field):
        verify_portable_observation(observation)


def test_pre_observation_decision_is_frozen() -> None:
    identity = _identity()
    decision = decide_timing_qualification(identity, _receipt(identity))

    with pytest.raises(FrozenInstanceError):
        setattr(decision, "disposition", TimingQualificationDisposition.UNQUALIFIED)


def test_observations_cannot_promote_unqualified_runtime() -> None:
    decision = decide_timing_qualification(_identity(), None)

    assessment = verify_timing_qualification_acceptance(
        decision,
        _campaign(),
    )

    assert decision.disposition is TimingQualificationDisposition.UNQUALIFIED
    assert assessment.timing_qualification_accepted is None


def test_non_success_manifest_is_bounded_and_public_safe() -> None:
    secret = "postgresql://private-user:private-password@private-host/db"
    observations = tuple(
        replace(
            item,
            request_outcome=RequestOutcome.TRANSPORT_FAILURE,
            operation_outcome=secret,
        )
        for item in _campaign()
    )

    manifest = build_non_success_manifest(observations)
    rendered = manifest.to_json()

    assert manifest.total_non_successes == 500
    assert len(manifest.entries) == NON_SUCCESS_MANIFEST_LIMIT
    assert manifest.omitted_non_successes == 500 - NON_SUCCESS_MANIFEST_LIMIT
    assert "request_transport_failure" in rendered
    assert "private-user" not in rendered
    assert "private-password" not in rendered
    assert "private-host" not in rendered
    assert len(rendered) < 8_000
