"""Evaluator graph scope, omission propagation, and measured work components."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from functools import wraps
from pathlib import Path
from time import perf_counter_ns
from typing import Any

from common_lore_index.retrieval.query_contracts import CapabilityState
from repomap_test_support.retrieval_evaluation_fixture import binding_id_for_alias
from retrieval_evaluation_current_observations import (
    FencedObservationResult,
    query_fenced_current_observations as _query,
)
from retrieval_evaluation_schema import EvaluationTask
from retrieval_evaluation_observation_contracts import ObservationPublicationPin


@dataclass(frozen=True)
class GraphExecutionWork:
    """Measured components of one adapter execution; components are not additive totals."""

    execution_ns: int
    standalone_fence_ns: int | None
    atomic_statement_ns: int | None
    known_payload_bytes: int | None
    returned_observation_rows: int
    failed: bool = False

    def to_dict(self) -> dict[str, object]:
        for value in (
            self.execution_ns, self.returned_observation_rows,
        ):
            if type(value) is not int or value < 0:
                raise ValueError("invalid graph work measurement")
        for optional_value in (self.standalone_fence_ns, self.atomic_statement_ns, self.known_payload_bytes):
            if optional_value is not None and (type(optional_value) is not int or optional_value < 0):
                raise ValueError("invalid graph optional measurement")
        if type(self.failed) is not bool:
            raise ValueError("invalid graph work outcome")
        if self.standalone_fence_ns is not None and self.standalone_fence_ns > self.execution_ns:
            raise ValueError("fence time exceeds its enclosing execution")
        return {
            "schema": "cloe-w5-graph-execution-work-v1",
            "execution_ns": self.execution_ns,
            "standalone_fence_ns": self.standalone_fence_ns,
            "adapter_ns_excluding_standalone_fence": (
                None if self.standalone_fence_ns is None else self.execution_ns - self.standalone_fence_ns
            ),
            "atomic_scope_and_query_statement_ns": self.atomic_statement_ns,
            "known_payload_bytes": self.known_payload_bytes,
            "database_wire_bytes": None,
            "returned_observation_rows": self.returned_observation_rows,
            "failed": self.failed,
            "timing_relationship": "fence_and_atomic_statement_are_execution_components",
            "execution_time_basis": "failure_wrapper_wall" if self.failed else "legacy_adapter_elapsed",
        }


_READS: ContextVar[list[FencedObservationResult] | None] = ContextVar("w5_graph_reads", default=None)
_WORK: ContextVar[list[GraphExecutionWork] | None] = ContextVar("w5_graph_work", default=None)


@contextmanager
def collect_graph_execution_work() -> Iterator[list[GraphExecutionWork]]:
    """Collect only observations made inside the current baseline callback."""
    observed: list[GraphExecutionWork] = []
    token = _WORK.set(observed)
    try:
        yield observed
    finally:
        _WORK.reset(token)


def query_fenced_current_observations(
    config_or_home: Any,
    *,
    task_scope: EvaluationTask | None = None,
    **kwargs: Any,
) -> FencedObservationResult:
    """Apply the actual task scope before the backend's bounded result page."""
    if task_scope is not None:
        selected = tuple(binding_id_for_alias(alias, task_scope.graph_id) for alias in task_scope.selected_bindings)
        if "selected_binding_ids" in kwargs and tuple(kwargs["selected_binding_ids"]) != selected:
            raise ValueError("task binding scope mismatch")
        if "source_path_prefix" in kwargs and kwargs["source_path_prefix"] != task_scope.source_path_prefix:
            raise ValueError("task path scope mismatch")
        kwargs["selected_binding_ids"] = selected
        kwargs["source_path_prefix"] = task_scope.source_path_prefix
    result = _query(config_or_home, **kwargs)
    reads = _READS.get()
    if reads is not None:
        reads.append(result)
    return result


def _record_work(reads: list[FencedObservationResult], elapsed: int, *, failed: bool) -> None:
    sink = _WORK.get()
    if sink is None:
        return
    payload_sizes = [item.known_payload_bytes for item in reads]
    statement_times = [item.query_statement_ns for item in reads]
    known_bytes = sum(value for value in payload_sizes if value is not None) if not failed and all(
        value is not None for value in payload_sizes
    ) else None
    work = GraphExecutionWork(
        execution_ns=elapsed,
        standalone_fence_ns=None if failed else sum(item.fence_elapsed_ns for item in reads),
        atomic_statement_ns=(
            sum(value for value in statement_times if value is not None)
            if not failed and all(value is not None for value in statement_times) else None
        ),
        known_payload_bytes=known_bytes,
        returned_observation_rows=sum(len(item.rows) for item in reads),
        failed=failed,
    )
    work.to_dict()
    sink.append(work)


def bind_graph_execution(execute: Callable[..., tuple[Any, Any, int, Any]]) -> Callable[..., tuple[Any, Any, int, Any]]:
    """Preserve the four-tuple API while recording scope omissions and query work."""
    @wraps(execute)
    def run(
        task: EvaluationTask,
        home_root: Path,
        *,
        psql_command: str = "psql",
        expected_pin: ObservationPublicationPin | None = None,
    ) -> tuple[Any, Any, int, Any]:
        reads: list[FencedObservationResult] = []
        token = _READS.set(reads)
        started = perf_counter_ns()
        try:
            state, envelope, elapsed, accounting = execute(
                task, home_root, psql_command=psql_command, expected_pin=expected_pin,
            )
        except BaseException:
            _record_work(reads, perf_counter_ns() - started, failed=True)
            raise
        finally:
            _READS.reset(token)
        read_omissions = tuple(item for read in reads for item in read.omissions)
        omissions: list[Any] = []
        for omission in (*envelope.omissions, *read_omissions):
            if omission not in omissions:
                omissions.append(omission)
        complete = envelope.scope_complete and all(read.scope_complete for read in reads)
        if omissions or complete != envelope.scope_complete:
            capability = envelope.capability_state
            if capability == CapabilityState.AVAILABLE and not complete:
                capability = CapabilityState.PARTIAL
            envelope = replace(
                envelope, omissions=tuple(omissions),
                scope_complete=complete, capability_state=capability,
            ).validate()
        _record_work(reads, elapsed, failed=False)
        return state, envelope, elapsed, accounting

    return run


__all__ = [
    "GraphExecutionWork", "bind_graph_execution", "collect_graph_execution_work",
    "query_fenced_current_observations",
]
