"""Focused unit tests for REVISE27 atomic SCC evaluation and controls."""

from __future__ import annotations

import copy
import itertools
import hashlib
import json
from pathlib import Path
from typing import Any
import pytest

from ci.python_retention_atomic import (
    canonical_scc_id,
    compute_internal_dependencies,
)
from ci.python_retention_cohort_evidence import evaluate_cohorts


def _make_tree(tmp_path: Path, files: dict[str, str]) -> list[str]:
    for rel_path, content in files.items():
        full = tmp_path / rel_path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
    return sorted(files)


def _make_check(
    paths: list[str],
    *,
    status: str = "passed",
    ruff_findings: list[dict[str, Any]] | None = None,
    mypy_findings: list[dict[str, Any]] | None = None,
    file_length_findings: list[dict[str, Any]] | None = None,
    analyzed_paths: list[str] | None = None,
    completed: bool = True,
    classification: str | None = None,
    tool_failure: str | None = None,
) -> dict[str, Any]:
    rf = ruff_findings or []
    mf = mypy_findings or []
    flf = file_length_findings or []
    checks = {
        "ruff": {"status": "failed" if rf else "passed", "findings": rf, "completed": completed},
        "mypy": {"status": "failed" if mf else "passed", "findings": mf, "completed": completed},
        "file_length": {"status": "failed" if flf else "passed", "findings": flf, "completed": completed},
    }
    res: dict[str, Any] = {
        "status": status,
        "paths": paths,
        "analyzed_paths": paths if analyzed_paths is None else analyzed_paths,
        "checks": checks,
    }
    if classification:
        res["classification"] = classification
    if tool_failure:
        res["tool_failure"] = tool_failure
    return res


def test_deterministic_scc_id_and_commitment_hashing() -> None:
    cids = ["cohort_b", "cohort_a"]
    scc_id = canonical_scc_id(cids)
    expected_compact = json.dumps(["cohort_a", "cohort_b"], separators=(",", ":"))
    expected_digest = hashlib.sha256(expected_compact.encode("utf-8")).hexdigest()
    assert scc_id == f"scc-v1-{expected_digest}"
    assert canonical_scc_id(["cohort_a", "cohort_b"]) == scc_id

    paths = {"tools/a.py", "tools/b.py"}
    graph_deps = {"tools/a.py": ["tools/b.py"], "tools/b.py": ["tools/a.py"]}
    count, sha = compute_internal_dependencies(paths, graph_deps)
    assert count == 2
    expected_edges = [["tools/a.py", "tools/b.py"], ["tools/b.py", "tools/a.py"]]
    expected_edges_sha = hashlib.sha256(
        json.dumps(expected_edges, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert sha == expected_edges_sha


def test_two_cohort_cycle_passes_and_enforces_atomically(tmp_path: Path) -> None:
    c_paths = _make_tree(tmp_path, {
        "tools/a.py": "from b import y\nx = 1\n",
        "tools/b.py": "from a import x\ny = 2\n",
    })
    cohorts = [
        {"id": "c_a", "root": "tools", "governing_profile": "clean_tooling",
         "members": ["tools/a.py"], "rationale": "a", "admission": "admitted"},
        {"id": "c_b", "root": "tools", "governing_profile": "clean_tooling",
         "members": ["tools/b.py"], "rationale": "b", "admission": "admitted"},
    ]
    checks = {"tools": _make_check(["tools/a.py", "tools/b.py"])}
    res = evaluate_cohorts(cohorts, checks, tmp_path, c_paths, [])

    assert res["cohort_results"]["c_a"]["status"] == "passed"
    assert res["cohort_results"]["c_b"]["status"] == "passed"
    assert res["cohort_results"]["c_a"]["effective_enforcement"] is True
    assert res["cohort_results"]["c_b"]["effective_enforcement"] is True
    assert res["enforced"]["tools"] == c_paths
    assert res["regressions"] == []

    gid = canonical_scc_id(["c_a", "c_b"])
    assert res["cohort_results"]["c_a"]["atomic_group_id"] == gid
    assert res["cohort_results"]["c_b"]["atomic_group_id"] == gid
    assert gid in res["atomic_groups"]
    group = res["atomic_groups"][gid]
    assert group["id"] == gid
    assert group["cohort_ids"] == ["c_a", "c_b"]
    assert group["root"] == "tools"
    assert group["governing_profile"] == "clean_tooling"
    assert group["internal_dependency_count"] == 2
    assert group["external_dependencies"] == []
    assert group["ungoverned_dependencies"] == []
    assert group["dependency_blockers"] == []
    assert group["status"] == "passed"
    assert group["effective_enforcement"] is True


def test_all_pending_clean_group_passes_not_effective(tmp_path: Path) -> None:
    c_paths = _make_tree(tmp_path, {
        "tools/p1.py": "from p2 import y\nx = 1\n",
        "tools/p2.py": "from p1 import x\ny = 2\n",
    })
    cohorts = [
        {"id": "c_p1", "root": "tools", "governing_profile": "clean_tooling",
         "members": ["tools/p1.py"], "rationale": "p1", "admission": "pending"},
        {"id": "c_p2", "root": "tools", "governing_profile": "clean_tooling",
         "members": ["tools/p2.py"], "rationale": "p2", "admission": "pending"},
    ]
    checks = {"tools": _make_check(["tools/p1.py", "tools/p2.py"])}
    res = evaluate_cohorts(cohorts, checks, tmp_path, c_paths, [])

    assert res["cohort_results"]["c_p1"]["status"] == "passed"
    assert res["cohort_results"]["c_p2"]["status"] == "passed"
    assert res["cohort_results"]["c_p1"]["effective_enforcement"] is False
    assert res["cohort_results"]["c_p2"]["effective_enforcement"] is False
    assert res["cohort_results"]["c_p1"]["governed_dependencies"] == []
    assert res["cohort_results"]["c_p2"]["governed_dependencies"] == []
    assert res["enforced"]["tools"] == []
    assert res["regressions"] == []

    gid = canonical_scc_id(["c_p1", "c_p2"])
    group = res["atomic_groups"][gid]
    assert group["status"] == "passed"
    assert group["effective_enforcement"] is False


def test_mixed_pending_admitted_group_fails_with_named_pending_ids(tmp_path: Path) -> None:
    c_paths = _make_tree(tmp_path, {
        "tools/admitted.py": "from pending_mod import y\nx = 1\n",
        "tools/pending_mod.py": "from admitted import x\ny = 2\n",
    })
    cohorts = [
        {"id": "c_adm", "root": "tools", "governing_profile": "clean_tooling",
         "members": ["tools/admitted.py"], "rationale": "adm", "admission": "admitted"},
        {"id": "c_pen", "root": "tools", "governing_profile": "clean_tooling",
         "members": ["tools/pending_mod.py"], "rationale": "pen", "admission": "pending"},
    ]
    checks = {"tools": _make_check(["tools/admitted.py", "tools/pending_mod.py"])}
    res = evaluate_cohorts(cohorts, checks, tmp_path, c_paths, [])

    assert res["cohort_results"]["c_adm"]["status"] == "failed"
    assert res["cohort_results"]["c_pen"]["status"] == "failed"
    assert res["regressions"] == ["c_adm"]
    assert "c_pen" not in res["regressions"]

    gid = canonical_scc_id(["c_adm", "c_pen"])
    group = res["atomic_groups"][gid]
    assert group["status"] == "failed"
    assert group["effective_enforcement"] is False
    assert any("c_pen" in b for b in group["dependency_blockers"])


@pytest.mark.parametrize("order", list(itertools.permutations(range(3))))
@pytest.mark.parametrize("checker", ["ruff", "mypy", "file_length"])
def test_three_cohort_cycle_clean_and_failing(tmp_path: Path, order: tuple[int, ...], checker: str) -> None:
    c_paths = _make_tree(tmp_path, {
        "tools/t1.py": "from t2 import y\nx = 1\n",
        "tools/t2.py": "from t3 import z\ny = 2\n",
        "tools/t3.py": "from t1 import x\nz = 3\n",
    })
    cohorts = [
        {"id": "c_t1", "root": "tools", "governing_profile": "clean_tooling",
         "members": ["tools/t1.py"], "rationale": "t1", "admission": "admitted"},
        {"id": "c_t2", "root": "tools", "governing_profile": "clean_tooling",
         "members": ["tools/t2.py"], "rationale": "t2", "admission": "admitted"},
        {"id": "c_t3", "root": "tools", "governing_profile": "clean_tooling",
         "members": ["tools/t3.py"], "rationale": "t3", "admission": "admitted"},
    ]
    cohorts = [cohorts[i] for i in order]
    original = copy.deepcopy(cohorts)
    checks_clean = {"tools": _make_check(c_paths)}
    res_clean = evaluate_cohorts(cohorts, checks_clean, tmp_path, c_paths, [])
    assert res_clean["enforced"]["tools"] == c_paths
    assert res_clean["regressions"] == []
    assert cohorts == original
    gid = canonical_scc_id(["c_t1", "c_t2", "c_t3"])
    assert res_clean["atomic_groups"][gid]["internal_dependency_count"] == 3

    checks_failing = copy.deepcopy(checks_clean)
    checks_failing["tools"]["checks"][checker]["findings"] = [
        {"path": "tools/t2.py", "code": "finding", "message": "direct debt"}
    ]
    res_failing = evaluate_cohorts(cohorts, checks_failing, tmp_path, c_paths, [])
    assert res_failing["enforced"]["tools"] == []
    assert sorted(res_failing["regressions"]) == ["c_t1", "c_t2", "c_t3"]
    assert any("c_t2" in b for b in res_failing["atomic_groups"][gid]["dependency_blockers"])


def test_fixed_point_ordering_group_and_singleton(tmp_path: Path) -> None:
    c_paths = _make_tree(tmp_path, {
        "tools/base.py": "val = 42\n",
        "tools/a.py": "from b import y\nfrom base import val\nx = 1\n",
        "tools/b.py": "from a import x\ny = 2\n",
        "tools/top.py": "from a import x\ntop_val = 100\n",
    })
    cohorts = [
        {"id": "c_base", "root": "tools", "governing_profile": "clean_tooling",
         "members": ["tools/base.py"], "rationale": "base", "admission": "admitted"},
        {"id": "c_a", "root": "tools", "governing_profile": "clean_tooling",
         "members": ["tools/a.py"], "rationale": "a", "admission": "admitted"},
        {"id": "c_b", "root": "tools", "governing_profile": "clean_tooling",
         "members": ["tools/b.py"], "rationale": "b", "admission": "admitted"},
        {"id": "c_top", "root": "tools", "governing_profile": "clean_tooling",
         "members": ["tools/top.py"], "rationale": "top", "admission": "admitted"},
    ]
    checks = {"tools": _make_check(c_paths)}
    res = evaluate_cohorts(cohorts, checks, tmp_path, c_paths, [])
    assert res["enforced"]["tools"] == c_paths
    assert res["regressions"] == []
    assert "atomic_group_id" not in res["cohort_results"]["c_base"]
    assert "atomic_group_id" not in res["cohort_results"]["c_top"]


def test_all_pending_group_does_not_lend_governance_to_downstream(tmp_path: Path) -> None:
    c_paths = _make_tree(tmp_path, {
        "tools/p1.py": "from p2 import y\nx = 1\n",
        "tools/p2.py": "from p1 import x\ny = 2\n",
        "tools/down.py": "from p1 import x\n",
    })
    cohorts = [
        {"id": "c_p1", "root": "tools", "governing_profile": "clean_tooling",
         "members": ["tools/p1.py"], "rationale": "p1", "admission": "pending"},
        {"id": "c_p2", "root": "tools", "governing_profile": "clean_tooling",
         "members": ["tools/p2.py"], "rationale": "p2", "admission": "pending"},
        {"id": "c_down", "root": "tools", "governing_profile": "clean_tooling",
         "members": ["tools/down.py"], "rationale": "down", "admission": "admitted"},
    ]
    checks = {"tools": _make_check(c_paths)}
    res = evaluate_cohorts(cohorts, checks, tmp_path, c_paths, [])
    assert res["cohort_results"]["c_p1"]["status"] == "passed"
    assert res["cohort_results"]["c_p2"]["status"] == "passed"
    assert res["cohort_results"]["c_down"]["status"] == "failed"
    assert res["regressions"] == ["c_down"]


@pytest.mark.parametrize("source,reason", [
    ("import importlib\nm = importlib.import_module('x')\n", "dynamic import"),
    ("import no_such_first_party_owner\nm = 1\n", "unresolved imports"),
    ("m = 1\n" + "# length\n" * 400, "physical length"),
])
def test_import_uncertainty_and_file_length_in_group(tmp_path: Path, source: str, reason: str) -> None:
    c_paths = _make_tree(tmp_path, {
        "tools/dyn.py": "from other import y\n" + source,
        "tools/other.py": "from dyn import m\ny = 1\n",
    })
    cohorts = [
        {"id": "c_dyn", "root": "tools", "governing_profile": "clean_tooling",
         "members": ["tools/dyn.py"], "rationale": "dyn", "admission": "admitted"},
        {"id": "c_oth", "root": "tools", "governing_profile": "clean_tooling",
         "members": ["tools/other.py"], "rationale": "oth", "admission": "admitted"},
    ]
    checks = {"tools": _make_check(c_paths)}
    res = evaluate_cohorts(cohorts, checks, tmp_path, c_paths, [])
    assert res["cohort_results"]["c_dyn"]["status"] == "failed"
    assert res["cohort_results"]["c_oth"]["status"] == "failed"
    gid = canonical_scc_id(["c_dyn", "c_oth"])
    assert any(reason in b for b in res["atomic_groups"][gid]["dependency_blockers"])


def test_cross_root_cycle_refused(tmp_path: Path) -> None:
    c_paths = _make_tree(tmp_path, {
        "tools/tool.py": "from repomap_test_support.supp import y\nx = 1\n",
        "src/test/support/python/repomap_test_support/supp.py": "from tools.tool import x\ny = 2\n",
    })
    cohorts = [
        {"id": "c_tl", "root": "tools", "governing_profile": "clean_tooling",
         "members": ["tools/tool.py"], "rationale": "tl", "admission": "admitted"},
        {"id": "c_sp", "root": "test_support", "governing_profile": "clean_test_support",
         "members": ["src/test/support/python/repomap_test_support/supp.py"], "rationale": "sp", "admission": "admitted"},
    ]
    checks = {
        "tools": _make_check(["tools/tool.py"]),
        "test_support": _make_check(["src/test/support/python/repomap_test_support/supp.py"]),
    }
    res = evaluate_cohorts(cohorts, checks, tmp_path, c_paths, [])
    assert res["cohort_results"]["c_tl"]["status"] == "failed"
    assert res["cohort_results"]["c_sp"]["status"] == "failed"
    assert sorted(res["regressions"]) == ["c_sp", "c_tl"]
    gid = canonical_scc_id(["c_sp", "c_tl"])
    group = res["atomic_groups"][gid]
    assert group["root"] is None
    assert group["governing_profile"] is None
    assert any("cross-root" in b for b in group["dependency_blockers"])


def test_external_dependency_product_seed_governed(tmp_path: Path) -> None:
    c_paths = _make_tree(tmp_path, {
        "src/main/python/repomap_kg/prod.py": "prod_val = 1\n",
        "tools/a.py": "from b import y\nfrom repomap_kg.prod import prod_val\nx = 1\n",
        "tools/b.py": "from a import x\ny = 2\n",
    })
    cohorts = [
        {"id": "c_a", "root": "tools", "governing_profile": "clean_tooling",
         "members": ["tools/a.py"], "rationale": "a", "admission": "admitted"},
        {"id": "c_b", "root": "tools", "governing_profile": "clean_tooling",
         "members": ["tools/b.py"], "rationale": "b", "admission": "admitted"},
    ]
    checks = {"tools": _make_check(["tools/a.py", "tools/b.py"])}

    # Without product seed: fails with unmet leaving dependencies
    res_no_seed = evaluate_cohorts(cohorts, checks, tmp_path, c_paths, [])
    assert res_no_seed["cohort_results"]["c_a"]["status"] == "failed"
    gid = canonical_scc_id(["c_a", "c_b"])
    assert "src/main/python/repomap_kg/prod.py" in res_no_seed["atomic_groups"][gid]["ungoverned_dependencies"]

    # With product seed: passes
    res_seeded = evaluate_cohorts(
        cohorts, checks, tmp_path, c_paths, ["src/main/python/repomap_kg/prod.py"]
    )
    assert res_seeded["cohort_results"]["c_a"]["status"] == "passed"
    assert res_seeded["cohort_results"]["c_b"]["status"] == "passed"
    assert res_seeded["atomic_groups"][gid]["status"] == "passed"

@pytest.mark.parametrize("failure", ["incomplete", "tool", "unknown", "stub"])
def test_atomic_group_keeps_check_failures(tmp_path: Path, failure: str) -> None:
    paths = _make_tree(tmp_path, {"tools/a.py": "import b\n", "tools/b.py": "import a\n"})
    cohorts = [dict(id=name, root="tools", governing_profile="clean_tooling",
                    members=[f"tools/{name}.py"], rationale=name, admission="admitted")
               for name in ("a", "b")]
    check = _make_check(paths)
    if failure == "incomplete":
        check["checks"]["mypy"]["completed"] = False
    elif failure == "tool":
        check["tool_failure"] = "checker unavailable"
    else:
        check["checks"]["mypy"]["findings"] = [{
            "path": "tools/a.py" if failure == "stub" else "unknown.py",
            "code": "import-untyped" if failure == "stub" else "arg-type",
        }]
    result = evaluate_cohorts(cohorts, {"tools": check}, tmp_path, paths, [])
    assert result["enforced"]["tools"] == []
    assert result["regressions"] == ["a", "b"]
    assert next(iter(result["atomic_groups"].values()))["dependency_blockers"]

def test_atomic_admission_preserves_transition_membership(tmp_path: Path) -> None:
    from ci.python_retention_cohorts import (
        COHORT_SCHEMA, HistoryValidationError, validate_cohort_transition,
    )
    paths = _make_tree(tmp_path, {"tools/a.py": "import b\n", "tools/b.py": "import a\n"})
    cohorts = [dict(id=name, root="tools", governing_profile="clean_tooling",
                    members=[f"tools/{name}.py"], rationale=name, admission="pending")
               for name in ("a", "b")]
    older: dict[str, Any] = dict(cohort_schema=COHORT_SCHEMA, cohorts=cohorts, files=[
        dict(path=p, root="tools", governing_profile="clean_tooling",
             confidence=0.95, maintained_executable=True, rationale="test")
        for p in paths])
    newer = copy.deepcopy(older)
    for c in newer["cohorts"]:
        c["admission"] = "admitted"
    validate_cohort_transition(older, newer)
    result = evaluate_cohorts(newer["cohorts"], {"tools": _make_check(paths)}, tmp_path, paths, [])
    assert result["enforced"]["tools"] == paths
    assert [c["members"] for c in older["cohorts"]] == [c["members"] for c in newer["cohorts"]]
    swapped = copy.deepcopy(newer)
    swapped["cohorts"][0]["members"], swapped["cohorts"][1]["members"] = (
        swapped["cohorts"][1]["members"], swapped["cohorts"][0]["members"])
    with pytest.raises(HistoryValidationError, match="cannot"):
        validate_cohort_transition(older, swapped)
