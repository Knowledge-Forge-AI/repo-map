from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict

import psycopg

from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)
from repomap_test_support.test_cov5g_r1_containment import (
    ParentAction,
    process_containment_cases,
)
from repomap_test_support.test_cov5g_r1_process import (
    ChildConfiguration,
    run_process_case,
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
    verify_source_freeze,
)
from scale28_observer_deadlines import DEFAULT_OBSERVER_DEADLINE_POLICY


_REPOSITORY_ROOT = Path(__file__).resolve().parents[6]


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


def test_cov5g_r1_twenty_process_containment_feasibility_cases() -> None:
    require_postgres_binaries()
    cases = process_containment_cases()
    verify_source_freeze(_REPOSITORY_ROOT)
    assert (
        verify_product_observation(DEFAULT_OBSERVER_DEADLINE_POLICY)
        == ADR_0046_EXPECTATIONS
    )
    qualification_plan = verify_qualification_plan(
        QualificationPlan(
            expected_values=ADR_0046_EXPECTATIONS.as_tuple(),
            operation_authorities=tuple(
                OperationAuthority(
                    case.case_id,
                    f"process-request:{case.case_id}",
                )
                for case in cases
            ),
            thresholds_ms=FROZEN_THRESHOLDS_MS,
            thresholds_frozen_before_observation=True,
            valid_observations_removed=0,
            uses_product_expected_mapping=False,
            accepts_any_positive_request_timeout=False,
        )
    )
    results = []

    with temporary_postgres() as postgres:
        parameters = _parameters(postgres)
        with psycopg.connect(
            host=parameters["host"],
            port=parameters["port"],
            user=parameters["user"],
            dbname=parameters["dbname"],
            password=parameters["password"],
            autocommit=True,
            application_name="cov5g_r1_process_parent",
        ) as admin:
            for index, case in enumerate(cases, start=1):
                configuration = ChildConfiguration(
                    case=case,
                    application_name=f"cov5g_r1_process_{index:02d}",
                    host=parameters["host"],
                    port=parameters["port"],
                    user=parameters["user"],
                    dbname=parameters["dbname"],
                    password=parameters["password"],
                )
                result = run_process_case(configuration, admin)
                assert result.child_started is True
                assert result.backend_observed is True
                assert result.request_started is True
                assert result.backend_disappeared is True, result
                assert result.descriptor_closed is True
                if case.parent_action is ParentAction.COOPERATIVE_STOP:
                    assert result.cooperative_exit is True
                    assert result.forced_termination is False
                else:
                    assert result.forced_termination is True
                if (
                    case.parent_action
                    is ParentAction.LIVE_DESCENDANT_REFUSAL
                ):
                    assert result.descendant_refused is True
                results.append(result)

    assert len(results) == 20
    assert len({result.case_id for result in results}) == 20
    verify_enacted_operations(
        qualification_plan,
        (result.case_id for result in results),
    )
    summary = {
        "successor_policy_digest": POLICY_DIGEST,
        "successor_source_digest": SOURCE_MANIFEST_DIGEST,
        "cases": len(results),
        "cooperative_exits": sum(
            result.cooperative_exit for result in results
        ),
        "forced_terminations": sum(
            result.forced_termination for result in results
        ),
        "descendant_refusals": sum(
            result.descendant_refused for result in results
        ),
        "backend_disappearances": sum(
            result.backend_disappeared for result in results
        ),
        "descriptor_cleanups": sum(
            result.descriptor_closed for result in results
        ),
    }
    print(
        "SCALE28_FIX12_R2_FIX2_PROCESS_RESULT="
        + json.dumps(summary, sort_keys=True)
    )
