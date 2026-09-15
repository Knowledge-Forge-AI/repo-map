from __future__ import annotations
from dataclasses import replace
import pytest
from repomap_test_support.test_cov5k_r2_fix1_qualification import DraftManifest, IntegrityError, build_result, create_draft, freeze_manifest, open_observations, parameter_digest, validate_draft, verify_frozen, verify_result

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


def test_duplicate_authority_id_is_rejected():
    draft = create_draft()
    entries = list(draft.entries)
    entries[1] = replace(entries[1], authority_id=entries[0].authority_id)

    with pytest.raises(IntegrityError, match="duplicate authority ID"):
        validate_draft(_draft_with_entries(draft, entries))


def test_duplicate_semantic_case_is_rejected():
    draft = create_draft()
    entries = list(draft.entries)
    entries[1] = replace(entries[1], case_id=entries[0].case_id)

    with pytest.raises(IntegrityError, match="duplicate semantic case"):
        validate_draft(_draft_with_entries(draft, entries))


@pytest.mark.parametrize("group", ("A", "H", "K"))
def test_missing_group_manifest_is_rejected(group):
    draft = create_draft()
    entries = [
        item for item in draft.entries if item.semantic_group != group
    ]

    with pytest.raises(IntegrityError, match="missing group manifest"):
        validate_draft(_draft_with_entries(draft, entries))


def test_group_k_cannot_be_mapped_to_final_release_or_rss():
    draft = create_draft()
    entries = list(draft.entries)
    index = next(
        index
        for index, item in enumerate(entries)
        if item.semantic_group == "K"
    )
    entries[index] = replace(
        entries[index],
        evidence_executor_id="fix1.executor.g.final_release_rss",
    )

    with pytest.raises(
        IntegrityError,
        match="Group K mapped to unrelated executor",
    ):
        validate_draft(_draft_with_entries(draft, entries))


def test_post_freeze_authority_addition_is_rejected(frozen):
    added = replace(
        frozen.entries[-1],
        case_id="caller-added-case",
        authority_id="caller-added-authority",
    )

    with pytest.raises(IntegrityError, match="unexpected registered case"):
        verify_frozen(replace(frozen, entries=frozen.entries + (added,)))


def test_post_freeze_validity_rule_change_is_rejected(frozen):
    changed = replace(
        frozen.entries[0],
        validity_rule="caller-selected-validity",
    )

    with pytest.raises(IntegrityError, match="closed registered case changed"):
        verify_frozen(
            replace(
                frozen,
                entries=(changed, *frozen.entries[1:]),
            )
        )


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({"case_id": "caller-ordinal-9999"}, "unexpected result"),
        (
            {"product_owner_id": "fix1.executor.g.request-origin"},
            "product owner does not match frozen case",
        ),
        (
            {"evidence_executor_id": "fix1.owner.g.request-origin"},
            "executor does not match frozen case",
        ),
        ({"enacted_parameters": ()}, "parameter tuple changed"),
        ({"parameter_digest": ""}, "parameter tuple changed"),
        ({"result_digest": "0" * 64}, "result digest mismatch"),
        (
            {"source_manifest_digest": "0" * 64},
            "source policy protocol or runtime drift",
        ),
        (
            {"policy_digest": "0" * 64},
            "source policy protocol or runtime drift",
        ),
        (
            {"protocol_digest": "0" * 64},
            "source policy protocol or runtime drift",
        ),
        (
            {"runtime_identity_digest": "0" * 64},
            "source policy protocol or runtime drift",
        ),
    ),
)
def test_result_identity_and_drift_mutations_fail_closed(
    frozen,
    changes,
    message,
):
    artifact = _artifact(frozen, "G-request-origin-0001")

    with pytest.raises(IntegrityError, match=message):
        verify_result(frozen, replace(artifact, **changes))


def test_display_label_cannot_relabel_a_case(frozen):
    artifact = _artifact(frozen, "G-request-origin-0001")
    mutation = replace(
        artifact,
        observed_fields=artifact.observed_fields
        + (("display_label", "caller-selected"),),
    )

    with pytest.raises(IntegrityError, match="observation schema changed"):
        verify_result(frozen, mutation)


def test_expected_value_cannot_be_inserted_as_observation(frozen):
    artifact = _artifact(frozen, "G-request-origin-0001")
    mutation = replace(
        artifact,
        observed_fields=artifact.observed_fields
        + (("expected", "passed"),),
    )

    with pytest.raises(
        IntegrityError,
        match="expected value inserted as observation",
    ):
        verify_result(frozen, mutation)
