from __future__ import annotations

from dataclasses import fields
import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from repomap_test_support import test_cov5k_r2_fix2_preparation as preparation
from repomap_test_support.test_cov5k_r2_fix2_catalog import build_closed_catalog
from repomap_test_support.test_cov5k_r2_groupa_contract import (
    GroupAContract,
    GroupAContractViolation,
    verify_group_a_contract,
)


def test_corr2_parent_observed_attempt_fact_is_raw_authority() -> None:
    fact_type = getattr(preparation, "ParentObservedAttemptFact", None)
    bundle_type = getattr(preparation, "AttemptEvidenceLayers", None)
    validator = getattr(preparation, "validate_attempt_evidence_layers", None)
    assert inspect.isclass(fact_type), "ParentObservedAttemptFact must be explicit"
    assert inspect.isclass(bundle_type), "typed evidence bundle must be explicit"
    assert callable(validator), "typed layer validation must be explicit"
    assert fact_type(
        "attempt-1", "failure", "worker_failed", "worker"
    ).category == "worker_failed"


def test_corr2_intent_or_frozen_fact_cannot_substitute_for_parent_fact() -> None:
    required = (
        "ScenarioIntentFact",
        "ChildLocalExceptionFact",
        "WireFailureNoticeFact",
        "ParentObservedAttemptFact",
        "PublicProjectionFact",
        "FrozenExpectedFact",
        "AttemptEvidenceLayers",
        "validate_attempt_evidence_layers",
    )
    missing = tuple(name for name in required if not hasattr(preparation, name))
    assert missing == (), f"typed evidence layers are missing: {missing}"
    intent = preparation.ScenarioIntentFact("generic_worker_failure")
    child = preparation.ChildLocalExceptionFact.not_observable()
    wire = preparation.WireFailureNoticeFact.not_observable()
    projection = preparation.PublicProjectionFact("failure", "unrecognized", "worker")
    frozen = preparation.FrozenExpectedFact("failure", "worker_failed", "worker")
    layers = preparation.AttemptEvidenceLayers(
        intent=intent,
        child_local=child,
        wire=wire,
        parent=None,
        public_projection=projection,
    )
    with pytest.raises(ValueError, match="parent observed attempt"):
        preparation.validate_attempt_evidence_layers(layers, expected=frozen)

    captured_without_parent = preparation.AttemptEvidenceLayers(
        intent=intent,
        child_local=child,
        wire=preparation.WireFailureNoticeFact.captured(
            category="worker_failed",
            boundary="worker",
            byte_length=171,
            sha256="a" * 64,
        ),
        parent=None,
        public_projection=preparation.PublicProjectionFact(
            "failure", "worker_failed", "worker"
        ),
    )
    with pytest.raises(ValueError, match="parent observed attempt"):
        preparation.validate_attempt_evidence_layers(
            captured_without_parent, expected=frozen
        )


def test_corr2_wire_parent_substitution_and_mismatch_are_rejected() -> None:
    required = (
        "ScenarioIntentFact",
        "ChildLocalExceptionFact",
        "WireFailureNoticeFact",
        "ParentObservedAttemptFact",
        "PublicProjectionFact",
        "AttemptEvidenceLayers",
        "validate_attempt_evidence_layers",
    )
    missing = tuple(name for name in required if not hasattr(preparation, name))
    assert missing == (), f"typed evidence layers are missing: {missing}"
    parent = preparation.ParentObservedAttemptFact(
        "attempt-1", "failure", "worker_failed", "worker"
    )
    layers = preparation.AttemptEvidenceLayers(
        intent=preparation.ScenarioIntentFact("generic_worker_failure"),
        child_local=preparation.ChildLocalExceptionFact.not_observable(),
        wire=preparation.WireFailureNoticeFact.captured(
            category="resource_unavailable",
            boundary="container_rss_read",
            byte_length=190,
            sha256="a" * 64,
        ),
        parent=parent,
        public_projection=preparation.PublicProjectionFact(
            "failure", "unrecognized", "worker"
        ),
    )
    with pytest.raises(ValueError, match="wire and parent"):
        preparation.validate_attempt_evidence_layers(layers)

    matched = preparation.AttemptEvidenceLayers(
        intent=preparation.ScenarioIntentFact("generic_worker_failure"),
        child_local=preparation.ChildLocalExceptionFact.not_observable(),
        wire=preparation.WireFailureNoticeFact.not_observable(),
        parent=parent,
        public_projection=preparation.PublicProjectionFact(
            "failure", "worker_failed", "worker"
        ),
    )
    with pytest.raises(ValueError, match="frozen expected fact"):
        preparation.validate_attempt_evidence_layers(
            matched,
            expected=preparation.FrozenExpectedFact(
                "failure", "resource_unavailable", "container_rss_read"
            ),
        )


def _a01_evidence(*, origin: str = "worker_result"):
    observed = (
        ("primary_result_category", "settled"),
        ("cleanup_disposition", "not_required"),
        ("attempt_ids", ("attempt-1",)),
        ("resource_ids", ("resource-1",)),
        ("failure_sources", ()),
        ("raw_worker_outcomes", ("success",)),
        ("raw_worker_categories", ("none",)),
        ("raw_worker_boundaries", ("none",)),
        (
            "parent_observed_attempt_facts",
            (("attempt-1", "success", "none", "none"),),
        ),
        (
            "child_local_exception_states",
            ("not_observable_at_parent_attempt_boundary",),
        ),
        (
            "wire_failure_notice_states",
            ("not_observable_at_parent_attempt_boundary",),
        ),
        ("public_projection_facts", (("success", "none", "none"),)),
        ("interpreted_evidence_origins", (origin,)),
        ("scenario_injection_intents", ("success",)),
        ("canonical_attempt_outcomes", ("success",)),
        ("canonical_attempt_categories", ("success",)),
        ("scenario_contract_categories", ("matched",)),
        ("authority_attempt_failures", ()),
        ("authority_attempt_count", 1),
        ("parent_observed_failure_pair", ("none", "none")),
        ("retry_observed", False),
        ("maximum_attempts", 2),
        ("observed_contract_category", "success"),
        ("retry_disposition", "retry_not_applicable_after_success"),
        ("third_attempt_absent", True),
        ("forced_tail_stdout_closed", None),
        ("forced_tail_signal", None),
        ("forced_tail_pid", None),
        ("forced_tail_returncode", None),
        ("final_projection_category", "released"),
    )
    events = (
        (
            "preparation_state_history",
            (
                "unprepared",
                "preparing",
                "observation_received",
                "observation_acknowledged",
                "receipt_received",
                "receipt_validated",
                "worker_settled",
                "freshness_validated",
                "final_readiness_open",
                "transient_ownership_clear",
                "stable_sample_one",
                "stable_sample_two",
                "ready_to_release",
                "child_released",
                "settled",
            ),
        ),
    )
    return SimpleNamespace(observed_fields=observed, observed_product_events=events)


def _a01_entry(*, expected: str = "success"):
    return SimpleNamespace(
        case_id="attempt_one_success",
        expected_contract_category=expected,
    )


def test_retry_expectation_echo_is_removed() -> None:
    assert "retry" not in {field.name for field in fields(GroupAContract)}


def test_result_category_expectation_echo_is_removed() -> None:
    assert "result_category" not in {
        field.name for field in fields(GroupAContract)
    }


def test_interpreted_origin_mutation_is_non_authoritative() -> None:
    verify_group_a_contract(_a01_entry(), _a01_evidence(origin="unrecognized"))


def test_correlated_expected_category_mutation_is_rejected() -> None:
    with pytest.raises(GroupAContractViolation, match="expected contract category"):
        verify_group_a_contract(_a01_entry(expected="failed"), _a01_evidence())


def test_runtime_retry_diagnostic_cannot_be_expectation_mutated() -> None:
    evidence = _a01_evidence()
    observed = tuple(
        (
            name,
            "retry_not_observed_after_failure"
            if name == "retry_disposition"
            else value,
        )
        for name, value in evidence.observed_fields
    )
    broken = SimpleNamespace(
        observed_fields=observed,
        observed_product_events=evidence.observed_product_events,
    )
    with pytest.raises(GroupAContractViolation, match="retry disposition"):
        verify_group_a_contract(_a01_entry(), broken)


@pytest.mark.parametrize(
    ("name", "value", "label"),
    (
        (
            "authority_attempt_failures",
            (("worker_failed", "worker"),),
            "authority attempt failures",
        ),
        ("authority_attempt_count", 2, "authority attempt count"),
    ),
)
def test_product_authority_cross_checks_test_side_attempts(
    name: str, value: object, label: str
) -> None:
    evidence = _a01_evidence()
    observed = tuple(
        (field, value if field == name else original)
        for field, original in evidence.observed_fields
    )
    broken = SimpleNamespace(
        observed_fields=observed,
        observed_product_events=evidence.observed_product_events,
    )
    with pytest.raises(GroupAContractViolation, match=label):
        verify_group_a_contract(_a01_entry(), broken)


def test_raw_tuple_mutation_remains_authoritative() -> None:
    evidence = _a01_evidence()
    observed = tuple(
        (name, ("worker_failed",) if name == "raw_worker_categories" else value)
        for name, value in evidence.observed_fields
    )
    broken = SimpleNamespace(
        observed_fields=observed,
        observed_product_events=evidence.observed_product_events,
    )
    with pytest.raises(GroupAContractViolation, match="parent raw authority"):
        verify_group_a_contract(_a01_entry(), broken)


def test_a10_healthy_refusal_is_derived_without_literal_contract_flag() -> None:
    evidence = _a01_evidence()
    observed = tuple(
        (
            name,
            "refused"
            if name in {"final_projection_category", "observed_contract_category"}
            else value,
        )
        for name, value in evidence.observed_fields
    )
    events = (
        (
            "preparation_state_history",
            (
                "unprepared",
                "preparing",
                "observation_received",
                "observation_acknowledged",
                "receipt_received",
                "receipt_validated",
                "worker_settled",
                "freshness_validated",
                "refused",
                "settled",
            ),
        ),
    )
    verify_group_a_contract(
        SimpleNamespace(
            case_id="final_refused_projection",
            expected_contract_category="refused",
        ),
        SimpleNamespace(
            observed_fields=observed,
            observed_product_events=events,
        ),
    )


def test_no_old_origin_name_or_scenario_retry_selector_remains() -> None:
    root = Path("src/test")
    owners = (
        root / "support/python/repomap_test_support/test_cov5k_r2_fix2_catalog.py",
        root / "support/python/repomap_test_support/test_cov5k_r2_fix2_evidence.py",
        root / "support/python/repomap_test_support/test_cov5k_r2_fix2_preparation.py",
        root / "support/python/repomap_test_support/test_cov5k_r2_groupa_contract.py",
        root / "unit/python/repomap_test_support/test_cov5k_r2_groupa_fix1_contract.unit.test.py",
    )
    old_name = "raw_evidence" + "_origin"
    assert all(old_name not in path.read_text(encoding="utf-8") for path in owners)
    preparation = owners[2].read_text(encoding="utf-8")
    assert "scenario_id in {846, 954, 1067}" not in preparation


def test_group_a_catalog_schema_declares_runtime_authority() -> None:
    required = {
        "parent_observed_attempt_facts",
        "child_local_exception_states",
        "wire_failure_notice_states",
        "public_projection_facts",
        "interpreted_evidence_origins",
        "authority_attempt_failures",
        "authority_attempt_count",
        "maximum_attempts",
        "observed_contract_category",
    }
    old_name = "raw_evidence" + "_origins"
    group_a = tuple(
        entry for entry in build_closed_catalog() if entry.semantic_group == "A"
    )
    assert len(group_a) == 9
    assert all(required <= set(entry.observation_schema) for entry in group_a)
    assert all(old_name not in entry.observation_schema for entry in group_a)


def test_no_literal_or_duplicate_boolean_contract_authority() -> None:
    names = {field.name for field in fields(GroupAContract)}
    assert names.isdisjoint(
        {
            "retry",
            "result_category",
            "cleanup",
            "forced_tail",
            "healthy_refusal",
        }
    )
    source = inspect.getsource(preparation.execute_preparation_state_path)
    assert '("forced_tail_stdout_closed", True)' not in source
