"""Filesystem/artifact integration boundary for the W5 paired report."""

from __future__ import annotations

import io
import json
from pathlib import Path
import sys

import pytest
from repomap_test_support.w5_experiment_results import ResultV2Run
from repomap_test_support.w5_pair_fixtures import make_pair_artifacts
from retrieval_evaluation_attempts import admit_attempt
from retrieval_evaluation_grading import ExecutionState
from retrieval_semantic_baseline_result_frames import decode_result_frames
from retrieval_semantic_experiment_contracts import ExperimentCell, ExperimentPlan, canonical_json_bytes
from retrieval_semantic_pair_artifacts import PairReportRefusal, digest_bytes
from retrieval_semantic_pair_report import build_pair_report, read_report, write_report
from repomap_test_support.w5_pair_fixtures import ARMS


_DIGEST = "sha256:" + "a" * 64


def _writer_plan(generation: int, source_digest: str) -> ExperimentPlan:
    return ExperimentPlan(
        attempt_id=f"w5-semantic-g{generation}", generation=generation,
        task_ids=("cal-01",), task_digests=(_DIGEST,), input_identity=_DIGEST,
        representation_report_identity=_DIGEST, publication_identity=_DIGEST,
        artifact_profile_identity=_DIGEST, controller_admission_sha256=_DIGEST,
        source_closure=(("tools/frozen.py", source_digest),),
        fixture_id="writer-public-fixture", freeze_sha256=_DIGEST,
        policy_digest=_DIGEST, arms=ARMS, repetitions=3,
    ).validate()


def _writer_artifacts(root: Path) -> tuple[dict[int, Path], dict[int, Path]]:
    journals: dict[int, Path] = {}
    results: dict[int, Path] = {}
    source = b"public writer fixture\n"
    source_digest = digest_bytes(source)
    result_run = ResultV2Run(enabled=True)
    for generation in (1, 2):
        plan = _writer_plan(generation, source_digest)
        collector = result_run.register(plan)
        assert collector is not None
        journal = admit_attempt(
            root / "attempts",
            {**plan.to_mapping(), "candidate_closure_digests": {"tools/frozen.py": source_digest}},
            {"tools/frozen.py": source},
        )
        for arm_id in ARMS:
            for repetition in range(1, 4):
                identity = {"arm_id": arm_id, "task_id": "cal-01", "repetition": repetition}
                not_run = arm_id == "exact_vector" and repetition == 1
                cell = ExperimentCell(
                    arm_id, "cal-01",
                    ExecutionState.NOT_RUN if not_run else ExecutionState.COMPLETED,
                    reason="fixture_not_run" if not_run else None,
                    candidates=(), elapsed_ns=None if not_run else 1,
                    query_bytes=None if not_run else 1,
                    cleanup_status="not_applicable" if not_run else "verified",
                ).validate()
                journal.append({"event": "query_started", **identity})
                journal.append({"event": "query_observed", **cell.to_dict(), "repetition": repetition})
                collector.add_cell(identity, cell)
        journal.finish(
            "failed",
            {"status": "failed", "generation": generation, "failure_code": "writer_fixture_failed"},
        )
        result_run.finish(journal, status="failed", failure_code="writer_fixture_failed")
        journals[generation] = journal.directory
    stream = io.StringIO()
    saved_stdout = sys.stdout
    try:
        sys.stdout = stream
        result_run.emit()
    finally:
        sys.stdout = saved_stdout
    decoded = decode_result_frames(stream.getvalue().encode("ascii"))
    for generation in (1, 2):
        result_path = root / f"writer-g{generation}-result-v2.json"
        result_path.write_bytes(
            canonical_json_bytes(decoded[f"w5-semantic-g{generation}"].to_mapping()) + b"\n"
        )
        results[generation] = result_path
    return journals, results


def test_paired_report_reads_real_six_member_artifacts(tmp_path: Path) -> None:
    journals: dict[int, Path] = {}
    results: dict[int, Path] = {}
    for generation in (1, 2):
        journal, result = make_pair_artifacts(tmp_path, generation)
        journals[generation] = journal
        results[generation] = result

    report = build_pair_report(journals, results)
    provenance = report["source_provenance"]
    assert isinstance(provenance, dict)
    assert len(provenance["journals"]) == 2
    assert len(provenance["results_v2"]) == 2
    assert report["acceptance"] == {
        "accepted": False,
        "scientific": False,
        "fullW5": False,
        "heldout": False,
        "production": False,
    }
    generations = report["generations"]
    denominators = report["denominators"]
    boundaries = report["measurement_boundaries"]
    assert isinstance(generations, list) and isinstance(denominators, dict) and isinstance(boundaries, dict)
    assert all(item["pair_count"] == 27 for item in generations)
    assert denominators["whole"] == 54
    assert boundaries["ann_correctness"] == "stored exact_reference_recall only; distinct from relevance"
    comparisons = report["comparisons"]
    assert isinstance(comparisons, list)
    assert len(comparisons) == 18
    assert {item["identity"]["generation"] for item in comparisons} == {1, 2}
    assert all(item["comparability"]["quality_comparison"] == "not_emitted" for item in comparisons)


def test_paired_report_reads_actual_journal_and_result_v2_writers(tmp_path: Path) -> None:
    journals, results = _writer_artifacts(tmp_path)
    report = build_pair_report(journals, results)
    generations = report["generations"]
    assert isinstance(generations, list)
    assert [item["terminal_status"] for item in generations] == ["failed", "failed"]
    assert [item["result_v2_status"] for item in generations] == ["failed", "failed"]
    assert all(
        item["denominators"]["reason_categories"].get("not_run") == 1
        for item in generations
    )
    output = tmp_path / "writer-paired-report.json"
    write_report(report, output)
    assert read_report(output) == report

    tampered = json.loads(results[1].read_text())
    tampered["raw_journal"]["report.json"]["sha256"] = "sha256:" + "b" * 64
    results[1].write_bytes(canonical_json_bytes(tampered) + b"\n")
    with pytest.raises(PairReportRefusal, match="pair_result_raw_journal_mismatch"):
        build_pair_report(journals, results)
