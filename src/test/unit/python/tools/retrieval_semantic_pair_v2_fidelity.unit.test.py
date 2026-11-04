"""Focused V2 fidelity and source-custody contracts."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

import retrieval_semantic_pair_v2_report as report_module
from repomap_test_support.w5_pair_fixtures import make_pair_artifacts
from retrieval_semantic_experiment_contracts import canonical_json_bytes
from retrieval_semantic_pair_artifacts import JournalArtifact, PairReportRefusal, load_journal
from retrieval_semantic_pair_v2_cost import component_counts
from retrieval_semantic_pair_v2_disclosures import validate_generation_2_component_disclosure
from retrieval_semantic_pair_v2_envelope import project_envelope
from retrieval_semantic_pair_v2_projection import _result
from retrieval_semantic_pair_v2_rows import project_generation
from retrieval_semantic_pair_v2_report import (
    build_pair_report_v2,
    read_pair_report_v2,
    write_pair_report_v2,
)


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


def _sources(tmp_path: Path) -> tuple[dict[int, Path], dict[int, Path]]:
    journals: dict[int, Path] = {}
    results: dict[int, Path] = {}
    for generation in (1, 2):
        journal, result = make_pair_artifacts(tmp_path, generation)
        journals[generation] = journal
        results[generation] = result
    return journals, results


def _pair(report: dict[str, object], arm_id: str) -> dict[str, object]:
    pairs = cast(list[dict[str, object]], report["pairs"])
    return next(
        pair
        for pair in pairs
        if cast(dict[str, object], pair["identity"])["arm_id"] == arm_id
    )


def test_baseline_envelope_is_not_a_missing_operation(tmp_path: Path) -> None:
    journals, results = _sources(tmp_path)
    report = build_pair_report_v2(journals, results)
    baseline = _pair(report, "postgres_native_fts:postgresql")
    vector = _pair(report, "exact_vector")
    baseline_context = cast(dict[str, object], baseline["context"])
    vector_context = cast(dict[str, object], vector["context"])
    assert baseline_context["observed_operation_status"] == "envelope_only"
    assert "observed_operation_not_recorded" not in cast(
        list[str], baseline_context["comparability_gaps"]
    )
    assert vector_context["observed_operation_status"] == "not_recorded"
    assert "observed_operation_not_recorded" in cast(
        list[str], vector_context["comparability_gaps"]
    )


def test_unknown_reasons_are_withheld_but_unknown_enums_refuse() -> None:
    envelope = project_envelope({
        "envelope": {
            "capability_state": "refused",
            "refusal_code": "private_policy_code",
            "unavailable_reason": "private_unavailable_code",
            "omissions": [{"reason_code": "private_omission_code"}],
            "hits": [{"rank": 1}],
        }
    })
    assert envelope is not None
    assert envelope["refusal_code"] == "withheld"
    assert envelope["unavailable_reason"] == "withheld"
    assert envelope["omission_reason_codes"] == ["withheld"]
    result = _result({
        "cell": {
            "execution_state": "failed", "reason": "private_cell_reason",
            "elapsed_ns": None, "query_bytes": None,
            "cleanup_status": "failed", "candidates": [],
        },
        "correspondence": None, "byte_work": None,
    })
    assert cast(dict[str, object], result["cell"])["reason"] == "withheld"
    with pytest.raises(PairReportRefusal, match="pair_v2_capability"):
        project_envelope({"envelope": {"capability_state": "future_state"}})


@pytest.mark.parametrize("reason", [
    "index_not_selected", "query_not_admitted", "source_scope_refused",
    "admitted_exact_query_not_executed", "admitted_hybrid_query_not_executed",
    "admitted_hnsw_execution_failed",
])
def test_known_evaluator_reasons_remain_public(reason: str) -> None:
    result = _result({
        "cell": {
            "execution_state": "failed", "reason": reason,
            "elapsed_ns": None, "query_bytes": None,
            "cleanup_status": "failed", "candidates": [],
        },
        "correspondence": None, "byte_work": None,
    })
    assert cast(dict[str, object], result["cell"])["reason"] == reason
    envelope = project_envelope({"envelope": {"capability_state": "refused", "refusal_code": reason}})
    assert envelope is not None and envelope["refusal_code"] == reason
    generation = project_generation({
        "generation": 1, "attempt_id": "attempt", "terminal_status": "failed",
        "legacy_report": {"status": "failed", "failure_code": reason},
        "result_v2_status": "failed", "result_v2_failure_code": reason,
        "plan": {"task_ids": ["task"], "task_digests": [_DIGEST], "arms": [],
                 "repetitions": 1},
    }, {})
    assert cast(dict[str, object], generation["legacy_report"])["failure_code"] == reason
    assert generation["result_v2_failure_code"] == reason


def _journal_with_counts(
    journal_path: Path, counts: dict[str, int], input_records: int,
) -> JournalArtifact:
    journal = load_journal(journal_path)
    report = dict(journal.report)
    report["component"] = dict(_COMPONENT_DIGESTS)
    report["component_counts"] = counts
    report["component_response_cost"] = {"input_records": input_records}
    return replace(journal, report=report)


def test_recorded_component_count_algebra_and_cost_mismatch_refuse(tmp_path: Path) -> None:
    journals, _results = _sources(tmp_path)
    valid = {"document_count": 80, "query_count": 4, "record_count": 84, "embedding_count": 84}
    recorded = component_counts(_journal_with_counts(journals[1], valid, 84))
    assert recorded["status"] == "recorded"
    assert recorded["values"] == valid
    bad_algebra = {**valid, "record_count": 83}
    with pytest.raises(PairReportRefusal, match="pair_v2_component_count_algebra"):
        component_counts(_journal_with_counts(journals[1], bad_algebra, 83))
    with pytest.raises(PairReportRefusal, match="pair_v2_component_count_cost_mismatch"):
        component_counts(_journal_with_counts(journals[1], valid, 83))


def test_recorded_document_only_is_bound_to_sealed_counts() -> None:
    work = {
        "component_counts": {
            "status": "recorded",
            "values": {"document_count": 80, "query_count": 0, "record_count": 80},
        }
    }
    disclosures: dict[str, object] = {
        "generation_2_limitation": {
            "document_only": {"value": True, "evidence_status": "recorded_sealed_response"},
            "component_querycount": {"value": 0, "evidence_status": "recorded_sealed_response"},
        }
    }
    validate_generation_2_component_disclosure(disclosures, work)
    forged = dict(disclosures)
    forged["generation_2_limitation"] = {
        **cast(dict[str, object], disclosures["generation_2_limitation"]),
        "document_only": {"value": False, "evidence_status": "recorded_sealed_response"},
    }
    with pytest.raises(PairReportRefusal, match="pair_v2_disclosures"):
        validate_generation_2_component_disclosure(forged, work)


def test_reader_refuses_forged_recorded_document_only(tmp_path: Path) -> None:
    journals, results = _sources(tmp_path)
    report = build_pair_report_v2(journals, results)
    output = tmp_path / "forged-document-only.json"
    write_pair_report_v2(report, output)
    raw = json.loads(output.read_text())
    limitation = raw["disclosures"]["generation_2_limitation"]
    assert limitation["document_only"] == {"value": None, "evidence_status": "unknown"}
    limitation["document_only"] = {"value": True, "evidence_status": "recorded_sealed_response"}
    output.write_bytes(canonical_json_bytes(raw) + b"\n")
    with pytest.raises(PairReportRefusal, match="pair_v2_disclosures"):
        read_pair_report_v2(output)


def test_cal07_is_a_historical_reference_not_current_observation(tmp_path: Path) -> None:
    journals, results = _sources(tmp_path)
    report = build_pair_report_v2(journals, results)
    disclosures = cast(dict[str, object], report["disclosures"])
    cal07 = cast(dict[str, object], disclosures["native_cal07_raw_process_stdout_bytes"])
    assert cal07["status"] == "historical_reference_only"
    assert cal07["historical_reference"] == 495781
    assert cal07["current_observed_values"] == []


def test_second_journal_read_must_match_v1_source_binding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    journals, results = _sources(tmp_path)
    original = report_module.load_journal

    def changed(path: object) -> JournalArtifact:
        artifact = original(path)
        members = dict(artifact.members)
        members["report.json"] += b" "
        return replace(artifact, members=members)

    monkeypatch.setattr(report_module, "load_journal", changed)
    with pytest.raises(PairReportRefusal, match="pair_v2_source_changed"):
        build_pair_report_v2(journals, results)
