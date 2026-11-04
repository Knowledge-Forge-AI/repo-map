"""Opt-in result-v2 wiring for the W5 integration owner.

The legacy journal and report remain the primary evidence.  This helper only
collects records when the designated optional caller enables result-v2 before
its source freeze.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import sys
from typing import Any, TypeGuard

from common_lore_index.retrieval.query_contracts import QueryEnvelope
from retrieval_evaluation_execution import TaskOutcome
from retrieval_evaluation_grading import ExecutionState
from retrieval_evaluation_schema import EvaluationTask
from retrieval_semantic_baseline_result_frames import emit_result_frames, read_raw_journal_members
from retrieval_semantic_baseline_result_objects import BaselineResultV2, ResultV2Collector
from retrieval_semantic_experiment_contracts import (
    ExperimentCell, ExperimentPlan, ExperimentRefusal,
)
from retrieval_semantic_experiment_scope import (
    BaselineCorrespondenceSidecar,
    CorrespondenceCostSample,
)
from retrieval_semantic_provenance import VerifiedPublicationPin
from retrieval_semantic_observed_operation_results import append_unadmitted_vector_observations
from retrieval_evaluation_admission_w5_capture import retain_native_work


BaselineMetrics = tuple[
    dict[str, float] | None,
    str,
    str | None,
    CorrespondenceCostSample,
]
MetricsReader = Callable[
    [EvaluationTask, str, ExecutionState, QueryEnvelope, BaselineCorrespondenceSidecar],
    BaselineMetrics,
]
CellSink = Callable[[Mapping[str, object], ExperimentCell], None]
_SAFE_FAILURE_CHARACTERS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_.-")


def _is_safe_failure_code(value: object) -> TypeGuard[str]:
    return (
        type(value) is str
        and bool(value)
        and value == value.strip()
        and value == value.lower()
        and all(character in _SAFE_FAILURE_CHARACTERS for character in value)
    )


def safe_failure_code(
    error: BaseException | None, *, fallback: str
) -> str:
    """Retain a safe refusal code without exposing exception class names."""
    candidate = error.code if isinstance(error, ExperimentRefusal) else None
    if _is_safe_failure_code(candidate):
        return candidate
    if _is_safe_failure_code(fallback):
        return fallback
    return "attempt_failed"


class ResultV2Run:
    """Collect typed supplementary results without changing legacy evidence."""

    def __init__(self, *, enabled: bool) -> None:
        if type(enabled) is not bool:
            raise TypeError("result-v2 enabled flag must be boolean")
        self.enabled = enabled
        self._collectors: dict[str, ResultV2Collector] = {}
        self._finished: set[str] = set()
        self._results: list[BaselineResultV2] = []

    def register(self, plan: ExperimentPlan) -> ResultV2Collector | None:
        """Bind a collector to the already-frozen experiment plan."""
        if not self.enabled:
            return None
        collector = ResultV2Collector(plan)
        if plan.attempt_id in self._collectors:
            raise ValueError("duplicate result-v2 attempt")
        self._collectors[plan.attempt_id] = collector
        return collector

    def cell_sink(self, collector: ResultV2Collector | None) -> CellSink | None:
        if collector is None:
            return None

        def sink(identity: Mapping[str, object], cell: ExperimentCell) -> None:
            collector.add_cell(identity, cell)

        return sink

    @staticmethod
    def _identity(arm_id: str, task: EvaluationTask, repetition: int) -> dict[str, object]:
        return {"arm_id": arm_id, "task_id": task.task_id, "repetition": repetition}

    def grade_baseline(
        self,
        collector: ResultV2Collector | None,
        *,
        task: EvaluationTask,
        arm_id: str,
        state: ExecutionState,
        envelope: QueryEnvelope,
        sidecar: BaselineCorrespondenceSidecar,
        metrics_reader: MetricsReader,
        repetition: int,
    ) -> tuple[dict[str, float] | None, str, str | None]:
        """Use the exact four-value correspondence result and retain its witness."""
        metrics, status, gap, cost = metrics_reader(
            task, arm_id, state, envelope, sidecar,
        )
        if collector is not None:
            reason = envelope.refusal_code or envelope.unavailable_reason
            if reason is None and state != ExecutionState.COMPLETED:
                reason = str(envelope.provenance.get("failure_reason") or state.value)
            collector.add_cell(
                self._identity(arm_id, task, repetition),
                ExperimentCell(
                    arm_id, task.task_id, state, reason=reason,
                    cleanup_status="not_applicable",
                ).validate(),
            )
            if arm_id == "native_tools_baseline" or arm_id.endswith(":sqlite"):
                target_backend = "sqlite"
            elif arm_id.endswith(":postgresql"):
                target_backend = "postgresql"
            else:
                raise ValueError("unsupported result-v2 correspondence arm")
            collector.add_correspondence(
                self._identity(arm_id, task, repetition),
                sidecar,
                observed_backend=envelope.scope.backend,
                target_backend=target_backend,
                status=status,
                gap_reason=gap,
                cost=cost,
            )
        return metrics, status, gap

    def baseline_callback(
        self,
        collector: ResultV2Collector | None,
        *,
        repetition: int,
        sidecar_factory: Callable[
            [EvaluationTask, str, QueryEnvelope], BaselineCorrespondenceSidecar
        ],
        metrics_reader: MetricsReader,
        legacy_reader: Callable[..., tuple[dict[str, float] | None, str, str | None]],
        pin: VerifiedPublicationPin,
    ) -> Callable[
        [EvaluationTask, str, ExecutionState, QueryEnvelope],
        tuple[dict[str, float] | None, str, str | None],
    ]:
        def callback(
            task: EvaluationTask,
            arm_id: str,
            state: ExecutionState,
            envelope: QueryEnvelope,
        ) -> tuple[dict[str, float] | None, str, str | None]:
            sidecar = sidecar_factory(task, arm_id, envelope)
            if collector is None:
                return legacy_reader(
                    task, arm_id, state, envelope, pin,
                    correspondence_sidecar=sidecar,
                )
            return self.grade_baseline(
                collector,
                task=task,
                arm_id=arm_id,
                state=state,
                envelope=envelope,
                sidecar=sidecar,
                metrics_reader=metrics_reader,
                repetition=repetition,
            )

        return callback

    def baseline_callback_for_runner(
        self,
        collector: ResultV2Collector | None,
        *,
        repetition: int,
        runner: Any,
        sqlite_projection: object,
        postgres_projection: object,
        metrics_reader: MetricsReader,
        legacy_reader: Callable[..., tuple[dict[str, float] | None, str, str | None]],
        pin: VerifiedPublicationPin,
    ) -> Callable[
        [EvaluationTask, str, ExecutionState, QueryEnvelope],
        tuple[dict[str, float] | None, str, str | None],
    ]:
        def sidecar_factory(
            task: EvaluationTask, arm_id: str, envelope: QueryEnvelope,
        ) -> BaselineCorrespondenceSidecar:
            retain_native_work(
                runner, collector, arm_id, task, envelope,
                self._identity(arm_id, task, repetition),
            )
            projection = (
                sqlite_projection
                if arm_id == "native_tools_baseline" or arm_id.endswith(":sqlite")
                else postgres_projection
            )
            return runner.sidecar(
                arm_id, task, envelope=envelope, projection=projection,
            )

        return self.baseline_callback(
            collector,
            repetition=repetition,
            sidecar_factory=sidecar_factory,
            metrics_reader=metrics_reader,
            legacy_reader=legacy_reader,
            pin=pin,
        )

    def captured_executor(
        self,
        context: Any,
        *,
        collector: ResultV2Collector | None,
        arm_id: str,
        task: EvaluationTask,
        repetition: int,
    ) -> Callable[[VerifiedPublicationPin], TaskOutcome]:
        return lambda expected: self.execute_arm(
            context,
            collector=collector,
            arm_id=arm_id,
            task=task,
            repetition=repetition,
            expected_pin=expected,
        )

    def record_unadmitted_vector_cells(
        self,
        journal: Any,
        *,
        task_id: str,
        generation: int,
        repetition: int,
        state: ExecutionState,
        reason: str,
        arm_ids: tuple[str, ...],
        cell_sink: CellSink | None,
    ) -> None:
        append_unadmitted_vector_observations(
            journal, task_id=task_id, generation=generation, repetition=repetition,
            state=state, reason=reason, arm_ids=arm_ids, cell_sink=cell_sink,
            include_operation=self.enabled,
        )

    def execute_arm(
        self,
        context: Any,
        *,
        collector: ResultV2Collector | None,
        arm_id: str,
        task: EvaluationTask,
        repetition: int,
        expected_pin: VerifiedPublicationPin | None,
    ) -> TaskOutcome:
        """Call the real adapter and retain native breakdowns when enabled."""
        if collector is None:
            return context.execute(arm_id, task, expected_pin=expected_pin)
        outcome, breakdown = context.execute_with_breakdown(
            arm_id, task, expected_pin=expected_pin,
        )
        if breakdown is not None:
            collector.add_byte_work(
                self._identity(arm_id, task, repetition), breakdown,
            )
        return outcome

    def finish(
        self,
        journal: Any,
        *,
        status: str,
        failure_code: str | None = None,
    ) -> None:
        """Bind exact six-member journal bytes after the terminal record exists."""
        if not self.enabled:
            return
        attempt_id = journal.directory.name
        collector = self._collectors.get(attempt_id)
        if collector is None:
            return
        if attempt_id in self._finished:
            raise ValueError("duplicate result-v2 finish")
        result = collector.finish(
            status=status,
            failure_code=failure_code,
            raw_journal_members=read_raw_journal_members(journal.directory),
        )
        self._results.append(result)
        self._finished.add(attempt_id)

    def finish_safely(
        self,
        journal: Any,
        *,
        status: str,
        failure_code: str | None,
    ) -> BaseException | None:
        try:
            self.finish(journal, status=status, failure_code=failure_code)
        except BaseException as error:
            return error
        return None

    def emit_safely(self) -> BaseException | None:
        try:
            self.emit()
        except BaseException as error:
            return error
        return None

    def emit(self) -> None:
        """Emit supplementary frames only after all legacy artifacts are emitted."""
        if self._results:
            emit_result_frames(tuple(self._results), stream=sys.stdout)


def finalize_attempt_evidence(
    journals: list[tuple[Any, Any, str, dict[str, object]]],
    *,
    result_v2: ResultV2Run,
    cleanup_status: str,
    cleanup_error: BaseException | None,
    attribution_error: BaseException | None,
    emit_legacy: Callable[[tuple[Any, ...]], None],
) -> tuple[BaseException | None, tuple[BaseException, ...]]:
    """Finish legacy journals and frames before returning V2 failures."""
    result_v2_errors: list[BaseException] = []
    for journal, costs, status, report in journals:
        report["cost"] = costs.to_dict()
        report["cleanup_status"] = cleanup_status
        terminal_status = status
        if cleanup_error is not None and status == "completed":
            terminal_status = "failed"
            report["status"] = "failed"
            report["failure_type"] = type(cleanup_error).__name__
            report["failure_code"] = safe_failure_code(
                cleanup_error, fallback="cleanup_failed"
            )
        failure_code = report.get("failure_code")
        if terminal_status == "failed" and not _is_safe_failure_code(failure_code):
            failure_code = "attempt_failed"
            report["failure_code"] = failure_code
        if terminal_status != "failed":
            failure_code = None
        try:
            journal.finish(terminal_status, report)
        except BaseException as error:
            attribution_error = attribution_error or error
        result_v2_error = result_v2.finish_safely(
            journal, status=terminal_status, failure_code=failure_code if _is_safe_failure_code(failure_code) else None
        )
        if result_v2_error is not None:
            result_v2_errors.append(result_v2_error)
    if journals and any(
        report.get("cleanup_status") != cleanup_status
        for _journal, _costs, _status, report in journals
    ):
        attribution_error = attribution_error or ExperimentRefusal(
            "campaign_cleanup_status_mismatch"
        )
    try:
        emit_legacy(tuple(item[0].directory for item in journals))
    except BaseException as error:
        attribution_error = attribution_error or error
    result_v2_error = result_v2.emit_safely()
    if result_v2_error is not None:
        result_v2_errors.append(result_v2_error)
    return attribution_error, tuple(result_v2_errors)


__all__ = [
    "ResultV2Run",
    "finalize_attempt_evidence",
    "safe_failure_code",
]
