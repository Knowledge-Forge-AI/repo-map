from __future__ import annotations
from dataclasses import replace
import pytest
from repomap_test_support.test_cov5k_r2_fix1_qualification import DraftManifest, IntegrityError, build_result, create_draft, freeze_manifest, open_observations, parameter_digest, validate_draft, verify_result
from pathlib import Path
from repomap_test_support.test_cov5k_r2_fix1_qualification import verify_rehearsal
from repomap_test_support.test_cov5k_r2_fix1_rehearsal import _run_group_k

@pytest.fixture
def frozen():
    return freeze_manifest(validate_draft(create_draft()))


def _artifact(frozen, case_id: str):
    entry = next(item for item in frozen.entries if item.case_id == case_id)
    values: dict[str, object] = {
        "primary_result_category": "observed",
        "secondary_limitations": (),
        "host_process_count": 0,
        "nested_psql_intent_count": 0,
        "cleanup_disposition": "none",
        "argv": ("fixed", case_id),
        "effective_argv": ("fixed", case_id),
        "argv_execution_digest": "0" * 64,
        "shell": False,
        "timeout_seconds": 10,
        "host_executable": "fixed",
        "disposable_resource_owned": True,
        "execution_disposition": "bounded_operation_completed",
        "returncode": 0,
        "execution_parameter_digest": parameter_digest(entry),
    }
    observed = tuple((field, values[field]) for field in entry.observation_schema)
    return build_result(
        frozen,
        open_observations(frozen),
        entry,
        observed,
        enacted_parameters=entry.parameter_values,
        started_monotonic_ns=1,
        completed_monotonic_ns=2,
    )


def _draft_with_entries(draft, entries):
    return DraftManifest(
        draft.registration_id,
        tuple(entries),
        draft.thresholds,
        draft.tolerances,
    )


@pytest.mark.parametrize(
    ("case_id", "message"),
    (
        ("G-request-origin-0001", "aggregate Group G result"),
        ("H01-psycopg_success", "aggregate Group H process zero"),
    ),
)
def test_aggregate_evidence_cannot_satisfy_per_case_authority(
    frozen,
    case_id,
    message,
):
    artifact = _artifact(frozen, case_id)
    mutation = replace(
        artifact,
        observed_fields=artifact.observed_fields + (("aggregate", True),),
    )

    with pytest.raises(IntegrityError, match=message):
        verify_result(frozen, mutation)


def test_removed_valid_observation_is_rejected(frozen):
    artifact = _artifact(frozen, "G-request-origin-0001")
    observed = dict(artifact.observed_fields)
    observed["primary_result_category"] = "removed"

    with pytest.raises(
        IntegrityError,
        match="expected or removed value used as observation",
    ):
        verify_result(
            frozen,
            replace(artifact, observed_fields=tuple(observed.items())),
        )


def test_duplicate_result_cannot_be_reused_across_cases(frozen):
    artifact = _artifact(frozen, "G-request-origin-0001")

    with pytest.raises(
        IntegrityError,
        match="duplicate result reused across cases",
    ):
        verify_rehearsal(
            frozen,
            ("G-request-origin-0001", "G-request-origin-0002"),
            (artifact, artifact),
        )


def test_missing_and_unexpected_results_fail_closed(frozen):
    artifact = _artifact(frozen, "G-request-origin-0001")

    with pytest.raises(IntegrityError, match="missing result"):
        verify_rehearsal(
            frozen,
            ("G-request-origin-0001", "G-request-origin-0002"),
            (artifact,),
        )
    with pytest.raises(IntegrityError, match="unexpected result"):
        verify_rehearsal(frozen, (), (artifact,))


def test_duplicate_observed_field_is_rejected_before_mapping(frozen):
    entry = next(
        item
        for item in frozen.entries
        if item.case_id == "G-request-origin-0001"
    )
    observed = (
        ("primary_result_category", "observed"),
        ("secondary_limitations", ()),
        ("host_process_count", 0),
        ("nested_psql_intent_count", 0),
        ("cleanup_disposition", "none"),
        ("primary_result_category", "conflicting"),
    )
    with pytest.raises(IntegrityError, match="duplicate observed field"):
        build_result(
            frozen,
            open_observations(frozen),
            entry,
            observed,
            enacted_parameters=entry.parameter_values,
            started_monotonic_ns=1,
            completed_monotonic_ns=2,
        )


def test_group_g_observation_cannot_be_reused_for_another_schedule(frozen):
    entries = [
        item
        for item in frozen.entries
        if item.case_id in {
            "G-request-origin-0001",
            "G-request-origin-0002",
        }
    ]
    first, second = entries
    values: dict[str, object] = {
        "primary_result_category": "observed",
        "secondary_limitations": (),
        "host_process_count": 0,
        "nested_psql_intent_count": 0,
        "cleanup_disposition": "none",
        "execution_parameter_digest": parameter_digest(first),
    }
    observed = tuple(
        (field, values[field]) for field in first.observation_schema
    )
    artifact = build_result(
        frozen,
        open_observations(frozen),
        second,
        observed,
        enacted_parameters=second.parameter_values,
        started_monotonic_ns=1,
        completed_monotonic_ns=2,
    )

    with pytest.raises(
        IntegrityError,
        match="Group G enacted parameter evidence changed",
    ):
        verify_result(frozen, artifact)


def test_executor_cannot_omit_or_replace_an_enacted_parameter(frozen):
    entry = next(
        item
        for item in frozen.entries
        if item.case_id == "G-request-origin-0001"
    )
    changed = (("schedule", "request-origin"),)
    values: dict[str, object] = {
        "primary_result_category": "observed",
        "secondary_limitations": (),
        "host_process_count": 0,
        "nested_psql_intent_count": 0,
        "cleanup_disposition": "none",
        "execution_parameter_digest": parameter_digest(entry),
    }
    observed = tuple(
        (field, values[field]) for field in entry.observation_schema
    )

    with pytest.raises(IntegrityError, match="parameter tuple changed"):
        build_result(
            frozen,
            open_observations(frozen),
            entry,
            observed,
            enacted_parameters=changed,
            started_monotonic_ns=1,
            completed_monotonic_ns=2,
        )


def test_group_k_rehearsal_argv_cannot_change_subcommand(frozen, tmp_path):
    entry = next(
        item for item in frozen.entries if item.case_id == "K01-backup"
    )
    observed = dict(_run_group_k(Path.cwd(), tmp_path, entry))
    observed["argv"] = ("repomap-kg", "unrelated", "--help")
    artifact = build_result(
        frozen,
        open_observations(frozen),
        entry,
        tuple((field, observed[field]) for field in entry.observation_schema),
        enacted_parameters=entry.parameter_values,
        started_monotonic_ns=1,
        completed_monotonic_ns=2,
    )

    with pytest.raises(IntegrityError, match="Group K observed argv changed"):
        verify_result(frozen, artifact)


@pytest.mark.parametrize(
    "mutation",
    (
        {"argv_execution_digest": "f" * 64},
        {
            "returncode": 7,
            "execution_disposition": "bounded_operation_rejected",
        },
    ),
)
def test_group_k_execution_receipt_cannot_be_substituted(
    frozen,
    tmp_path,
    mutation,
):
    entry = next(
        item for item in frozen.entries if item.case_id == "K01-backup"
    )
    observed = dict(_run_group_k(Path.cwd(), tmp_path, entry))
    observed.update(mutation)
    artifact = build_result(
        frozen,
        open_observations(frozen),
        entry,
        tuple((field, observed[field]) for field in entry.observation_schema),
        enacted_parameters=entry.parameter_values,
        started_monotonic_ns=1,
        completed_monotonic_ns=2,
    )

    with pytest.raises(IntegrityError, match="Group K execution receipt changed"):
        verify_result(frozen, artifact)
