"""Bounded, disposable, nonqualification rehearsals for the FIX1 model."""

from __future__ import annotations

from pathlib import Path
import tempfile
import time
from typing import Mapping

from repomap_test_support.test_cov5k_r2_fix1_catalog import CatalogEntry
from repomap_test_support.test_cov5k_r2_fix1_executors import (
    ExecutionEvidence,
    _argv_shape,
    RunnerBinding,
    execute_entry,
    execute_group_k,
    runner_binding_for,
)
from repomap_test_support.test_cov5k_r2_fix1_qualification import (
    FrozenManifest,
    ObservationSession,
    ResultArtifact,
    build_result,
    resolve_owner,
)


def build_runner_registry(
    entries: tuple[CatalogEntry, ...],
) -> Mapping[str, RunnerBinding]:
    """Return exactly one declared binding for every fixed runner identity."""

    registry: dict[str, RunnerBinding] = {}
    for entry in entries:
        declared = runner_binding_for(entry)
        existing = registry.get(entry.fixed_runner_id)
        if existing and existing.semantic_group != entry.semantic_group:
            raise ValueError("runner spans unrelated semantic groups")
        registry[entry.fixed_runner_id] = declared
    return registry


def verify_static_bindings(
    repository_root: Path,
    entries: tuple[CatalogEntry, ...],
    registry: Mapping[str, RunnerBinding],
) -> None:
    """Prove owners, runners, and case-bound argv for the closed catalog."""

    by_executor: dict[str, set[str]] = {}
    for entry in entries:
        resolve_owner(repository_root, entry)
        if entry.pytest_node_id is not None:
            _verify_pytest_node(repository_root, entry.pytest_node_id)
        binding = registry.get(entry.fixed_runner_id)
        if binding is None:
            raise ValueError("fixed runner does not exist")
        argv = binding.argv_builder(entry, repository_root)
        expected = (
            _argv_shape(dict(entry.parameter_values)["rehearsal_argv_shape"])
            if entry.semantic_group == "K"
            else entry.fixed_argv_shape
        )
        if not argv or argv != expected:
            raise ValueError("fixed argv does not match frozen case")
        by_executor.setdefault(entry.evidence_executor_id, set()).add(
            entry.semantic_group
        )
    if any(len(groups) != 1 for groups in by_executor.values()):
        raise ValueError("executor spans unrelated semantic groups")


def _verify_pytest_node(repository_root: Path, node_id: str) -> None:
    path_text, separator, selector = node_id.partition("::")
    if not separator or not selector:
        raise ValueError("pytest node is malformed")
    path = repository_root / path_text
    if not path.is_file():
        raise ValueError("pytest node path does not exist")
    function_name = selector.split("[", 1)[0]
    if f"def {function_name}(" not in path.read_text(encoding="utf-8"):
        raise ValueError("pytest node function does not exist")


def bounded_rehearsal_case_ids(
    entries: tuple[CatalogEntry, ...],
) -> tuple[str, ...]:
    """Select only the FIX1 model rehearsal, never an R3 cohort."""

    selected: list[str] = []
    selected.extend(
        entry.case_id for entry in entries if entry.semantic_group == "A"
    )
    for case_id in (
        "D-driver-psycopg-unavailable",
        "D-driver-psql-unavailable",
        "D-process-current_process",
        "D-container-success",
        "D-terminal-one_read",
    ):
        selected.append(case_id)
    selected.extend(
        entry.case_id for entry in entries if entry.semantic_group == "H"
    )
    selected.extend(
        entry.case_id for entry in entries if entry.semantic_group == "K"
    )
    for case_id in (
        "G-request-origin-0001",
        "G-request-origin-0002",
        "G-close-under-use-0001",
        "G-source-causality-0001",
        "complete-gate-0001",
        "focused-selection-0001",
    ):
        selected.append(case_id)
    return tuple(selected)


def run_bounded_rehearsal(
    repository_root: Path,
    manifest: FrozenManifest,
    session: ObservationSession,
) -> tuple[ResultArtifact, ...]:
    """Execute the forty-one selected verifier rehearsals."""

    by_case = {entry.case_id: entry for entry in manifest.entries}
    results: list[ResultArtifact] = []
    with tempfile.TemporaryDirectory(prefix="repomap-fix1-") as temp:
        root = Path(temp)
        for case_id in bounded_rehearsal_case_ids(manifest.entries):
            entry = by_case[case_id]
            started = time.monotonic_ns()
            evidence = _run_entry(repository_root, root, entry)
            completed = time.monotonic_ns()
            results.append(
                build_result(
                    manifest,
                    session,
                    entry,
                    evidence.observed_fields,
                    enacted_parameters=evidence.enacted_parameters,
                    started_monotonic_ns=started,
                    completed_monotonic_ns=completed,
                )
            )
    return tuple(results)


def _run_entry(
    repository_root: Path,
    temp_root: Path,
    entry: CatalogEntry,
) -> ExecutionEvidence:
    if entry.semantic_group == "K":
        resolve_owner(repository_root, entry)
    return execute_entry(repository_root, temp_root, entry)


_run_group_k = execute_group_k

