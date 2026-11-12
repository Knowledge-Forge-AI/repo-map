"""Per-task exact/vector/ANN orchestration for the optional W5 experiment."""

from __future__ import annotations

from dataclasses import replace
import time
from typing import Callable, Mapping, Protocol

from common_lore_index.retrieval.query_contracts import QueryEnvelope
from common_lore_index.storage.semantic_candidates import (
    CandidatePublication, CandidateQuery,
)
from repomap_test_support.w5_experiment_postgres import (
    PostgresHandle, exact_candidates,
)
from repomap_test_support.w5_experiment_support import (
    combine_scoped_cells, merge_candidate_rows, record_cell, selected_public_binding_ids,
)
from retrieval_evaluation_attempts import AttemptJournal
from retrieval_evaluation_grading import ExecutionState
from retrieval_evaluation_schema import EvaluationTask
from retrieval_semantic_arm_validation import FileIdentityTuple, _verify_envelope_against_pin
from retrieval_semantic_experiment_contracts import (
    ExperimentCell, ExperimentCostLedger, ExperimentRefusal,
)
from retrieval_semantic_experiment_outcomes import require_admitted_vector_execution
from retrieval_semantic_experiment_evaluator import (
    SealedComponent, build_candidate_rows_arm, grade_vector_arm,
)
from retrieval_semantic_observed_operation_capture import (
    make_exact_operation, make_hnsw_operation, make_hybrid_operation,
    make_unadmitted_operation,
)
from repomap_test_support.w5_experiment_hnsw import run_hnsw_binding
from retrieval_semantic_fusion import AdmittedArmObservation, FileFusionResult
from retrieval_semantic_grading import evaluate_arm_task_applicability, grade_w5_task_slot
from retrieval_semantic_generator_inputs import PublicGenerationInput
from retrieval_semantic_provenance import VerifiedPublicationPin
from retrieval_semantic_experiment_scope import (
    BaselineCorrespondenceSidecar, CorrespondenceCostSample, verify_baseline_correspondence_sidecar,
)

VECTOR_ARM_IDS: tuple[str, ...] = ("exact_vector", "hnsw_vector", "hybrid_rrf")


class _JournalWriter(Protocol):
    def append(self, record: dict[str, object]) -> None: ...


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
    result_cell_sink: Callable[[Mapping[str, object], ExperimentCell], None] | None = None,
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
                generation=task.generation,
                observed_operation=(
                    make_unadmitted_operation(
                        task, arm_id, repetition, state, query.reason or "query_not_admitted"
                    ) if result_cell_sink is not None else None
                ),
                result_cell_sink=result_cell_sink,
            )
        return
    bindings = selected_public_binding_ids(task)
    exact_results: dict[str, tuple[ExperimentCell, tuple[dict[str, object], ...]]] = {}
    query_descriptors: dict[str, str] = {}
    for binding in bindings:
        started = time.perf_counter_ns()
        def observe_query(
            _query: CandidateQuery, descriptor: str, source_binding: str = binding,
        ) -> None:
            query_descriptors[source_binding] = descriptor
        cell, rows = exact_candidates(
            postgres, publication, sealed.artifact.profile,
            rebuild_id=rebuild_id, vector=query.vector, task_id=task.task_id,
            publication_pin=pin, source_binding_id=binding,
            query_observer=observe_query,
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
        exact_fusion_results: list[FileFusionResult] = []
        exact_grade, exact_slot = grade_vector_arm(
            exact_arm, task, pin,
            fusion_sink=exact_fusion_results.append if result_cell_sink is not None else None,
        )
        exact_operation = (
            make_exact_operation(
                task, repetition, publication=publication, pin=pin, profile=sealed.artifact.profile,
                rebuild_id=rebuild_id, vector=query.vector, task_sha256=query.task_sha256,
                results=exact_results, query_descriptors=query_descriptors,
                fused=exact_fusion_results[0] if exact_fusion_results else None,
            ) if result_cell_sink is not None else None
        )
        record_cell(
            journal, exact_grade, repetition, generation=task.generation,
            observed_operation=exact_operation, slot=exact_slot, result_cell_sink=result_cell_sink,
        )
        fusion_results: list[FileFusionResult] = []
        hybrid_grade, hybrid_slot = grade_vector_arm(
            exact_arm, task, pin, lexical_arm=lexical_arm,
            fusion_sink=fusion_results.append if result_cell_sink is not None else None,
        )
        hybrid_operation = (
            make_hybrid_operation(
                task, repetition, publication=publication, pin=pin, profile=sealed.artifact.profile,
                rebuild_id=rebuild_id, vector=query.vector, task_sha256=query.task_sha256,
                selected_binding_ids=selected_public_binding_ids(task),
                fused=fusion_results[0] if fusion_results else None,
            ) if result_cell_sink is not None else None
        )
        record_cell(
            journal, hybrid_grade, repetition, generation=task.generation,
            observed_operation=hybrid_operation, slot=hybrid_slot, result_cell_sink=result_cell_sink,
        )
    else:
        exact_operation = (
            make_exact_operation(
                task, repetition, publication=publication, pin=pin, profile=sealed.artifact.profile,
                rebuild_id=rebuild_id, vector=query.vector, task_sha256=query.task_sha256,
                results=exact_results, query_descriptors=query_descriptors,
            ) if result_cell_sink is not None else None
        )
        record_cell(
            journal, exact_cell, repetition, generation=task.generation,
            observed_operation=exact_operation, result_cell_sink=result_cell_sink,
        )
        hybrid_operation = (
            make_hybrid_operation(
                task, repetition, publication=publication, pin=pin, profile=sealed.artifact.profile,
                rebuild_id=rebuild_id, vector=query.vector, task_sha256=query.task_sha256,
                selected_binding_ids=selected_public_binding_ids(task), fused=None,
                upstream_state=exact_cell.execution_state, upstream_reason=exact_cell.reason,
            ) if result_cell_sink is not None else None
        )
        record_cell(
            journal,
            ExperimentCell(
                "hybrid_rrf", task.task_id, exact_cell.execution_state,
                exact_cell.reason or "exact_vector_not_completed",
                cleanup_status="not_applicable",
            ),
            repetition,
            generation=task.generation, observed_operation=hybrid_operation,
            result_cell_sink=result_cell_sink,
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
            "plan": observation.plan if observation.plan else None,
            "plan_sha256": observation.plan_sha256 if observation.plan else None,
        })
    hnsw_cell = combine_scoped_cells(hnsw_cells, arm_id="hnsw_vector", task_id=task.task_id)
    hnsw_rows = (
        merge_candidate_rows({binding: result[0].candidates for binding, result in hnsw_results.items()})
        if all(cell.execution_state == ExecutionState.COMPLETED for cell in hnsw_cells) else ()
    )
    plans = tuple(result[0].plan for result in hnsw_results.values() if result[0].plan)
    plan_digests = tuple(result[0].plan_sha256 for result in hnsw_results.values() if result[0].plan)
    plan = plans[0] if len(plans) == 1 else list(plans) if plans else None
    plan_sha256 = plan_digests[0] if len(plan_digests) == 1 else None
    exact_keys = {
        (row["source_binding_id"], row["input_digest"], row["canonical_key"])
        for row in exact_rows
    }
    reference_recall: float | None = None
    if hnsw_cell.execution_state == ExecutionState.COMPLETED:
        hnsw_arm = build_candidate_rows_arm(
            hnsw_rows, arm_id="hnsw_vector", task=task, pin=pin, inputs=inputs
        )
        hnsw_keys = {
            (row["source_binding_id"], row["input_digest"], row["canonical_key"])
            for row in hnsw_rows
        }
        if exact_cell.execution_state == ExecutionState.COMPLETED and exact_keys:
            reference_recall = len(exact_keys & hnsw_keys) / len(exact_keys)
    hnsw_fusion_results: list[FileFusionResult] = []
    if hnsw_cell.execution_state == ExecutionState.COMPLETED:
        hnsw_grade, hnsw_slot = grade_vector_arm(
            hnsw_arm, task, pin,
            fusion_sink=hnsw_fusion_results.append if result_cell_sink is not None else None,
        )
    hnsw_operation = (
        make_hnsw_operation(
            task, repetition, publication=publication, pin=pin, profile=sealed.artifact.profile,
            rebuild_id=rebuild_id, vector=query.vector, task_sha256=query.task_sha256,
            results=hnsw_results, exact_state=exact_cell.execution_state,
            exact_count=len(exact_keys), reference_recall=reference_recall,
            fused=hnsw_fusion_results[0] if hnsw_fusion_results else None,
        ) if result_cell_sink is not None else None
    )
    if hnsw_cell.execution_state == ExecutionState.COMPLETED:
        record_cell(
            journal, hnsw_grade, repetition, plan=plan, plan_sha256=plan_sha256,
            generation=task.generation, observed_operation=hnsw_operation,
            exact_reference_recall=reference_recall, slot=hnsw_slot,
            result_cell_sink=result_cell_sink,
        )
    else:
        record_cell(
            journal, hnsw_cell, repetition, plan=plan, plan_sha256=plan_sha256,
            generation=task.generation, observed_operation=hnsw_operation,
            result_cell_sink=result_cell_sink,
        )
    # All cells and cleanup evidence are recorded before mechanical failure.
    require_admitted_vector_execution(
        exact=exact_grade.execution_state if exact_arm is not None else exact_cell.execution_state,
        hybrid=hybrid_grade.execution_state if exact_arm is not None else exact_cell.execution_state,
        hnsw=hnsw_grade.execution_state if hnsw_cell.execution_state == ExecutionState.COMPLETED else hnsw_cell.execution_state,
        lexical=lexical_arm.execution_state,
    )


def baseline_file_metrics_with_correspondence(
    task: EvaluationTask,
    arm_id: str,
    state: ExecutionState,
    envelope: QueryEnvelope,
    correspondence_sidecar: BaselineCorrespondenceSidecar,
) -> tuple[dict[str, float] | None, str, str | None, CorrespondenceCostSample]:
    """Grade baseline locators via verified correspondence sidecar and measure verification cost."""
    t0 = time.perf_counter_ns()
    try:
        cost = correspondence_sidecar.captured_gap_cost(task, arm_id, envelope)
        applicability = evaluate_arm_task_applicability(arm_id, task)
        if not applicability.applicable:
            return None, "not_applicable", "file_metric_not_applicable", cost
        if state in (ExecutionState.REFUSED, ExecutionState.UNAVAILABLE):
            reason = envelope.refusal_code if state == ExecutionState.REFUSED else envelope.unavailable_reason
            return None, "gap", f"{state.value}:{reason or state.value}", cost
        if state != ExecutionState.COMPLETED:
            return None, "gap", f"non_completed:{state.value}", cost
        verified_pin, cost = verify_baseline_correspondence_sidecar(
            correspondence_sidecar, task=task, arm_id=arm_id, state=state, envelope=envelope,
        )
        snapshots = verified_pin.snapshot_by_binding()
        items = tuple(
            FileIdentityTuple(
                hit.locator.binding_id, snapshots[hit.locator.binding_id][1], hit.locator.source_relative_path,
            ).validate()
            for hit in envelope.hits
        )
        file_slot = grade_w5_task_slot(
            task, arm_id=arm_id, verified_pin=verified_pin, returned_files=items,
            execution_state=state, capability_state=envelope.capability_state.value,
            refusal_code=envelope.refusal_code, scope_complete=envelope.scope_complete,
        )
    except ExperimentRefusal as exc:
        code = getattr(exc, "code", "file_metric_provenance_unresolved")
        retained_cost = getattr(exc, "correspondence_cost", None)
        fail_cost = (
            retained_cost
            if isinstance(retained_cost, CorrespondenceCostSample)
            else CorrespondenceCostSample(
                correspondence_verification_ns=max(0, time.perf_counter_ns() - t0),
                correspondence_verification_bytes_read=None, correspondence_failures=1,
            )
        )
        return None, "gap", str(code) if isinstance(code, str) and code else "file_metric_provenance_unresolved", fail_cost
    if file_slot.capability_state == "unsupported_mode":
        return None, "not_applicable", "file_metric_not_applicable", cost
    return (
        {key: value for key, value in file_slot.metrics.items() if key.startswith("file_")},
        "verified", None, cost,
    )


def baseline_file_metrics(
    task: EvaluationTask,
    arm_id: str,
    state: ExecutionState,
    envelope: QueryEnvelope,
    pin: VerifiedPublicationPin | None,
    *,
    correspondence_sidecar: BaselineCorrespondenceSidecar | None = None,
) -> tuple[dict[str, float] | None, str, str | None]:
    """Grade baseline envelope locators only with a current public pin or verified sidecar."""
    if correspondence_sidecar is not None:
        metrics, status, gap, _cost = baseline_file_metrics_with_correspondence(
            task, arm_id, state, envelope, correspondence_sidecar
        )
        return metrics, status, gap
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
            task, arm_id=arm_id, verified_pin=pin, returned_files=items,
            execution_state=state, capability_state=envelope.capability_state.value,
            refusal_code=envelope.refusal_code, scope_complete=envelope.scope_complete,
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
    "VECTOR_ARM_IDS", "baseline_file_metrics", "baseline_file_metrics_with_correspondence",
    "record_vector_query_starts", "run_hnsw_binding", "run_vector_task",
)
