"""Filesystem integration for real journal and ResultV2 writers feeding V2."""

from __future__ import annotations

import io
import json
from pathlib import Path
import sys
from typing import cast

import pytest

from repomap_test_support.w5_experiment_journal import record_cell
from repomap_test_support.w5_experiment_results import ResultV2Run
from repomap_test_support.w5_pair_fixtures import ARMS
from retrieval_evaluation_attempts import admit_attempt
from retrieval_evaluation_grading import ExecutionState
from retrieval_semantic_baseline_result_frames import decode_result_frames
from retrieval_semantic_experiment_contracts import (
    ExperimentCell, ExperimentPlan, canonical_json_bytes, digest_json,
)
from retrieval_semantic_observed_operation import OBSERVED_OPERATION_SCHEMA, finalize_observed_operation
from retrieval_semantic_observed_operation_capture import make_unadmitted_operation_identity
from retrieval_semantic_pair_artifacts import digest_bytes
from retrieval_semantic_pair_v2_report import build_pair_report_v2, read_pair_report_v2, write_pair_report_v2


_DIGEST = "sha256:" + "a" * 64
_COMPONENT_DIGESTS = {
    "admission": _DIGEST,
    "declaration": _DIGEST,
    "report": _DIGEST,
    "request": _DIGEST,
    "source_manifest": _DIGEST,
    "sources_archive": _DIGEST,
    "terminal": _DIGEST,
}


def _plan(generation: int) -> ExperimentPlan:
    return ExperimentPlan(
        attempt_id=f"w5-semantic-g{generation}", generation=generation,
        task_ids=("cal-01",), task_digests=(_DIGEST,), input_identity=_DIGEST,
        representation_report_identity=_DIGEST, publication_identity=_DIGEST,
        artifact_profile_identity=_DIGEST, controller_admission_sha256=_DIGEST,
        source_closure=(("tools/frozen.py", _DIGEST),), fixture_id="writer-public",
        freeze_sha256=_DIGEST, policy_digest=_DIGEST, arms=ARMS, repetitions=3,
    ).validate()


def _component_report(generation: int) -> dict[str, object]:
    query_count = 4 if generation == 1 else 0
    record_count = 80 + query_count
    return {
        "component": dict(_COMPONENT_DIGESTS),
        "component_counts": {
            "document_count": 80, "query_count": query_count,
            "record_count": record_count, "embedding_count": record_count,
        },
        "component_response_cost": {"input_records": record_count},
    }


def _hnsw_operation(
    generation: int, repetition: int, state: str, reason: str, *, raw_result: bool,
) -> dict[str, object]:
    plan = {
        "node_types": ["Limit", "Index Scan"], "index_names": ["public_hnsw"],
        "actual_rows": 1, "planning_time_ms": 0.1, "execution_time_ms": 0.2,
        "shared_hit_blocks": 1, "shared_read_blocks": 0,
        "used_expected_index": True, "used_seq_scan": False,
        "distance_order_present": True, "planner_forced": False,
    }
    provenance = {
        "repository_identity": "repo:public", "run_id": 1,
        "receipt_identity": _DIGEST, "profile_identity": _DIGEST,
        "rebuild_id": "rebuild-public", "index_name": "public_hnsw",
        "query_digest": _DIGEST, "attempt_identity": f"w5-semantic-g{generation}",
        "source_scope": [["bind1", "snapshot-public"]], "dimensions": 384,
        "ef_search": 40, "iterative_scan": "off", "ann_scan_limit": 20,
        "baseline_sql_digest": _DIGEST, "privacy_class": "public",
        "search": "hnsw-public", "input_digest_validation": "verified",
    }
    item = {
        "source_binding_id": "bind1", "plan": plan if raw_result else None,
        "plan_sha256": digest_json(plan) if raw_result else None,
        "provenance": provenance if raw_result else None,
        "recall": {
            "exact_count": 1, "ann_count": 1, "overlap_at_k": 1,
            "recall_at_k": 1.0, "truncated": False,
        } if raw_result else None,
        "receipt_sha256": _DIGEST,
        "creation_state": "completed" if raw_result else "failed" if state == "failed" else "not_attempted",
        "creation_error": None if raw_result or state != "failed" else "hnsw_index_creation_failed",
        "explain_executed": True if raw_result else None,
        "cleanup_state": "failed" if raw_result else "not_attempted",
        "cell_state": state, "cell_reason": reason,
        "result_state": "completed" if raw_result else None, "result_reason": None,
    }
    return finalize_observed_operation({
        "schema": OBSERVED_OPERATION_SCHEMA,
        "identity": {
            "generation": generation, "task_id": "cal-01",
            "arm_id": "hnsw_vector", "repetition": repetition,
        },
        "kind": "hnsw_vector", "state": state, "reason": reason,
        "declared_mode": None,
        "actual": {
            "operation": "hnsw_vector_sql", "backend": "postgresql",
            "publication_identity": _DIGEST, "profile_identity": _DIGEST,
            "rebuild_id": "rebuild-public",
            "input_descriptor_sha256": _DIGEST if raw_result else None,
            "selected_binding_ids": ["bind1"], "snapshot_manifest_id": "snapshot-public",
            "effective_mode": None, "match_surface": None, "fallback": None,
        },
        "work": {"per_binding": [], "hnsw": [item], "fusion": None, "reference": None},
    })


def _writer_artifacts(
    root: Path, *, hnsw_case: str | None = None,
) -> tuple[dict[int, Path], dict[int, Path]]:
    journals: dict[int, Path] = {}
    result_run = ResultV2Run(enabled=True)
    source = b"writer-public\n"
    for generation in (1, 2):
        plan = _plan(generation)
        collector = result_run.register(plan)
        assert collector is not None
        journal = admit_attempt(
            root / "attempts",
            {**plan.to_mapping(), "candidate_closure_digests": {"tools/frozen.py": digest_bytes(source)}},
            {"tools/frozen.py": source},
        )
        sink = result_run.cell_sink(collector)
        for arm_id in ARMS:
            for repetition in range(1, 4):
                identity = {"task_id": "cal-01", "arm_id": arm_id, "repetition": repetition}
                journal.append({"event": "query_started", **identity})
                failure_case = (
                    hnsw_case
                    if generation == 1 and arm_id == "hnsw_vector" and repetition == 1
                    else None
                )
                not_run = arm_id == "exact_vector" and repetition == 1
                if failure_case == "creation_failure":
                    execution_state, cell_reason, cleanup_status = (
                        ExecutionState.FAILED, "hnsw_index_creation_failed", "not_applicable"
                    )
                elif failure_case == "query_refused":
                    execution_state, cell_reason, cleanup_status = (
                        ExecutionState.REFUSED, "query_not_admitted", "not_applicable"
                    )
                elif failure_case == "cleanup_failure":
                    execution_state, cell_reason, cleanup_status = (
                        ExecutionState.FAILED, "cleanup_failed", "failed"
                    )
                elif not_run:
                    execution_state, cell_reason, cleanup_status = (
                        ExecutionState.NOT_RUN, "fixture_not_run", "not_applicable"
                    )
                else:
                    execution_state, cell_reason, cleanup_status = (
                        ExecutionState.COMPLETED, None, "verified"
                    )
                cell = ExperimentCell(
                    arm_id, "cal-01",
                    execution_state, reason=cell_reason, candidates=(),
                    elapsed_ns=None if execution_state is not ExecutionState.COMPLETED else 1,
                    query_bytes=None if execution_state is not ExecutionState.COMPLETED else 1,
                    cleanup_status=cleanup_status,
                ).validate()
                operation = (
                    _hnsw_operation(
                        generation, repetition, execution_state.value, cast(str, cell_reason),
                        raw_result=failure_case == "cleanup_failure",
                    )
                    if failure_case is not None else make_unadmitted_operation_identity(
                        "cal-01", generation, arm_id, repetition,
                        ExecutionState.NOT_RUN, "fixture_not_run",
                    )
                    if not_run else None
                )
                record_cell(
                    journal, cell, repetition, generation=generation,
                    observed_operation=operation, result_cell_sink=sink,
                )
        journal.finish(
            "failed",
            {
                **_component_report(generation),
                "status": "failed", "failure_code": "writer_fixture_failed",
            },
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
    results: dict[int, Path] = {}
    for generation in (1, 2):
        path = root / f"writer-g{generation}-result-v2.json"
        path.write_bytes(canonical_json_bytes(decoded[f"w5-semantic-g{generation}"].to_mapping()) + b"\n")
        results[generation] = path
    return journals, results


def test_v2_reads_actual_journal_and_result_v2_writers(tmp_path: Path) -> None:
    journals, results = _writer_artifacts(tmp_path)
    report = build_pair_report_v2(journals, results)
    assert report["pair_count"] == 54
    assert len(cast(list[object], report["comparisons"])) == 18
    for generation in cast(list[dict[str, object]], report["generations"]):
        assert cast(dict[str, object], generation["legacy_report"])["status"] == "failed"
        work = cast(dict[str, object], generation["recorded_work"])
        counts = cast(dict[str, object], work["component_counts"])
        assert counts["status"] == "recorded"
        assert cast(dict[str, object], counts["source"])["component_digests"] == _COMPONENT_DIGESTS
    operation_pair = next(
        pair for pair in cast(list[dict[str, object]], report["pairs"])
        if cast(dict[str, object], pair["identity"])["generation"] == 1
        and cast(dict[str, object], pair["identity"])["arm_id"] == "exact_vector"
        and cast(dict[str, object], pair["identity"])["repetition"] == 1
    )
    context = cast(dict[str, object], operation_pair["context"])
    operation = cast(dict[str, object], context["observed_operation"])
    assert operation["schema"] == "cloe-w5-observed-operation-v1"
    assert context["actual_state"] == "not_run"
    assert operation_pair["classification"] == "unsupported"
    assert context["comparability_gaps"] == ["observed_envelope_not_recorded"]
    assert context["observed_operation_status"] == "recorded"
    disclosures = cast(dict[str, object], report["disclosures"])
    limitation = cast(dict[str, object], disclosures["generation_2_limitation"])
    document_only = cast(dict[str, object], limitation["document_only"])
    assert document_only == {"value": True, "evidence_status": "recorded_sealed_response"}
    component_querycount = cast(dict[str, object], limitation["component_querycount"])
    assert component_querycount == {"value": 0, "evidence_status": "recorded_sealed_response"}
    component_counts = cast(list[dict[str, object]], report["component_counts"])
    assert cast(dict[str, object], component_counts[0]["values"]) == {
        "document_count": 80, "embedding_count": 84, "query_count": 4, "record_count": 84,
    }
    assert cast(dict[str, object], component_counts[1]["values"]) == {
        "document_count": 80, "embedding_count": 80, "query_count": 0, "record_count": 80,
    }
    output = tmp_path / "writer-v2.json"
    write_pair_report_v2(report, output)
    assert read_pair_report_v2(output) == report
    raw = json.loads(output.read_text())
    tampered_pair = next(
        item for item in raw["pairs"]
        if item["identity"]["generation"] == 1
        and item["identity"]["arm_id"] == "exact_vector"
        and item["identity"]["repetition"] == 1
    )
    tampered_pair["context"]["actual_state"] = "failed"
    output.write_bytes(canonical_json_bytes(raw) + b"\n")
    try:
        read_pair_report_v2(output)
    except ValueError as error:
        assert "pair_v2_operation_state_mismatch" in str(error)
    else:
        raise AssertionError("tampered operation state was accepted")


def test_v2_rejects_reordered_declared_result_plan(tmp_path: Path) -> None:
    journals, results = _writer_artifacts(tmp_path)
    raw = json.loads(results[2].read_text())
    raw["plan"]["arms"] = list(reversed(raw["plan"]["arms"]))
    results[2].write_bytes(canonical_json_bytes(raw) + b"\n")
    with pytest.raises(ValueError, match="pair_result_plan_population|pair_result_plan_identity"):
        build_pair_report_v2(journals, results)


@pytest.mark.parametrize("hnsw_case", ["creation_failure", "query_refused", "cleanup_failure"])
def test_v2_reads_hnsw_failure_result_shapes(tmp_path: Path, hnsw_case: str) -> None:
    journals, results = _writer_artifacts(tmp_path, hnsw_case=hnsw_case)
    report = build_pair_report_v2(journals, results)
    pair = next(
        pair for pair in cast(list[dict[str, object]], report["pairs"])
        if cast(dict[str, object], pair["identity"])["generation"] == 1
        and cast(dict[str, object], pair["identity"])["arm_id"] == "hnsw_vector"
        and cast(dict[str, object], pair["identity"])["repetition"] == 1
    )
    context = cast(dict[str, object], pair["context"])
    operation = cast(dict[str, object], context["observed_operation"])
    work = cast(dict[str, object], operation["work"])
    item = cast(dict[str, object], cast(list[object], work["hnsw"])[0])
    if hnsw_case == "cleanup_failure":
        assert item["cell_state"] == "failed"
        assert item["cleanup_state"] == "failed"
        assert item["result_state"] == "completed"
    else:
        assert item["result_state"] is None
    output = tmp_path / f"hnsw-{hnsw_case}.json"
    write_pair_report_v2(report, output)
    assert read_pair_report_v2(output) == report
