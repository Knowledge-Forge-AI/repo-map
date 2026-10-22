"""Read-only Git primitives for retained authority replay."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
from typing import Sequence

from ci.retained_python_contract import RatchetContractError


def git(
    repo_root: Path, args: Sequence[str], *, text: bool = True
) -> subprocess.CompletedProcess:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        env=os.environ | {"GIT_NO_REPLACE_OBJECTS": "1"},
        check=False,
        capture_output=True,
        text=text,
        timeout=60,
    )
    return completed


def git_required(repo_root: Path, *args: str) -> str:
    completed = git(repo_root, args)
    if completed.returncode != 0:
        raise RatchetContractError("Git history inspection failed")
    return completed.stdout.strip()


def blob(repo_root: Path, commit: str, path: str) -> bytes | None:
    listed = git(repo_root, ("ls-tree", "-z", commit, "--", path), text=False)
    if listed.returncode != 0:
        raise RatchetContractError("Git tree inspection failed")
    if not listed.stdout:
        return None
    shown = git(repo_root, ("show", f"{commit}:{path}"), text=False)
    if shown.returncode != 0:
        raise RatchetContractError("Git blob inspection failed")
    return shown.stdout


def raw_commit(repo_root: Path, commit: str) -> bytes | None:
    """Return unauthenticated raw commit bytes; callers must verify the object ID."""
    shown = git(repo_root, ("cat-file", "commit", commit), text=False)
    return shown.stdout if shown.returncode == 0 else None


def commit_authority(repo_root: Path, commit: str, path: str) -> str | None:
    content = blob(repo_root, commit, path)
    return content.decode("utf-8") if content is not None else None


def parents(repo_root: Path, commit: str) -> tuple[str, ...]:
    output = git_required(repo_root, "show", "-s", "--format=%P", commit)
    return tuple(output.split()) if output else ()


def is_ancestor(repo_root: Path, ancestor: str, descendant: str) -> bool:
    completed = git(repo_root, ("merge-base", "--is-ancestor", ancestor, descendant))
    if completed.returncode not in {0, 1}:
        raise RatchetContractError("Git ancestry inspection failed")
    return completed.returncode == 0


def change_commits(repo_root: Path, path: str) -> tuple[str, ...]:
    output = git_required(
        repo_root, "log", "--format=%H", "--full-history", "--reverse", "HEAD", "--", path
    )
    return tuple(output.splitlines()) if output else ()
