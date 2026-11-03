"""Pure graph work collection and bounded-scope envelope contracts."""
from __future__ import annotations

from pathlib import Path
from typing import NoReturn

import pytest

from common_lore_index.retrieval import query_contracts as qc
from repomap_test_support.retrieval_evaluation_fixture import binding_id_for_alias
from retrieval_evaluation_accounting import ByteLayerAccounting
import retrieval_evaluation_correspondence_graph_scope as graph_scope
from retrieval_evaluation_correspondence_observation_records import FencedObservationResult
from retrieval_evaluation_grading import ExecutionState
from retrieval_evaluation_schema import EvaluationTask, load_task_catalog


def _task() -> EvaluationTask:
    root = Path(__file__).resolve().parents[5]
    catalog = load_task_catalog(root / "src/test/fixtures/retrieval_evaluation/mixed-v1/tasks/catalog-v1.json")
    return next(task for task in catalog.calibration_tasks() if task.task_id == "cal-23")


def _envelope(task: EvaluationTask) -> qc.QueryEnvelope:
    return qc.QueryEnvelope(
        contract_version=qc.QUERY_CONTRACT_VERSION,
        requested_mode=qc.QueryMode.CURRENT_LITERAL_ENUMERATION,
        effective_mode=qc.QueryMode.CURRENT_LITERAL_ENUMERATION,
        match_surface=qc.MatchSurface.STORED_METADATA,
        scope=qc.QueryScope(
            graph_id=task.graph_id, backend="sqlite",
            selected_binding_ids=tuple(binding_id_for_alias(alias, task.graph_id) for alias in task.selected_bindings),
        ),
        ordering_policy_version=qc.DEFAULT_ORDERING_POLICY_VERSION,
        capability_state=qc.CapabilityState.AVAILABLE,
        hits=(), scope_complete=True,
    ).validate()


def _read_result() -> FencedObservationResult:
    omission = qc.OmissionRecord("scope", None, "observation_page_limit", "bounded page").validate()
    return FencedObservationResult(
        backend="sqlite", graph_id="mixed-v1", repository_identity="repo1:public-fixture",
        accepted_run_id=2, accepted_generation=2,
        publication_bundle_id="bundle1:" + "1" * 64,
        snapshot_manifest_id="snapmanifest1:" + "2" * 64,
        rows=(), omissions=(omission,), scope_complete=False, has_more=True,
        fence_elapsed_ns=5, query_statement_ns=7, known_payload_bytes=10,
    )


def test_scope_omissions_propagate_without_changing_execution_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    task, read = _task(), _read_result()
    original = _envelope(task)
    monkeypatch.setattr(graph_scope, "_query", lambda *_args, **_kwargs: read)

    def execute(*_args: object, **_kwargs: object) -> tuple[ExecutionState, qc.QueryEnvelope, int, ByteLayerAccounting]:
        graph_scope.query_fenced_current_observations(
            tmp_path, task_scope=task, graph_id=task.graph_id, query=task.permitted_query_plan["query"],
        )
        return ExecutionState.COMPLETED, original, 100, ByteLayerAccounting(0)

    with graph_scope.collect_graph_execution_work() as observed:
        state, envelope, elapsed, accounting = graph_scope.bind_graph_execution(execute)(task, tmp_path)
    assert state == ExecutionState.COMPLETED and elapsed == 100
    assert accounting == ByteLayerAccounting(0)
    assert (envelope.scope, envelope.requested_mode, envelope.match_surface, envelope.hits) == (
        original.scope, original.requested_mode, original.match_surface, original.hits,
    )
    assert envelope.capability_state == qc.CapabilityState.PARTIAL
    assert envelope.scope_complete is False and envelope.omissions == read.omissions
    assert len(observed) == 1
    work = observed[0].to_dict()
    assert work["execution_ns"] == 100
    assert work["standalone_fence_ns"] == 5
    assert work["adapter_ns_excluding_standalone_fence"] == 95
    assert work["atomic_scope_and_query_statement_ns"] == 7
    assert work["known_payload_bytes"] == 10 and work["database_wire_bytes"] is None


def test_query_exception_keeps_measured_time_and_unknown_partial_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _task()
    original_error = RuntimeError("controlled query failure")
    monkeypatch.setattr(graph_scope, "_query", lambda *_args, **_kwargs: _read_result())

    def execute(*_args: object, **_kwargs: object) -> NoReturn:
        graph_scope.query_fenced_current_observations(
            tmp_path, task_scope=task, graph_id=task.graph_id, query=task.permitted_query_plan["query"],
        )
        raise original_error

    with graph_scope.collect_graph_execution_work() as observed:
        with pytest.raises(RuntimeError) as caught:
            graph_scope.bind_graph_execution(execute)(task, tmp_path)
    assert caught.value is original_error
    assert len(observed) == 1
    work = observed[0].to_dict()
    execution_ns = work["execution_ns"]
    assert work["failed"] is True
    assert isinstance(execution_ns, int) and execution_ns > 0
    assert work["standalone_fence_ns"] is None
    assert work["atomic_scope_and_query_statement_ns"] is None
    assert work["known_payload_bytes"] is None


def test_task_scope_rejects_a_different_requested_binding_before_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = []
    monkeypatch.setattr(graph_scope, "_query", lambda *_args, **_kwargs: called.append(True))
    with pytest.raises(ValueError, match="task binding scope mismatch"):
        graph_scope.query_fenced_current_observations(
            tmp_path, task_scope=_task(), graph_id="mixed-v1", query="token",
            selected_binding_ids=("bind1:foreign",),
        )
    assert called == []
