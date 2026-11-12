"""The six original incumbent operations for one public-text task (study sections 11 and 19.4).

Execution reuses the maintained ``BaselineCorrespondenceRunner`` (live pins,
W5 admission, sidecars) around the unchanged ``ArmContext`` callbacks and
``measure_task_repetitions``, which grades with the original modes, golds and
rules and journals every envelope privately. Public cells carry only state,
closed reasons, flags, a result digest and the maintained correspondence file
grading; a completed operation whose file grading is not applicable or has a
gap stays completed with ``metrics: null`` and its actual reason. Original
node metrics are never copied into file metrics, and failures stay failures.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import hashlib
import json
import re
import time
from typing import Any

from repomap_test_support.w5_experiment_vector import baseline_file_metrics_with_correspondence
from repomap_test_support.w5_public_text_generation import GenerationResources
from retrieval_evaluation_attempts import AttemptJournal
from retrieval_evaluation_execution import TaskOutcome, failed_outcome, measure_task_repetitions
from retrieval_evaluation_grading import ExecutionState
from retrieval_evaluation_schema import EvaluationTask
from retrieval_public_text_census import retained_task_sha256
from retrieval_public_text_report_cells import INCUMBENT_ARMS, REPETITIONS, cell
from retrieval_semantic_baseline_capture import BaselineCorrespondenceRunner, make_baseline_correspondence_runner
from retrieval_semantic_experiment_scope import (
    BASELINE_ARM_OBSERVED_BACKENDS, BASELINE_ARM_TARGET_BACKENDS, BaselineCorrespondenceSidecar,
)

LEXICAL_ARM = "postgres_native_fts:postgresql"
RETRIEVAL_TRUNCATION_CODES = frozenset({
    "observation_page_limit", "graph_expansion_limit", "graph_result_limit", "direct_location_limit",
})
_UNSAFE = re.compile(r"[^a-z0-9_.:-]+")


def safe_code(value: object, fallback: str) -> str:
    """Closed reason grammar from an actual code; never free text."""
    text = _UNSAFE.sub("_", value.strip().lower()).strip("_") if isinstance(value, str) else ""
    return (text or fallback)[:96]


@dataclass(frozen=True, repr=False)
class FileGrading:
    """Maintained correspondence file grading for one repetition; private cost/sidecar excluded."""

    state: str
    reason: str | None
    metrics: Mapping[str, float] | None

    def __repr__(self) -> str:
        return f"FileGrading(state={self.state!r})"


@dataclass(frozen=True, repr=False)
class IncumbentRun:
    """One task's 18 incumbent cells plus the private lexical outcomes the learned hybrid fuses."""

    cells: tuple[dict[str, Any], ...]
    lexical: tuple[TaskOutcome, ...] = field(repr=False)
    failed_operations: int

    def __repr__(self) -> str:
        return f"IncumbentRun(cells={len(self.cells)}, failed_operations={self.failed_operations})"


def make_runner(resources: GenerationResources) -> BaselineCorrespondenceRunner:
    """The maintained runner bound to this generation's live readers; it owns W5 admission."""
    return make_baseline_correspondence_runner(
        BaselineCorrespondenceSidecar, resources.generation_aliases, resources.context.native_view,
        resources.sqlite_reader, resources.postgres_reader, resources.sqlite_state, resources.postgres_state)


def _projection(resources: GenerationResources, arm: str) -> Any:
    target = BASELINE_ARM_TARGET_BACKENDS[arm]
    return resources.context.sqlite_projection if target == "sqlite" else resources.context.postgres_projection


def _grading(task: EvaluationTask, arm: str, outcome: TaskOutcome, runner: BaselineCorrespondenceRunner,
             resources: GenerationResources) -> FileGrading:
    state, envelope, _elapsed, _bytes = outcome
    if state is not ExecutionState.COMPLETED:
        return FileGrading("not_run", "execution_not_completed", None)
    sidecar = runner.sidecar(arm, task, envelope=envelope, projection=_projection(resources, arm))
    metrics, status, gap, _cost = baseline_file_metrics_with_correspondence(task, arm, state, envelope, sidecar)
    if status == "verified" and metrics is not None:
        return FileGrading("verified", None, {key: float(value) for key, value in metrics.items()})
    if status == "not_applicable":
        return FileGrading("not_applicable", safe_code(gap, "file_metric_not_applicable"), None)
    return FileGrading("gap", safe_code(gap, "file_metric_gap"), None)


def _result(envelope: Any) -> dict[str, Any]:
    raw = json.dumps(envelope.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return {"sha256": "sha256:" + hashlib.sha256(raw).hexdigest(), "length": len(raw)}


def incumbent_cell(task: EvaluationTask, arm: str, repetition: int, outcome: TaskOutcome,
                   grading: FileGrading) -> dict[str, Any]:
    """Public-safe cell: actual execution state, closed reason, flags, result digest and file grading."""
    state, envelope, _elapsed, _bytes = outcome
    truncated = any(getattr(item, "reason_code", None) in RETRIEVAL_TRUNCATION_CODES for item in envelope.omissions)
    reason = None
    if state is not ExecutionState.COMPLETED:
        code = envelope.refusal_code or envelope.unavailable_reason or envelope.provenance.get("failure_type")
        reason = ("experiment", safe_code(code, state.value))
    return cell(generation=task.generation, task_id=task.task_id, task_sha256=retained_task_sha256(task), arm=arm,
                repetition=repetition, state=state.value, reason=reason, incomplete=truncated,
                retrieval_truncated=truncated, metrics=grading.metrics, result=_result(envelope),
                file_grading=(grading.state, grading.reason))


def run_incumbent_cells(resources: GenerationResources, runner: BaselineCorrespondenceRunner, task: EvaluationTask,
                        *, journal: AttemptJournal) -> IncumbentRun:
    """Three repetitions of each original incumbent arm, in original order and mode."""
    if task.generation != resources.generation:
        raise ValueError("incumbent task generation does not match the live publication")
    cells: list[dict[str, Any]] = []
    lexical: list[TaskOutcome] = []
    failed = 0
    for arm in INCUMBENT_ARMS:
        outcomes: list[TaskOutcome] = []
        gradings: list[FileGrading] = []

        def execute(selected: str = arm) -> TaskOutcome:
            started = time.perf_counter_ns()
            try:
                outcome = runner.execute(selected, task, lambda expected: resources.context.execute(
                    selected, task, expected_pin=expected))
            except Exception as error:  # external maintained operation; recorded as an actual failure
                outcome = failed_outcome(task, selected, type(error).__name__, time.perf_counter_ns() - started,
                                         backend=BASELINE_ARM_OBSERVED_BACKENDS[selected])
            gradings.append(_grading(task, selected, outcome, runner, resources))
            outcomes.append(outcome)
            return outcome

        # The maintained helper journals every envelope and the original grade ("task_graded") privately.
        measure_task_repetitions(task, arm, len(REPETITIONS), execute, journal)
        if len(outcomes) != len(REPETITIONS):
            raise RuntimeError("incumbent repetition capture lost an outcome")
        for repetition, outcome, grading in zip(REPETITIONS, outcomes, gradings, strict=True):
            cells.append(incumbent_cell(task, arm, repetition, outcome, grading))
            failed += int(outcome[0] is ExecutionState.FAILED)
        if arm == LEXICAL_ARM:
            lexical.extend(outcomes)
    return IncumbentRun(tuple(cells), tuple(lexical), failed)


__all__ = [
    "FileGrading", "IncumbentRun", "LEXICAL_ARM", "incumbent_cell", "make_runner", "run_incumbent_cells",
    "safe_code",
]
