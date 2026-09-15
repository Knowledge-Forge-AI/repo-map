"""Independent executable seams and facade for the FIX1 model rehearsal."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from repomap_test_support.test_cov5k_r2_fix1_catalog import (
    CatalogEntry,
    ParameterTuple,
)
from repomap_test_support.test_cov5k_r2_fix1_executor_administrative import (
    AdministrativeEntry,
    _execution_receipt_digest as _execution_receipt_digest,
    _free_loopback_port as _free_loopback_port,
    _run_k as _run_k,
    execute_group_k_administrative,
    execute_group_k_docker as execute_group_k_docker,
    execute_group_k_ephemeral as execute_group_k_ephemeral,
)
from repomap_test_support.test_cov5k_r2_fix1_executor_preparation import (
    ExecutionEvidence as ExecutionEvidence,
    ObservedTuple as ObservedTuple,
    _A_PROGRAMS as _A_PROGRAMS,
    _argv_shape as _argv_shape,
    _base_values as _base_values,
    _executor_digest as _executor_digest,
    _project as _project,
    execute_group_a as execute_group_a,
)
from repomap_test_support.test_cov5k_r2_fix1_executor_runtime import (
    _database as _database,
    _group_d_enacted_parameters,
    execute_group_d_runtime,
    execute_group_g as execute_group_g,
    execute_group_h_runtime,
)


@dataclass(frozen=True, slots=True)
class RunnerBinding:
    """One independently authored runner and argv-builder contract."""

    runner_id: str
    semantic_group: str
    argv_builder: Callable[[CatalogEntry, Path], tuple[str, ...]]


def _fixed_in_process_argv(
    entry: CatalogEntry,
    _: Path,
) -> tuple[str, ...]:
    return ("in-process", entry.evidence_executor_id, entry.case_id)


def _fixed_pytest_argv(
    entry: CatalogEntry,
    _: Path,
) -> tuple[str, ...]:
    if entry.pytest_node_id is None:
        raise ValueError("pytest executor lacks a frozen node")
    return ("pytest", entry.pytest_node_id)


def _fixed_k_argv(entry: CatalogEntry, _: Path) -> tuple[str, ...]:
    return _argv_shape(dict(entry.parameter_values)["rehearsal_argv_shape"])


def runner_binding_for(entry: CatalogEntry) -> RunnerBinding:
    """Select one explicit builder without manufacturing it from a manifest."""

    if entry.semantic_group == "K":
        builder = _fixed_k_argv
    elif entry.pytest_node_id is not None:
        builder = _fixed_pytest_argv
    else:
        builder = _fixed_in_process_argv
    return RunnerBinding(
        runner_id=entry.fixed_runner_id,
        semantic_group=entry.semantic_group,
        argv_builder=builder,
    )


def execute_group_d(entry: CatalogEntry) -> ObservedTuple:
    """Run one real representative for each selected Group D family."""
    return execute_group_d_runtime(entry, database=_database)


def execute_group_h(temp_root: Path, entry: CatalogEntry) -> ObservedTuple:
    """Call the registered axis owner and measure its post-call boundary."""
    return execute_group_h_runtime(temp_root, entry, database=_database)


def execute_group_k(
    repository_root: Path,
    temp_root: Path,
    entry: AdministrativeEntry,
) -> ObservedTuple:
    """Execute the registered administrative owner against disposable state."""
    return execute_group_k_administrative(
        repository_root,
        temp_root,
        entry,
        run_k=_run_k,
        database=_database,
        execute_group_k_ephemeral=execute_group_k_ephemeral,
        execute_group_k_docker=execute_group_k_docker,
        free_loopback_port=_free_loopback_port,
    )


def execute_entry(
    repository_root: Path,
    temp_root: Path,
    entry: CatalogEntry,
) -> ExecutionEvidence:
    """Execute one registered model-rehearsal authority."""

    if entry.semantic_group in {"A", "PARENT_SETTLEMENT"}:
        observed = execute_group_a(temp_root, entry)
        program = _A_PROGRAMS[entry.condition_id]
        enacted: ParameterTuple = (
            ("path", entry.case_id),
            ("cleanup", program.cleanup),
            ("retry", program.retry),
        )
        return ExecutionEvidence(observed, enacted)
    if entry.semantic_group == "D":
        observed = execute_group_d(entry)
        return ExecutionEvidence(
            observed,
            _group_d_enacted_parameters(entry, dict(observed)),
        )
    if entry.semantic_group == "G":
        return execute_group_g(entry)
    if entry.semantic_group == "H":
        observed = execute_group_h(temp_root, entry)
        axis_names = {
            "H01": "psycopg_success",
            "H02": "psycopg_connection_failure",
            "H03": "process_rss",
            "H04": "process_tree_rss",
            "H05": "container_rss",
            "H06": "terminal_read_success",
            "H07": "terminal_read_timeout",
            "H08": "complete_preparation_resource_read",
        }
        return ExecutionEvidence(observed, (("axis", axis_names[entry.condition_id]),))
    if entry.semantic_group == "K":
        observed = execute_group_k(repository_root, temp_root, entry)
        values = dict(observed)
        parameters = dict(entry.parameter_values)
        raw_timeout = values["timeout_seconds"]
        if not isinstance(raw_timeout, (int, str)):
            raise TypeError("timeout_seconds must be an integer or string representation")
        k_enacted: ParameterTuple = (
            ("operation", entry.operation_kind),
            ("fixed_argv_shape", _argv_shape(parameters["fixed_argv_shape"])),
            ("rehearsal_argv_shape", _argv_shape(values["effective_argv"])),
            ("shell", bool(values["shell"])),
            ("timeout_seconds", int(raw_timeout)),
        )
        return ExecutionEvidence(observed, k_enacted)
    primary = (
        "simulated_pass"
        if entry.semantic_group in {"COMPLETE_GATE", "FOCUSED_SELECTION"}
        else "observed"
    )
    return ExecutionEvidence(
        _project(entry, _base_values(primary=primary)),
        entry.parameter_values,
    )
