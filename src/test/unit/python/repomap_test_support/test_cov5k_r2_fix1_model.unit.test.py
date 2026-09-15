"""Closed-manifest and lifecycle checks for TEST-COV5K-R2-FIX1."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from repomap_test_support.scale28_fix9_failure_inventory import FORMER_FAILURES
from repomap_test_support.test_cov5k_r2_fix1_catalog import (
    REQUIRED_MANIFEST_GROUPS,
    build_closed_catalog,
)
from repomap_test_support.test_cov5k_r2_fix1_executors import execute_group_a
from repomap_test_support.test_cov5k_r2_fix1_qualification import (
    IntegrityError,
    LifecycleState,
    build_result,
    create_draft,
    freeze_manifest,
    open_observations,
    validate_draft,
    verify_frozen,
)
from repomap_test_support.test_cov5k_r2_fix1_rehearsal import (
    build_runner_registry,
    verify_static_bindings,
)


REPOSITORY_ROOT = Path(__file__).parents[5]


def test_closed_catalog_contains_every_group_before_observation():
    entries = build_closed_catalog()

    assert len(entries) == 1_698
    assert tuple(sorted({item.semantic_group for item in entries})) == tuple(
        sorted(REQUIRED_MANIFEST_GROUPS)
    )
    assert len({item.case_id for item in entries}) == len(entries)
    assert len({item.authority_id for item in entries}) == len(entries)
    assert all(
        item.product_owner_id != item.evidence_executor_id
        for item in entries
    )


def test_group_g_counts_come_from_frozen_parameter_tuples():
    entries = build_closed_catalog()
    group_g = [
        item
        for item in entries
        if item.semantic_group == "G"
        and item.operation_kind == "observer_schedule"
    ]
    counts: dict[str, int] = {}
    for entry in group_g:
        schedule = str(dict(entry.parameter_values)["schedule"])
        counts[schedule] = counts.get(schedule, 0) + 1

    assert counts == {
        "request-origin": 30,
        "request-publication": 30,
        "pre-dispatch-refusal": 12,
        "operation-class": 8,
        "d-op-classification": 12,
        "close-quarantine": 12,
        "cleanup-attempt": 12,
        "terminal-read": 12,
        "triple-fault": 12,
        "three-party": 50,
        "close-under-use": 100,
        "source-causality": 200,
        "terminal-claim": 18,
        "reacquisition": 36,
        "caller-context": 9,
        "final-release": 20,
    }
    assert len({item.parameter_values for item in group_g}) == len(group_g)
    assert (
        len(
            [
                item
                for item in entries
                if item.operation_kind == "former_failure_node"
            ]
        )
        == 14
    )


def test_groups_d_h_and_k_have_independent_typed_authorities():
    entries = build_closed_catalog()
    group_d = [item for item in entries if item.semantic_group == "D"]
    group_h = [item for item in entries if item.semantic_group == "H"]
    group_k = [item for item in entries if item.semantic_group == "K"]

    assert {item.operation_kind for item in group_d} == {
        "runtime_driver_read",
        "process_rss",
        "container_rss",
        "container_rss_equivalence",
        "terminal_read",
    }
    assert len(group_h) == 8
    assert len({item.product_owner_id for item in group_h}) == 5
    assert len({item.evidence_executor_id for item in group_h}) == 8
    assert len(group_k) == 12
    assert len({item.product_owner_id for item in group_k}) == 12
    assert len({item.evidence_executor_id for item in group_k}) == 12
    assert all(
        "rss" not in item.evidence_executor_id
        and "final_release" not in item.evidence_executor_id
        for item in group_k
    )


def test_lifecycle_is_closed_and_restart_invalidates_prior_session():
    draft = create_draft("registration-one")
    validated = validate_draft(draft)
    frozen = freeze_manifest(validated)
    first_session = open_observations(frozen)
    restarted = freeze_manifest(
        validate_draft(create_draft("registration-two"))
    )

    assert draft.state is LifecycleState.DRAFT
    assert validated.state is LifecycleState.VALIDATED
    assert frozen.state is LifecycleState.FROZEN
    assert first_session.state is LifecycleState.OBSERVATION_OPEN
    assert restarted.preregistration_digest != frozen.preregistration_digest
    assert (
        first_session.preregistration_digest
        != restarted.preregistration_digest
    )
    entry = next(
        item
        for item in restarted.entries
        if item.case_id == "G-request-origin-0001"
    )
    observed = (
        ("primary_result_category", "observed"),
        ("secondary_limitations", ()),
        ("host_process_count", 0),
        ("nested_psql_intent_count", 0),
        ("cleanup_disposition", "none"),
    )
    with pytest.raises(
        IntegrityError,
        match="not bound to frozen manifest",
    ):
        build_result(
            restarted,
            first_session,
            entry,
            observed,
            enacted_parameters=entry.parameter_values,
            started_monotonic_ns=1,
            completed_monotonic_ns=2,
        )
    with pytest.raises(FrozenInstanceError):
        frozen.registration_id = "changed"  # type: ignore[misc]
    with pytest.raises(IntegrityError, match="not in draft state"):
        validate_draft(replace(draft, state=LifecycleState.SEALED))
    with pytest.raises(IntegrityError, match="not in validated state"):
        freeze_manifest(
            replace(validated, state=LifecycleState.OBSERVATION_OPEN)
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("thresholds", (("request_deadline_ms", 301),), "threshold changed"),
        ("tolerances", (("rss_bytes", 1),), "tolerance changed"),
    ),
)
def test_post_freeze_policy_change_fails_closed(field, value, message):
    frozen = freeze_manifest(validate_draft(create_draft()))

    with pytest.raises(IntegrityError, match=message):
        verify_frozen(replace(frozen, **{field: value}))


def test_every_owner_and_fixed_runner_resolves_to_the_repository():
    entries = build_closed_catalog()
    registry = build_runner_registry(entries)

    verify_static_bindings(REPOSITORY_ROOT, entries, registry)
    assert set(registry) == {item.fixed_runner_id for item in entries}
    assert {
        item.pytest_node_id
        for item in entries
        if item.pytest_node_id is not None
    } == {item.node_id for item in FORMER_FAILURES}


def test_runner_builders_are_independently_authored_executors():
    registry = build_runner_registry(build_closed_catalog())

    assert all(
        binding.argv_builder.__module__.endswith(
            "test_cov5k_r2_fix1_executors"
        )
        for binding in registry.values()
    )


@pytest.mark.parametrize("executor_name", [
    "test_cov5k_r2_fix1_catalog_administrative.py",
    "test_cov5k_r2_fix1_catalog_runtime.py",
    "test_cov5k_r2_fix1_catalog_storage.py",
    "test_cov5k_r2_fix1_catalog_values.py",
    "test_cov5k_r2_fix1_executor_administrative.py",
    "test_cov5k_r2_fix1_executor_preparation.py",
    "test_cov5k_r2_fix1_executor_runtime.py",
    "test_cov5k_r2_fix1_qualification_records.py",
    "test_cov5k_r2_fix1_qualification_groups.py",
    "test_cov5k_r2_fix1_rehearsal.py",
    "test_cov5k_r2_group_k_container.py",
    "test_cov5k_r2_image_route.py",
])
def test_freeze_binds_test_owned_executor_source(monkeypatch, executor_name):
    before = freeze_manifest(validate_draft(create_draft()))
    executor_path = REPOSITORY_ROOT.joinpath(
        "src/test/support/python/repomap_test_support/",
        executor_name
    ).resolve()
    original = Path.read_bytes

    def changed_bytes(path):
        payload = original(path)
        if path.resolve() == executor_path:
            return payload + b"\n# executor mutation\n"
        return payload

    monkeypatch.setattr(Path, "read_bytes", changed_bytes)
    after = freeze_manifest(validate_draft(create_draft()))

    assert after.source_manifest_digest != before.source_manifest_digest


def test_group_a_complete_cleanup_removes_acquired_resources(tmp_path):
    entry = next(
        item
        for item in build_closed_catalog()
        if item.condition_id == "A02"
    )

    observed = dict(execute_group_a(tmp_path, entry))

    assert observed["cleanup_completed"] is True
    assert observed["descriptor_settled"] is True
    assert not tuple(tmp_path.glob("*.resource"))
