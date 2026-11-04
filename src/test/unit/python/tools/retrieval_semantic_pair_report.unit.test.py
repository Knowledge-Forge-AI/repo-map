"""Pure paired-report contracts over public-safe filesystem samples."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from repomap_test_support.w5_pair_fixtures import make_pair_artifacts
from retrieval_semantic_pair_artifacts import (
    MAX_RESULT_BYTES,
    MAX_RESULT_INPUT_BYTES,
    PairReportRefusal,
    digest_bytes,
    parse_json_object,
)
from retrieval_semantic_pair_report import (
    MAX_REPORT_BYTES,
    _validate_report_output_size,
    build_pair_report,
    read_report,
    write_report,
)
from retrieval_semantic_pair_report_support import (
    validate_result_frame_budget,
    validate_result_input_lengths,
)
from retrieval_semantic_pair_metrics import _classify, _denominators
from retrieval_semantic_pair_rational import rational_records


def _sources(tmp_path: Path) -> tuple[dict[int, Path], dict[int, Path]]:
    journals: dict[int, Path] = {}
    results: dict[int, Path] = {}
    for generation in (1, 2):
        journal, result = make_pair_artifacts(tmp_path, generation)
        journals[generation] = journal
        results[generation] = result
    return journals, results


def _refresh_journal_binding(journal: Path, result: Path, observations: bytes) -> None:
    observations_path = journal / "observations.jsonl"
    observations_path.write_bytes(observations)

    terminal_path = journal / "terminal.json"
    terminal = json.loads(terminal_path.read_text())
    terminal["journal_sha256"] = digest_bytes(observations)
    terminal["observation_count"] = len(observations.splitlines())
    terminal_raw = json.dumps(terminal, sort_keys=True, separators=(",", ":")).encode("ascii") + b"\n"
    terminal_path.write_bytes(terminal_raw)

    result_mapping = json.loads(result.read_text())
    for member in ("observations.jsonl", "terminal.json"):
        member_raw = (journal / member).read_bytes()
        result_mapping["raw_journal"][member] = {
            "length": len(member_raw), "sha256": digest_bytes(member_raw),
        }
    result.write_text(json.dumps(result_mapping, separators=(",", ":")))


def _duplicate_journal_event(journal: Path, result: Path, event_name: str) -> None:
    observations = (journal / "observations.jsonl").read_bytes()
    line = next(
        line for line in observations.splitlines(keepends=True)
        if f'"event":"{event_name}"'.encode("ascii") in line
    )
    _refresh_journal_binding(journal, result, observations + line)


def _tamper_grade_metric(journal: Path, result: Path) -> None:
    observations = (journal / "observations.jsonl").read_bytes()
    lines = observations.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if b'"event":"task_graded"' in line:
            event = json.loads(line)
            event["slot"]["metrics"]["recall@5"] = True
            lines[index] = json.dumps(event, sort_keys=True, separators=(",", ":")).encode("ascii") + b"\n"
            break
    else:
        raise AssertionError("fixture has no task grade")
    _refresh_journal_binding(journal, result, b"".join(lines))


def _add_divergent_grade(journal: Path, result: Path) -> None:
    observations = (journal / "observations.jsonl").read_bytes()
    lines = observations.splitlines(keepends=True)
    for line in lines:
        if b'"event":"query_observed"' not in line or b'"arm_id":"hnsw_vector"' not in line:
            continue
        observed = json.loads(line)
        grade = {
            "event": "task_graded",
            "arm_id": observed["arm_id"],
            "task_id": observed["task_id"],
            "repetition": observed["repetition"],
            "slot": observed["slot"],
        }
        grade["slot"] = dict(grade["slot"])
        grade["slot"]["metrics"] = {"recall@5": 0.0, "mrr@5": 1.0, "ndcg@5": 1.0}
        _refresh_journal_binding(journal, result, observations + _json_line(grade))
        return
    raise AssertionError("fixture has no hnsw query grade")


def _json_line(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii") + b"\n"


def test_pairing_uses_recorded_identity_and_keeps_missing_grade_explicit(tmp_path: Path) -> None:
    journals, results = _sources(tmp_path)
    report = build_pair_report(journals, results)

    assert report["pair_count"] == 54
    generations = report["generations"]
    assert isinstance(generations, list)
    assert [item["denominators"]["whole"] for item in generations] == [27, 27]
    assert [item["denominators"]["supported"] for item in generations] == [24, 24]
    pairs = report["pairs"]
    assert isinstance(pairs, list)
    unsupported = [pair for pair in pairs if pair["classification"] == "unsupported"]
    assert len(unsupported) == 6
    vector = next(pair for pair in pairs if pair["identity"]["arm_id"] == "exact_vector")
    assert vector["journal_grade"] is None
    hnsw = next(pair for pair in pairs if pair["identity"]["arm_id"] == "hnsw_vector")
    assert hnsw["journal_grade"]["grading_state"] == "correct"
    assert hnsw["journal_grade"]["metrics"]["recall@5"] == 1.0
    assert hnsw["file_grading_policy_version"] == "cloe-w5-file-grading-v2"
    assert hnsw["file_grading_policy_version_source"] == "query_observed.slot"
    assert hnsw["journal_observation"]["ann_exact_reference_recall"] == 0.75
    native = next(pair for pair in pairs if pair["identity"]["arm_id"] == "native_tools_baseline")
    assert native["file_grading_policy_version"] == "cloe-w5-file-grading-v2"
    sqlite_safety = next(
        pair for pair in pairs
        if pair["identity"]["generation"] == 1
        and pair["identity"]["arm_id"] == "current_graph_baseline:sqlite"
    )
    assert sqlite_safety["classification"] == "safety_incorrect"
    assert sqlite_safety["journal_grade"]["safety_refusal_correct"] is False
    assert sqlite_safety["journal_grade"]["metrics"]["recall@5"] == 0.0
    assert sqlite_safety["journal_grade"]["quality_credit"] == "not_applicable"
    postgres_safety = next(
        pair for pair in pairs
        if pair["identity"]["generation"] == 1
        and pair["identity"]["arm_id"] == "current_graph_baseline:postgresql"
    )
    assert postgres_safety["classification"] == "safety_not_recorded"
    assert postgres_safety["journal_grade"]["safety_refusal_correct"] is None
    assert [item["denominators"]["graded"] for item in generations] == [6, 6]
    assert [item["denominators"]["eligible"] for item in generations] == [6, 6]
    assert all(item["result_v2_status"] == "failed" for item in generations)
    assert all(item["result_v2_failure_code"] == "fixture_failed" for item in generations)
    disclosures = report["disclosures"]
    assert isinstance(disclosures, dict)
    generation_2 = disclosures["generation_2_limitation"]
    assert generation_2["component_querycount"] == {
        "value": None, "evidence_status": "not_recorded",
    }
    assert generation_2["recorded_unavailable_observations"] == 3
    assert generation_2["whole_denominator"] == 27
    hybrid = next(
        pair for pair in pairs
        if pair["identity"]["arm_id"] == "hybrid_rrf" and pair["identity"]["repetition"] == 1
    )
    assert hybrid["rational_fusion"]
    assert hybrid["rational_fusion"][0]["cell_identity"]["arm_id"] == "hybrid_rrf"
    assert hybrid["rational_fusion"][0]["measurement"]["kind"] == "score"
    comparisons = report["comparisons"]
    assert isinstance(comparisons, list)
    assert len(comparisons) == 18
    assert {item["family"] for item in comparisons} == {
        "postgres_native_fts:postgresql_vs_exact_vector",
        "postgres_native_fts:postgresql_vs_hybrid_rrf",
        "exact_vector_vs_hnsw_vector",
    }
    ann_comparison = next(item for item in comparisons if item["family"] == "exact_vector_vs_hnsw_vector")
    assert ann_comparison["right"]["ann_exact_reference_recall"] == 0.75
    assert ann_comparison["right"]["metrics"]["recall@5"] == 1.0
    assert ann_comparison["comparability"]["status"] == "gap"
    assert "byte_work_not_recorded" in ann_comparison["comparability"]["reasons"]
    assert "correspondence_not_recorded" in ann_comparison["comparability"]["reasons"]
    assert ann_comparison["right"]["rational_fusion"]["status"] == "not_recorded"
    hybrid_comparison = next(
        item for item in comparisons
        if item["family"] == "postgres_native_fts:postgresql_vs_hybrid_rrf"
        and item["identity"]["repetition"] == 1
    )
    assert hybrid_comparison["left"]["rational_fusion"]["status"] == "not_recorded"
    assert hybrid_comparison["right"]["rational_fusion"]["status"] == "present"
    assert all(item["comparability"]["quality_comparison"] == "not_emitted" for item in comparisons)
    assert all("delta" not in item and "winner" not in item for item in comparisons)


def test_report_output_is_owned_and_round_trips(tmp_path: Path) -> None:
    journals, results = _sources(tmp_path)
    report = build_pair_report(journals, results)
    output = tmp_path / "paired-report.json"
    write_report(report, output)
    assert read_report(output) == report
    with pytest.raises(PairReportRefusal, match="pair_output_exists"):
        write_report(report, output)


def test_tampered_result_raw_journal_digest_is_refused(tmp_path: Path) -> None:
    journals, results = _sources(tmp_path)
    raw = json.loads(results[1].read_text())
    raw["raw_journal"]["report.json"]["sha256"] = "sha256:" + "b" * 64
    results[1].write_text(json.dumps(raw, separators=(",", ":")))
    with pytest.raises(PairReportRefusal, match="pair_result_raw_journal_mismatch"):
        build_pair_report(journals, results)


def test_tampered_terminal_member_digest_is_refused(tmp_path: Path) -> None:
    journals, results = _sources(tmp_path)
    terminal_path = journals[1] / "terminal.json"
    terminal = json.loads(terminal_path.read_text())
    terminal["report_sha256"] = "sha256:" + "b" * 64
    terminal_path.write_text(json.dumps(terminal, separators=(",", ":")))
    with pytest.raises(PairReportRefusal, match="pair_terminal_digest_mismatch"):
        build_pair_report(journals, results)


def test_tampered_source_manifest_archive_digest_is_refused(tmp_path: Path) -> None:
    journals, results = _sources(tmp_path)
    manifest_path = journals[1] / "source-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["archive_sha256"] = "sha256:" + "b" * 64
    manifest_raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("ascii") + b"\n"
    manifest_path.write_bytes(manifest_raw)
    terminal_path = journals[1] / "terminal.json"
    terminal = json.loads(terminal_path.read_text())
    terminal["source_manifest_sha256"] = digest_bytes(manifest_raw)
    terminal_path.write_bytes(
        json.dumps(terminal, sort_keys=True, separators=(",", ":")).encode("ascii") + b"\n"
    )
    with pytest.raises(PairReportRefusal, match="pair_source_archive_mismatch"):
        build_pair_report(journals, results)


def test_result_attempt_generation_mismatch_is_refused(tmp_path: Path) -> None:
    journals, results = _sources(tmp_path)
    raw = json.loads(results[1].read_text())
    raw["attempt_id"] = "w5-semantic-g2"
    raw["generation"] = 2
    raw["plan"]["attempt_id"] = "w5-semantic-g2"
    raw["plan"]["generation"] = 2
    results[1].write_text(json.dumps(raw, separators=(",", ":")))
    with pytest.raises(PairReportRefusal, match="pair_result_attempt_mismatch"):
        build_pair_report(journals, results)


def test_reordered_result_plan_population_is_refused(tmp_path: Path) -> None:
    journals, results = _sources(tmp_path)
    raw = json.loads(results[1].read_text())
    raw["plan"]["arms"] = list(reversed(raw["plan"]["arms"]))
    results[1].write_text(json.dumps(raw, sort_keys=True, separators=(",", ":")))
    with pytest.raises(PairReportRefusal, match="pair_result_plan_population"):
        build_pair_report(journals, results)


def test_dual_grade_slot_divergence_is_refused(tmp_path: Path) -> None:
    journals, results = _sources(tmp_path)
    _add_divergent_grade(journals[1], results[1])
    with pytest.raises(PairReportRefusal, match="pair_dual_grade_mismatch"):
        build_pair_report(journals, results)


def test_safety_refusal_classification_preserves_true_false_and_null() -> None:
    cell = {"cell": {"execution_state": "refused"}}
    observed = {"execution_state": "refused"}
    for safety, expected in ((True, "safety_correct"), (False, "safety_incorrect"), (None, "safety_not_recorded")):
        grade = {"grading_rule": "safety_refusal", "safety_refusal_correct": safety}
        assert _classify(cell, observed, grade) == expected


def test_not_run_is_explicit_reason_without_changing_classification() -> None:
    cell = {"cell": {"execution_state": "not_run"}}
    classification = _classify(cell, {"execution_state": "not_run"}, None)
    summary = _denominators(({
        "classification": classification, "result_v2": cell, "journal_grade": None,
    },))
    assert classification == "unsupported"
    assert summary["whole"] == 1
    assert summary["supported"] == 0
    assert summary["reason_categories"] == {"not_run": 1}


def test_rational_traversal_is_bounded() -> None:
    nested: object = 1
    for _ in range(300):
        nested = [nested]
    with pytest.raises(PairReportRefusal, match="pair_rational_depth"):
        rational_records(nested)


def test_deep_json_is_refused_with_public_code() -> None:
    raw = b'{"x":' * 300 + b"null" + b"}" * 300
    with pytest.raises(PairReportRefusal, match="pair_json_depth"):
        parse_json_object(raw, code_prefix="pair_deep")


@pytest.mark.parametrize("event_name", ["query_observed", "task_graded"])
def test_duplicate_journal_observation_or_grade_is_refused(tmp_path: Path, event_name: str) -> None:
    journals, results = _sources(tmp_path)
    _duplicate_journal_event(journals[1], results[1], event_name)
    with pytest.raises(PairReportRefusal, match="pair_duplicate_journal_identity"):
        build_pair_report(journals, results)


def test_duplicate_result_identity_is_refused(tmp_path: Path) -> None:
    journals, results = _sources(tmp_path)
    raw = json.loads(results[1].read_text())
    raw["cells"].append(raw["cells"][0])
    results[1].write_text(json.dumps(raw, separators=(",", ":")))
    with pytest.raises(PairReportRefusal, match="pair_result_v2_invalid"):
        build_pair_report(journals, results)


def test_oversized_result_v2_file_is_refused_without_loading_it(tmp_path: Path) -> None:
    journals, results = _sources(tmp_path)
    with results[1].open("r+b") as stream:
        stream.truncate(MAX_RESULT_BYTES + 1)
    with pytest.raises(PairReportRefusal, match="pair_result_v2_size"):
        build_pair_report(journals, results)


def test_oversized_result_v2_aggregate_budget_is_refused() -> None:
    with pytest.raises(PairReportRefusal, match="pair_result_v2_input_size"):
        validate_result_frame_budget((MAX_RESULT_INPUT_BYTES, 1))


def test_oversized_result_v2_individual_budget_is_refused() -> None:
    with pytest.raises(PairReportRefusal, match="pair_result_v2_size"):
        validate_result_input_lengths((MAX_RESULT_BYTES + 1,))


def test_json_numeric_overflow_is_refused() -> None:
    with pytest.raises(PairReportRefusal, match="pair_nonfinite_json"):
        parse_json_object(b'{"overflow":1e999}', code_prefix="pair_overflow")


def test_malformed_stored_metric_is_refused_before_eligibility(tmp_path: Path) -> None:
    journals, results = _sources(tmp_path)
    _tamper_grade_metric(journals[1], results[1])
    with pytest.raises(PairReportRefusal, match="pair_grade_metrics"):
        build_pair_report(journals, results)


def test_report_output_size_and_path_boundaries_are_refused(tmp_path: Path) -> None:
    journals, results = _sources(tmp_path)
    report = build_pair_report(journals, results)
    with pytest.raises(PairReportRefusal, match="pair_output_size"):
        _validate_report_output_size(MAX_REPORT_BYTES + 1)
    oversized = tmp_path / "oversized-report.json"
    with oversized.open("wb") as stream:
        stream.truncate(MAX_REPORT_BYTES + 1)
    with pytest.raises(PairReportRefusal, match="pair_report_size"):
        read_report(oversized)
    with pytest.raises(PairReportRefusal, match="pair_output_unsafe"):
        write_report(report, tmp_path / ".." / "escape.json")


def test_symlinked_journal_path_is_refused(tmp_path: Path) -> None:
    journals, results = _sources(tmp_path)
    link_parent = tmp_path / "link-parent"
    link_parent.symlink_to(tmp_path, target_is_directory=True)
    journals[1] = link_parent / "w5-semantic-g1"
    with pytest.raises(PairReportRefusal, match="pair_attempt_unsafe"):
        build_pair_report(journals, results)


def test_missing_six_member_is_refused(tmp_path: Path) -> None:
    journals, results = _sources(tmp_path)
    journals[1].joinpath("sources.zip").unlink()
    with pytest.raises(PairReportRefusal, match="pair_member_unreadable"):
        build_pair_report(journals, results)
