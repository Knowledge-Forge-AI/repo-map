"""Actual disposable Git source edges for namespace authority checks."""
from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any

from ci.retained_python_namespace_contract import OLD_PREFIX, project_baseline, project_ownership_manifest
from ci.retained_python_namespace_evidence import document_digest
from ci.retained_python_namespace_history import LEDGER_PATH, SCHEMA, source_map_digest
from ci.retained_python_namespace_source import project_source_bytes
from ci.retained_python_records import BaselineDocument, render_document
from ci.retained_python_selection import selection_digest
from repomap_test_support.retained_ratchet_fixture import (
    BASELINE_PATH, baseline_fixture, commit_all, git, write_json,
)

OLD_MODULE_PATH = OLD_PREFIX + "future.py"


@dataclass
class NamespaceCase:
    repo: Path
    before: BaselineDocument
    after: BaselineDocument
    source_commit: str
    genesis: str
    record: dict[str, Any]
    new_path: str


def namespace_case(tmp_path: Path) -> NamespaceCase:
    ownership = {
        "schema": "repomap-python-type-ownership-v1", "resolution": "longest-component-prefix-wins",
        "entries": [{"module_prefix": "repomap_kg.future", "match": "exact",
                     "ownership_class": "python_retained", "architecture_box": "runtime",
                     "enforcement_tier": "T1-future", "justification": "Synthetic retained owner",
                     "disposition": "retain"}],
    }
    raw = render_document(ownership).encode()
    before = baseline_fixture()
    before["selection"]["modules"][0]["module"] = "repomap_kg.future"
    before["selection"]["modules"][0]["path"] = OLD_MODULE_PATH
    before["ownership"]["sha256"] = hashlib.sha256(raw).hexdigest()
    repo = tmp_path / "repository"
    repo.mkdir()
    git(repo, "init", "-q")
    write_json(repo / BASELINE_PATH, before)
    (repo / OLD_MODULE_PATH).parent.mkdir(parents=True)
    (repo / OLD_MODULE_PATH).write_text("value = 1\n")
    commit_all(repo, "seal synthetic namespace genesis")
    genesis = git(repo, "rev-parse", "HEAD").stdout.strip()
    manifest = repo / before["ownership"]["manifest_path"]
    manifest.write_bytes(raw)
    decision = "docs/adr/2099/01/9999-synthetic-namespace.md"
    (repo / decision).parent.mkdir(parents=True)
    (repo / decision).write_text("# Synthetic namespace decision\n\nsynthetic.namespace\n")
    write_json(repo / LEDGER_PATH, {"schema": SCHEMA, "records": []})
    source_commit = commit_all(repo, "seal namespace predecessor")
    after_raw = project_ownership_manifest(raw)
    after = project_baseline(before, ownership_sha256=hashlib.sha256(after_raw).hexdigest())
    source = (repo / OLD_MODULE_PATH).read_bytes()
    rewritten = project_source_bytes(OLD_MODULE_PATH, source)
    new_path = OLD_MODULE_PATH.replace("/repomap_kg/", "/common_lore_index/")
    (repo / new_path).parent.mkdir(parents=True)
    (repo / new_path).write_bytes(rewritten)
    (repo / OLD_MODULE_PATH).unlink()
    manifest.write_bytes(after_raw)
    rows = [{"before_path": OLD_MODULE_PATH, "after_path": new_path,
             "before_sha256": hashlib.sha256(source).hexdigest(),
             "after_sha256": hashlib.sha256(rewritten).hexdigest(), "mode": "100644"}]
    record = {
        "id": "synthetic.namespace", "source_commit": source_commit, "decision": decision,
        "before_manifest_sha256": before["ownership"]["sha256"],
        "after_manifest_sha256": after["ownership"]["sha256"],
        "before_selection_sha256": selection_digest(before), "after_selection_sha256": selection_digest(after),
        "before_baseline_sha256": document_digest(before), "after_baseline_sha256": document_digest(after),
        "source_map_sha256": source_map_digest(rows), "source_files": rows, "mypy_translations": [],
    }
    case = NamespaceCase(repo, before, after, source_commit, genesis, record, new_path)
    write_case(case)
    return case


def write_case(case: NamespaceCase) -> None:
    write_json(case.repo / BASELINE_PATH, case.after)
    write_json(case.repo / LEDGER_PATH, {"schema": SCHEMA, "records": [case.record]})
