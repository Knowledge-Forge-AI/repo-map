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
    path = "src/main/python/repomap_kg/owner.py"
    rule = {
        "module_prefix": "repomap_kg.owner", "match": "exact",
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
    selected = [{"module": "repomap_kg.owner", "path": path,
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
