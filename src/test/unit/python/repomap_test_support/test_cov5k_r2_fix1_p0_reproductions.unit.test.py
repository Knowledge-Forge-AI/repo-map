"""Failure-first reproductions for the rejected R2 qualification model."""

from __future__ import annotations

from dataclasses import replace

import pytest

from repomap_test_support.test_cov5k_r2_fix1_qualification import (
    IntegrityError,
    build_result,
    create_draft,
    freeze_manifest,
    open_observations,
    parameter_digest,
    predecessor_accepts_p0,
    validate_draft,
    verify_result,
)


@pytest.fixture
def model():
    frozen = freeze_manifest(validate_draft(create_draft()))
    return frozen, open_observations(frozen)


def _result(model, case_id: str):
    frozen, session = model
    entry = next(
        item for item in frozen.entries if item.case_id == case_id
    )
    observed = tuple(
        (field, _observed_value(field, entry))
        for field in entry.observation_schema
    )
    return frozen, build_result(
        frozen,
        session,
        entry,
        observed,
        enacted_parameters=entry.parameter_values,
        started_monotonic_ns=10,
        completed_monotonic_ns=20,
    )


def _observed_value(field: str, entry):
    if field in {"host_process_count", "nested_psql_intent_count"}:
        return 0
    if field == "secondary_limitations":
        return ()
    if field in {
        "cleanup_started",
        "cleanup_completed",
        "cleanup_limited",
        "worker_settled",
        "descriptor_settled",
        "third_attempt_absent",
        "shell",
        "disposable_resource_owned",
    }:
        return False
    if field == "argv":
        return ("fixed",)
    if field == "effective_argv":
        return ("fixed",)
    if field == "argv_execution_digest":
        return "0" * 64
    if field == "execution_parameter_digest":
        return parameter_digest(entry)
    if field == "timeout_seconds":
        return 10
    if field in {"attempt_ids", "resource_ids", "failure_sources"}:
        return ()
    return "observed"


def test_p0_1_predecessor_conflates_owner_and_executor(model):
    frozen, artifact = _result(model, "attempt_one_success")
    mutation = replace(
        artifact,
        product_owner_id=artifact.evidence_executor_id,
    )

    assert predecessor_accepts_p0("P0-1", (mutation,))
    with pytest.raises(
        IntegrityError,
        match="product owner does not match frozen case",
    ):
        verify_result(frozen, mutation)


def test_p0_2_predecessor_allows_one_result_to_be_relabelled(model):
    frozen, artifact = _result(model, "G-request-origin-0001")
    second = next(
        item
        for item in frozen.entries
        if item.case_id == "G-request-origin-0002"
    )
    mutation = replace(
        artifact,
        authority_id=second.authority_id,
        case_id=second.case_id,
        condition_id=second.condition_id,
        product_owner_id=second.product_owner_id,
    )
    ordinal_expansion = replace(
        artifact,
        observed_fields=artifact.observed_fields
        + (("caller_ordinal", 30), ("aggregate_count", 30)),
    )

    assert predecessor_accepts_p0("P0-2", (artifact, mutation))
    assert predecessor_accepts_p0("P0-2", (ordinal_expansion,))
    with pytest.raises(IntegrityError, match="parameter tuple changed"):
        verify_result(frozen, mutation)
    with pytest.raises(IntegrityError, match="observation schema changed"):
        verify_result(frozen, ordinal_expansion)


def test_p0_3_predecessor_accepts_claim_without_semantic_evidence(model):
    frozen, artifact = _result(
        model, "parent_settlement_cleanup_limitation_no_retry"
    )
    mutation = replace(
        artifact,
        observed_fields=(
            ("primary_result_category", "refused"),
            ("secondary_limitations", ()),
            ("host_process_count", 0),
            ("nested_psql_intent_count", 0),
            ("cleanup_disposition", "complete"),
            ("resource_settled", True),
            ("forced_tail_signal", "SIGKILL"),
            ("retry_disposition", "admitted"),
        ),
    )

    assert predecessor_accepts_p0("P0-3", (mutation,))
    with pytest.raises(IntegrityError, match="observation schema changed"):
        verify_result(frozen, mutation)


def test_p0_4_predecessor_maps_independent_owner_to_final_release(model):
    frozen, group_d = _result(model, "D-driver-psycopg-success")
    _, group_h = _result(model, "H01-psycopg_success")
    _, group_k = _result(model, "K01-backup")
    missing_typed_dimensions = replace(group_d, enacted_parameters=())
    aggregate_zero = replace(
        group_h,
        observed_fields=group_h.observed_fields + (("aggregate", True),),
    )
    unrelated_k = replace(
        group_k,
        evidence_executor_id="fix1.executor.g.final_release",
    )

    assert predecessor_accepts_p0(
        "P0-4",
        (missing_typed_dimensions, aggregate_zero, unrelated_k),
    )
    with pytest.raises(IntegrityError, match="parameter tuple changed"):
        verify_result(frozen, missing_typed_dimensions)
    with pytest.raises(
        IntegrityError,
        match="aggregate Group H process zero",
    ):
        verify_result(frozen, aggregate_zero)
    with pytest.raises(
        IntegrityError,
        match="executor does not match frozen case",
    ):
        verify_result(frozen, unrelated_k)
