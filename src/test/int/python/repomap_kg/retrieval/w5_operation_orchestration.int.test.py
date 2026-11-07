"""Container-owner proof for the W5 vector orchestration writer boundary."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

import repomap_test_support.w5_experiment_vector as vector_support
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


def _plan(fixture: OrchestrationFixture, source_digest: str):
    return make_plan(
        attempt_id="w5-semantic-g1", generation=1, tasks=(fixture.task,),
        input_identity=DIGEST, representation_report_identity=DIGEST,
        publication_identity=DIGEST, artifact_profile_identity=DIGEST,
        controller_admission_sha256=DIGEST,
        source_closure={"orchestration.py": source_digest},
        arms=("exact_vector", "hnsw_vector", "hybrid_rrf"),
    ).validate()


def _journal(root: Path, source: bytes):
    return admit_attempt(
        root,
        {
            "attempt_id": "w5-semantic-g1",
            "candidate_closure_digests": {"orchestration.py": digest_bytes(source)},
        },
        {"orchestration.py": source},
    )


def _run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *,
    exact_state: ExecutionState = ExecutionState.COMPLETED,
    exact_reason: str | None = None,
    hnsw_state: ExecutionState = ExecutionState.NOT_RUN,
    hnsw_cleanup_status: str = "verified_absent",
    hnsw_creation_error: str | None = None,
) -> tuple[AttemptJournal, BaselineResultV2]:
    fixture = make_fixture()
    monkeypatch.setattr(vector_support, "exact_candidates", exact_stub(exact_state, exact_reason))
    monkeypatch.setattr(vector_support, "build_candidate_rows_arm", candidate_arm_stub)
    monkeypatch.setattr(vector_support, "grade_vector_arm", grade_stub)
    monkeypatch.setattr(
        vector_support,
        "run_hnsw_binding",
        lambda *args, **kwargs: hnsw_stub(
            *args, state=hnsw_state, cleanup_status=hnsw_cleanup_status,
            creation_error=hnsw_creation_error, **kwargs
        ),
    )
    source = b"public orchestration integration fixture\n"
    journal = _journal(tmp_path, source)
    plan = _plan(fixture, digest_bytes(source))
    collector = ResultV2Collector(plan)
    costs = ExperimentCostLedger()
    failure_code: str | None = None
    for repetition in range(1, plan.repetitions + 1):
        try:
            vector_support.run_vector_task(
                journal, cast(PostgresHandle, FakePostgres()), fixture.publication,
                cast(SealedComponent, fixture.sealed),
                cast(PublicGenerationInput, fixture.inputs), fixture.task, repetition,
                pin=fixture.pin, rebuild_id="rebuild-1", attempt_identity=plan.attempt_id,
                lexical_arm=fixture.lexical_arm, costs=costs,
                result_cell_sink=collector.add_cell,
            )
        except ExperimentRefusal as error:
            if failure_code is not None and error.code != failure_code:
                raise AssertionError("repetitions produced different refusal codes")
            failure_code = error.code
    if failure_code is not None:
        journal.finish("failed", {"status": "failed", "failure_code": failure_code})
        return journal, collector.finish(
            status="failed", failure_code=failure_code,
            raw_journal_members=read_raw_journal_members(journal.directory),
        )
    journal.finish("completed", {"status": "completed"})
    return journal, collector.finish(
        status="completed", raw_journal_members=read_raw_journal_members(journal.directory),
    )


def test_completed_hnsw_operation_is_written_with_plan_and_fusion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal, result = _run(tmp_path, monkeypatch, hnsw_state=ExecutionState.COMPLETED)
    assert result.status == "completed"
    assert len(result.cells) == 9
    observations = (journal.directory / "observations.jsonl").read_text(encoding="utf-8")
    assert observations.count('"observed_operation"') == 9
    assert '"operation":"hnsw_vector_sql"' in observations
    assert '"used_expected_index":true' in observations


def test_refused_exact_keeps_hybrid_unattempted_and_hnsw_not_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal, result = _run(
        tmp_path, monkeypatch, exact_state=ExecutionState.REFUSED,
        exact_reason="source_scope_refused",
    )
    assert result.status == "failed"
    assert result.failure_code == "admitted_exact_query_not_executed"
    assert len(result.cells) == 9
    assert {
        (cast(dict[str, object], cell["identity"])["arm_id"], cast(dict[str, object], cell["cell"])["execution_state"])
        for cell in result.cells
    } == {("exact_vector", "refused"), ("hybrid_rrf", "refused"), ("hnsw_vector", "not_run")}
    observations = (journal.directory / "observations.jsonl").read_text(encoding="utf-8")
    assert '"reason":"binding_refused"' in observations
    assert '"query_descriptor_sha256":null' in observations
    assert '"operation":"vector_query_not_attempted"' in observations
    assert '"operation":"hnsw_vector_sql"' in observations


def test_cleanup_failure_retains_hnsw_result_and_cleanup_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal, result = _run(
        tmp_path, monkeypatch, hnsw_state=ExecutionState.FAILED,
        hnsw_cleanup_status="failed",
    )
    assert result.status == "failed"
    assert result.failure_code == "admitted_hnsw_execution_failed"
    assert len(result.cells) == 9
    assert {
        (cast(dict[str, object], cell["identity"])["arm_id"], cast(dict[str, object], cell["cell"])["execution_state"])
        for cell in result.cells
    } == {("exact_vector", "completed"), ("hybrid_rrf", "completed"), ("hnsw_vector", "failed")}
    observations = (journal.directory / "observations.jsonl").read_text(encoding="utf-8")
    assert '"cleanup_state":"failed"' in observations
    assert '"result_state":"completed"' in observations


def test_creation_failure_does_not_issue_hnsw_query() -> None:
    fixture = make_fixture()
    observation, _creation, _cleanup, _index_ns, _cleanup_ns, receipt = hnsw_stub(
        FakePostgres(), fixture.publication, fixture.profile, task_id=fixture.task.task_id,
        source_binding_id="bind1:" + "1" * 64, state=ExecutionState.FAILED,
        creation_error="hnsw_index_creation_failed",
    )
    assert observation.cell.execution_state is ExecutionState.FAILED
    assert observation.plan == {} and observation.result is None
    assert receipt["creation_error"] == "hnsw_index_creation_failed"


def test_creation_failure_is_retained_without_result_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal, result = _run(
        tmp_path, monkeypatch, hnsw_state=ExecutionState.FAILED,
        hnsw_creation_error="hnsw_index_creation_failed",
    )
    assert result.status == "failed"
    assert len(result.cells) == 9
    observations = (journal.directory / "observations.jsonl").read_text(encoding="utf-8")
    assert '"creation_error":"hnsw_index_creation_failed"' in observations
    assert '"result_state":null' in observations
