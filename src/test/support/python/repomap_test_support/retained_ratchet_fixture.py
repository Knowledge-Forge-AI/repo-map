"""Public-safe real-Git fixtures for retained-Python lineage tests."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
from typing import Mapping

from ci.retained_python_ratchets import (
    BaselineDocument,
    SelectionModuleRecord,
    SnapshotDocument,
    baseline_document,
    render_document,
)


BASELINE_PATH = Path("tools/ci/retained_python_ratchets.json")
SCOPE_PATH = Path("tools/ci/retained_python_scope_transitions.json")
STATUS_PATH = Path("docs/status/2099/01/01/99999-synthetic-scope-exit.md")
MODULE_PATH = "src/main/python/repomap_kg/future.py"


def snapshot_fixture() -> SnapshotDocument:
    return {
        "ownership": {
            "manifest_path": "tools/ci/python_type_ownership.json",
            "sha256": "a" * 64,
        },
        "tools": {
            "mypy": "2.1.0",
            "ruff": "0.16.2",
            "ruff_rules": ["F"],
            "ruff_target_version": "py312",
        },
        "selection": {
            "ownership_classes": ["cross_language_contract", "python_retained"],
            "tiers": ["T0", "T1-future", "T1-seed"],
            "modules": [selection_item()],
        },
        "ruff": {"findings": []},
        "mypy": {"findings": []},
        "migration_direction_imports": {"edges": []},
        "file_length": {
            "warning_limit": 400,
            "failure_limit": 1000,
            "ceilings": [],
            "hard_failures": [],
        },
    }


def selection_item(
    module: str = "repomap_kg.future",
    path: str = MODULE_PATH,
    ownership_class: str = "python_retained",
    tier: str = "T1-future",
) -> SelectionModuleRecord:
    return {
        "module": module,
        "path": path,
        "ownership_class": ownership_class,
        "tier": tier,
    }


def baseline_fixture() -> BaselineDocument:
    return baseline_document(snapshot_fixture())


def empty_scope_registry() -> dict[str, object]:
    return {
        "schema": "repomap-retained-python-scope-transitions-v1",
        "records": [],
    }


def write_json(path: Path, document: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_document(document), encoding="utf-8")


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ | {
        "GIT_AUTHOR_NAME": "Synthetic Fixture",
        "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_NAME": "Synthetic Fixture",
        "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
    }
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )


def commit_all(repo: Path, message: str) -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def initialize_repository(tmp_path: Path, baseline: Mapping[str, object]) -> Path:
    repo = tmp_path / "repository"
    repo.mkdir()
    git(repo, "init", "-q")
    write_json(repo / BASELINE_PATH, baseline)
    source = repo / MODULE_PATH
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("value = 1\n", encoding="utf-8")
    commit_all(repo, "REPOMAP-PYRATCHET1: ratchet retained Python quality")
    return repo


def write_status(repo: Path, phase: str = "SYNTHETIC-SCOPE1") -> None:
    path = repo / STATUS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# 99999 {phase} Synthetic Scope Exit\n\n## Status\n\n- **Phase**: {phase}\n",
        encoding="utf-8",
    )
