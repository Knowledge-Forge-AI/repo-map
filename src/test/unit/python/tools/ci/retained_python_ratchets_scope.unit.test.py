from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from ci.retained_python_ratchet_lineage import (
    LineagePolicyError,
    audit_candidate_lineage,
    document_sha256,
    selection_digest,
    validate_scope_registry,
)
from ci.retained_python_ratchets import main
from ci.retained_python_records import (
    BaselineDocument,
    ScopeChange,
    ScopeRegistry,
    ScopeTransitionRecord,
)
from repomap_test_support.retained_ratchet_fixture import (
    BASELINE_PATH,
    MODULE_PATH,
    SCOPE_PATH,
    STATUS_PATH,
    baseline_fixture,
    commit_all,
    initialize_repository,
    selection_item,
    snapshot_fixture,
    write_json,
    write_status,
)


def _audit(
    repo: Path, candidate: BaselineDocument, genesis: BaselineDocument
) -> None:
    audit_candidate_lineage(
        repo,
        BASELINE_PATH,
        candidate,
        SCOPE_PATH,
        trusted_genesis_sha256=document_sha256(genesis),
    )


def _empty_scope_registry() -> ScopeRegistry:
    return {
        "schema": "repomap-retained-python-scope-transitions-v1",
        "records": [],
    }


def _scope_record(
    before: BaselineDocument,
    after: BaselineDocument,
    changes: list[ScopeChange],
) -> ScopeTransitionRecord:
    return {
        "old_ownership_manifest_sha256": before["ownership"]["sha256"],
        "new_ownership_manifest_sha256": after["ownership"]["sha256"],
        "old_selected_set_sha256": selection_digest(before),
        "new_selected_set_sha256": selection_digest(after),
        "changes": changes,
        "phase": "SYNTHETIC-SCOPE1",
        "status_path": STATUS_PATH.as_posix(),
        "reason": "Synthetic public-safe architecture migration.",
    }


def test_manual_selection_record_removal_is_blocked(tmp_path: Path) -> None:
    before = baseline_fixture()
    repo = initialize_repository(tmp_path, before)
    after = copy.deepcopy(before)
    after["selection"]["modules"] = []

    with pytest.raises(LineagePolicyError, match="scope transition"):
        _audit(repo, after, before)


def test_downward_debt_refresh_succeeds(tmp_path: Path) -> None:
    before = baseline_fixture()
    before["ruff"]["findings"] = [{
        "path": MODULE_PATH, "code": "F401", "message": "unused",
        "fingerprint": "f" * 64, "count": 1,
    }]
    repo = initialize_repository(tmp_path, before)
    after = baseline_fixture()

    _audit(repo, after, before)


def test_new_clean_retained_module_succeeds(tmp_path: Path) -> None:
    before = baseline_fixture()
    repo = initialize_repository(tmp_path, before)
    after = copy.deepcopy(before)
    after["selection"]["modules"].append(
        selection_item("repomap_kg.new_clean", "src/main/python/repomap_kg/new_clean.py")
    )

    _audit(repo, after, before)


def test_new_retained_module_with_debt_fails(tmp_path: Path) -> None:
    before = baseline_fixture()
    repo = initialize_repository(tmp_path, before)
    after = copy.deepcopy(before)
    path = "src/main/python/repomap_kg/new_debt.py"
    after["selection"]["modules"].append(selection_item("repomap_kg.new_debt", path))
    after["ruff"]["findings"] = [{
        "path": path, "code": "F401", "message": "unused",
        "fingerprint": "f" * 64, "count": 1,
    }]

    with pytest.raises(LineagePolicyError, match="clean"):
        _audit(repo, after, before)


def test_exact_scope_transition_record_authorizes_removal(tmp_path: Path) -> None:
    before = baseline_fixture()
    repo = initialize_repository(tmp_path, before)
    after = copy.deepcopy(before)
    removed = after["selection"]["modules"].pop()
    after["ownership"]["sha256"] = "b" * 64
    record = _scope_record(before, after, [{"old": removed, "new": None}])
    registry = _empty_scope_registry()
    registry["records"].append(record)
    write_json(repo / SCOPE_PATH, registry)
    write_status(repo)

    _audit(repo, after, before)


def test_clean_additions_with_authorized_scope_transition_succeeds(tmp_path: Path) -> None:
    before = baseline_fixture()
    repo = initialize_repository(tmp_path, before)
    after = copy.deepcopy(before)
    admitted = selection_item(
        "repomap_kg.artifacts.bundle",
        "src/main/python/repomap_kg/artifacts/bundle.py",
    )
    after["selection"]["modules"].append(admitted)
    after["selection"]["modules"].sort(key=lambda item: item["module"])
    after["ownership"]["sha256"] = "c" * 64
    record = _scope_record(before, after, [{"old": None, "new": admitted}])
    registry = _empty_scope_registry()
    registry["records"].append(record)
    write_json(repo / SCOPE_PATH, registry)
    write_status(repo)

    _audit(repo, after, before)


def test_scope_transition_with_mismatched_manifest_digest_fails(tmp_path: Path) -> None:
    before = baseline_fixture()
    repo = initialize_repository(tmp_path, before)
    after = copy.deepcopy(before)
    admitted = selection_item(
        "repomap_kg.artifacts.bundle",
        "src/main/python/repomap_kg/artifacts/bundle.py",
    )
    after["selection"]["modules"].append(admitted)
    after["selection"]["modules"].sort(key=lambda item: item["module"])
    after["ownership"]["sha256"] = "c" * 64
    record = _scope_record(before, after, [{"old": None, "new": admitted}])
    record["new_ownership_manifest_sha256"] = "d" * 64
    registry = _empty_scope_registry()
    registry["records"].append(record)
    write_json(repo / SCOPE_PATH, registry)
    write_status(repo)

    with pytest.raises(LineagePolicyError, match="scope transition lacks exact authority"):
        _audit(repo, after, before)


def test_second_appended_scope_record_need_not_sort_by_digest(tmp_path: Path) -> None:
    before = baseline_fixture()
    before["ownership"]["sha256"] = "f" * 64
    before["selection"]["modules"].append(
        selection_item("repomap_kg.second", "src/main/python/repomap_kg/second.py")
    )
    repo = initialize_repository(tmp_path, before)
    write_status(repo)

    first = copy.deepcopy(before)
    first_removed = first["selection"]["modules"].pop(0)
    first["ownership"]["sha256"] = "e" * 64
    first_record = _scope_record(
        before, first, [{"old": first_removed, "new": None}]
    )
    registry = _empty_scope_registry()
    registry["records"].append(first_record)
    write_json(repo / BASELINE_PATH, first)
    write_json(repo / SCOPE_PATH, registry)
    commit_all(repo, "authorize first scope transition")

    second = copy.deepcopy(first)
    second_removed = second["selection"]["modules"].pop()
    second["ownership"]["sha256"] = "d" * 64
    second_record = _scope_record(
        first, second, [{"old": second_removed, "new": None}]
    )
    registry["records"].append(second_record)
    keys = [
        (
            record["old_ownership_manifest_sha256"],
            record["new_ownership_manifest_sha256"],
            record["old_selected_set_sha256"],
            record["new_selected_set_sha256"],
        )
        for record in registry["records"]
    ]
    assert keys != sorted(keys)
    write_json(repo / BASELINE_PATH, second)
    write_json(repo / SCOPE_PATH, registry)
    commit_all(repo, "authorize second scope transition")

    _audit(repo, second, before)


def test_scope_registry_rejects_rewriting_committed_authority(tmp_path: Path) -> None:
    before = baseline_fixture()
    repo = initialize_repository(tmp_path, before)
    after = copy.deepcopy(before)
    removed = after["selection"]["modules"].pop()
    after["ownership"]["sha256"] = "b" * 64
    record = _scope_record(before, after, [{"old": removed, "new": None}])
    registry = _empty_scope_registry()
    registry["records"].append(record)
    write_json(repo / BASELINE_PATH, after)
    write_json(repo / SCOPE_PATH, registry)
    write_status(repo)
    commit_all(repo, "authorize scope transition")

    registry["records"][0]["reason"] = "Rewritten authority."
    write_json(repo / SCOPE_PATH, registry)

    with pytest.raises(LineagePolicyError, match="append-only"):
        _audit(repo, after, before)


def test_scope_registry_rejects_unused_authority(tmp_path: Path) -> None:
    before = baseline_fixture()
    repo = initialize_repository(tmp_path, before)
    hypothetical = copy.deepcopy(before)
    removed = hypothetical["selection"]["modules"].pop()
    hypothetical["ownership"]["sha256"] = "b" * 64
    registry = _empty_scope_registry()
    registry["records"].append(
        _scope_record(before, hypothetical, [{"old": removed, "new": None}])
    )
    write_json(repo / SCOPE_PATH, registry)
    write_status(repo)

    with pytest.raises(LineagePolicyError, match="unused authority"):
        _audit(repo, before, before)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("malformed", "scope transition record is invalid"),
        ("overbroad", "scope transition record is overbroad or incomplete"),
    ],
)
def test_malformed_or_overbroad_scope_record_fails(
    tmp_path: Path, mutation: str, message: str
) -> None:
    before = baseline_fixture()
    repo = initialize_repository(tmp_path, before)
    after = copy.deepcopy(before)
    removed = after["selection"]["modules"].pop()
    after["ownership"]["sha256"] = "b" * 64
    changes: list[ScopeChange] = [{"old": removed, "new": None}]
    record: dict[str, object] = dict(_scope_record(before, after, changes))
    if mutation == "malformed":
        record.pop("reason")
    else:
        record_changes = record["changes"]
        assert isinstance(record_changes, list)
        record_changes.append({
            "old": None,
            "new": selection_item("repomap_kg.unrelated", "src/main/python/repomap_kg/unrelated.py"),
        })
    write_json(repo / SCOPE_PATH, {
        "schema": "repomap-retained-python-scope-transitions-v1",
        "records": [record],
    })
    write_status(repo)

    with pytest.raises(LineagePolicyError, match=message):
        _audit(repo, after, before)


def test_malformed_scope_registry_is_a_policy_finding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    before = baseline_fixture()
    repo = initialize_repository(tmp_path, before)
    malformed: dict[str, object] = {
        "schema": "repomap-retained-python-scope-transitions-v1",
        "records": [{}],
    }
    write_json(repo / SCOPE_PATH, malformed)
    monkeypatch.chdir(repo)
    monkeypatch.setattr("ci.retained_python_ratchets.ROOT", repo)
    monkeypatch.setattr(
        "ci.retained_python_ratchets.collect_snapshot", lambda _path: snapshot_fixture()
    )

    def audit(_root, _baseline, _candidate, scope_path):
        document = json.loads((repo / scope_path).read_text(encoding="utf-8"))
        validate_scope_registry(document)

    monkeypatch.setattr(
        "ci.retained_python_ratchets._lineage_contract",
        lambda: (SCOPE_PATH, LineagePolicyError, audit),
    )

    assert main([
        "--baseline", str(BASELINE_PATH),
        "--scope-transitions", str(SCOPE_PATH),
    ]) == 1
    assert '"classification": "policy-finding"' in capsys.readouterr().out
