"""Explicit comparator exposure populations within each backend arm."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from retrieval_evaluation_grading import GradedSlotRecord, aggregate_arm_summary
from retrieval_evaluation_schema import EvaluationTask


def describe_comparability(
    arm_id: str, backend: str, slots: Sequence[GradedSlotRecord], tasks: Sequence[EvaluationTask],
) -> dict[str, Any]:
    key = "native" if arm_id == "native_tools_baseline" else (
        "graph" if arm_id.startswith("current_graph_baseline:") else "reference"
    )
    exposures = {task.task_id: task.comparator_exposure.get(key) for task in tasks}
    if any(not isinstance(value, str) or not value for value in exposures.values()):
        raise ValueError("every task must declare the arm's comparator exposure")
    if set(exposures) != {slot.task_id for slot in slots}:
        raise ValueError("comparator population must preserve every declared task")
    groups: dict[str, list[GradedSlotRecord]] = {}
    for slot in slots:
        exposure = exposures.get(slot.task_id)
        if not isinstance(exposure, str):
            raise ValueError("slot has no declared comparator exposure")
        groups.setdefault(exposure, []).append(slot)
    summaries: dict[str, dict[str, Any]] = {}
    for exposure, population in sorted(groups.items()):
        summary = aggregate_arm_summary(
            arm_id, backend, population, expected_task_ids=[slot.task_id for slot in population],
        ).to_dict()
        summaries[exposure] = {name: value for name, value in summary.items() if name not in {"slots", "arm_id", "backend"}}
    return {"comparator_exposure_by_task": exposures, "exposure_strata": summaries}
