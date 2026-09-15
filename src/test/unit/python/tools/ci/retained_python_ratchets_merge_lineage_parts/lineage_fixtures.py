from __future__ import annotations

import copy
from pathlib import Path

from ci.retained_python_ratchet_lineage import (
    document_sha256 as document_sha256,
    selection_digest,
)
from ci.retained_python_records import (
    BaselineDocument,
    ScopeChange,
    ScopeRegistry,
    ScopeTransitionRecord,
)
from repomap_test_support.retained_ratchet_fixture import (
    BASELINE_PATH as BASELINE_PATH,
    MODULE_PATH as MODULE_PATH,
    SCOPE_PATH as SCOPE_PATH,
    baseline_fixture,
    commit_all,
    empty_scope_registry as empty_scope_registry,
    git,
    initialize_repository,
    selection_item,
    write_json,
)


def _write_status_file(repo: Path, rel_path: str, phase: str) -> None:
    path = repo / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# 99999 {phase} Synthetic Exit\n\n## Status\n\n- **Phase**: {phase}\n",
        encoding="utf-8",
    )


def _scope_record(
    before: BaselineDocument,
    after: BaselineDocument,
    changes: list[ScopeChange],
    *,
    phase: str,
    status_path: str,
) -> ScopeTransitionRecord:
    return {
        "old_ownership_manifest_sha256": before["ownership"]["sha256"],
        "new_ownership_manifest_sha256": after["ownership"]["sha256"],
        "old_selected_set_sha256": selection_digest(before),
        "new_selected_set_sha256": selection_digest(after),
        "changes": changes,
        "phase": phase,
        "status_path": status_path,
        "reason": f"Synthetic scope transition for {phase}.",
    }


def _setup_two_transition_history(
    tmp_path: Path,
) -> tuple[Path, str, str, BaselineDocument, BaselineDocument, BaselineDocument, ScopeRegistry]:
    """Build a repo with staging base, FIX1 transition, and FIX2 transition."""
    genesis = baseline_fixture()
    repo = initialize_repository(tmp_path, genesis)
    base_commit = git(repo, "rev-parse", "HEAD").stdout.strip()

    # FIX1: change ownership manifest and add helper module
    status1_path = "docs/status/2099/01/01/99991-synthetic-fix1-exit.md"
    _write_status_file(repo, status1_path, "SYNTHETIC-FIX1")
    fix1_baseline = copy.deepcopy(genesis)
    fix1_baseline["ownership"]["sha256"] = "b" * 64
    new_mod = selection_item(
        "repomap_kg.added_helper",
        "src/main/python/repomap_kg/added_helper.py",
    )
    fix1_baseline["selection"]["modules"].append(new_mod)
    fix1_baseline["selection"]["modules"].sort(key=lambda m: m["module"])
    helper_path = repo / new_mod["path"]
    helper_path.parent.mkdir(parents=True, exist_ok=True)
    helper_path.write_text("helper = 1\n", encoding="utf-8")

    registry: ScopeRegistry = {
        "schema": "repomap-retained-python-scope-transitions-v1",
        "records": [],
    }
    rec1 = _scope_record(
        genesis,
        fix1_baseline,
        [{"old": None, "new": new_mod}],
        phase="SYNTHETIC-FIX1",
        status_path=status1_path,
    )
    registry["records"].append(rec1)
    write_json(repo / BASELINE_PATH, fix1_baseline)
    write_json(repo / SCOPE_PATH, registry)
    commit_all(repo, "PR26-FAST-FIX1: add helper to retained scope")

    # FIX2: rename/replace helper with package-private helper
    status2_path = "docs/status/2099/01/01/99992-synthetic-fix2-exit.md"
    _write_status_file(repo, status2_path, "SYNTHETIC-FIX2")
    fix2_baseline = copy.deepcopy(fix1_baseline)
    fix2_baseline["selection"]["modules"] = [
        m for m in fix2_baseline["selection"]["modules"]
        if m["module"] != "repomap_kg.added_helper"
    ]
    private_mod = selection_item(
        "repomap_kg._added_helper",
        "src/main/python/repomap_kg/_added_helper.py",
    )
    fix2_baseline["selection"]["modules"].append(private_mod)
    fix2_baseline["selection"]["modules"].sort(key=lambda m: m["module"])
    private_path = repo / private_mod["path"]
    private_path.parent.mkdir(parents=True, exist_ok=True)
    private_path.write_text("private_helper = 1\n", encoding="utf-8")

    rec2 = _scope_record(
        fix1_baseline,
        fix2_baseline,
        [
            {"old": None, "new": private_mod},
            {"old": new_mod, "new": None},
        ],
        phase="SYNTHETIC-FIX2",
        status_path=status2_path,
    )
    registry["records"].append(rec2)
    write_json(repo / BASELINE_PATH, fix2_baseline)
    write_json(repo / SCOPE_PATH, registry)
    head_commit = commit_all(repo, "PR26-FAST-FIX2: restore package-private helper")

    return repo, base_commit, head_commit, genesis, fix1_baseline, fix2_baseline, registry


def _create_synthetic_merge(
    repo: Path,
    parent1: str,
    parent2: str,
    *,
    tree: str | None = None,
    message: str = "Synthetic PR merge",
) -> str:
    tree_sha = tree or git(repo, "rev-parse", f"{parent2}^{{tree}}").stdout.strip()
    completed = git(repo, "commit-tree", tree_sha, "-p", parent1, "-p", parent2, "-m", message)
    return completed.stdout.strip()
