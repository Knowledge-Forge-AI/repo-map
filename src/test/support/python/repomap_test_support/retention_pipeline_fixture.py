"""Synthetic Git candidates for real retention history and enforcement tests."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

from ci.python_retention_authorities import CHECKERS
from ci.python_retention_cohorts import COHORT_SCHEMA
from ci.python_retention_history_git import HistoryContext
from ci import python_retention_inventory as inventory
from ci.retained_python_ratchets import BASELINE_SCHEMA, EXPECTED_TOOLS, RETAINED_CLASSES, RETAINED_TIERS
from typing import Any


def candidate_context(root: Path) -> HistoryContext:
    head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    return HistoryContext(github_candidate_sha=head)


def pipeline_cohort(path: str, admission: str = "admitted") -> dict[str, Any]:
    return dict(id=path.replace("/", "."), root="tools", admission=admission,
                members=[path], rationale="Synthetic pipeline responsibility owner",
                governing_profile="clean_tooling")


def retention_candidate(
    tmp_path: Path, paths: tuple[str, ...], admissions: tuple[str, ...],
    *, first_parent: bool = False,
) -> tuple[Path, Path]:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    inventory_path = tmp_path / "inventory.json"
    inventory_path.write_text(json.dumps({"schema": inventory.SCHEMA_VERSION, "files": []}))
    subprocess.run(["git", "-C", str(tmp_path), "add", "inventory.json"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=Fixture",
                    "-c", "user.email=fixture@example.invalid", "commit", "-qm",
                    "Inventory genesis"], check=True)
    if first_parent:
        subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=Fixture",
                        "-c", "user.email=fixture@example.invalid", "commit", "--allow-empty", "-qm",
                        "Candidate commit"], check=True)

    checker_root = tmp_path / "tools/ci"
    checker_root.mkdir(parents=True)
    (tmp_path / "src/test/fixtures").mkdir(parents=True)
    (tmp_path / ".gitignore").write_text("/tools/ci/*.py\n")
    for name in CHECKERS:
        (checker_root / name).write_text('"""Synthetic checker authority."""\n')
    (tmp_path / "pyproject.toml").write_text("[tool]\n")
    (checker_root / "retained_python_scope_transitions.json").write_text(
        json.dumps({"records": []})
    )
    (checker_root / "python_retention_transitions.json").write_text(json.dumps({
        "schema": "repomap-python-retention-transitions-v1", "records": [],
    }))
    (checker_root / "python_fixture_authority.json").write_text(json.dumps({
        "schema": "repomap-python-fixture-authority-v1", "version": 1,
        "fixture_root": "src/test/fixtures", "entries": [],
    }))

    entries = []
    for path_name in paths:
        path = tmp_path / path_name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("value: int = 1\n", encoding="utf-8")
        entries.append({
            "path": path_name, "root": "tools", "confidence": 0.9,
            "maintained_executable": True, "rationale": "Synthetic maintained implementation",
            "governing_profile": inventory.PROFILES["tools"], "status": "active_tool",
        })

    ownership = {
        "schema": "repomap-python-type-ownership-v1",
        "resolution": "longest-component-prefix-wins", "entries": [{
            "module_prefix": "repomap_kg", "match": "exact",
            "ownership_class": "python_retained", "architecture_box": "go_control_and_api",
            "enforcement_tier": "T1-future", "justification": "Synthetic maintained product owner",
            "disposition": "retained_python_ratcheted",
        }],
    }
    ownership_path = checker_root / "python_type_ownership.json"
    ownership_path.write_text(json.dumps(ownership))
    ratchet_path = tmp_path / "ratchet.json"
    ratchet_path.write_text(json.dumps({
        "schema": BASELINE_SCHEMA,
        "ownership": {"manifest_path": "tools/ci/python_type_ownership.json",
                       "sha256": hashlib.sha256(ownership_path.read_bytes()).hexdigest()},
        "tools": dict(EXPECTED_TOOLS, ruff_rules=["F"], ruff_target_version="py312"),
        "selection": {"ownership_classes": list(RETAINED_CLASSES),
                       "tiers": list(RETAINED_TIERS), "modules": []},
        "ruff": {"findings": []}, "mypy": {"findings": []},
        "migration_direction_imports": {"edges": []},
        "file_length": {"warning_limit": 400, "failure_limit": 1000, "ceilings": []},
    }))
    inventory_path.write_text(json.dumps({
        "schema": inventory.SCHEMA_VERSION, "files": entries,
        "cohort_schema": COHORT_SCHEMA,
        "cohorts": [pipeline_cohort(path, admission)
                    for path, admission in zip(paths, admissions, strict=True)],
    }))
    return inventory_path, ratchet_path


