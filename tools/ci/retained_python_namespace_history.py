"""Closed append-only authority for the one coordinated product namespace move."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any

from ci.retained_python_git import blob, git_required, parents
from ci.retained_python_namespace_contract import (
    NamespaceProjectionError, rewrite_product_path,
)
from ci.retained_python_projection_evidence import read_file

LEDGER_PATH = "tools/ci/retained_python_namespace_projections.json"
SCHEMA = "cloe-retained-python-namespace-projections-v1"
RECORD_FIELDS = frozenset({
    "id", "source_commit", "decision", "before_manifest_sha256", "after_manifest_sha256",
    "before_selection_sha256", "after_selection_sha256", "before_baseline_sha256",
    "after_baseline_sha256", "source_map_sha256", "source_files", "mypy_translations",
})
SOURCE_FIELDS = frozenset({"before_path", "after_path", "before_sha256", "after_sha256", "mode"})


def require(condition: bool, message: str) -> None:
    if not condition:
        raise NamespaceProjectionError("namespace projection " + message)


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, "contains duplicate JSON keys")
        result[key] = value
    return result


def _digest(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def source_map_digest(rows: list[dict[str, Any]]) -> str:
    raw = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def record_key(record: dict[str, Any]) -> tuple[str, str, str, str]:
    return (record["before_manifest_sha256"], record["after_manifest_sha256"],
            record["before_selection_sha256"], record["after_selection_sha256"])


def parse_records(raw: bytes | None) -> list[dict[str, Any]]:
    if raw is None:
        return []
    try:
        document = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise NamespaceProjectionError("namespace projection JSON is invalid") from error
    require(isinstance(document, dict) and set(document) == {"schema", "records"}, "fields are invalid")
    require(document["schema"] == SCHEMA and isinstance(document["records"], list), "schema is invalid")
    records = document["records"]
    for record in records:
        require(isinstance(record, dict) and set(record) == RECORD_FIELDS, "record fields are invalid")
        require(isinstance(record["id"], str) and re.fullmatch(r"[a-z][a-z0-9.-]{0,127}", record["id"]) is not None,
                "identifier is invalid")
        require(isinstance(record["source_commit"], str) and
                re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", record["source_commit"]) is not None,
                "source revision is invalid")
        decision = record["decision"]
        require(isinstance(decision, str) and decision.startswith("docs/adr/") and decision.endswith(".md")
                and ".." not in Path(decision).parts and "\\" not in decision,
                "decision path is invalid")
        for name in RECORD_FIELDS - {"id", "source_commit", "decision", "source_files", "mypy_translations"}:
            require(_digest(record[name]), "record digest is invalid")
        require(isinstance(record["mypy_translations"], list), "type translations are invalid")
        rows = record["source_files"]
        require(isinstance(rows, list) and bool(rows), "source mapping is empty or invalid")
        for row in rows:
            require(isinstance(row, dict) and set(row) == SOURCE_FIELDS, "source mapping fields are invalid")
            require(row["after_path"] == rewrite_product_path(row["before_path"]), "source path mapping differs")
            require(_digest(row["before_sha256"]) and _digest(row["after_sha256"]), "source digest is invalid")
            require(isinstance(row["mode"], str) and row["mode"] in {"100644", "100755"}, "source mode is unsupported")
        paths = [row["before_path"] for row in rows]
        require(paths == sorted(set(paths)), "source mapping is duplicated or unordered")
        require(len({row["after_path"] for row in rows}) == len(rows), "source mapping collides")
        require(source_map_digest(rows) == record["source_map_sha256"], "source map digest differs")
    require(len({record["id"] for record in records}) == len(records), "identifier is duplicated")
    require(len({record_key(record) for record in records}) == len(records), "transition key is duplicated")
    return records


def extension(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> None:
    require(after[:len(before)] == before, "authority is not append-only")


def load_history(root: Path, head: str) -> list[dict[str, Any]]:
    """Check every reachable version, including deletion and divergent merge loss."""
    revisions = git_required(root, "log", "--full-history", "--reverse", "--format=%H", head,
                             "--", LEDGER_PATH).splitlines()
    versions: dict[str, tuple[bytes | None, list[dict[str, Any]]]] = {}

    def at(revision: str) -> tuple[bytes | None, list[dict[str, Any]]]:
        if revision not in versions:
            raw = blob(root, revision, LEDGER_PATH)
            versions[revision] = raw, parse_records(raw)
        return versions[revision]

    for revision in revisions:
        raw, current = at(revision)
        for parent in parents(root, revision):
            old_raw, previous = at(parent)
            require(old_raw is None or raw is not None, "initialized ledger was deleted")
            extension(previous, current)
    path = root / LEDGER_PATH
    raw = read_file(root, LEDGER_PATH) if path.exists() or path.is_symlink() else None
    current = parse_records(raw)
    for old_raw, previous in [at(head), *versions.values()]:
        require(old_raw is None or raw is not None, "initialized ledger was deleted")
        extension(previous, current)
    return current


def namespace_governing_paths(root: Path) -> set[Path]:
    path = root / LEDGER_PATH
    present = path.exists() or path.is_symlink()
    records = parse_records(read_file(root, LEDGER_PATH) if present else None)
    paths = {path} if present else set()
    for record in records:
        decision = read_file(root, record["decision"])
        require(decision is not None, "decision is missing")
        assert decision is not None
        require(record["id"].encode() in decision, "decision lacks identifier")
        paths.add(root / record["decision"])
    return paths
