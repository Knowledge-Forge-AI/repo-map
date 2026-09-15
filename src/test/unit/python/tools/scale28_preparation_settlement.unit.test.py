from __future__ import annotations

from dataclasses import replace

import pytest

from repomap_test_support import test_cov5k_r2_fix2_preparation as preparation
from repomap_test_support.test_cov5k_r2_fix2_catalog import build_closed_catalog
from repomap_test_support.test_cov5k_r2_fix2_evidence import (
    ExecutorEvidenceError,
    bind_executor_evidence,
    verify_executor_evidence,
)
from repomap_test_support.test_cov5k_r2_fix2_registry import (
    build_executor_registry,
)


@pytest.fixture()
def settlement_case(monkeypatch, tmp_path):
    entries = build_closed_catalog()
    entry = next(
        entry
        for entry in entries
        if entry.case_id == "parent_settlement_cleanup_limitation_no_retry"
    )
    contracts = build_executor_registry()
    executor = next(
        contract.executor
        for contract in contracts
        if contract.authority_id == entry.authority_id
    )
    parent_run_calls = []
    original_parent_run = preparation._ParentSettlementAttempt.run

    def counted_parent_run(attempt):
        parent_run_calls.append(attempt)
        return original_parent_run(attempt)

    def unexpected_child_preparer(_specification):
        raise AssertionError("cleanup must not invoke a child preparer")

    monkeypatch.setattr(
        preparation._ParentSettlementAttempt, "run", counted_parent_run
    )
    for name in tuple(preparation._PREPARERS):
        monkeypatch.setitem(
            preparation._PREPARERS, name, unexpected_child_preparer
        )
    return entry, executor(tmp_path, entry), parent_run_calls


def _replace_field(evidence, name: str, value: object):
    fields = tuple(
        (field, value if field == name else original)
        for field, original in evidence.observed_fields
    )
    assert name in dict(fields)
    return fields


def _replace_event(evidence, name: str, value: object):
    events = tuple(
        (event, value if event == name else original)
        for event, original in evidence.observed_product_events
    )
    assert name in dict(events)
    return events


def _rebind(entry, evidence, observed_fields, observed_product_events):
    return bind_executor_evidence(
        entry,
        enacted_parameters=evidence.enacted_parameters,
        observed_fields=observed_fields,
        owner_entry_evidence=evidence.owner_entry_evidence,
        scenario_program_identity=evidence.scenario_program_identity,
        observed_product_events=observed_product_events,
    )


def _mutate_settlement(evidence, mutation: str):
    observed_fields = evidence.observed_fields
    observed_product_events = evidence.observed_product_events
    if mutation == "raw_category":
        observed_fields = _replace_field(
            evidence, "raw_worker_categories", ("worker_failed",)
        )
    elif mutation == "raw_boundary":
        observed_fields = _replace_field(
            evidence, "raw_worker_boundaries", ("worker",)
        )
    elif mutation == "parent_observed_attempt_fact":
        observed_fields = _replace_field(
            evidence,
            "parent_observed_attempt_facts",
            (("attempt-1", "failure", "cleanup_limitation", "worker"),),
        )
    elif mutation == "authority_attempt_count":
        observed_fields = _replace_field(evidence, "authority_attempt_count", 2)
    elif mutation == "retry_observed":
        observed_fields = _replace_field(evidence, "retry_observed", True)
    elif mutation == "retry_disposition":
        observed_fields = _replace_field(
            evidence, "retry_disposition", "retry_observed"
        )
    elif mutation == "child_local_explicit_absence":
        observed_fields = _replace_field(
            evidence, "child_local_exception_states", ("captured",)
        )
    elif mutation == "wire_explicit_absence":
        observed_fields = _replace_field(
            evidence, "wire_failure_notice_states", ("captured",)
        )
    elif mutation == "preparation_state_history":
        observed_product_events = _replace_event(
            evidence,
            "preparation_state_history",
            ("unprepared", "preparing", "settled"),
        )
    elif mutation == "forced_tail_absence":
        observed_fields = _replace_field(
            evidence, "forced_tail_signal", "SIGTERM"
        )
    elif mutation == "final_projection":
        observed_fields = _replace_field(
            evidence, "final_projection_category", "released"
        )
    else:
        raise AssertionError(f"unknown settlement mutation: {mutation}")
    return observed_fields, observed_product_events


def test_parent_settlement_cleanup_limitation_is_one_attempt_without_retry(
    settlement_case,
) -> None:
    entry, evidence, parent_run_calls = settlement_case
    assert entry.semantic_group == "PARENT_SETTLEMENT"
    assert entry.condition_id == "A09"
    assert dict(entry.parameter_values)["scenario_id"] == 954
    verify_executor_evidence(entry, evidence)
    observed = dict(evidence.observed_fields)
    assert observed["parent_observed_failure_pair"] == (
        "cleanup_limitation",
        "process_settlement",
    )
    assert observed["authority_attempt_count"] == 1
    assert observed["retry_observed"] is False
    assert len(parent_run_calls) == 1
    assert "cleanup" not in preparation._PREPARERS


@pytest.mark.parametrize(
    ("mutation", "label"),
    (
        ("raw_category", "raw parent failure"),
        ("raw_boundary", "raw parent failure"),
        ("parent_observed_attempt_fact", "parent raw authority"),
        ("authority_attempt_count", "attempt count"),
        ("retry_observed", "retry absence"),
        ("retry_disposition", "retry disposition"),
        ("child_local_explicit_absence", "child-local explicit absence"),
        ("wire_explicit_absence", "wire explicit absence"),
        ("preparation_state_history", "lifecycle"),
        ("forced_tail_absence", "forced-tail absence"),
        ("final_projection", "projection"),
    ),
)
def test_parent_settlement_rejects_digest_rebound_contract_mutations(
    settlement_case, mutation: str, label: str
) -> None:
    entry, evidence, _parent_run_calls = settlement_case
    observed_fields, observed_product_events = _mutate_settlement(
        evidence, mutation
    )
    rebound = _rebind(entry, evidence, observed_fields, observed_product_events)
    with pytest.raises(ExecutorEvidenceError) as captured:
        verify_executor_evidence(entry, rebound)
    assert str(captured.value).startswith(
        f"parent-settlement {label} mismatch; settlement_context="
    )


def test_parent_settlement_ignored_bound_field_requires_digest_rebind(
    settlement_case,
) -> None:
    entry, evidence, _parent_run_calls = settlement_case
    mutated = replace(
        evidence,
        observed_fields=_replace_field(
            evidence,
            "parent_observed_failure_pair",
            ("tampered", "bound"),
        ),
    )
    with pytest.raises(ExecutorEvidenceError, match="result digest differs"):
        verify_executor_evidence(entry, mutated)
