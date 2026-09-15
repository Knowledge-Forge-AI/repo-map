from __future__ import annotations

import hashlib
from pathlib import Path

from repomap_test_support.test_cov5k_r2_fix2_catalog import (
    CatalogEntry,
    build_closed_catalog,
)
from repomap_test_support.test_cov5k_r2_fix2_evidence import verify_executor_evidence
from repomap_test_support.test_cov5k_r2_groupa_contract import group_a_public_context
from repomap_test_support.test_cov5k_r2_fix2_observer import (
    execute_observer_request,
    execute_observer_schedule,
)
from repomap_test_support.test_cov5k_r2_fix2_preparation import (
    execute_preparation_state_path,
)
from repomap_test_support.test_cov5k_r2_fix2_process_recorder import (
    execute_zero_process_boundary,
)
from repomap_test_support.test_cov5k_r2_fix2_registry import build_executor_registry
from repomap_test_support.test_cov5k_r2_fix2_runtime import (
    execute_failure_causality,
    execute_process_containment_companion,
    execute_terminal_live_cohort,
    execute_terminal_stage_matrix,
)


def _entries(group: str, operation_kind: str | None = None):
    return tuple(
        entry
        for entry in build_closed_catalog()
        if entry.semantic_group == group
        and (operation_kind is None or entry.operation_kind == operation_kind)
    )


def _verify(entry, result) -> None:
    verify_executor_evidence(entry, result)
    assert result.purpose == "qualification_executor_enactment_rehearsal"
    assert result.model_rehearsal_only is True
    assert result.qualification_status == "unqualified"


def test_fix3_registry_closes_1698_exact_committed_executors() -> None:
    contracts = build_executor_registry()
    assert len(contracts) == 1698
    assert all(contract.callgraph_reachable for contract in contracts)


def test_corr2_catalog_renames_preserve_all_authority_assignments() -> None:
    entries = build_closed_catalog()
    predecessor_names = {
        "A04": "two_source_failures",
        "A05": "source_failure_then_timeout",
        "A06": "timeout_then_source_failure",
        "A09": "cleanup_limitation",
    }
    payload = "".join(
        f"{predecessor_names.get(entry.condition_id, entry.case_id)}="
        f"{entry.authority_id}\n"
        for entry in entries
    ).encode("utf-8")
    assert hashlib.sha256(payload).hexdigest() == (
        "a0b8cec0354713231d509bcb718be42426c10bfb93927f15d2c602a76caa0f66"
    )
    identities = {entry.case_id: entry.authority_id for entry in entries}
    assert identities["parent_settlement_cleanup_limitation_no_retry"] == (
        "TEST-COV5K-R2-AUTH-1676"
    )
    assert identities["final_refused_projection"] == "TEST-COV5K-R2-AUTH-1681"
    assert identities["retry_gate_refusal"] == "TEST-COV5K-R2-AUTH-1693"


def test_fix3_all_group_a_results_bind_complete_product_observations(
    tmp_path: Path,
) -> None:
    entries = _entries("A", "preparation_state_path")
    results = [
        execute_preparation_state_path(tmp_path / f"case-{index}", entry)
        for index, entry in enumerate(entries)
    ]
    for entry, result in zip(entries, results, strict=True):
        context = group_a_public_context(result)
        _verify(entry, result)
        assert set(dict(result.observed_fields)) == set(entry.observation_schema), context
        events = dict(result.observed_product_events)
        assert "forced_tail_stdout_closed" in events, context
        assert "preparation_state_history" in events, context
    projections = {
        entry.case_id: dict(result.observed_fields)["final_projection_category"]
        for entry, result in zip(entries, results, strict=True)
    }
    contexts = {
        entry.case_id: group_a_public_context(result)
        for entry, result in zip(entries, results, strict=True)
    }
    assert projections["attempt_one_success"] == "released", contexts
    assert projections["final_refused_projection"] == "refused", contexts
    forced_signals = {
        dict(result.observed_fields)["forced_tail_signal"] for result in results
    }
    assert {"SIGTERM", "SIGKILL"} <= forced_signals, contexts


def test_fix3_one_group_c_result_per_source_is_owner_derived() -> None:
    representatives: dict[str, CatalogEntry] = {}
    for entry in _entries("C", "failure_causality"):
        source = str(dict(entry.parameter_values)["failure_source"])
        representatives.setdefault(source, entry)
    for source, entry in representatives.items():
        result = execute_failure_causality(entry)
        _verify(entry, result)
        observed = dict(result.observed_fields)
        first_event = result.observed_product_events[0][1]
        assert observed["first_source"] == source
        assert isinstance(first_event, (tuple, list))
        assert first_event[0] != source
        assert observed["causal_sequence"] == 1
    assert len(representatives) == 8


def test_fix3_all_68_group_e_entries_enact_closed_terminal_scenarios() -> None:
    entries = _entries("E")
    results = []
    for entry in entries:
        executor = (
            execute_terminal_live_cohort
            if entry.operation_kind == "terminal_live_cohort"
            else execute_terminal_stage_matrix
        )
        result = executor(
            entry,
            psql_args=("-h", "127.0.0.1"),
            timeout_seconds=0.5,
        )
        _verify(entry, result)
        assert result.enacted_parameters == entry.parameter_values
        assert dict(result.observed_fields)["read_count"] == 1
        assert result.purpose == "qualification_executor_enactment_rehearsal"
        assert result.model_rehearsal_only is True
        assert result.qualification_status == "unqualified"
        results.append(result)
    assert len(results) == 68
    assert len({result.scenario_program_identity for result in results}) == 68


def test_fix3_all_500_group_f_requests_bind_dispatch_and_product_identity() -> None:
    entries = _entries("F", "observer_request")
    results = [execute_observer_request(entry) for entry in entries]
    for entry, result in zip(entries, results, strict=True):
        _verify(entry, result)
        observed = dict(result.observed_fields)
        parameters = dict(entry.parameter_values)
        assert observed["request_deadline_ms"] == parameters["request_deadline_ms"]
        dispatch_timestamp = observed["dispatch_timestamp_ns"]
        assert isinstance(dispatch_timestamp, int)
        assert dispatch_timestamp > 0
        assert observed["operation_identity"] not in {
            entry.authority_id,
            entry.case_id,
            entry.condition_id,
        }
    assert len(results) == 500
    assert len({dict(result.observed_fields)["operation_identity"] for result in results}) == 500


def test_fix3_all_20_group_f_process_companions_are_separately_bound() -> None:
    entries = _entries("F", "process_containment_companion")
    results = [execute_process_containment_companion(entry) for entry in entries]
    for entry, result in zip(entries, results, strict=True):
        _verify(entry, result)
        assert result.enacted_parameters == entry.parameter_values
    assert len(results) == 20
    assert len({result.scenario_program_identity for result in results}) == 20


def test_fix3_all_573_group_g_schedules_enact_product_event_shapes() -> None:
    entries = _entries("G", "observer_schedule")
    results = [execute_observer_schedule(entry) for entry in entries]
    families: dict[str, set[str]] = {}
    for entry, result in zip(entries, results, strict=True):
        _verify(entry, result)
        parameters = dict(entry.parameter_values)
        observed = dict(result.observed_fields)
        trace = observed["event_trace"]
        assert result.enacted_parameters == entry.parameter_values
        assert isinstance(trace, (tuple, list))
        assert len(trace) == parameters["schedule_index"]
        last_event = trace[-1]
        assert isinstance(last_event, (tuple, list))
        assert last_event[1] == parameters["schedule_index"]
        families.setdefault(str(parameters["schedule"]), set()).add(
            str(observed["observed_boundary"])
        )
    assert len(results) == 573
    assert len(families) == 16
    assert all(len(boundaries) == 1 for boundaries in families.values())
    assert len({next(iter(boundaries)) for boundaries in families.values()}) == 16
    assert len({result.scenario_program_identity for result in results}) == 573


def test_fix3_all_eight_group_h_axes_bind_the_process_recorder() -> None:
    entries = _entries("H", "zero_process_boundary")
    results = [execute_zero_process_boundary(entry, lambda: None) for entry in entries]
    for entry, result in zip(entries, results, strict=True):
        _verify(entry, result)
        observed = dict(result.observed_fields)
        assert observed["host_process_count"] == 0
        assert observed["nested_psql_intent_count"] == 0
    assert len(results) == 8
