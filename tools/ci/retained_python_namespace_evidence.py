"""Bind exact namespace document projection to the actual source edge once."""
from __future__ import annotations

import hashlib
from pathlib import Path
import stat
from typing import Any

from ci.retained_python_git import blob, git_required
from ci.retained_python_namespace_contract import audit_namespace_documents
from ci.retained_python_namespace_history import load_history, record_key, require
from ci.retained_python_namespace_source import project_source_bytes
from ci.retained_python_projection_evidence import read_file
from ci.retained_python_records import BaselineDocument, render_document, scope_record_key, validate_scope_registry_records
from ci.retained_python_selection import selection_digest

OLD_PREFIX = "src/main/python/repomap_kg/"
NEW_PREFIX = "src/main/python/common_lore_index/"


def document_digest(document: BaselineDocument) -> str:
    return hashlib.sha256(render_document(document).encode()).hexdigest()


def _tree_files(root: Path, revision: str, prefix: str) -> dict[str, str]:
    output = git_required(root, "ls-tree", "-r", "-z", revision, "--", prefix)
    result = {}
    for row in output.split("\0"):
        if not row:
            continue
        meta, path = row.split("\t", 1)
        mode, kind, _oid = meta.split()
        require(path.startswith(prefix) and kind == "blob" and mode in {"100644", "100755"},
                "source tree contains an unsupported entry")
        result[path] = mode
    return result


def _candidate_files(root: Path, prefix: str) -> dict[str, str]:
    output = git_required(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", prefix)
    result = {}
    for path in output.split("\0"):
        if not path or not ((root / path).exists() or (root / path).is_symlink()):
            continue
        read_file(root, path)
        mode = (root / path).lstat().st_mode
        require(stat.S_ISREG(mode), "source candidate entry is not regular")
        result[path] = "100755" if mode & 0o111 else "100644"
    return result


class NamespaceProofLedger:
    """Separate authority; never substitutes for ordinary scope/export authority."""

    def __init__(self, root: Path, head: str) -> None:
        self.root = root
        self.records = load_history(root, head)
        self.used: set[str] = set()

    def authorize(self, parent: str, commit: str | None, before: BaselineDocument, after: BaselineDocument,
                  registry: object, *, projection_edges: set[tuple[str, str]]) -> bool:
        key = (before["ownership"]["sha256"], after["ownership"]["sha256"],
               selection_digest(before), selection_digest(after))
        matches = [record for record in self.records if record_key(record) == key]
        if not matches:
            return False
        require(len(matches) == 1, "edge is ambiguous")
        record = matches[0]
        require(record["id"] not in self.used, "authority was consumed twice")
        require(record["source_commit"] == parent, "source revision differs from edge parent")
        require(commit is None or (commit, parent) not in projection_edges, "conflicts with export proof authority")
        require(not any(scope_record_key(row) == key for row in validate_scope_registry_records(registry)),
                "conflicts with ordinary scope authority")
        require(document_digest(before) == record["before_baseline_sha256"] and
                document_digest(after) == record["after_baseline_sha256"], "baseline digest differs")
        manifest_path = before["ownership"]["manifest_path"]
        require(after["ownership"]["manifest_path"] == manifest_path, "ownership path changed")
        before_raw = blob(self.root, parent, manifest_path)
        after_raw = self._read(commit, manifest_path)
        require(before_raw is not None, "predecessor ownership is missing")
        assert before_raw is not None
        audit_namespace_documents(before, after, ownership_before=before_raw, ownership_after=after_raw,
                                  mypy_translations=record["mypy_translations"])
        decision = self._read(commit, record["decision"])
        require(record["id"].encode() in decision, "decision lacks identifier")
        self._sources(record, parent, commit, before, after)
        self.used.add(record["id"])
        return True

    def _read(self, commit: str | None, path: str) -> bytes:
        raw = read_file(self.root, path) if commit is None else blob(self.root, commit, path)
        require(raw is not None, "bound material is missing")
        assert raw is not None
        return raw

    def _sources(self, record: dict[str, Any], parent: str, commit: str | None,
                 before_document: BaselineDocument, after_document: BaselineDocument) -> None:
        before = _tree_files(self.root, parent, OLD_PREFIX)
        after = (_tree_files(self.root, commit, NEW_PREFIX) if commit is not None
                 else _candidate_files(self.root, NEW_PREFIX))
        rows = record["source_files"]
        require(set(before) == {row["before_path"] for row in rows}, "predecessor census differs")
        require(set(after) == {row["after_path"] for row in rows}, "successor census differs")
        require(not _tree_files(self.root, parent, NEW_PREFIX), "successor root already existed")
        old_after = (_tree_files(self.root, commit, OLD_PREFIX) if commit is not None
                     else _candidate_files(self.root, OLD_PREFIX))
        require(not old_after, "old source root was copied instead of moved")
        require({row["path"] for row in before_document["selection"]["modules"]} <= set(before),
                "predecessor selection is absent from source census")
        require({row["path"] for row in after_document["selection"]["modules"]} <= set(after),
                "successor selection is absent from source census")
        for row in rows:
            old_path, new_path = row["before_path"], row["after_path"]
            require(before[old_path] == after[new_path] == row["mode"], "source mode changed")
            old_raw = self._read(parent, old_path)
            new_raw = self._read(commit, new_path)
            require(hashlib.sha256(old_raw).hexdigest() == row["before_sha256"] and
                    hashlib.sha256(new_raw).hexdigest() == row["after_sha256"], "source digest differs")
            require(project_source_bytes(old_path, old_raw) == new_raw, "source changed beyond the closed rewrite")

    def finish(self) -> None:
        require(self.used == {record["id"] for record in self.records}, "contains unused authority")
