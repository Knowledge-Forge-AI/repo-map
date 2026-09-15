"""Explicit synthetic candidate authority and first-parent predecessor controls."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from typing import Any, cast
import pytest
from ci import python_retention_history as history
from ci import python_retention_inventory as inventory
from ci.python_retention_history_git import HistoryContext
from repomap_test_support.retention_pipeline_fixture import retention_candidate, candidate_context


def git(repo: Path, *arguments: str) -> None:
    env = os.environ | {"GIT_AUTHOR_NAME": "Fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
                        "GIT_COMMITTER_NAME": "Fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid"}
    subprocess.run(["git", "-C", str(repo), *arguments], check=True, capture_output=True, env=env)


def _entry(name: str) -> dict[str, Any]:
    return {"path": name, "confidence": 0.9, "maintained_executable": True}


def test_explicit_candidate_mismatch_is_rejected(tmp_path: Path) -> None:
    paths = retention_candidate(tmp_path, ("tools/clean.py",), ("admitted",))
    with pytest.raises(inventory.InventoryValidationError, match="GitHub candidate identity differs from HEAD"):
        inventory.validate_inventory(tmp_path, *paths, context=HistoryContext(github_candidate_sha="0" * 40))
    context = candidate_context(tmp_path)
    result = inventory.validate_inventory(tmp_path, *paths, context=context)
    assert result["history"]["candidate"]["commit"] == context.github_candidate_sha


def test_first_parent_audits_both_parent_and_dirty_worktree_predecessor(tmp_path: Path) -> None:
    repo = tmp_path
    git(repo, "init", "-q")
    inventory = repo / "inventory.json"
    inventory.write_text(json.dumps({"files": [_entry("tools/old.py")]}))
    git(repo, "add", "inventory.json")
    git(repo, "commit", "-qm", "commit 1: initial")
    inventory.write_text(json.dumps({"files": [_entry("tools/old.py"), _entry("tools/intermediate.py")]}))
    git(repo, "add", "inventory.json")
    git(repo, "commit", "-qm", "commit 2: intermediate")

    inventory.write_text(json.dumps({"files": [_entry("tools/old.py")]}))
    data = json.loads(inventory.read_text())
    current = {"tools/old.py"}
    with pytest.raises(
        history.HistoryValidationError,
        match="removed path requires explicit scope history: tools/intermediate.py",
    ):
        history.validate_path_history(repo, inventory, current, data, context=candidate_context(repo))

    data["path_transitions"] = [{
        "from": "tools/intermediate.py", "to": None,
        "rationale": "Retired intermediate tool in worktree",
    }]
    inventory.write_text(json.dumps(data))
    result = history.validate_path_history(repo, inventory, current, data, context=candidate_context(repo))
    assert result == data["path_transitions"]
    basis = cast(dict[str, Any], result.evidence["comparison_basis"])
    assert basis["method"] == "first-parent"
    assert basis["worktree_predecessor"] is not None

