"""Capture-boundary tests for observed SQL, fusion, and cleanup records."""

from __future__ import annotations

from dataclasses import replace
from collections.abc import Sequence
from types import SimpleNamespace
from typing import cast

import pytest

from common_lore_index.storage.authority import GraphRunId
from common_lore_index.storage.publication_readback import RunPublicationRecord
from common_lore_index.storage.semantic_candidates import (
    CandidatePublication, CandidateQuery, CandidateResult, EmbeddingProfile,
)
from repomap_test_support import w5_experiment_postgres as postgres_support
from repomap_test_support.w5_experiment_postgres import HnswObservation
from repomap_test_support.w5_semantic_support import (
    BIND_COMP, BIND_CORE, SNAP_CORE_G1,
    make_w5_calibration_task, make_w5_verified_pin,
)
from retrieval_evaluation_grading import ExecutionState
from retrieval_semantic_ann_models import (
    HnswExecutionState, HnswPlanSummary, HnswProvenance, HnswRecallSummary, HnswResult,
)
from retrieval_semantic_experiment_contracts import ExperimentCell, ExperimentRefusal, digest_json
from retrieval_semantic_experiment_evaluator import grade_vector_arm
from retrieval_semantic_ann_plan import parse_hnsw_explain
from retrieval_semantic_fusion import (
    AdmittedArmObservation, FileFusionResult, FileIdentityTuple, fuse_arm_observations_rrf,
)
from retrieval_semantic_observed_operation_capture import (
    _hnsw_binding_work, make_exact_operation, make_hnsw_operation, make_hybrid_operation,
)
from retrieval_semantic_observed_operation import _validate_plan
from repomap_test_support.w5_experiment_journal import record_cell
from repomap_test_support.w5_experiment_support import combine_scoped_cells
from retrieval_semantic_provenance import VerifiedPublicationPin
from retrieval_evaluation_schema import EvaluationTask


_DIGEST = "sha256:" + "a" * 64


class _FakePostgres:
    psql_command = "psql"
    psql_args: Sequence[str] = ()

    def psql_scalar(self, sql: str) -> str:
        raise AssertionError("the query transport should be replaced in this unit")


def _fixture(
    *, selected_bindings: tuple[str, ...] = (BIND_CORE,),
) -> tuple[EvaluationTask, VerifiedPublicationPin, CandidatePublication, EmbeddingProfile]:
    task = make_w5_calibration_task(selected_bindings=selected_bindings)
    pin = make_w5_verified_pin(backend="postgresql", selected_binding_ids=selected_bindings)
    publication = CandidatePublication(
        pin.repository_identity, RunPublicationRecord(GraphRunId(pin.run_id), pin.receipt)
    )
    profile = EmbeddingProfile("fixture-model", "1", "fixture-generator", "1", 3)
    return task, pin, publication, profile


def _fusion(pin: VerifiedPublicationPin, arm_id: str) -> FileFusionResult:
    file_hit = FileIdentityTuple(BIND_CORE, SNAP_CORE_G1, "pkg/a.py")
    arm = AdmittedArmObservation(
        arm_id=arm_id, mode="ranked_discovery", verified_pin=pin,
        selected_binding_ids=(BIND_CORE,), raw_file_hits=((file_hit, 1, "chunk:1"),),
    )
    return fuse_arm_observations_rrf(
        (arm,), expected_pin=pin, allow_explicit_single_arm_fallback=True,
    )


def test_exact_candidate_observer_receives_validated_query_and_digest(monkeypatch: pytest.MonkeyPatch) -> None:
    _task, pin, publication, profile = _fixture()
    observed: list[tuple[CandidateQuery, str]] = []
    monkeypatch.setattr(
        postgres_support, "_query", lambda _postgres, _query: CandidateResult("ok", None, ()),
    )
    cell, rows = postgres_support.exact_candidates(
        _FakePostgres(), publication, profile,
        rebuild_id="rebuild-1", vector=(1.0, 0.0, 0.0), task_id="task-1",
        publication_pin=pin, source_binding_id=BIND_CORE,
        query_observer=lambda query, digest: observed.append((query, digest)),
    )
    assert cell.execution_state is ExecutionState.COMPLETED
    assert rows == () and len(observed) == 1
    query, descriptor = observed[0]
    assert query.source_binding_id == BIND_CORE
    assert descriptor.startswith("sha256:")


def test_nested_plan_parser_preserves_repeated_actual_node_labels() -> None:
    summary = parse_hnsw_explain(
        [{
            "Plan": {
                "Node Type": "Nested Loop", "Actual Rows": 2,
                "Plans": [
                    {"Node Type": "Index Scan", "Index Name": "w5_hnsw_fixture", "Order By": "embedding <=> query"},
                    {"Node Type": "Index Scan", "Index Name": "w5_hnsw_fixture", "Order By": "embedding <=> query"},
                ],
            },
            "Planning Time": 0.1, "Execution Time": 0.2,
        }],
        expected_index_name="w5_hnsw_fixture",
    )
    assert summary.node_types == ("Nested Loop", "Index Scan", "Index Scan")
    assert summary.index_names == ("w5_hnsw_fixture", "w5_hnsw_fixture")
    assert _validate_plan(summary.to_dict()) == summary.to_dict()
    bounded = summary.to_dict()
    bounded["node_types"] = ["Index Scan"] * 128
    assert _validate_plan(bounded) == bounded
    bounded["node_types"] = ["Index Scan"] * 129
    with pytest.raises(ExperimentRefusal, match="plan_node_types"):
        _validate_plan(bounded)


def test_exact_capture_retains_actual_file_fusion_without_raw_hits() -> None:
    task, pin, publication, profile = _fixture()
    cell = ExperimentCell(
        "exact_vector", task.task_id, ExecutionState.COMPLETED,
        elapsed_ns=1, cleanup_status="not_applicable",
    )
    operation = make_exact_operation(
        task, 1, publication=publication, pin=pin, profile=profile, rebuild_id="rebuild-1",
        vector=(1.0, 0.0, 0.0), task_sha256=_DIGEST,
        results={BIND_CORE: (cell, ())}, query_descriptors={BIND_CORE: _DIGEST},
        fused=_fusion(pin, "exact_vector"),
    )
    work = cast(dict[str, object], operation["work"])
    fusion = cast(dict[str, object], work["fusion"])
    assert fusion["fusion_state"] == "completed"
    assert "hits" not in fusion


def test_blocked_hybrid_records_no_attempt_and_no_pin_claim() -> None:
    task, pin, publication, profile = _fixture()
    operation = make_hybrid_operation(
        task, 1, publication=publication, pin=pin, profile=profile, rebuild_id="rebuild-1",
        vector=(1.0, 0.0, 0.0), task_sha256=_DIGEST, selected_binding_ids=(BIND_CORE,),
        fused=None, upstream_state=ExecutionState.UNAVAILABLE,
        upstream_reason="exact_source_scope_required",
    )
    actual = cast(dict[str, object], operation["actual"])
    work = cast(dict[str, object], operation["work"])
    assert operation["state"] == "unavailable"
    assert actual["operation"] == "vector_query_not_attempted"
    assert actual["selected_binding_ids"] == []
    assert all(
        actual[field] is None
        for field in (
            "backend", "publication_identity", "profile_identity", "rebuild_id",
            "input_descriptor_sha256", "snapshot_manifest_id", "effective_mode",
            "match_surface", "fallback",
        )
    )
    assert work["fusion"] is None


@pytest.mark.parametrize(
    ("state", "reason", "top_reason"),
    [
        (ExecutionState.REFUSED, "source_scope_refused", "binding_refused"),
        (ExecutionState.UNAVAILABLE, "candidate_store_unavailable", "binding_unavailable"),
    ],
)
def test_exact_nonexecution_preserves_missing_descriptor_and_state_reason(
    state: ExecutionState, reason: str, top_reason: str,
) -> None:
    task, pin, publication, profile = _fixture()
    cell = ExperimentCell("exact_vector", task.task_id, state, reason, elapsed_ns=1)
    operation = make_exact_operation(
        task, 1, publication=publication, pin=pin, profile=profile, rebuild_id="rebuild-1",
        vector=(1.0, 0.0, 0.0), task_sha256=_DIGEST,
        results={BIND_CORE: (cell, ())}, query_descriptors={}, fused=None,
    )
    work = cast(dict[str, object], operation["work"])
    binding = cast(list[dict[str, object]], work["per_binding"])[0]
    actual = cast(dict[str, object], operation["actual"])
    assert operation["state"] == state.value
    assert operation["reason"] == top_reason
    assert binding["reason"] == reason
    assert binding["query_descriptor_sha256"] is None
    assert actual["input_descriptor_sha256"] is None


def test_completed_sql_and_refused_fusion_remain_separate_outcomes() -> None:
    task, pin, publication, profile = _fixture()
    refused = fuse_arm_observations_rrf((), expected_pin=pin)
    cell = ExperimentCell(
        "exact_vector", task.task_id, ExecutionState.COMPLETED,
        elapsed_ns=1, cleanup_status="not_applicable",
    )
    operation = make_exact_operation(
        task, 1, publication=publication, pin=pin, profile=profile, rebuild_id="rebuild-1",
        vector=(1.0, 0.0, 0.0), task_sha256=_DIGEST,
        results={BIND_CORE: (cell, ())}, query_descriptors={BIND_CORE: _DIGEST}, fused=refused,
    )
    work = cast(dict[str, object], operation["work"])
    binding = cast(list[dict[str, object]], work["per_binding"])[0]
    fusion = cast(dict[str, object], work["fusion"])
    assert operation["state"] == "refused"
    assert operation["reason"] == "invalid_fusion_parameters"
    assert binding["state"] == "completed"
    assert fusion["fusion_state"] == "refused"


def test_hnsw_capture_keeps_cleanup_failure_separate_from_raw_result() -> None:
    task, pin, publication, profile = _fixture()
    failed = HnswObservation(
        ExperimentCell("hnsw_vector", task.task_id, ExecutionState.FAILED, "cleanup_failed", cleanup_status="failed"),
        {}, "", result=None,
    )
    work = _hnsw_binding_work(
        BIND_CORE, failed, {"creation_error": "index_create_failed", "cleanup": {"status": "failed"}},
    )
    assert work["cell_state"] == "failed"
    assert work["result_state"] is None
    assert work["result_reason"] is None
    assert work["cleanup_state"] == "failed"
    assert work["explain_executed"] is None


def test_hnsw_capture_retains_completed_file_fusion_and_plan_evidence() -> None:
    task, pin, publication, profile = _fixture()
    plan = HnswPlanSummary(
        ("Limit", "Index Scan"), ("index-1",), 1, 0.1, 0.2, 4, 0,
        True, False, True,
    )
    receipt: dict[str, object] = {
        "attempt_identity": "attempt-1", "query_digest": _DIGEST,
        "creation": {}, "cleanup": {"status": "verified_absent"},
    }
    provenance = HnswProvenance(
        pin.repository_identity, pin.run_id, pin.receipt_identity, profile.identity,
        "rebuild-1", "index-1", _DIGEST, "attempt-1", ((BIND_CORE, SNAP_CORE_G1),),
        profile.dimensions, 40, "off", 20, "owner-1", _DIGEST,
    )
    result = HnswResult(
        HnswExecutionState.COMPLETED, None, (), plan,
        HnswRecallSummary(1, 1, 1, 1.0, False), provenance,
    )
    observation = HnswObservation(
        ExperimentCell("hnsw_vector", task.task_id, ExecutionState.COMPLETED, cleanup_status="verified"),
        plan.to_dict(), digest_json(plan.to_dict()), result=result,
    )
    operation = make_hnsw_operation(
        task, 1, publication=publication, pin=pin, profile=profile, rebuild_id="rebuild-1",
        vector=(1.0, 0.0, 0.0), task_sha256=_DIGEST,
        results={BIND_CORE: (observation, None, None, 0, 0, receipt)},
        exact_state=ExecutionState.COMPLETED, exact_count=1, reference_recall=1.0,
        fused=_fusion(pin, "hnsw_vector"),
    )
    work = cast(dict[str, object], operation["work"])
    fusion = cast(dict[str, object], work["fusion"])
    hnsw = cast(list[object], work["hnsw"])
    item = cast(dict[str, object], hnsw[0])
    assert fusion["fusion_state"] == "completed"
    assert item["cell_state"] == "completed"
    assert item["explain_executed"] is True
    cleanup_failed = replace(
        observation,
        cell=replace(observation.cell, execution_state=ExecutionState.FAILED,
                     reason="hnsw_cleanup_failed", cleanup_status="failed"),
    )
    failed_operation = make_hnsw_operation(
        task, 1, publication=publication, pin=pin, profile=profile, rebuild_id="rebuild-1",
        vector=(1.0, 0.0, 0.0), task_sha256=_DIGEST,
        results={BIND_CORE: (cleanup_failed, None, None, 0, 0,
                 {**receipt, "cleanup": {"status": "failed"}})},
        exact_state=ExecutionState.COMPLETED, exact_count=1,
    )
    failed_work = cast(dict[str, object], failed_operation["work"])
    failed_items = cast(list[dict[str, object]], failed_work["hnsw"])
    assert failed_operation["state"] == "failed"
    assert failed_items[0]["result_state"] == "completed"
    assert failed_items[0]["cleanup_state"] == "failed"
    assert failed_work["fusion"] is None
    refused_fusion = fuse_arm_observations_rrf((), expected_pin=pin)
    refused_operation = make_hnsw_operation(
        task, 1, publication=publication, pin=pin, profile=profile, rebuild_id="rebuild-1",
        vector=(1.0, 0.0, 0.0), task_sha256=_DIGEST,
        results={BIND_CORE: (observation, None, None, 0, 0, receipt)},
        exact_state=ExecutionState.COMPLETED, exact_count=1, reference_recall=1.0,
        fused=refused_fusion,
    )
    assert refused_operation["state"] == "refused"
    refused_work = cast(dict[str, object], refused_operation["work"])
    assert cast(list[dict[str, object]], refused_work["hnsw"])[0]["cell_state"] == "completed"


def test_single_arm_grade_sink_preserves_two_return_values(monkeypatch: pytest.MonkeyPatch) -> None:
    task, pin, _publication, _profile = _fixture()
    arm = AdmittedArmObservation(
        arm_id="exact_vector", mode="ranked_discovery", verified_pin=pin,
        selected_binding_ids=(BIND_CORE,), raw_file_hits=(),
    )
    captured: list[FileFusionResult] = []
    monkeypatch.setattr(
        "retrieval_semantic_experiment_evaluator.grade_w5_task_slot",
        lambda *_args, **_kwargs: None,
    )
    cell, slot = grade_vector_arm(arm, task, pin, fusion_sink=captured.append)
    assert cell.execution_state is ExecutionState.COMPLETED
    assert slot is None and len(captured) == 1
    assert captured[0].to_dict()["hits"] == []


def test_empty_exact_reference_is_explicitly_vacuous() -> None:
    task, pin, publication, profile = _fixture()
    failed = HnswObservation(
        ExperimentCell("hnsw_vector", task.task_id, ExecutionState.FAILED, "index_create_failed", cleanup_status="failed"),
        {}, "", result=None,
    )
    operation = make_hnsw_operation(
        task, 1, publication=publication, pin=pin, profile=profile, rebuild_id="rebuild-1",
        vector=(1.0, 0.0, 0.0), task_sha256=_DIGEST,
        results={BIND_CORE: (failed, None, None, 0, 0, {"creation_error": "index_create_failed"})},
        exact_state=ExecutionState.COMPLETED, exact_count=0,
    )
    work = cast(dict[str, object], operation["work"])
    assert work["reference"] == {
        "status": "vacuous_empty", "reason": "exact_reference_empty", "recall": None,
    }


def test_mixed_binding_states_keep_verified_scope_and_refusal_reason() -> None:
    task, pin, publication, profile = _fixture(selected_bindings=(BIND_CORE, BIND_COMP))
    completed = ExperimentCell(
        "exact_vector", task.task_id, ExecutionState.COMPLETED,
        elapsed_ns=1, cleanup_status="not_applicable",
    )
    refused = ExperimentCell(
        "exact_vector", task.task_id, ExecutionState.REFUSED, "source_scope_refused",
        elapsed_ns=1, cleanup_status="not_applicable",
    )
    operation = make_exact_operation(
        task, 1, publication=publication, pin=pin, profile=profile, rebuild_id="rebuild-1",
        vector=(1.0, 0.0, 0.0), task_sha256=_DIGEST,
        results={BIND_CORE: (completed, ()), BIND_COMP: (refused, ())},
        query_descriptors={BIND_CORE: _DIGEST}, fused=None,
    )
    actual = cast(dict[str, object], operation["actual"])
    items = cast(list[dict[str, object]], cast(dict[str, object], operation["work"])["per_binding"])
    assert actual["selected_binding_ids"] == [BIND_CORE, BIND_COMP]
    assert [item["state"] for item in items] == ["completed", "refused"]
    assert operation["state"] == "refused"
    assert operation["reason"] == "binding_refused"
    cell = combine_scoped_cells((completed, refused), arm_id="exact_vector", task_id=task.task_id)
    assert operation["state"] == cell.execution_state.value


def test_scope_refusal_cannot_be_bypassed_by_missing_descriptor() -> None:
    task, pin, publication, profile = _fixture()
    cell = ExperimentCell("exact_vector", task.task_id, ExecutionState.REFUSED, "source_scope_refused")
    with pytest.raises(ExperimentRefusal, match="observed_operation_binding_scope"):
        make_exact_operation(
            task, 1, publication=publication, pin=pin, profile=profile, rebuild_id="rebuild-1",
            vector=(1.0, 0.0, 0.0), task_sha256=_DIGEST,
            results={"bind1:" + "f" * 64: (cell, ())}, query_descriptors={}, fused=None,
        )


def test_writer_refuses_operation_state_mismatch_before_append() -> None:
    task, pin, publication, profile = _fixture()
    failed = ExperimentCell(
        "exact_vector", task.task_id, ExecutionState.FAILED, "query_failed",
        elapsed_ns=1, cleanup_status="not_applicable",
    )
    operation = make_exact_operation(
        task, 1, publication=publication, pin=pin, profile=profile, rebuild_id="rebuild-1",
        vector=(1.0, 0.0, 0.0), task_sha256=_DIGEST,
        results={BIND_CORE: (failed, ())}, query_descriptors={}, fused=None,
    )
    appended: list[object] = []
    completed = replace(failed, execution_state=ExecutionState.COMPLETED, reason=None)
    with pytest.raises(ExperimentRefusal, match="observed_operation_state_mismatch"):
        record_cell(
            SimpleNamespace(append=appended.append), completed, 1,
            generation=task.generation, observed_operation=operation,
        )
    assert appended == []
