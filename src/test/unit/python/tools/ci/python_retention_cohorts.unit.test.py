"""Unit tests for deterministic cohort inventory schema extension and validation."""

from __future__ import annotations

from typing import Any
from pathlib import Path

import pytest

from ci.python_retention_cohorts import (
    COHORT_SCHEMA,
    HistoryValidationError,
    category_for_path,
    validate_cohorts,
    validate_cohort_transition,
)


def _file(path: str, root: str, profile: str) -> dict[str, Any]:
    return {
        "path": path,
        "root": root,
        "governing_profile": profile,
        "confidence": 0.9,
        "maintained_executable": True,
        "rationale": "Maintained file",
    }


def _valid_inventory() -> dict[str, Any]:
    return {
        "schema": "repomap-python-retention-inventory-v1",
        "cohort_schema": COHORT_SCHEMA,
        "files": [
            _file("tools/ci/tool_a.py", "tools", "clean_tooling"),
            _file("tools/ci/tool_b.py", "tools", "clean_tooling"),
            _file("src/test/support/python/repomap_test_support/helper.py", "test_support", "clean_test_support"),
            _file("src/test/unit/python/test_owner.unit.test.py", "test_owners", "clean_test_owners"),
            _file("src/main/python/repomap_kg/core.py", "product", "retained_python_ratchets"),
        ],
        "cohorts": [
            {
                "id": "test_owners_unit",
                "root": "test_owners",
                "governing_profile": "clean_test_owners",
                "members": ["src/test/unit/python/test_owner.unit.test.py"],
                "rationale": "Unit test suite owners",
                "admission": "pending",
            },
            {
                "id": "test_support_core",
                "root": "test_support",
                "governing_profile": "clean_test_support",
                "members": ["src/test/support/python/repomap_test_support/helper.py"],
                "rationale": "Test support helpers",
                "admission": "admitted",
            },
            {
                "id": "tools_ci",
                "root": "tools",
                "governing_profile": "clean_tooling",
                "members": ["tools/ci/tool_a.py", "tools/ci/tool_b.py"],
                "rationale": "CI scripts and utilities",
                "admission": "admitted",
            },
        ],
    }


def test_legacy_inventory_without_extension_returns_empty() -> None:
    data = {"schema": "repomap-python-retention-inventory-v1", "files": []}
    assert validate_cohorts(data) == []


@pytest.mark.parametrize("has_schema, has_cohorts", [(True, False), (False, True)])
def test_extension_fields_must_appear_together(has_schema: bool, has_cohorts: bool) -> None:
    data: dict[str, Any] = {"files": []}
    if has_schema:
        data["cohort_schema"] = COHORT_SCHEMA
    if has_cohorts:
        data["cohorts"] = []
    with pytest.raises(HistoryValidationError, match="must appear together"):
        validate_cohorts(data)


def test_unsupported_cohort_schema_version_fails() -> None:
    data = {"cohort_schema": "repomap-python-retention-cohorts-v99", "cohorts": []}
    with pytest.raises(HistoryValidationError, match="unsupported cohort_schema version"):
        validate_cohorts(data)


def test_cohorts_not_a_list_fails() -> None:
    data = {"cohort_schema": COHORT_SCHEMA, "cohorts": "invalid"}
    with pytest.raises(HistoryValidationError, match="cohorts must be a list"):
        validate_cohorts(data)


def test_valid_inventory_cohorts_accepted() -> None:
    data = _valid_inventory()
    result = validate_cohorts(data)
    assert len(result) == 3
    assert [c["id"] for c in result] == ["test_owners_unit", "test_support_core", "tools_ci"]


def test_cohort_entry_not_a_mapping_fails() -> None:
    data = _valid_inventory()
    data["cohorts"] = ["not-a-dict"]
    with pytest.raises(HistoryValidationError, match="must be a mapping"):
        validate_cohorts(data)


def test_cohort_missing_required_keys_fails() -> None:
    data = _valid_inventory()
    del data["cohorts"][0]["rationale"]
    with pytest.raises(HistoryValidationError, match="do not match schema"):
        validate_cohorts(data)


def test_cohort_extra_keys_fails_tamper() -> None:
    data = _valid_inventory()
    data["cohorts"][0]["extra_tamper_key"] = True
    with pytest.raises(HistoryValidationError, match="do not match schema"):
        validate_cohorts(data)


@pytest.mark.parametrize("invalid_id", ["", "   ", "Tools-CI", "tools ci", "tools/ci", "tools@ci", "cohort#1"])
def test_invalid_cohort_id_pattern_fails(invalid_id: str) -> None:
    data = _valid_inventory()
    data["cohorts"][2]["id"] = invalid_id
    data["cohorts"].sort(key=lambda c: str(c["id"]))
    with pytest.raises(HistoryValidationError, match="invalid cohort id"):
        validate_cohorts(data)


def test_out_of_order_cohort_records_fails() -> None:
    data = _valid_inventory()
    data["cohorts"] = [data["cohorts"][2], data["cohorts"][0], data["cohorts"][1]]
    with pytest.raises(HistoryValidationError, match="deterministically ordered"):
        validate_cohorts(data)


def test_duplicate_cohort_id_fails() -> None:
    data = _valid_inventory()
    data["cohorts"][0]["id"] = "tools_ci"
    data["cohorts"].sort(key=lambda c: c["id"])
    with pytest.raises(HistoryValidationError, match="duplicate cohort id"):
        validate_cohorts(data)


def test_inapplicable_cohort_root_fails() -> None:
    data = _valid_inventory()
    data["cohorts"][0]["root"] = "product"
    with pytest.raises(HistoryValidationError, match="inapplicable cohort root"):
        validate_cohorts(data)


def test_mismatched_governing_profile_for_root_fails() -> None:
    data = _valid_inventory()
    data["cohorts"][0]["governing_profile"] = "clean_tooling"
    with pytest.raises(HistoryValidationError, match="mismatched governing profile"):
        validate_cohorts(data)


@pytest.mark.parametrize("empty_rationale", ["", "   ", None, 123])
def test_empty_rationale_fails(empty_rationale: object) -> None:
    data = _valid_inventory()
    data["cohorts"][0]["rationale"] = empty_rationale
    with pytest.raises(HistoryValidationError, match="non-empty rationale"):
        validate_cohorts(data)


@pytest.mark.parametrize("bad_admission", ["active", "rejected", "", "unknown", 1])
def test_invalid_admission_state_fails(bad_admission: object) -> None:
    data = _valid_inventory()
    data["cohorts"][0]["admission"] = bad_admission
    with pytest.raises(HistoryValidationError, match="invalid admission state"):
        validate_cohorts(data)


@pytest.mark.parametrize("bad_members", [[], "not-a-list", ["tools/a.py", 123], ["/abs/tools.py"], ["tools/../escape.py"]])
def test_malformed_members_fails(bad_members: object) -> None:
    data = _valid_inventory()
    data["cohorts"][2]["members"] = bad_members
    with pytest.raises(HistoryValidationError, match="member"):
        validate_cohorts(data)


def test_duplicate_members_in_same_cohort_fails() -> None:
    data = _valid_inventory()
    data["cohorts"][2]["members"] = ["tools/ci/tool_a.py", "tools/ci/tool_a.py"]
    with pytest.raises(HistoryValidationError, match="duplicate member in cohort"):
        validate_cohorts(data)


def test_unsorted_members_in_cohort_fails() -> None:
    data = _valid_inventory()
    data["cohorts"][2]["members"] = ["tools/ci/tool_b.py", "tools/ci/tool_a.py"]
    with pytest.raises(HistoryValidationError, match="not sorted"):
        validate_cohorts(data)


def test_duplicate_membership_across_cohorts_fails() -> None:
    data = _valid_inventory()
    # Add second tools cohort containing tool_a.py which is already in tools_ci
    data["cohorts"].append({
        "id": "tools_extra",
        "root": "tools",
        "governing_profile": "clean_tooling",
        "members": ["tools/ci/tool_a.py"],
        "rationale": "Extra tools cohort",
        "admission": "pending",
    })
    data["cohorts"].sort(key=lambda c: c["id"])
    with pytest.raises(HistoryValidationError, match="duplicate membership across cohorts"):
        validate_cohorts(data)


def test_eligible_files_missing_from_cohort_fails() -> None:
    data = _valid_inventory()
    data["cohorts"][2]["members"] = ["tools/ci/tool_a.py"]
    with pytest.raises(HistoryValidationError, match="eligible files missing from cohort"):
        validate_cohorts(data)


def test_non_applicable_root_file_in_cohort_fails() -> None:
    data = _valid_inventory()
    data["cohorts"][0]["members"].append("src/main/python/repomap_kg/core.py")
    data["cohorts"][0]["members"].sort()
    with pytest.raises(HistoryValidationError, match="cohort member root mismatch"):
        validate_cohorts(data)


def test_member_not_in_files_or_transitions_fails() -> None:
    data = _valid_inventory()
    data["cohorts"][2]["members"].append("tools/ci/nonexistent.py")
    data["cohorts"][2]["members"].sort()
    with pytest.raises(HistoryValidationError, match="not an eligible current or transitioned file"):
        validate_cohorts(data)


def test_transition_source_member_accepted_if_root_matches() -> None:
    data = _valid_inventory()
    data["path_transitions"] = [{
        "from": "tools/ci/retired_tool.py",
        "to": None,
        "rationale": "Retired older script",
    }]
    data["cohorts"][2]["members"].append("tools/ci/retired_tool.py")
    data["cohorts"][2]["members"].sort()
    assert validate_cohorts(data)


def test_decomposition_successor_cannot_move_to_pending_cohort() -> None:
    data = _valid_inventory()
    data["decompositions"] = [{
        "from": "tools/ci/tool_a.py",
        "to": ["src/test/unit/python/test_owner.unit.test.py"],
        "rationale": "Extract helper",
    }]
    with pytest.raises(HistoryValidationError, match="cannot move to pending cohort"):
        validate_cohorts(data)


def test_category_for_path_all_roots() -> None:
    assert category_for_path("src/main/python/pkg/mod.py") == "product"
    assert category_for_path("src/test/fixtures/f.py") == "fixtures"
    assert category_for_path("src/test/conftest.py") == "conftest"
    assert category_for_path("src/test/support/python/s.py") == "test_support"
    assert category_for_path("src/test/unit/python/u.py") == "test_owners"
    assert category_for_path("src/test/int/python/i.py") == "test_owners"
    assert category_for_path("tools/ci/t.py") == "tools"
    with pytest.raises(HistoryValidationError, match="no maintained root"):
        category_for_path("other/file.py")


@pytest.mark.parametrize("record_kind", ["path_transitions", "decompositions"])
def test_admitted_replacement_chain_keeps_original_cohort(record_kind: str) -> None:
    import copy
    old = _valid_inventory()
    new = copy.deepcopy(old)
    source, successor = "tools/ci/tool_a.py", "tools/ci/replacement.py"
    new["files"][0]["path"] = successor
    new["cohorts"][2]["members"] = sorted([successor, "tools/ci/tool_b.py"])
    new[record_kind] = [
        {"from": source, "to": ["tools/ci/intermediate.py"], "rationale": "Extract owner"},
        {"from": "tools/ci/intermediate.py", "to": [successor], "rationale": "Rename owner"},
    ]
    validate_cohort_transition(old, new)


@pytest.mark.parametrize("failure", [
    "silent", "terminated", "partial_termination", "cycle", "other_cohort", "source_present",
])
def test_admitted_replacement_cannot_drop_or_reassign_obligations(failure: str) -> None:
    import copy
    old = _valid_inventory()
    new = copy.deepcopy(old)
    source, target = "tools/ci/tool_a.py", "tools/ci/replacement.py"
    new["files"][0]["path"] = target
    new["cohorts"][2]["members"] = sorted([target, "tools/ci/tool_b.py"])
    new["path_transitions"] = [{"from": source, "to": [target], "rationale": "Move owner"}]
    if failure == "silent":
        new["path_transitions"] = []
    elif failure == "terminated":
        new["path_transitions"][0]["to"] = None
    elif failure in {"cycle", "partial_termination"}:
        new["path_transitions"][0]["to"].append("tools/ci/intermediate.py")
        new["path_transitions"].append({"from": "tools/ci/intermediate.py",
            "to": source if failure == "cycle" else None, "rationale": "Invalid chain"})
    elif failure in {"other_cohort", "source_present"}:
        member = source if failure == "source_present" else target
        if failure == "source_present":
            new["files"].append(old["files"][0])
        else:
            new["cohorts"][2]["members"].remove(target)
        new["cohorts"].append(dict(new["cohorts"][2], id="tools_other", members=[member]))
    with pytest.raises(HistoryValidationError):
        validate_cohort_transition(old, new)


@pytest.mark.parametrize("debt", [True, False])
def test_replacement_members_need_fresh_atomic_evidence(tmp_path: Path, debt: bool) -> None:
    import copy
    from ci.python_retention_cohort_evidence import evaluate_cohorts
    old = _valid_inventory()
    old["files"] = old["files"][:2]
    old["cohorts"] = old["cohorts"][2:]
    new = copy.deepcopy(old)
    successor = "tools/ci/replacement.py"
    new["files"][0]["path"] = successor
    members = sorted([successor, "tools/ci/tool_b.py"])
    new["cohorts"][0]["members"] = members
    new["decompositions"] = [{"from": "tools/ci/tool_a.py", "to": members,
                              "rationale": "Split responsibility within its stable cohort"}]
    validate_cohort_transition(old, new)
    for member in members:
        path = tmp_path / member
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("value = 1\n")
    checks = {name: dict(status="passed", completed=True, findings=[])
              for name in ("ruff", "mypy", "file_length")}
    if debt:
        checks["mypy"].update(status="failed", findings=[{"path": successor}])
    result = evaluate_cohorts(new["cohorts"], {"tools": dict(
        status="failed" if debt else "passed", paths=members, analyzed_paths=members,
        checks=checks)}, tmp_path, members, [])
    assert result["enforced"]["tools"] == ([] if debt else members)
    assert result["regressions"] == (["tools_ci"] if debt else [])
