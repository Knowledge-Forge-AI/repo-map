"""Append current W5 observations without rewriting historical journal members."""
from __future__ import annotations
from collections.abc import Callable, Mapping
from typing import Any
from common_lore_index.retrieval.query_contracts import QueryEnvelope
from retrieval_evaluation_accounting import summarize_timing_samples
from retrieval_evaluation_execution import TaskOutcome
from retrieval_evaluation_grading import ExecutionState, GradedSlotRecord, grade_task_execution
from retrieval_evaluation_schema import EvaluationTask
from retrieval_semantic_experiment_contracts import ExperimentCell, ExperimentRefusal
from retrieval_semantic_observed_operation import validate_observed_operation
from retrieval_semantic_grading import W5_FILE_GRADING_POLICY_CURRENT

def record_baseline(
    journal: Any,
    task: EvaluationTask,
    arm_id: str,
    repetition: int,
    execute: Callable[[], TaskOutcome],
    *,
    file_metrics_callback: Callable[[EvaluationTask, str, ExecutionState, QueryEnvelope], tuple[dict[str, float] | None, str, str | None]] | None = None,
) -> TaskOutcome:
    journal.append({"event": "query_started", "task_id": task.task_id, "arm_id": arm_id, "repetition": repetition})
    outcome = execute()
    state, envelope, elapsed_ns, byte_accounting = outcome
    journal.append({
        "event": "query_observed", "task_id": task.task_id, "arm_id": arm_id,
        "repetition": repetition, "execution_state": state.value,
        "elapsed_ns": max(0, elapsed_ns), "byte_accounting": byte_accounting.to_dict(),
        "envelope": envelope.to_dict(),
    })
    span_slot = grade_task_execution(
        task,
        execution_state=state,
        envelope=envelope,
        timing=summarize_timing_samples([max(0, elapsed_ns)]),
        byte_accounting=byte_accounting,
    )
    file_metrics, file_status, file_gap = (
        (None, "gap", "verified_pin_required") if file_metrics_callback is None
        else file_metrics_callback(task, arm_id, state, envelope)
    )
    grade_record: dict[str, object] = {
        "event": "task_graded",
        "arm_id": arm_id,
        "task_id": task.task_id,
        "repetition": repetition,
        "divergent": False,
        "slot": span_slot.to_dict(),
        "span_metrics": dict(span_slot.metrics),
        "file_metrics": file_metrics,
        "file_metrics_status": file_status,
        "file_grading_policy_version": W5_FILE_GRADING_POLICY_CURRENT,
    }
    if file_gap is not None:
        grade_record["file_metrics_gap"] = file_gap
    journal.append(grade_record)
    return outcome


def record_cell(
    journal: Any,
    cell: ExperimentCell,
    repetition: int,
    *,
    generation: int | None = None,
    observed_operation: Mapping[str, object] | None = None,
    plan: object | None = None,
    plan_sha256: str | None = None,
    exact_reference_recall: float | None = None,
    slot: GradedSlotRecord | None = None,
    result_cell_sink: Callable[[Mapping[str, object], ExperimentCell], None] | None = None,
) -> None:
    record: dict[str, object] = {
        "event": "query_observed", **cell.to_dict(), "repetition": repetition,
    }
    if plan is not None:
        record["plan"] = plan
    if plan_sha256 is not None:
        record["plan_sha256"] = plan_sha256
    if exact_reference_recall is not None:
        record["exact_reference_recall"] = exact_reference_recall
    if slot is not None:
        record["slot"] = slot.to_dict()
        record["file_grading_policy_version"] = W5_FILE_GRADING_POLICY_CURRENT
    if observed_operation is not None:
        if generation is None:
            raise ValueError("observed operation generation is required")
        operation = validate_observed_operation(
            observed_operation,
            identity={
                "generation": generation, "task_id": cell.task_id,
                "arm_id": cell.arm_id, "repetition": repetition,
            },
        )
        if operation["state"] != cell.execution_state.value:
            raise ExperimentRefusal("observed_operation_state_mismatch")
        record["observed_operation"] = operation
    journal.append(record)
    if result_cell_sink is not None:
        result_cell_sink(
            {"arm_id": cell.arm_id, "task_id": cell.task_id, "repetition": repetition}, cell
        )
