from __future__ import annotations

from collections.abc import Sized
from pathlib import Path
import subprocess
import sys


from repomap_test_support.test_cov5k_r2_fix2_administrative import (
    execute_administrative_operation,
)
from repomap_test_support.test_cov5k_r2_fix2_catalog import (
    CatalogEntry,
    build_closed_catalog,
)
from repomap_test_support.test_cov5k_r2_fix2_encoding import canonical_digest
from repomap_test_support.test_cov5k_r2_fix2_evidence import verify_executor_evidence
from repomap_test_support.test_cov5k_r2_fix2_observer import (
    execute_fresh_public_rehearsal,
    execute_mixed_configured_campaign,
    execute_observer_schedule,
    execute_observer_request,
    execute_prior_state_preservation,
)
from repomap_test_support.test_cov5k_r2_fix2_preparation import (
    execute_preparation_condition,
    execute_preparation_state_path,
)
from repomap_test_support.test_cov5k_r2_fix2_process_recorder import (
    _command_shape,
    _host_executable,
    record_process_boundary,
)
from repomap_test_support.test_cov5k_r2_fix2_runtime import (
    execute_container_rss,
    execute_container_rss_equivalence,
    execute_failure_causality,
    execute_process_rss,
    execute_process_containment_companion,
    execute_runtime_driver_read,
    execute_terminal_live_cohort,
    execute_terminal_read,
    execute_terminal_stage_matrix,
)
from repomap_test_support.test_cov5k_r2_fix4_psycopg import (
    public_expected_authority,
)


def test_process_observer_preserves_legacy_sequence_commands() -> None:
    class IndexedCommand:
        def __getitem__(self, index: int) -> str:
            return ("/usr/bin/psql", "--version")[index]

    command = IndexedCommand()
    assert _command_shape(command) == ("psql", "<arg>")
    assert _host_executable(command) == "psql"
    assert _command_shape(object()) == ("<opaque-command>",)
    assert _host_executable(object()) == "unknown"


def _entries(group: str):
    return tuple(entry for entry in build_closed_catalog() if entry.semantic_group == group)


def test_all_group_a_cases_enter_parent_and_worker_state_machine(tmp_path: Path) -> None:
    results = [execute_preparation_state_path(tmp_path, entry) for entry in _entries("A")]
    assert len(results) == 9
    assert all(result.owner_entered for result in results)
    assert all(dict(result.observed_fields)["worker_settled"] for result in results)
    assert all(result.qualification_status == "unqualified" for result in results)
    attempt_id_lengths = set()
    for result in results:
        attempt_ids = dict(result.observed_fields)["attempt_ids"]
        assert isinstance(attempt_ids, Sized)
        attempt_id_lengths.add(len(attempt_ids))
    assert attempt_id_lengths == {1, 2}


def test_one_group_b_rehearsal_per_condition_uses_real_parent(tmp_path: Path) -> None:
    representatives: dict[object, CatalogEntry] = {}
    for entry in _entries("B"):
        representatives.setdefault(dict(entry.parameter_values)["condition"], entry)
    results = [execute_preparation_condition(tmp_path, entry) for entry in representatives.values()]
    assert len(results) == 6
    assert all(result.owner_entered for result in results)
    assert all(result.model_rehearsal_only for result in results)


def test_one_group_c_rehearsal_per_source_comes_from_causality_owner() -> None:
    representatives: dict[object, CatalogEntry] = {}
    for entry in _entries("C"):
        representatives.setdefault(dict(entry.parameter_values)["failure_source"], entry)
    results = [execute_failure_causality(entry) for entry in representatives.values()]
    assert len(results) == 8
    assert {
        dict(result.observed_fields)["first_source"] for result in results
    } == set(representatives)


def test_all_group_d_process_parameters_are_enacted_independently() -> None:
    entries = [entry for entry in _entries("D") if entry.operation_kind == "process_rss"]
    results = [execute_process_rss(entry) for entry in entries]
    assert len(results) == 14
    assert {
        dict(result.observed_fields)["process_case"] for result in results
    } == {dict(entry.parameter_values)["process_case"] for entry in entries}


def test_all_group_d_equivalence_pairs_preserve_workload_and_pair() -> None:
    entries = [
        entry for entry in _entries("D") if entry.operation_kind == "container_rss_equivalence"
    ]
    results = [
        execute_container_rss_equivalence(
            entry, api_reader=lambda: 10_000, diagnostic_reader=lambda: 10_001
        )
        for entry in entries
    ]
    assert len(results) == 30
    assert {
        (dict(result.observed_fields)["workload"], dict(result.observed_fields)["pair"])
        for result in results
    } == {
        (dict(entry.parameter_values)["workload"], dict(entry.parameter_values)["pair"])
        for entry in entries
    }


class _PsqlCompletion(subprocess.CompletedProcess[str]):
    def __init__(self, category: str) -> None:
        diagnostics = {
            "success": "",
            "class_08": "SQLSTATE 08006 connection failure",
            "unavailable": "psql: command not found",
            "authentication": "FATAL: password authentication failed",
            "semantic_schema": 'ERROR: relation "missing" does not exist',
            "transport_refusal": "connection refused",
        }
        super().__init__(
            args=["psql"],
            returncode=int(category != "success"),
            stdout="",
            stderr=diagnostics[category],
        )


def test_all_70_group_d_entries_enact_their_frozen_parameter_tuple() -> None:
    results = []
    for entry in _entries("D"):
        parameters = dict(entry.parameter_values)
        if entry.operation_kind == "runtime_driver_read":
            category = str(parameters["failure_category"])
            result = execute_runtime_driver_read(
                entry,
                psql_args=("-h", "127.0.0.1"),
                expected_authority=public_expected_authority(),
                psql_runner=lambda *_args, category=category, **_kwargs: _PsqlCompletion(category),
            )
            assert dict(result.observed_fields)["failure_category"] == category
        elif entry.operation_kind == "process_rss":
            result = execute_process_rss(entry)
        elif entry.operation_kind == "container_rss":
            category = str(parameters["category"])
            result = execute_container_rss(
                entry,
                runtime="docker",
                container_name="public-safe-container",
                runtime_source_commit="1" * 40,
                postgresql_server_version="17",
            )
            assert dict(result.observed_fields)["primary_result_category"] == category
        elif entry.operation_kind == "container_rss_equivalence":
            result = execute_container_rss_equivalence(
                entry, api_reader=lambda: 10_000, diagnostic_reader=lambda: 10_001
            )
        elif entry.operation_kind == "terminal_read":
            result = execute_terminal_read(
                entry,
                psql_args=("-h", "127.0.0.1"),
                timeout_seconds=0.5,
            )
            observed = dict(result.observed_fields)
            assert observed["enacted_family"] == "dimension"
            assert observed["enacted_value"] == parameters["dimension"]
            assert observed["read_count"] == 1
        else:
            raise AssertionError(entry.operation_kind)
        assert result.enacted_parameters == entry.parameter_values
        verify_executor_evidence(entry, result)
        assert result.purpose == "qualification_executor_enactment_rehearsal"
        assert result.model_rehearsal_only is True
        assert result.qualification_status == "unqualified"
        results.append(result)
    assert len(results) == 70
    assert not tuple(
        result
        for result in results
        if result.owner_entry_evidence is None
        or result.owner_entry_evidence.qualified_symbol
        != result.owner_entry_evidence.registered_owner_qualified_symbol
    )


def test_one_group_e_rehearsal_per_cohort_and_stage_enters_terminal_owner() -> None:
    representatives: dict[tuple[str, object], CatalogEntry] = {}
    for entry in _entries("E"):
        parameters = dict(entry.parameter_values)
        family = "cohort" if "cohort" in parameters else "stage"
        representatives.setdefault((family, parameters[family]), entry)

    terminal_executors = {
        "execute_terminal_read": execute_terminal_read,
        "execute_terminal_live_cohort": execute_terminal_live_cohort,
        "execute_terminal_stage_matrix": execute_terminal_stage_matrix,
    }
    results = [
        terminal_executors[entry.executor_symbol](
            entry,
            psql_args=("-h", "127.0.0.1"),
            timeout_seconds=0.5,
        )
        for entry in representatives.values()
    ]
    assert len(results) == 13
    assert all(result.owner_entry_evidence is not None for result in results)
    assert {
        (dict(result.observed_fields)["enacted_family"], dict(result.observed_fields)["enacted_value"])
        for result in results
    } == set(representatives)
    assert all(dict(result.observed_fields)["enacted_steps"] for result in results)
    assert all(result.qualification_status == "unqualified" for result in results)


def test_one_group_g_rehearsal_per_schedule_uses_frozen_parameter_object() -> None:
    representatives: dict[object, CatalogEntry] = {}
    for entry in _entries("G"):
        if entry.operation_kind == "observer_schedule":
            representatives.setdefault(dict(entry.parameter_values)["schedule"], entry)
    results = [execute_observer_schedule(entry) for entry in representatives.values()]
    assert len(results) == 16
    assert {
        dict(result.enacted_parameters)["schedule"] for result in results
    } == set(representatives)
    assert len({dict(result.observed_fields)["observed_boundary"] for result in results}) == 16


def test_small_group_f_subset_uses_observer_and_containment_owners() -> None:
    request = next(entry for entry in _entries("F") if entry.operation_kind == "observer_request")
    companion = next(
        entry for entry in _entries("F") if entry.operation_kind == "process_containment_companion"
    )
    results = (
        execute_observer_request(request),
        execute_process_containment_companion(companion),
    )
    assert all(result.owner_entered for result in results)
    assert all(result.qualification_status == "unqualified" for result in results)


def test_group_j_mixed_fresh_and_prior_samples_use_parent_handoff() -> None:
    by_operation = {entry.operation_kind: entry for entry in _entries("J")}
    results = (
        execute_mixed_configured_campaign(by_operation["mixed_configured_campaign"]),
        execute_fresh_public_rehearsal(by_operation["fresh_public_rehearsal"]),
        execute_prior_state_preservation(by_operation["prior_state_preservation"]),
    )
    assert all(dict(result.observed_fields)["parent_readiness"] == (True, True, True, True) for result in results)


def test_process_recorder_catches_short_lived_and_nested_psql_intents() -> None:
    def operation() -> None:
        subprocess.run([sys.executable, "-c", "pass"], check=True, shell=False)
        subprocess.run(["psql", "--version"], check=True, shell=False, capture_output=True)

    evidence = record_process_boundary(operation)
    assert evidence.host_process_count == 2
    assert evidence.nested_psql_intent_count == 1
    assert evidence.operation_started_ns <= evidence.operation_ended_ns


def test_process_recorder_does_not_double_count_run_and_popen() -> None:
    evidence = record_process_boundary(
        lambda: subprocess.run([sys.executable, "-c", "pass"], check=True, shell=False)
    )
    assert len(evidence.creations) == 1
    assert evidence.creations[0].boundary == "subprocess.run"


def test_group_k_all_cases_bind_real_argv_digest_and_exact_disposition(tmp_path: Path) -> None:
    receipts = []
    for entry in _entries("K"):
        argv = ("tool", entry.condition_id, "private-value")

        def runner(command, **_kwargs):
            return subprocess.CompletedProcess(
                command,
                1
                if entry.condition_id in {"K02", "K03", "K04", "K05", "K11"}
                else 0,
                "",
                "",
            )

        receipt = execute_administrative_operation(
            entry, argv, cwd=tmp_path, runner=runner
        )
        receipts.append(receipt)
        assert receipt.effective_argv_digest == canonical_digest(
            {"effective_argv": argv, "shell": False, "timeout_seconds": 10}
        )
        assert "private-value" not in receipt.redacted_argv_shape
    assert len(receipts) == 12
