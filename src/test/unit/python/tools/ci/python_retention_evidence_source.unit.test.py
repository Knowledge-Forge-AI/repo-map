from __future__ import annotations

import copy
import pytest

from ci.python_retention_evidence_source import (
    validate_source_document,
)

from repomap_test_support.retention_evidence_fixture import evidence_source as _make_source


def test_valid_synthetic_source_passes() -> None:
    source = _make_source(status="passed")
    validate_source_document(source)


def test_empty_synthetic_source_passes() -> None:
    source = _make_source(status="passed", file_count=0, cohort_count=0)
    validate_source_document(source)


@pytest.mark.parametrize("missing", [
    "status", "classification", "enforcement_complete", "counts",
    "candidate_sha256", "eligible", "assigned", "enforced", "check_results",
    "cohorts", "cohort_results", "cohort_regressions", "governing_inputs",
    "history", "environment", "inventory_path", "ratchet_sha256",
    "duration_seconds", "validation_duration_seconds", "cohort_evaluation_duration_seconds",
])
def test_missing_required_field_fails(missing: str) -> None:
    source = _make_source()
    del source[missing]
    with pytest.raises(ValueError, match="missing required field"):
        validate_source_document(source)


@pytest.mark.parametrize("mutator,match_err", [
    (lambda s: s.__setitem__("status", "unknown"), "invalid status"),
    (lambda s: s.__setitem__("classification", "bad-cls"), "invalid classification"),
    (lambda s: s.__setitem__("enforcement_complete", "True"), "must be a boolean"),
    (lambda s: s.__setitem__("enforcement_complete", 1), "must be a boolean"),
    (lambda s: s["counts"].__setitem__("total_files", True), "must be a non-negative integer"),
    (lambda s: s["counts"].__setitem__("total_files", 999), "does not match candidate_sha256"),
    (lambda s: s["candidate_sha256"].__setitem__("tools/tool_0.py", "bad_digest"), "entry invalid"),
    (lambda s: s["candidate_sha256"].__setitem__("tools/tool_0.py", "1" * 63), "entry invalid"),
])
def test_type_and_digest_controls_fail(mutator, match_err) -> None:
    source = _make_source()
    mutator(source)
    with pytest.raises(ValueError, match=match_err):
        validate_source_document(source)


@pytest.mark.parametrize("mutator,match_err", [
    (lambda s: s.__setitem__("duration_seconds", float("nan")), "finite non-negative"),
    (lambda s: s.__setitem__("duration_seconds", float("inf")), "finite non-negative"),
    (lambda s: s.__setitem__("duration_seconds", -0.1), "finite non-negative"),
    (lambda s: s.__setitem__("duration_seconds", True), "finite non-negative"),
    (lambda s: s.__setitem__("validation_duration_seconds", True), "finite non-negative"),
    (lambda s: s.__setitem__("cohort_evaluation_duration_seconds", True), "finite non-negative"),
])
def test_nonfinite_and_bool_timings_fail(mutator, match_err) -> None:
    source = _make_source()
    mutator(source)
    with pytest.raises(ValueError, match=match_err):
        validate_source_document(source)


@pytest.mark.parametrize("mutator,match_err", [
    (lambda s: s["eligible"].pop("conftest"), "must contain exactly the six required roots"),
    (lambda s: s["eligible"].__setitem__("extra_root", []), "must contain exactly the six required roots"),
    (lambda s: s["eligible"]["product"].append("tools/tool_0.py"), "root separation violation"),
    (lambda s: s["assigned"]["tools"].append("tools/phantom.py"), "not a subset of eligible"),
    (lambda s: s["enforced"]["tools"].append("tools/phantom.py"), "not a subset of assigned"),
    (lambda s: s["eligible_minus_enforced"].__setitem__("tools", ["tools/tool_0.py"]), "does not match"),
])
def test_partition_controls_fail(mutator, match_err) -> None:
    source = _make_source()
    mutator(source)
    with pytest.raises(ValueError, match=match_err):
        validate_source_document(source)


@pytest.mark.parametrize("mutator,match_err", [
    (lambda s: s["history"]["candidate"].__setitem__("commit", "bad_hash"), "commit and tree must be 40 or 64"),
    (lambda s: s["history"]["candidate"].__setitem__("tree", "x" * 39), "commit and tree must be 40 or 64"),
    (lambda s: s["history"].__setitem__("candidate_inventory_sha256", "9" * 64), "does not match governing_inputs"),
    (lambda s: s["governing_inputs"]["tools/ci/python_retention_inventory.json"].__setitem__("bytes", True), "bytes must be non-negative int"),
    (lambda s: s["governing_inputs"]["tools/ci/python_retention_inventory.json"].__setitem__("bytes", -1), "bytes must be non-negative int"),
    (lambda s: s["governing_inputs"]["tools/ci/python_retention_inventory.json"].__setitem__("sha256", "short"), "sha256 must be 64-char hex"),
    (lambda s: s.__setitem__("ratchet_sha256", "9" * 64), "does not match governing_inputs"),
    (lambda s: s["environment"].__setitem__("sha256", "short"), "sha256 must be a 64-char hex"),
    (lambda s: s["environment"].__setitem__("input_count", True), "input_count must be a non-negative integer"),
])
def test_immutable_identities_fail(mutator, match_err) -> None:
    source = _make_source()
    mutator(source)
    with pytest.raises(ValueError, match=match_err):
        validate_source_document(source)


@pytest.mark.parametrize("mutator,match_err", [
    (lambda s: s["cohorts"].append(copy.deepcopy(s["cohorts"][0])), "duplicate cohort id"),
    (lambda s: s["cohort_results"].pop("cohort_0000"), "cohort_results keys do not match"),
    (lambda s: s["cohort_results"].__setitem__("extra_c", {}), "cohort_results keys do not match"),
    (lambda s: s["cohorts"][0].__setitem__("root", "unknown_root"), "root invalid"),
    (lambda s: s["cohorts"][0].__setitem__("admission", "unknown_adm"), "admission invalid"),
    (lambda s: s["cohorts"][0].__setitem__("members", ["tools/phantom.py"]), "not in root eligible"),
    (lambda s: s["cohort_results"]["cohort_0000"].__setitem__("effective_enforcement", False), "inconsistent effective_enforcement"),
    (lambda s: s["cohort_results"]["cohort_0000"].__setitem__("status", "failed"), "inconsistent effective_enforcement"),
])
def test_cohort_records_and_admissions_fail(mutator, match_err) -> None:
    source = _make_source()
    mutator(source)
    with pytest.raises(ValueError, match=match_err):
        validate_source_document(source)


def test_regression_consistency_fail() -> None:
    source = _make_source(status="failed", file_count=2, cohort_count=2, regressions=["cohort_0000"])
    source["cohort_results"]["cohort_0000"]["status"] = "failed"
    source["cohort_results"]["cohort_0000"]["effective_enforcement"] = False
    source["enforced"]["tools"] = ["tools/tool_1.py"]
    source["eligible_minus_enforced"]["tools"] = ["tools/tool_0.py"]
    source["cohort_regressions"] = []
    with pytest.raises(ValueError, match="cohort_regressions mismatch"):
        validate_source_document(source)

    source["cohort_regressions"] = ["cohort_0000", "cohort_0000"]
    with pytest.raises(ValueError, match="cohort_regressions must be sorted and unique"):
        validate_source_document(source)

    pass_source = _make_source(status="passed")
    pass_source["cohort_regressions"] = ["cohort_0000"]
    with pytest.raises(ValueError, match="passed status cannot declare cohort regressions"):
        validate_source_document(pass_source)


@pytest.mark.parametrize("mutator,match_err", [
    (lambda s: s["cohort_results"]["cohort_0000"]["direct_findings"]["mypy"].append(0), "direct finding index 0 out of bounds"),
    (lambda s: s["cohort_results"]["cohort_0000"]["direct_findings"]["mypy"].append(True), "direct finding index True out of bounds"),
    (lambda s: s["cohort_results"]["cohort_0000"]["direct_findings"]["mypy"].append(-1), "direct finding index -1 out of bounds"),
    (lambda s: s["cohort_results"]["cohort_0000"]["dependency_finding_indices"].append(0), "dependency finding index 0 out of bounds"),
    (lambda s: s["cohort_results"]["cohort_0000"]["dependency_finding_indices"].append(True), "dependency finding index True out of bounds"),
    (lambda s: s["cohort_results"]["cohort_0000"]["dependency_finding_indices"].append(-1), "dependency finding index -1 out of bounds"),
    (lambda s: s["cohort_results"]["cohort_0000"]["governed_dependency_indices"].append(99), "governed_dependency_indices index 99 out of bounds"),
    (lambda s: s["cohort_results"]["cohort_0000"]["governed_dependency_indices"].append(True), "governed_dependency_indices index True out of bounds"),
    (lambda s: s["cohort_results"]["cohort_0000"]["ungoverned_dependency_indices"].append(99), "ungoverned_dependency_indices index 99 out of bounds"),
    (lambda s: s["cohort_results"]["cohort_0000"]["ungoverned_dependency_indices"].append(True), "ungoverned_dependency_indices index True out of bounds"),
    (lambda s: s["cohort_results"]["cohort_0000"]["dependency_blocker_indices"].append(99), "dependency_blocker_indices index 99 out of bounds"),
    (lambda s: s["cohort_results"]["cohort_0000"]["dependency_blocker_indices"].append(True), "dependency_blocker_indices index True out of bounds"),
])
def test_all_indices_out_of_bounds_and_bool_rejection(mutator, match_err) -> None:
    source = _make_source()
    mutator(source)
    with pytest.raises(ValueError, match=match_err):
        validate_source_document(source)


def test_real_empty_root_and_product_nested_checks() -> None:
    source = _make_source(status="passed")
    source["check_results"]["conftest"] = {"status": "passed", "paths": [], "reason": "empty applicable set"}
    source["check_results"]["product"] = {
        "status": "passed",
        "classification": "passed",
        "paths": [],
        "checks": {
            "retained_ratchet": {"status": "accepted", "classification": "passed"},
            "type_ownership": {"status": "passed"},
        },
    }
    validate_source_document(source)


def test_atomic_groups_source_document_validation() -> None:
    from ci.python_retention_atomic_source import make_atomic_group_id, make_internal_dependency_sha256
    source = _make_source(status="passed", file_count=4, cohort_count=2)
    cids = ["cohort_0000", "cohort_0001"]
    gid = make_atomic_group_id(cids)
    source["cohort_results"]["cohort_0000"]["atomic_group_id"] = gid
    source["cohort_results"]["cohort_0001"]["atomic_group_id"] = gid
    source["atomic_groups"] = {
        gid: {
            "id": gid,
            "cohort_ids": cids,
            "root": "tools",
            "governing_profile": "clean_tooling",
            "internal_dependency_count": 2,
            "internal_dependency_sha256": make_internal_dependency_sha256([["tools/tool_0.py", "tools/tool_1.py"]]),
            "external_dependency_indices": [],
            "ungoverned_dependency_indices": [],
            "dependency_blocker_indices": [],
            "status": "passed",
            "effective_enforcement": True,
        }
    }
    validate_source_document(source)

    bad_source = copy.deepcopy(source)
    bad_source["cohort_results"]["cohort_0000"]["atomic_group_id"] = "scc-v1-unknown"
    with pytest.raises(ValueError, match="atomic_group_id mismatch"):
        validate_source_document(bad_source)
