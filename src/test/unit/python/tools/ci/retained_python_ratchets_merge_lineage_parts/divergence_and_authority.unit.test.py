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
    baseline_fixture,
    commit_all,
    git,
    initialize_repository,
    write_json,
)
from src.test.unit.python.tools.ci.retained_python_ratchets_merge_lineage_parts.lineage_fixtures import (
    _create_synthetic_merge,
    _setup_two_transition_history,
)


def test_6_divergent_merge_restoring_debt_remains_rejected(tmp_path: Path) -> None:
    genesis = baseline_fixture()
    genesis["ruff"]["findings"] = [{
        "path": MODULE_PATH, "code": "F401", "message": "unused",
        "fingerprint": "f" * 64, "count": 1,
    }]
    repo = initialize_repository(tmp_path, genesis)
    primary = git(repo, "branch", "--show-current").stdout.strip()
    git(repo, "checkout", "-q", "-b", "retained-debt-branch")
    (repo / "side.txt").write_text("side\n", encoding="utf-8")
    commit_all(repo, "retain debt on side branch")

    git(repo, "checkout", "-q", primary)
    lowered = baseline_fixture()
    write_json(repo / BASELINE_PATH, lowered)
    (repo / "primary.txt").write_text("primary\n", encoding="utf-8")
    commit_all(repo, "lower debt on primary branch")

    git(repo, "merge", "-q", "--no-ff", "--no-commit", "retained-debt-branch")
    write_json(repo / BASELINE_PATH, genesis)
    commit_all(repo, "restore debt in merge commit")

    with pytest.raises(LineagePolicyError, match="increased debt"):
        audit_candidate_lineage(
            repo,
            BASELINE_PATH,
            genesis,
            SCOPE_PATH,
            trusted_genesis_sha256=document_sha256(genesis),
        )


def test_7_divergent_merge_with_unauthorized_scope_removal_remains_rejected(tmp_path: Path) -> None:
    genesis = baseline_fixture()
    repo = initialize_repository(tmp_path, genesis)
    primary = git(repo, "branch", "--show-current").stdout.strip()
    git(repo, "checkout", "-q", "-b", "scope-removal-branch")
    removed_baseline = copy.deepcopy(genesis)
    removed_baseline["selection"]["modules"] = []
    write_json(repo / BASELINE_PATH, removed_baseline)
    commit_all(repo, "remove scope on side branch without authority")

    git(repo, "checkout", "-q", primary)
    (repo / "primary.txt").write_text("advance\n", encoding="utf-8")
    commit_all(repo, "advance primary branch")

    git(repo, "merge", "-q", "--no-ff", "--no-commit", "scope-removal-branch")
    commit_all(repo, "merge unauthorized scope removal")

    with pytest.raises(LineagePolicyError, match="scope transition"):
        audit_candidate_lineage(
            repo,
            BASELINE_PATH,
            removed_baseline,
            SCOPE_PATH,
            trusted_genesis_sha256=document_sha256(genesis),
        )


def test_8_corrupting_or_deleting_sequential_transition_fails_in_synthetic_merge(tmp_path: Path) -> None:
    # 8a: omit record 1 inside the carrier chain, while the redundant merge skip engages
    repo, base_commit, head_commit, genesis, _fix1, final_baseline, registry = _setup_two_transition_history(tmp_path)
    bad_registry = copy.deepcopy(registry)
    bad_registry["records"].pop(0)
    fix1_commit = git(repo, "rev-parse", f"{head_commit}^").stdout.strip()
    git(repo, "checkout", "-q", fix1_commit)
    write_json(repo / SCOPE_PATH, bad_registry)
    git(repo, "add", str(SCOPE_PATH))
    corrupt_fix1_tree = git(repo, "write-tree").stdout.strip()
    corrupt_fix1 = git(
        repo, "commit-tree", corrupt_fix1_tree, "-p", base_commit, "-m", "corrupt FIX1 authority"
    ).stdout.strip()
    head_tree = git(repo, "rev-parse", f"{head_commit}^{{tree}}").stdout.strip()
    corrupt_head = git(
        repo, "commit-tree", head_tree, "-p", corrupt_fix1, "-m", "carry corrupt FIX1 chain"
    ).stdout.strip()
    merge_commit = _create_synthetic_merge(repo, base_commit, corrupt_head)
    git(repo, "checkout", "-q", "-f", merge_commit)

    with pytest.raises(LineagePolicyError, match="scope transition lacks exact authority"):
        audit_candidate_lineage(
            repo,
            BASELINE_PATH,
            final_baseline,
            SCOPE_PATH,
            trusted_genesis_sha256=document_sha256(genesis),
        )

    # 8b: omit record 2 at the carrier head, while the redundant merge skip engages
    bad_registry2 = copy.deepcopy(registry)
    bad_registry2["records"].pop(1)
    git(repo, "checkout", "-q", head_commit)
    write_json(repo / SCOPE_PATH, bad_registry2)
    git(repo, "add", str(SCOPE_PATH))
    corrupt_head_tree = git(repo, "write-tree").stdout.strip()
    corrupt_head2 = git(
        repo, "commit-tree", corrupt_head_tree, "-p", fix1_commit, "-m", "omit FIX2 authority"
    ).stdout.strip()
    merge_commit2 = _create_synthetic_merge(repo, base_commit, corrupt_head2)
    git(repo, "checkout", "-q", merge_commit2)

    with pytest.raises(LineagePolicyError, match="scope transition lacks exact authority"):
        audit_candidate_lineage(
            repo,
            BASELINE_PATH,
            final_baseline,
            SCOPE_PATH,
            trusted_genesis_sha256=document_sha256(genesis),
        )


def test_9_unrelated_or_non_ancestor_parent_is_never_skipped(tmp_path: Path) -> None:
    repo, base_commit, head_commit, genesis, _fix1, final_baseline, _reg = _setup_two_transition_history(tmp_path)
    # Create a divergent branch from base_commit with unchanged policy blobs.
    git(repo, "checkout", "-q", "-b", "divergent-branch", base_commit)
    (repo / "divergent.txt").write_text("divergent\n", encoding="utf-8")
    divergent_commit = commit_all(repo, "divergent branch commit")

    # Synthetic merge with divergent_commit and head_commit (divergent_commit is NOT an ancestor of head_commit)
    merge_commit = _create_synthetic_merge(repo, divergent_commit, head_commit)
    git(repo, "checkout", "-q", merge_commit)

    with pytest.raises(LineagePolicyError, match="scope transition lacks exact authority"):
        audit_candidate_lineage(
            repo,
            BASELINE_PATH,
            final_baseline,
            SCOPE_PATH,
            trusted_genesis_sha256=document_sha256(genesis),
        )


def test_10_candidate_worktree_transition_validation_remains_unchanged(tmp_path: Path) -> None:
    repo, base_commit, head_commit, genesis, _fix1, final_baseline, _reg = _setup_two_transition_history(tmp_path)
    merge_commit = _create_synthetic_merge(repo, base_commit, head_commit)
    git(repo, "checkout", "-q", merge_commit)

    # Clean worktree passes
    audit_candidate_lineage(
        repo,
        BASELINE_PATH,
        final_baseline,
        SCOPE_PATH,
        trusted_genesis_sha256=document_sha256(genesis),
    )

    # Worktree with unauthorized debt increase fails
    dirty_candidate = copy.deepcopy(final_baseline)
    dirty_candidate["ruff"]["findings"] = [{
        "path": MODULE_PATH, "code": "F401", "message": "unused",
        "fingerprint": "f" * 64, "count": 1,
    }]
    with pytest.raises(LineagePolicyError, match="increased debt"):
        audit_candidate_lineage(
            repo,
            BASELINE_PATH,
            dirty_candidate,
            SCOPE_PATH,
            trusted_genesis_sha256=document_sha256(genesis),
        )


def test_11_exact_pr26_fix1_then_fix2_transition_shape_passes_under_synthetic_merge(tmp_path: Path) -> None:
    repo, base_commit, head_commit, genesis, fix1, fix2, registry = _setup_two_transition_history(tmp_path)
    # Verify FIX1 and FIX2 transition properties:
    # FIX1 changed ownership manifest and added module
    assert fix1["ownership"]["sha256"] != genesis["ownership"]["sha256"]
    # FIX2 restored package-root inventory by replacing with package-private helper
    assert len(fix2["selection"]["modules"]) == len(genesis["selection"]["modules"]) + 1
    assert registry["records"][0]["phase"] == "SYNTHETIC-FIX1"
    assert registry["records"][1]["phase"] == "SYNTHETIC-FIX2"

    # Wrap in synthetic merge with ancestor base
    merge_commit = _create_synthetic_merge(repo, base_commit, head_commit)
    git(repo, "checkout", "-q", merge_commit)

    audit = audit_candidate_lineage(
        repo,
        BASELINE_PATH,
        fix2,
        SCOPE_PATH,
        trusted_genesis_sha256=document_sha256(genesis),
    )
    assert audit.committed_transitions == 2
    assert audit.scope_transitions == 2
    assert audit.candidate_transition is False
