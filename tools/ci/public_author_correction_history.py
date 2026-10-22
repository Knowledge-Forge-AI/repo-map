"""Authenticated old-to-new commit bridge for corrected public history (ADR 0085)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from ci.public_author_correction import (
    DECISION, PROOF_ID, PROOF_PATH, WITNESS, object_id, parents, parse_commit, parse_proof,
    reconstruct, require, witness_author,
)
from ci.retained_python_git import blob, git_required, is_ancestor, raw_commit
from ci.retained_python_projection_evidence import PROOFS_PATH, parse_proofs, read_file
from ci.retained_python_records import is_repository_path


@dataclass(frozen=True)
class AuthorCorrection:
    """Exact original-to-corrected IDs; unmapped revisions are ordinary current IDs."""

    new_by_old: Mapping[str, str] = field(default_factory=dict)

    def resolve(self, revision: str) -> str:
        return self.new_by_old.get(revision, revision)


def _read(root: Path, path: str) -> bytes | None:
    target = root / path
    if not target.exists() and not target.is_symlink():
        return None
    require(is_repository_path(path) and target.resolve() == root.resolve() / path
            and not target.is_symlink() and target.is_file(), "material path is aliased")
    return target.read_bytes()


def _governing(root: Path) -> bytes | None:
    current = _read(root, PROOF_PATH)
    if current is not None:
        parse_proof(current)
        decision = _read(root, DECISION)
        require(decision is not None and PROOF_ID.encode() in decision, "decision is missing")
    return current


def author_correction_governing_paths(root: Path) -> set[Path]:
    return set() if _governing(root) is None else {root / PROOF_PATH, root / DECISION}


def _witness(root: Path, old: str) -> bytes:
    """Fixed source: the recovered author of the published projection edge at ``old``."""
    present = (root / PROOFS_PATH).exists()
    proofs = parse_proofs(read_file(root, PROOFS_PATH) if present else None)
    matches = [proof for proof in proofs if proof["commit"] == old]
    require(len(matches) == 1, "witness edge is missing or ambiguous")
    authors = {witness_author(hop["source_objects"]["commit"])
               for hop in matches[0]["hops"] if "source_objects" in hop}
    require(len(authors) == 1, "witness author is missing or ambiguous")
    return authors.pop()


def load_author_correction(root: Path, head: str) -> AuthorCorrection:
    """Authenticate every corrected and original object before any old ID is resolved.

    Absent and never-committed proof material leaves ordinary repositories unchanged.
    Original objects are never read, so their presence cannot shortcut validation.
    """
    current = _governing(root)
    introduced = git_required(root, "log", "--full-history", "--format=%H", head, "--",
                              PROOF_PATH).splitlines()
    for revision in introduced:
        require(blob(root, revision, PROOF_PATH) == current, "changed or was deleted after introduction")
    if current is None:
        return AuthorCorrection()
    require(git_required(root, "rev-parse", "--show-object-format") == "sha1",
            "requires SHA-1 object IDs")
    proof = parse_proof(current)
    old_by_new = {row.new: row.old for row in proof.rows}
    commits = {}
    for row in proof.rows:
        payload = raw_commit(root, row.new)
        require(payload is not None and object_id(payload) == row.new,
                "corrected object is missing or forged")
        assert payload is not None
        commit = parse_commit(payload)
        lineage = parents(commit)
        require(all(parent in old_by_new for parent in lineage), "parent is outside the corrected range")
        require(all(parent in commits for parent in lineage), "rows are not ordered parent-first")
        reconstruct(commit, row, old_by_new, _witness(root, row.old) if row.source == WITNESS else None)
        commits[row.new] = commit
    require(old_by_new.get(proof.new_tip) == proof.old_tip, "tip mapping is invalid")
    reachable: set[str] = set()
    pending = [proof.new_tip]
    while pending:
        revision = pending.pop()
        if revision not in reachable:
            reachable.add(revision)
            pending.extend(parents(commits[revision]))
    require(reachable == set(commits), "contains rows outside the corrected tip closure")
    require(is_ancestor(root, proof.new_tip, head), "corrected tip is outside HEAD ancestry")
    return AuthorCorrection({row.old: row.new for row in proof.rows})
