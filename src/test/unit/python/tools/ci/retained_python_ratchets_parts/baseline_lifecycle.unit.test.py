from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from ci.python_type_check import TypeCheckToolError
from ci.python_type_ownership import (
    OwnershipManifest,
    OwnershipManifestError,
    classify_modules,
)
from ci.retained_python_ratchet_lineage import (
    LineagePolicyError,
    _assert_clean_additions,
)
from ci.retained_python_ratchets import (
    BASELINE_SCHEMA,
    RESULT_SCHEMA,
    RatchetContractError,
    baseline_document,
    compare_snapshot,
    main,
    render_document,
    validate_baseline,
    write_baseline_atomic,
)
from ci.retained_python_records import (
    BaselineDocument,
    SelectionModuleRecord,
    SnapshotDocument,
)


def snapshot_fixture() -> SnapshotDocument:
    return {
        "ownership": {"manifest_path": "tools/ci/python_type_ownership.json", "sha256": "a" * 64},
        "tools": {"mypy": "2.1.0", "ruff": "0.16.2", "ruff_rules": ["F"], "ruff_target_version": "py312"},
        "selection": {
            "ownership_classes": ["cross_language_contract", "python_retained"],
            "tiers": ["T0", "T1-future", "T1-seed"],
            "modules": [
                {
                    "module": "repomap_kg.future",
                    "path": "src/main/python/repomap_kg/future.py",
                    "ownership_class": "python_retained",
                    "tier": "T1-future",
                }
            ],
        },
        "ruff": {"findings": []},
        "mypy": {"findings": []},
        "migration_direction_imports": {"edges": []},
        "file_length": {"warning_limit": 400, "failure_limit": 1000, "ceilings": [], "hard_failures": []},
    }


def test_ownership_manifest_drift_is_a_stale_baseline_policy_finding() -> None:
    snapshot = snapshot_fixture()
    baseline = baseline_document(snapshot)
    snapshot["ownership"] = {
        "manifest_path": snapshot["ownership"]["manifest_path"],
        "sha256": "b" * 64,
    }

    result = compare_snapshot(snapshot, baseline, mode="check")

    assert result["classification"] == "policy-finding"
    assert isinstance(result["ownership"], dict)
    assert result["ownership"]["sha256_match"] is False


def test_baseline_is_closed_sorted_and_rejects_duplicate_paths() -> None:
    baseline = baseline_document(snapshot_fixture())
    assert baseline["schema"] == BASELINE_SCHEMA
    validate_baseline(baseline)
    baseline["file_length"]["ceilings"] = [
        {"path": "same.py", "line_count": 401},
        {"path": "same.py", "line_count": 402},
    ]

    with pytest.raises(RatchetContractError, match="duplicate"):
        validate_baseline(baseline)


def test_baseline_generation_is_explicit_atomic_and_newline_terminated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "baseline.json"
    replacements: list[tuple[Path, Path]] = []
    real_replace = os.replace

    def observed_replace(source: str, target: str) -> None:
        replacements.append((Path(source), Path(target)))
        real_replace(source, target)

    monkeypatch.setattr(os, "replace", observed_replace)
    document = baseline_document(snapshot_fixture())

    write_baseline_atomic(destination, document)

    assert replacements and replacements[-1][1] == destination
    assert replacements[-1][0].parent == destination.parent
    assert json.loads(destination.read_text(encoding="utf-8")) == document
    assert destination.read_bytes().endswith(b"\n")
    assert not tuple(tmp_path.glob("*.tmp"))


def test_check_result_schema_is_closed_and_improvement_stays_blocking() -> None:
    snapshot = snapshot_fixture()
    baseline = baseline_document(snapshot)
    baseline["ruff"]["findings"] = [
        {"path": "src/main/python/repomap_kg/future.py", "code": "F401", "message": "unused", "fingerprint": "f" * 64, "count": 1}
    ]

    result = compare_snapshot(snapshot, baseline, mode="check")

    assert set(result) == {
        "schema",
        "mode",
        "status",
        "classification",
        "ownership",
        "selection",
        "tools",
        "ruff",
        "mypy",
        "migration_direction_imports",
        "file_length",
        "summary", "profile_path_facts",
    }
    assert result["schema"] == RESULT_SCHEMA
    assert result["classification"] == "policy-finding"
    assert isinstance(result["ruff"], dict)
    ruff_comparison = result["ruff"]["comparison"]
    assert isinstance(ruff_comparison, dict)
    assert ruff_comparison["removed"]
    rendered = render_document(result)
    assert rendered.endswith("\n") and not rendered.endswith("\n\n")
    assert str(Path.cwd().resolve()) not in rendered


def test_check_is_read_only_and_generation_refuses_upward_laundering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    snapshot = snapshot_fixture()
    monkeypatch.setattr("ci.retained_python_ratchets.ROOT", tmp_path)

    def audit_candidate(_root: Path, _baseline: Path, candidate: BaselineDocument, _scopes: Path) -> None:
        if candidate["ruff"]["findings"]:
            raise LineagePolicyError("synthetic upward transition")

    monkeypatch.setattr(
        "ci.retained_python_ratchet_lineage.audit_candidate_lineage",
        audit_candidate,
    )
    baseline = tmp_path / "baseline.json"
    baseline.write_text(render_document(baseline_document(snapshot)), encoding="utf-8")
    monkeypatch.setattr("ci.retained_python_ratchets.collect_snapshot", lambda _path: snapshot)
    monkeypatch.setattr(
        "ci.retained_python_ratchets.write_baseline_atomic",
        lambda *_args: pytest.fail("check or rejected generation must not write"),
    )
    assert main(["--baseline", "baseline.json"]) == 0
    snapshot["ruff"]["findings"] = [
        {"path": "src/main/python/repomap_kg/future.py", "code": "F401", "message": "unused", "fingerprint": "f" * 64, "count": 1}
    ]
    assert main(["--baseline", "baseline.json", "--generate-baseline"]) == 1
    assert json.loads(baseline.read_text(encoding="utf-8"))["ruff"]["findings"] == []
    assert '"classification": "policy-finding"' in capsys.readouterr().out


def test_environment_attestation_failure_is_classified_as_tool_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail_collection(_path: Path) -> SnapshotDocument:
        raise TypeCheckToolError("synthetic sealed-environment failure")

    monkeypatch.setattr("ci.retained_python_ratchets.collect_snapshot", fail_collection)

    assert main([]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result == {
        "classification": "tool-failure",
        "mode": "check",
        "schema": RESULT_SCHEMA,
        "status": "failed",
        "tool_failure": "TypeCheckToolError",
    }


def test_generation_refuses_retained_hard_file_length_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    snapshot = snapshot_fixture()
    snapshot["file_length"]["hard_failures"] = [
        {"path": "src/main/python/repomap_kg/future.py", "line_count": 1001}
    ]
    monkeypatch.setattr("ci.retained_python_ratchets.ROOT", tmp_path)
    destination = tmp_path / "baseline.json"
    destination.write_text(
        render_document(baseline_document(snapshot_fixture())), encoding="utf-8"
    )
    monkeypatch.setattr("ci.retained_python_ratchets.collect_snapshot", lambda _path: snapshot)

    before = destination.read_bytes()
    assert main(["--baseline", "baseline.json", "--generate-baseline"]) == 1
    assert destination.read_bytes() == before
    result = json.loads(capsys.readouterr().out)
    assert result["classification"] == "policy-finding"
    assert result["summary"]["hard_failures"] == 1


def test_unclassified_maintained_module_raises_ownership_manifest_error(tmp_path: Path) -> None:
    manifest = OwnershipManifest(tuple())
    modules = {"repomap_kg.unclassified": tmp_path / "unclassified.py"}
    with pytest.raises(OwnershipManifestError, match="unclassified maintained modules"):
        classify_modules(modules, manifest)


def test_assert_clean_additions_enforces_zero_findings_and_line_limits() -> None:
    additions: tuple[SelectionModuleRecord, ...] = ({
        "module": "repomap_kg.dirty",
        "path": "src/main/python/repomap_kg/dirty.py",
        "ownership_class": "python_retained",
        "tier": "T1-future",
    },)
    after = baseline_document(snapshot_fixture())
    after["ruff"]["findings"] = [{
        "path": "src/main/python/repomap_kg/dirty.py",
        "code": "F401",
        "message": "unused",
        "fingerprint": "f" * 64,
        "count": 1,
    }]
    with pytest.raises(LineagePolicyError, match="new retained module is not clean"):
        _assert_clean_additions(additions, after)

    # Line limit ceiling violation is also rejected
    long_additions: tuple[SelectionModuleRecord, ...] = ({
        "module": "repomap_kg.long",
        "path": "src/main/python/repomap_kg/long.py",
        "ownership_class": "python_retained",
        "tier": "T1-future",
    },)
    after_long = baseline_document(snapshot_fixture())
    after_long["file_length"]["ceilings"] = [{"path": "src/main/python/repomap_kg/long.py", "line_count": 401}]
    with pytest.raises(LineagePolicyError, match="new retained module is not clean"):
        _assert_clean_additions(long_additions, after_long)

    # Clean addition passes
    clean_additions: tuple[SelectionModuleRecord, ...] = ({
        "module": "repomap_kg.clean",
        "path": "src/main/python/repomap_kg/clean.py",
        "ownership_class": "python_retained",
        "tier": "T1-future",
    },)
    clean_after = baseline_document(snapshot_fixture())
    _assert_clean_additions(clean_additions, clean_after)
