"""End-to-end unit coverage for vector orchestration and journal writers."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

import repomap_test_support.w5_experiment_vector as vector_support
import repomap_test_support.w5_experiment_hnsw as hnsw_support
from repomap_test_support.w5_experiment_results import ResultV2Collector
from repomap_test_support.w5_operation_orchestration import (
    DIGEST, FakePostgres, OrchestrationFixture, candidate_arm_stub, exact_stub,
    grade_stub, hnsw_stub, make_fixture,
)
from retrieval_evaluation_attempts import AttemptJournal, admit_attempt
from retrieval_evaluation_grading import ExecutionState
from retrieval_semantic_baseline_result_frames import read_raw_journal_members
from retrieval_semantic_baseline_result_objects import BaselineResultV2
from repomap_test_support.w5_experiment_postgres import PostgresHandle
from retrieval_semantic_experiment_contracts import (
    ExperimentCostLedger, ExperimentRefusal, digest_bytes, make_plan,
)
from retrieval_semantic_experiment_evaluator import SealedComponent
from retrieval_semantic_generator_inputs import PublicGenerationInput
from repomap_test_support.w5_semantic_support import BIND_CORE


def _plan(fixture: OrchestrationFixture, source_digest: str):
    task = fixture.task
    plan = make_plan(
        attempt_id="w5-semantic-g1", generation=1, tasks=(task,),
        input_identity=DIGEST, representation_report_identity=DIGEST,
        publication_identity=DIGEST, artifact_profile_identity=DIGEST,
        controller_admission_sha256=DIGEST,
        source_closure={"orchestration.py": source_digest},
        arms=("exact_vector", "hnsw_vector", "hybrid_rrf"),
    )
    return plan.validate()


def _journal(tmp_path: Path, source: bytes):
    return admit_attempt(
        tmp_path,
        {
            "attempt_id": "w5-semantic-g1",
            "candidate_closure_digests": {"orchestration.py": digest_bytes(source)},
        },
        {"orchestration.py": source},
    )


def _run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, exact_state: ExecutionState,
    exact_reason: str | None = None, hnsw_state: ExecutionState = ExecutionState.NOT_RUN,
    hnsw_creation_error: str | None = None,
) -> tuple[AttemptJournal, BaselineResultV2, ResultV2Collector]:
    fixture = make_fixture()
    monkeypatch.setattr(vector_support, "exact_candidates", exact_stub(exact_state, exact_reason))
    monkeypatch.setattr(vector_support, "build_candidate_rows_arm", candidate_arm_stub)
    monkeypatch.setattr(vector_support, "grade_vector_arm", grade_stub)
    monkeypatch.setattr(
        vector_support, "run_hnsw_binding",
        lambda *args, **kwargs: hnsw_stub(
            *args, state=hnsw_state, creation_error=hnsw_creation_error, **kwargs
        ),
    )
    source = b"public orchestration fixture\n"
    journal = _journal(tmp_path, source)
    plan = _plan(fixture, digest_bytes(source))
    collector = ResultV2Collector(plan)
    sink = collector.add_cell
    costs = ExperimentCostLedger()
    failure_code: str | None = None
    for repetition in range(1, plan.repetitions + 1):
        try:
            vector_support.run_vector_task(
                journal, cast(PostgresHandle, FakePostgres()), fixture.publication,
                cast(SealedComponent, fixture.sealed),
                cast(PublicGenerationInput, fixture.inputs), fixture.task, repetition,
                pin=fixture.pin, rebuild_id="rebuild-1", attempt_identity=plan.attempt_id,
                lexical_arm=fixture.lexical_arm, costs=costs, result_cell_sink=sink,
            )
        except ExperimentRefusal as error:
            if failure_code is not None and error.code != failure_code:
                raise AssertionError("repetitions produced different refusal codes")
            failure_code = error.code
    if failure_code is not None:
        journal.finish("failed", {"status": "failed", "failure_code": failure_code})
        result = collector.finish(
            status="failed", failure_code=failure_code,
            raw_journal_members=read_raw_journal_members(journal.directory),
        )
        return journal, result, collector
    journal.finish("completed", {"status": "completed"})
    result = collector.finish(
        status="completed", raw_journal_members=read_raw_journal_members(journal.directory),
    )
    return journal, result, collector


def test_vector_orchestration_writes_real_journal_and_result_v2_cells(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal, result, _collector = _run(
        tmp_path, monkeypatch, exact_state=ExecutionState.COMPLETED,
    )
    assert journal.observation_count == 24
    assert len(result.cells) == 9
    observations = (journal.directory / "observations.jsonl").read_text(encoding="utf-8")
    assert observations.count('"observed_operation"') == 9
    assert '"node_types":["Limit","Seq Scan"]' in observations
    hnsw = [cell for cell in result.cells if cast(dict[str, object], cell["identity"])["arm_id"] == "hnsw_vector"]
    assert len(hnsw) == 3
    assert {cast(dict[str, object], cell["cell"])["execution_state"] for cell in hnsw} == {"not_run"}


def test_exact_unavailable_preserves_blocked_hybrid_and_result_v2_cells(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal, result, _collector = _run(
        tmp_path, monkeypatch, exact_state=ExecutionState.UNAVAILABLE,
        exact_reason="candidate_store_unavailable",
    )
    assert result.status == "failed"
    assert result.failure_code == "admitted_exact_query_not_executed"
    assert len(result.cells) == 9
    assert {
        (cast(dict[str, object], cell["identity"])["arm_id"], cast(dict[str, object], cell["cell"])["execution_state"])
        for cell in result.cells
    } == {("exact_vector", "unavailable"), ("hybrid_rrf", "unavailable"), ("hnsw_vector", "not_run")}
    observations = (journal.directory / "observations.jsonl").read_text(encoding="utf-8")
    assert '"arm_id":"hybrid_rrf"' in observations
    assert '"query_descriptor_sha256":null' in observations
    assert '"operation":"vector_query_not_attempted"' in observations
    assert '"selected_binding_ids":[]' in observations


def test_hnsw_failure_is_retained_before_mechanical_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal, result, _collector = _run(
        tmp_path, monkeypatch, exact_state=ExecutionState.COMPLETED,
        hnsw_state=ExecutionState.FAILED,
    )
    assert result.status == "failed"
    assert result.failure_code == "admitted_hnsw_execution_failed"
    assert len(result.cells) == 9
    assert {
        (cast(dict[str, object], cell["identity"])["arm_id"], cast(dict[str, object], cell["cell"])["execution_state"])
        for cell in result.cells
    } == {("exact_vector", "completed"), ("hybrid_rrf", "completed"), ("hnsw_vector", "failed")}
    observations = (journal.directory / "observations.jsonl").read_text(encoding="utf-8")
    assert '"arm_id":"hnsw_vector"' in observations
    assert '"execution_state":"failed"' in observations


def test_hnsw_creation_failure_has_no_query_result_or_plan() -> None:
    fixture = make_fixture()
    observation, _creation, _cleanup, _index_ns, _cleanup_ns, receipt = hnsw_stub(
        FakePostgres(), fixture.publication, fixture.profile, task_id=fixture.task.task_id,
        source_binding_id="bind1:" + "1" * 64, state=ExecutionState.FAILED,
        creation_error="hnsw_index_creation_failed",
    )
    assert observation.cell.execution_state is ExecutionState.FAILED
    assert observation.plan == {} and observation.result is None
    assert receipt["creation_error"] == "hnsw_index_creation_failed"


def test_hnsw_creation_failure_is_retained_without_result_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal, result, _collector = _run(
        tmp_path, monkeypatch, exact_state=ExecutionState.COMPLETED,
        hnsw_state=ExecutionState.FAILED,
        hnsw_creation_error="hnsw_index_creation_failed",
    )
    assert result.status == "failed"
    assert len(result.cells) == 9
    observations = (journal.directory / "observations.jsonl").read_text(encoding="utf-8")
    assert '"creation_error":"hnsw_index_creation_failed"' in observations
    assert '"result_state":null' in observations


@pytest.mark.parametrize("invalid_vector", [False, True])
def test_actual_hnsw_failure_paths_never_issue_followup_query(
    monkeypatch: pytest.MonkeyPatch, invalid_vector: bool,
) -> None:
    fixture = make_fixture()
    creations: list[bool] = []

    def creation_failure(*args: object, **kwargs: object) -> None:
        creations.append(True)
        raise RuntimeError("public creation fixture")

    def unexpected_query(*args: object, **kwargs: object) -> None:
        raise AssertionError("failed admission or creation must not issue a query")

    monkeypatch.setattr(hnsw_support, "create_hnsw_index", creation_failure)
    monkeypatch.setattr(hnsw_support, "hnsw_candidates", unexpected_query)
    observation, creation, cleanup, _index_ns, _cleanup_ns, receipt = hnsw_support.run_hnsw_binding(
        cast(PostgresHandle, FakePostgres()), fixture.publication, replace(fixture.profile, dimensions=384),
        rebuild_id="rebuild-1", vector=(1.0,) if invalid_vector else (1.0,) + (0.0,) * 383,
        task_id=fixture.task.task_id, source_binding_id=BIND_CORE,
        publication_pin=fixture.pin, attempt_identity="w5-semantic-g1",
    )
    assert observation.cell.execution_state is (
        ExecutionState.REFUSED if invalid_vector else ExecutionState.FAILED
    )
    assert creations == ([] if invalid_vector else [True])
    assert observation.result is None and observation.plan == {}
    assert creation is None and cleanup is None
    assert (receipt["query_digest"] is None) is invalid_vector
