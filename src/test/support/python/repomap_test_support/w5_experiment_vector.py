"""Per-task exact/vector/ANN orchestration for the optional W5 experiment."""

from __future__ import annotations

from dataclasses import replace
import time
from typing import Protocol

from common_lore_index.retrieval.query_contracts import QueryEnvelope
from common_lore_index.storage.semantic_candidates import (
    CandidatePublication,
    CandidateQuery,
    EmbeddingProfile,
)
from repomap_test_support.w5_experiment_postgres import (
    HNSW_OWNER_ROLE,
    HnswObservation,
    PostgresHandle,
    cleanup_hnsw_index,
    create_hnsw_index,
    exact_candidates,
    hnsw_candidates,
)
from repomap_test_support.w5_experiment_support import (
    combine_scoped_cells,
    merge_candidate_rows,
    record_cell,
    selected_public_binding_ids,
)
from retrieval_evaluation_attempts import AttemptJournal
from retrieval_evaluation_grading import ExecutionState
from retrieval_evaluation_schema import EvaluationTask
from retrieval_semantic_ann import HnswEvaluationQuery
from retrieval_semantic_ann_lifecycle import HnswCleanupDisposition, HnswCreationReceipt
from retrieval_semantic_arm_validation import (
    FileIdentityTuple,
    _verify_envelope_against_pin,
)
from retrieval_semantic_experiment_contracts import (
    ExperimentCell,
    ExperimentCostLedger,
    digest_json,
)
from retrieval_semantic_experiment_outcomes import require_admitted_vector_execution
from retrieval_semantic_experiment_evaluator import (
    SealedComponent,
    build_candidate_rows_arm,
    grade_vector_arm,
)
from retrieval_semantic_fusion import AdmittedArmObservation
from retrieval_semantic_grading import grade_w5_task_slot
from retrieval_semantic_generator_inputs import PublicGenerationInput
from retrieval_semantic_provenance import VerifiedPublicationPin

VECTOR_ARM_IDS: tuple[str, ...] = ("exact_vector", "hnsw_vector", "hybrid_rrf")


class _JournalWriter(Protocol):
    def append(self, record: dict[str, object]) -> None: ...


def run_hnsw_binding(
    postgres: PostgresHandle,
    publication: CandidatePublication,
    profile: EmbeddingProfile,
    *,
    rebuild_id: str,
    vector: tuple[float, ...],
    task_id: str,
    source_binding_id: str,
    publication_pin: VerifiedPublicationPin,
    attempt_identity: str,
    limit: int = 20,
    evidence_limit: int = 5,
) -> tuple[HnswObservation, HnswCreationReceipt | None, HnswCleanupDisposition | None, int, int, dict[str, object]]:
    """Run one receipt-bound HNSW query and prove cleanup before returning."""
    query = CandidateQuery(
        publication, profile, rebuild_id, vector, selected=True, limit=limit,
        evidence_limit=evidence_limit, source_binding_id=source_binding_id,
    )
    vector_digest = digest_json(list(vector))
    try:
        evaluation = HnswEvaluationQuery(
            query, publication_pin, attempt_identity, owner_identity=HNSW_OWNER_ROLE,
        ).validate()
        query_digest = evaluation.index_spec.query_digest
        source_scope = [list(pair) for pair in evaluation.public_source_scope]
    except Exception:
        query_digest = None
        source_scope = []
    receipt: dict[str, object] = {
        "task_id": task_id,
        "source_binding_id": source_binding_id,
        "vector_digest": vector_digest,
        "query_digest": query_digest,
        "source_scope": source_scope,
        "attempt_identity": attempt_identity,
    }
    started = time.perf_counter_ns()
    try:
        creation = create_hnsw_index(
            postgres, candidate_query=query, publication_pin=publication_pin,
            attempt_identity=attempt_identity,
        )
    except Exception as exc:
        elapsed = time.perf_counter_ns() - started
        failed_observation = hnsw_candidates(
            postgres, task_id=task_id, candidate_query=query,
            publication_pin=publication_pin, attempt_identity=attempt_identity,
        )
        code = getattr(exc, "code", type(exc).__name__)
        failed_observation = HnswObservation(
            replace(failed_observation.cell, reason=code if isinstance(code, str) else type(exc).__name__),
            failed_observation.plan, failed_observation.plan_sha256,
            failed_observation.candidates, failed_observation.result,
        )
        receipt["creation_error"] = code if isinstance(code, str) else type(exc).__name__
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
        observation.plan,
        observation.plan_sha256,
        observation.candidates,
        observation.result,
    )
    receipt["cleanup"] = cleanup.to_dict()
    return observation, creation, cleanup, index_ns, cleanup_ns, receipt


def record_vector_query_starts(journal: _JournalWriter, task_id: str, repetition: int) -> None:
    for arm_id in VECTOR_ARM_IDS:
        journal.append({
            "event": "query_started", "task_id": task_id,
            "arm_id": arm_id, "repetition": repetition,
        })


def run_vector_task(
    journal: AttemptJournal,
    postgres: PostgresHandle,
    publication: CandidatePublication,
    sealed: SealedComponent,
    inputs: PublicGenerationInput,
    task: EvaluationTask,
    repetition: int,
    *,
    pin: VerifiedPublicationPin,
    rebuild_id: str,
    attempt_identity: str,
    lexical_arm: AdmittedArmObservation,
    costs: ExperimentCostLedger,
) -> None:
    """Record one task/repetition, retaining every binding state and receipt."""
    record_vector_query_starts(journal, task.task_id, repetition)
    query = next(item for item in sealed.artifact.queries if item.task_id == task.task_id)
    if query.state != "admitted" or query.vector is None:
        state = ExecutionState.REFUSED if query.state == "refused" else ExecutionState.UNAVAILABLE
        for arm_id in VECTOR_ARM_IDS:
            record_cell(
                journal,
                ExperimentCell(
                    arm_id, task.task_id, state, query.reason or "query_not_admitted",
                    cleanup_status="not_applicable",
                ),
                repetition,
            )
        return
    bindings = selected_public_binding_ids(task)
    exact_results: dict[str, tuple[ExperimentCell, tuple[dict[str, object], ...]]] = {}
    for binding in bindings:
        started = time.perf_counter_ns()
        cell, rows = exact_candidates(
            postgres, publication, sealed.artifact.profile,
            rebuild_id=rebuild_id, vector=query.vector, task_id=task.task_id,
            publication_pin=pin, source_binding_id=binding,
        )
        exact_results[binding] = (replace(cell, elapsed_ns=time.perf_counter_ns() - started), rows)
    exact_cells = tuple(result[0] for result in exact_results.values())
    costs.failures += sum(int(cell.execution_state == ExecutionState.FAILED) for cell in exact_cells)
    exact_rows = (
        merge_candidate_rows({binding: result[1] for binding, result in exact_results.items()})
        if all(cell.execution_state == ExecutionState.COMPLETED for cell in exact_cells) else ()
    )
    for binding, (cell, _rows) in exact_results.items():
        journal.append({
            "event": "binding_query_observed", "arm_id": "exact_vector",
            "task_id": task.task_id, "repetition": repetition,
            "source_binding_id": binding, **cell.to_dict(),
        })
    exact_cell = combine_scoped_cells(exact_cells, arm_id="exact_vector", task_id=task.task_id)
    exact_arm = (
        build_candidate_rows_arm(
            exact_rows, arm_id="exact_vector", task=task, pin=pin, inputs=inputs
        ) if exact_cell.execution_state == ExecutionState.COMPLETED else None
    )
    if exact_arm is not None:
        exact_grade, exact_slot = grade_vector_arm(exact_arm, task, pin)
        record_cell(journal, exact_grade, repetition, slot=exact_slot)
        hybrid_grade, hybrid_slot = grade_vector_arm(
            exact_arm, task, pin, lexical_arm=lexical_arm
        )
        record_cell(journal, hybrid_grade, repetition, slot=hybrid_slot)
    else:
        record_cell(journal, exact_cell, repetition)
        record_cell(
            journal,
            ExperimentCell(
                "hybrid_rrf", task.task_id, exact_cell.execution_state,
                exact_cell.reason or "exact_vector_not_completed",
                cleanup_status="not_applicable",
            ),
            repetition,
        )
    hnsw_results = {
        binding: run_hnsw_binding(
            postgres, publication, sealed.artifact.profile,
            rebuild_id=rebuild_id, vector=query.vector, task_id=task.task_id,
            source_binding_id=binding, publication_pin=pin,
            attempt_identity=attempt_identity,
        )
        for binding in bindings
    }
    costs.index_ns += sum(result[3] for result in hnsw_results.values())
    costs.ann_cleanup_ns += sum(result[4] for result in hnsw_results.values())
    hnsw_cells = tuple(result[0].cell for result in hnsw_results.values())
    costs.failures += sum(int(cell.execution_state == ExecutionState.FAILED) for cell in hnsw_cells)
    for binding, result in hnsw_results.items():
        observation, _creation, _cleanup, _index_ns, _cleanup_ns, receipt = result
        journal.append({
            "event": "hnsw_binding_observed", "task_id": task.task_id,
            "repetition": repetition, "source_binding_id": binding,
            **observation.cell.to_dict(), "receipt": receipt,
            "plan": observation.plan, "plan_sha256": observation.plan_sha256,
        })
    hnsw_cell = combine_scoped_cells(hnsw_cells, arm_id="hnsw_vector", task_id=task.task_id)
    hnsw_rows = (
        merge_candidate_rows({binding: result[0].candidates for binding, result in hnsw_results.items()})
        if all(cell.execution_state == ExecutionState.COMPLETED for cell in hnsw_cells) else ()
    )
    plans = tuple(result[0].plan for result in hnsw_results.values() if result[0].plan)
    plan_digests = tuple(result[0].plan_sha256 for result in hnsw_results.values() if result[0].plan)
    plan = plans[0] if len(plans) == 1 else list(plans)
    plan_sha256 = plan_digests[0] if len(plan_digests) == 1 else None
    if hnsw_cell.execution_state == ExecutionState.COMPLETED:
        hnsw_arm = build_candidate_rows_arm(
            hnsw_rows, arm_id="hnsw_vector", task=task, pin=pin, inputs=inputs
        )
        hnsw_grade, hnsw_slot = grade_vector_arm(hnsw_arm, task, pin)
        exact_keys = {
            (row["source_binding_id"], row["input_digest"], row["canonical_key"])
            for row in exact_rows
        }
        hnsw_keys = {
            (row["source_binding_id"], row["input_digest"], row["canonical_key"])
            for row in hnsw_rows
        }
        reference_recall = len(exact_keys & hnsw_keys) / len(exact_keys) if exact_keys else 1.0
        record_cell(
            journal, hnsw_grade, repetition, plan=plan, plan_sha256=plan_sha256,
            exact_reference_recall=reference_recall, slot=hnsw_slot,
        )
    else:
        record_cell(journal, hnsw_cell, repetition, plan=plan, plan_sha256=plan_sha256)
    # All cells and cleanup evidence are recorded before mechanical failure.
    require_admitted_vector_execution(
        exact=exact_grade.execution_state if exact_arm is not None else exact_cell.execution_state,
        hybrid=hybrid_grade.execution_state if exact_arm is not None else exact_cell.execution_state,
        hnsw=hnsw_grade.execution_state if hnsw_cell.execution_state == ExecutionState.COMPLETED else hnsw_cell.execution_state,
        lexical=lexical_arm.execution_state,
    )


def baseline_file_metrics(
    task: EvaluationTask,
    arm_id: str,
    state: ExecutionState,
    envelope: QueryEnvelope,
    pin: VerifiedPublicationPin | None,
) -> tuple[dict[str, float] | None, str, str | None]:
    """Grade baseline envelope locators only with a current public pin."""
    if pin is None:
        return None, "gap", "verified_pin_required"
    try:
        envelope.validate()
        envelope_error, _, _, _, _ = _verify_envelope_against_pin(envelope, pin)
        if envelope_error is not None:
            raise ValueError(envelope_error)
        if envelope.scope.graph_id != pin.graph_id or set(envelope.scope.selected_binding_ids) != set(selected_public_binding_ids(task)):
            raise ValueError("baseline_envelope_scope_mismatch")
        if (envelope.scope.publication_bundle_id != pin.publication_bundle_id
                or envelope.scope.snapshot_manifest_id != pin.snapshot_manifest_id):
            raise ValueError("baseline_publication_correspondence_unproven")
        pin.revalidate_current()
        snapshots = pin.snapshot_by_binding()
        items = tuple(
            FileIdentityTuple(
                hit.locator.binding_id,
                snapshots[hit.locator.binding_id][1],
                hit.locator.source_relative_path,
            ).validate()
            for hit in envelope.hits
        )
        file_slot = grade_w5_task_slot(
            task,
            arm_id=arm_id,
            verified_pin=pin,
            returned_files=items,
            execution_state=state,
            capability_state=envelope.capability_state.value,
            refusal_code=envelope.refusal_code,
            scope_complete=envelope.scope_complete,
        )
    except Exception:
        return None, "gap", "file_metric_provenance_unresolved"
    if file_slot.capability_state == "unsupported_mode":
        return None, "not_applicable", "file_metric_not_applicable"
    return (
        {key: value for key, value in file_slot.metrics.items() if key.startswith("file_")},
        "verified",
        None,
    )


__all__ = (
    "VECTOR_ARM_IDS", "baseline_file_metrics", "record_vector_query_starts",
    "run_hnsw_binding", "run_vector_task",
)
