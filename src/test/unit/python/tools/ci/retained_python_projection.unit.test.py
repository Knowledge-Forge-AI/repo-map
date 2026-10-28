"""Offline exact-edge projection acceptance and adversarial history checks."""

from __future__ import annotations

import copy
from pathlib import Path
import subprocess

import pytest

from ci.retained_python_comparison import selection_delta
from ci.retained_python_contract import LineagePolicyError, RatchetContractError
from ci.retained_python_projection_evidence import EVIDENCE_PATH, PROOFS_PATH
from ci.retained_python_projection_proofs import load_projection_proofs
from ci.retained_python_ratchet_lineage import (
    audit_candidate_lineage,
    audit_transition,
    document_sha256,
)
from ci.retained_python_records import BaselineDocument, render_document
from ci.retained_python_selection import selection_digest
from repomap_test_support.retained_projection_fixture import (
    ProjectionFixture,
    add_chain_alternative,
    projection_fixture,
)
from repomap_test_support.retained_ratchet_fixture import (
    BASELINE_PATH,
    SCOPE_PATH,
    commit_all,
    git,
    selection_item,
    write_json,
)


def test_exact_projection_replays_original_hops_and_fails_without_proof(tmp_path: Path) -> None:
    fixture = projection_fixture(tmp_path)
    fixture.audit()
    (fixture.repo / PROOFS_PATH).unlink()
    for path in (fixture.repo / EVIDENCE_PATH).iterdir():
        path.unlink()
    with pytest.raises(LineagePolicyError, match="lacks exact authority"):
        fixture.audit()


def test_proof_works_in_fresh_clone_without_source_commit(tmp_path: Path) -> None:
    fixture = projection_fixture(tmp_path)
    commit_all(fixture.repo, "Publish forward-only proof")
    destination = tmp_path / "clone"
    git(fixture.repo, "clone", "-q", "--no-local", "--single-branch", "--branch", "staging",
        str(fixture.repo), str(destination))
    absent = subprocess.run(["git", "cat-file", "-e", fixture.source], cwd=destination,
                            capture_output=True, check=False)
    assert absent.returncode != 0
    fixture.repo = destination
    fixture.audit()


@pytest.mark.parametrize("variant,reason", [
    ("hidden_debt", "increased debt"), ("dirty_addition", "not clean"),
    ("hidden_mypy", "increased debt"), ("hidden_imports", "increased debt"),
    ("hidden_length", "increased debt"),
    ("tool_policy", "baseline contract"), ("selection_policy", "baseline contract"),
    ("overbroad", "overbroad or incomplete"), ("incomplete", "overbroad or incomplete"),
    ("unsealed", "scope transition record is invalid"),
    ("overlap", "hop changes overlap"), ("direct", "conflicts with direct"),
    ("unused_record", "unused records"),
])
def test_authentic_intermediate_cannot_hide_policy_or_debt(tmp_path: Path, variant: str, reason: str) -> None:
    fixture = projection_fixture(tmp_path, variant)
    with pytest.raises(LineagePolicyError, match=reason):
        fixture.audit()


@pytest.mark.parametrize("field", ["commit", "parent"])
def test_wrong_or_swapped_edge_is_rejected(tmp_path: Path, field: str) -> None:
    fixture = projection_fixture(tmp_path)
    fixture.proof[field] = fixture.source
    fixture.write_proof()
    with pytest.raises(LineagePolicyError):
        fixture.audit()


@pytest.mark.parametrize("field", ["baseline_sha256", "ownership_sha256"])
@pytest.mark.parametrize("operation", ["tamper", "delete", "alias"])
def test_intermediate_evidence_is_complete_and_unaliased(tmp_path: Path, field: str, operation: str) -> None:
    fixture = projection_fixture(tmp_path)
    path = fixture.repo / EVIDENCE_PATH / (fixture.proof["states"][1][field] + ".json")
    if operation == "tamper":
        path.write_text("{}\n")
    elif operation == "delete":
        path.unlink()
    else:
        real = tmp_path / "original.json"
        path.rename(real)
        path.symlink_to(real)
    with pytest.raises(LineagePolicyError):
        fixture.audit()


@pytest.mark.parametrize("mutation", ["commit_payload", "source", "phase", "tree", "unused_tree", "discontinuous"])
def test_source_and_chain_cannot_be_relabelled(tmp_path: Path, mutation: str) -> None:
    fixture = projection_fixture(tmp_path)
    hop = fixture.proof["hops"][1]
    if mutation == "commit_payload":
        hop["source_objects"]["commit"] += "forged\n"
    elif mutation == "source":
        hop["source_commit"] = "f" * 40
    elif mutation == "phase":
        hop["phase"] = fixture.proof["hops"][0]["phase"]
    elif mutation == "tree":
        hop["source_objects"]["trees"]["tools/ci"] = "00"
    elif mutation == "unused_tree":
        hop["source_objects"]["trees"]["unused"] = ""
    else:
        fixture.proof["states"][1]["selected_set_sha256"] = "f" * 64
    fixture.write_proof()
    with pytest.raises(LineagePolicyError):
        fixture.audit()


@pytest.mark.parametrize("cycle", [False, True])
def test_alternative_record_paths_and_cycles_are_rejected(tmp_path: Path, cycle: bool) -> None:
    fixture = projection_fixture(tmp_path)
    add_chain_alternative(fixture, cycle)
    with pytest.raises(LineagePolicyError, match="ambiguous|cycle"):
        fixture.audit()


@pytest.mark.parametrize("before_proof", [False, True])
def test_record_cannot_authorize_both_direct_and_projection(tmp_path: Path, before_proof: bool) -> None:
    fixture = projection_fixture(tmp_path)
    ledger = load_projection_proofs(fixture.repo, head=fixture.edge, genesis=fixture.parent,
                                   baseline=str(BASELINE_PATH), scopes=str(SCOPE_PATH), audit=audit_transition)
    args = (fixture.states[0], fixture.states[1], fixture.registry, lambda _path: None)
    if before_proof:
        ledger.direct(*args)
        with pytest.raises(LineagePolicyError, match="consumed twice"):
            ledger.authorize(fixture.edge, fixture.parent, fixture.states[0], fixture.states[-1],
                             fixture.registry, lambda _path: None)
    else:
        ledger.authorize(fixture.edge, fixture.parent, fixture.states[0], fixture.states[-1],
                         fixture.registry, lambda _path: None)
        with pytest.raises(LineagePolicyError, match="consumed twice"):
            ledger.direct(*args)


@pytest.mark.parametrize("operation", ["delete", "edit", "unused_evidence", "duplicate_proof"])
def test_committed_proof_and_evidence_cannot_change(tmp_path: Path, operation: str) -> None:
    fixture = projection_fixture(tmp_path)
    commit_all(fixture.repo, "Publish proof")
    if operation == "delete":
        (fixture.repo / PROOFS_PATH).unlink()
    elif operation == "edit":
        fixture.proof["reason"] = "Changed authority"
        fixture.write_proof()
    elif operation == "unused_evidence":
        (fixture.repo / EVIDENCE_PATH / ("f" * 64 + ".json")).write_text("{}")
    else:
        import json
        (fixture.repo / PROOFS_PATH).write_text(json.dumps({"schema": "repomap-retained-python-projection-proofs-v1",
                                                         "proofs": [fixture.proof, copy.deepcopy(fixture.proof)]}))
    with pytest.raises(LineagePolicyError):
        fixture.audit()


def test_deleted_evidence_cannot_be_hidden_by_reintroduction(tmp_path: Path) -> None:
    fixture = projection_fixture(tmp_path)
    commit_all(fixture.repo, "Publish proof")
    path = next((fixture.repo / EVIDENCE_PATH).iterdir())
    content = path.read_bytes()
    path.unlink()
    commit_all(fixture.repo, "Delete evidence")
    path.write_bytes(content)
    commit_all(fixture.repo, "Reintroduce evidence")
    with pytest.raises(LineagePolicyError, match="evidence set"):
        fixture.audit()


def test_divergent_merge_cannot_drop_a_published_proof(tmp_path: Path) -> None:
    fixture = projection_fixture(tmp_path)
    carrier = commit_all(fixture.repo, "Publish proof on carrier")
    git(fixture.repo, "checkout", "-q", "-b", "divergent", fixture.edge)
    (fixture.repo / "notice.txt").write_text("Synthetic unrelated change\n")
    commit_all(fixture.repo, "Unrelated divergent change")
    git(fixture.repo, "merge", "-q", "--no-ff", "-s", "ours", carrier, "-m", "Drop proof in merge")
    with pytest.raises(LineagePolicyError, match="append-only"):
        fixture.audit()


def test_committed_proof_mutation_cannot_be_hidden_by_restoration(tmp_path: Path) -> None:
    fixture = projection_fixture(tmp_path)
    commit_all(fixture.repo, "Publish proof")
    original = copy.deepcopy(fixture.proof)
    fixture.proof["reason"] = "Rewritten reason"
    fixture.write_proof()
    commit_all(fixture.repo, "Rewrite proof")
    fixture.proof = original
    fixture.write_proof()
    commit_all(fixture.repo, "Restore original proof")
    with pytest.raises(LineagePolicyError, match="append-only"):
        fixture.audit()


@pytest.mark.parametrize("mutation", ["unicode", "missing_decision", "unused_edge", "duplicate_evidence"])
def test_invalid_or_unused_projection_material_fails_closed(tmp_path: Path, mutation: str) -> None:
    import json
    fixture = projection_fixture(tmp_path)
    if mutation == "unicode":
        fixture.proof["hops"][1]["source_objects"]["commit"] = "\ud800"
    elif mutation == "missing_decision":
        (fixture.repo / fixture.proof["decision"]).unlink()
    elif mutation == "unused_edge":
        fixture.proof["commit"] = fixture.source
    else:
        second = copy.deepcopy(fixture.proof)
        second.update(proof="UNUSED-PROOF", commit=fixture.source)
        (fixture.repo / PROOFS_PATH).write_text(json.dumps({"schema": "repomap-retained-python-projection-proofs-v1",
                                                         "proofs": [fixture.proof, second]}))
        with pytest.raises(LineagePolicyError, match="duplicate evidence"):
            fixture.audit()
        return
    # JSON escapes the surrogate, ensuring the candidate document itself is valid UTF-8.
    (fixture.repo / PROOFS_PATH).write_text(json.dumps({"schema": "repomap-retained-python-projection-proofs-v1",
                                                     "proofs": [fixture.proof]}))
    with pytest.raises(LineagePolicyError):
        fixture.audit()


def test_shallow_clone_cannot_use_projection_to_replace_history(tmp_path: Path) -> None:
    fixture = projection_fixture(tmp_path)
    commit_all(fixture.repo, "Publish proof")
    target = tmp_path / "shallow"
    git(fixture.repo, "clone", "-q", "--depth", "1", "--branch", "staging", fixture.repo.as_uri(), str(target))
    fixture.repo = target
    with pytest.raises(RatchetContractError, match="shallow"):
        fixture.audit()


INHERITED_PROOF_HOPS = ("REPOMAP-PRODUCT5-PUBLIC-STAGING-REPAIR1", "REPOMAP-PRODUCT5-HOSTED-QUAL2-REPAIR10")
# Each independently reviewed clean forward admission committed after the inherited proof.
FORWARD_ADMISSIONS = (
    "REPOMAP-PRODUCT6-NAVIGATION27-PUBLIC-PROJECTION-FIX1",
    "REPOMAP-PRODUCT6-NAVIGATION37-EXTENSION-PROVENANCE1",
    "REPOMAP-PRODUCT6-NAVIGATION40-EXTENSION-RESTORE1",
    "REPOMAP-PRODUCT6-NAVIGATION46-D12HOSTED8",
    "REPOMAP-PRODUCT6-NAVIGATION47-D12SYSTEM1",
    "REPOMAP-PRODUCT6-NAVIGATION47-CI85REPAIR1",
)


def _prepare_direct_v2_admission(
    fixture: ProjectionFixture,
) -> tuple[BaselineDocument, dict[str, object], str]:
    commit_all(fixture.repo, "Publish projection proof")
    before = fixture.states[-1]
    after = copy.deepcopy(before)
    after["ownership"]["sha256"] = "c" * 64
    after["selection"]["modules"].append(
        selection_item("repomap_kg.projected2", "src/main/python/repomap_kg/projected2.py")
    )
    status_rel = "tools/ci/direct-qualification.md"
    (fixture.repo / status_rel).write_text(
        "# SYNTHETIC-DIRECT1 Exit: direct v2 qualification\n", encoding="utf-8"
    )
    record: dict[str, object] = {
        "old_ownership_manifest_sha256": before["ownership"]["sha256"],
        "new_ownership_manifest_sha256": after["ownership"]["sha256"],
        "old_selected_set_sha256": selection_digest(before),
        "new_selected_set_sha256": selection_digest(after),
        "changes": selection_delta(before, after)[0],
        "phase": "SYNTHETIC-DIRECT1",
        "status_path": status_rel,
        "reason": "Admit clean direct module after projection proof.",
        "source_commit": fixture.edge,
        "source_manifest_sha256": before["ownership"]["sha256"],
    }
    fixture.registry["records"].append(record)
    write_json(fixture.repo / BASELINE_PATH, after)
    write_json(fixture.repo / SCOPE_PATH, fixture.registry)
    return after, record, document_sha256(fixture.states[0])


def test_direct_v2_admission_audits_before_and_after_commit(tmp_path: Path) -> None:
    fixture = projection_fixture(tmp_path)
    after, _record, genesis = _prepare_direct_v2_admission(fixture)
    uncommitted = audit_candidate_lineage(
        fixture.repo, BASELINE_PATH, after, SCOPE_PATH, trusted_genesis_sha256=genesis
    )
    assert uncommitted.candidate_transition is True
    assert uncommitted.committed_transitions == 1
    assert uncommitted.scope_transitions == 3
    commit_all(fixture.repo, "Commit clean v2 direct admission")
    committed = audit_candidate_lineage(
        fixture.repo, BASELINE_PATH, after, SCOPE_PATH, trusted_genesis_sha256=genesis
    )
    assert committed.candidate_transition is False
    assert committed.committed_transitions == 2
    assert committed.scope_transitions == uncommitted.scope_transitions == 3


@pytest.mark.parametrize("missing_field", ["source_commit", "source_manifest_sha256"])
def test_direct_v2_admission_requires_source_commit_and_manifest(
    tmp_path: Path, missing_field: str
) -> None:
    fixture = projection_fixture(tmp_path)
    after, record, genesis = _prepare_direct_v2_admission(fixture)
    record.pop(missing_field)
    write_json(fixture.repo / SCOPE_PATH, fixture.registry)
    with pytest.raises(LineagePolicyError, match="scope transition record is invalid"):
        audit_candidate_lineage(
            fixture.repo, BASELINE_PATH, after, SCOPE_PATH, trusted_genesis_sha256=genesis
        )


def test_inherited_public_edge_uses_the_exact_recovered_proof(pytestconfig: pytest.Config) -> None:
    import json
    repo = pytestconfig.rootpath
    baseline = json.loads((repo / BASELINE_PATH).read_text())
    head_baseline = json.loads(git(repo, "show", f"HEAD:{BASELINE_PATH}").stdout)
    result = audit_candidate_lineage(repo, BASELINE_PATH, baseline)
    assert result.candidate_transition is (head_baseline != baseline)
    proof = json.loads((repo / PROOFS_PATH).read_text())["proofs"][0]
    assert proof["commit"] == "1adfc7a15e830c8709f76f4e61abb9e24a8c0b17"
    assert proof["parent"] == "d1671f8088531c4be11de65908f762c61f986844"
    assert tuple(hop["phase"] for hop in proof["hops"]) == INHERITED_PROOF_HOPS
    # The post-genesis registry tail is exactly the proof hops followed by the forward
    # admissions, each continuing its predecessor's ownership and selection state.
    expected = INHERITED_PROOF_HOPS + FORWARD_ADMISSIONS
    records = json.loads((repo / SCOPE_PATH).read_text())["records"][-len(expected) - 1:]
    assert tuple(record["phase"] for record in records[1:]) == expected
    for before, after in zip(records, records[1:]):
        assert after["old_ownership_manifest_sha256"] == before["new_ownership_manifest_sha256"]
        assert after["old_selected_set_sha256"] == before["new_selected_set_sha256"]
    # The audit consumes exactly that authority: one key per hop and per forward admission.
    assert result.scope_transitions == len(expected)
    assert render_document(baseline).encode() == (repo / BASELINE_PATH).read_bytes()
