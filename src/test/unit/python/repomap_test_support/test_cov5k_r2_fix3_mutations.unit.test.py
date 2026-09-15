from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import subprocess

import pytest

from repomap_test_support.test_cov5k_r2_fix2_administrative import (
    execute_administrative_operation,
)
from repomap_test_support.test_cov5k_r2_fix2_catalog import build_closed_catalog
from repomap_test_support.test_cov5k_r2_fix2_evidence import (
    ExecutorEvidenceError,
    bind_executor_evidence,
    verify_executor_evidence,
)
from repomap_test_support.test_cov5k_r2_fix2_observer import (
    execute_observer_request,
    execute_observer_schedule,
)
from repomap_test_support.test_cov5k_r2_fix2_preparation import (
    execute_preparation_state_path,
)
from repomap_test_support.test_cov5k_r2_fix2_runtime import (
    _SOURCE_CODES,
    execute_container_rss_equivalence,
    execute_failure_causality,
    execute_runtime_driver_read,
    execute_terminal_read,
)
from repomap_test_support.test_cov5k_r2_fix3_owner_binding import (
    exact_callable_matches,
)
from repomap_test_support.test_cov5k_r2_fix3_sibling_oracle import (
    SiblingCampaignOracleError,
    validate_sibling_campaign_oracle,
)
from repomap_test_support.test_cov5k_r2_fix4_psycopg import public_expected_authority
import repomap_test_support.test_cov5k_r2_fix2_runtime as runtime


class EnactmentMutationError(AssertionError):
    pass


def _entry(group: str, operation: str, *, offset: int = 0):
    entries = [
        entry
        for entry in build_closed_catalog()
        if entry.semantic_group == group and entry.operation_kind == operation
    ]
    return entries[offset]


def _replace_field(evidence, name: str, value: object):
    fields = tuple(
        (field, value if field == name else original)
        for field, original in evidence.observed_fields
    )
    return replace(evidence, observed_fields=fields)


def _validate_group_g_pair(entries, results) -> None:
    if len({result.observed_product_events for result in results}) != len(results):
        raise EnactmentMutationError("Group G product summaries are identical")
    for entry, result in zip(entries, results, strict=True):
        if result.scenario_program_identity in {entry.case_id, entry.condition_id}:
            raise EnactmentMutationError("Group G scenario is inferred from a label")


def _validate_request(entry, result) -> None:
    observed = dict(result.observed_fields)
    if observed["request_deadline_ms"] != dict(entry.parameter_values)["request_deadline_ms"]:
        raise EnactmentMutationError("request deadline was not passed at dispatch")
    if observed["operation_identity"] in {
        entry.authority_id,
        entry.case_id,
        entry.condition_id,
    }:
        raise EnactmentMutationError("request operation identity is catalog-owned")


def _validate_terminal(entry, result) -> None:
    if result.scenario_program_identity in {entry.case_id, entry.condition_id}:
        raise EnactmentMutationError("terminal scenario is label-only")


def _validate_group_a(entry, result) -> None:
    if set(dict(result.observed_fields)) != set(entry.observation_schema):
        raise EnactmentMutationError("Group A registered observation is incomplete")
    if "forced_tail_stdout_closed" not in dict(result.observed_product_events):
        raise EnactmentMutationError("forced-tail stdout closure evidence is absent")


def _validate_group_a_distinction(success, refused) -> None:
    success_projection = dict(success.observed_fields)["final_projection_category"]
    refused_projection = dict(refused.observed_fields)["final_projection_category"]
    if success_projection == refused_projection:
        raise EnactmentMutationError("Group A success and refused are identical")


def _validate_group_c(result) -> None:
    reverse = {code: source for source, code in _SOURCE_CODES.items()}
    first_code = str(result.observed_product_events[0][1][0])
    if dict(result.observed_fields)["first_source"] != reverse[first_code]:
        raise EnactmentMutationError("Group C first source is not owner-derived")


@pytest.fixture(scope="module")
def samples(tmp_path_factory):
    root = tmp_path_factory.mktemp("fix3-mutations")
    g_entries = (
        _entry("G", "observer_schedule", offset=0),
        next(
            entry
            for entry in build_closed_catalog()
            if entry.semantic_group == "G"
            and entry.operation_kind == "observer_schedule"
            and dict(entry.parameter_values)["schedule"]
            != dict(_entry("G", "observer_schedule").parameter_values)["schedule"]
        ),
    )
    a_entries = (
        next(entry for entry in build_closed_catalog() if entry.case_id == "attempt_one_success"),
        next(
            entry
            for entry in build_closed_catalog()
            if entry.case_id == "final_refused_projection"
        ),
    )
    return {
        "g_entries": g_entries,
        "g_results": tuple(execute_observer_schedule(entry) for entry in g_entries),
        "f_entry": _entry("F", "observer_request"),
        "a_entries": a_entries,
        "a_results": tuple(
            execute_preparation_state_path(root / f"a-{index}", entry)
            for index, entry in enumerate(a_entries)
        ),
        "c_entry": _entry("C", "failure_causality"),
        "pair_entry": _entry("D", "container_rss_equivalence"),
        "terminal_entry": _entry("D", "terminal_read"),
        "root": root,
    }


@pytest.mark.parametrize(
    "mutation",
    (
        "g_identical_summary",
        "g_case_id_scenario",
        "f_deadline_not_dispatched",
        "f_catalog_operation_identity",
        "terminal_label_only",
        "unfrozen_terminal_argument",
        "psql_categories_collapsed",
        "container_owner_not_entered",
        "a_missing_registered_field",
        "a_success_refused_identical",
        "a_descriptor_worker_alias",
        "enacted_tuple_copied",
        "same_module_owner_substitution",
        "runtime_generic_insertion",
        "c_first_source_echoed",
        "k_cleanup_not_proved",
        "sibling_oracle_not_propagated",
    ),
)
def test_fix3_anti_inflation_mutations_fail_for_intended_reason(
    mutation: str,
    samples,
    monkeypatch,
) -> None:
    if mutation.startswith("g_"):
        entries = samples["g_entries"]
        first, second = samples["g_results"]
        if mutation == "g_identical_summary":
            second = replace(second, observed_product_events=first.observed_product_events)
        else:
            second = replace(second, scenario_program_identity=entries[1].case_id)
        with pytest.raises(EnactmentMutationError, match="Group G"):
            _validate_group_g_pair(entries, (first, second))
        return
    if mutation.startswith("f_"):
        entry = samples["f_entry"]
        result = execute_observer_request(entry)
        field = "request_deadline_ms" if "deadline" in mutation else "operation_identity"
        value = 0 if "deadline" in mutation else entry.authority_id
        with pytest.raises(EnactmentMutationError, match="request"):
            _validate_request(entry, _replace_field(result, field, value))
        return
    if mutation == "terminal_label_only":
        entry = samples["terminal_entry"]
        result = execute_terminal_read(entry, psql_args=(), timeout_seconds=0.5)
        with pytest.raises(EnactmentMutationError, match="label-only"):
            _validate_terminal(entry, replace(result, scenario_program_identity=entry.case_id))
        return
    if mutation == "unfrozen_terminal_argument":
        with pytest.raises(ValueError, match="deadline differs"):
            execute_terminal_read(
                samples["terminal_entry"], psql_args=(), timeout_seconds=0.6
            )
        return
    if mutation == "psql_categories_collapsed":
        entry = next(
            entry
            for entry in build_closed_catalog()
            if entry.semantic_group == "D"
            and entry.operation_kind == "runtime_driver_read"
            and dict(entry.parameter_values)["driver"] == "psql"
            and dict(entry.parameter_values)["failure_category"] != "unavailable"
        )
        monkeypatch.setattr(runtime, "_psql_failure_category", lambda _result: "unavailable")
        completion = subprocess.CompletedProcess((), 1, "", "connection refused")
        with pytest.raises(ExecutorEvidenceError, match="differ from frozen"):
            execute_runtime_driver_read(
                entry,
                psql_args=(),
                expected_authority=public_expected_authority(),
                psql_runner=lambda *_args, **_kwargs: completion,
            )
        return
    if mutation == "container_owner_not_entered":
        entry = samples["pair_entry"]
        result = execute_container_rss_equivalence(
            entry, api_reader=lambda: 1, diagnostic_reader=lambda: 1
        )
        assert result.owner_entry_evidence is not None
        owner = replace(result.owner_entry_evidence, owner_entry_count=0)
        with pytest.raises(ExecutorEvidenceError, match="not entered"):
            verify_executor_evidence(entry, replace(result, owner_entry_evidence=owner))
        return
    if mutation.startswith("a_"):
        entries = samples["a_entries"]
        success, refused = samples["a_results"]
        if mutation == "a_missing_registered_field":
            broken = replace(success, observed_fields=success.observed_fields[:-1])
            with pytest.raises(EnactmentMutationError, match="incomplete"):
                _validate_group_a(entries[0], broken)
        elif mutation == "a_success_refused_identical":
            refused = _replace_field(
                refused,
                "final_projection_category",
                dict(success.observed_fields)["final_projection_category"],
            )
            with pytest.raises(EnactmentMutationError, match="success and refused"):
                _validate_group_a_distinction(success, refused)
        else:
            events = tuple(
                event for event in success.observed_product_events
                if event[0] != "forced_tail_stdout_closed"
            )
            with pytest.raises(EnactmentMutationError, match="closure evidence"):
                _validate_group_a(entries[0], replace(success, observed_product_events=events))
        return
    if mutation == "enacted_tuple_copied":
        entry = samples["g_entries"][0]
        result = samples["g_results"][0]
        with pytest.raises(ExecutorEvidenceError, match="reuse frozen"):
            bind_executor_evidence(
                entry,
                enacted_parameters=entry.parameter_values,
                observed_fields=result.observed_fields,
                owner_entry_evidence=result.owner_entry_evidence,
                scenario_program_identity=result.scenario_program_identity,
                observed_product_events=result.observed_product_events,
            )
        return
    if mutation in {"same_module_owner_substitution", "runtime_generic_insertion"}:
        candidate = (
            runtime.execute_failure_causality
            if mutation == "same_module_owner_substitution"
            else lambda _entry: None
        )
        assert not exact_callable_matches(
            candidate,
            source_path=Path(runtime.__file__),
            symbol="execute_process_rss",
        )
        return
    if mutation == "c_first_source_echoed":
        result = execute_failure_causality(samples["c_entry"])
        source = next(
            source for source in _SOURCE_CODES
            if source != dict(result.observed_fields)["first_source"]
        )
        with pytest.raises(EnactmentMutationError, match="owner-derived"):
            _validate_group_c(_replace_field(result, "first_source", source))
        return
    if mutation == "k_cleanup_not_proved":
        entry = _entry("K", "backup")
        receipt = execute_administrative_operation(
            entry,
            ("tool", "public-object"),
            cwd=samples["root"],
            runner=lambda command, **_kwargs: subprocess.CompletedProcess(
                command, 0, "", ""
            ),
        )
        with pytest.raises(EnactmentMutationError, match="cleanup"):
            if not receipt.cleanup_proved:
                raise EnactmentMutationError("Group K cleanup is recorded but not proved")
        return
    attacks = (
        (0, {"observer_active_summary", "observer_connection_lost", "observer_event_apply"}, 0),
        (1, {"observer_active_summary"}, 0),
        (1, {"observer_active_summary", "observer_connection_lost", "observer_event_apply"}, 2),
    )
    for published, boundaries, preemptions in attacks:
        with pytest.raises(SiblingCampaignOracleError):
            validate_sibling_campaign_oracle(
                published=published,
                observed_injected_boundaries=boundaries,
                source_owned_preemptions=preemptions,
            )
