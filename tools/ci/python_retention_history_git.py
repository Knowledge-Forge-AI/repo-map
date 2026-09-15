"""Git identity and immutable predecessor resolution for retention history."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Callable, Sequence


SHA_PATTERN = re.compile(r"[0-9a-f]{40,64}\Z")
HISTORY_SCHEMA = "repomap-python-retention-history-v1"


class HistoryValidationError(RuntimeError):
    """The inventory history or its immutable comparison basis is invalid."""


GitRunner = Callable[..., subprocess.CompletedProcess[Any]]


@dataclass(frozen=True, slots=True)
class HistoryContext:
    """Optional CI lineage facts used to select an immutable predecessor."""

    candidate_ref: str = "HEAD"
    target_ref: str | None = None
    target_commit: str | None = None
    pull_request_merge: bool | None = None
    github_candidate_sha: str | None = None


@dataclass(frozen=True, slots=True)
class HistoryBasis:
    """Resolved candidate and predecessor identities for machine evidence."""

    inventory_path: str
    candidate_commit: str
    candidate_tree: str
    comparison_commits: tuple[str, ...]
    comparison_trees: tuple[str, ...]
    selection_method: str
    target_commit: str | None = None
    merge_base: str | None = None
    inventory_introduction: str | None = None
    worktree_predecessor: str | None = None
    audited_commits: tuple[str, ...] = ()
    audited_trees: tuple[str, ...] = ()
    audited_lineages: tuple[tuple[str, ...], ...] = ()

    def as_dict(self) -> dict[str, object]:
        comparison: dict[str, object] = {
            "method": self.selection_method,
            "commits": list(self.comparison_commits),
            "trees": list(self.comparison_trees),
            "audited_commits": list(self.audited_commits or self.comparison_commits),
            "audited_trees": list(self.audited_trees or self.comparison_trees),
            "audited_lineages": [list(lineage) for lineage in self.audited_lineages],
        }
        if self.target_commit is not None:
            comparison["target_commit"] = self.target_commit
        if self.merge_base is not None:
            comparison["merge_base"] = self.merge_base
        if self.inventory_introduction is not None:
            comparison["inventory_introduction"] = self.inventory_introduction
        if self.worktree_predecessor is not None:
            comparison["worktree_predecessor"] = self.worktree_predecessor
        return {
            "schema": HISTORY_SCHEMA,
            "inventory_path": self.inventory_path,
            "candidate": {"commit": self.candidate_commit, "tree": self.candidate_tree},
            "comparison_basis": comparison,
        }


def _run_git(
    repo_root: Path,
    arguments: Sequence[str],
    runner: GitRunner,
    *,
    text: bool = True,
) -> subprocess.CompletedProcess[Any]:
    try:
        return runner(
            ["git", *arguments],
            cwd=repo_root,
            capture_output=True,
            check=False,
            timeout=60,
            text=text,
            env=os.environ | {"GIT_NO_REPLACE_OBJECTS": "1"},
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise HistoryValidationError(
            f"unsupported history: Git command failed ({arguments[0]})"
        ) from error


def _text_output(completed: subprocess.CompletedProcess[Any]) -> str:
    output = completed.stdout
    if isinstance(output, bytes):
        try:
            return output.decode("utf-8")
        except UnicodeDecodeError as error:
            raise HistoryValidationError("unsupported history: Git output is not UTF-8") from error
    return output if isinstance(output, str) else ""


def _required_sha(completed: subprocess.CompletedProcess[Any], label: str) -> str:
    if completed.returncode != 0:
        raise HistoryValidationError(f"unsupported history: cannot resolve {label}")
    value = _text_output(completed).strip()
    if not SHA_PATTERN.fullmatch(value):
        raise HistoryValidationError(f"unsupported history: {label} is not an immutable commit")
    return value


def _resolve_commit(
    repo_root: Path, reference: str, runner: GitRunner, label: str
) -> str:
    return _required_sha(
        _run_git(repo_root, ["rev-parse", "--verify", f"{reference}^{{commit}}"], runner),
        label,
    )


def _resolve_tree(repo_root: Path, commit: str, runner: GitRunner, label: str) -> str:
    return _required_sha(
        _run_git(repo_root, ["rev-parse", "--verify", f"{commit}^{{tree}}"], runner),
        label,
    )


def _parents(repo_root: Path, commit: str, runner: GitRunner) -> tuple[str, ...]:
    completed = _run_git(repo_root, ["show", "-s", "--format=%P", commit], runner)
    if completed.returncode != 0:
        raise HistoryValidationError("unsupported history: candidate parents cannot be read")
    values = _text_output(completed).split()
    if any(not SHA_PATTERN.fullmatch(value) for value in values):
        raise HistoryValidationError("unsupported history: candidate parent is not immutable")
    return tuple(values)


def inventory_blob(
    repo_root: Path, commit: str, path: str, runner: GitRunner
) -> bytes | None:
    """Read one immutable inventory blob, distinguishing absence from failure."""
    listed = _run_git(repo_root, ["ls-tree", "-z", commit, "--", path], runner, text=False)
    if listed.returncode != 0:
        raise HistoryValidationError("unsupported history: predecessor inventory tree cannot be read")
    output = listed.stdout
    if isinstance(output, str):
        output = output.encode("utf-8")
    if not isinstance(output, bytes):
        output = b""
    if not output:
        return None
    shown = _run_git(repo_root, ["show", f"{commit}:{path}"], runner, text=False)
    if shown.returncode != 0:
        raise HistoryValidationError("unsupported history: predecessor inventory cannot be read")
    if isinstance(shown.stdout, bytes):
        return shown.stdout
    if isinstance(shown.stdout, str):
        return shown.stdout.encode("utf-8")
    raise HistoryValidationError("unsupported history: predecessor inventory is unreadable")


def validate_inventory_introduction(
    repo_root: Path,
    candidate: str,
    inventory_path: str,
    runner: GitRunner,
) -> str | None:
    """Prove the first reachable inventory commit, or a new worktree file."""
    completed = _run_git(
        repo_root,
        ["log", "--format=%H", "--full-history", "--reverse", candidate, "--", inventory_path],
        runner,
    )
    if completed.returncode != 0:
        raise HistoryValidationError("unsupported history: inventory introduction cannot be established")
    commits = tuple(_text_output(completed).split())
    if not commits:
        if (repo_root / inventory_path).is_file():
            return "worktree"
        raise HistoryValidationError("unsupported history: inventory introduction boundary is missing")
    if any(not SHA_PATTERN.fullmatch(commit) for commit in commits):
        raise HistoryValidationError("unsupported history: inventory introduction boundary is missing")
    introduction = commits[0]
    if inventory_blob(repo_root, introduction, inventory_path, runner) is None:
        raise HistoryValidationError("unsupported history: inventory introduction boundary is invalid")
    for parent in _parents(repo_root, introduction, runner):
        if inventory_blob(repo_root, parent, inventory_path, runner) is not None:
            raise HistoryValidationError("unsupported history: inventory introduction boundary is invalid")
    ancestor = _run_git(
        repo_root,
        ["merge-base", "--is-ancestor", introduction, candidate],
        runner,
    )
    if ancestor.returncode != 0:
        raise HistoryValidationError("unsupported history: inventory introduction is outside candidate lineage")
    return introduction


def resolve_history_basis(
    repo_root: Path,
    inventory_path: Path,
    *,
    git_runner: GitRunner = subprocess.run,
    context: HistoryContext | None = None,
) -> HistoryBasis:
    """Resolve a candidate and immutable predecessor identities without fetching."""
    try:
        relative = inventory_path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError as error:
        raise HistoryValidationError(
            "unsupported history: inventory path is outside the repository"
        ) from error
    shallow = _run_git(
        repo_root, ["rev-parse", "--is-shallow-repository"], git_runner
    )
    if shallow.returncode != 0 or _text_output(shallow).strip() != "false":
        raise HistoryValidationError("unsupported history: shallow or incomplete Git history")
    from ci.python_retention_history_git_context import event_context, target_commit
    from ci.python_retention_history_git_lineage import (
        inventory_history,
        merge_base as resolve_merge_base,
    )

    selected_context = context or event_context()
    candidate = _resolve_commit(
        repo_root, selected_context.candidate_ref, git_runner, "candidate commit"
    )
    github_sha = selected_context.github_candidate_sha
    if github_sha:
        if not SHA_PATTERN.fullmatch(github_sha):
            raise HistoryValidationError(
                "unsupported history: GitHub candidate identity is not immutable"
            )
        if github_sha != candidate:
            raise HistoryValidationError(
                "unsupported history: GitHub candidate identity differs from HEAD"
            )
    tree = _resolve_tree(repo_root, candidate, git_runner, "candidate tree")
    parents = _parents(repo_root, candidate, git_runner)
    is_merge = selected_context.pull_request_merge
    if is_merge is None:
        is_merge = len(parents) > 1
    target = None
    merge_base = None
    introduction = None
    audited: list[str] = []
    audited_lineages: list[tuple[str, ...]] = []
    if is_merge:
        if len(parents) < 2:
            raise HistoryValidationError("unsupported history: pull-request merge has no merge parents")
        comparison = parents
        method = "pull-request-merge-parents"
        lineage_base = resolve_merge_base(repo_root, parents, git_runner)
        merge_base = lineage_base
        if lineage_base not in audited:
            audited.append(lineage_base)
        for parent in parents:
            lineage = [lineage_base, *inventory_history(
                repo_root,
                parent,
                relative,
                git_runner,
                lower=lineage_base,
            )]
            audited_lineages.append(tuple(dict.fromkeys(lineage)))
            for commit in lineage:
                if commit not in audited:
                    audited.append(commit)
    else:
        target = target_commit(repo_root, selected_context, git_runner)
        if target is not None:
            merge_completed = _run_git(
                repo_root, ["merge-base", candidate, target], git_runner
            )
            merge_base = _required_sha(merge_completed, "candidate target merge-base")
            comparison = (merge_base,)
            method = "target-merge-base"
            lineage = [merge_base]
            if parents:
                lineage.extend(
                    inventory_history(
                        repo_root,
                        parents[0],
                        relative,
                        git_runner,
                        lower=merge_base,
                    )
                )
            lineage = list(dict.fromkeys(lineage))
            audited_lineages.append(tuple(lineage))
            audited.extend(commit for commit in lineage if commit not in audited)
        elif parents:
            comparison = (parents[0],)
            method = "first-parent"
            lineage = list(inventory_history(
                repo_root, parents[0], relative, git_runner, first_parent=True
            ))
            audited_lineages.append(tuple(lineage))
            audited.extend(lineage)
        else:
            introduction = validate_inventory_introduction(repo_root, candidate, relative, git_runner)
            comparison = ()
            method = "inventory-introduction"
    if any(commit == candidate for commit in comparison):
        raise HistoryValidationError(
            "unsupported history: comparison basis resolves to candidate itself"
        )
    if any(commit == candidate for commit in audited):
        raise HistoryValidationError(
            "unsupported history: audited lineage resolves to candidate itself"
        )
    worktree_predecessor = None
    try:
        worktree = inventory_path.read_bytes()
    except OSError:
        worktree = None
    committed_inventory = inventory_blob(repo_root, candidate, relative, git_runner)
    if worktree != committed_inventory:
        # A dirty candidate is checked against HEAD in addition to the
        # immutable committed-candidate lineage selected above.
        worktree_predecessor = candidate
    trees = tuple(
        _resolve_tree(repo_root, commit, git_runner, "comparison tree")
        for commit in comparison
    )
    audited_trees = tuple(
        _resolve_tree(repo_root, commit, git_runner, "audited lineage tree")
        for commit in audited
    )
    return HistoryBasis(
        inventory_path=relative,
        candidate_commit=candidate,
        candidate_tree=tree,
        comparison_commits=tuple(comparison),
        comparison_trees=trees,
        selection_method=method,
        target_commit=target,
        merge_base=merge_base,
        inventory_introduction=introduction,
        worktree_predecessor=worktree_predecessor,
        audited_commits=tuple(audited),
        audited_trees=audited_trees,
        audited_lineages=tuple(audited_lineages),
    )


__all__ = [
    "GitRunner",
    "HISTORY_SCHEMA",
    "HistoryBasis",
    "HistoryContext",
    "HistoryValidationError",
    "SHA_PATTERN",
    "inventory_blob",
    "resolve_history_basis",
    "validate_inventory_introduction",
]
