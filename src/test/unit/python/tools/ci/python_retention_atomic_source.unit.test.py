from __future__ import annotations

import copy
from typing import Any
import pytest

from ci.python_retention_atomic_source import (
    make_atomic_group_id,
    make_internal_dependency_sha256,
    validate_atomic_groups,
)
from ci.python_retention_evidence_source import (
    RetentionSourceValidationError,
    validate_source_document,
)
from repomap_test_support.retention_evidence_fixture import evidence_source as _make_source


def _build_atomic_source(
    *,
    status: str = "passed",
    admissions: tuple[str, ...] = ("admitted", "admitted"),
    cohort_statuses: tuple[str, ...] = ("passed", "passed"),
    cross_root: bool = False,
    blockers: list[str] | None = None,
    regressions: list[str] | None = None,
) -> dict[str, Any]:
    c_count = len(admissions)
    reg_list = list(regressions or [])
    src_status = "passed" if all(s == "passed" for s in cohort_statuses) and not reg_list and status == "passed" else "failed"
    source = _make_source(
        status=src_status,
        cohort_count=c_count,
        file_count=c_count * 2,
        regressions=reg_list,
    )
    cids = sorted(f"cohort_{i:04d}" for i in range(c_count))
    gid = make_atomic_group_id(cids)
    edges = [["tools/tool_0.py", "tools/tool_1.py"], ["tools/tool_1.py", "tools/tool_0.py"]]
    internal_sha = make_internal_dependency_sha256(edges)

    group_blocker_indices: list[int] = []
    if blockers:
        source["cohort_dependency_blockers"] = sorted(
            set(source.get("cohort_dependency_blockers", [])) | set(blockers)
        )
        b_table = source["cohort_dependency_blockers"]
        group_blocker_indices = [b_table.index(b) for b in blockers]

    is_mixed = "admitted" in admissions and "pending" in admissions
    is_all_admitted = set(admissions) == {"admitted"}
    g_pass = status == "passed" and all(s == "passed" for s in cohort_statuses) and not blockers and not is_mixed and not cross_root
    g_eff = g_pass and is_all_admitted

    src_status = "passed" if g_pass and is_all_admitted and not reg_list else "failed"
    source["status"] = src_status
    source["classification"] = "passed" if src_status == "passed" else "ratchet-regression" if reg_list else "policy-finding"
    source["enforcement_complete"] = (src_status == "passed")

    if cross_root:
        source["cohorts"][1]["root"] = "test_support"
        source["cohort_results"]["cohort_0001"]["root"] = "test_support"
        source["eligible"]["test_support"] = list(source["cohorts"][1]["members"])
        source["assigned"]["test_support"] = list(source["cohorts"][1]["members"])
        source["eligible"]["tools"] = list(source["cohorts"][0]["members"])
        source["assigned"]["tools"] = list(source["cohorts"][0]["members"])
        source["check_results"]["test_support"] = copy.deepcopy(source["check_results"]["tools"])
        source["check_results"]["test_support"]["paths"] = source["eligible"]["test_support"]
        source["check_results"]["test_support"]["analyzed_paths"] = source["eligible"]["test_support"]
        g_root = None
        g_prof = None
    else:
        g_root = "tools"
        g_prof = "clean_tooling"

    for i, cid in enumerate(cids):
        adm = admissions[i]
        c_st = cohort_statuses[i]
        c_eff = (c_st == "passed" and adm == "admitted" and g_eff)
        source["cohorts"][i]["admission"] = adm
        source["cohort_results"][cid]["admission"] = adm
        source["cohort_results"][cid]["status"] = c_st
        source["cohort_results"][cid]["effective_enforcement"] = c_eff
        source["cohort_results"][cid]["evidence_complete"] = (c_st == "passed")
        source["cohort_results"][cid]["atomic_group_id"] = gid

    source["atomic_groups"] = {
        gid: {
            "id": gid,
            "cohort_ids": cids,
            "root": g_root,
            "governing_profile": g_prof,
            "internal_dependency_count": len(edges),
            "internal_dependency_sha256": internal_sha,
            "external_dependency_indices": [],
            "ungoverned_dependency_indices": [],
            "dependency_blocker_indices": group_blocker_indices,
            "status": "passed" if g_pass else "failed",
            "effective_enforcement": g_eff,
        }
    }
    enf_tools = [m for c in source["cohorts"] if c["root"] == "tools" and source["cohort_results"][c["id"]]["effective_enforcement"] for m in c["members"]]
    source["enforced"]["tools"] = sorted(enf_tools)
    source["eligible_minus_enforced"]["tools"] = sorted(set(source["eligible"]["tools"]) - set(enf_tools))
    enf_supp = [m for c in source["cohorts"] if c["root"] == "test_support" and source["cohort_results"][c["id"]]["effective_enforcement"] for m in c["members"]]
    source["enforced"]["test_support"] = sorted(enf_supp)
    source["eligible_minus_enforced"]["test_support"] = sorted(set(source["eligible"]["test_support"]) - set(enf_supp))
    return source


def test_helper_identities_determinism() -> None:
    cids = ["cohort_0001", "cohort_0000"]
    gid1 = make_atomic_group_id(cids)
    gid2 = make_atomic_group_id(sorted(cids))
    assert gid1 == gid2
    assert gid1.startswith("scc-v1-")
    assert len(gid1) == 7 + 64

    edges1 = [["b", "a"], ["a", "b"]]
    edges2 = [["a", "b"], ["b", "a"]]
    sha1 = make_internal_dependency_sha256(edges1)
    sha2 = make_internal_dependency_sha256(edges2)
    assert sha1 == sha2
    assert len(sha1) == 64


def test_valid_atomic_group_passes_admitted() -> None:
    source = _build_atomic_source(status="passed")
    validate_source_document(source)


def test_valid_atomic_group_passes_pending() -> None:
    source = _build_atomic_source(status="passed", admissions=("pending", "pending"))
    validate_source_document(source)


def test_valid_atomic_group_three_cohort_cycle() -> None:
    source = _build_atomic_source(
        status="passed",
        admissions=("admitted", "admitted", "admitted"),
        cohort_statuses=("passed", "passed", "passed"),
    )
    validate_source_document(source)


def test_inconsistent_roots_fail() -> None:
    source = _build_atomic_source(status="passed")
    gid = next(iter(source["atomic_groups"]))
    source["atomic_groups"][gid]["root"] = "product"
    with pytest.raises(RetentionSourceValidationError, match="root.*does not match constituents root"):
        validate_atomic_groups(source)

    cross_source = _build_atomic_source(
        cross_root=True, status="failed", cohort_statuses=("failed", "failed"),
        regressions=["cohort_0000", "cohort_0001"]
    )
    c_gid = next(iter(cross_source["atomic_groups"]))
    cross_source["atomic_groups"][c_gid]["root"] = "tools"
    with pytest.raises(RetentionSourceValidationError, match="cross-root.*root must be null"):
        validate_atomic_groups(cross_source)

    cross_pass = _build_atomic_source(
        cross_root=True, status="failed", cohort_statuses=("failed", "failed"),
        regressions=["cohort_0000", "cohort_0001"]
    )
    cp_gid = next(iter(cross_pass["atomic_groups"]))
    cross_pass["atomic_groups"][cp_gid]["status"] = "passed"
    with pytest.raises(RetentionSourceValidationError, match="cross-root.*must have status='failed'"):
        validate_atomic_groups(cross_pass)


def test_inconsistent_members_and_identities_fail() -> None:
    source = _build_atomic_source(status="passed")
    gid = next(iter(source["atomic_groups"]))
    source["atomic_groups"][gid]["cohort_ids"] = ["cohort_0000"]
    with pytest.raises(RetentionSourceValidationError, match="at least two cohorts"):
        validate_atomic_groups(source)

    source2 = _build_atomic_source(status="passed")
    gid2 = next(iter(source2["atomic_groups"]))
    source2["atomic_groups"][gid2]["cohort_ids"] = ["cohort_0001", "cohort_0000"]
    with pytest.raises(RetentionSourceValidationError, match="must be sorted and unique"):
        validate_atomic_groups(source2)

    source3 = _build_atomic_source(status="passed")
    gid3 = next(iter(source3["atomic_groups"]))
    source3["atomic_groups"][gid3]["cohort_ids"] = ["cohort_0000", "cohort_phantom"]
    with pytest.raises(RetentionSourceValidationError, match="id does not match hash"):
        validate_atomic_groups(source3)


def test_inconsistent_statuses_fail() -> None:
    source = _build_atomic_source(status="passed")
    source["cohort_results"]["cohort_0000"]["status"] = "failed"
    source["cohort_results"]["cohort_0000"]["effective_enforcement"] = False
    source["cohort_results"]["cohort_0000"]["evidence_complete"] = False
    with pytest.raises(RetentionSourceValidationError, match="passing atomic group.*has failed constituent cohorts"):
        validate_atomic_groups(source)

    fail_source = _build_atomic_source(status="failed", cohort_statuses=("failed", "failed"), regressions=["cohort_0000", "cohort_0001"])
    fail_source["cohort_results"]["cohort_0000"]["status"] = "passed"
    fail_source["cohort_results"]["cohort_0000"]["effective_enforcement"] = True
    fail_source["cohort_results"]["cohort_0000"]["evidence_complete"] = True
    with pytest.raises(RetentionSourceValidationError, match="failed atomic group.*has passing constituent cohorts"):
        validate_atomic_groups(fail_source)

    mixed_source = _build_atomic_source(admissions=("admitted", "pending"), cohort_statuses=("failed", "failed"), regressions=["cohort_0000"])
    m_gid = next(iter(mixed_source["atomic_groups"]))
    mixed_source["atomic_groups"][m_gid]["status"] = "passed"
    with pytest.raises(RetentionSourceValidationError, match="mixed admission atomic group.*must have status='failed'"):
        validate_atomic_groups(mixed_source)


def test_references_and_unknown_group_ids_fail() -> None:
    source = _build_atomic_source(status="passed")
    source["cohort_results"]["cohort_0000"]["atomic_group_id"] = "scc-v1-unknown"
    with pytest.raises(RetentionSourceValidationError, match="atomic_group_id mismatch"):
        validate_atomic_groups(source)

    old_source = _make_source(status="passed")
    old_source["cohort_results"]["cohort_0000"]["atomic_group_id"] = "scc-v1-unknown"
    with pytest.raises(RetentionSourceValidationError, match="references missing atomic_groups"):
        validate_atomic_groups(old_source)

    source3 = _build_atomic_source(status="passed", admissions=("pending", "pending"))
    source3["cohort_results"]["cohort_0000"]["effective_enforcement"] = True
    with pytest.raises(RetentionSourceValidationError, match="effective_enforcement mismatch"):
        validate_atomic_groups(source3)


def test_dependency_blockers_and_index_bounds_fail() -> None:
    source = _build_atomic_source(status="passed")
    gid = next(iter(source["atomic_groups"]))
    source["atomic_groups"][gid]["dependency_blocker_indices"] = [999]
    with pytest.raises(RetentionSourceValidationError, match="dependency_blocker_indices index 999 out of bounds"):
        validate_source_document(source)

    source2 = _build_atomic_source(status="passed")
    gid2 = next(iter(source2["atomic_groups"]))
    source2["atomic_groups"][gid2]["external_dependency_indices"] = [True]
    with pytest.raises(RetentionSourceValidationError, match="external_dependency_indices index True out of bounds"):
        validate_source_document(source2)


def test_overlapping_cohorts_and_regressions_controls() -> None:
    source = _build_atomic_source(
        status="passed",
        admissions=("admitted", "admitted", "admitted"),
        cohort_statuses=("passed", "passed", "passed"),
    )
    g1 = make_atomic_group_id(["cohort_0000", "cohort_0001"])
    g2 = make_atomic_group_id(["cohort_0001", "cohort_0002"])
    source["atomic_groups"] = {
        g1: {
            "id": g1, "cohort_ids": ["cohort_0000", "cohort_0001"],
            "root": "tools", "governing_profile": "clean_tooling",
            "internal_dependency_count": 2, "internal_dependency_sha256": "0" * 64,
            "external_dependency_indices": [], "ungoverned_dependency_indices": [],
            "dependency_blocker_indices": [], "status": "passed", "effective_enforcement": True,
        },
        g2: {
            "id": g2, "cohort_ids": ["cohort_0001", "cohort_0002"],
            "root": "tools", "governing_profile": "clean_tooling",
            "internal_dependency_count": 2, "internal_dependency_sha256": "0" * 64,
            "external_dependency_indices": [], "ungoverned_dependency_indices": [],
            "dependency_blocker_indices": [], "status": "passed", "effective_enforcement": True,
        },
    }
    source["cohort_results"]["cohort_0000"]["atomic_group_id"] = g1
    source["cohort_results"]["cohort_0001"]["atomic_group_id"] = g1
    source["cohort_results"]["cohort_0002"]["atomic_group_id"] = g2
    with pytest.raises(RetentionSourceValidationError, match="belongs to multiple atomic groups"):
        validate_atomic_groups(source)

    fail_source = _build_atomic_source(
        status="failed",
        admissions=("admitted", "admitted"),
        cohort_statuses=("failed", "failed"),
        regressions=["cohort_0000"],
    )
    with pytest.raises(RetentionSourceValidationError, match="missing from cohort_regressions"):
        validate_atomic_groups(fail_source)


def test_internal_dependencies_and_profile_controls() -> None:
    source = _build_atomic_source(status="passed")
    gid = next(iter(source["atomic_groups"]))
    source["atomic_groups"][gid]["internal_dependency_count"] = -1
    with pytest.raises(RetentionSourceValidationError, match="internal_dependency_count must be non-negative"):
        validate_atomic_groups(source)

    source["atomic_groups"][gid]["internal_dependency_count"] = 2
    source["atomic_groups"][gid]["internal_dependency_sha256"] = "short_hash"
    with pytest.raises(RetentionSourceValidationError, match="internal_dependency_sha256 must be 64-char hex"):
        validate_atomic_groups(source)

    source_null_root = _build_atomic_source(status="passed")
    gid_nr = next(iter(source_null_root["atomic_groups"]))
    source_null_root["atomic_groups"][gid_nr]["root"] = None
    source_null_root["atomic_groups"][gid_nr]["governing_profile"] = "clean_tooling"
    with pytest.raises(RetentionSourceValidationError, match="null root requires null governing_profile"):
        validate_atomic_groups(source_null_root)

def test_unicode_group_identity_matches_evaluator() -> None:
    from ci.python_retention_atomic import canonical_scc_id
    assert make_atomic_group_id(["cohort_é", "cohort_a"]) == canonical_scc_id(["cohort_é", "cohort_a"])


def test_group_profile_must_match_constituents() -> None:
    source = _build_atomic_source()
    next(iter(source["atomic_groups"].values()))["governing_profile"] = "forged"
    with pytest.raises(RetentionSourceValidationError, match="profile"):
        validate_atomic_groups(source)
