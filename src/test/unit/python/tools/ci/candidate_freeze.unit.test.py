from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

import ci.candidate_freeze as candidate_freeze

freeze = candidate_freeze


def load_module():
    return candidate_freeze


def git(root: Path, *arguments: str) -> None:
    subprocess.run(["git", "-C", str(root), *arguments], check=True)


def initialized_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    (root / "tracked.py").write_text("before\n", encoding="utf-8")
    git(root, "add", "--", "tracked.py")
    git(
        root,
        "-c",
        "user.name=RepoMap Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-qm",
        "fixture",
    )
    return root


def test_safety3_freeze_classifies_tracked_modified_from_git(tmp_path: Path) -> None:
    freeze = load_module()
    root = initialized_repo(tmp_path)
    (root / "tracked.py").write_text("after\n", encoding="utf-8")

    result = freeze.classify_candidate_paths(root, relevant_untracked=())

    assert result.base_commit == subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert result.tracked_modified == ("tracked.py",)
    assert result.relevant_untracked == ()
    assert result.files[0].sha256 == freeze.sha256_file(root / "tracked.py")


def test_safety3_freeze_classifies_only_declared_relevant_untracked(
    tmp_path: Path,
) -> None:
    freeze = load_module()
    root = initialized_repo(tmp_path)
    (root / "relevant.txt").write_text("bound\n", encoding="utf-8")
    (root / "noise.txt").write_text("ignored by phase scope\n", encoding="utf-8")

    result = freeze.classify_candidate_paths(
        root,
        relevant_untracked=("relevant.txt",),
    )

    assert result.tracked_modified == ()
    assert result.relevant_untracked == ("relevant.txt",)
    assert [item.path for item in result.files] == ["relevant.txt"]


def test_safety3_freeze_refuses_tracked_rename(tmp_path: Path) -> None:
    freeze = load_module()
    root = initialized_repo(tmp_path)
    git(root, "mv", "tracked.py", "renamed.py")

    with pytest.raises(freeze.CandidateClassificationError, match="rename"):
        freeze.classify_candidate_paths(root, relevant_untracked=())
