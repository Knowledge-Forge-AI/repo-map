"""Synthetic Git history coverage for retained-Python predecessor selection."""
from __future__ import annotations
from typing import Any, cast

import json
import os
from pathlib import Path
import subprocess

import pytest

from ci import python_retention_history as history
from ci.python_retention_history_git import HistoryContext, resolve_history_basis


def git(repo: Path, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    environment = os.environ | {
        "GIT_AUTHOR_NAME": "RepoMap test",
        "GIT_AUTHOR_EMAIL": "repomap-test@example.invalid",
        "GIT_COMMITTER_NAME": "RepoMap test",
        "GIT_COMMITTER_EMAIL": "repomap-test@example.invalid",
    }
    return subprocess.run(
        ["git", "-C", str(repo), *arguments],
        check=check,
        capture_output=True,
        text=True,
        env=environment,
    )


def _entry(path: str, *, confidence: float = 0.9) -> dict[str, object]:
    return {"path": path, "confidence": confidence, "maintained_executable": True}


def _inventory(paths: tuple[str, ...]) -> dict[str, object]:
    return {"files": [_entry(path) for path in paths]}


def _write_inventory(repo: Path, data: dict[str, object]) -> Path:
    path = repo / "inventory.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _commit_inventory(repo: Path, data: dict[str, object], message: str) -> str:
    _write_inventory(repo, data)
    git(repo, "add", "inventory.json")
    git(repo, "commit", "-qm", message)
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def _init(tmp_path: Path, initial: dict[str, object]) -> tuple[Path, Path, str]:
    repo = tmp_path
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "-q")
    inventory = _write_inventory(repo, initial)
    git(repo, "add", "inventory.json")
    git(repo, "commit", "-qm", "initial inventory")
    return repo, inventory, git(repo, "rev-parse", "HEAD").stdout.strip()


def _validate(repo: Path, inventory: Path, data: dict[str, Any]) -> history.PathHistoryResult:
    current = {entry["path"] for entry in data["files"]}
    return history.validate_path_history(repo, inventory, current, data, context=HistoryContext())


def test_non_merge_candidates_use_target_merge_base(tmp_path: Path) -> None:
    repo, inventory, base = _init(tmp_path, _inventory(("tools/old.py",)))
    git(repo, "checkout", "-q", "-b", "target", base)
    target = _inventory(("tools/old.py", "tools/target-only.py"))
    target_sha = _commit_inventory(repo, target, "target advances independently")

    git(repo, "checkout", "-q", "-b", "feature", base)
    candidate = _inventory(("tools/new.py",))
    candidate["path_transitions"] = [{
        "from": "tools/old.py",
        "to": "tools/new.py",
        "rationale": "Rename preserves the maintained owner",
    }]
    candidate_sha = _commit_inventory(repo, candidate, "candidate renames owner")

    result = history.validate_path_history(
        repo,
        inventory,
        {"tools/new.py"},
        candidate,
        context=HistoryContext(
            target_commit=target_sha,
            pull_request_merge=False,
        ),
    )
    comparison = cast(dict[str, Any], result.evidence)["comparison_basis"]
    assert comparison["method"] == "target-merge-base"
    assert comparison["merge_base"] == base
    assert comparison["commits"] == [base]
    assert cast(dict[str, Any], result.evidence)["candidate"]["commit"] == candidate_sha
    assert cast(dict[str, Any], result.evidence)["comparison_basis"]["audited_revisions"][0]["commit"] == base


def test_pull_request_merge_audits_both_merge_parents_and_protections(
    tmp_path: Path,
) -> None:
    repo, inventory, base = _init(tmp_path, _inventory(("tools/common.py",)))
    git(repo, "checkout", "-q", "-b", "target", base)
    target = _inventory(("tools/common.py", "tools/target-old.py"))
    target_sha = _commit_inventory(repo, target, "target protected addition")
    git(repo, "checkout", "-q", "-b", "feature", base)
    feature = _inventory(("tools/common.py", "tools/feature-old.py"))
    feature_sha = _commit_inventory(repo, feature, "feature protected addition")

    candidate = _inventory(("tools/common.py", "tools/target-new.py", "tools/feature-new.py"))
    candidate["path_transitions"] = [
        {
            "from": "tools/target-old.py",
            "to": "tools/target-new.py",
            "rationale": "Target owner renamed in the merge candidate",
        },
        {
            "from": "tools/feature-old.py",
            "to": "tools/feature-new.py",
            "rationale": "Feature owner renamed in the merge candidate",
        },
    ]
    candidate_path = _write_inventory(repo, candidate)
    git(repo, "add", "inventory.json")
    tree = git(repo, "write-tree").stdout.strip()
    merge = git(
        repo,
        "commit-tree",
        tree,
        "-p",
        target_sha,
        "-p",
        feature_sha,
        "-m",
        "synthetic pull request merge",
    ).stdout.strip()
    git(repo, "checkout", "-q", merge)

    result = history.validate_path_history(
        repo,
        candidate_path,
        {"tools/common.py", "tools/target-new.py", "tools/feature-new.py"},
        candidate,
        context=HistoryContext(pull_request_merge=True),
    )
    comparison = cast(dict[str, Any], result.evidence)["comparison_basis"]
    assert comparison["method"] == "pull-request-merge-parents"
    assert comparison["commits"] == [target_sha, feature_sha]
    assert comparison["merge_base"] == base
    assert len(comparison["audited_revisions"]) == 3
    assert {item["commit"] for item in comparison["audited_revisions"]} == {
        base,
        target_sha,
        feature_sha,
    }


def test_pull_request_merge_context_is_read_from_event_without_target_tip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, inventory, base = _init(tmp_path, _inventory(("tools/common.py",)))
    git(repo, "checkout", "-q", "-b", "target", base)
    target_sha = _commit_inventory(repo, _inventory(("tools/common.py", "tools/target.py")), "target")
    git(repo, "checkout", "-q", "-b", "feature", base)
    feature_sha = _commit_inventory(repo, _inventory(("tools/common.py", "tools/feature.py")), "feature")
    candidate = _inventory(("tools/common.py", "tools/target.py", "tools/feature.py"))
    candidate_path = _write_inventory(repo, candidate)
    git(repo, "add", "inventory.json")
    tree = git(repo, "write-tree").stdout.strip()
    merge = git(repo, "commit-tree", tree, "-p", target_sha, "-p", feature_sha, "-m", "merge").stdout.strip()
    git(repo, "checkout", "-q", merge)
    event = tmp_path / "event.json"
    event.write_text(json.dumps({
        "pull_request": {"base": {"ref": "staging", "sha": base}},
    }), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.setenv("GITHUB_REF", "refs/pull/26/merge")
    monkeypatch.setenv("GITHUB_SHA", merge)

    from ci.python_retention_history_git_context import event_context

    context = event_context()
    assert context.github_candidate_sha == merge
    basis = resolve_history_basis(repo, candidate_path, context=context)
    assert basis.selection_method == "pull-request-merge-parents"
    assert basis.comparison_commits == (target_sha, feature_sha)


def test_pull_request_merge_audits_intervening_protected_inventory_states(
    tmp_path: Path,
) -> None:
    repo, inventory, base = _init(tmp_path, _inventory(("tools/common.py",)))
    protected = _inventory(("tools/common.py", "tools/protected.py"))
    _commit_inventory(repo, protected, "introduce protected path")
    _commit_inventory(repo, _inventory(("tools/common.py",)), "illicitly remove protected path")
    feature_tip = _commit_inventory(
        repo,
        _inventory(("tools/common.py", "tools/feature-current.py")),
        "advance feature independently",
    )
    candidate = _inventory(("tools/common.py", "tools/current.py"))
    candidate_path = _write_inventory(repo, candidate)
    git(repo, "add", "inventory.json")
    tree = git(repo, "write-tree").stdout.strip()
    merge = git(
        repo,
        "commit-tree",
        tree,
        "-p",
        base,
        "-p",
        feature_tip,
        "-m",
        "merge after illicit removal",
    ).stdout.strip()
    git(repo, "checkout", "-q", merge)

    with pytest.raises(history.HistoryValidationError, match="removed path"):
        history.validate_path_history(
            repo,
            candidate_path,
            {"tools/common.py", "tools/current.py"},
            candidate,
            context=HistoryContext(pull_request_merge=True),
        )


def test_candidate_never_self_compares_for_removal_protection(tmp_path: Path) -> None:
    repo, inventory, _base = _init(tmp_path, _inventory(("tools/old.py",)))
    candidate = _inventory(("tools/new.py",))
    candidate_sha = _commit_inventory(repo, candidate, "remove without authority")
    with pytest.raises(history.HistoryValidationError, match="removed path"):
        _validate(repo, inventory, candidate)
    basis = resolve_history_basis(repo, inventory, context=HistoryContext())
    assert basis.candidate_commit == candidate_sha
    assert candidate_sha not in basis.comparison_commits


def test_local_first_parent_audits_intervening_protected_inventory_states(
    tmp_path: Path,
) -> None:
    repo, inventory, _base = _init(tmp_path, _inventory(("tools/common.py",)))
    introduced = _commit_inventory(
        repo,
        _inventory(("tools/common.py", "tools/protected.py")),
        "introduce protected path",
    )
    removed = _commit_inventory(
        repo,
        _inventory(("tools/common.py",)),
        "illicitly remove protected path",
    )
    candidate = _inventory(("tools/common.py", "tools/current.py"))
    candidate_sha = _commit_inventory(repo, candidate, "advance unrelated candidate")

    with pytest.raises(history.HistoryValidationError, match="removed path"):
        _validate(repo, inventory, candidate)
    basis = resolve_history_basis(repo, inventory, context=HistoryContext())
    assert candidate_sha not in basis.audited_commits
    assert introduced in basis.audited_commits
    assert removed in basis.audited_commits


def test_local_inventory_history_is_append_only_across_intervening_revisions(
    tmp_path: Path,
) -> None:
    repo, inventory, _base = _init(tmp_path, _inventory(("tools/common.py",)))
    first = _inventory(("tools/common.py", "tools/old.py", "tools/new.py"))
    first["path_transitions"] = [{
        "from": "tools/old.py",
        "to": "tools/new.py",
        "rationale": "Preserve the owner while recording the rename",
    }]
    first_sha = _commit_inventory(repo, first, "record rename")
    second = _inventory(("tools/common.py", "tools/old.py", "tools/new.py"))
    second_sha = _commit_inventory(repo, second, "illicitly remove history record")
    candidate = _inventory(("tools/common.py", "tools/old.py", "tools/new.py"))
    candidate["path_transitions"] = first["path_transitions"]
    _commit_inventory(repo, candidate, "restore history record")

    with pytest.raises(history.HistoryValidationError, match="not append-only"):
        _validate(repo, inventory, candidate)
    basis = resolve_history_basis(repo, inventory, context=HistoryContext())
    assert first_sha in basis.audited_commits
    assert second_sha in basis.audited_commits


def test_shallow_history_fails_closed(tmp_path: Path) -> None:
    source, inventory, _base = _init(tmp_path / "source", _inventory(("tools/old.py",)))
    candidate = _inventory(("tools/old.py",))
    clone = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", f"file://{source}", str(clone)],
        check=True,
        capture_output=True,
        text=True,
    )
    with pytest.raises(history.HistoryValidationError, match="shallow or incomplete"):
        _validate(clone, clone / "inventory.json", candidate)
    with pytest.raises(history.HistoryValidationError, match="shallow or incomplete"):
        resolve_history_basis(clone, clone / "inventory.json")


def test_inventory_introduction_is_validated_when_predecessor_lacks_blob(
    tmp_path: Path,
) -> None:
    repo = tmp_path
    git(repo, "init", "-q")
    (repo / "README").write_text("unrelated\n", encoding="utf-8")
    git(repo, "add", "README")
    git(repo, "commit", "-qm", "unrelated root")
    data = _inventory(("tools/new.py",))
    inventory_path = _write_inventory(repo, data)
    git(repo, "add", "inventory.json")
    git(repo, "commit", "-qm", "introduce inventory")
    result = _validate(repo, inventory_path, data)
    comparison = cast(dict[str, Any], result.evidence)["comparison_basis"]
    assert comparison["method"] == "first-parent"
    assert comparison["inventory_introduction"] == git(repo, "rev-parse", "HEAD").stdout.strip()
    assert comparison["commits"]


def test_worktree_inventory_introduction_has_explicit_boundary(tmp_path: Path) -> None:
    repo = tmp_path
    git(repo, "init", "-q")
    (repo / "README").write_text("unrelated\n", encoding="utf-8")
    git(repo, "add", "README")
    git(repo, "commit", "-qm", "unrelated root")
    inventory = _write_inventory(repo, _inventory(("tools/new.py",)))
    result = _validate(repo, inventory, _inventory(("tools/new.py",)))
    comparison = cast(dict[str, Any], result.evidence)["comparison_basis"]
    assert comparison["method"] == "inventory-introduction"
    assert comparison["inventory_introduction"] == "worktree"
    assert comparison["commits"] == []


def test_missing_inventory_history_cannot_be_treated_as_empty(tmp_path: Path) -> None:
    repo = tmp_path
    git(repo, "init", "-q")
    (repo / "README").write_text("unrelated\n", encoding="utf-8")
    git(repo, "add", "README")
    git(repo, "commit", "-qm", "unrelated root")
    inventory = repo / "inventory.json"
    with pytest.raises(history.HistoryValidationError, match="introduction boundary is missing"):
        _validate(repo, inventory, _inventory(()))


def test_explicit_context_ignores_outer_github_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, inventory, commit = _init(tmp_path, _inventory(("tools/owner.py",)))
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    monkeypatch.setenv("GITHUB_REF", "refs/pull/26/merge")
    monkeypatch.setenv("GITHUB_BASE_REF", "unavailable-outer-target")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(tmp_path / "absent-outer-event.json"))
    basis = resolve_history_basis(repo, inventory, context=HistoryContext())
    assert basis.candidate_commit == commit
    assert basis.selection_method == "inventory-introduction"


@pytest.mark.parametrize("explicit", [False, True])
@pytest.mark.parametrize("identity", ["matching", "mismatched", "malformed"])
def test_environment_context_preserves_candidate_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, explicit: bool, identity: str,
) -> None:
    from ci.python_retention_history_git_context import event_context

    repo, inventory, commit = _init(tmp_path, _inventory(("tools/owner.py",)))
    for name in ("GITHUB_EVENT_PATH", "GITHUB_REF", "GITHUB_BASE_REF"):
        monkeypatch.delenv(name, raising=False)
    expected = {"matching": commit, "mismatched": "a" * 40, "malformed": "branch-name"}[identity]
    monkeypatch.setenv("GITHUB_SHA", expected)
    context = event_context() if explicit else None
    if explicit:
        # Authority is captured at derivation, not re-read at validation time.
        monkeypatch.setenv("GITHUB_SHA", "b" * 40)
    if identity == "matching":
        assert resolve_history_basis(repo, inventory, context=context).candidate_commit == commit
    else:
        message = "differs from HEAD" if identity == "mismatched" else "not immutable"
        with pytest.raises(history.HistoryValidationError, match=message):
            resolve_history_basis(repo, inventory, context=context)


def test_dirty_worktree_predecessor_coverage(tmp_path: Path) -> None:
    repo, inventory, base = _init(tmp_path, _inventory(("tools/common.py",)))
    commit = _commit_inventory(repo, _inventory(("tools/common.py", "tools/committed.py")), "committed")
    _write_inventory(repo, _inventory(("tools/common.py", "tools/committed.py", "tools/worktree.py")))
    basis = resolve_history_basis(repo, inventory, context=HistoryContext())
    assert basis.selection_method == "first-parent"
    assert basis.comparison_commits == (base,)
    assert basis.worktree_predecessor == commit
