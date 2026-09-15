from __future__ import annotations

import copy
from pathlib import Path

import pytest

from ci.retained_python_ratchet_lineage import (
    LineagePolicyError,
    audit_candidate_lineage,
    document_sha256,
)
from ci.retained_python_ratchets import compare_snapshot, main
from ci.retained_python_records import BaselineDocument, baseline_document
from repomap_test_support.retained_ratchet_fixture import (
    BASELINE_PATH,
    MODULE_PATH,
    SCOPE_PATH,
    baseline_fixture,
    commit_all,
    git,
    initialize_repository,
    snapshot_fixture,
    write_json,
)


def _audit(
    repo: Path,
    candidate: BaselineDocument | None = None,
    genesis: BaselineDocument | None = None,
) -> None:
    trusted = genesis or baseline_fixture()
    audit_candidate_lineage(
        repo,
        BASELINE_PATH,
        candidate or baseline_fixture(),
        SCOPE_PATH,
        trusted_genesis_sha256=document_sha256(trusted),
    )


@pytest.mark.parametrize("dimension", ["ruff", "mypy", "imports", "length"])
def test_manually_raised_candidate_baseline_cannot_self_authorize(
    tmp_path: Path, dimension: str
) -> None:
    genesis = baseline_fixture()
    repo = initialize_repository(tmp_path, genesis)
    actual = snapshot_fixture()
    if dimension == "ruff":
        actual["ruff"]["findings"] = [{
            "path": MODULE_PATH, "code": "F401", "message": "unused",
            "fingerprint": "f" * 64, "count": 1,
        }]
    elif dimension == "mypy":
        actual["mypy"]["findings"] = [{
            "module": "repomap_kg.future", "path": MODULE_PATH,
            "error_code": "arg-type", "normalized_fingerprint": "e" * 64,
            "count": 1,
        }]
    elif dimension == "imports":
        actual["migration_direction_imports"]["edges"] = [{
            "source_module": "repomap_kg.future", "source_path": MODULE_PATH,
            "target_module": "repomap_kg.planned", "target_tier": "T3",
        }]
    else:
        actual["file_length"]["ceilings"] = [
            {"path": MODULE_PATH, "line_count": 401}
        ]
    raised = baseline_document(actual)

    assert compare_snapshot(actual, raised, mode="check")["classification"] == "passed"
    with pytest.raises(LineagePolicyError, match="increased debt"):
        _audit(repo, raised)


def test_generate_refuses_a_deleted_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    repo = initialize_repository(tmp_path, baseline_fixture())
    (repo / BASELINE_PATH).unlink()
    monkeypatch.chdir(repo)
    monkeypatch.setattr("ci.retained_python_ratchets.ROOT", repo)
    monkeypatch.setattr(
        "ci.retained_python_ratchets.collect_snapshot", lambda _path: snapshot_fixture()
    )

    assert main(["--baseline", str(BASELINE_PATH), "--generate-baseline"]) == 2
    assert not (repo / BASELINE_PATH).exists()
    assert '"classification": "tool-failure"' in capsys.readouterr().out


def test_deleted_then_reintroduced_baseline_is_rejected(tmp_path: Path) -> None:
    baseline = baseline_fixture()
    repo = initialize_repository(tmp_path, baseline)
    (repo / BASELINE_PATH).unlink()
    commit_all(repo, "delete baseline")
    write_json(repo / BASELINE_PATH, baseline)
    commit_all(repo, "reintroduce baseline")

    with pytest.raises(LineagePolicyError, match="deleted"):
        _audit(repo)


def test_prior_committed_debt_raise_cannot_be_hidden_by_unchanged_head(
    tmp_path: Path,
) -> None:
    raised = baseline_fixture()
    repo = initialize_repository(tmp_path, raised)
    raised["ruff"]["findings"] = [{
        "path": MODULE_PATH, "code": "F401", "message": "unused",
        "fingerprint": "f" * 64, "count": 1,
    }]
    write_json(repo / BASELINE_PATH, raised)
    commit_all(repo, "raise debt")
    (repo / "unchanged.txt").write_text("later\n", encoding="utf-8")
    commit_all(repo, "leave raised debt unchanged")

    with pytest.raises(LineagePolicyError, match="increased debt"):
        _audit(repo, raised)


def test_raised_baseline_on_merged_side_history_is_audited(tmp_path: Path) -> None:
    baseline = baseline_fixture()
    repo = initialize_repository(tmp_path, baseline)
    primary = git(repo, "branch", "--show-current").stdout.strip()
    git(repo, "checkout", "-q", "-b", "raised-side")
    raised = copy.deepcopy(baseline)
    raised["ruff"]["findings"] = [{
        "path": MODULE_PATH, "code": "F401", "message": "unused",
        "fingerprint": "f" * 64, "count": 1,
    }]
    write_json(repo / BASELINE_PATH, raised)
    commit_all(repo, "raise debt on side history")
    git(repo, "checkout", "-q", primary)
    (repo / "primary.txt").write_text("primary\n", encoding="utf-8")
    commit_all(repo, "advance primary history")
    git(repo, "merge", "-q", "--no-ff", "raised-side", "-m", "merge raised side")
    write_json(repo / BASELINE_PATH, baseline)
    commit_all(repo, "restore baseline after merge")

    with pytest.raises(LineagePolicyError, match="increased debt"):
        _audit(repo, baseline)


def test_merge_restoring_parent_debt_is_audited_against_every_parent(
    tmp_path: Path,
) -> None:
    raised = baseline_fixture()
    raised["ruff"]["findings"] = [{
        "path": MODULE_PATH, "code": "F401", "message": "unused",
        "fingerprint": "f" * 64, "count": 1,
    }]
    repo = initialize_repository(tmp_path, raised)
    primary = git(repo, "branch", "--show-current").stdout.strip()
    git(repo, "checkout", "-q", "-b", "raised-side")
    (repo / "side.txt").write_text("side\n", encoding="utf-8")
    commit_all(repo, "retain debt on side history")
    git(repo, "checkout", "-q", primary)
    lowered = baseline_fixture()
    write_json(repo / BASELINE_PATH, lowered)
    (repo / "primary.txt").write_text("primary\n", encoding="utf-8")
    commit_all(repo, "lower debt on primary history")
    git(repo, "merge", "-q", "--no-ff", "--no-commit", "raised-side")
    write_json(repo / BASELINE_PATH, raised)
    commit_all(repo, "merge side debt into primary history")

    with pytest.raises(LineagePolicyError, match="increased debt"):
        _audit(repo, raised, raised)


def test_rename_into_t3_namespace_is_rejected_without_scope_record(
    tmp_path: Path,
) -> None:
    baseline = baseline_fixture()
    repo = initialize_repository(tmp_path, baseline)
    renamed = repo / "src/main/python/repomap_kg/planned/future.py"
    renamed.parent.mkdir(parents=True)
    git(repo, "mv", MODULE_PATH, str(renamed.relative_to(repo)))
    candidate = copy.deepcopy(baseline)
    candidate["selection"]["modules"] = []
    write_json(repo / BASELINE_PATH, candidate)
    commit_all(repo, "rename and demote retained module")

    with pytest.raises(LineagePolicyError, match="scope transition"):
        _audit(repo, candidate)


def test_same_path_ownership_demotion_is_rejected_without_scope_record(
    tmp_path: Path,
) -> None:
    baseline = baseline_fixture()
    repo = initialize_repository(tmp_path, baseline)
    candidate = copy.deepcopy(baseline)
    candidate["selection"]["modules"] = []
    write_json(repo / BASELINE_PATH, candidate)
    commit_all(repo, "demote retained ownership")

    with pytest.raises(LineagePolicyError, match="scope transition"):
        _audit(repo, candidate)


def test_shallow_history_is_a_tool_failure(tmp_path: Path) -> None:
    source = initialize_repository(tmp_path, baseline_fixture())
    clone = tmp_path / "shallow"
    git(tmp_path, "clone", "-q", "--depth", "1", f"file://{source}", str(clone))

    with pytest.raises(RuntimeError, match="shallow"):
        _audit(clone)
