"""Real-Git authentication of the exact public author-correction proof (ADR 0085)."""

from __future__ import annotations

import base64
import copy
from dataclasses import dataclass, field, replace
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Callable

import pytest

from ci.public_author_correction import DECISION, PROOF_ID, PROOF_PATH, SCHEMA, TARGET_AUTHOR
from ci.public_author_correction_history import load_author_correction
from ci.retained_python_contract import LineagePolicyError
from ci.retained_python_projection_evidence import PROOFS_PATH

ORIGINAL = b"Original Steward <steward@example.invalid>"
WITNESSED = b"Witnessed Steward <witnessed@example.invalid>"
SERVICE = b"Hosting Service <service@example.invalid>"
SIGNATURE = b"gpgsig -----BEGIN PGP SIGNATURE-----\n \n c3ludGhldGlj\n -----END PGP SIGNATURE-----\n "
ENV = os.environ | {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
                    "GIT_NO_REPLACE_OBJECTS": "1", "GIT_AUTHOR_NAME": "Synthetic Fixture",
                    "GIT_AUTHOR_EMAIL": "fixture@example.invalid", "GIT_COMMITTER_NAME": "Synthetic Fixture",
                    "GIT_COMMITTER_EMAIL": "fixture@example.invalid"}


def run(repo: Path, *args: str, data: bytes | None = None) -> str:
    return subprocess.run(["git", *args], cwd=repo, env=ENV, input=data, check=True,
                          capture_output=True, timeout=30).stdout.decode().strip()


@dataclass(frozen=True)
class Spec:
    name: str
    files: tuple[tuple[str, bytes], ...]
    parents: tuple[str, ...]
    author: bytes = ORIGINAL
    committer: bytes = ORIGINAL
    stamp: bytes = b"1700000000 +0000"
    extras: tuple[bytes, ...] = ()
    signature: bytes | None = None
    message: bytes = b"Synthetic public commit\n"
    source: str = "committer"


SPECS = (
    Spec("root", (("a.txt", b"one\n"),), ()),
    Spec("signed", (("a.txt", b"two\n"),), ("root",), WITNESSED, SERVICE, signature=SIGNATURE,
         source="inherited_projection_author", message=b"Squash publication (#1)\n"),
    Spec("main", (("a.txt", b"three\n"),), ("signed",), stamp=b"1700000100 -0400"),
    Spec("side", (("b.txt", b"side\n"),), ("signed",)),
    Spec("merge", (("a.txt", b"three\n"), ("b.txt", b"side\n")), ("main", "side"),
         extras=(b"encoding ISO-8859-1",), message=b"Merge side\n\nBody stays exact.\n"),
)


def tree(repo: Path, files: tuple[tuple[str, bytes], ...]) -> str:
    lines = [f"100644 blob {run(repo, 'hash-object', '-w', '--stdin', data=content)}\t{name}"
             for name, content in files]
    return run(repo, "mktree", data=("\n".join(lines) + "\n").encode())


def payload(repo: Path, spec: Spec, ids: dict[str, str], author: bytes, signed: bool) -> bytes:
    headers = [b"tree " + tree(repo, spec.files).encode(),
               *(b"parent " + ids[p].encode() for p in spec.parents),
               b"author " + author + b" " + spec.stamp, b"committer " + spec.committer + b" " + spec.stamp,
               *spec.extras]
    if signed and spec.signature:
        headers.append(spec.signature)
    return b"\n".join(headers) + b"\n\n" + spec.message


def write(repo: Path, raw: bytes) -> str:
    return run(repo, "hash-object", "-t", "commit", "-w", "--stdin", data=raw)


Mutation = Callable[[Spec], Spec]


@dataclass
class Correction:
    repo: Path
    proof: dict[str, Any]
    old: dict[str, str]
    new: dict[str, str]
    witness: dict[str, Any] = field(default_factory=dict)

    def write_proof(self) -> None:
        (self.repo / PROOF_PATH).write_text(json.dumps(self.proof, indent=2) + "\n")

    def load(self) -> dict[str, str]:
        return dict(load_author_correction(self.repo, run(self.repo, "rev-parse", "HEAD")).new_by_old)

    def row(self, name: str) -> dict[str, Any]:
        return next(row for row in self.proof["rows"] if row["new"] == self.new[name])


def witness_document(old_edge: str, old_parent: str, author: bytes) -> dict[str, Any]:
    states = [{"baseline_sha256": f"{i}" * 64, "ownership_sha256": "a" * 64,
               "selected_set_sha256": "b" * 64} for i in range(3)]
    text = f"tree {'c' * 40}\nauthor {author.decode()} 1 +0000\ncommitter {author.decode()} 1 +0000\n\nw\n"
    return {"schema": "repomap-retained-python-projection-proofs-v1", "proofs": [{
        "proof": "SYNTHETIC-WITNESS", "decision": "docs/adr/2099/01/0001-projection.md",
        "reason": "Published witness.", "commit": old_edge, "parent": old_parent, "states": states,
        "hops": [{"phase": "P0", "source_commit": "d" * 40},
                 {"phase": "P1", "source_commit": "e" * 40,
                  "source_objects": {"commit": text, "trees": {}}}]}]}


def correction(tmp_path: Path, mutate: dict[str, Mutation] | None = None) -> Correction:
    """Write original and corrected graphs, then fresh-clone only the corrected graph."""
    origin = tmp_path / "origin"
    origin.mkdir()
    run(origin, "init", "-q", "-b", "staging")
    old: dict[str, str] = {}
    new: dict[str, str] = {}
    for spec in SPECS:
        old[spec.name] = write(origin, payload(origin, spec, old, spec.author, True))
        corrected = (mutate or {}).get(spec.name, lambda value: value)(spec)
        new[spec.name] = write(origin, payload(origin, corrected, new, TARGET_AUTHOR.encode(), False))
    run(origin, "update-ref", "refs/heads/staging", new["merge"])
    clone = tmp_path / "clone"
    run(tmp_path, "clone", "-q", "--no-local", "--single-branch", "--branch", "staging",
        str(origin), str(clone))
    rows = [{"old": old[s.name], "new": new[s.name], "old_author_source": s.source,
             "removed_signature_headers": [{"position": 4, "header_base64": base64.b64encode(
                 s.signature).decode()}] if s.signature else []} for s in SPECS]
    proof = {"schema": SCHEMA, "proof": PROOF_ID, "decision": DECISION, "target_author": TARGET_AUTHOR,
             "committer_policy": "preserve", "old_tip": old["merge"], "new_tip": new["merge"], "rows": rows}
    fixture = Correction(clone, proof, old, new, witness_document(old["signed"], old["root"], WITNESSED))
    (clone / DECISION).parent.mkdir(parents=True)
    (clone / DECISION).write_text(f"# Synthetic decision\n\n{PROOF_ID}\n")
    (clone / PROOFS_PATH).parent.mkdir(parents=True)
    (clone / PROOFS_PATH).write_text(json.dumps(fixture.witness))
    fixture.write_proof()
    return fixture


def commit(repo: Path, message: str) -> str:
    run(repo, "add", "-A")
    run(repo, "commit", "-q", "-m", message)
    return run(repo, "rev-parse", "HEAD")


def test_fresh_clone_authenticates_every_original_without_original_objects(tmp_path: Path) -> None:
    fixture = correction(tmp_path)
    for oid in fixture.old.values():
        absent = subprocess.run(["git", "cat-file", "-e", oid], cwd=fixture.repo, env=ENV, check=False)
        assert absent.returncode != 0
    expected = {fixture.old[name]: fixture.new[name] for name in fixture.old}
    assert fixture.load() == expected
    # A later ordinary commit stays outside the historical transform.
    commit(fixture.repo, "Publish correction proof")
    assert fixture.load() == expected


def test_repository_without_proof_keeps_identity_lookup(tmp_path: Path) -> None:
    fixture = correction(tmp_path)
    (fixture.repo / PROOF_PATH).unlink()
    assert fixture.load() == {}
    lookup = load_author_correction(fixture.repo, run(fixture.repo, "rev-parse", "HEAD"))
    assert lookup.resolve(fixture.old["root"]) == fixture.old["root"]


@pytest.mark.parametrize("name,mutation", [
    ("main", lambda s: replace(s, files=(("a.txt", b"changed\n"),))),
    ("main", lambda s: replace(s, message=b"Changed message\n")),
    ("merge", lambda s: replace(s, message=b"Merge side\n\nBody changed.\n")),
    ("main", lambda s: replace(s, committer=SERVICE)),
    ("main", lambda s: replace(s, stamp=b"1700000101 -0400")),
    ("main", lambda s: replace(s, stamp=b"1700000100 +0000")),
    ("merge", lambda s: replace(s, extras=())),
    ("merge", lambda s: replace(s, extras=(b"encoding UTF-8",))),
    ("merge", lambda s: replace(s, parents=("side", "main"))),
    ("main", lambda s: replace(s, parents=("root",))),
], ids=["tree", "message", "body", "committer", "date", "offset", "header_removed",
        "header_changed", "parent_order", "wrong_parent"])
def test_corrected_content_or_lineage_change_breaks_original_reconstruction(
        tmp_path: Path, name: str, mutation: Mutation) -> None:
    fixture = correction(tmp_path, {name: mutation})
    with pytest.raises(LineagePolicyError, match="original object ID"):
        fixture.load()


@pytest.mark.parametrize("mutation,reason", [
    (lambda s: replace(s, extras=(SIGNATURE,)), "unexpected structural or signature"),
    (lambda s: replace(s, extras=(b"author " + ORIGINAL + b" 1 +0000",)), "unexpected structural"),
], ids=["signature_replacement", "second_author"])
def test_corrected_commit_cannot_add_signature_or_identity_headers(
        tmp_path: Path, mutation: Mutation, reason: str) -> None:
    with pytest.raises(LineagePolicyError, match=reason):
        correction(tmp_path, {"signed": mutation}).load()


def test_other_author_than_the_requested_identity_is_rejected(tmp_path: Path) -> None:
    fixture = correction(tmp_path)
    origin = tmp_path / "origin"
    spec = SPECS[0]
    forged = write(origin, payload(origin, spec, {}, b"Other Person <other@example.invalid>", False))
    run(origin, "update-ref", "refs/heads/other", forged)
    run(fixture.repo, "fetch", "-q", str(origin), "other")
    fixture.row("root")["new"] = forged
    fixture.write_proof()
    with pytest.raises(LineagePolicyError, match="requested identity"):
        fixture.load()


@pytest.mark.parametrize("mutation", ["forged", "swapped", "new_as_old"])
def test_forged_original_object_id_is_rejected(tmp_path: Path, mutation: str) -> None:
    fixture = correction(tmp_path)
    main, side = fixture.row("main"), fixture.row("side")
    if mutation == "forged":
        main["old"] = "f" * 40
    elif mutation == "swapped":
        main["old"], side["old"] = side["old"], main["old"]
    else:
        main["old"] = fixture.new["main"]
    fixture.write_proof()
    with pytest.raises(LineagePolicyError, match="original object ID|cyclic"):
        fixture.load()


@pytest.mark.parametrize("mutation,reason", [
    ("missing", "original object ID"), ("wrong_bytes", "original object ID"),
    ("wrong_position", "signature position"), ("misplaced", "original object ID"),
    ("not_signature", "not a signature header"), ("bad_base64", "signature encoding"),
    ("unordered", "not ordered"), ("extra", "original object ID"),
    ("sha256_kind", "not a signature header"),
])
def test_signature_preimage_must_be_exact(tmp_path: Path, mutation: str, reason: str) -> None:
    fixture = correction(tmp_path)
    removed = fixture.row("signed")["removed_signature_headers"]
    header = SIGNATURE.replace(b"c3ludGhldGlj", b"Zm9yZ2Vk")
    if mutation == "missing":
        removed.clear()
    elif mutation == "wrong_bytes":
        removed[0]["header_base64"] = base64.b64encode(header).decode()
    elif mutation == "wrong_position":
        removed[0]["position"] = 3
    elif mutation == "misplaced":
        fixture.row("main")["removed_signature_headers"] = copy.deepcopy(removed)
        removed.clear()
    elif mutation == "not_signature":
        removed[0]["header_base64"] = base64.b64encode(b"mergetag object " + b"0" * 40).decode()
    elif mutation == "bad_base64":
        removed[0]["header_base64"] = "not base64!"
    elif mutation == "sha256_kind":
        removed[0]["header_base64"] = base64.b64encode(b"gpgsig-sha256" + SIGNATURE[6:]).decode()
    elif mutation == "unordered":
        removed.insert(0, {"position": 5, "header_base64": base64.b64encode(header).decode()})
    else:
        removed.append({"position": 5, "header_base64": base64.b64encode(header).decode()})
    fixture.write_proof()
    with pytest.raises(LineagePolicyError, match=reason):
        fixture.load()


@pytest.mark.parametrize("mutation,reason", [
    ("missing_root", "outside the corrected range"), ("missing_tip", "tip mapping"),
    ("duplicate", "duplicate"), ("unordered", "parent-first"), ("empty", "rows are missing"),
    ("extra_unused", "outside the corrected tip closure"), ("wrong_old_tip", "tip mapping"),
    ("cyclic", "cyclic"), ("unknown_new", "missing or forged"),
])
def test_rows_must_be_the_exact_complete_closure(tmp_path: Path, mutation: str, reason: str) -> None:
    fixture = correction(tmp_path)
    rows = fixture.proof["rows"]
    if mutation == "missing_root":
        rows.pop(0)
    elif mutation == "missing_tip":
        rows.pop()
    elif mutation == "duplicate":
        rows.append(copy.deepcopy(rows[2]))
    elif mutation == "unordered":
        rows[0], rows[1] = rows[1], rows[0]
    elif mutation == "empty":
        rows.clear()
    elif mutation == "extra_unused":
        fixture.proof.update(old_tip=fixture.old["main"], new_tip=fixture.new["main"])
    elif mutation == "wrong_old_tip":
        fixture.proof["old_tip"] = fixture.old["main"]
    elif mutation == "cyclic":
        rows[1]["old"] = rows[0]["new"]
    else:
        rows.append({**copy.deepcopy(rows[0]), "old": "e" * 40, "new": "d" * 40})
    fixture.write_proof()
    with pytest.raises(LineagePolicyError, match=reason):
        fixture.load()


def test_corrected_tip_must_be_in_head_ancestry(tmp_path: Path) -> None:
    fixture = correction(tmp_path)
    run(fixture.repo, "checkout", "-q", "--orphan", "unrelated")
    commit(fixture.repo, "Unrelated root")
    with pytest.raises(LineagePolicyError, match="outside HEAD ancestry"):
        fixture.load()


@pytest.mark.parametrize("name,value", [
    ("schema", SCHEMA + "-proposed"), ("proof", "OTHER-PROOF"), ("decision", "docs/adr/other.md"),
    ("target_author", "Other Person <other@example.invalid>"), ("committer_policy", "rewrite"),
])
def test_pinned_identity_rule_and_decision_cannot_be_chosen(tmp_path: Path, name: str, value: str) -> None:
    fixture = correction(tmp_path)
    fixture.proof[name] = value
    fixture.write_proof()
    with pytest.raises(LineagePolicyError, match="pinned identity or policy"):
        fixture.load()


@pytest.mark.parametrize("mutation,reason", [
    ("source", "author source"), ("row_field", "fields are invalid"),
    ("duplicate_json", "duplicate JSON"), ("decision", "decision is missing"),
])
def test_malformed_proof_material_fails_closed(tmp_path: Path, mutation: str, reason: str) -> None:
    fixture = correction(tmp_path)
    if mutation == "source":
        fixture.row("main")["old_author_source"] = "tools/ci/any_file.json"
    elif mutation == "row_field":
        fixture.row("main")["old_message"] = "Synthetic"
    elif mutation == "decision":
        (fixture.repo / DECISION).write_text("# Synthetic decision without identifier\n")
    if mutation == "duplicate_json":
        text = json.dumps(fixture.proof)
        (fixture.repo / PROOF_PATH).write_text(text[:-1] + ', "rows": []}')
    else:
        fixture.write_proof()
    with pytest.raises(LineagePolicyError, match=reason):
        fixture.load()


@pytest.mark.parametrize("mutation", ["author", "missing_edge", "committer_source"])
def test_witness_source_is_fixed_and_exact(tmp_path: Path, mutation: str) -> None:
    fixture = correction(tmp_path)
    if mutation == "author":
        witness = witness_document(fixture.old["signed"], fixture.old["root"], ORIGINAL)
        (fixture.repo / PROOFS_PATH).write_text(json.dumps(witness))
    elif mutation == "missing_edge":
        (fixture.repo / PROOFS_PATH).unlink()
    else:
        fixture.row("signed")["old_author_source"] = "committer"
        fixture.write_proof()
    with pytest.raises(LineagePolicyError, match="original object ID|witness"):
        fixture.load()


@pytest.mark.parametrize("operation", ["edit", "delete", "restore"])
def test_committed_proof_is_immutable_after_introduction(tmp_path: Path, operation: str) -> None:
    fixture = correction(tmp_path)
    commit(fixture.repo, "Introduce correction proof")
    original = (fixture.repo / PROOF_PATH).read_bytes()
    if operation == "delete":
        (fixture.repo / PROOF_PATH).unlink()
    else:
        # Semantically identical but byte-different material is still a changed proof.
        (fixture.repo / PROOF_PATH).write_text(json.dumps(fixture.proof))
    if operation == "restore":
        commit(fixture.repo, "Rewrite correction proof")
        (fixture.repo / PROOF_PATH).write_bytes(original)
    with pytest.raises(LineagePolicyError, match="changed or was deleted"):
        fixture.load()


def test_repeated_load_never_reuses_a_stale_result_after_edits(tmp_path: Path) -> None:
    fixture = correction(tmp_path)
    assert len(fixture.load()) == len(SPECS)
    fixture.row("merge")["old"] = fixture.old["main"]
    fixture.write_proof()
    with pytest.raises(LineagePolicyError):
        fixture.load()
    fixture.row("merge")["old"] = fixture.old["merge"]
    fixture.write_proof()
    (fixture.repo / PROOFS_PATH).write_text(json.dumps(
        witness_document(fixture.old["signed"], fixture.old["root"], SERVICE)))
    with pytest.raises(LineagePolicyError, match="original object ID"):
        fixture.load()


def test_corrupted_store_bytes_cannot_stand_in_for_a_corrected_id(tmp_path: Path) -> None:
    import zlib
    fixture = correction(tmp_path)
    origin, oid = tmp_path / "origin", fixture.new["main"]
    for path in (PROOF_PATH, PROOFS_PATH, DECISION):
        (origin / path).parent.mkdir(parents=True, exist_ok=True)
        (origin / path).write_bytes((fixture.repo / path).read_bytes())
    forged = subprocess.run(["git", "cat-file", "commit", oid], cwd=origin, env=ENV, check=True,
                            capture_output=True).stdout.replace(b"Synthetic public", b"Forged public")
    loose = origin / ".git/objects" / oid[:2] / oid[2:]
    loose.chmod(0o644)
    loose.write_bytes(zlib.compress(b"commit %d\0" % len(forged) + forged))
    with pytest.raises(LineagePolicyError, match="missing or forged"):
        load_author_correction(origin, fixture.new["merge"])
