"""Retention history shape, successor continuity, and protected eligibility."""
from __future__ import annotations

from typing import Any

import json
import os
from pathlib import Path
import subprocess

import pytest

from ci import python_retention_history as history
from ci.python_retention_history_git import HistoryContext


def git(repo: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ | {
        "GIT_AUTHOR_NAME": "RepoMap test",
        "GIT_AUTHOR_EMAIL": "repomap-test@example.invalid",
        "GIT_COMMITTER_NAME": "RepoMap test",
        "GIT_COMMITTER_EMAIL": "repomap-test@example.invalid",
    }
    return subprocess.run(
        ["git", "-C", str(repo), *arguments],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )


def _entry(name: str) -> dict[str, Any]:
    return {"path": name, "confidence": 0.9, "maintained_executable": True}


def candidate(
    tmp_path: Path,
    paths: tuple[str, ...],
    *,
    previous: tuple[str, ...] = (),
) -> tuple[Path, Path]:
    repo = tmp_path
    git(repo, "init", "-q")
    inventory = repo / "inventory.json"
    inventory.write_text(json.dumps({"files": [_entry(name) for name in previous]}))
    git(repo, "add", "inventory.json")
    git(repo, "commit", "-qm", "baseline inventory")
    inventory.write_text(json.dumps({"files": [_entry(name) for name in paths]}))
    return inventory, repo


def validate(root: Path, paths: tuple[Path, Path]) -> history.PathHistoryResult:
    data = json.loads(paths[0].read_text())
    current = {entry["path"] for entry in data["files"]}
    return history.validate_path_history(root, paths[0], current, data, context=HistoryContext())


def change(inv: Path, **fields: object) -> None:
    data = json.loads(inv.read_text())
    data["files"][0].update(fields)
    inv.write_text(json.dumps(data))


def test_committed_recorded_decompositions_accepted(tmp_path: Path) -> None:
    paths = candidate(tmp_path, ("tools/new.py",), previous=("tools/old.py",))
    data = json.loads(paths[0].read_text())
    data["decompositions"] = [{
        "from": "tools/old.py", "to": ["tools/new.py"],
        "rationale": "Separate the maintained responsibility",
    }]
    paths[0].write_text(json.dumps(data))
    git(tmp_path, "add", "inventory.json")
    git(tmp_path, "commit", "-qm", "record decomposition")
    result = validate(tmp_path, paths)
    assert result == data["decompositions"]
    candidate_evidence = result.evidence["candidate"]
    assert isinstance(candidate_evidence, dict)
    assert candidate_evidence["commit"]
    comparison = result.evidence["comparison_basis"]
    assert isinstance(comparison, dict)
    assert comparison["commits"]


def test_decompositions_and_list_valued_to_accepted(tmp_path: Path) -> None:
    paths = candidate(tmp_path, ("tools/new1.py", "tools/new2.py"), previous=("tools/old.py",))
    data = json.loads(paths[0].read_text())
    data["decompositions"] = [{
        "from": "tools/old.py",
        "to": ["tools/new1.py", "tools/new2.py"],
        "rationale": "Decomposed tool across responsibilities",
    }]
    paths[0].write_text(json.dumps(data))
    result = validate(tmp_path, paths)
    assert result == data["decompositions"]

    del data["decompositions"]
    data["path_transitions"] = [{
        "from": "tools/old.py",
        "to": ["tools/new1.py", "tools/new2.py"],
        "rationale": "Split transition into two owners",
    }]
    paths[0].write_text(json.dumps(data))
    result = validate(tmp_path, paths)
    assert result == data["path_transitions"]


@pytest.mark.parametrize("history_key, entry, error_pattern", [
    ("path_transitions", "not-a-list", "invalid path transition history"),
    ("path_transitions", [{"from": "tools/old.py", "rationale": "r"}], "invalid or duplicate path transition"),
    ("decompositions", "not-a-list", "invalid decomposition history"),
    ("path_transitions", [{"from": "tools/old.py", "to": 123, "rationale": "r"}], "invalid or duplicate path transition"),
    ("path_transitions", [{"from": "tools/old.py", "to": [123], "rationale": "r"}], "invalid or duplicate path transition"),
    ("path_transitions", [{"from": "tools/old.py", "to": [""], "rationale": "r"}], "invalid or duplicate path transition"),
    ("decompositions", [{"from": "tools/old.py", "to": 123, "rationale": "r"}], "invalid or duplicate decomposition"),
    ("decompositions", [{"from": "tools/old.py", "to": [], "rationale": "r"}], "invalid or duplicate decomposition"),
    ("decompositions", [{"from": "tools/old.py", "to": [123], "rationale": "r"}], "invalid or duplicate decomposition"),
    ("decompositions", [{"from": "tools/old.py", "to": [""], "rationale": "r"}], "invalid or duplicate decomposition"),
    ("decompositions", [{"from": "tools/old.py", "to": None, "rationale": "r"}], "invalid or duplicate decomposition"),
    ("decompositions", [{"from": "", "to": ["tools/new.py"], "rationale": "r"}], "invalid or duplicate decomposition"),
    ("decompositions", [{"from": "tools/old.py", "to": ["tools/new.py"], "rationale": " "}], "invalid or duplicate decomposition"),
])
def test_malformed_history_structured_failures(
    tmp_path: Path, history_key: str, entry: object, error_pattern: str,
) -> None:
    paths = candidate(tmp_path, ("tools/new.py",))
    data = json.loads(paths[0].read_text())
    data[history_key] = entry
    paths[0].write_text(json.dumps(data))
    with pytest.raises(history.HistoryValidationError, match=error_pattern):
        validate(tmp_path, paths)


def test_successor_chain_preservation(tmp_path: Path) -> None:
    paths = candidate(tmp_path, ("tools/final.py",), previous=("tools/orig.py",))
    data = json.loads(paths[0].read_text())
    data["path_transitions"] = [
        {"from": "tools/orig.py", "to": "tools/step.py", "rationale": "First transition step"},
        {"from": "tools/step.py", "to": "tools/final.py", "rationale": "Final transition step"},
    ]
    paths[0].write_text(json.dumps(data))
    result = validate(tmp_path, paths)
    assert result == [data["path_transitions"][0]]

    data["path_transitions"] = [
        {"from": "tools/orig.py", "to": "tools/missing.py", "rationale": "Broken transition step"},
    ]
    paths[0].write_text(json.dumps(data))
    with pytest.raises(history.HistoryValidationError, match="scope history"):
        validate(tmp_path, paths)

    data["path_transitions"] = [
        {"from": "tools/orig.py", "to": "tools/cycle_a.py", "rationale": "Into cycle"},
        {"from": "tools/cycle_a.py", "to": "tools/cycle_b.py", "rationale": "Cycle a to b"},
        {"from": "tools/cycle_b.py", "to": "tools/cycle_a.py", "rationale": "Cycle b to a"},
    ]
    paths[0].write_text(json.dumps(data))
    with pytest.raises(history.HistoryValidationError, match="cyclic successor chain"):
        validate(tmp_path, paths)


def test_terminal_successor_chain_is_valid_termination(tmp_path: Path) -> None:
    paths = candidate(tmp_path, (), previous=("tools/orig.py",))
    data = json.loads(paths[0].read_text())
    data["path_transitions"] = [
        {"from": "tools/orig.py", "to": "tools/step.py", "rationale": "Retire in two stages"},
        {"from": "tools/step.py", "to": None, "rationale": "Final owner was intentionally retired"},
    ]
    paths[0].write_text(json.dumps(data))
    assert validate(tmp_path, paths) == [data["path_transitions"][0]]


def test_terminal_record_cannot_cover_living_path(tmp_path: Path) -> None:
    paths = candidate(tmp_path, ("tools/live.py",), previous=("tools/live.py",))
    data = json.loads(paths[0].read_text())
    data["path_transitions"] = [{
        "from": "tools/live.py", "to": None, "rationale": "Incorrect termination",
    }]
    paths[0].write_text(json.dumps(data))
    with pytest.raises(history.HistoryValidationError, match="living eligible"):
        validate(tmp_path, paths)


def test_confidence_drop_cannot_discard_prior_protection(tmp_path: Path) -> None:
    paths = candidate(tmp_path, ("tools/owner.py",), previous=("tools/owner.py",))
    change(paths[0], confidence=0.5, counterevidence="Drop confidence")
    with pytest.raises(history.HistoryValidationError, match="prior protection"):
        validate(tmp_path, paths)

    change(paths[0], confidence=0.85, counterevidence="")
    assert validate(tmp_path, paths) == []

    change(paths[0], confidence=0.9, maintained_executable=False, counterevidence="Drop executable")
    with pytest.raises(history.HistoryValidationError, match="prior protection"):
        validate(tmp_path, paths)


def test_successor_confidence_drop_cannot_discard_prior_protection(tmp_path: Path) -> None:
    paths = candidate(tmp_path, ("tools/new.py",), previous=("tools/old.py",))
    change(paths[0], confidence=0.5, counterevidence="Lower confidence successor")
    data = json.loads(paths[0].read_text())
    data["path_transitions"] = [{
        "from": "tools/old.py", "to": "tools/new.py", "rationale": "Transition to lower confidence",
    }]
    paths[0].write_text(json.dumps(data))
    with pytest.raises(history.HistoryValidationError, match="prior protection"):
        validate(tmp_path, paths)

    del data["path_transitions"]
    data["decompositions"] = [{
        "from": "tools/old.py", "to": ["tools/new.py"], "rationale": "Decompose to lower confidence",
    }]
    paths[0].write_text(json.dumps(data))
    with pytest.raises(history.HistoryValidationError, match="prior protection"):
        validate(tmp_path, paths)


def test_convergent_successors_are_not_a_cycle(tmp_path: Path) -> None:
    paths = candidate(tmp_path, ("tools/final.py",), previous=("tools/original.py",))
    data = json.loads(paths[0].read_text())
    data["decompositions"] = [
        {"from": "tools/original.py", "to": ["tools/a.py", "tools/b.py"], "rationale": "Split"},
        {"from": "tools/a.py", "to": "tools/final.py", "rationale": "Converge"},
        {"from": "tools/b.py", "to": "tools/final.py", "rationale": "Converge"},
    ]
    paths[0].write_text(json.dumps(data))
    assert validate(tmp_path, paths) == [data["decompositions"][0]]


def _cohort_entry(name: str) -> dict[str, Any]:
    return {
        "path": name, "root": "tools", "governing_profile": "clean_tooling",
        "confidence": 0.9, "maintained_executable": True, "rationale": "r",
    }


def _cohort_doc(paths: tuple[str, ...], *, admission: str = "admitted", cid: str = "tools_ci") -> dict[str, Any]:
    return {
        "schema": "repomap-python-retention-inventory-v1",
        "cohort_schema": "repomap-python-retention-cohorts-v1",
        "files": [_cohort_entry(p) for p in paths],
        "cohorts": [{
            "id": cid, "root": "tools", "governing_profile": "clean_tooling",
            "members": sorted(paths), "rationale": "Tools cohort", "admission": admission,
        }],
    }


def _commit_doc(repo: Path, inv: Path, data: dict[str, Any], msg: str) -> str:
    inv.write_text(json.dumps(data))
    git(repo, "add", "inventory.json")
    git(repo, "commit", "-qm", msg)
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def test_cohort_schema_rollback_disappearance_fails(tmp_path: Path) -> None:
    repo = tmp_path
    git(repo, "init", "-q")
    inv = repo / "inventory.json"
    _commit_doc(repo, inv, _cohort_doc(("tools/a.py",)), "intro cohorts")
    candidate_data = {"schema": "repomap-python-retention-inventory-v1", "files": [_entry("tools/a.py")]}
    inv.write_text(json.dumps(candidate_data))
    with pytest.raises(history.HistoryValidationError, match="cohort schema extension cannot disappear"):
        validate(repo, (inv, repo))


def test_cohort_cannot_disappear(tmp_path: Path) -> None:
    repo = tmp_path
    git(repo, "init", "-q")
    inv = repo / "inventory.json"
    doc = _cohort_doc(("tools/a.py",), cid="tools_a")
    doc["files"].append(_cohort_entry("tools/b.py"))
    doc["cohorts"].append({
        "id": "tools_b", "root": "tools", "governing_profile": "clean_tooling",
        "members": ["tools/b.py"], "rationale": "Cohort B", "admission": "pending",
    })
    doc["cohorts"].sort(key=lambda c: c["id"])
    _commit_doc(repo, inv, doc, "two cohorts")

    candidate_doc = _cohort_doc(("tools/a.py",), cid="tools_a")
    inv.write_text(json.dumps(candidate_doc))
    with pytest.raises(history.HistoryValidationError, match="cohort cannot disappear: tools_b"):
        validate(repo, (inv, repo))


def test_cohort_tamper_rationale_fails(tmp_path: Path) -> None:
    repo = tmp_path
    git(repo, "init", "-q")
    inv = repo / "inventory.json"
    _commit_doc(repo, inv, _cohort_doc(("tools/a.py",)), "base cohort")
    cand = _cohort_doc(("tools/a.py",))
    cand["cohorts"][0]["rationale"] = "Tampered rationale"
    inv.write_text(json.dumps(cand))
    with pytest.raises(history.HistoryValidationError, match="cohort rationale cannot change"):
        validate(repo, (inv, repo))


def test_cohort_transition_tamper_root_and_profile_fails() -> None:
    import copy
    old_doc = _cohort_doc(("tools/a.py",))
    new_doc = copy.deepcopy(old_doc)
    new_doc["cohorts"][0]["root"] = "test_support"
    new_doc["cohorts"][0]["governing_profile"] = "clean_test_support"
    new_doc["files"][0]["root"] = "test_support"
    new_doc["files"][0]["governing_profile"] = "clean_test_support"
    with pytest.raises(history.HistoryValidationError, match="cohort root cannot change"):
        history.validate_cohort_transition(old_doc, new_doc)


def test_admitted_cohort_cannot_downgrade_to_pending(tmp_path: Path) -> None:
    repo = tmp_path
    git(repo, "init", "-q")
    inv = repo / "inventory.json"
    _commit_doc(repo, inv, _cohort_doc(("tools/a.py",), admission="admitted"), "base admitted")
    cand = _cohort_doc(("tools/a.py",), admission="pending")
    inv.write_text(json.dumps(cand))
    with pytest.raises(history.HistoryValidationError, match="admitted cohort cannot be downgraded"):
        validate(repo, (inv, repo))


def test_admitted_cohort_recorded_replacement_preserves_lineage(tmp_path: Path) -> None:
    repo = tmp_path
    git(repo, "init", "-q")
    inv = repo / "inventory.json"
    _commit_doc(repo, inv, _cohort_doc(("tools/a.py", "tools/b.py"), admission="admitted"), "base")
    cand = _cohort_doc(("tools/a.py", "tools/c.py"), admission="admitted")
    cand["path_transitions"] = [{
        "from": "tools/b.py", "to": "tools/c.py", "rationale": "Transition b to c",
    }]
    inv.write_text(json.dumps(cand))
    assert validate(repo, (inv, repo)) == cand["path_transitions"]


@pytest.mark.parametrize("keep_source", [True, False])
def test_decomposition_successor_cannot_move_to_pending_cohort(tmp_path: Path, keep_source: bool) -> None:
    repo = tmp_path
    git(repo, "init", "-q")
    inv = repo / "inventory.json"
    _commit_doc(repo, inv, _cohort_doc(("tools/source.py",), admission="admitted", cid="tools_admitted"), "base")
    paths = ("tools/source.py", "tools/succ.py") if keep_source else ("tools/succ.py",)
    cand: dict[str, Any] = {
        "schema": "repomap-python-retention-inventory-v1",
        "cohort_schema": "repomap-python-retention-cohorts-v1",
        "files": [_cohort_entry(p) for p in paths],
        "cohorts": [
            {
                "id": "tools_admitted", "root": "tools", "governing_profile": "clean_tooling",
                "members": ["tools/source.py"], "rationale": "Admitted", "admission": "admitted",
            },
            {
                "id": "tools_pending", "root": "tools", "governing_profile": "clean_tooling",
                "members": ["tools/succ.py"], "rationale": "Pending", "admission": "pending",
            },
        ],
        "decompositions": [{
            "from": "tools/source.py", "to": ["tools/succ.py"], "rationale": "Decompose tool",
        }],
    }
    cand["cohorts"].sort(key=lambda c: c["id"])
    inv.write_text(json.dumps(cand))
    with pytest.raises(history.HistoryValidationError, match="cannot move to pending cohort"):
        validate(repo, (inv, repo))


def test_intermediate_weakening_restored_in_lineage_fails(tmp_path: Path) -> None:
    repo = tmp_path
    git(repo, "init", "-q")
    inv = repo / "inventory.json"
    _commit_doc(repo, inv, _cohort_doc(("tools/a.py",), admission="admitted"), "commit 1 base")
    _commit_doc(repo, inv, _cohort_doc(("tools/a.py",), admission="pending"), "commit 2 weakened")
    cand = _cohort_doc(("tools/a.py",), admission="admitted")
    _commit_doc(repo, inv, cand, "commit 3 restored")
    with pytest.raises(history.HistoryValidationError, match="admitted cohort cannot be downgraded"):
        validate(repo, (inv, repo))


def test_merge_history_rejects_weakened_branch(tmp_path: Path) -> None:
    repo = tmp_path
    git(repo, "init", "-q")
    inv = repo / "inventory.json"
    base_sha = _commit_doc(repo, inv, _cohort_doc(("tools/a.py",), admission="admitted"), "base")

    git(repo, "checkout", "-q", "-b", "target", base_sha)
    target_doc = _cohort_doc(("tools/a.py", "tools/target.py"), admission="admitted")
    target_sha = _commit_doc(repo, inv, target_doc, "target clean")

    git(repo, "checkout", "-q", "-b", "feature", base_sha)
    _commit_doc(repo, inv, _cohort_doc(("tools/a.py",), admission="pending"), "feature weakened")

    cand = _cohort_doc(("tools/a.py",), admission="admitted")
    _commit_doc(repo, inv, cand, "feature restored before merge")

    with pytest.raises(history.HistoryValidationError, match="admitted cohort cannot be downgraded"):
        history.validate_path_history(
            repo, inv, {"tools/a.py"}, cand,
            context=HistoryContext(target_commit=target_sha, pull_request_merge=False),
        )
