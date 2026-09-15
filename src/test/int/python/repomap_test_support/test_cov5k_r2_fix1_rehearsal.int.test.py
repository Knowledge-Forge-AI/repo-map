"""Bounded executable rehearsal of the corrected qualification model."""

from __future__ import annotations

from pathlib import Path

import pytest

from repomap_test_support.test_cov5k_r2_fix1_qualification import (
    create_draft,
    freeze_manifest,
    open_observations,
    validate_draft,
    verify_rehearsal,
)
from repomap_test_support.test_cov5k_r2_fix1_rehearsal import (
    bounded_rehearsal_case_ids,
    run_bounded_rehearsal,
)


REPOSITORY_ROOT = Path(__file__).parents[5]
pytestmark = pytest.mark.requires_build_profile


def test_bounded_model_rehearsal_is_complete_and_unqualified():
    frozen = freeze_manifest(validate_draft(create_draft()))
    selected = bounded_rehearsal_case_ids(frozen.entries)

    results = run_bounded_rehearsal(
        REPOSITORY_ROOT,
        frozen,
        open_observations(frozen),
    )
    sealed = verify_rehearsal(frozen, selected, results)

    assert len(selected) == 40
    assert {item.case_id for item in results} == set(selected)
    assert all(item.model_rehearsal_only for item in results)
    assert all(item.qualification_status == "unqualified" for item in results)
    assert all(
        item.purpose == "qualification_model_rehearsal"
        for item in results
    )
    assert sealed.model_rehearsal_only
    assert sealed.qualification_status == "unqualified"

    group_a = [item for item in results if item.semantic_group == "A"]
    group_h = [item for item in results if item.semantic_group == "H"]
    group_k = [item for item in results if item.semantic_group == "K"]
    assert len(group_a) == 9
    assert len(group_h) == 8
    assert len(group_k) == 12
    assert all(dict(item.observed_fields)["third_attempt_absent"] for item in group_a)
    assert all(dict(item.observed_fields)["host_process_count"] == 0 for item in group_h)
    assert all(dict(item.observed_fields)["shell"] is False for item in group_k)
    psql_load = next(item for item in group_k if item.condition_id == "K06")
    psql_observed = dict(psql_load.observed_fields)
    argv = psql_observed["argv"]
    assert isinstance(argv, tuple)
    assert argv[-2:] == ("-f", "rows.sql")
    assert psql_observed["nested_psql_intent_count"] == 1
    assert psql_observed["execution_disposition"] == (
        "bounded_operation_completed"
    )
