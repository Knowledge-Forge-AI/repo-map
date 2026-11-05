"""Candidate binding uses actual Git blobs, not only a matching HEAD string."""

from pathlib import Path
import json
import os
import subprocess
from typing import Any

import pytest

from ci.rust_pilot_qualification import PrerequisiteRefused, _bind_candidate


def _git(root: Path, *args: str) -> str:
    env = os.environ | {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
                        "GIT_AUTHOR_NAME": "Fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
                        "GIT_COMMITTER_NAME": "Fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid"}
    result = subprocess.run(["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null",
                             "-c", "init.templateDir=", *args], cwd=root, env=env,
                            text=True, capture_output=True, check=True, timeout=10)
    return result.stdout.strip()


@pytest.fixture
def candidate(tmp_path: Path) -> tuple[Path, dict[str, Any], str, str]:
    _git(tmp_path, "init", "-b", "main")
    (tmp_path / "source.py").write_text("VALUE = 1\n")
    _git(tmp_path, "add", "source.py")
    _git(tmp_path, "commit", "-m", "Pre-manifest fixture checkpoint")
    checkpoint = {"sha": _git(tmp_path, "rev-parse", "HEAD"),
                  "tree": _git(tmp_path, "rev-parse", "HEAD^{tree}")}
    (tmp_path / "fixtures").mkdir()
    (tmp_path / "fixtures/sample.rs").write_text("fn sample() {}\n")
    (tmp_path / "incumbent.json").write_text("{}\n")
    (tmp_path / "recipe.txt").write_text("pinned recipe fixture\n")
    document = {"source_checkpoint": checkpoint, "closure": {"python_paths": ["source.py"]},
                "fixture": {"root": "fixtures", "files": {"sample.rs": {}}},
                "incumbent": {"report_path": "incumbent.json"},
                "sdk": {"recipe_files": {"recipe.txt": "unused-by-blob-binding"}}}
    (tmp_path / "manifest.json").write_text(json.dumps(document) + "\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "Candidate fixture bytes")
    return tmp_path, document, _git(tmp_path, "rev-parse", "HEAD"), _git(tmp_path, "rev-parse", "HEAD^{tree}")


def test_exact_candidate_regular_blobs_bind(candidate: tuple[Path, dict[str, Any], str, str]) -> None:
    root, manifest, head, tree = candidate
    _bind_candidate(root, manifest, head, tree, root / "manifest.json")


@pytest.mark.parametrize("path", ["source.py", "manifest.json", "fixtures/sample.rs", "incumbent.json", "recipe.txt"])
def test_uncommitted_bound_bytes_refuse(
        candidate: tuple[Path, dict[str, Any], str, str], path: str) -> None:
    root, manifest, head, tree = candidate
    target = root / path
    target.write_bytes(target.read_bytes() + b"\n")
    with pytest.raises(PrerequisiteRefused, match="committed_input_bytes_mismatch"):
        _bind_candidate(root, manifest, head, tree, root / "manifest.json")


def test_untracked_bound_source_refuses(candidate: tuple[Path, dict[str, Any], str, str]) -> None:
    root, manifest, head, tree = candidate
    (root / "extra.py").write_text("VALUE = 2\n")
    manifest["closure"]["python_paths"].append("extra.py")
    with pytest.raises(PrerequisiteRefused, match="committed_input_path_set_mismatch"):
        _bind_candidate(root, manifest, head, tree, root / "manifest.json")


def test_sealed_candidate_tree_mismatch_refuses(candidate: tuple[Path, dict[str, Any], str, str]) -> None:
    root, manifest, head, _tree = candidate
    with pytest.raises(PrerequisiteRefused, match="candidate_binding_mismatch"):
        _bind_candidate(root, manifest, head, "0" * 40, root / "manifest.json")
