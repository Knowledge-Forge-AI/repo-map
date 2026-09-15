"""Negative controls for same-run ownership and reporting authority."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import json

import pytest

from ci.python_retention_cohort_evidence import evaluate_cohorts
from ci.python_retention_cohort_checks import compact_cohort_records
from ci.python_retention_dependencies import build_dependency_graph
from ci.python_retention_reporting import build_profile_progress
from ci.pre_review_evaluation import evaluate
from ci.pre_review_records import Check
from ci import python_retention_inventory as inventory
from repomap_test_support.retention_pipeline_fixture import (
    retention_candidate as retention_candidate, candidate_context,
)


def cohort(path: str, root: str = "tools", admission: str = "admitted") -> dict[str, Any]:
    return dict(id=path, root=root, admission=admission, members=[path],
                rationale="Synthetic responsibility owner", governing_profile={
                    "tools": "clean_tooling", "test_support": "clean_test_support",
                }[root])


def checked(paths: list[str]) -> dict[str, Any]:
    return dict(status="passed", paths=paths, analyzed_paths=paths, checks={
        name: dict(status="passed", completed=True, findings=[])
        for name in ("ruff", "mypy", "file_length")
    })


def tree(root: Path, files: dict[str, str]) -> list[str]:
    for name, source in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
    return sorted(files)


@pytest.mark.parametrize("admission", ["pending", "admitted"])
def test_nonproduct_dependency_requires_its_own_same_run_pass(tmp_path: Path, admission: str) -> None:
    caller = "tools/caller.py"
    support = "src/test/support/python/support.py"
    paths = tree(tmp_path, {caller: "from support import value\n", support: "value = 1\n"})
    checks = {"tools": checked([caller]), "test_support": checked([support])}
    checks["tools"]["checks"]["mypy"].update(status="failed", findings=[{
        "path": support, "code": "assignment", "dependency": True,
    }])
    result = evaluate_cohorts([cohort(caller), cohort(support, "test_support", admission)],
                              checks, tmp_path, paths, [])
    assert result["enforced"]["tools"] == ([caller] if admission == "admitted" else [])
    assert checks["tools"]["checks"]["mypy"]["findings"][0]["path"] == support


@pytest.mark.parametrize("name", ["ruff", "mypy", "file_length"])
@pytest.mark.parametrize("finding", [None, {}, {"path": ""}, {"path": []}, {"path": "tools/owner.py", "code": []}])
def test_malformed_finding_never_means_zero_debt(tmp_path: Path, name: str, finding: Any) -> None:
    path = "tools/owner.py"
    paths = tree(tmp_path, {path: "value = 1\n"})
    check = checked(paths)
    check["checks"][name]["findings"] = [finding]
    result = evaluate_cohorts([cohort(path)], {"tools": check}, tmp_path, paths, [])
    assert result["enforced"]["tools"] == []
    assert result["regressions"] == [path]


def test_wrong_length_profile_cannot_admit(tmp_path: Path) -> None:
    path = "tools/owner.py"
    paths = tree(tmp_path, {path: "value = 1\n"})
    check = checked(paths)
    check["checks"]["file_length"]["limit"] = 1000
    assert not evaluate_cohorts([cohort(path)], {"tools": check}, tmp_path, paths, [])["enforced"]["tools"]


def test_dependency_cycle_cannot_use_raw_governance_claims(tmp_path: Path) -> None:
    paths = tree(tmp_path, {
        "tools/a.py": "import b\nimport external\n",
        "tools/b.py": "import a\n",
        "tools/external.py": "x = 1\n",
    })
    check = checked(["tools/a.py", "tools/b.py"])
    check["checks"]["mypy"]["governed_dependency_paths"] = ["tools/external.py"]
    cohort_paths = ["tools/a.py", "tools/b.py"]
    result = evaluate_cohorts([cohort(p) for p in cohort_paths], {"tools": check}, tmp_path, paths, [])
    assert result["enforced"]["tools"] == []
    assert len(result["regressions"]) == 2


def test_pending_pass_cannot_inflate_reported_effective_count() -> None:
    path = "tools/pending.py"
    record = dict(cohort(path, admission="pending"), status="passed", evidence_complete=True,
                  effective_enforcement=False)
    result = dict(eligible={"tools": [path]}, assigned={"tools": [path]}, enforced={"tools": []},
                  check_results={"tools": checked([path])}, cohort_results={path: record})
    progress = build_profile_progress(result)["tools"]
    assert progress["effectively_enforced"]["count"] == 0
    assert progress["root_closure"]["closed"] is False


def test_identical_bytes_with_ambiguous_import_identity_do_not_select_one_owner(tmp_path: Path) -> None:
    paths = tree(tmp_path, {"tools/collision.py": "value = 1\n",
                           "src/test/support/python/collision.py": "value = 1\n",
                           "tools/caller.py": "import collision\n"})
    graph = build_dependency_graph(tmp_path, paths)
    assert graph["unresolved_imports"]["tools/caller.py"] == ["collision"]


def test_missing_child_does_not_resolve_to_existing_parent(tmp_path: Path) -> None:
    paths = tree(tmp_path, {"tools/pkg/__init__.py": "", "tools/caller.py": "import pkg.missing\n"})
    assert build_dependency_graph(tmp_path, paths)["unresolved_imports"]["tools/caller.py"] == ["pkg.missing"]


def test_regex_compilation_is_not_dynamic_import(tmp_path: Path) -> None:
    paths = tree(tmp_path, {"tools/parser.py": "import re\nPATTERN = re.compile('x')\n"})
    assert not build_dependency_graph(tmp_path, paths)["dynamic_uncertainty"]


def test_omitted_regression_summary_cannot_hide_failed_admitted_cohort() -> None:
    owner = cohort("tools/owner.py")
    document = dict(status="passed", enforcement_complete=True, cohorts=[owner],
                    cohort_results={owner["id"]: dict(owner, status="failed")})
    check = Check("python-retention-inventory", ("python", "inventory.py"))
    assert evaluate(check, 0, json.dumps(document))[2] == "ratchet-regression"


def test_missing_admitted_cohort_evidence_cannot_be_residual_only() -> None:
    document = dict(status="failed", cohorts=[cohort("tools/owner.py")], cohort_results={})
    check = Check("python-retention-inventory", ("python", "inventory.py"))
    assert evaluate(check, 1, json.dumps(document))[2] == "ratchet-regression"


def test_compact_dependency_evidence_is_lossless_and_does_not_mutate_raw_records() -> None:
    record: dict[str, Any] = dict(governed_dependencies=["tools/a.py"], ungoverned_dependencies=["tools/b.py"],
                  dependency_blockers=["missing stub"], direct_findings={"mypy": [4]})
    original: dict[str, Any] = dict(cohort_results={"a": record, "b": record}, enforced={"tools": []})
    compact = compact_cohort_records(original)
    for value in compact["cohort_results"].values():
        assert [compact["cohort_dependency_paths"][i] for i in value["governed_dependency_indices"]] == ["tools/a.py"]
        assert [compact["cohort_dependency_paths"][i] for i in value["ungoverned_dependency_indices"]] == ["tools/b.py"]
        assert [compact["cohort_dependency_blockers"][i] for i in value["dependency_blocker_indices"]] == ["missing stub"]
        assert value["direct_findings"] == {"mypy": [4]}
    assert original["cohort_results"]["a"]["dependency_blockers"] == ["missing stub"]
    assert compact["enforced"] == original["enforced"]


def test_admitted_regression_has_hard_cli_exit(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(inventory, "validate_inventory", lambda **kwargs: {})
    monkeypatch.setattr(inventory, "check_inventory", lambda *args: dict(
        status="failed", classification="ratchet-regression", cohort_regressions=["owner"],
    ))
    assert inventory.main(["--check", "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["classification"] == "ratchet-regression"


@pytest.mark.parametrize("first_parent", [False, True])
def test_real_pipeline_reports_partial_enforcement_residual_and_open_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, first_parent: bool,
) -> None:
    paths = retention_candidate(
        tmp_path, ("tools/clean.py", "tools/pending.py"), ("admitted", "pending"),
        first_parent=first_parent,
    )
    validated = inventory.validate_inventory(tmp_path, *paths, context=candidate_context(tmp_path))
    assert validated["status"] == "not_checked"
    assert validated["eligible"]["tools"] == ["tools/clean.py", "tools/pending.py"]

    def partial_profile(requested: tuple[str, ...], **kwargs: object) -> dict[str, Any]:
        result = checked(list(requested))
        result["status"] = "failed"
        result["checks"]["ruff"] = {
            "status": "failed", "completed": True,
            "findings": [{"path": "tools/pending.py", "code": "F401"}],
        }
        return result

    monkeypatch.setattr(inventory, "bind_environment",
                        lambda: {"input_count": 1, "sha256": "stable", "versions": []})
    monkeypatch.setattr(inventory, "check_paths", partial_profile)
    result = inventory.check_inventory(validated, tmp_path, paths[1])

    assert result["enforced"]["tools"] == ["tools/clean.py"]
    assert result["eligible_minus_enforced"]["tools"] == ["tools/pending.py"]
    assert result["status"] == "failed"
    assert result["classification"] == "policy-finding"
    progress = result["profile_progress"]["tools"]
    assert progress["effectively_enforced"] == {"count": 1, "paths_ref": "enforced"}
    assert progress["root_closure"] == {"closed": False, "status": "open"}
    record = result["cohort_results"]["tools.clean.py"]
    assert "dependency_blockers" not in record
    assert record["dependency_blocker_indices"] == []
    assert result["cohort_results"]["tools.pending.py"]["direct_findings"]["ruff"] == [0]


def test_real_main_pipeline_reports_full_cohort_success_and_closure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    inventory_path, ratchet_path = retention_candidate(
        tmp_path, ("tools/clean.py",), ("admitted",)
    )
    context = candidate_context(tmp_path)
    monkeypatch.setattr("ci.python_retention_history_git_context.event_context", lambda: context)
    monkeypatch.setattr(inventory, "bind_environment",
                        lambda: {"input_count": 1, "sha256": "stable", "versions": []})
    monkeypatch.setattr(inventory, "check_paths",
                        lambda requested, **kwargs: checked(list(requested)))

    status = inventory.main(["--repo-root", str(tmp_path), "--inventory", str(inventory_path),
                             "--ratchet", str(ratchet_path), "--check", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert status == 0
    assert payload["status"] == "passed"
    assert payload["classification"] == "passed"
    assert payload["eligible_minus_enforced"]["tools"] == []
    assert payload["profile_progress"]["tools"]["effectively_enforced"] == {
        "count": 1, "paths_ref": "enforced",
    }
    assert payload["profile_progress"]["tools"]["root_closure"] == {
        "closed": True, "status": "closed",
    }


def test_real_main_pipeline_returns_two_for_admitted_cohort_regression(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    inventory_path, ratchet_path = retention_candidate(
        tmp_path, ("tools/bad.py",), ("admitted",)
    )

    def failing_profile(requested: tuple[str, ...], **kwargs: object) -> dict[str, Any]:
        result = checked(list(requested))
        result["status"] = "failed"
        result["checks"]["ruff"] = {
            "status": "failed", "completed": True,
            "findings": [{"path": "tools/bad.py", "code": "F401"}],
        }
        return result

    context = candidate_context(tmp_path)
    monkeypatch.setattr("ci.python_retention_history_git_context.event_context", lambda: context)
    monkeypatch.setattr(inventory, "bind_environment",
                        lambda: {"input_count": 1, "sha256": "stable", "versions": []})
    monkeypatch.setattr(inventory, "check_paths", failing_profile)
    status = inventory.main(["--repo-root", str(tmp_path), "--inventory", str(inventory_path),
                             "--ratchet", str(ratchet_path), "--check", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert status == 2
    assert payload["status"] == "failed"
    assert payload["classification"] == "ratchet-regression"
    assert payload["cohort_regressions"] == ["tools.bad.py"]
    assert payload["cohort_results"]["tools.bad.py"]["direct_findings"]["ruff"] == [0]
    assert payload["eligible_minus_enforced"]["tools"] == ["tools/bad.py"]


def test_environment_drift_during_cohort_evaluation_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = retention_candidate(tmp_path, ("tools/clean.py",), ("admitted",))
    validated = inventory.validate_inventory(tmp_path, *paths, context=candidate_context(tmp_path))
    snapshots = iter((
        {"input_count": 1, "sha256": "stable", "versions": []},
        {"input_count": 1, "sha256": "changed", "versions": []},
    ))
    monkeypatch.setattr(inventory, "bind_environment", lambda: next(snapshots))
    monkeypatch.setattr(inventory, "check_paths",
                        lambda requested, **kwargs: checked(list(requested)))

    with pytest.raises(inventory.InventoryValidationError, match="installed tool or typing inputs"):
        inventory.check_inventory(validated, tmp_path, paths[1])


def test_candidate_drift_after_cohort_evaluation_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = "tools/clean.py"
    paths = retention_candidate(tmp_path, (owner,), ("admitted",))
    validated = inventory.validate_inventory(tmp_path, *paths, context=candidate_context(tmp_path))
    calls = 0

    def binding() -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 2:
            (tmp_path / owner).write_text("value: int = 2\n", encoding="utf-8")
        return {"input_count": 1, "sha256": "stable", "versions": []}

    monkeypatch.setattr(inventory, "bind_environment", binding)
    monkeypatch.setattr(inventory, "check_paths",
                        lambda requested, **kwargs: checked(list(requested)))

    with pytest.raises(
        inventory.InventoryValidationError, match="candidate changed during cohort evaluation"
    ):
        inventory.check_inventory(validated, tmp_path, paths[1])


def test_mismatched_outer_github_candidate_is_rejected_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = retention_candidate(tmp_path, ("tools/clean.py",), ("admitted",))
    monkeypatch.setenv("GITHUB_SHA", "0" * 40)
    with pytest.raises(inventory.InventoryValidationError, match="differs from HEAD"):
        inventory.validate_inventory(tmp_path, *paths)


def test_explicit_context_ignores_outer_conflicting_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = retention_candidate(tmp_path, ("tools/clean.py",), ("admitted",))
    monkeypatch.setenv("GITHUB_SHA", "0" * 40)
    monkeypatch.setenv("GITHUB_REF", "refs/pull/26/merge")
    monkeypatch.setenv("GITHUB_BASE_REF", "unavailable-outer-target")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(tmp_path / "absent-outer-event.json"))
    validated = inventory.validate_inventory(tmp_path, *paths, context=candidate_context(tmp_path))
    assert validated["status"] == "not_checked"
    assert validated["history"]["candidate"]["commit"]
