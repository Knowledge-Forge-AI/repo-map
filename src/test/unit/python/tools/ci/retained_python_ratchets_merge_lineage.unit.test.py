from __future__ import annotations

import copy
from pathlib import Path

import pytest

from ci.retained_python_ratchet_lineage import (
    LineagePolicyError,
    audit_candidate_lineage,
    document_sha256,
)
from repomap_test_support.retained_ratchet_fixture import (
    BASELINE_PATH,
    MODULE_PATH,
    SCOPE_PATH,
    commit_all,
    empty_scope_registry,
    git,
    selection_item,
    write_json,
)
from src.test.unit.python.tools.ci.retained_python_ratchets_merge_lineage_parts.lineage_fixtures import (
    _create_synthetic_merge,
    _setup_two_transition_history,
)


def test_1_two_sequential_scope_transitions_pass_on_linear_head(tmp_path: Path) -> None:
    repo, _base, _head, genesis, _fix1, final_baseline, _reg = _setup_two_transition_history(tmp_path)
    audit_candidate_lineage(
        repo,
        BASELINE_PATH,
        final_baseline,
        SCOPE_PATH,
        trusted_genesis_sha256=document_sha256(genesis),
    )


def test_2_synthetic_merge_wrapping_sequential_transitions_passes(tmp_path: Path) -> None:
    repo, base_commit, head_commit, genesis, _fix1, final_baseline, _reg = _setup_two_transition_history(tmp_path)
    merge_commit = _create_synthetic_merge(repo, base_commit, head_commit)
    git(repo, "checkout", "-q", merge_commit)
    audit_candidate_lineage(
        repo,
        BASELINE_PATH,
        final_baseline,
        SCOPE_PATH,
        trusted_genesis_sha256=document_sha256(genesis),
    )


def test_3_redundant_ancestor_edge_skipped_only_when_baseline_and_registry_identical(
    tmp_path: Path,
) -> None:
    # 3a: Baseline differs from carrier -> edge base -> merge is not skipped
    repo, base_commit, head_commit, genesis, _fix1, final_baseline, _reg = _setup_two_transition_history(tmp_path)
    git(repo, "checkout", "-q", "-b", "mutated-merge-baseline", head_commit)
    mutated_baseline = copy.deepcopy(final_baseline)
    mutated_baseline["file_length"]["ceilings"] = [{"path": MODULE_PATH, "line_count": 401}]
    write_json(repo / BASELINE_PATH, mutated_baseline)
    git(repo, "add", str(BASELINE_PATH))
    mutated_tree = git(repo, "write-tree").stdout.strip()
    merge_bad_baseline = _create_synthetic_merge(repo, base_commit, head_commit, tree=mutated_tree)
    git(repo, "checkout", "-q", merge_bad_baseline)
    with pytest.raises(LineagePolicyError):
        audit_candidate_lineage(
            repo,
            BASELINE_PATH,
            mutated_baseline,
            SCOPE_PATH,
            trusted_genesis_sha256=document_sha256(genesis),
        )

    # 3b: Registry differs from carrier -> edge base -> merge is not skipped
    git(repo, "checkout", "-q", head_commit)
    extra_registry = empty_scope_registry()
    write_json(repo / SCOPE_PATH, extra_registry)
    git(repo, "add", str(SCOPE_PATH))
    mutated_reg_tree = git(repo, "write-tree").stdout.strip()
    merge_bad_reg = _create_synthetic_merge(repo, base_commit, head_commit, tree=mutated_reg_tree)
    git(repo, "checkout", "-q", merge_bad_reg)
    with pytest.raises(LineagePolicyError):
        audit_candidate_lineage(
            repo,
            BASELINE_PATH,
            final_baseline,
            SCOPE_PATH,
            trusted_genesis_sha256=document_sha256(genesis),
        )


def test_4_merge_local_baseline_debt_increase_is_audited_and_rejected(tmp_path: Path) -> None:
    repo, base_commit, head_commit, genesis, _fix1, final_baseline, _reg = _setup_two_transition_history(tmp_path)
    git(repo, "checkout", "-q", "-b", "debt-merge", head_commit)
    raised = copy.deepcopy(final_baseline)
    raised["ruff"]["findings"] = [{
        "path": MODULE_PATH, "code": "F401", "message": "unused",
        "fingerprint": "f" * 64, "count": 1,
    }]
    write_json(repo / BASELINE_PATH, raised)
    git(repo, "add", str(BASELINE_PATH))
    tree = git(repo, "write-tree").stdout.strip()
    merge_commit = _create_synthetic_merge(repo, base_commit, head_commit, tree=tree)
    git(repo, "checkout", "-q", merge_commit)

    with pytest.raises(LineagePolicyError, match="baseline transition increased debt"):
        audit_candidate_lineage(
            repo,
            BASELINE_PATH,
            raised,
            SCOPE_PATH,
            trusted_genesis_sha256=document_sha256(genesis),
        )


def test_5_merge_local_registry_change_checked_for_append_only_and_unused_authority(
    tmp_path: Path,
) -> None:
    # 5a: Registry not append-only on a merge whose parents carry identical policy blobs
    repo, base_commit, head_commit, genesis, _fix1, final_baseline, registry = _setup_two_transition_history(tmp_path)
    git(repo, "checkout", "-q", "-b", "registry-side", head_commit)
    (repo / "side.txt").write_text("side\n", encoding="utf-8")
    side_commit = commit_all(repo, "advance registry side branch")
    git(repo, "checkout", "-q", "-b", "registry-primary", head_commit)
    (repo / "primary.txt").write_text("primary\n", encoding="utf-8")
    primary_commit = commit_all(repo, "advance registry primary branch")
    tampered_reg = copy.deepcopy(registry)
    tampered_reg["records"][0]["reason"] = "Tampered reason"
    write_json(repo / SCOPE_PATH, tampered_reg)
    git(repo, "add", str(SCOPE_PATH))
    tree1 = git(repo, "write-tree").stdout.strip()
    merge1 = _create_synthetic_merge(repo, primary_commit, side_commit, tree=tree1)
    git(repo, "checkout", "-q", merge1)
    with pytest.raises(LineagePolicyError, match="registry is not append-only"):
        audit_candidate_lineage(
            repo,
            BASELINE_PATH,
            final_baseline,
            SCOPE_PATH,
            trusted_genesis_sha256=document_sha256(genesis),
        )

    # 5b: Unused authority appended to registry in merge commit
    git(repo, "checkout", "-q", primary_commit)
    unused_reg = copy.deepcopy(registry)
    unused_reg["records"].append({
        "old_ownership_manifest_sha256": "c" * 64,
        "new_ownership_manifest_sha256": "d" * 64,
        "old_selected_set_sha256": "e" * 64,
        "new_selected_set_sha256": "f" * 64,
        "changes": [{"old": None, "new": selection_item("repomap_kg.unused", "src/main/python/repomap_kg/unused.py")}],
        "phase": "SYNTHETIC-UNUSED",
        "status_path": "docs/status/2099/01/01/99999-synthetic-unused-exit.md",
        "reason": "Unused authority.",
    })
    status_unused = repo / "docs/status/2099/01/01/99999-synthetic-unused-exit.md"
    status_unused.parent.mkdir(parents=True, exist_ok=True)
    status_unused.write_text("# 99999 SYNTHETIC-UNUSED Exit\n", encoding="utf-8")
    write_json(repo / SCOPE_PATH, unused_reg)
    git(repo, "add", str(SCOPE_PATH), str(status_unused))
    tree2 = git(repo, "write-tree").stdout.strip()
    merge2 = _create_synthetic_merge(repo, primary_commit, side_commit, tree=tree2)
    git(repo, "checkout", "-q", merge2)
    with pytest.raises(LineagePolicyError, match="unused authority"):
        audit_candidate_lineage(
            repo,
            BASELINE_PATH,
            final_baseline,
            SCOPE_PATH,
            trusted_genesis_sha256=document_sha256(genesis),
        )

    # 5c: Unused authority at worktree on clean synthetic merge
    clean_merge = _create_synthetic_merge(repo, base_commit, head_commit)
    git(repo, "checkout", "-q", clean_merge)
    write_json(repo / SCOPE_PATH, unused_reg)
    with pytest.raises(LineagePolicyError, match="unused authority"):
        audit_candidate_lineage(
            repo,
            BASELINE_PATH,
            final_baseline,
            SCOPE_PATH,
            trusted_genesis_sha256=document_sha256(genesis),
        )
