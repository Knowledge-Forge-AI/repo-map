from __future__ import annotations

from typing import Any

import pytest

from ci.python_quality_profiles import derive_profile_path_facts
from ci.python_quality_ownership import attribute_product_dependencies
from ci.python_retention_reporting import add_profile_progress, build_profile_progress


def _check_result(
    paths: list[str], *,
    ruff_findings: list[dict[str, Any]] | None = None,
    mypy_findings: list[dict[str, Any]] | None = None,
    file_length_findings: list[dict[str, Any]] | None = None,
    completed: bool = True,
) -> dict[str, Any]:
    checks = {
        "ruff": {"status": "failed" if ruff_findings else "passed",
                  "findings": ruff_findings or [], "completed": completed},
        "mypy": {"status": "failed" if mypy_findings else "passed",
                 "findings": mypy_findings or [], "completed": completed},
        "file_length": {"status": "failed" if file_length_findings else "passed",
                        "findings": file_length_findings or [], "completed": completed},
    }
    return {
        "status": "failed" if any(check["status"] == "failed" for check in checks.values()) else "passed",
        "paths": paths,
        "analyzed_paths": paths if completed else [],
        "checks": checks,
        "classification": "tool-failure" if not completed else "passed",
    }


def test_complete_profile_distinguishes_clean_and_finding_paths() -> None:
    paths = ["tools/clean.py", "tools/bad.py"]
    result = _check_result(
        paths,
        ruff_findings=[{"path": "tools/bad.py", "code": "F401", "message": "unused"}],
    )

    facts = derive_profile_path_facts(result, paths)

    assert facts["profile_executed_paths"] == sorted(paths)
    assert facts["clean_under_profile"] == ["tools/clean.py"]
    assert facts["finding_paths"] == ["tools/bad.py"]
    assert facts["unknown_paths"] == []
    assert facts["finding_or_tool_failure_paths"] == ["tools/bad.py"]
    assert facts["evidence_complete"] is True


def test_dependency_finding_keeps_every_owner_path_unknown() -> None:
    paths = ["tools/owner.py", "tools/caller.py"]
    result = _check_result(
        paths,
        mypy_findings=[
            {"path": "tools/dependency.py", "code": "assignment", "dependency": True},
        ],
    )

    facts = derive_profile_path_facts(result, paths)

    assert facts["profile_executed_paths"] == sorted(paths)
    assert facts["clean_under_profile"] == []
    assert facts["unknown_paths"] == sorted(paths)
    assert facts["finding_or_tool_failure_paths"] == sorted(paths)
    assert facts["evidence_complete"] is True


def test_governed_product_debt_retains_raw_evidence_and_cleans_owner() -> None:
    paths = ["tools/owner.py"]
    product = "src/main/python/repomap_kg/owner.py"
    finding = {"path": product, "code": "assignment", "dependency": True}
    raw = _check_result(paths, mypy_findings=[finding])
    result = attribute_product_dependencies(raw, [product])
    assert result["status"] == "passed"
    assert result["raw_status"] == "failed"
    assert result["checks"]["mypy"]["raw_status"] == "failed"
    assert result["checks"]["mypy"]["findings"] == [finding]
    assert raw["status"] == "failed"
    assert "governed_dependency_paths" not in raw["checks"]["mypy"]
    assert derive_profile_path_facts(result)["clean_under_profile"] == paths


def test_direct_finding_cannot_be_discarded_by_dependency_marker() -> None:
    paths = ["tools/owner.py", "tools/clean.py"]
    raw = _check_result(paths, mypy_findings=[
        {"path": paths[0], "code": "assignment", "dependency": True},
    ])
    result = attribute_product_dependencies(raw, paths)
    facts = derive_profile_path_facts(result)
    assert result["status"] == "failed"
    assert facts["finding_paths"] == [paths[0]]
    assert facts["clean_under_profile"] == [paths[1]]


def test_unowned_dependency_still_blocks_after_product_attribution() -> None:
    product = "src/main/python/repomap_kg/owner.py"
    raw = _check_result(["tools/owner.py"], mypy_findings=[
        {"path": product, "dependency": True},
        {"path": "tools/unselected.py", "dependency": True},
    ])
    result = attribute_product_dependencies(raw, [product])
    assert result["status"] == "failed"
    assert derive_profile_path_facts(result)["unknown_paths"] == ["tools/owner.py"]


def test_governed_debt_does_not_mask_missing_attestation_or_tool_failure() -> None:
    product = "src/main/python/repomap_kg/owner.py"
    raw = _check_result(["tools/owner.py"], mypy_findings=[{"path": product}])
    raw["analyzed_paths"] = []
    result = attribute_product_dependencies(raw, [product])
    assert result["status"] == "failed"
    assert not derive_profile_path_facts(result)["evidence_complete"]
    raw["classification"] = "tool-failure"
    assert attribute_product_dependencies(raw, [product]) is raw


def test_malformed_finding_cannot_receive_ownership_credit() -> None:
    raw = _check_result(["tools/owner.py"])
    raw["checks"]["mypy"]["findings"] = [None]
    assert attribute_product_dependencies(raw, []) is raw
    assert not derive_profile_path_facts(raw)["evidence_complete"]


@pytest.mark.parametrize("missing_status", ["profile", "mypy"])
def test_missing_status_cannot_receive_ownership_credit(missing_status: str) -> None:
    product = "src/main/python/repomap_kg/owner.py"
    raw = _check_result(["tools/owner.py"], mypy_findings=[{"path": product}])
    target = raw if missing_status == "profile" else raw["checks"]["mypy"]
    del target["status"]
    assert attribute_product_dependencies(raw, [product]) is raw
    assert "governed_dependency_paths" not in raw["checks"]["mypy"]
    assert derive_profile_path_facts(raw)["unknown_paths"] == ["tools/owner.py"]


def test_incomplete_tool_run_does_not_claim_clean_paths() -> None:
    paths = ["tools/owner.py"]
    result = _check_result(paths, completed=False)

    facts = derive_profile_path_facts(result, paths)

    assert facts["profile_executed_paths"] == []
    assert facts["clean_under_profile"] == []
    assert facts["unknown_paths"] == sorted(paths)
    assert facts["tool_failure_paths"] == sorted(paths)
    assert facts["evidence_complete"] is False


def test_pass_without_path_attestation_is_unknown() -> None:
    path = "tools/owner.py"
    facts = derive_profile_path_facts({"status": "passed", "paths": [path]}, [path])

    assert facts["profile_executed_paths"] == []
    assert facts["clean_under_profile"] == []
    assert facts["unknown_paths"] == [path]
    assert facts["evidence_complete"] is False


def test_progress_preserves_effective_credit_and_separates_product_ratchet() -> None:
    product = "src/main/python/repomap_kg/owner.py"
    tool = "tools/owner.py"
    result = {
        "eligible": {"product": [product], "tools": [tool]},
        "assigned": {"product": [product], "tools": [tool]},
        "enforced": {"product": [product], "tools": []},
        "check_results": {
            "product": {
                "status": "passed",
                "classification": "passed",
                "checks": {
                    "retained_ratchet": {"status": "passed"},
                    "type_ownership": {"status": "passed"},
                },
            },
            "tools": _check_result([tool]),
        },
    }

    progress = build_profile_progress(result)

    assert progress["product"]["eligible"] == {"count": 1, "paths_ref": "eligible"}
    assert progress["product"]["assigned"] == {"count": 1, "paths_ref": "assigned"}
    assert progress["product"]["profile_executed"] == {"count": 0, "paths": []}
    assert progress["product"]["clean_under_profile"] == {"count": 0, "paths": []}
    assert progress["product"]["unknown"] == {"count": 1, "paths_ref": "assigned"}
    assert progress["product"]["effectively_enforced"] == {"count": 1, "paths_ref": "enforced"}
    assert progress["product"]["root_closure"] == {"closed": True, "status": "closed"}
    assert progress["tools"]["clean_under_profile"] == {"count": 1, "paths_ref": "assigned"}
    assert progress["tools"]["effectively_enforced"] == {"count": 0, "paths": []}
    assert progress["tools"]["root_closure"] == {"closed": False, "status": "open"}


def test_add_profile_progress_does_not_recompute_or_mutate_enforcement() -> None:
    tool = "tools/owner.py"
    result = {
        "enforced": {"tools": []},
        "eligible": {"tools": [tool]},
        "assigned": {"tools": [tool]},
        "check_results": {"tools": _check_result([tool])},
    }

    enriched = add_profile_progress(result)

    assert "profile_progress" in enriched
    assert enriched["enforced"] == {"tools": []}
    assert "profile_progress" not in result


def test_cohort_root_closure_requires_exact_eligible_and_complete_evidence() -> None:
    t1 = "tools/t1.py"
    t2 = "tools/t2.py"
    product = "src/main/python/repomap_kg/owner.py"
    check_result = _check_result([t1, t2], mypy_findings=[{"path": product, "dependency": True}])
    check_result["status"] = "failed"
    result = {
        "eligible": {"tools": [t1, t2]},
        "assigned": {"tools": [t1, t2]},
        "enforced": {"tools": [t1, t2], "product": [product]},
        "check_results": {"tools": check_result},
        "cohort_results": {
            "cohort-t1": {"status": "passed", "members": [t1], "root": "tools", "admission": "admitted",
                          "effective_enforcement": True, "evidence_complete": True},
            "cohort-t2": {"status": "passed", "members": [t2], "root": "tools", "admission": "admitted",
                          "effective_enforcement": True, "evidence_complete": True},
        },
    }
    progress = build_profile_progress(result)
    assert progress["tools"]["effectively_enforced"]["count"] == 2
    assert progress["tools"]["root_closure"] == {"closed": True, "status": "closed"}


def test_partial_cohort_credit_never_closes_root() -> None:
    t1 = "tools/t1.py"
    t2 = "tools/t2.py"
    result = {
        "eligible": {"tools": [t1, t2]},
        "assigned": {"tools": [t1, t2]},
        "enforced": {"tools": [t1]},
        "cohort_results": {
            "cohort-t1": {"status": "passed", "members": [t1], "root": "tools", "admission": "admitted",
                          "effective_enforcement": True, "evidence_complete": True},
            "cohort-t2": {"status": "failed", "members": [t2], "root": "tools", "admission": "admitted",
                          "effective_enforcement": True, "evidence_complete": True},
        },
    }
    progress = build_profile_progress(result)
    assert progress["tools"]["effectively_enforced"]["count"] == 1
    assert progress["tools"]["root_closure"] == {"closed": False, "status": "open"}


def test_cohort_root_closure_fails_on_direct_findings_or_regressions() -> None:
    t1 = "tools/t1.py"
    check_res = _check_result([t1], ruff_findings=[{"path": t1, "message": "error"}])
    result_direct = {
        "eligible": {"tools": [t1]},
        "assigned": {"tools": [t1]},
        "enforced": {"tools": []},
        "check_results": {"tools": check_res},
        "cohort_results": {
            "cohort-t1": {"status": "passed", "members": [t1], "root": "tools", "admission": "admitted",
                          "effective_enforcement": True, "evidence_complete": True},
        },
    }
    assert build_profile_progress(result_direct)["tools"]["root_closure"]["closed"] is False

    result_reg = {
        "eligible": {"tools": [t1]},
        "assigned": {"tools": [t1]},
        "enforced": {"tools": []},
        "cohort_results": {
            "cohort-t1": {"status": "passed", "members": [t1], "root": "tools", "admission": "admitted",
                          "effective_enforcement": True, "evidence_complete": True},
        },
        "cohort_regressions": ["cohort-t1"],
    }
    assert build_profile_progress(result_reg)["tools"]["root_closure"]["closed"] is False
