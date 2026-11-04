"""HNSW operation orchestration retained for the W5 context capture owner."""

from __future__ import annotations

from dataclasses import replace
import re
import time

from common_lore_index.storage.semantic_candidates import (
    CandidatePublication, CandidateQuery, EmbeddingProfile,
)
from repomap_test_support.w5_experiment_postgres import (
    HNSW_OWNER_ROLE, HnswObservation, PostgresHandle,
    cleanup_hnsw_index, create_hnsw_index, hnsw_candidates,
)
from retrieval_evaluation_grading import ExecutionState
from retrieval_semantic_ann import HnswEvaluationQuery
from retrieval_semantic_ann_models import HnswEvaluationError
from retrieval_semantic_ann_lifecycle import HnswCleanupDisposition, HnswCreationReceipt
from retrieval_semantic_experiment_contracts import ExperimentCell, ExperimentRefusal, digest_json
from retrieval_semantic_provenance import VerifiedPublicationPin


def run_hnsw_binding(
    postgres: PostgresHandle, publication: CandidatePublication, profile: EmbeddingProfile, *,
    rebuild_id: str, vector: tuple[float, ...], task_id: str, source_binding_id: str,
    publication_pin: VerifiedPublicationPin, attempt_identity: str, limit: int = 20, evidence_limit: int = 5,
) -> tuple[HnswObservation, HnswCreationReceipt | None, HnswCleanupDisposition | None, int, int, dict[str, object]]:
    """Run one receipt-bound HNSW query and prove cleanup before returning."""
    query = CandidateQuery(
        publication, profile, rebuild_id, vector, selected=True, limit=limit,
        evidence_limit=evidence_limit, source_binding_id=source_binding_id,
    )
    vector_digest = digest_json(list(vector))
    query_validation_error: Exception | None = None
    try:
        evaluation = HnswEvaluationQuery(
            query, publication_pin, attempt_identity, owner_identity=HNSW_OWNER_ROLE,
        ).validate()
        query_digest = evaluation.index_spec.query_digest
        source_scope = [list(pair) for pair in evaluation.public_source_scope]
    except Exception as exc:
        query_digest = None
        source_scope = []
        query_validation_error = exc
    receipt: dict[str, object] = {
        "task_id": task_id, "source_binding_id": source_binding_id,
        "vector_digest": vector_digest, "query_digest": query_digest,
        "source_scope": source_scope, "attempt_identity": attempt_identity,
    }
    if query_validation_error is not None:
        validation_error = query_validation_error
        raw_code = getattr(validation_error, "code", None)
        code = raw_code if type(raw_code) is str else (
            "hnsw_query_not_admitted"
            if isinstance(validation_error, (ExperimentRefusal, HnswEvaluationError)) else "hnsw_query_validation_failed"
        )
        if re.fullmatch(r"[a-z][a-z0-9_.-]{0,127}", code) is None:
            code = "hnsw_query_validation_failed"
        receipt["query_error"] = code
        state = ExecutionState.REFUSED if isinstance(validation_error, (ExperimentRefusal, HnswEvaluationError)) else ExecutionState.FAILED
        return HnswObservation(
            ExperimentCell("hnsw_vector", task_id, state, code, cleanup_status="not_applicable"),
            {}, "", (), None,
        ), None, None, 0, 0, receipt
    started = time.perf_counter_ns()
    try:
        creation = create_hnsw_index(
            postgres, candidate_query=query, publication_pin=publication_pin,
            attempt_identity=attempt_identity,
        )
    except Exception as exc:
        elapsed = time.perf_counter_ns() - started
        raw_code = getattr(exc, "code", None)
        code = raw_code if type(raw_code) is str else "hnsw_index_creation_failed"
        if re.fullmatch(r"[a-z][a-z0-9_.-]{0,127}", code) is None:
            code = "hnsw_index_creation_failed"
        failed_observation = HnswObservation(
            ExperimentCell(
                "hnsw_vector", task_id, ExecutionState.FAILED, code,
                cleanup_status="not_applicable",
            ),
            {}, "", (), None,
        )
        receipt["creation_error"] = code
        return failed_observation, None, None, elapsed, 0, receipt
    index_ns = time.perf_counter_ns() - started
    receipt["creation"] = creation.to_dict()
    cleanup: HnswCleanupDisposition | None = None
    observation: HnswObservation | None = None
    query_started = time.perf_counter_ns()
    cleanup_started = query_started
    try:
        observation = hnsw_candidates(
            postgres, task_id=task_id, candidate_query=query,
            publication_pin=publication_pin, attempt_identity=attempt_identity,
            creation_receipt=creation,
        )
    finally:
        cleanup_started = time.perf_counter_ns()
        cleanup = cleanup_hnsw_index(
            postgres, creation,
            primary_reason=None if observation is None else observation.cell.reason,
        )
    cleanup_ns = time.perf_counter_ns() - cleanup_started
    assert observation is not None and cleanup is not None
    query_elapsed = cleanup_started - query_started
    observation = HnswObservation(
        replace(
            observation.cell,
            elapsed_ns=query_elapsed,
            execution_state=(
                observation.cell.execution_state
                if cleanup.status == "verified_absent" else ExecutionState.FAILED
            ),
            reason=(
                observation.cell.reason
                if cleanup.status == "verified_absent" else "hnsw_cleanup_failed"
            ),
            cleanup_status="verified" if cleanup.status == "verified_absent" else "failed",
        ),
        observation.plan, observation.plan_sha256,
        observation.candidates, observation.result,
    )
    receipt["cleanup"] = cleanup.to_dict()
    return observation, creation, cleanup, index_ns, cleanup_ns, receipt


__all__ = ["run_hnsw_binding"]
