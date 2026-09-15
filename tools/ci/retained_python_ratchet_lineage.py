#!/usr/bin/env python3
"""Audit retained-Python baselines against complete repository lineage."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Callable, Mapping, Sequence

if __package__ in (None, ""):
    tools_root = Path(__file__).resolve().parents[1]
    if str(tools_root) not in sys.path:
        sys.path.insert(0, str(tools_root))

from ci.retained_python_contract import (
    RatchetContractError,
    validate_baseline,
)
from ci.retained_python_comparison import (
    additions_have_debt,
    compare_counted as compare_counted,
    compare_file_lengths as compare_file_lengths,
    has_upward_debt,
    selection_delta,
)
from ci.retained_python_records import (
    BaselineDocument,
    RecordValidationError,
    ScopeRegistry,
    ScopeSelection,
    ScopeTransitionRecord,
    is_repository_path,
    render_document,
    scope_record_key,
    validate_scope_registry_records,
)


TRUSTED_GENESIS_BASELINE_SHA256 = "f891e37dd72e54cdcd9aa72a9544aa8df83e46a5ea436eb08dd5822709bfdf18"
PUBLIC_GENESIS_BASELINE_SHA256 = "e6a4830df94a210d83da9e37bce147eb3891d74a7868e50cfc1c648d858475f4"
ACCEPTED_GENESIS_BASELINE_SHA256S = frozenset({TRUSTED_GENESIS_BASELINE_SHA256, PUBLIC_GENESIS_BASELINE_SHA256})
SCOPE_TRANSITIONS_SCHEMA = "repomap-retained-python-scope-transitions-v1"
DEFAULT_SCOPE_TRANSITIONS = Path("tools/ci/retained_python_scope_transitions.json")


_selection_delta = selection_delta


class LineagePolicyError(RatchetContractError):
    """A candidate attempted a forbidden baseline or scope transition."""


@dataclass(frozen=True)
class LineageAudit:
    genesis_sha256: str
    committed_transitions: int
    scope_transitions: int
    candidate_transition: bool


def document_sha256(document: Mapping[str, object]) -> str:
    return hashlib.sha256(render_document(document).encode()).hexdigest()


def selection_digest(document: BaselineDocument) -> str:
    modules = document["selection"]["modules"]
    encoded = json.dumps(
        modules, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


_record_key = scope_record_key


def validate_scope_registry(document: object) -> tuple[ScopeTransitionRecord, ...]:
    try:
        return validate_scope_registry_records(
            document,
            schema=SCOPE_TRANSITIONS_SCHEMA,
        )
    except RecordValidationError as error:
        raise LineagePolicyError(str(error)) from error


def _repository_path(value: object) -> str:
    if not is_repository_path(value):
        raise RatchetContractError("lineage path is invalid")
    assert isinstance(value, str)
    return value


def _assert_clean_additions(
    additions: Sequence[ScopeSelection], after: BaselineDocument
) -> None:
    if additions_have_debt(additions, after):
        raise LineagePolicyError("new retained module is not clean")


def _has_upward_debt(
    before: BaselineDocument, after: BaselineDocument
) -> bool:
    return has_upward_debt(before, after)


def audit_transition(
    before: BaselineDocument,
    after: BaselineDocument,
    registry: object,
    authority_reader: Callable[[str], str | None],
) -> tuple[str, str, str, str] | None:
    validate_baseline(before)
    validate_baseline(after)
    if before["tools"] != after["tools"]:
        raise LineagePolicyError("ratchet tool policy changed")
    for field in ("ownership_classes", "tiers"):
        if before["selection"][field] != after["selection"][field]:
            raise LineagePolicyError("retained selection policy changed")
    changes, additions, restricted = _selection_delta(before, after)
    _assert_clean_additions(additions, after)
    if _has_upward_debt(before, after):
        raise LineagePolicyError("baseline transition increased debt")
    ownership_changed = before["ownership"] != after["ownership"]
    if not restricted and not ownership_changed:
        return None
    key = (
        str(before["ownership"]["sha256"]),
        str(after["ownership"]["sha256"]),
        selection_digest(before),
        selection_digest(after),
    )
    matches = [record for record in validate_scope_registry(registry) if _record_key(record) == key]
    if len(matches) != 1:
        raise LineagePolicyError("scope transition lacks exact authority")
    record = matches[0]
    if record["changes"] != changes:
        raise LineagePolicyError("scope transition record is overbroad or incomplete")
    status = authority_reader(str(record["status_path"]))
    if (
        status is None
        or str(record["phase"]) not in status
        or "Exit" not in status.splitlines()[0]
    ):
        raise LineagePolicyError("scope transition status authority is invalid")
    return key


def _git(
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


def _git_required(repo_root: Path, *args: str) -> str:
    completed = _git(repo_root, args)
    if completed.returncode != 0:
        raise RatchetContractError("Git history inspection failed")
    return completed.stdout.strip()


def _blob(repo_root: Path, commit: str, path: str) -> bytes | None:
    listed = _git(repo_root, ("ls-tree", "-z", commit, "--", path), text=False)
    if listed.returncode != 0:
        raise RatchetContractError("Git tree inspection failed")
    if not listed.stdout:
        return None
    shown = _git(repo_root, ("show", f"{commit}:{path}"), text=False)
    if shown.returncode != 0:
        raise RatchetContractError("Git blob inspection failed")
    return shown.stdout


def _commit_authority(repo_root: Path, commit: str, path: str) -> str | None:
    blob = _blob(repo_root, commit, path)
    return blob.decode("utf-8") if blob is not None else None


def _document(blob: bytes | None, label: str) -> BaselineDocument | None:
    if blob is None:
        return None
    try:
        document = json.loads(blob.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RatchetContractError(f"{label} JSON is invalid") from error
    validate_baseline(document)
    return document


def _registry(blob: bytes | None) -> ScopeRegistry:
    if blob is None:
        return {"schema": SCOPE_TRANSITIONS_SCHEMA, "records": []}
    try:
        document = json.loads(blob.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise LineagePolicyError("scope transition registry JSON is invalid") from error
    validate_scope_registry(document)
    return document


def _parents(repo_root: Path, commit: str) -> tuple[str, ...]:
    output = _git_required(repo_root, "show", "-s", "--format=%P", commit)
    return tuple(output.split()) if output else ()


def _is_ancestor(repo_root: Path, ancestor: str, descendant: str) -> bool:
    completed = _git(repo_root, ("merge-base", "--is-ancestor", ancestor, descendant))
    if completed.returncode not in {0, 1}:
        raise RatchetContractError("Git ancestry inspection failed")
    return completed.returncode == 0


def _is_redundant_ancestor_merge_parent(
    repo_root: Path,
    *,
    parent: str,
    other_parents: Sequence[str],
    current_baseline_blob: bytes,
    current_scopes_blob: bytes | None,
    baseline: str,
    scopes: str,
    genesis: str,
) -> bool:
    for carrier in other_parents:
        if carrier != genesis and not _is_ancestor(repo_root, genesis, carrier):
            continue
        if not _is_ancestor(repo_root, parent, carrier):
            continue
        if _blob(repo_root, carrier, baseline) != current_baseline_blob:
            continue
        if _blob(repo_root, carrier, scopes) != current_scopes_blob:
            continue
        return True
    return False


def _change_commits(repo_root: Path, path: str) -> tuple[str, ...]:
    output = _git_required(
        repo_root, "log", "--format=%H", "--full-history", "--reverse", "HEAD", "--", path
    )
    return tuple(output.splitlines()) if output else ()


def _read_worktree_registry(repo_root: Path, path: str) -> ScopeRegistry:
    candidate = repo_root / path
    if not candidate.exists():
        return {"schema": SCOPE_TRANSITIONS_SCHEMA, "records": []}
    try:
        document = json.loads(candidate.read_text(encoding="utf-8"))
    except OSError as error:
        raise RatchetContractError("scope transition registry is unreadable") from error
    except json.JSONDecodeError as error:
        raise LineagePolicyError("scope transition registry JSON is invalid") from error
    validate_scope_registry(document)
    return document


def _assert_registry_extension(
    before: ScopeRegistry, after: ScopeRegistry
) -> None:
    old = validate_scope_registry(before)
    new = validate_scope_registry(after)
    if tuple(new[: len(old)]) != old:
        raise LineagePolicyError("scope transition registry is not append-only")


def audit_candidate_lineage(
    repo_root: Path,
    baseline_path: Path,
    candidate: BaselineDocument,
    scope_path: Path = DEFAULT_SCOPE_TRANSITIONS,
    *,
    trusted_genesis_sha256: str = TRUSTED_GENESIS_BASELINE_SHA256,
) -> LineageAudit:
    validate_baseline(candidate)
    baseline = _repository_path(baseline_path.as_posix())
    scopes = _repository_path(scope_path.as_posix())
    if _git_required(repo_root, "rev-parse", "--is-shallow-repository") != "false":
        raise RatchetContractError("shallow Git history cannot establish baseline lineage")
    head = _git_required(repo_root, "rev-parse", "HEAD")
    commits = _change_commits(repo_root, baseline)
    baseline_commits = [
        commit for commit in commits if _blob(repo_root, commit, baseline) is not None
    ]
    genesis_candidates = [
        commit
        for commit in baseline_commits
        if not any(
            prior != commit and _is_ancestor(repo_root, prior, commit)
            for prior in baseline_commits
        )
    ]
    if len(genesis_candidates) != 1:
        raise RatchetContractError("baseline genesis is missing or non-unique")
    genesis = genesis_candidates[0]
    genesis_blob = _blob(repo_root, genesis, baseline)
    assert genesis_blob is not None
    genesis_digest = hashlib.sha256(genesis_blob).hexdigest()
    if (
        genesis_digest != trusted_genesis_sha256
        and genesis_digest not in ACCEPTED_GENESIS_BASELINE_SHA256S
    ):
        raise RatchetContractError("baseline genesis digest is untrusted")

    used: set[tuple[str, str, str, str]] = set()
    committed_transitions = 0
    for commit in commits:
        if commit == genesis or not _is_ancestor(repo_root, genesis, commit):
            continue
        current_blob = _blob(repo_root, commit, baseline)
        if current_blob is None:
            raise LineagePolicyError("initialized baseline was deleted from history")
        current = _document(current_blob, "baseline")
        assert current is not None
        parents = _parents(repo_root, commit)
        for parent in parents:
            if parent != genesis and not _is_ancestor(repo_root, genesis, parent):
                continue
            prior = _document(_blob(repo_root, parent, baseline), "predecessor baseline")
            if prior is None:
                raise LineagePolicyError("initialized baseline was deleted from history")
            if prior == current:
                continue
            if len(parents) > 1 and _is_redundant_ancestor_merge_parent(
                repo_root,
                parent=parent,
                other_parents=tuple(p for p in parents if p != parent),
                current_baseline_blob=current_blob,
                current_scopes_blob=_blob(repo_root, commit, scopes),
                baseline=baseline,
                scopes=scopes,
                genesis=genesis,
            ):
                continue
            registry = _registry(_blob(repo_root, commit, scopes))
            committed_authority = lambda path: _commit_authority(repo_root, commit, path)
            record = audit_transition(prior, current, registry, committed_authority)
            if record is not None:
                used.add(record)
            committed_transitions += 1

    for commit in _change_commits(repo_root, scopes):
        if not _is_ancestor(repo_root, genesis, commit):
            continue
        current_registry = _registry(_blob(repo_root, commit, scopes))
        for parent in _parents(repo_root, commit):
            if parent != genesis and not _is_ancestor(repo_root, genesis, parent):
                continue
            _assert_registry_extension(
                _registry(_blob(repo_root, parent, scopes)), current_registry
            )

    head_document = _document(_blob(repo_root, head, baseline), "HEAD baseline")
    if head_document is None:
        raise LineagePolicyError("initialized baseline is absent from HEAD")
    committed_registry = _registry(_blob(repo_root, head, scopes))
    candidate_registry = _read_worktree_registry(repo_root, scopes)
    _assert_registry_extension(committed_registry, candidate_registry)
    candidate_transition = head_document != candidate
    if candidate_transition:
        candidate_authority = lambda path: (
            (repo_root / path).read_text(encoding="utf-8")
            if (repo_root / path).is_file()
            else None
        )
        record = audit_transition(
            head_document, candidate, candidate_registry, candidate_authority
        )
        if record is not None:
            used.add(record)
    genesis_registry = _registry(_blob(repo_root, genesis, scopes))
    genesis_keys = {_record_key(record) for record in validate_scope_registry(genesis_registry)}
    candidate_keys = {_record_key(record) for record in validate_scope_registry(candidate_registry)}
    if (candidate_keys - genesis_keys) != used:
        raise LineagePolicyError("scope transition registry contains unused authority")
    return LineageAudit(
        trusted_genesis_sha256,
        committed_transitions,
        len(used),
        candidate_transition,
    )
