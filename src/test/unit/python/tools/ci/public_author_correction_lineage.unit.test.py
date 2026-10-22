"""Exact projection-edge replay over an author-corrected public history (ADR 0085)."""

from __future__ import annotations

import base64
import json
from pathlib import Path
import re
import subprocess

import pytest

from ci.public_author_correction import DECISION, PROOF_ID, PROOF_PATH, SCHEMA, TARGET_AUTHOR
from ci.retained_python_contract import LineagePolicyError, RatchetContractError
from ci.retained_python_projection_evidence import PROOFS_PATH
from ci.retained_python_projection_proofs import load_projection_proofs
from ci.retained_python_ratchet_lineage import audit_transition
from repomap_test_support.retained_projection_fixture import ProjectionFixture, projection_fixture
from repomap_test_support.retained_ratchet_fixture import BASELINE_PATH, SCOPE_PATH, commit_all, git

AUTHOR = re.compile(rb"^author [^<>\n]+ <[^<>\n]*>( [0-9]+ [+-][0-9]{4})$", re.MULTILINE)


def rewrite(repo: Path, tip: str) -> list[tuple[str, str]]:
    """Fixture-only metadata rewrite in a temporary repository; never a real history."""
    pairs: list[tuple[str, str]] = []
    new: dict[str, str] = {}
    for old in git(repo, "rev-list", "--topo-order", "--reverse", tip).stdout.split():
        raw = subprocess.check_output(["git", "cat-file", "commit", old], cwd=repo, timeout=30)
        raw = AUTHOR.sub(lambda m: b"author " + TARGET_AUTHOR.encode() + m.group(1), raw, count=1)
        raw = re.sub(rb"^parent ([0-9a-f]{40})$", lambda m: b"parent " + new[m.group(1).decode()].encode(),
                     raw, flags=re.MULTILINE)
        new[old] = subprocess.run(["git", "hash-object", "-t", "commit", "-w", "--stdin"], cwd=repo,
                                  input=raw, capture_output=True, check=True, timeout=30).stdout.decode().strip()
        pairs.append((old, new[old]))
    git(repo, "update-ref", "refs/heads/staging", new[tip])
    git(repo, "reset", "-q", "--hard", new[tip])
    return pairs


def write_correction(repo: Path, pairs: list[tuple[str, str]], **overrides: object) -> dict:
    rows = [{"old": old, "new": new, "old_author_source": "committer", "removed_signature_headers": []}
            for old, new in pairs]
    proof: dict[str, object] = {"schema": SCHEMA, "proof": PROOF_ID, "decision": DECISION,
                                "target_author": TARGET_AUTHOR, "committer_policy": "preserve",
                                "old_tip": pairs[-1][0], "new_tip": pairs[-1][1], "rows": rows}
    proof.update(overrides)
    (repo / PROOF_PATH).write_text(json.dumps(proof, indent=2) + "\n")
    (repo / DECISION).parent.mkdir(parents=True, exist_ok=True)
    (repo / DECISION).write_text(f"# Synthetic decision\n\n{PROOF_ID}\n")
    return proof


def corrected(tmp_path: Path, *, clone: bool = True) -> tuple[ProjectionFixture, list[tuple[str, str]]]:
    fixture = projection_fixture(tmp_path)
    published = commit_all(fixture.repo, "Publish forward-only proof")
    pairs = rewrite(fixture.repo, published)
    if clone:
        destination = tmp_path / "corrected-clone"
        git(tmp_path, "clone", "-q", "--no-local", "--single-branch", "--branch", "staging",
            str(fixture.repo), str(destination))
        fixture.repo = destination
    return fixture, pairs


def present(repo: Path, oid: str) -> bool:
    return subprocess.run(["git", "cat-file", "-e", oid], cwd=repo, check=False).returncode == 0


def test_fresh_corrected_clone_replays_the_original_projection_edge(tmp_path: Path) -> None:
    fixture, pairs = corrected(tmp_path)
    assert not any(present(fixture.repo, old) for old, _ in pairs)
    with pytest.raises(RatchetContractError, match="ancestry inspection"):
        fixture.audit()
    write_correction(fixture.repo, pairs)
    fixture.audit()
    # The published proof keeps its original edge strings; only the lookup is translated.
    assert json.loads((fixture.repo / PROOFS_PATH).read_text())["proofs"][0]["commit"] == fixture.edge
    commit_all(fixture.repo, "Introduce correction proof")
    fixture.audit()


def test_original_object_presence_is_not_a_proof_shortcut(tmp_path: Path) -> None:
    fixture, pairs = corrected(tmp_path, clone=False)
    assert all(present(fixture.repo, old) for old, _ in pairs)
    with pytest.raises(LineagePolicyError, match="outside genesis history"):
        fixture.audit()
    write_correction(fixture.repo, pairs)
    fixture.audit()
    forged = [(old, new) if old != fixture.edge else (fixture.parent, new) for old, new in pairs]
    write_correction(fixture.repo, forged)
    with pytest.raises(LineagePolicyError, match="author correction proof"):
        fixture.audit()
    signature = base64.b64encode(b"gpgsig -----BEGIN PGP SIGNATURE-----\n -----END PGP SIGNATURE-----").decode()
    proof = write_correction(fixture.repo, pairs)
    proof["rows"][1]["removed_signature_headers"] = [{"position": 4, "header_base64": signature}]
    (fixture.repo / PROOF_PATH).write_text(json.dumps(proof))
    with pytest.raises(LineagePolicyError, match="original object ID"):
        fixture.audit()


@pytest.mark.parametrize("operation", ["rewrite_inherited_edge", "edit_correction", "drop_edge_row"])
def test_old_governing_proof_and_committed_correction_are_immutable(tmp_path: Path, operation: str) -> None:
    fixture, pairs = corrected(tmp_path)
    write_correction(fixture.repo, pairs)
    commit_all(fixture.repo, "Introduce correction proof")
    if operation == "rewrite_inherited_edge":
        new = dict(pairs)
        fixture.proof.update(commit=new[fixture.edge], parent=new[fixture.parent])
        fixture.write_proof()
    elif operation == "edit_correction":
        text = (fixture.repo / PROOF_PATH).read_text()
        (fixture.repo / PROOF_PATH).write_text(text.replace("\n", "\r\n"))
    else:
        write_correction(fixture.repo, [pair for pair in pairs if pair[0] != fixture.edge])
    with pytest.raises(LineagePolicyError, match="append-only|changed or was deleted"):
        fixture.audit()


def test_unproved_rows_cannot_correct_a_projection_edge(tmp_path: Path) -> None:
    fixture, pairs = corrected(tmp_path)
    proof = write_correction(fixture.repo, pairs)
    proof["rows"] = [row for row in proof["rows"] if row["old"] != fixture.edge]
    (fixture.repo / PROOF_PATH).write_text(json.dumps(proof))
    with pytest.raises(LineagePolicyError, match="author correction proof"):
        fixture.audit()


def test_corrected_and_original_edges_cannot_alias(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture, pairs = corrected(tmp_path)
    write_correction(fixture.repo, pairs)
    new = dict(pairs)
    alias = {**fixture.proof, "proof": "SYNTHETIC-ALIAS", "commit": new[fixture.edge],
             "parent": new[fixture.parent]}
    # Defense in depth: even if two published edges reached the ledger, one cannot be dropped.
    monkeypatch.setattr("ci.retained_python_projection_proofs.load_history",
                        lambda *_args: [fixture.proof, alias])
    with pytest.raises(LineagePolicyError, match="ambiguous after author correction"):
        load_projection_proofs(fixture.repo, head=pairs[-1][1], genesis=new[fixture.parent],
                               baseline=str(BASELINE_PATH), scopes=str(SCOPE_PATH), audit=audit_transition)
