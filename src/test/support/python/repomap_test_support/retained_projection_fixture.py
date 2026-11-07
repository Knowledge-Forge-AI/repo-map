"""Real, public-safe Git projection histories with an offline source witness."""

from __future__ import annotations

import copy
from dataclasses import dataclass
import hashlib
from pathlib import Path
import subprocess
from typing import Any, Mapping

from ci.retained_python_comparison import selection_delta
from ci.retained_python_projection_evidence import EVIDENCE_PATH, PROOFS_PATH, SCHEMA
from ci.retained_python_ratchet_lineage import audit_candidate_lineage, document_sha256
from ci.retained_python_records import BaselineDocument, render_document
from ci.retained_python_selection import selection_digest
from repomap_test_support.retained_ratchet_fixture import (
    BASELINE_PATH, MODULE_PATH, SCOPE_PATH, baseline_fixture, commit_all, git,
    selection_item, write_json,
)

OWNERSHIP = "tools/ci/python_type_ownership.json"
DECISION = "docs/adr/2099/01/0001-projection.md"


def encoded(value: Mapping[str, object]) -> bytes:
    return render_document(value).encode()


def raw_git(repo: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=repo, timeout=30)


@dataclass
class ProjectionFixture:
    repo: Path
    states: list[BaselineDocument]
    ownership: list[bytes]
    proof: dict[str, Any]
    registry: dict[str, Any]
    edge: str
    parent: str
    source: str

    def write_proof(self) -> None:
        write_json(self.repo / PROOFS_PATH, {"schema": SCHEMA, "proofs": [self.proof]})

    def audit(self) -> None:
        audit_candidate_lineage(self.repo, BASELINE_PATH, self.states[-1], SCOPE_PATH,
                                trusted_genesis_sha256=document_sha256(self.states[0]))


def projection_fixture(tmp_path: Path, variant: str = "clean") -> ProjectionFixture:
    repo = tmp_path / "projection"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "staging")
    ownership = [encoded({"synthetic_state": i}) for i in range(3)]
    states = [copy.deepcopy(baseline_fixture()) for _ in range(3)]
    for i, state in enumerate(states):
        state["ownership"]["sha256"] = hashlib.sha256(ownership[i]).hexdigest()
        for number in range(i):
            state["selection"]["modules"].append(selection_item(
                f"common_lore_index.projected{number}", f"src/main/python/common_lore_index/projected{number}.py"))
    if variant in {"hidden_debt", "dirty_addition"}:
        path = MODULE_PATH if variant == "hidden_debt" else "src/main/python/common_lore_index/projected0.py"
        states[1]["ruff"]["findings"] = [{"path": path, "code": "F401", "message": "unused",
                                           "fingerprint": "f" * 64, "count": 1}]
    if variant == "hidden_mypy":
        states[1]["mypy"]["findings"] = [{"module": "common_lore_index.future", "path": MODULE_PATH,
            "error_code": "arg-type", "normalized_fingerprint": "e" * 64, "count": 1}]
    if variant == "hidden_imports":
        states[1]["migration_direction_imports"]["edges"] = [{"source_module": "common_lore_index.future",
            "source_path": MODULE_PATH, "target_module": "common_lore_index.planned", "target_tier": "T3"}]
    if variant == "hidden_length":
        states[1]["file_length"]["ceilings"] = [{"path": MODULE_PATH, "line_count": 401}]
    if variant == "tool_policy":
        states[1]["tools"]["ruff_target_version"] = "py313"
    if variant == "selection_policy":
        states[1]["selection"]["tiers"] = ["T0", "T1-future"]
    if variant == "overlap":
        states[2]["selection"]["modules"][1]["tier"] = "T0"

    def write_state(index: int) -> None:
        write_json(repo / BASELINE_PATH, states[index])
        (repo / OWNERSHIP).write_bytes(ownership[index])

    write_state(0)
    parent = commit_all(repo, "Synthetic public genesis")
    git(repo, "checkout", "-q", "-b", "witness")
    write_state(1)
    source = commit_all(repo, "Synthetic intermediate source")
    objects = {"commit": raw_git(repo, "cat-file", "commit", source).decode(), "trees": {
        directory: raw_git(repo, "cat-file", "tree", f"{source}:{directory}" if directory != "."
                           else f"{source}^{{tree}}").hex()
        for directory in (".", "tools", "tools/ci")}}
    records = []
    for i, (before, after) in enumerate(zip(states, states[1:])):
        records.append({
            "old_ownership_manifest_sha256": before["ownership"]["sha256"],
            "new_ownership_manifest_sha256": after["ownership"]["sha256"],
            "old_selected_set_sha256": selection_digest(before),
            "new_selected_set_sha256": selection_digest(after),
            "changes": selection_delta(before, after)[0], "phase": f"SYNTHETIC-PROJECTION{i}",
            "status_path": f"docs/status/2099/01/01/9999{i}-projection-exit.md",
            "reason": "Synthetic independently sealed hop.", "source_commit": parent if i == 0 else source,
            "source_manifest_sha256": before["ownership"]["sha256"],
        })
    if variant == "overbroad":
        records[0]["changes"] = [*records[0]["changes"], *records[1]["changes"]]
    if variant == "incomplete":
        records[0]["changes"] = []
    if variant == "unsealed":
        records[0].pop("source_manifest_sha256")
    if variant in {"direct", "unused_record"}:
        extra = copy.deepcopy(records[0])
        extra["phase"] = "SYNTHETIC-EXTRA"
        if variant == "direct":
            extra["new_ownership_manifest_sha256"] = states[2]["ownership"]["sha256"]
            extra["new_selected_set_sha256"] = selection_digest(states[2])
            extra["changes"] = selection_delta(states[0], states[2])[0]
        else:
            extra.update(old_ownership_manifest_sha256="d" * 64, new_ownership_manifest_sha256="e" * 64,
                         source_manifest_sha256="d" * 64,
                         old_selected_set_sha256="d" * 64, new_selected_set_sha256="e" * 64)
        records.append(extra)
    registry = {"schema": "repomap-retained-python-scope-transitions-v2", "records": records}
    git(repo, "checkout", "-q", "staging")
    write_state(2)
    write_json(repo / SCOPE_PATH, registry)
    edge = commit_all(repo, "Synthetic combined publication")
    proof = {"proof": "SYNTHETIC-PROJECTION", "decision": DECISION,
             "reason": "Replay original sealed hops.", "commit": edge, "parent": parent,
             "states": [{"baseline_sha256": hashlib.sha256(encoded(state)).hexdigest(),
                         "ownership_sha256": state["ownership"]["sha256"],
                         "selected_set_sha256": selection_digest(state)} for state in states],
             "hops": [{"phase": records[0]["phase"], "source_commit": parent},
                      {"phase": records[1]["phase"], "source_commit": source, "source_objects": objects}]}
    fixture = ProjectionFixture(repo, states, ownership, proof, registry, edge, parent, source)
    evidence = repo / EVIDENCE_PATH
    evidence.mkdir(parents=True)
    for content in (encoded(states[1]), ownership[1]):
        (evidence / (hashlib.sha256(content).hexdigest() + ".json")).write_bytes(content)
    decision = repo / DECISION
    decision.parent.mkdir(parents=True)
    decision.write_text("# Synthetic decision\n\nSYNTHETIC-PROJECTION\n")
    fixture.write_proof()
    return fixture


def add_chain_alternative(fixture: ProjectionFixture, cycle: bool = False) -> None:
    """Commit extra authority at the projected edge before binding its proof."""
    records = fixture.registry["records"]
    first, second = records[:2]
    extra = copy.deepcopy(second)
    extra["phase"] = "SYNTHETIC-ALTERNATIVE"
    if cycle:
        extra.update(old_ownership_manifest_sha256=first["new_ownership_manifest_sha256"],
                     new_ownership_manifest_sha256=first["old_ownership_manifest_sha256"],
                     old_selected_set_sha256=first["new_selected_set_sha256"],
                     new_selected_set_sha256=first["old_selected_set_sha256"])
        records.append(extra)
    else:
        extra.update(old_ownership_manifest_sha256=first["old_ownership_manifest_sha256"],
                     new_ownership_manifest_sha256="e" * 64,
                     old_selected_set_sha256=first["old_selected_set_sha256"],
                     new_selected_set_sha256="d" * 64)
        final = copy.deepcopy(second)
        final.update(old_ownership_manifest_sha256="e" * 64, old_selected_set_sha256="d" * 64,
                     phase="SYNTHETIC-ALTERNATIVE-END")
        records.extend([extra, final])
    # This is a test fixture's publication, never a real repository history rewrite.
    git(fixture.repo, "reset", "--soft", fixture.parent)
    write_json(fixture.repo / SCOPE_PATH, fixture.registry)
    git(fixture.repo, "add", str(BASELINE_PATH), OWNERSHIP, str(SCOPE_PATH))
    git(fixture.repo, "commit", "-q", "-m", "Synthetic alternative authority")
    fixture.edge = git(fixture.repo, "rev-parse", "HEAD").stdout.strip()
    fixture.proof["commit"] = fixture.edge
    fixture.write_proof()
