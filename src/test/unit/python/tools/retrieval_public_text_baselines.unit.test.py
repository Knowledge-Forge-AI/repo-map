"""Incumbent cells: original operations and grades kept, file grading independent of execution state."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import repomap_test_support.w5_public_text_baselines as baselines
from common_lore_index.retrieval.query_contracts import CapabilityState
from repomap_test_support.w5_public_text_baselines import FileGrading, incumbent_cell, run_incumbent_cells, safe_code
from repomap_test_support.w5_public_text_generation import GenerationResources
from retrieval_evaluation_attempts import AttemptJournal, admit_attempt
from retrieval_evaluation_execution import failed_outcome
from retrieval_evaluation_grading import ExecutionState
from retrieval_public_text_census import retained_task_sha256
from retrieval_public_text_fusion import METRIC_KEYS
from retrieval_public_text_report_cells import INCUMBENT_ARMS, validate_cell
from retrieval_public_text_tasks import load_selected_calibration_tasks, registered_task_pins
from retrieval_semantic_baseline_capture import BaselineCorrespondenceRunner
from retrieval_semantic_experiment_scope import BaselineCorrespondenceSidecar

REPO = Path(__file__).resolve().parents[5]
CATALOG = REPO / "src/test/fixtures/retrieval_evaluation/mixed-v1/tasks/catalog-v1.json"
METRICS = {name: 0.5 for name in METRIC_KEYS}


@pytest.fixture(scope="module")
def task() -> Any:
    return load_selected_calibration_tasks(CATALOG, registered_task_pins()).tasks[0]


def _completed(task: Any, arm: str) -> Any:
    state, envelope, elapsed, layers = failed_outcome(task, arm, "placeholder", 5)
    envelope = replace(envelope, capability_state=CapabilityState.AVAILABLE, scope_complete=True,
                       provenance={"adapter_id": arm}).validate()
    return ExecutionState.COMPLETED, envelope, elapsed, layers


def test_safe_codes_are_closed_and_bounded() -> None:
    assert safe_code("Refusal Code!", "x") == "refusal_code" and safe_code(None, "fallback") == "fallback"
    assert safe_code("a" * 200, "x") == "a" * 96 and safe_code("///", "fallback") == "fallback"


def test_failed_operation_stays_failed_with_not_run_grading(task: Any) -> None:
    value = incumbent_cell(task, INCUMBENT_ARMS[0], 1, failed_outcome(task, INCUMBENT_ARMS[0], "OSError", 3),
                           FileGrading("not_run", "execution_not_completed", None))
    validate_cell(value)
    assert value["state"] == "failed" and value["reason"] == {"source": "experiment", "code": "oserror"}
    assert value["metrics"] is None and value["file_grading"] == {"state": "not_run", "reason": "execution_not_completed"}
    assert value["task_sha256"] == retained_task_sha256(task) and value["result"]["sha256"].startswith("sha256:")


def test_completed_operation_with_grading_gap_stays_completed_without_metrics(task: Any) -> None:
    outcome = _completed(task, INCUMBENT_ARMS[1])
    gap = incumbent_cell(task, INCUMBENT_ARMS[1], 2, outcome, FileGrading("gap", "file_metric_provenance_unresolved", None))
    assert gap["state"] == "completed" and gap["metrics"] is None and gap["file_grading"]["state"] == "gap"
    verified = incumbent_cell(task, INCUMBENT_ARMS[1], 2, outcome, FileGrading("verified", None, METRICS))
    assert verified["metrics"] == METRICS and verified["file_grading"] == {"state": "verified", "reason": None}
    with pytest.raises(ValueError):
        incumbent_cell(task, INCUMBENT_ARMS[1], 2, outcome, FileGrading("not_run", "execution_not_completed", None))


class _Runner:
    def __init__(self) -> None:
        self.executed: list[str] = []

    def execute(self, arm: str, task: Any, callback: Any) -> Any:
        self.executed.append(arm)
        return callback("live-pin")

    def sidecar(self, arm: str, task: Any, *, envelope: Any, projection: Any) -> Any:
        return SimpleNamespace(arm=arm)


def test_six_original_arms_three_repetitions_with_actual_failures_and_grading(task: Any, tmp_path: Path,
                                                                            monkeypatch: pytest.MonkeyPatch) -> None:
    def execute(arm: str, selected: Any, *, expected_pin: Any) -> Any:
        assert expected_pin == "live-pin" and selected is task
        if arm == "captured_projection_reference:sqlite":
            raise OSError("private backend detail")
        return _completed(task, arm)

    def grading(selected: Any, arm: str, state: Any, envelope: Any, sidecar: Any) -> Any:
        if arm == "native_tools_baseline":
            return None, "not_applicable", "file_metric_not_applicable", None
        if arm == "current_graph_baseline:sqlite":
            return None, "gap", "file_metric_provenance_unresolved", None
        return dict(METRICS), "verified", None, None

    monkeypatch.setattr(baselines, "baseline_file_metrics_with_correspondence", grading)
    resources = SimpleNamespace(generation=task.generation, context=SimpleNamespace(
        execute=execute, sqlite_projection=None, postgres_projection=None))
    journal = admit_attempt(tmp_path, {"attempt_id": "w5-semantic-g1", "candidate_closure_digests": {}}, {})
    runner = _Runner()
    run = run_incumbent_cells(cast(GenerationResources, resources), cast(BaselineCorrespondenceRunner, runner),
                              task, journal=journal)
    assert [c["arm"] for c in run.cells] == [arm for arm in INCUMBENT_ARMS for _ in range(3)]
    assert [c["repetition"] for c in run.cells] == [1, 2, 3] * 6 and len(run.lexical) == 3
    assert runner.executed == [arm for arm in INCUMBENT_ARMS for _ in range(3)] and run.failed_operations == 3
    by_arm = {arm: [c for c in run.cells if c["arm"] == arm] for arm in INCUMBENT_ARMS}
    assert all(c["state"] == "failed" for c in by_arm["captured_projection_reference:sqlite"])
    assert all(c["file_grading"]["state"] == "not_applicable" for c in by_arm["native_tools_baseline"])
    assert all(c["file_grading"]["state"] == "gap" and c["metrics"] is None
               for c in by_arm["current_graph_baseline:sqlite"])
    assert all(c["metrics"] == METRICS for c in by_arm["postgres_native_fts:postgresql"])
    for value in run.cells:
        validate_cell(value)
    text = json.dumps(run.cells)
    assert "private backend detail" not in text and "correspondence" not in text
    events = [json.loads(line)["event"] for line in (journal.directory / "observations.jsonl").read_text().splitlines()]
    assert events.count("query_started") == 18 and events.count("task_graded") == 6


def test_task_from_another_generation_is_refused(task: Any) -> None:
    with pytest.raises(ValueError):
        run_incumbent_cells(cast(GenerationResources, SimpleNamespace(generation=2)),
                            cast(BaselineCorrespondenceRunner, _Runner()), task,
                            journal=cast(AttemptJournal, None))


@pytest.mark.parametrize("error", [RuntimeError("private correspondence defect"), KeyboardInterrupt(), SystemExit(3)])
def test_correspondence_errors_are_never_silently_replaced_with_gaps(
        task: Any, monkeypatch: pytest.MonkeyPatch, error: BaseException) -> None:
    def broken(*args: Any, **kwargs: Any) -> Any:
        raise error

    monkeypatch.setattr(baselines, "baseline_file_metrics_with_correspondence", broken)
    resources = SimpleNamespace(context=SimpleNamespace(sqlite_projection=None, postgres_projection=None))
    with pytest.raises(type(error)) as raised:
        baselines._grading(task, INCUMBENT_ARMS[0], _completed(task, INCUMBENT_ARMS[0]),
                           cast(BaselineCorrespondenceRunner, _Runner()),
                           cast(GenerationResources, resources))
    assert raised.value is error


@pytest.mark.parametrize("error", [RuntimeError("unexpected grading defect"), KeyError("private key"),
                                 TypeError("unexpected type")])
def test_actual_correspondence_helper_propagates_unexpected_errors(task, monkeypatch, error) -> None:
    import repomap_test_support.w5_experiment_vector as vector
    from retrieval_semantic_experiment_scope import CorrespondenceCostSample

    sidecar = SimpleNamespace(captured_gap_cost=lambda *args: CorrespondenceCostSample())
    monkeypatch.setattr(vector, "verify_baseline_correspondence_sidecar",
                        lambda *args, **kwargs: (_ for _ in ()).throw(error))
    state, envelope, *_ = _completed(task, INCUMBENT_ARMS[1])
    with pytest.raises(type(error)) as raised:
        vector.baseline_file_metrics_with_correspondence(
            task, INCUMBENT_ARMS[1], state, envelope, cast(BaselineCorrespondenceSidecar, sidecar))
    assert raised.value is error


def test_actual_correspondence_helper_preserves_a_known_refusal_as_gap(task, monkeypatch) -> None:
    import repomap_test_support.w5_experiment_vector as vector
    from retrieval_semantic_experiment_contracts import ExperimentRefusal
    from retrieval_semantic_experiment_scope import CorrespondenceCostSample

    sidecar = SimpleNamespace(captured_gap_cost=lambda *args: CorrespondenceCostSample())
    monkeypatch.setattr(vector, "verify_baseline_correspondence_sidecar",
                        lambda *args, **kwargs: (_ for _ in ()).throw(ExperimentRefusal("baseline_capture_required")))
    state, envelope, *_ = _completed(task, INCUMBENT_ARMS[1])
    metrics, status, reason, cost = vector.baseline_file_metrics_with_correspondence(
        task, INCUMBENT_ARMS[1], state, envelope, cast(BaselineCorrespondenceSidecar, sidecar))
    assert metrics is None and status == "gap" and reason == "baseline_capture_required"
    assert cost.correspondence_failures == 1
