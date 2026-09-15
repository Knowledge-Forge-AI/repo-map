"""Enumerate immutable inventory history on Git ancestry paths."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from ci.python_retention_history_git import (
    GitRunner,
    HistoryValidationError,
    SHA_PATTERN,
    _required_sha,
    _run_git,
    _text_output,
)


def merge_base(
    repo_root: Path, commits: Sequence[str], runner: GitRunner
) -> str:
    if len(commits) < 2:
        raise HistoryValidationError(
            "unsupported history: merge lineage has fewer than two parents"
        )
    arguments = ["merge-base"]
    if len(commits) > 2:
        arguments.append("--octopus")
    arguments.extend(commits)
    return _required_sha(
        _run_git(repo_root, arguments, runner), "merge lineage base"
    )


def inventory_history(
    repo_root: Path,
    tip: str,
    inventory_path: str,
    runner: GitRunner,
    *,
    lower: str | None = None,
    first_parent: bool = False,
) -> tuple[str, ...]:
    """Return every inventory-changing revision on one immutable lineage."""
    arguments = ["log", "--format=%H", "--full-history", "--reverse"]
    if first_parent:
        arguments.append("--first-parent")
    if lower is not None:
        arguments.extend(["--ancestry-path", f"{lower}..{tip}"])
    else:
        arguments.append(tip)
    arguments.extend(["--", inventory_path])
    completed = _run_git(repo_root, arguments, runner)
    if completed.returncode != 0:
        raise HistoryValidationError(
            "unsupported history: inventory lineage cannot be enumerated"
        )
    values = tuple(_text_output(completed).split())
    if any(not SHA_PATTERN.fullmatch(value) for value in values):
        raise HistoryValidationError(
            "unsupported history: inventory lineage contains a non-immutable revision"
        )
    return values


__all__ = ["inventory_history", "merge_base"]
