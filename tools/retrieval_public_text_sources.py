"""Public-text evaluator and worker source closures (study section 19.1).

Two distinct, separately named closures:

* the unchanged flat worker closure: exactly ``WORKER_SOURCE_FILES`` read from
  ``tools/`` and keyed by bare file name (17 files, including the pins JSON);
* the evaluator closure: the maintained experiment closure supplied by the
  caller plus the explicit public-text owners below, keyed by relative path.

Every file is a fresh regular, non-symlink read below the resolved source root.
There is no broader discovery, no ``__pycache__`` member and no absolute path.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat

from retrieval_semantic_generator_worker_contracts import WORKER_SOURCE_FILES

_SUPPORT = "src/test/support/python/repomap_test_support/"
PUBLIC_TEXT_EVALUATOR_PATHS: tuple[str, ...] = tuple(
    [f"tools/retrieval_public_text_{name}.py" for name in (
        "admission", "allocation", "allocation_io", "capture", "census", "contracts", "descriptors", "excerpt",
        "export", "fusion", "native_gate", "native_inputs", "preflight", "privacy", "report", "report_cells",
        "report_contracts", "report_joins", "request", "response", "sources", "study_catalog", "study_queries",
        "study_schema", "tasks")]
    + [f"{_SUPPORT}w5_public_text_{name}.py" for name in (
        "artifacts", "baselines", "evidence", "functional", "generation", "journal", "learned", "postgres", "readback",
        "registered_fixture", "study")]
    + ["src/test/int/python/tools/retrieval_public_text_lifecycle.int.test.py",
       "src/test/int/python/tools/retrieval_public_text_study.int.test.py"]
)
MAX_SOURCE_BYTES = 4 * 1024 * 1024


class SourceClosureRefusal(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class SourceClosure:
    """Exact bytes and digests of one named closure; ``identity`` binds the digest map."""

    name: str
    files: Mapping[str, bytes] = field(repr=False)
    digests: Mapping[str, str]
    identity: str


def _digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def closure_identity(name: str, digests: Mapping[str, str]) -> str:
    raw = json.dumps({"closure": name, "files": dict(sorted(digests.items()))}, ensure_ascii=True,
                     sort_keys=True, separators=(",", ":"))
    return _digest(raw.encode("ascii"))


def _source_root(repo_root: Path) -> Path:
    if not isinstance(repo_root, Path) or not repo_root.is_absolute() or repo_root.is_symlink():
        raise SourceClosureRefusal("source_root_invalid")
    resolved = repo_root.resolve()
    if resolved != repo_root or not (resolved / "tools").is_dir():
        raise SourceClosureRefusal("source_root_invalid")
    return resolved


def _relative(name: object) -> str:
    if type(name) is not str or not name or "\\" in name or name.startswith("/"):
        raise SourceClosureRefusal("source_path_invalid")
    parts = PurePosixPath(name).parts
    if any(part in ("", ".", "..", "__pycache__") for part in parts) or PurePosixPath(*parts).as_posix() != name:
        raise SourceClosureRefusal("source_path_invalid")
    return name


def _read_regular(root: Path, relative: str) -> bytes:
    path = root / _relative(relative)
    for ancestor in (path, *path.parents):
        if ancestor == root:
            break
        if ancestor.is_symlink():
            raise SourceClosureRefusal("source_file_symlink")
    try:
        before = os.lstat(path)
    except OSError:
        raise SourceClosureRefusal("source_file_missing") from None
    if not stat.S_ISREG(before.st_mode) or not 0 <= before.st_size <= MAX_SOURCE_BYTES:
        raise SourceClosureRefusal("source_file_custody")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
    try:
        raw = b""
        while chunk := os.read(descriptor, 1024 * 1024):
            raw += chunk
            if len(raw) > MAX_SOURCE_BYTES:
                raise SourceClosureRefusal("source_file_custody")
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (after.st_ino, after.st_size, after.st_mtime_ns) != (before.st_ino, before.st_size, before.st_mtime_ns) \
            or len(raw) != before.st_size:
        raise SourceClosureRefusal("source_file_changed")
    return raw


def worker_closure(repo_root: Path) -> SourceClosure:
    """The unchanged flat worker closure, keyed by bare name exactly as the model archive is."""
    root = _source_root(repo_root)
    files = {name: _read_regular(root, f"tools/{name}") for name in WORKER_SOURCE_FILES}
    digests = {name: _digest(raw) for name, raw in sorted(files.items())}
    return SourceClosure("worker", files, digests, closure_identity("worker", digests))


def evaluator_closure(repo_root: Path, base_files: Mapping[str, bytes]) -> SourceClosure:
    """The maintained experiment closure plus explicit public-text owners, all freshly re-read."""
    root = _source_root(repo_root)
    if not isinstance(base_files, Mapping) or not base_files:
        raise SourceClosureRefusal("source_base_closure_required")
    names = set(base_files) | set(PUBLIC_TEXT_EVALUATOR_PATHS)
    worker_members = {f"tools/{name}" for name in WORKER_SOURCE_FILES}
    if not worker_members <= set(base_files):
        raise SourceClosureRefusal("source_worker_members_missing")
    files: dict[str, bytes] = {}
    for name in sorted(names):
        raw = _read_regular(root, name)
        if name in base_files and base_files[name] != raw:
            raise SourceClosureRefusal("source_base_closure_changed")
        files[name] = raw
    digests = {name: _digest(raw) for name, raw in files.items()}
    return SourceClosure("evaluator", files, digests, closure_identity("evaluator", digests))


def require_unchanged(repo_root: Path, closure: SourceClosure) -> None:
    """Re-read every member at a frozen boundary; any byte change refuses."""
    root = _source_root(repo_root)
    for name, digest in closure.digests.items():
        relative = f"tools/{name}" if closure.name == "worker" else name
        if _digest(_read_regular(root, relative)) != digest:
            raise SourceClosureRefusal(f"{closure.name}_source_closure_changed")


__all__ = [
    "PUBLIC_TEXT_EVALUATOR_PATHS", "SourceClosure", "SourceClosureRefusal", "closure_identity",
    "evaluator_closure", "require_unchanged", "worker_closure",
]
