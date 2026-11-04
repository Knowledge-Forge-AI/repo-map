"""Provenance-shaped HNSW operation records for non-completed results."""

from __future__ import annotations

from typing import cast

import pytest

from common_lore_index.storage.authority import GraphRunId
from common_lore_index.storage.publication_readback import RunPublicationRecord
from common_lore_index.storage.semantic_candidates import (
    CandidatePublication, CandidateQuery, EmbeddingProfile,
)
from repomap_test_support.w5_experiment_postgres import HNSW_OWNER_ROLE, HnswObservation
from repomap_test_support.w5_semantic_support import (
    BIND_COMP, BIND_CORE, make_w5_calibration_task, make_w5_verified_pin,
)
from retrieval_evaluation_grading import ExecutionState
from retrieval_evaluation_schema import EvaluationTask
from retrieval_semantic_ann import HnswEvaluationQuery
from retrieval_semantic_ann_models import (
    HnswExecutionState, HnswPlanSummary, HnswProvenance, HnswResult,
)
from retrieval_semantic_experiment_contracts import ExperimentCell, digest_json
from retrieval_semantic_observed_operation import finalize_observed_operation
from retrieval_semantic_observed_operation_capture import make_hnsw_operation
from retrieval_semantic_provenance import VerifiedPublicationPin


_DIGEST = "sha256:" + "a" * 64
_BASELINE_SQL_DIGEST = "sha256:" + "b" * 64
_ATTEMPT = "w5-semantic-g1"


def _fixture() -> tuple[
    VerifiedPublicationPin, CandidatePublication, EmbeddingProfile, HnswProvenance,
    HnswPlanSummary, dict[str, object],
]:
    pin = make_w5_verified_pin(
        backend="postgresql", selected_binding_ids=(BIND_CORE,), run_id=1,
    )
    publication = CandidatePublication(
        pin.repository_identity,
        RunPublicationRecord(GraphRunId(pin.run_id), pin.receipt),
    )
    profile = EmbeddingProfile("fixture-model", "5", "fixture-generator", "1", 384)
    vector = (1.0,) + (0.0,) * 383
    candidate_query = CandidateQuery(
        publication, profile, "rebuild-1", vector, selected=True, limit=20,
        evidence_limit=5, source_binding_id=BIND_CORE,
    )
    evaluation = HnswEvaluationQuery(
        candidate_query, pin, _ATTEMPT, owner_identity=HNSW_OWNER_ROLE,
    ).validate()
    spec = evaluation.index_spec
    provenance = HnswProvenance(
        publication.repository_identity, publication.publication.run_id,
        publication.receipt_identity, profile.identity, "rebuild-1", spec.name,
        spec.query_digest, _ATTEMPT, evaluation.public_source_scope, 384, 40,
        "off", 500, HNSW_OWNER_ROLE, _BASELINE_SQL_DIGEST,
    )
    not_run_plan = HnswPlanSummary(
        ("Limit", "Seq Scan"), (), 0, 0.1, 0.2, 4, 0,
        False, True, False,
    )
    receipt: dict[str, object] = {
        "attempt_identity": _ATTEMPT, "query_digest": spec.query_digest,
        "creation": {"index_name": spec.name},
        "cleanup": {"status": "verified_absent"},
    }
    return pin, publication, profile, provenance, not_run_plan, receipt


def _observation(
    task_id: str, state: ExecutionState, result_state: HnswExecutionState,
    reason: str, provenance: HnswProvenance, plan: HnswPlanSummary | None,
) -> HnswObservation:
    result = HnswResult(result_state, reason, (), plan, None, provenance)
    plan_mapping = None if plan is None else plan.to_dict()
    return HnswObservation(
        ExperimentCell("hnsw_vector", task_id, state, reason, cleanup_status="verified"),
        plan_mapping, "" if plan_mapping is None else digest_json(plan_mapping), result=result,
    )


@pytest.mark.parametrize(
    ("state", "result_state", "reason", "plan_factory"),
    [
        (ExecutionState.NOT_RUN, HnswExecutionState.NOT_RUN, "hnsw_index_not_selected", "not_run"),
        (ExecutionState.UNAVAILABLE, HnswExecutionState.UNAVAILABLE, "hnsw_catalog_unavailable", "none"),
        (ExecutionState.FAILED, HnswExecutionState.FAILED, "hnsw_query_failed", "none"),
    ],
)
def test_noncompleted_real_provenance_is_retained_without_ann_credit(
    state: ExecutionState, result_state: HnswExecutionState, reason: str,
    plan_factory: str,
) -> None:
    pin, publication, profile, provenance, not_run_plan, receipt = _fixture()
    plan = not_run_plan if plan_factory == "not_run" else None
    observation = _observation("w5-cal-01", state, result_state, reason, provenance, plan)
    operation = make_hnsw_operation(
        _task(), 1, publication=publication, pin=pin, profile=profile,
        rebuild_id="rebuild-1", vector=(1.0,) + (0.0,) * 383,
        task_sha256=_DIGEST,
        results={BIND_CORE: (observation, None, None, 0, 0, receipt)},
        exact_state=ExecutionState.COMPLETED, exact_count=1,
    )
    record = finalize_observed_operation(operation)
    actual = cast(dict[str, object], record["actual"])
    item = cast(dict[str, object], cast(list[object], cast(dict[str, object], record["work"])["hnsw"])[0])
    assert record["state"] == state.value != "completed"
    assert actual["selected_binding_ids"] == [BIND_CORE]
    assert item["result_state"] == result_state.value
    expected_provenance = provenance.to_dict()
    expected_provenance.pop("owner_identity")
    assert item["provenance"] == expected_provenance
    assert item["provenance"] is not None


def _task() -> EvaluationTask:
    return make_w5_calibration_task(
        task_id="w5-cal-01", selected_bindings=(BIND_CORE,), generation=1,
    )


def test_missing_hnsw_result_is_nullable_and_distinct_from_raw_failure() -> None:
    pin, publication, profile, _provenance, _plan, receipt = _fixture()
    observation = HnswObservation(
        ExperimentCell(
            "hnsw_vector", "w5-cal-01", ExecutionState.FAILED,
            "hnsw_index_creation_failed", cleanup_status="not_applicable",
        ),
        {}, "", result=None,
    )
    receipt.pop("creation")
    receipt.pop("cleanup")
    receipt["creation_error"] = "hnsw_index_creation_failed"
    operation = make_hnsw_operation(
        _task(), 1, publication=publication, pin=pin, profile=profile,
        rebuild_id="rebuild-1", vector=(1.0,) + (0.0,) * 383,
        task_sha256=_DIGEST,
        results={BIND_CORE: (observation, None, None, 0, 0, receipt)},
        exact_state=ExecutionState.COMPLETED, exact_count=1,
    )
    record = finalize_observed_operation(operation)
    item = cast(dict[str, object], cast(list[object], cast(dict[str, object], record["work"])["hnsw"])[0])
    assert record["state"] == "failed"
    assert item["cell_state"] == "failed"
    assert item["result_state"] is None
    assert item["result_reason"] is None
    assert item["provenance"] is None


def test_hnsw_aggregate_reason_matches_the_failed_binding() -> None:
    bindings = (BIND_CORE, BIND_COMP)
    pin = make_w5_verified_pin(backend="postgresql", selected_binding_ids=bindings, run_id=1)
    publication = CandidatePublication(pin.repository_identity, RunPublicationRecord(GraphRunId(pin.run_id), pin.receipt))
    profile = EmbeddingProfile("fixture-model", "5", "fixture-generator", "1", 384)
    task = make_w5_calibration_task(task_id="w5-cal-01", selected_bindings=bindings, generation=1)
    results = {}
    for binding, state, reason in (
        (BIND_CORE, ExecutionState.NOT_RUN, "hnsw_index_not_selected"),
        (BIND_COMP, ExecutionState.FAILED, "hnsw_cleanup_failed"),
    ):
        observation = HnswObservation(ExperimentCell("hnsw_vector", task.task_id, state, reason), {}, "")
        results[binding] = (observation, None, None, 0, 0, {"attempt_identity": _ATTEMPT})
    operation = make_hnsw_operation(
        task, 1, publication=publication, pin=pin, profile=profile, rebuild_id="rebuild-1",
        vector=(1.0,) + (0.0,) * 383, task_sha256=_DIGEST, results=results,
        exact_state=ExecutionState.COMPLETED, exact_count=1,
    )
    assert operation["state"] == "failed"
    assert operation["reason"] == "hnsw_cleanup_failed"
