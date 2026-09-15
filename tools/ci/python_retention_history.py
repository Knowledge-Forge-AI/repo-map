"""Validate retained-Python inventory history against an immutable predecessor."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Mapping, Sequence

from ci.python_retention_history_git import (
    GitRunner,
    HistoryBasis,
    HistoryContext,
    HistoryValidationError,
    inventory_blob,
    resolve_history_basis,
    validate_inventory_introduction,
)
from ci.python_retention_cohorts import (
    validate_cohort_transition,
    validate_cohorts,
)



# The inventory owner may import this name while preserving its public error API.
InventoryValidationError = HistoryValidationError


class PathHistoryResult(list[dict[str, Any]]):
    """Removed history records with non-lossy predecessor evidence attached."""

    def __init__(self, records: Sequence[dict[str, Any]], evidence: Mapping[str, object]) -> None:
        super().__init__(records)
        self.evidence = dict(evidence)


def _parse_history(data: Mapping[str, Any]) -> tuple[
    dict[str, dict[str, Any]], dict[str, list[str]], list[dict[str, Any]], list[dict[str, Any]]
]:
    transitions = data.get("path_transitions", [])
    decompositions = data.get("decompositions", [])
    if not isinstance(transitions, list):
        raise HistoryValidationError("invalid path transition history")
    if not isinstance(decompositions, list):
        raise HistoryValidationError("invalid decomposition history")
    by_old: dict[str, dict[str, Any]] = {}
    targets: dict[str, list[str]] = {}

    def parse_entry(entry: Any, label: str, allow_none: bool) -> tuple[str, list[str]]:
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("from"), str)
            or not entry["from"].strip()
            or "to" not in entry
            or not isinstance(entry.get("rationale"), str)
            or not entry["rationale"].strip()
            or entry["from"] in by_old
        ):
            raise HistoryValidationError(f"invalid or duplicate {label}")
        to = entry.get("to")
        if to is None and allow_none:
            return entry["from"], []
        if isinstance(to, str) and to.strip():
            return entry["from"], [to]
        if isinstance(to, list) and to and all(isinstance(item, str) and item.strip() for item in to):
            return entry["from"], list(to)
        raise HistoryValidationError(f"invalid or duplicate {label}")

    for entries, label, allow_none in (
        (transitions, "path transition", True),
        (decompositions, "decomposition", False),
    ):
        for entry in entries:
            source, successors = parse_entry(entry, label, allow_none)
            by_old[source] = entry
            targets[source] = successors
    return by_old, targets, transitions, decompositions


def _load_document(blob: bytes | None) -> dict[str, Any]:
    if blob is None:
        return {"files": []}
    try:
        loaded = json.loads(blob.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HistoryValidationError("prior inventory cannot be read") from error
    if not isinstance(loaded, dict) or not isinstance(loaded.get("files"), list):
        raise HistoryValidationError("prior inventory cannot be read")
    paths: set[str] = set()
    for entry in loaded["files"]:
        path = entry.get("path") if isinstance(entry, dict) else None
        if (
            not isinstance(path, str)
            or not path.strip()
            or not path.endswith(".py")
            or Path(path).is_absolute()
            or ".." in Path(path).parts
            or path in paths
        ):
            raise HistoryValidationError("prior inventory cannot be read")
        paths.add(path)
    return loaded


def _subsequence(older: Sequence[dict[str, Any]], newer: Sequence[dict[str, Any]]) -> bool:
    position = 0
    for entry in newer:
        if position < len(older) and entry == older[position]:
            position += 1
    return position == len(older)


def _resolve_chain(
    start: str,
    current: set[str],
    targets: Mapping[str, Sequence[str]],
) -> set[str]:
    leaves: set[str] = set()

    def walk(node: str, visiting: set[str]) -> None:
        if node in visiting:
            raise HistoryValidationError(f"cyclic successor chain detected: {start}")
        if node in current:
            leaves.add(node)
            return
        if node not in targets:
            raise HistoryValidationError(
                f"removed path requires explicit scope history: {node}"
            )
        successors = targets[node]
        if not successors:
            return  # An explicit ``to: null`` is a valid terminated leaf.
        next_visiting = visiting | {node}
        for successor in successors:
            walk(successor, next_visiting)

    for successor in targets.get(start, ()):
        walk(successor, {start})
    return leaves


def _protected(old_entry: Mapping[str, Any]) -> bool:
    confidence = old_entry.get("confidence")
    return (
        old_entry.get("maintained_executable") is True
        and not isinstance(confidence, bool)
        and isinstance(confidence, (int, float))
        and confidence >= 0.8
    )


def _check_protection(
    old_entry: Mapping[str, Any], current_entry: Mapping[str, Any] | None, source: str
) -> None:
    if not _protected(old_entry):
        return
    confidence = current_entry.get("confidence") if current_entry else None
    if (
        current_entry is None
        or current_entry.get("maintained_executable") is not True
        or isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or confidence < 0.8
    ):
        raise HistoryValidationError(
            f"confidence drop cannot discard prior protection: {source}"
        )


def validate_path_history(
    repo_root: Path,
    inventory_path: Path,
    current: set[str],
    data: Mapping[str, Any],
    *,
    git_runner: GitRunner = subprocess.run,
    context: HistoryContext | None = None,
) -> PathHistoryResult:
    """Validate append-only path lineage and protected predecessor coverage."""
    by_old, targets, transitions, decompositions = _parse_history(data)
    current_files = {
        entry["path"]: entry
        for entry in data.get("files", [])
        if isinstance(entry, dict) and isinstance(entry.get("path"), str)
    }
    for source, successors in targets.items():
        if not successors and source in current:
            raise HistoryValidationError(
                f"terminal lineage cannot exempt living eligible path: {source}"
            )

    basis = resolve_history_basis(
        repo_root, inventory_path, git_runner=git_runner, context=context
    )
    previous_documents: list[dict[str, Any]] = []
    audited_revisions: list[dict[str, object]] = []
    introduction = basis.inventory_introduction
    audited_commits = basis.audited_commits or basis.comparison_commits
    audited_tree_values = basis.audited_trees or basis.comparison_trees
    predecessor_commits = list(audited_commits)
    audited_trees = dict(zip(audited_commits, audited_tree_values))
    if basis.worktree_predecessor is not None and basis.worktree_predecessor not in predecessor_commits:
        predecessor_commits.append(basis.worktree_predecessor)
    documents_by_commit: dict[str, dict[str, Any]] = {}
    for commit in predecessor_commits:
        blob = inventory_blob(repo_root, commit, basis.inventory_path, git_runner)
        if blob is None:
            # An absent predecessor is valid only after complete-history proof.
            introduction = introduction or validate_inventory_introduction(
                repo_root, basis.candidate_commit, basis.inventory_path, git_runner
            )
        document = _load_document(blob)
        documents_by_commit[commit] = document
        previous_documents.append(document)
        audited_revisions.append(
            {
                "commit": commit,
                "tree": (
                    basis.candidate_tree
                    if commit == basis.worktree_predecessor
                    else audited_trees[commit]
                ),
                "inventory_sha256": hashlib.sha256(blob).hexdigest() if blob is not None else None,
                "path_transition_count": len(document.get("path_transitions", [])),
                "decomposition_count": len(document.get("decompositions", [])),
            }
        )
    lineages = basis.audited_lineages
    if not lineages and audited_commits:
        lineages = (tuple(audited_commits),)
    for lineage in lineages:
        for older_commit, newer_commit in zip(lineage, lineage[1:]):
            older = documents_by_commit[older_commit]
            newer = documents_by_commit[newer_commit]
            _, _, older_transitions, older_decompositions = _parse_history(older)
            _, _, newer_transitions, newer_decompositions = _parse_history(newer)
            if not _subsequence(older_transitions, newer_transitions) or not _subsequence(
                older_decompositions, newer_decompositions
            ):
                raise HistoryValidationError(
                    "inventory lineage history is not append-only"
                )
            validate_cohort_transition(older, newer)
    for document in previous_documents:
        _, _, old_transitions, old_decompositions = _parse_history(document)
        if not _subsequence(old_transitions, transitions) or not _subsequence(
            old_decompositions, decompositions
        ):
            raise HistoryValidationError("inventory lineage history is not append-only")
        validate_cohort_transition(document, data)
    if not previous_documents:
        validate_cohorts(data)

    old_entries: dict[str, list[dict[str, Any]]] = {}
    for document in previous_documents:
        for entry in document["files"]:
            old_entries.setdefault(entry["path"], []).append(entry)
    old_paths = set(old_entries)
    referenced = {
        successor
        for successors in targets.values()
        for successor in successors
    }
    for source in set(by_old) - referenced:
        if source not in current and source not in old_paths:
            raise HistoryValidationError(
                f"lineage source lacks predecessor evidence: {source}"
            )
    for path in sorted(old_paths - current):
        entry = by_old.get(path)
        if entry is None:
            raise HistoryValidationError(
                f"removed path requires explicit scope history: {path}"
            )
        if targets[path]:
            _resolve_chain(path, current, targets)
    for path, entries in old_entries.items():
        if path in current:
            for entry in entries:
                _check_protection(entry, current_files.get(path), path)
    for source, successors in targets.items():
        if not successors:
            continue
        leaves = _resolve_chain(source, current, targets)
        source_entries = old_entries.get(source, [])
        if not source_entries and source in current_files:
            source_entries = [current_files[source]]
        for old_entry in source_entries:
            for leaf in leaves:
                _check_protection(old_entry, current_files.get(leaf), source)
    records = [by_old[path] for path in sorted(old_paths - current) if path in by_old]
    evidence = basis.as_dict()
    evidence["candidate_inventory_sha256"] = (
        hashlib.sha256(inventory_path.read_bytes()).hexdigest()
        if inventory_path.is_file()
        else None
    )
    comparison_evidence = evidence.get("comparison_basis")
    if not isinstance(comparison_evidence, dict):
        raise HistoryValidationError("history evidence comparison basis is invalid")
    comparison_evidence["audited_revisions"] = audited_revisions
    if introduction is not None:
        comparison_evidence["inventory_introduction"] = introduction
    return PathHistoryResult(records, evidence)


__all__ = [
    "HistoryBasis",
    "HistoryContext",
    "HistoryValidationError",
    "InventoryValidationError",
    "PathHistoryResult",
    "resolve_history_basis",
    "validate_inventory_introduction",
    "validate_path_history",
]
