"""Narrow Git-authoritative classification for an explicitly scoped candidate."""

from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Sequence


class CandidateClassificationError(RuntimeError):
    """The candidate cannot be classified without guessing."""


@dataclass(frozen=True, slots=True)
class CandidateFile:
    """One path and its exact current content identity."""

    path: str
    sha256: str


@dataclass(frozen=True, slots=True)
class CandidateClassification:
    """The tracked/untracked classes and their bound current content."""

    base_commit: str
    tracked_modified: tuple[str, ...]
    relevant_untracked: tuple[str, ...]
    files: tuple[CandidateFile, ...]


def _run_git(repo_root: Path, arguments: Sequence[str]) -> bytes:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("GIT_")
    }
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), *arguments],
            check=False,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as error:
        raise CandidateClassificationError("unable to run Git") from error
    if completed.returncode != 0:
        raise CandidateClassificationError("Git candidate classification failed")
    return completed.stdout


def _decode_path(encoded: bytes) -> str:
    try:
        path = encoded.decode("utf-8")
    except UnicodeError as error:
        raise CandidateClassificationError("Git returned a non-UTF-8 path") from error
    pure = PurePosixPath(path)
    if pure.is_absolute() or ".." in pure.parts or path in {"", "."}:
        raise CandidateClassificationError("Git returned an unsafe candidate path")
    return pure.as_posix()


def _status_classes(repo_root: Path) -> tuple[set[str], set[str]]:
    output = _run_git(
        repo_root,
        ("status", "--porcelain=v2", "-z", "--untracked-files=all"),
    )
    tracked: set[str] = set()
    untracked: set[str] = set()
    for record in output.split(b"\0"):
        if not record:
            continue
        if record.startswith(b"1 "):
            fields = record.split(b" ", 8)
            if len(fields) != 9:
                raise CandidateClassificationError("malformed Git status record")
            tracked.add(_decode_path(fields[8]))
        elif record.startswith(b"? "):
            untracked.add(_decode_path(record[2:]))
        elif record.startswith(b"2 "):
            raise CandidateClassificationError("candidate rename requires separate review")
        elif record.startswith(b"u "):
            raise CandidateClassificationError("candidate has an unmerged path")
        else:
            raise CandidateClassificationError("unknown Git status record")
    return tracked, untracked


def sha256_file(path: Path) -> str:
    """Return the lowercase SHA-256 identity of one regular file."""
    if path.is_symlink() or not path.is_file():
        raise CandidateClassificationError("candidate path is not a regular file")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(64 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_relevant(paths: Iterable[str]) -> tuple[str, ...]:
    normalized = {_decode_path(os.fsencode(path)) for path in paths}
    return tuple(sorted(normalized))


def classify_candidate_paths(
    repo_root: Path,
    *,
    relevant_untracked: Iterable[str],
) -> CandidateClassification:
    """Classify one explicitly scoped dirty candidate from current Git state.

    Relevance is supplied by the phase owner. This helper only verifies the Git
    class and binds current bytes; it does not invent a universal dirty digest.
    """
    root = repo_root.resolve(strict=True)
    base_commit = _run_git(root, ("rev-parse", "HEAD")).decode("ascii").strip()
    if len(base_commit) != 40 or any(
        character not in "0123456789abcdef" for character in base_commit
    ):
        raise CandidateClassificationError("Git base commit identity is invalid")
    tracked, untracked = _status_classes(root)
    relevant = _normalize_relevant(relevant_untracked)
    missing = set(relevant).difference(untracked)
    if missing:
        raise CandidateClassificationError(
            "declared relevant untracked path is not Git-untracked"
        )
    selected = tuple(sorted(tracked)) + relevant
    files = tuple(
        CandidateFile(path=path, sha256=sha256_file(root / path))
        for path in selected
    )
    return CandidateClassification(
        base_commit=base_commit,
        tracked_modified=tuple(sorted(tracked)),
        relevant_untracked=relevant,
        files=files,
    )
