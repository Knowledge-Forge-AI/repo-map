"""Sensitivity, canonical ordering and fail-closed compact evidence controls."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any
import pytest
from ci.python_retention_evidence import compact_retention_evidence, canonical_json_bytes, make_collection_commitment
from ci.python_retention_evidence_schema import validate_retention_evidence_schema
from ci.pre_review_records import sanitize_machine_result
from repomap_test_support.retention_evidence_fixture import evidence_source


def reordered(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: reordered(item) for key, item in reversed(list(value.items()))}
    if isinstance(value, list):
        return [reordered(item) for item in value]
    return value


def test_logical_source_order_does_not_change_commitments() -> None:
    original = evidence_source()
    changed = reordered(original)
    for field in ("eligible", "assigned", "enforced", "eligible_minus_enforced", "unassigned"):
        for paths in changed[field].values():
            paths.reverse()
    changed["cohorts"].reverse()
    for record in [*changed["cohorts"], *changed["cohort_results"].values()]:
        record["members"].reverse()
    assert compact_retention_evidence(original) == compact_retention_evidence(changed)


@pytest.mark.parametrize("kind,commitment", [("path", "candidate_files"), ("candidate_digest", "candidate_files"),
    ("finding", "check_results"), ("cohort_result", "cohort_results"), ("dependency", "cohort_dependency_paths")])
def test_omitted_changes_affect_commitments(kind: str, commitment: str) -> None:
    source = evidence_source(status="failed", regressions=["cohort_0000"])
    before = compact_retention_evidence(source)
    if kind == "path":
        source = json.loads(json.dumps(source).replace("tools/tool_0.py", "tools/renamed.py"))
    elif kind == "candidate_digest":
        source["candidate_sha256"]["tools/tool_0.py"] = "9" * 64
    elif kind == "finding":
        source["check_results"]["tools"]["checks"]["mypy"]["findings"][0]["message"] = "different finding"
    elif kind == "cohort_result":
        source["cohort_results"]["cohort_0000"]["duration_seconds"] = 0.25
    else:
        source["cohort_dependency_paths"].append("tools/tool_0.py")
    after = compact_retention_evidence(source)
    assert before["omitted_collections"][commitment]["sha256"] != after["omitted_collections"][commitment]["sha256"]
    assert before["sanitized_source_commitment"] != after["sanitized_source_commitment"]


def test_admission_status_and_regressions_are_visible() -> None:
    pending = compact_retention_evidence(evidence_source(status="failed"))
    passed = compact_retention_evidence(evidence_source())
    regression = compact_retention_evidence(evidence_source(status="failed", regressions=["cohort_0000"]))
    assert pending["cohorts"]["pending"] == passed["cohorts"]["admitted"] == 2
    assert pending["omitted_collections"]["cohorts"]["sha256"] != passed["omitted_collections"]["cohorts"]["sha256"]
    assert passed["status"] == "passed" and regression["status"] == "failed"
    assert regression["cohorts"]["regressions"] == ["cohort_0000"]


@pytest.mark.parametrize("field", ["eligible_minus_enforced", "profile_progress", "cohort_results", "check_results", "history", "environment"])
def test_absent_evidence_cannot_be_complete_success(field: str) -> None:
    source = evidence_source()
    del source[field]
    with pytest.raises(ValueError):
        compact_retention_evidence(source)


@pytest.mark.parametrize("mutation", ["roots", "bindings", "commitments", "regressions", "nan", "bool"])
def test_compact_schema_rejects_qualification_tampering(mutation: str) -> None:
    doc = compact_retention_evidence(evidence_source())
    if mutation == "roots":
        doc["roots"]["tools"]["enforced"] -= 1
    elif mutation == "bindings":
        del doc["bindings"]["environment"]
    elif mutation == "commitments":
        del doc["omitted_collections"]["cohort_dependency_paths"]
    elif mutation == "regressions":
        doc["cohorts"]["regressions"] = ["hidden"]
    elif mutation == "nan":
        doc["timings"]["duration_seconds"] = float("nan")
    else:
        doc["totals"]["enforced"] = True
    with pytest.raises(ValueError):
        validate_retention_evidence_schema(doc)


def test_sanitize_keys_values_and_collision_without_private_error(tmp_path: Path) -> None:
    scratch, tool = tmp_path / "scratch", tmp_path / "tool"
    source = evidence_source(status="failed", regressions=["cohort_0000"])
    source["check_results"]["tools"]["message"] = str(tool / "bin/check")
    source["extra"] = {str(scratch / "record.json"): str(tool / "private.json")}
    original = copy.deepcopy(source)
    sanitized = sanitize_machine_result(source, scratch, tool)
    assert isinstance(sanitized, dict)
    data = canonical_json_bytes(compact_retention_evidence(sanitized))
    assert str(tmp_path).encode() not in data
    assert source == original
    with pytest.raises(ValueError) as error:
        sanitize_machine_result({str(scratch / "record"): 1, str(tool / "record"): 2}, scratch, tool)
    assert str(tmp_path) not in str(error.value)


def test_scale_populated_findings_dependencies_and_regressions() -> None:
    source = evidence_source(status="failed", file_count=1500, cohort_count=1125,
                             regressions=[f"cohort_{i:04d}" for i in range(500)])
    for finding in source["check_results"]["tools"]["checks"]["mypy"]["findings"]:
        finding["message"] = "bounded synthetic diagnostic " * 300
    source["cohort_dependency_paths"] = list(source["candidate_sha256"])
    for record in source["cohort_results"].values():
        record["governed_dependency_indices"] = list(range(500))
    raw = canonical_json_bytes(source)
    compact = canonical_json_bytes(compact_retention_evidence(source))
    assert len(raw) > 5 * 1024 * 1024
    assert len(compact) < 1024 * 1024
    assert len(json.loads(compact)["cohorts"]["regressions"]) == 500


@pytest.mark.parametrize("mutation", ["checks", "mypy", "completed", "count"])
def test_required_executed_checks_fail_closed(mutation: str) -> None:
    source = evidence_source()
    checks = source["check_results"]["tools"]
    if mutation == "checks":
        del checks["checks"]
    elif mutation == "mypy":
        del checks["checks"]["mypy"]
    elif mutation == "completed":
        del checks["checks"]["mypy"]["completed"]
    else:
        checks["checks"]["mypy"]["count"] = 1
    with pytest.raises(ValueError):
        compact_retention_evidence(source)


def test_unavailable_root_duration_is_not_claimed_as_zero() -> None:
    compact = compact_retention_evidence(evidence_source())
    assert compact["timings"]["root_check_seconds"]["tools"] == 0.1
    assert compact["timings"]["root_check_seconds"]["product"] is None


@pytest.mark.parametrize("kind", ["missing_root_counts", "root_nan"])
def test_required_root_diagnostics_validate(kind: str) -> None:
    compact = compact_retention_evidence(evidence_source())
    if kind == "missing_root_counts":
        del compact["finding_counts"]["tools"]
    else:
        compact["timings"]["root_check_seconds"]["tools"] = float("nan")
    with pytest.raises(ValueError):
        validate_retention_evidence_schema(compact)


@pytest.mark.parametrize("items,count", [(None, None), (1, None), (True, None), ([], -1), ([], True), ([], 1.5)])
def test_commitment_rejects_unproven_or_invalid_count(items: Any, count: Any) -> None:
    with pytest.raises(ValueError, match="count"):
        make_collection_commitment(items, "element", count)


def test_commitment_preserves_explicit_flattened_count_and_zero() -> None:
    assert make_collection_commitment({"root": ["a", "b"]}, "path", 2)["count"] == 2
    assert make_collection_commitment([], "path", 0)["count"] == 0
