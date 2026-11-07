"""Result-v2 no-execution observation writer for refused vector tasks."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol

from retrieval_evaluation_grading import ExecutionState
from retrieval_semantic_experiment_contracts import ExperimentCell
from retrieval_semantic_observed_operation_capture import make_unadmitted_operation_identity


class _Journal(Protocol):
    def append(self, record: dict[str, object]) -> None: ...


def append_unadmitted_vector_observations(
    journal: _Journal,
    *,
    task_id: str,
    generation: int,
    repetition: int,
    state: ExecutionState,
    reason: str,
    arm_ids: tuple[str, ...],
    cell_sink: Callable[[Mapping[str, object], ExperimentCell], None] | None,
    include_operation: bool,
) -> None:
    for arm_id in arm_ids:
        cell = ExperimentCell(
            arm_id, task_id, state, reason, cleanup_status="not_applicable",
        ).validate()
        journal.append({
            "event": "query_started", "task_id": task_id,
            "arm_id": arm_id, "repetition": repetition,
        })
        observed: dict[str, object] = {
            "event": "query_observed", **cell.to_dict(), "repetition": repetition,
        }
        if include_operation:
            observed["observed_operation"] = make_unadmitted_operation_identity(
                task_id, generation, arm_id, repetition, state, reason,
            )
        journal.append(observed)
        if cell_sink is not None:
            cell_sink({"arm_id": arm_id, "task_id": task_id, "repetition": repetition}, cell)


__all__ = ["append_unadmitted_vector_observations"]
