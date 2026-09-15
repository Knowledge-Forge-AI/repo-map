from __future__ import annotations

from dataclasses import replace

import pytest

from repomap_test_support.test_cov5k_r2_fix2_catalog import build_closed_catalog
from repomap_test_support.test_cov5k_r2_fix2_encoding import canonical_digest
from repomap_test_support.test_cov5k_r2_fix2_evidence import (
    ExecutorEvidenceError,
    verify_executor_evidence,
)
from repomap_test_support.test_cov5k_r2_fix2_runtime import execute_terminal_read
from repomap_test_support.test_cov5k_r2_fix4_psycopg import (
    PsycopgOwnerObservation,
    PsycopgTaxonomyError,
    classify_psycopg_observation,
)
from repomap_test_support.test_cov5k_r2_fix4_terminal_contexts import (
    verify_terminal_context_distinctions,
)


def _entry(value: str):
    return next(
        entry
        for entry in build_closed_catalog()
        if entry.semantic_group == "D"
        and entry.operation_kind == "terminal_read"
        and dict(entry.parameter_values)["dimension"] == value
    )


def _result_digest(result) -> str:
    return canonical_digest(
        {
            "authority_id": result.authority_id,
            "frozen_parameter_digest": result.frozen_parameter_digest,
            "observed_enacted_parameter_digest": result.observed_enacted_parameter_digest,
            "owner": result.owner_entry_evidence,
            "scenario_program_identity": result.scenario_program_identity,
            "observed_product_events": result.observed_product_events,
            "observed_fields": result.observed_fields,
        }
    )


def _rebind(result, **changes):
    mutated = replace(result, **changes)
    return replace(mutated, result_digest=_result_digest(mutated))


def _replace_field(result, name: str, value: object):
    fields = tuple(
        (field, value if field == name else original)
        for field, original in result.observed_fields
    )
    return _rebind(result, observed_fields=fields)


@pytest.fixture(scope="module")
def terminal_samples():
    entries = (_entry("one_read"), _entry("query_fetch"))
    results = tuple(
        execute_terminal_read(entry, psql_args=(), timeout_seconds=0.5)
        for entry in entries
    )
    return entries, results


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("owner_digest", "module digest"),
        ("owner_symbol", "qualified symbol"),
        ("executor_symbol", "executor qualified symbol"),
        ("owner_outside_operation", "outside.*operation"),
        ("catalog_label_scenario", "catalog label"),
        ("scenario_label_stage_source", "not sourced"),
        ("scenario_label_stage", "absent from owner events"),
        ("context_not_started", "not started"),
        ("context_not_observed", "not observed during owner"),
        ("context_event_removed", "observation is absent"),
    ),
)
def test_fix4_identity_and_context_mutations_fail_for_intended_reason(
    mutation: str,
    message: str,
    terminal_samples,
) -> None:
    entries, results = terminal_samples
    entry, result = entries[0], results[0]
    owner = result.owner_entry_evidence
    assert owner is not None
    if mutation == "owner_digest":
        result = _rebind(result, owner_entry_evidence=replace(owner, module_source_digest="0" * 64))
    elif mutation == "owner_symbol":
        result = _rebind(result, owner_entry_evidence=replace(owner, qualified_symbol="alternate.owner"))
    elif mutation == "executor_symbol":
        result = _rebind(
            result,
            owner_entry_evidence=replace(owner, executor_qualified_symbol="alternate.executor"),
        )
    elif mutation == "owner_outside_operation":
        result = _rebind(
            result,
            owner_entry_evidence=replace(owner, owner_entry_during_operation=False),
        )
    elif mutation == "catalog_label_scenario":
        result = _rebind(result, scenario_program_identity=entry.case_id)
    elif mutation == "scenario_label_stage_source":
        result = _replace_field(result, "observed_stage_source", "scenario_label")
    elif mutation == "scenario_label_stage":
        result = _replace_field(result, "observed_stage", dict(entry.parameter_values)["dimension"])
    elif mutation == "context_not_started":
        result = _replace_field(result, "context_condition_started", False)
    elif mutation == "context_not_observed":
        result = _replace_field(result, "context_condition_observed_during_owner", False)
    else:
        events = tuple(
            event for event in result.observed_product_events
            if event[0] != "context_condition_observed"
        )
        result = _rebind(result, observed_product_events=events)
    with pytest.raises(ExecutorEvidenceError, match=message):
        verify_executor_evidence(entry, result)


def test_fix4_rejects_one_success_trace_reused_for_distinct_contexts(
    terminal_samples,
) -> None:
    _entries, results = terminal_samples
    first_fields = dict(results[0].observed_fields)
    second = _replace_field(
        results[1], "context_program_id", first_fields["context_program_id"]
    )
    second = _replace_field(
        second, "terminal_event_trace", first_fields["terminal_event_trace"]
    )
    second = _rebind(
        second,
        scenario_program_identity=results[0].scenario_program_identity,
    )
    with pytest.raises(ValueError, match="reused"):
        verify_terminal_context_distinctions((results[0], second))


def test_fix4_rejects_category_string_without_typed_psycopg_evidence() -> None:
    observation = PsycopgOwnerObservation(
        None,
        "public.CategoryError",
        None,
        None,
        None,
        None,
        "driver_connect",
        (("owner_stage", "driver_connect"),),
    )
    with pytest.raises(PsycopgTaxonomyError, match="does not support"):
        classify_psycopg_observation(observation)
