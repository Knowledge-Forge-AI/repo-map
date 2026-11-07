"""Unit contracts for the opt-in V2 paired context report."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

import retrieval_semantic_pair_v2_report as pair_v2_module
from repomap_test_support.w5_pair_fixtures import make_pair_artifacts
from retrieval_evaluation_grading import ExecutionState
from retrieval_semantic_observed_operation_capture import make_unadmitted_operation_identity
from retrieval_semantic_pair_artifacts import PairReportRefusal, load_journal
from retrieval_semantic_pair_report import build_pair_report, read_report, write_report
from retrieval_semantic_pair_v2_context import build_context, index_query_observed
from retrieval_semantic_pair_v2_envelope import project_envelope
from retrieval_semantic_pair_v2_rational import rational_projection
from retrieval_semantic_pair_v2_report import (
    PAIR_REPORT_V2_SCHEMA,
    build_pair_report_v2,
    read_pair_report_v2,
    write_pair_report_v2,
)


def _sources(tmp_path: Path) -> tuple[dict[int, Path], dict[int, Path]]:
    journals: dict[int, Path] = {}
    results: dict[int, Path] = {}
    for generation in (1, 2):
        journal, result = make_pair_artifacts(tmp_path, generation)
        journals[generation] = journal
        results[generation] = result
    return journals, results


def test_v2_preserves_v1_population_and_sanitizes_legacy_rows(tmp_path: Path) -> None:
    journals, results = _sources(tmp_path)
    legacy = build_pair_report(journals, results)
    report = build_pair_report_v2(journals, results)

    assert legacy["schema"] == "cloe-w5-semantic-paired-report-v1"
    assert report["schema"] == PAIR_REPORT_V2_SCHEMA
    assert report["base_report_schema"] == legacy["schema"]
    assert report["pair_count"] == legacy["pair_count"] == 54
    assert report["denominators"] == legacy["denominators"]
    report_comparisons = cast(list[object], report["comparisons"])
    legacy_comparisons = cast(list[object], legacy["comparisons"])
    assert len(report_comparisons) == len(legacy_comparisons) == 18
    report_pairs = cast(list[dict[str, object]], report["pairs"])
    vector = next(
        pair
        for pair in report_pairs
        if cast(dict[str, object], pair["identity"])["arm_id"] == "exact_vector"
    )
    vector_context = cast(dict[str, object], vector["context"])
    assert vector["journal_grade"] is None
    assert vector_context["observed_operation"] is None
    assert vector_context["actual_state"] == "unavailable"
    assert "observed_operation_not_recorded" in cast(list[str], vector_context["comparability_gaps"])
    assert "source_relative_path" not in json.dumps(report, sort_keys=True)


def test_operation_context_uses_shared_validator_and_identity() -> None:
    operation = make_unadmitted_operation_identity(
        "cal-01", 2, "exact_vector", 1, ExecutionState.UNAVAILABLE,
        "unsupported_semantic_query_mode",
    )
    pair = {
        "identity": {
            "generation": 2, "task_id": "cal-01", "arm_id": "exact_vector", "repetition": 1,
        },
        "journal_grade": None,
    }
    event = {
        "event": "query_observed",
        "task_id": "cal-01",
        "arm_id": "exact_vector",
        "repetition": 1,
        "execution_state": "unavailable",
        "observed_operation": operation,
    }
    context = build_context(pair, event, 7)
    observed_operation = cast(dict[str, object], context["observed_operation"])
    assert observed_operation["schema"] == "cloe-w5-observed-operation-v1"
    assert context["source"] == {"member": "observations.jsonl", "line": 7}
    assert context["comparability_gaps"] == ["observed_envelope_not_recorded"]

    bad = dict(operation)
    bad_actual = dict(cast(dict[str, object], operation["actual"]))
    bad_actual["sql"] = "private-marker"
    bad["actual"] = bad_actual
    with pytest.raises(PairReportRefusal, match="pair_v2_operation_invalid"):
        build_context(pair, {**event, "observed_operation": bad}, 7)


def test_operation_state_conflict_is_refused() -> None:
    operation = make_unadmitted_operation_identity(
        "cal-01", 1, "hybrid_rrf", 1, ExecutionState.NOT_RUN, "fixture_not_run",
    )
    pair = {
        "identity": {
            "generation": 1, "task_id": "cal-01", "arm_id": "hybrid_rrf", "repetition": 1,
        },
        "journal_grade": None,
    }
    event = {
        "event": "query_observed", "task_id": "cal-01", "arm_id": "hybrid_rrf",
        "repetition": 1, "execution_state": "completed", "observed_operation": operation,
    }
    with pytest.raises(PairReportRefusal, match="pair_v2_operation_state_mismatch"):
        build_context(pair, event, 2)


def test_operation_foreign_identity_is_refused() -> None:
    operation = make_unadmitted_operation_identity(
        "cal-01", 1, "exact_vector", 1, ExecutionState.NOT_RUN, "fixture_not_run",
    )
    pair = {
        "identity": {
            "generation": 1, "task_id": "cal-01", "arm_id": "exact_vector", "repetition": 1,
        },
        "journal_grade": None,
    }
    foreign = dict(operation)
    identity = cast(dict[str, object], operation["identity"])
    foreign["identity"] = {**identity, "arm_id": "hnsw_vector"}
    with pytest.raises(PairReportRefusal, match="pair_v2_operation_invalid"):
        build_context(pair, {"execution_state": "not_run", "observed_operation": foreign}, 4)


def test_v2_round_trip_is_owned_and_structural(tmp_path: Path) -> None:
    journals, results = _sources(tmp_path)
    report = build_pair_report_v2(journals, results)
    output = tmp_path / "paired-v2.json"
    write_pair_report_v2(report, output)
    assert read_pair_report_v2(output) == report
    with pytest.raises(PairReportRefusal, match="pair_v2_output_exists"):
        write_pair_report_v2(report, output)

    payload = json.loads(output.read_text())
    payload["pairs"][0]["context"]["comparability_gaps"] = ["private-marker"]
    output.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    with pytest.raises(PairReportRefusal, match="pair_v2_context_gaps"):
        read_pair_report_v2(output)


def test_v2_old_vector_unknown_does_not_become_zero(tmp_path: Path) -> None:
    journals, results = _sources(tmp_path)
    report = build_pair_report_v2(journals, results)
    report_pairs = cast(list[dict[str, object]], report["pairs"])
    vector = next(
        pair
        for pair in report_pairs
        if cast(dict[str, object], pair["identity"])["arm_id"] == "exact_vector"
    )
    work = cast(dict[str, object], vector["recorded_work"])
    vector_context = cast(dict[str, object], vector["context"])
    observation = cast(dict[str, object], vector["journal_observation"])
    result_work = cast(dict[str, object], work["result_v2"])
    assert vector_context["observed_envelope"] is not None
    assert observation["ann_exact_reference_recall"] is None
    assert result_work["byte_work"] is None
    component_counts = cast(list[dict[str, object]], report["component_counts"])
    assert component_counts[0]["status"] == "not_recorded"
    assert component_counts[0]["values"] is None
    disclosures = cast(dict[str, object], report["disclosures"])
    limitation = cast(dict[str, object], disclosures["generation_2_limitation"])
    component_querycount = cast(dict[str, object], limitation["component_querycount"])
    assert component_querycount["evidence_status"] == "unknown"
    historical = cast(dict[str, object], disclosures["native_cal07_raw_process_stdout_bytes"])
    assert historical["historical_reference"] == 495781
    assert historical["current_observed_values"] == []


def test_context_preserves_surface_selection_and_withholds_raw_prefix() -> None:
    event = {
        "envelope": {
            "scope": {
                "graph_id": "graph-public",
                "backend": "postgresql",
                "selected_binding_ids": ["binding-b", "binding-a"],
                "source_path_prefix": "private/source/root",
            },
            "hits": [
                {"match_surface": "captured_text"},
                {"match_surface": "stored_metadata"},
            ],
        }
    }
    projected = project_envelope(event)
    assert projected is not None
    assert projected["match_surfaces"] == {
        "status": "recorded", "counts": {"captured_text": 1, "stored_metadata": 1},
    }
    scope = cast(dict[str, object], projected["scope"])
    assert scope["selected_binding_count"] == 2
    assert cast(str, scope["selected_binding_ids_sha256"]).startswith("sha256:")
    assert cast(dict[str, object], scope["source_path_prefix"])["status"] == "withheld"
    assert "private/source/root" not in json.dumps(projected)


def test_declared_observed_mode_difference_is_disclosed() -> None:
    pair = {
        "identity": {"generation": 1, "task_id": "cal-01", "arm_id": "native_tools_baseline", "repetition": 1},
        "journal_grade": {
            "requested_mode": "exact_identity", "effective_mode": "exact_identity", "fallback": None,
            "grade_source": "query_observed.slot",
        },
    }
    event = {
        "execution_state": "completed",
        "envelope": {
            "requested_mode": "ranked_discovery", "effective_mode": "ranked_discovery", "hits": [],
        },
    }
    context = build_context(pair, event, 3)
    assert cast(dict[str, object], context["declared_intent"])["source"] == "query_observed.slot"
    assert context["intent_comparison"] == {
        "status": "different", "differences": ["effective_mode", "requested_mode"],
    }


def test_duplicate_observation_identity_is_refused(tmp_path: Path) -> None:
    journals, _results = _sources(tmp_path)
    journal = load_journal(journals[1])
    duplicate = journal.observations[1]
    replacement = replace(journal, observations=journal.observations + (duplicate,))
    with pytest.raises(PairReportRefusal, match="pair_v2_duplicate_query_observed"):
        index_query_observed(replacement)


def test_v2_reader_rejects_malformed_grade_and_component_trust(tmp_path: Path) -> None:
    journals, results = _sources(tmp_path)
    report = build_pair_report_v2(journals, results)
    output = tmp_path / "malformed-v2.json"
    write_pair_report_v2(report, output)
    raw = json.loads(output.read_text())
    graded = next(pair for pair in raw["pairs"] if pair["journal_grade"] is not None)
    graded["journal_grade"]["safety_refusal_correct"] = "false"
    output.write_bytes(json.dumps(raw, sort_keys=True, separators=(",", ":")).encode() + b"\n")
    with pytest.raises(PairReportRefusal, match="pair_v2_grade_safety"):
        read_pair_report_v2(output)
    raw["pairs"] = json.loads(json.dumps(report["pairs"], sort_keys=True))
    raw["component_counts"][0]["independently_revalidated"] = True
    output.write_bytes(json.dumps(raw, sort_keys=True, separators=(",", ":")).encode() + b"\n")
    with pytest.raises(PairReportRefusal, match="pair_v2_component_counts"):
        read_pair_report_v2(output)
    raw = json.loads(json.dumps(report, sort_keys=True))
    raw["source_provenance"]["journals"][0]["member_digests"]["report.json"] = "sha256:" + "b" * 64
    output.write_bytes(json.dumps(raw, sort_keys=True, separators=(",", ":")).encode() + b"\n")
    with pytest.raises(PairReportRefusal, match="pair_v2_provenance"):
        read_pair_report_v2(output)
    raw = json.loads(json.dumps(report, sort_keys=True))
    raw["source_provenance"]["results_v2"][0]["sha256"] = "sha256:" + "b" * 64
    output.write_bytes(json.dumps(raw, sort_keys=True, separators=(",", ":")).encode() + b"\n")
    with pytest.raises(PairReportRefusal, match="pair_v2_provenance"):
        read_pair_report_v2(output)


def test_v1_round_trip_remains_separate_from_v2(tmp_path: Path) -> None:
    journals, results = _sources(tmp_path)
    legacy = build_pair_report(journals, results)
    output = tmp_path / "legacy.json"
    write_report(legacy, output)
    assert read_report(output) == legacy


def test_v2_output_rejects_symlink_destination(tmp_path: Path) -> None:
    journals, results = _sources(tmp_path)
    report = build_pair_report_v2(journals, results)
    target = tmp_path / "target.json"
    target.write_text("owned\n")
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(PairReportRefusal, match="pair_v2_output_path"):
        write_pair_report_v2(report, link)


def test_v2_output_bound_is_enforced_without_large_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    journals, results = _sources(tmp_path)
    report = build_pair_report_v2(journals, results)
    monkeypatch.setattr(pair_v2_module, "MAX_PAIR_REPORT_V2_BYTES", 1)
    with pytest.raises(PairReportRefusal, match="pair_v2_output_size"):
        write_pair_report_v2(report, tmp_path / "too-large.json")


def test_rational_projection_rejects_wrong_container_and_zero_denominator() -> None:
    with pytest.raises(PairReportRefusal, match="pair_v2_rational"):
        rational_projection({"measurement": {}})
    with pytest.raises(PairReportRefusal, match="pair_v2_rational_measurement"):
        rational_projection([{
            "cell_identity": {"task_id": "cal-01", "arm_id": "hybrid_rrf", "repetition": 1},
            "source": "journal",
            "measurement": {"numerator": 1, "denominator": 0},
        }])


def test_result_generation_mismatch_is_refused(tmp_path: Path) -> None:
    journals, results = _sources(tmp_path)
    result = json.loads(results[2].read_text())
    result["generation"] = 1
    results[2].write_bytes(json.dumps(result, sort_keys=True, separators=(",", ":")).encode() + b"\n")
    with pytest.raises(
        PairReportRefusal,
        match="pair_result_v2_invalid|pair_result_attempt_mismatch|pair_result_plan_identity",
    ):
        build_pair_report_v2(journals, results)


@pytest.mark.parametrize("value", [True, -1, "cloe-w5-byte-accounting-v1"])
def test_v2_reader_rejects_non_count_byte_fields(tmp_path: Path, value: object) -> None:
    journals, results = _sources(tmp_path)
    report = build_pair_report_v2(journals, results)
    raw = json.loads(json.dumps(report, sort_keys=True))
    raw["pairs"][0]["recorded_work"]["result_v2"]["byte_work"] = {
        "schema_version": "cloe-w5-byte-accounting-v1",
        "decoded_candidate_count": value,
    }
    output = tmp_path / "invalid-byte-count.json"
    output.write_bytes(json.dumps(raw, sort_keys=True, separators=(",", ":")).encode() + b"\n")
    with pytest.raises(PairReportRefusal, match="pair_v2_byte_work"):
        read_pair_report_v2(output)


@pytest.mark.parametrize("target", ["journal_grade", "journal_observation", "result_v2"])
def test_v2_reader_refuses_nested_unknown_fields(tmp_path: Path, target: str) -> None:
    journals, results = _sources(tmp_path)
    raw = json.loads(json.dumps(build_pair_report_v2(journals, results)))
    pair = next(pair for pair in raw["pairs"] if pair.get(target) is not None)
    pair[target]["private_payload"] = "private-marker"
    output = tmp_path / "unknown-field.json"
    output.write_bytes(json.dumps(raw, sort_keys=True, separators=(",", ":")).encode() + b"\n")
    with pytest.raises(PairReportRefusal, match="pair_v2_.*fields"):
        read_pair_report_v2(output)


def test_v2_reader_reconciles_denominators_with_cells(tmp_path: Path) -> None:
    journals, results = _sources(tmp_path)
    raw = json.loads(json.dumps(build_pair_report_v2(journals, results)))
    raw["denominators"]["supported"] = raw["denominators"]["whole"]
    raw["denominators"]["graded"] = 0
    raw["denominators"]["eligible"] = 0
    output = tmp_path / "forged-denominators.json"
    output.write_bytes(json.dumps(raw, sort_keys=True, separators=(",", ":")).encode() + b"\n")
    with pytest.raises(PairReportRefusal, match="pair_v2_denominators"):
        read_pair_report_v2(output)


@pytest.mark.parametrize("target", ["generation", "legacy_report", "scope_complete"])
def test_v2_reader_closes_generation_and_envelope_shapes(tmp_path: Path, target: str) -> None:
    journals, results = _sources(tmp_path)
    raw = json.loads(json.dumps(build_pair_report_v2(journals, results)))
    if target == "generation":
        raw["generations"][0]["private_payload"] = "private-marker"
    elif target == "legacy_report":
        raw["generations"][0]["legacy_report"]["private_payload"] = "private-marker"
    else:
        pair = next(pair for pair in raw["pairs"] if pair["context"]["observed_envelope"] is not None)
        pair["context"]["observed_envelope"]["scope_complete"] = 1
    output = tmp_path / "invalid-nested-shape.json"
    output.write_bytes(json.dumps(raw, sort_keys=True, separators=(",", ":")).encode() + b"\n")
    with pytest.raises(PairReportRefusal, match="pair_v2_generation_fields|pair_v2_scope_complete"):
        read_pair_report_v2(output)


@pytest.mark.parametrize("kind", ["counts", "count_source", "negative_elapsed", "fractional_elapsed", "candidate_unknown", "comparison_grade", "comparison_scope"])
def test_v2_reader_refuses_inconsistent_work_witnesses(tmp_path: Path, kind: str) -> None:
    journals, results = _sources(tmp_path)
    raw = json.loads(json.dumps(build_pair_report_v2(journals, results)))
    if kind in {"counts", "count_source"}:
        counts = raw["generations"][0]["recorded_work"]["component_counts"]
        target = counts if kind == "counts" else counts["source"]
        target["private_payload"] = "private-marker"
    elif kind in {"negative_elapsed", "fractional_elapsed"}:
        pair = next(pair for pair in raw["pairs"] if pair["journal_observation"] is not None)
        pair["journal_observation"]["elapsed_ns"] = -1 if kind == "negative_elapsed" else 1.5
    elif kind == "candidate_unknown":
        pair = next(pair for pair in raw["pairs"] if pair["result_v2"]["cell"] is not None)
        pair["result_v2"]["cell"]["candidate_count"] = None
    elif kind == "comparison_grade":
        grading = raw["comparisons"][0]["left"]["grading"]
        grading["state"] = "partial" if grading["state"] == "correct" else "correct"
    else:
        side = raw["comparisons"][0]["left"]
        side["scope_complete"] = not side["scope_complete"]
    output = tmp_path / "inconsistent-work.json"
    output.write_bytes(json.dumps(raw, sort_keys=True, separators=(",", ":")).encode() + b"\n")
    with pytest.raises(PairReportRefusal):
        read_pair_report_v2(output)
