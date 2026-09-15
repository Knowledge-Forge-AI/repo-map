from __future__ import annotations

from contextlib import nullcontext
import json
from pathlib import Path
from typing import TypedDict
import tempfile
import warnings

import psycopg
import pytest

from repomap_test_support.postgres_harness import (
    active_or_new_postgres_session,
    require_postgres_binaries,
    temporary_postgres,
)
from repomap_test_support.test_cov5g_r1_characterization import (
    Condition,
    PROTOCOL,
    RequestObservation,
    aggregate,
    verify_source_freeze,
)
from repomap_test_support.test_cov5g_r1_load import (
    BoundedConditionLoad,
    ExactContainerHandle,
)
from repomap_test_support.test_cov5g_r1_measurement import (
    run_configured_observation,
    run_direct_observation,
)
from repomap_test_support.test_cov5k_r2_observer_protocol import (
    ADR_0046_EXPECTATIONS,
    FROZEN_THRESHOLDS_MS,
    POLICY_DIGEST,
    SOURCE_MANIFEST_DIGEST,
    OperationAuthority,
    QualificationPlan,
    verify_product_observation,
    verify_enacted_operations,
    verify_qualification_plan,
    verify_source_freeze as verify_successor_source_freeze,
)
from repomap_test_support.test_cov5k_r2_timing_qualification import (
    TimingQualificationReceipt,
    build_non_success_manifest,
    capture_timing_runtime_identity,
    classify_postgres_transport,
    decide_timing_qualification,
    verify_portable_observation,
    verify_timing_qualification_acceptance,
)
from scale28_observer_deadlines import DEFAULT_OBSERVER_DEADLINE_POLICY


_REPOSITORY_ROOT = Path(__file__).resolve().parents[6]
_ACCEPTED_CANCELLATION_TIMING_RECEIPT: TimingQualificationReceipt | None = None


class _ConnectionParameters(TypedDict):
    host: str
    port: int
    user: str
    dbname: str
    password: str


def _parameters(postgres) -> _ConnectionParameters:
    return {
        "host": postgres.host,
        "port": postgres.port,
        "user": postgres.user,
        "dbname": postgres.database,
        "password": postgres.password,
    }


def _aggregate_json(
    observations: tuple[RequestObservation, ...],
) -> dict[str, object]:
    result = aggregate(observations)
    successful = result.successful_request_ms
    operation = result.operation_ms
    return {
        "sample_count": result.sample_count,
        "successes": result.successes,
        "timeouts": result.timeouts,
        "transport_failures": result.transport_failures,
        "censored": result.censored,
        "request_success_ms": {
            "min": round(min(successful), 3) if successful else None,
            "median": round(result.percentile(50), 3) if successful else None,
            "p90": round(result.percentile(90), 3) if successful else None,
            "p95": round(result.percentile(95), 3) if successful else None,
            "p99": round(result.percentile(99), 3) if successful else None,
            "max": round(max(successful), 3) if successful else None,
        },
        "operation_ms": {
            "min": round(min(operation), 3),
            "median": round(result.percentile(50, operation=True), 3),
            "p95": round(result.percentile(95, operation=True), 3),
            "max": round(max(operation), 3),
        },
        "threshold_exceedances": dict(result.threshold_exceedances),
        "cleanup_failures": result.cleanup_failures,
    }


def _assert_valid(observation: RequestObservation) -> None:
    verify_portable_observation(observation)


def _successor_plan() -> QualificationPlan:
    return QualificationPlan(
        expected_values=ADR_0046_EXPECTATIONS.as_tuple(),
        operation_authorities=tuple(
            OperationAuthority(
                f"{cohort}:{condition.value}:{case_number}",
                f"request:{cohort}:{condition.value}:{case_number}",
            )
            for cohort in ("A", "B")
            for condition in Condition
            for case_number in range(
                1,
                PROTOCOL.operations_per_condition + 1,
            )
        ),
        thresholds_ms=FROZEN_THRESHOLDS_MS,
        thresholds_frozen_before_observation=True,
        valid_observations_removed=0,
        uses_product_expected_mapping=False,
        accepts_any_positive_request_timeout=False,
    )


def test_cov5g_r1_two_cohort_configured_cancellation_request_tail() -> None:
    require_postgres_binaries()
    with pytest.raises(ValueError, match="production source changed"):
        verify_source_freeze(_REPOSITORY_ROOT)
    verify_successor_source_freeze(_REPOSITORY_ROOT)
    assert (
        verify_product_observation(DEFAULT_OBSERVER_DEADLINE_POLICY)
        == ADR_0046_EXPECTATIONS
    )
    qualification_plan = verify_qualification_plan(_successor_plan())
    observations: list[RequestObservation] = []

    with temporary_postgres() as postgres:
        parameters = _parameters(postgres)
        parameters_dict: dict[str, object] = dict(parameters)
        active_session, context = active_or_new_postgres_session()
        assert context is None
        container = ExactContainerHandle(
            runtime=active_session.config.runtime,
            name=active_session.harness.container_name,
        )
        with psycopg.connect(
            **parameters,
            autocommit=True,
            application_name="cov5g_r1_admin",
        ) as admin:
            timing_identity = capture_timing_runtime_identity(
                postgresql_server_version=str(admin.info.server_version),
                transport_class=classify_postgres_transport(postgres.host),
            )
            timing_decision = decide_timing_qualification(
                timing_identity,
                _ACCEPTED_CANCELLATION_TIMING_RECEIPT,
            )
            for cohort in ("A", "B"):
                for condition in Condition:
                    with tempfile.TemporaryDirectory(
                        prefix="cov5g-r1-load-"
                    ) as temporary_root:
                        load = (
                            BoundedConditionLoad(
                                condition,
                                parameters=parameters_dict,
                                filesystem_root=Path(temporary_root),
                                container=container,
                            )
                            if condition
                            in {
                                Condition.CPU,
                                Condition.FILESYSTEM_CONTAINER,
                                Condition.CONNECTION_CHURN,
                            }
                            else nullcontext()
                        )
                        with load:
                            for case_number in range(
                                1,
                                PROTOCOL.operations_per_condition + 1,
                            ):
                                if condition is Condition.CONFIGURED_SESSION:
                                    observation = run_configured_observation(
                                        parameters_dict,
                                        admin,
                                        cohort=cohort,
                                        case_number=case_number,
                                    )
                                else:
                                    observation = run_direct_observation(
                                        parameters_dict,
                                        admin,
                                        cohort=cohort,
                                        condition=condition,
                                        case_number=case_number,
                                    )
                                _assert_valid(observation)
                                observations.append(observation)

    selected = tuple(observations)
    assert len(selected) == PROTOCOL.total_operations == 500
    assert len(
        {
            (item.cohort, item.condition, item.case_number)
            for item in selected
        }
    ) == 500
    verify_enacted_operations(
        qualification_plan,
        (
            f"{item.cohort}:{item.condition.value}:{item.case_number}"
            for item in selected
        ),
    )
    assert qualification_plan.valid_observations_removed == 0
    timing_assessment = verify_timing_qualification_acceptance(
        timing_decision,
        selected,
    )
    report = {
        "historical_cohort_digest": PROTOCOL.digest,
        "successor_policy_digest": POLICY_DIGEST,
        "successor_source_digest": SOURCE_MANIFEST_DIGEST,
        "timing_qualification": {
            "disposition": timing_decision.disposition.value,
            "accepted_receipt_phase_id": (
                timing_decision.accepted_receipt_phase_id
            ),
            "accepted_receipt_digest": timing_decision.accepted_receipt_digest,
            "timing_acceptance_applied": (
                timing_assessment.timing_acceptance_applied
            ),
            "timing_qualification_accepted": (
                timing_assessment.timing_qualification_accepted
            ),
            "non_success_count": timing_assessment.non_success_count,
        },
        "runtime_identity": timing_identity.to_mapping(),
        "cohorts": {
            cohort: _aggregate_json(
                tuple(item for item in selected if item.cohort == cohort)
            )
            for cohort in ("A", "B")
        },
        "conditions": {
            condition.value: _aggregate_json(
                tuple(
                    item
                    for item in selected
                    if item.condition is condition
                )
            )
            for condition in Condition
        },
        "combined": _aggregate_json(selected),
        "valid_removed": 0,
    }
    combined = report["combined"]
    assert isinstance(combined, dict)
    assert combined["sample_count"] == 500
    if timing_assessment.timing_acceptance_applied:
        assert combined["successes"] == 500
        assert combined["timeouts"] == 0
        assert combined["transport_failures"] == 0
        assert combined["censored"] == 0
    assert report["valid_removed"] == 0
    if (
        not timing_assessment.timing_acceptance_applied
        and timing_assessment.non_success_count > 0
    ):
        warnings.warn(
            "Unqualified runtime cancellation timing drift observed: "
            f"{timing_assessment.non_success_count} non-successes; manifest: "
            f"{build_non_success_manifest(selected).to_json()}",
            UserWarning,
            stacklevel=2,
        )
    print(
        "SCALE28_FIX12_R2_FIX2_REQUEST_PROTOCOL_RESULT="
        + json.dumps(report, sort_keys=True)
    )
