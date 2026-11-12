"""Genuine component journals over real filesystem primitives, and the closed failure receipt."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from repomap_test_support.w5_experiment_support import experiment_source_closure
from repomap_test_support.w5_public_text_artifacts import (
    MODEL_MEMBERS, SyntheticStudy, synthetic_admission, synthetic_raw_component,
)
from repomap_test_support.w5_public_text_journal import (
    FAILURE_NAME, StudyFailureReceipt, StudyJournalRefusal, begin_component_journal, finish_component_journal,
    record_operation, validate_failure_receipt, write_failure_receipt,
)
from retrieval_public_text_request import encode_dual_arm_request
from retrieval_public_text_sources import evaluator_closure, worker_closure
from retrieval_semantic_pair_artifacts import PairReportRefusal
from retrieval_semantic_raw_component import verify_raw_component

REPO = Path(__file__).resolve().parents[5]
D = "sha256:" + "d" * 64


@pytest.fixture(scope="module")
def closures():
    return worker_closure(REPO), evaluator_closure(REPO, experiment_source_closure(REPO)[0])


def _component(tmp_path: Path, worker, generation: int = 1):
    request_raw = encode_dual_arm_request(SyntheticStudy(tmp_path / "study", generation=generation).build())
    admission_raw = synthetic_admission(request_raw, worker.digests)
    raw = synthetic_raw_component(tmp_path / "model", request_raw, source_files=worker.files,
                                  admission_raw=admission_raw)
    return request_raw, admission_raw, raw


def _begin(tmp_path: Path, closures, request_raw: bytes, admission_raw: bytes, generation: int = 1):
    worker, evaluator = closures
    return begin_component_journal(
        tmp_path / "journals", attempt_id=f"w5-semantic-g{generation}", generation=generation,
        task_ids=["cal-01"], request_raw=request_raw, admission_raw=admission_raw, evaluator=evaluator,
        worker=worker, input_files={"publication.json": b"{}"})


def test_recorded_component_reconciles_through_unchanged_raw_verification(tmp_path: Path, closures) -> None:
    worker, evaluator = closures
    request_raw, admission_raw, raw = _component(tmp_path, worker)
    journal = _begin(tmp_path, closures, request_raw, admission_raw)
    record_operation(journal, "study_cell", task_id="cal-01", arm="native_tools_baseline", repetition=1)
    artifact = finish_component_journal(journal, request_raw=request_raw, admission_raw=admission_raw,
                                        response=raw.parse(), raw_members=dict(raw.members), status="completed")
    assert artifact.declaration["candidate_closure_digests"] == dict(evaluator.digests)
    assert artifact.declaration["component_source_closure"] == dict(worker.digests)
    assert artifact.report["component_counts"] == dict(raw.counts)
    summary = verify_raw_component(artifact, dict(raw.members))
    assert dict(summary.counts) == dict(raw.counts)
    assert [event["event"] for event in artifact.observations][:2] == ["component_admission_accepted", "study_cell"]


def test_tampered_members_or_foreign_counts_refuse_after_the_journal_is_written(tmp_path: Path, closures) -> None:
    worker, _evaluator = closures
    request_raw, admission_raw, raw = _component(tmp_path, worker)
    tampered = dict(raw.members)
    tampered["report.json"] = raw.members["report.json"].replace(b'"elapsed_seconds":3.0', b'"elapsed_seconds":4.0')
    assert tampered["report.json"] != raw.members["report.json"]
    journal = _begin(tmp_path, closures, request_raw, admission_raw)
    with pytest.raises(PairReportRefusal):
        finish_component_journal(journal, request_raw=request_raw, admission_raw=admission_raw,
                                 response=raw.parse(), raw_members=tampered, status="completed")
    other_request, other_admission, _ = _component(tmp_path / "other", worker, generation=2)
    second = _begin(tmp_path / "second", closures, other_request, other_admission, generation=2)
    with pytest.raises(PairReportRefusal):
        finish_component_journal(second, request_raw=other_request, admission_raw=other_admission,
                                 response=raw.parse(), raw_members=dict(raw.members), status="completed")


def test_failure_before_a_component_is_not_recorded_and_never_completed(tmp_path: Path, closures) -> None:
    worker, _evaluator = closures
    request_raw, admission_raw, raw = _component(tmp_path, worker)
    journal = _begin(tmp_path, closures, request_raw, admission_raw)
    for kwargs in ({"status": "completed"}, {"status": "failed"}, {"status": "failed", "failure_code": "invented"},
                   {"status": "failed", "failure_code": "seal_refused", "response": raw.parse()}):
        with pytest.raises(StudyJournalRefusal):
            finish_component_journal(journal, request_raw=request_raw, admission_raw=admission_raw,
                                      **{"response": None, "raw_members": None, **kwargs})
    artifact = finish_component_journal(journal, request_raw=request_raw, admission_raw=admission_raw, response=None,
                                        raw_members=None, status="failed", failure_code="seal_refused")
    assert artifact.report["component_status"] == "not_recorded" and "component" not in artifact.report
    assert artifact.terminal["status"] == "failed"
    with pytest.raises(RuntimeError):
        record_operation(journal, "study_cell")


def test_begin_refuses_mismatched_attempts_reserved_inputs_and_unknown_events(tmp_path: Path, closures) -> None:
    worker, evaluator = closures
    request_raw, admission_raw, _raw = _component(tmp_path, worker)
    for kwargs in ({"attempt_id": "w5-semantic-g2"}, {"input_files": {"request.json": b"x"}},
                   {"worker": evaluator}, {"generation": True}, {"generation": 1.0}):
        values = {"attempt_id": "w5-semantic-g1", "generation": 1, "task_ids": ["cal-01"], "request_raw": request_raw,
                  "admission_raw": admission_raw, "evaluator": evaluator, "worker": worker, "input_files": {}}
        values.update(kwargs)
        with pytest.raises(StudyJournalRefusal):
            begin_component_journal(tmp_path / "refused", **values)
    journal = _begin(tmp_path, closures, request_raw, admission_raw)
    with pytest.raises(StudyJournalRefusal):
        record_operation(journal, "free_text_event", message="anything")


def _receipt(**changes) -> StudyFailureReceipt:
    values: dict[str, Any] = {
        "functional_only": True, "study_identity": D, "q_source_closure_identity": D, "task_pins_identity": D,
        "stop_state": "G2_PUBLISHED", "failure_code": "publication_failed", "observed_cells": 828,
        "components": ((1, D), (2, None)), "cleanup_status": "clean", "cleanup_reason": None}
    values.update(changes)
    return StudyFailureReceipt(**values)


def test_failure_receipt_is_closed_truthful_and_written_once(tmp_path: Path) -> None:
    value = _receipt().to_dict()
    assert (value["planned_cells"], value["observed_cells"], value["unknown_cells"]) == (864, 828, 36)
    assert value["components"][1] == {"generation": 2, "state": "not_recorded", "report_sha256": None}
    digest = write_failure_receipt(tmp_path.resolve(), _receipt())
    raw = (tmp_path / FAILURE_NAME).read_bytes()
    assert digest.startswith("sha256:") and json.loads(raw) == value and b"/" not in raw.replace(b"sha256:", b"")
    with pytest.raises(FileExistsError):
        write_failure_receipt(tmp_path.resolve(), _receipt())
    unknown = _receipt(study_identity=None, q_source_closure_identity=None, stop_state="DECLARED",
                       failure_code="study_declaration_refused", observed_cells=0, components=(),
                       cleanup_status="not_run", cleanup_reason="cleanup_not_reached").to_dict()
    assert unknown["unknown_cells"] == 864


def test_failure_receipt_refuses_a_symlink_parent_and_preserves_other_files(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    real = root / "real"
    real.mkdir()
    sentinel = real / "sentinel"
    sentinel.write_bytes(b"unchanged")
    alias = root / "alias"
    alias.symlink_to(real, target_is_directory=True)
    with pytest.raises(StudyJournalRefusal, match="failure_receipt_root"):
        write_failure_receipt(alias / "new", _receipt())
    assert sentinel.read_bytes() == b"unchanged" and not (real / "new").exists()


@pytest.mark.parametrize("changes", [
    {"stop_state": "INVENTED"}, {"failure_code": "free text"}, {"observed_cells": 865}, {"observed_cells": True},
    {"components": ((2, None),)}, {"components": ((True, None),)}, {"components": ((1.0, None),)},
    {"components": ((1, "sha256:x"),)}, {"cleanup_status": "clean", "cleanup_reason": "x"},
    {"cleanup_status": "failed", "cleanup_reason": None}, {"study_identity": "/private/path"},
])
def test_failure_receipt_refuses_open_or_inconsistent_values(changes: dict) -> None:
    with pytest.raises(StudyJournalRefusal):
        _receipt(**changes).to_dict()
    with pytest.raises(StudyJournalRefusal):
        validate_failure_receipt({**_receipt().to_dict(), "message": "raw error text"})
    assert MODEL_MEMBERS
