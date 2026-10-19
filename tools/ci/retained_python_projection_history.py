"""Append-only proof authority and complete evidence-set checks."""

from __future__ import annotations

import hashlib
from pathlib import Path

from ci.retained_python_git import blob, git_required, parents
from ci.retained_python_projection_evidence import (
    EVIDENCE_PATH, PROOFS_PATH, parse_proofs, read_file, require,
)


def evidence_paths(proofs: list[dict]) -> set[str]:
    paths: list[str] = []
    for proof in proofs:
        for state in proof["states"][1:-1]:
            paths.extend(f"{EVIDENCE_PATH}/{state[field]}.json"
                         for field in ("baseline_sha256", "ownership_sha256"))
    require(len(paths) == len(set(paths)), "contains duplicate evidence references")
    return set(paths)


def validate_material(root: Path, proofs: list[dict], revision: str | None) -> None:
    expected = evidence_paths(proofs)
    if revision is None:
        directory = root / EVIDENCE_PATH
        actual = {p.relative_to(root).as_posix() for p in directory.rglob("*")
                  if not p.is_dir() or p.is_symlink()} if directory.exists() else set()
    else:
        actual = set(git_required(root, "ls-tree", "-r", "--name-only", revision,
                                 "--", EVIDENCE_PATH).splitlines())
    require(actual == expected, "evidence set is missing or unused")
    for path in expected:
        content = read_file(root, path) if revision is None else blob(root, revision, path)
        require(content is not None, "evidence is missing")
        assert content is not None
        require(hashlib.sha256(content).hexdigest() == Path(path).stem, "evidence digest mismatch")
    for proof in proofs:
        path = proof["decision"]
        content = read_file(root, path) if revision is None else blob(root, revision, path)
        require(content is not None, "decision is missing")
        assert content is not None
        require(proof["proof"].encode() in content, "decision lacks proof identifier")


def extension(before: list[dict], after: list[dict]) -> None:
    require(after[:len(before)] == before, "authority is not append-only")


def load_history(root: Path, head: str, genesis: str) -> list[dict]:
    """Inspect all versions, including deletion/reintroduction and divergent merges."""
    revisions = git_required(root, "log", "--full-history", "--reverse", "--format=%H",
                             head, "--", PROOFS_PATH, EVIDENCE_PATH).splitlines()
    versions: dict[str, list[dict]] = {}

    def at(revision: str) -> list[dict]:
        if revision not in versions:
            versions[revision] = parse_proofs(blob(root, revision, PROOFS_PATH))
        return versions[revision]

    for revision in revisions:
        current = at(revision)
        for parent in parents(root, revision):
            extension(at(parent), current)
        validate_material(root, current, revision)
    target = root / PROOFS_PATH
    current = parse_proofs(read_file(root, PROOFS_PATH) if target.exists() else None)
    extension(at(head), current)
    # Check all reachable prior versions even when a merge drops a side-branch proof.
    for previous in versions.values():
        extension(previous, current)
    validate_material(root, current, None)
    return current


def projection_governing_paths(root: Path) -> set[Path]:
    path = root / PROOFS_PATH
    proofs = parse_proofs(read_file(root, PROOFS_PATH) if path.exists() else None)
    paths = {root / relative for relative in evidence_paths(proofs)}
    paths.update(root / proof["decision"] for proof in proofs)
    if path.exists():
        paths.add(path)
    validate_material(root, proofs, None)
    return paths
