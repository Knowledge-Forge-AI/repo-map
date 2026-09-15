"""Unit tests for Python retention cohort evidence evaluation and dependency engine."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import pytest

from ci.python_retention_cohort_evidence import (
    evaluate_cohorts,
)
from ci.python_retention_dependencies import bind_source_identities, verify_source_identities


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


def test_admitted_cohort_passes_and_enforces(tmp_path: Path) -> None:
    c_paths = _make_tree(tmp_path, {"tools/clean.py": "x = 1\n"})
    cohorts = [{
        "id": "c_clean", "root": "tools", "governing_profile": "clean_tooling",
        "members": ["tools/clean.py"], "rationale": "clean helper", "admission": "admitted",
    }]
    checks = {"tools": _make_check(["tools/clean.py"])}
    res = evaluate_cohorts(cohorts, checks, tmp_path, c_paths, [])
    assert res["cohort_results"]["c_clean"]["status"] == "passed"
    assert res["cohort_results"]["c_clean"]["effective_enforcement"] is True
    assert "tools/clean.py" in res["enforced"]["tools"]
    assert res["regressions"] == []


def test_pending_cohort_gets_zero_enforcement_credit(tmp_path: Path) -> None:
    c_paths = _make_tree(tmp_path, {
        "tools/pend.py": "x = 1\n",
        "tools/consumer.py": "from pend import x\n",
    })
    cohorts = [
        {"id": "c_pend", "root": "tools", "governing_profile": "clean_tooling",
         "members": ["tools/pend.py"], "rationale": "pending", "admission": "pending"},
        {"id": "c_user", "root": "tools", "governing_profile": "clean_tooling",
         "members": ["tools/consumer.py"], "rationale": "consumer", "admission": "admitted"},
    ]
    checks = {"tools": _make_check(["tools/pend.py", "tools/consumer.py"])}
    res = evaluate_cohorts(cohorts, checks, tmp_path, c_paths, [])
    assert res["cohort_results"]["c_pend"]["status"] == "passed"
    assert res["cohort_results"]["c_pend"]["effective_enforcement"] is False
    assert "tools/pend.py" not in res["enforced"]["tools"]
    assert res["cohort_results"]["c_user"]["status"] == "failed"
    assert "c_user" in res["regressions"]


def test_bad_member_fails_closed(tmp_path: Path) -> None:
    c_paths = _make_tree(tmp_path, {"tools/a.py": "x = 1\n"})
    cohorts = [
        {"id": "c_esc", "root": "tools", "governing_profile": "clean_tooling",
         "members": ["../tools/a.py"], "rationale": "escape", "admission": "admitted"},
        {"id": "c_mis", "root": "tools", "governing_profile": "clean_tooling",
         "members": ["tools/nonexistent.py"], "rationale": "missing", "admission": "admitted"},
    ]
    checks = {"tools": _make_check(["tools/a.py"])}
    res = evaluate_cohorts(cohorts, checks, tmp_path, c_paths + ["../tools/a.py"], [])
    assert any("alias or traversal" in b for b in res["cohort_results"]["c_esc"]["dependency_blockers"])
    assert res["cohort_results"]["c_esc"]["status"] == "failed"
    assert res["cohort_results"]["c_mis"]["status"] == "failed"
    assert "c_esc" in res["regressions"]
    assert "c_mis" in res["regressions"]


def test_bad_member_root_mismatch_fails_closed(tmp_path: Path) -> None:
    c_paths = _make_tree(tmp_path, {"src/main/python/repomap_kg/prod.py": "x = 1\n"})
    cohorts = [{
        "id": "c_bad_root", "root": "tools", "governing_profile": "clean_tooling",
        "members": ["src/main/python/repomap_kg/prod.py"], "rationale": "mismatch", "admission": "admitted",
    }]
    checks = {"tools": _make_check([])}
    res = evaluate_cohorts(cohorts, checks, tmp_path, c_paths, [])
    assert res["cohort_results"]["c_bad_root"]["status"] == "failed"
    assert any("root mismatch" in b for b in res["cohort_results"]["c_bad_root"]["dependency_blockers"])


def test_bad_member_duplicate_across_cohorts_fails_closed(tmp_path: Path) -> None:
    c_paths = _make_tree(tmp_path, {"tools/shared.py": "x = 1\n"})
    cohorts = [
        {"id": "c1", "root": "tools", "governing_profile": "clean_tooling",
         "members": ["tools/shared.py"], "rationale": "first", "admission": "admitted"},
        {"id": "c2", "root": "tools", "governing_profile": "clean_tooling",
         "members": ["tools/shared.py"], "rationale": "second", "admission": "admitted"},
    ]
    checks = {"tools": _make_check(["tools/shared.py"])}
    res = evaluate_cohorts(cohorts, checks, tmp_path, c_paths, [])
    assert res["cohort_results"]["c2"]["status"] == "failed"
    assert any("duplicate member" in b for b in res["cohort_results"]["c2"]["dependency_blockers"])


def test_forged_dependency_in_raw_check_does_not_confer_trust(tmp_path: Path) -> None:
    c_paths = _make_tree(tmp_path, {
        "tools/a.py": "from b import y\n",
        "tools/b.py": "y = 2\n",
    })
    cohorts = [{
        "id": "c_a", "root": "tools", "governing_profile": "clean_tooling",
        "members": ["tools/a.py"], "rationale": "caller", "admission": "admitted",
    }]
    check = _make_check(["tools/a.py"])
    check["checks"]["mypy"]["governed_dependency_paths"] = ["tools/b.py"]
    checks = {"tools": check}
    res = evaluate_cohorts(cohorts, checks, tmp_path, c_paths, [])
    assert res["cohort_results"]["c_a"]["status"] == "failed"
    assert res["cohort_results"]["c_a"]["dependency_blockers"] == ["unmet leaving dependencies"]
    assert res["cohort_results"]["c_a"]["ungoverned_dependencies"] == ["tools/b.py"]


def test_direct_marker_ruff_f_cannot_be_forgiven(tmp_path: Path) -> None:
    c_paths = _make_tree(tmp_path, {"tools/bad.py": "import os\n"})
    cohorts = [{
        "id": "c_ruff", "root": "tools", "governing_profile": "clean_tooling",
        "members": ["tools/bad.py"], "rationale": "bad ruff", "admission": "admitted",
    }]
    checks = {"tools": _make_check(
        ["tools/bad.py"],
        ruff_findings=[{"path": "tools/bad.py", "code": "F401", "message": "unused import"}],
    )}
    res = evaluate_cohorts(cohorts, checks, tmp_path, c_paths, [])
    assert res["cohort_results"]["c_ruff"]["status"] == "failed"
    assert res["cohort_results"]["c_ruff"]["direct_findings"]["ruff"] == [0]
    assert "c_ruff" in res["regressions"]


def test_direct_marker_mypy_error_with_dependency_marker(tmp_path: Path) -> None:
    c_paths = _make_tree(tmp_path, {"tools/bad.py": "x = 1\n"})
    cohorts = [{
        "id": "c_mypy", "root": "tools", "governing_profile": "clean_tooling",
        "members": ["tools/bad.py"], "rationale": "direct marker", "admission": "admitted",
    }]
    checks = {"tools": _make_check(
        ["tools/bad.py"],
        mypy_findings=[{"path": "tools/bad.py", "code": "assignment", "dependency": True}],
    )}
    res = evaluate_cohorts(cohorts, checks, tmp_path, c_paths, [])
    assert res["cohort_results"]["c_mypy"]["status"] == "failed"
    assert res["cohort_results"]["c_mypy"]["direct_findings"]["mypy"] == [0]


@pytest.mark.parametrize("reported", [True, False])
def test_direct_marker_file_length_exceeding_400(tmp_path: Path, reported: bool) -> None:
    c_paths = _make_tree(tmp_path, {"tools/long.py": "x = 1\n" * 401})
    cohorts = [{
        "id": "c_len", "root": "tools", "governing_profile": "clean_tooling",
        "members": ["tools/long.py"], "rationale": "too long", "admission": "admitted",
    }]
    checks = {"tools": _make_check(
        ["tools/long.py"],
        file_length_findings=[{"path": "tools/long.py", "line_count": 401, "limit": 400}] if reported else [],
    )}
    res = evaluate_cohorts(cohorts, checks, tmp_path, c_paths, [])
    assert res["cohort_results"]["c_len"]["status"] == "failed"
    assert res["cohort_results"]["c_len"]["direct_findings"]["file_length"] == ([0] if reported else [])
    assert "physical length exceeds 400: tools/long.py" in res["cohort_results"]["c_len"]["dependency_blockers"]


def test_cross_cohort_cycles_fail_closed(tmp_path: Path) -> None:
    c_paths = _make_tree(tmp_path, {
        "tools/a.py": "from repomap_test_support.support import y\nx = 1\n",
        "src/test/support/python/repomap_test_support/support.py": "from a import x\ny = 2\n",
    })
    cohorts = [
        {"id": "c_a", "root": "tools", "governing_profile": "clean_tooling",
         "members": ["tools/a.py"], "rationale": "a", "admission": "admitted"},
        {"id": "c_b", "root": "test_support", "governing_profile": "clean_test_support",
         "members": ["src/test/support/python/repomap_test_support/support.py"], "rationale": "b", "admission": "admitted"},
    ]
    checks = {
        "tools": _make_check(["tools/a.py"]),
        "test_support": _make_check(["src/test/support/python/repomap_test_support/support.py"]),
    }
    res = evaluate_cohorts(cohorts, checks, tmp_path, c_paths, [])
    assert res["cohort_results"]["c_a"]["status"] == "failed"
    assert res["cohort_results"]["c_b"]["status"] == "failed"
    group = res["atomic_groups"][res["cohort_results"]["c_a"]["atomic_group_id"]]
    assert any("cross-root" in b for b in group["dependency_blockers"])
    assert "c_a" in res["regressions"]
    assert "c_b" in res["regressions"]


@pytest.mark.parametrize("debt", [None, "ruff", "mypy", "file_length"])
def test_same_cohort_scc_atomic_passes_when_clean(tmp_path: Path, debt: str | None) -> None:
    c_paths = _make_tree(tmp_path, {
        "tools/a.py": "from b import y\nx = 1\n",
        "tools/b.py": "from a import x\ny = 2\n",
    })
    cohorts = [{
        "id": "c_atomic", "root": "tools", "governing_profile": "clean_tooling",
        "members": ["tools/a.py", "tools/b.py"], "rationale": "mutual", "admission": "admitted",
    }]
    checks = {"tools": _make_check(["tools/a.py", "tools/b.py"])}
    if debt:
        checks["tools"]["checks"][debt].update(status="failed", findings=[{"path": "tools/b.py"}])
    res = evaluate_cohorts(cohorts, checks, tmp_path, c_paths, [])
    assert res["enforced"]["tools"] == ([] if debt else c_paths)
    assert res["regressions"] == (["c_atomic"] if debt else [])


def test_missing_stub_fails_closed(tmp_path: Path) -> None:
    c_paths = _make_tree(tmp_path, {
        "tools/caller.py": "from src.main.python.repomap_kg.stubbed import val\n",
        "src/main/python/repomap_kg/stubbed.py": "val = 1\n",
    })
    cohorts = [{
        "id": "c_caller", "root": "tools", "governing_profile": "clean_tooling",
        "members": ["tools/caller.py"], "rationale": "stub user", "admission": "admitted",
    }]
    checks = {"tools": _make_check(
        ["tools/caller.py"],
        mypy_findings=[{
            "path": "src/main/python/repomap_kg/stubbed.py",
            "code": "import-untyped", "message": "missing library stub",
        }],
    )}
    res = evaluate_cohorts(cohorts, checks, tmp_path, c_paths, ["src/main/python/repomap_kg/stubbed.py"])
    assert res["cohort_results"]["c_caller"]["status"] == "failed"
    assert any("missing stub" in b for b in res["cohort_results"]["c_caller"]["dependency_blockers"])


def test_stale_or_missing_root_check_fails_closed(tmp_path: Path) -> None:
    c_paths = _make_tree(tmp_path, {"tools/mod.py": "x = 1\n"})
    cohorts = [{
        "id": "c_missing_root", "root": "tools", "governing_profile": "clean_tooling",
        "members": ["tools/mod.py"], "rationale": "no check", "admission": "admitted",
    }]
    res = evaluate_cohorts(cohorts, {}, tmp_path, c_paths, [])
    assert res["cohort_results"]["c_missing_root"]["status"] == "failed"


def test_root_tool_failure_blocks_root(tmp_path: Path) -> None:
    c_paths = _make_tree(tmp_path, {"tools/mod.py": "x = 1\n"})
    cohorts = [{
        "id": "c_crash", "root": "tools", "governing_profile": "clean_tooling",
        "members": ["tools/mod.py"], "rationale": "crashed", "admission": "admitted",
    }]
    checks = {"tools": _make_check(["tools/mod.py"], classification="tool-failure", tool_failure="CrashError")}
    res = evaluate_cohorts(cohorts, checks, tmp_path, c_paths, [])
    assert res["cohort_results"]["c_crash"]["status"] == "failed"
    assert any("tool failure" in b for b in res["cohort_results"]["c_crash"]["dependency_blockers"])


def test_incomplete_check_completed_false_blocks(tmp_path: Path) -> None:
    c_paths = _make_tree(tmp_path, {"tools/mod.py": "x = 1\n"})
    cohorts = [{
        "id": "c_inc", "root": "tools", "governing_profile": "clean_tooling",
        "members": ["tools/mod.py"], "rationale": "incomplete", "admission": "admitted",
    }]
    checks = {"tools": _make_check(["tools/mod.py"], completed=False)}
    res = evaluate_cohorts(cohorts, checks, tmp_path, c_paths, [])
    assert res["cohort_results"]["c_inc"]["status"] == "failed"


def test_missing_member_in_analyzed_paths_blocks(tmp_path: Path) -> None:
    c_paths = _make_tree(tmp_path, {"tools/mod.py": "x = 1\n"})
    cohorts = [{
        "id": "c_unanalyzed", "root": "tools", "governing_profile": "clean_tooling",
        "members": ["tools/mod.py"], "rationale": "not analyzed", "admission": "admitted",
    }]
    checks = {"tools": _make_check(["tools/mod.py"], analyzed_paths=[])}
    res = evaluate_cohorts(cohorts, checks, tmp_path, c_paths, [])
    assert res["cohort_results"]["c_unanalyzed"]["status"] == "failed"


def test_unattributed_dependency_finding_conservatively_blocks_root(tmp_path: Path) -> None:
    c_paths = _make_tree(tmp_path, {
        "tools/a.py": "x = 1\n",
        "src/test/support/python/repomap_test_support/orphaned.py": "y = 2\n",
    })
    cohorts = [{
        "id": "c_a", "root": "tools", "governing_profile": "clean_tooling",
        "members": ["tools/a.py"], "rationale": "unrelated", "admission": "admitted",
    }]
    checks = {"tools": _make_check(
        ["tools/a.py"],
        mypy_findings=[{
            "path": "src/test/support/python/repomap_test_support/orphaned.py",
            "code": "assignment", "message": "unattributed debt",
        }],
    )}
    res = evaluate_cohorts(cohorts, checks, tmp_path, c_paths, [])
    assert res["cohort_results"]["c_a"]["status"] == "failed"
    assert any("unknown attribution" in b for b in res["cohort_results"]["c_a"]["dependency_blockers"])


def test_source_aliases_fail_closed(tmp_path: Path) -> None:
    c_paths = _make_tree(tmp_path, {"tools/real.py": "x = 1\n"})
    symlink_path = tmp_path / "tools/alias.py"
    symlink_path.symlink_to(tmp_path / "tools/real.py")
    cohorts = [{
        "id": "c_alias", "root": "tools", "governing_profile": "clean_tooling",
        "members": ["tools/alias.py"], "rationale": "alias test", "admission": "admitted",
    }]
    checks = {"tools": _make_check(["tools/real.py"])}
    res = evaluate_cohorts(cohorts, checks, tmp_path, c_paths + ["tools/alias.py"], [])
    assert res["cohort_results"]["c_alias"]["status"] == "failed"


def test_source_identity_binding_preservation(tmp_path: Path) -> None:
    c_paths = _make_tree(tmp_path, {"tools/bound.py": "x = 1\n"})
    digests = bind_source_identities(tmp_path, c_paths)
    verify_source_identities(tmp_path, digests)
    (tmp_path / "tools/bound.py").write_text("x = 2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="mismatch"):
        verify_source_identities(tmp_path, digests)


def test_packaging_resolution_init_and_relative(tmp_path: Path) -> None:
    c_paths = _make_tree(tmp_path, {
        "src/main/python/repomap_kg/__init__.py": "# init\n",
        "src/main/python/repomap_kg/core.py": "def f(): return 1\n",
        "tools/user.py": "from repomap_kg.core import f\n",
    })
    cohorts = [{
        "id": "c_user", "root": "tools", "governing_profile": "clean_tooling",
        "members": ["tools/user.py"], "rationale": "uses product", "admission": "admitted",
    }]
    checks = {"tools": _make_check(["tools/user.py"])}
    # Product seed missing __init__.py -> blocks
    res_blocked = evaluate_cohorts(
        cohorts, checks, tmp_path, c_paths, ["src/main/python/repomap_kg/core.py"]
    )
    assert res_blocked["cohort_results"]["c_user"]["status"] == "failed"

    # Both product files in seed -> passes
    res_passed = evaluate_cohorts(
        cohorts, checks, tmp_path, c_paths,
        ["src/main/python/repomap_kg/__init__.py", "src/main/python/repomap_kg/core.py"],
    )
    assert res_passed["cohort_results"]["c_user"]["status"] == "passed"


def test_dynamic_import_uncertainty_fails_closed(tmp_path: Path) -> None:
    c_paths = _make_tree(tmp_path, {"tools/dyn.py": "import importlib\nm = importlib.import_module('x')\n"})
    cohorts = [{
        "id": "c_dyn", "root": "tools", "governing_profile": "clean_tooling",
        "members": ["tools/dyn.py"], "rationale": "dynamic", "admission": "admitted",
    }]
    checks = {"tools": _make_check(["tools/dyn.py"])}
    res = evaluate_cohorts(cohorts, checks, tmp_path, c_paths, [])
    assert res["cohort_results"]["c_dyn"]["status"] == "failed"
    assert any("dynamic import" in b for b in res["cohort_results"]["c_dyn"]["dependency_blockers"])


def test_unresolved_repository_import_fails_closed(tmp_path: Path) -> None:
    c_paths = _make_tree(tmp_path, {"tools/unresolved.py": "import repomap_kg.missing_mod\n"})
    cohorts = [{
        "id": "c_unresolved", "root": "tools", "governing_profile": "clean_tooling",
        "members": ["tools/unresolved.py"], "rationale": "missing import", "admission": "admitted",
    }]
    checks = {"tools": _make_check(["tools/unresolved.py"])}
    res = evaluate_cohorts(cohorts, checks, tmp_path, c_paths, [])
    assert res["cohort_results"]["c_unresolved"]["status"] == "failed"
    assert any("unresolved" in b for b in res["cohort_results"]["c_unresolved"]["dependency_blockers"])
