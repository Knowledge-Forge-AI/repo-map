"""Contradictory retention authorities never erase maintenance obligations."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from ci.python_retention_authorities import (
    CHECKERS, RetentionAuthorityError, bind_inputs, validate_consistency, verify_bindings,
    validate_transition_history, validate_ownership_transitions,
)


def authority(root: Path, *, retained: bool = False) -> tuple[list[dict], list[dict]]:
    folder = root / "tools/ci"
    folder.mkdir(parents=True)
    path = "src/main/python/common_lore_index/owner.py"
    rule = {
        "module_prefix": "common_lore_index.owner", "match": "exact",
        "ownership_class": "python_retained" if retained else "planned_go",
        "architecture_box": "go_control_and_api",
        "enforcement_tier": "T1-future" if retained else "T3",
        "justification": "Specific future native command owner",
        "disposition": "retained_python_ratcheted" if retained else "planned_go",
    }
    (folder / "python_type_ownership.json").write_text(json.dumps({
        "schema": "repomap-python-type-ownership-v1",
        "resolution": "longest-component-prefix-wins", "entries": [rule],
    }))
    (folder / "python_retention_transitions.json").write_text(json.dumps({
        "schema": "repomap-python-retention-transitions-v1", "records": [{
            "path": path, "disposition": "pending_admission", "superseded_rule": rule,
            "reason": "Maintain executable command until replacement is implemented",
        }],
    }))
    files = [{"path": path, "root": "product", "confidence": 0.9,
              "maintained_executable": True, "governing_profile": "retained_python_ratchets",
              "status": "retained_ratchet" if retained else "deferred_decomposition"}]
    selected = [{"module": "common_lore_index.owner", "path": path,
                 "ownership_class": rule["ownership_class"], "tier": rule["enforcement_tier"]}]
    return files, selected if retained else []


def test_forecast_retains_explicit_pending_obligation(tmp_path: Path) -> None:
    files, selected = authority(tmp_path)
    validate_consistency(tmp_path, files, selected)


def test_retained_ownership_requires_selection(tmp_path: Path) -> None:
    files, _ = authority(tmp_path, retained=True)
    with pytest.raises(RetentionAuthorityError, match="contradictory"):
        validate_consistency(tmp_path, files, [])


def test_inventory_cannot_claim_retained_forecast(tmp_path: Path) -> None:
    files, selected = authority(tmp_path)
    files[0]["status"] = "retained_ratchet"
    with pytest.raises(RetentionAuthorityError, match="contradictory"):
        validate_consistency(tmp_path, files, selected)


def test_pending_transition_must_preserve_specific_rule(tmp_path: Path) -> None:
    files, selected = authority(tmp_path)
    path = tmp_path / "tools/ci/python_retention_transitions.json"
    document = json.loads(path.read_text())
    document["records"][0]["superseded_rule"]["justification"] = "Generic replacement prose"
    path.write_text(json.dumps(document))
    with pytest.raises(RetentionAuthorityError, match="compatible maintenance transition"):
        validate_consistency(tmp_path, files, selected)


def test_selection_must_match_effective_tier(tmp_path: Path) -> None:
    files, selected = authority(tmp_path, retained=True)
    selected[0]["tier"] = "T0"
    with pytest.raises(RetentionAuthorityError, match="selection disagrees"):
        validate_consistency(tmp_path, files, selected)


def test_missing_transition_authority_fails_closed(tmp_path: Path) -> None:
    files, selected = authority(tmp_path)
    (tmp_path / "tools/ci/python_retention_transitions.json").unlink()
    with pytest.raises(RetentionAuthorityError, match="unreadable"):
        validate_consistency(tmp_path, files, selected)


def binding_fixture(root: Path) -> tuple[Path, Path]:
    authority(root)
    folder = root / "tools/ci"
    for name in CHECKERS:
        (folder / name).write_text('"""Synthetic governing checker."""\n')
    for name in ("python_fixture_authority.json", "inventory.json", "ratchet.json"):
        (folder / name).write_text("{}")
    (folder / "python_fixture_authority.json").write_text(json.dumps({"entries": []}))
    (root / "pyproject.toml").write_text("[tool]\n")
    (folder / "retained_python_scope_transitions.json").write_text(json.dumps({"records": []}))
    return folder / "inventory.json", folder / "ratchet.json"


@pytest.mark.parametrize("changed", ["python_quality_profiles.py", "python_type_ownership.json",
                                     "python_retention_transitions.json", "python_fixture_authority.json",
                                     "file_length_policy.py", "check_file_lengths.py"])
def test_governing_input_change_invalidates_check(tmp_path: Path, changed: str) -> None:
    inv, ratchet = binding_fixture(tmp_path)
    bindings = bind_inputs(tmp_path, inv, ratchet)
    with (tmp_path / "tools/ci" / changed).open("a") as output:
        output.write("\n")
    with pytest.raises(RetentionAuthorityError, match="changed"):
        verify_bindings(tmp_path, bindings, inv, ratchet)


def test_missing_checker_cannot_disappear_from_binding_set(tmp_path: Path) -> None:
    inv, ratchet = binding_fixture(tmp_path)
    (tmp_path / "tools/ci/python_quality_profiles.py").unlink()
    with pytest.raises(RetentionAuthorityError, match="unavailable"):
        bind_inputs(tmp_path, inv, ratchet)


def test_referenced_scope_evidence_is_bound(tmp_path: Path) -> None:
    inv, ratchet = binding_fixture(tmp_path)
    evidence = tmp_path / "exit.md"
    evidence.write_text("# Synthetic Exit\n")
    (tmp_path / "tools/ci/retained_python_scope_transitions.json").write_text(json.dumps({
        "records": [{"status_path": "exit.md"}],
    }))
    bindings = bind_inputs(tmp_path, inv, ratchet)
    assert bindings["exit.md"]["bytes"] == len(evidence.read_bytes())
    evidence.write_text("# Changed Exit\n")
    with pytest.raises(RetentionAuthorityError, match="changed"):
        verify_bindings(tmp_path, bindings, inv, ratchet)


def test_transition_rationale_is_append_only(tmp_path: Path) -> None:
    authority(tmp_path)
    def git(*args: str) -> str:
        return subprocess.check_output(["git", "-C", str(tmp_path), *args], text=True).strip()
    git("init", "-q")
    git("add", "tools/ci/python_retention_transitions.json")
    git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
        "commit", "-qm", "Explicit forecast")
    revision = git("rev-parse", "HEAD")
    validate_transition_history(tmp_path, [revision])
    path = tmp_path / "tools/ci/python_retention_transitions.json"
    document = json.loads(path.read_text())
    document["records"][0]["reason"] = "Replacement boilerplate"
    path.write_text(json.dumps(document))
    with pytest.raises(RetentionAuthorityError, match="not append-only"):
        validate_transition_history(tmp_path, [revision])


def test_new_retention_requires_exact_superseded_forecast(tmp_path: Path) -> None:
    files, _ = authority(tmp_path)
    folder = tmp_path / "tools/ci"
    ownership_path = folder / "python_type_ownership.json"
    prior_document = json.loads(ownership_path.read_text())
    def git(*args: str) -> str:
        return subprocess.check_output(["git", "-C", str(tmp_path), *args], text=True).strip()
    git("init", "-q")
    git("add", "tools/ci/python_type_ownership.json")
    git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
        "commit", "-qm", "Specific migration forecast")
    revision = git("rev-parse", "HEAD")
    current = json.loads(ownership_path.read_text())
    rule = current["entries"][0]
    rule.update(ownership_class="python_retained", enforcement_tier="T1-future",
                disposition="retained_python_ratcheted")
    ownership_path.write_text(json.dumps(current))
    files[0]["status"] = "retained_ratchet"
    with pytest.raises(RetentionAuthorityError, match="specific superseded rationale"):
        validate_ownership_transitions(tmp_path, files, [revision])
    path = folder / "python_retention_transitions.json"
    ledger = json.loads(path.read_text())
    ledger["records"].append({
        "path": files[0]["path"], "disposition": "retained_python",
        "superseded_rule": prior_document["entries"][0], "current_rule": rule,
    })
    path.write_text(json.dumps(ledger))
    validate_ownership_transitions(tmp_path, files, [revision])
    ledger["records"][-1]["superseded_rule"]["justification"] = "Generic replacement"
    path.write_text(json.dumps(ledger))
    with pytest.raises(RetentionAuthorityError, match="specific superseded rationale"):
        validate_ownership_transitions(tmp_path, files, [revision])


@pytest.mark.parametrize("changed", ["tools/ci/public_author_corrections.json",
                                     "docs/adr/2026/10/0085-public-author-metadata-correction.md",
                                     "tools/ci/public_author_correction.py"])
def test_author_correction_proof_decision_and_checker_are_bound(tmp_path: Path, changed: str) -> None:
    from ci.public_author_correction import DECISION, PROOF_ID, PROOF_PATH, SCHEMA, TARGET_AUTHOR
    inv, ratchet = binding_fixture(tmp_path)
    assert not any("author_correction" in path for path in bind_inputs(tmp_path, inv, ratchet))
    row = {"old": "a" * 40, "new": "b" * 40, "old_author_source": "committer",
           "removed_signature_headers": []}
    (tmp_path / PROOF_PATH).write_text(json.dumps({
        "schema": SCHEMA, "proof": PROOF_ID, "decision": DECISION, "target_author": TARGET_AUTHOR,
        "committer_policy": "preserve", "old_tip": "a" * 40, "new_tip": "b" * 40, "rows": [row]}))
    (tmp_path / DECISION).parent.mkdir(parents=True)
    (tmp_path / DECISION).write_text(f"# Synthetic decision\n\n{PROOF_ID}\n")
    (tmp_path / "tools/ci/public_author_correction.py").write_text('"""Synthetic checker."""\n')
    bindings = bind_inputs(tmp_path, inv, ratchet)
    assert {PROOF_PATH, DECISION, "tools/ci/public_author_correction.py"} <= set(bindings)
    with (tmp_path / changed).open("a") as output:
        output.write("\n")
    with pytest.raises(RetentionAuthorityError, match="changed"):
        verify_bindings(tmp_path, bindings, inv, ratchet)


def test_namespace_successor_keeps_pending_forecast_exact(tmp_path: Path, monkeypatch) -> None:
    from ci import python_retention_authorities as owner
    files, selected = authority(tmp_path)
    current_path = files[0]["path"]
    old_path = current_path.replace("/common_lore_index/", "/repomap_kg/")
    path = tmp_path / "tools/ci/python_retention_transitions.json"
    ledger = json.loads(path.read_text())
    record = ledger["records"][0]
    record["path"] = old_path
    record["superseded_rule"]["module_prefix"] = "repomap_kg.owner"
    path.write_text(json.dumps(ledger))
    monkeypatch.setattr(owner, "_namespace_predecessors", lambda _root: {current_path: old_path})
    validate_consistency(tmp_path, files, selected)
    record["superseded_rule"]["justification"] = "Erased predecessor rationale"
    path.write_text(json.dumps(ledger))
    with pytest.raises(RetentionAuthorityError, match="compatible maintenance transition"):
        validate_consistency(tmp_path, files, selected)


def test_namespace_mapping_does_not_invent_unlisted_successors(tmp_path: Path, monkeypatch) -> None:
    from ci import python_retention_authorities as owner
    files, selected = authority(tmp_path)
    path = tmp_path / "tools/ci/python_retention_transitions.json"
    ledger = json.loads(path.read_text())
    ledger["records"][0]["path"] = files[0]["path"].replace("/common_lore_index/", "/repomap_kg/")
    path.write_text(json.dumps(ledger))
    monkeypatch.setattr(owner, "_namespace_predecessors", lambda _root: {})
    with pytest.raises(RetentionAuthorityError, match="compatible maintenance transition"):
        validate_consistency(tmp_path, files, selected)


def test_namespace_history_cannot_hide_a_new_retained_admission(tmp_path: Path, monkeypatch) -> None:
    from ci import python_retention_authorities as owner
    files, _selected = authority(tmp_path)
    path = tmp_path / "tools/ci/python_type_ownership.json"
    current = json.loads(path.read_text())
    prior = json.loads(path.read_text())
    prior["entries"][0]["module_prefix"] = "repomap_kg.owner"
    path.write_text(json.dumps(prior))
    def git(*args: str) -> str:
        return subprocess.check_output(["git", "-C", str(tmp_path), *args], text=True).strip()
    git("init", "-q")
    git("add", "tools/ci/python_type_ownership.json")
    git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "Prior namespace forecast")
    revision = git("rev-parse", "HEAD")
    rule = current["entries"][0]
    rule.update(ownership_class="python_retained", enforcement_tier="T1-future", disposition="retained_python_ratcheted")
    path.write_text(json.dumps(current))
    files[0]["status"] = "retained_ratchet"
    old_path = files[0]["path"].replace("/common_lore_index/", "/repomap_kg/")
    monkeypatch.setattr(owner, "_namespace_predecessors", lambda _root: {files[0]["path"]: old_path})
    with pytest.raises(RetentionAuthorityError, match="specific superseded rationale"):
        validate_ownership_transitions(tmp_path, files, [revision])
    ledger_path = tmp_path / "tools/ci/python_retention_transitions.json"
    ledger = json.loads(ledger_path.read_text())
    old_current = dict(rule, module_prefix="repomap_kg.owner")
    ledger["records"].append({"path": old_path, "disposition": "retained_python",
        "superseded_rule": prior["entries"][0], "current_rule": old_current})
    ledger_path.write_text(json.dumps(ledger))
    validate_ownership_transitions(tmp_path, files, [revision])
    old_current["justification"] = "Wrong preserved rationale"
    ledger_path.write_text(json.dumps(ledger))
    with pytest.raises(RetentionAuthorityError, match="specific superseded rationale"):
        validate_ownership_transitions(tmp_path, files, [revision])
