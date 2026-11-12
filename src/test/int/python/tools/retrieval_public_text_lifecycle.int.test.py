"""Complete functional public-text lifecycle: the SAME driver with synthetic raw delivery (study section 19).

Selected only by the existing ``requires_pgvector`` profile. Both actual
mixed-v1 publications, the genuine six incumbent operations, the study SQL,
all 864 cells, the real ComponentExchange boundaries, genuine journals, the
strict report read with raw evidence and owned cleanup all run. Only the raw
worker delivery is synthetic; nothing here is model, native or relevance
evidence, and no allocation is reserved.
"""

from __future__ import annotations

import json
import io
from pathlib import Path
import sys
import zipfile
from typing import cast

import pytest

from repomap_test_support.postgres_harness import temporary_postgres
from repomap_test_support.w5_experiment_support import DECLARED_PROFILE_IDENTITY, experiment_source_closure
from repomap_test_support.w5_public_text_evidence import (
    TRANSITION_GATE_NAME, TRANSITION_NAME, read_private_file, write_private_file,
)
from repomap_test_support.w5_public_text_study import REPORT_NAME, StudyEnvironment, run_public_text_study
from retrieval_public_text_export import decode_study_evidence
from retrieval_public_text_native_gate import PREFIX, read_actual_gate
from retrieval_public_text_preflight import check_transition_observation
from retrieval_public_text_report import ReportEvidence, read_verified_report
from retrieval_public_text_report_cells import INCUMBENT_ARMS, LEARNED_ARMS
from retrieval_public_text_sources import evaluator_closure
from retrieval_public_text_tasks import load_selected_calibration_tasks, registered_task_pins
from retrieval_semantic_bridge_transport import READY_PREFIX
from retrieval_semantic_experiment_artifacts import ARTIFACT_LINE_PREFIX, decode_attempt_artifacts
from retrieval_semantic_pair_artifacts import load_journal
from retrieval_public_text_contracts import PrivateMarkerScope
from test_sandbox_contract import INNER_REPORT_ROOT


def _export_root(tmp_path: Path) -> Path:
    """The existing canonical report root when present (canonical sandbox), else a private temp root."""
    if INNER_REPORT_ROOT.is_dir():
        return INNER_REPORT_ROOT / "public-text-functional"
    return tmp_path.resolve() / "report"


@pytest.mark.requires_pgvector
def test_public_text_functional_lifecycle(tmp_path: Path, capfd: pytest.CaptureFixture[str]) -> None:
    repo = Path(__file__).resolve().parents[5]
    work = tmp_path.resolve()
    export = _export_root(tmp_path)
    with temporary_postgres() as database:
        outcome = run_public_text_study(StudyEnvironment(
            database=database, repo_root=repo, workspace=work / "workspace", journal_root=export / "journals",
            report_root=export, functional_only=True))
    captured = capfd.readouterr()
    stdout = captured.out.encode("utf-8")
    sys.stdout.write(captured.out)
    sys.stderr.write(captured.err)
    assert outcome.failure_code is None, (outcome.state, outcome.failure_code)
    assert outcome.failure_receipt_sha256 is None and outcome.native_reservations == 0
    assert outcome.diagnostic_errors == ()
    assert outcome.state == "REPORTED" and outcome.observed_cells == 864
    assert outcome.verification == "raw_evidence_verified"
    assert outcome.cleanup is not None and outcome.cleanup["status"] == "clean"
    assert all(item["absent"] is True for item in outcome.cleanup["objects"])
    assert len(outcome.frame_sha256) == 2 and outcome.frame_sha256[0] != outcome.frame_sha256[1]

    counts = outcome.record_counts
    assert counts["1"]["ptx.query"] >= 1 and counts["1"]["v1.query"] <= 4
    assert counts["2"]["v1.query"] == counts["2"]["ptx.query"] == 0 and counts["2"]["ptx.document"] >= 1
    pins = registered_task_pins()
    catalog = repo / "src/test/fixtures/retrieval_evaluation/mixed-v1/tasks/catalog-v1.json"
    selected = load_selected_calibration_tasks(catalog, pins)
    evaluator = evaluator_closure(repo, experiment_source_closure(repo)[0])
    transition = json.loads(read_private_file(export / TRANSITION_NAME))
    gate = check_transition_observation(
        transition, actual_counts=counts, q_source_closure_identity=evaluator.identity, task_pins_identity=pins.identity(),
        selected_task_set_identity=selected.identity(),
        artifact_profile_identity=DECLARED_PROFILE_IDENTITY)
    assert transition == outcome.transition and gate == json.loads(read_private_file(export / TRANSITION_GATE_NAME))
    assert cast(float, gate["observed_interval_seconds"]) + 120 <= 600

    journals = {g: load_journal(export / "journals" / f"w5-semantic-g{g}") for g in (1, 2)}
    raw_members = {g: {name: read_private_file(export / "raw-components" / f"w5-semantic-g{g}" / name)
                       for name in ("declaration.json", "report.json", "source-manifest.json", "sources.zip", "terminal.json")}
                   for g in (1, 2)}
    scope = PrivateMarkerScope.create((str(work / "workspace"), str(export / "journals")))
    read = read_verified_report(export / REPORT_NAME, ReportEvidence(
        {g: (journals[g], raw_members[g]) for g in (1, 2)}, selected, scope))
    assert read.verification == "raw_evidence_verified"
    decoded = decode_attempt_artifacts(stdout)
    assert decoded == {f"w5-semantic-g{g}/{name}": data
                       for g, journal in journals.items() for name, data in journal.members.items()}
    extras = decode_study_evidence(stdout, journal_decoded_bytes=sum(map(len, decoded.values())),
                                  expected_functional_only=True)
    assert extras[REPORT_NAME] == read_private_file(export / REPORT_NAME)
    for name in (TRANSITION_NAME, TRANSITION_GATE_NAME):
        assert extras[name] == read_private_file(export / name)
    for g, members in raw_members.items():
        assert all(extras[f"raw-components/w5-semantic-g{g}/{name}"] == raw for name, raw in members.items())
    readiness = [json.loads(line[len(READY_PREFIX):]) for line in captured.out.splitlines()
                 if line.startswith(READY_PREFIX)]
    assert [item["attempt_id"] for item in readiness] == ["w5-semantic-g1", "w5-semantic-g2"]
    gate_output = stdout[:stdout.index(ARTIFACT_LINE_PREFIX.encode())]
    second_start = gate_output.index(PREFIX, gate_output.index(PREFIX) + len(PREFIX))
    for g, ready in enumerate(readiness, 1):
        log = work / f"actual-generation-{g}.stdout.log"
        write_private_file(log, gate_output[:second_start] if g == 1 else gate_output)
        frame, payload, identity = read_actual_gate(log, generation=g, nonce=ready["nonce"],
                                                   request_sha256=ready["request_sha256"])
        assert identity == outcome.frame_sha256[g - 1]
        assert frame["q_source_closure_identity"] == evaluator.identity
        assert frame["selected_task_set_identity"] == selected.identity()
        with zipfile.ZipFile(io.BytesIO(journals[g].members["sources.zip"])) as archive:
            assert archive.read("inputs/generation-gate.json") == payload
            assert json.loads(archive.read("inputs/task-pins.json")) == pins.to_dict()
            assert json.loads(archive.read("inputs/selected-task-objects.json")) == [t.to_dict() for t in selected.tasks]
    report = read.report
    assert report["functional_only"] is True and all(flag is False for flag in report["acceptance"].values())
    assert report["counts"]["cells"]["value"] == 864 and report["observation_status"] == "all_cells_observed"
    assert {row["fences"]["execution_kind"] for row in report["generations"]} == {"synthetic_functional"}
    cells = report["cells"]
    assert sum(1 for c in cells if c["generation"] == 1) == 828
    assert all(c["state"] != "failed" for c in cells)
    incumbents = [c for c in cells if c["arm"] in INCUMBENT_ARMS]
    assert len(incumbents) == 432 and any(c["state"] == "completed" for c in incumbents)
    assert {c["arm"] for c in incumbents if c["file_grading"]["state"] == "verified"} == set(INCUMBENT_ARMS)
    assert all(c["file_grading"]["state"] == "not_run" for c in incumbents if c["state"] != "completed")
    learned = [c for c in cells if c["arm"] in LEARNED_ARMS]
    completed = [c for c in learned if c["state"] == "completed"]
    assert completed and all(c["file_grading"]["state"] == "verified" and c["metrics"] for c in completed)
    assert all(c["plan"]["index_selected"] is True for c in completed if c["arm"].startswith("hnsw_vector:"))
    for c in learned:
        if c["generation"] == 2:
            assert c["state"] in ("refused", "unavailable")
            assert c["reason"]["source"] in ("v1_decision", "public_text_decision")
    raw = (export / REPORT_NAME).read_bytes()
    for private in (str(work), str(repo), "/sandbox-scratch", "BOUNDARY_START_TOKEN"):
        assert private.encode() not in raw
    assert json.loads(raw)["study_identity"] == report["study_identity"]
