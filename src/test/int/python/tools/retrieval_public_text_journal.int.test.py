"""Core journal integration: genuine temporary journals, unchanged load/raw verification and framing.

Synthetic fixtures only (registered task objects over the pure public fixture);
this is never native-origin evidence and runs no model, database or network.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from repomap_test_support.w5_experiment_support import experiment_source_closure
from repomap_test_support.w5_public_text_artifacts import SyntheticStudy, synthetic_admission, synthetic_raw_component
from repomap_test_support.w5_public_text_journal import begin_component_journal, finish_component_journal
from retrieval_public_text_allocation import (
    AllocationRefused, StudySpec, WorkerSpec, finish_study, finish_worker, read_state, reserve_study, reserve_worker,
)
from retrieval_public_text_report import component_evidence
from retrieval_public_text_request import encode_dual_arm_request
from retrieval_public_text_sources import evaluator_closure, worker_closure
from retrieval_public_text_tasks import load_selected_calibration_tasks, registered_task_pins
from retrieval_semantic_experiment_artifacts import ARTIFACT_LINE_PREFIX, emit_attempt_artifacts
from retrieval_semantic_pair_artifacts import PairReportRefusal, load_journal
from retrieval_semantic_raw_component import verify_raw_component

REPO = Path(__file__).resolve().parents[5]
CATALOG = REPO / "src/test/fixtures/retrieval_evaluation/mixed-v1/tasks/catalog-v1.json"


def test_two_generation_journals_reconcile_load_and_frame_after_both_generations(tmp_path: Path) -> None:
    worker = worker_closure(REPO)
    evaluator = evaluator_closure(REPO, experiment_source_closure(REPO)[0])
    tasks = load_selected_calibration_tasks(CATALOG, registered_task_pins())
    journal_root = tmp_path.resolve() / "journals"
    directories = []
    for generation in (1, 2):
        value = SyntheticStudy(tmp_path / f"study-{generation}", generation=generation, registered_tasks=tasks).build()
        request_raw = encode_dual_arm_request(value)
        admission_raw = synthetic_admission(request_raw, worker.digests)
        raw = synthetic_raw_component(tmp_path / f"model-{generation}", request_raw, source_files=worker.files,
                                      admission_raw=admission_raw)
        journal = begin_component_journal(
            journal_root, attempt_id=f"w5-semantic-g{generation}", generation=generation,
            task_ids=[t.task_id for t in tasks.for_generation(generation)], request_raw=request_raw,
            admission_raw=admission_raw, evaluator=evaluator, worker=worker, input_files={})
        artifact = finish_component_journal(journal, request_raw=request_raw, admission_raw=admission_raw,
                                            response=raw.parse(), raw_members=dict(raw.members), status="completed")
        reloaded = load_journal(journal.directory)
        assert reloaded.declaration == artifact.declaration and reloaded.generation == generation
        summary = verify_raw_component(reloaded, dict(raw.members))
        assert dict(summary.counts) == dict(raw.counts)
        evidence = component_evidence(reloaded, dict(raw.members))
        assert evidence["component_status"]["state"] != "not_recorded"
        tampered = {**raw.members, "terminal.json": raw.members["terminal.json"] + b" "}
        with pytest.raises(PairReportRefusal):
            verify_raw_component(reloaded, tampered)
        directories.append(str(journal.directory))
    stream = io.StringIO()
    emit_attempt_artifacts(directories, stream=stream)
    lines = [line for line in stream.getvalue().splitlines() if line]
    assert lines and all(line.startswith(ARTIFACT_LINE_PREFIX) for line in lines)
    assert len(lines) == 2 * 6 + 1


@pytest.mark.parametrize("cleanup_clean,code,opposite", [
    (True, "study_evidence_failed", "study_cleanup_failed"),
    (False, "study_cleanup_failed", "study_evidence_failed"),
])
def test_functional_allocation_terminal_reloads_actual_cleanup_verdict(
        tmp_path: Path, cleanup_clean: bool, code: str, opposite: str) -> None:
    """Synthetic bookkeeping over real private files, with zero model/native reservations."""
    digest = "sha256:" + "a" * 64
    root = tmp_path.resolve() / "functional-allocation"
    study = StudySpec("REPOMAP-CLOE-PUBLIC-TEXT1", "functional-terminal-classification",
                      digest, digest, digest, digest, digest, functional_only=True)
    reserve_study(root, study)
    for generation in (1, 2):
        unique = "sha256:" + str(generation) * 64
        worker = WorkerSpec(generation, digest, unique, unique, unique, str(generation) * 64,
                            unique, unique, unique, unique)
        reserve_worker(root, study, worker, stale_g1_proof_sha256=None if generation == 1 else digest)
        finish_worker(root, study, worker, status="completed", clean=True)
    with pytest.raises(AllocationRefused):
        finish_study(root, study, status="failed", failure_code=opposite, cleanup_clean=cleanup_clean,
                     cleanup_evidence_sha256=digest)
    finish_study(root, study, status="failed", failure_code=code, cleanup_clean=cleanup_clean,
                 cleanup_evidence_sha256=digest)
    terminal = read_state(root, study)["study-terminal.json"]
    assert terminal is not None
    assert terminal["clean"] is cleanup_clean and terminal["failure_code"] == code
    assert terminal["functional_only"] is True and terminal["native_status"] == "not_asserted"


def test_driver_keeps_actual_journal_write_failure_beside_primary(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Real exclusive journal writes fail; the original study cause remains primary."""
    import json
    import repomap_test_support.w5_public_text_study as study
    from repomap_test_support.w5_public_text_journal import FAILURE_NAME

    root = tmp_path.resolve()
    worker = worker_closure(REPO)
    evaluator = evaluator_closure(REPO, experiment_source_closure(REPO)[0])
    tasks = load_selected_calibration_tasks(CATALOG, registered_task_pins())
    value = SyntheticStudy(root / "synthetic", generation=1, registered_tasks=tasks).build()
    request = encode_dual_arm_request(value)
    admission = synthetic_admission(request, worker.digests)

    def broken(self) -> None:
        self.declare()
        gen = self.gens[1]
        gen.request_raw, gen.admission_raw = request, admission
        gen.journal = begin_component_journal(
            root / "journals", attempt_id="w5-semantic-g1", generation=1,
            task_ids=[t.task_id for t in tasks.for_generation(1)], request_raw=request,
            admission_raw=admission, evaluator=evaluator, worker=worker, input_files={})
        # This is an actual pre-existing exclusive destination, not a mocked writer.
        (gen.journal.directory / "report.json").write_bytes(b"{}\n")
        raise study.StudyFailure("operation_failed", "G1_OBSERVED")

    monkeypatch.setattr(study._Driver, "run", broken)
    env = study.StudyEnvironment(database=None, repo_root=REPO, workspace=root / "workspace",
                                 journal_root=root / "journals", report_root=root / "report", functional_only=True)
    outcome = study.run_public_text_study(env)
    assert (outcome.state, outcome.failure_code) == ("G1_OBSERVED", "operation_failed")
    assert "journal_finish_failed" in outcome.diagnostic_errors
    receipt = json.loads((env.report_root / FAILURE_NAME).read_bytes())
    assert receipt["failure_code"] == "operation_failed" and receipt["cleanup"]["status"] == "not_run"
    assert outcome.native_reservations == 0
