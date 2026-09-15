"""SCALE28-FIX12-DIAG1-FIX2: exact ownership of an inherited test scratch run.

DIAG1-FIX1 accepted any safe directory beneath the shared scratch root as an
inherited run. That is too broad: the root is shared with other projects and
other agents, so "safe and beneath the root" describes their runs too. These
tests were written red, and pin the narrower authority — an inherited run must
carry this project's own manifest, naming this exact run, still running — plus
a monitoring index that fails closed instead of silently reusing a colliding
path, and a finalizer that revalidates before it writes.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from repomap_test_support.test_scratch import (
    DEFAULT_PROJECT,
    ENV_PHASE,
    ENV_PROJECT,
    ENV_SCRATCH_ROOT,
    MANIFEST_SCHEMA,
    TestScratchError,
    _monitoring_index,
    establish_run,
    finalize_run,
    validate_inherited_run_root,
)


def _env(root: Path, **extra: str) -> dict[str, str]:
    env = {ENV_SCRATCH_ROOT: str(root)}
    env.update(extra)
    return env


def _valid_run(scratch: Path, **manifest_updates):
    """One genuinely allocated run, optionally corrupted for a negative case."""
    layout = establish_run(_env(scratch))
    if manifest_updates:
        manifest = json.loads(layout.manifest.read_text(encoding="utf-8"))
        manifest.update(manifest_updates)
        layout.manifest.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return layout


def _validate(run_root: Path, scratch: Path, **kwargs):
    kwargs.setdefault("project", DEFAULT_PROJECT)
    return validate_inherited_run_root(run_root, scratch, **kwargs)


# --- inherited-run authority: the accepting case ---------------------------

def _index_dir(scratch: Path) -> Path:
    index = scratch / "index" / DEFAULT_PROJECT / "PH"
    index.mkdir(mode=0o700, parents=True, exist_ok=True)
    return index

def _fingerprint(root: Path) -> dict:
    out = {}
    for path in sorted(root.rglob("*")):
        stat = path.lstat()
        entry = {"mode": oct(stat.st_mode), "mtime_ns": stat.st_mtime_ns}
        if path.is_symlink():
            entry["target"] = os.readlink(path)
        elif path.is_file():
            entry["bytes"] = path.read_bytes()
        out[str(path.relative_to(root))] = entry
    return out

FOREIGN_RUN_IDS = (
    "apg-synthetic-1",
    "ctrl-synthetic-1",
    "wrong-id-synthetic-1",
    "terminal-synthetic-1",
)


def _foreign_tree(scratch: Path) -> Path:
    """Synthetic runs owned by other projects. No real run is ever read."""
    runs = scratch / "r"
    runs.mkdir(mode=0o700, parents=True, exist_ok=True)

    shapes = {
        "apg-synthetic-1": {
            "schema": "apg-run-manifest-v2",
            "project": "agentic-praxis-grimoire",
            "retention_state": "active",
        },
        "ctrl-synthetic-1": {
            "schema": MANIFEST_SCHEMA,
            "project": "repo-map_ctrl",
            "run_kind": "test",
            "run_id": "ctrl-synthetic-1",
            "state": "running",
        },
        "wrong-id-synthetic-1": {
            "schema": MANIFEST_SCHEMA,
            "project": DEFAULT_PROJECT,
            "run_kind": "test",
            "run_id": "not-the-directory-name",
            "state": "running",
        },
        "terminal-synthetic-1": {
            "schema": MANIFEST_SCHEMA,
            "project": DEFAULT_PROJECT,
            "run_kind": "test",
            "run_id": "terminal-synthetic-1",
            "state": "passed",
            "exit_status": 0,
        },
    }
    for run_id, manifest in shapes.items():
        root = runs / run_id
        root.mkdir(mode=0o700, exist_ok=True)
        (root / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    index = scratch / "index" / "agentic-praxis-grimoire" / "OTHER"
    index.mkdir(mode=0o700, parents=True, exist_ok=True)
    link = index / "apg-synthetic-1"
    if not link.is_symlink():
        link.symlink_to(runs / "apg-synthetic-1")
    return runs

def test_monitoring_index_creates_a_relative_symlink_to_the_exact_run(tmp_path):
    layout = establish_run(_env(tmp_path, **{ENV_PHASE: "PH"}))
    link = _monitoring_index(tmp_path, DEFAULT_PROJECT, "PH", layout.run_root)

    assert link.is_symlink()
    assert not os.path.isabs(os.readlink(link))
    assert link.resolve() == layout.run_root.resolve()

def test_monitoring_index_reuse_is_idempotent_for_the_same_run(tmp_path):
    layout = establish_run(_env(tmp_path, **{ENV_PHASE: "PH"}))
    first = _monitoring_index(tmp_path, DEFAULT_PROJECT, "PH", layout.run_root)
    second = _monitoring_index(tmp_path, DEFAULT_PROJECT, "PH", layout.run_root)

    assert first == second
    assert second.resolve() == layout.run_root.resolve()

def test_monitoring_index_regular_file_collision_raises(tmp_path):
    layout = establish_run(_env(tmp_path))
    entry = _index_dir(tmp_path) / layout.run_root.name
    entry.write_text("not a symlink\n", encoding="utf-8")

    with pytest.raises(TestScratchError):
        _monitoring_index(tmp_path, DEFAULT_PROJECT, "PH", layout.run_root)

    assert entry.read_text(encoding="utf-8") == "not a symlink\n"

def test_monitoring_index_real_directory_collision_raises(tmp_path):
    layout = establish_run(_env(tmp_path))
    entry = _index_dir(tmp_path) / layout.run_root.name
    entry.mkdir()

    with pytest.raises(TestScratchError):
        _monitoring_index(tmp_path, DEFAULT_PROJECT, "PH", layout.run_root)

    assert entry.is_dir() and not entry.is_symlink()

def test_monitoring_index_dangling_symlink_collision_raises(tmp_path):
    layout = establish_run(_env(tmp_path))
    entry = _index_dir(tmp_path) / layout.run_root.name
    entry.symlink_to(tmp_path / "r" / "does-not-exist")

    with pytest.raises(TestScratchError):
        _monitoring_index(tmp_path, DEFAULT_PROJECT, "PH", layout.run_root)

    assert entry.is_symlink()

def test_monitoring_index_wrong_target_symlink_collision_raises(tmp_path):
    mine = establish_run(_env(tmp_path))
    other = establish_run(_env(tmp_path))
    entry = _index_dir(tmp_path) / mine.run_root.name
    entry.symlink_to(other.run_root)

    with pytest.raises(TestScratchError):
        _monitoring_index(tmp_path, DEFAULT_PROJECT, "PH", mine.run_root)

    assert entry.resolve() == other.run_root.resolve()

def test_monitoring_index_symlink_outside_the_scratch_root_raises(tmp_path):
    layout = establish_run(_env(tmp_path))
    outside = tmp_path.parent / "outside-target"
    outside.mkdir(exist_ok=True)
    entry = _index_dir(tmp_path) / layout.run_root.name
    entry.symlink_to(outside)

    with pytest.raises(TestScratchError):
        _monitoring_index(tmp_path, DEFAULT_PROJECT, "PH", layout.run_root)

    assert entry.resolve() == outside.resolve()

def test_finalize_rejects_a_manifest_that_is_no_longer_this_run(tmp_path):
    layout = establish_run(_env(tmp_path))
    manifest = json.loads(layout.manifest.read_text(encoding="utf-8"))
    manifest["run_id"] = "some-other-run"
    layout.manifest.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    with pytest.raises(TestScratchError):
        finalize_run(layout, "passed", exit_status=0)

def test_finalize_rejects_a_manifest_belonging_to_another_project(tmp_path):
    layout = establish_run(_env(tmp_path, **{ENV_PROJECT: DEFAULT_PROJECT}))
    manifest = json.loads(layout.manifest.read_text(encoding="utf-8"))
    manifest["project"] = "repo-map_ctrl"
    layout.manifest.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    with pytest.raises(TestScratchError):
        finalize_run(layout, "passed", exit_status=0)

def test_finalize_rejects_a_foreign_schema_before_writing(tmp_path):
    layout = establish_run(_env(tmp_path))
    layout.manifest.write_text(
        json.dumps({"schema": "apg-run-manifest-v2", "retention_state": "active"})
        + "\n",
        encoding="utf-8",
    )
    before = layout.manifest.read_bytes()

    with pytest.raises(TestScratchError):
        finalize_run(layout, "passed", exit_status=0)

    assert layout.manifest.read_bytes() == before

def test_finalize_writes_only_this_run_and_leaves_siblings_alone(tmp_path):
    mine = establish_run(_env(tmp_path))
    sibling = establish_run(_env(tmp_path))
    before = sibling.manifest.read_bytes()

    finalize_run(mine, "passed", exit_status=0)

    assert json.loads(mine.manifest.read_text(encoding="utf-8"))["state"] == "passed"
    assert sibling.manifest.read_bytes() == before

def test_foreign_runs_are_untouched_by_establish_validate_and_finalize(tmp_path):
    """The predecessor damaged three real foreign manifests. This is the pin."""
    _foreign_tree(tmp_path)
    before = _fingerprint(tmp_path / "r")

    for run_id in FOREIGN_RUN_IDS:
        with pytest.raises(TestScratchError):
            _validate(tmp_path / "r" / run_id, tmp_path)

    mine = establish_run(_env(tmp_path))
    finalize_run(mine, "failed", exit_status=1)

    after = _fingerprint(tmp_path / "r")
    for key, value in before.items():
        assert after[key] == value, key

def test_foreign_monitoring_index_entries_are_untouched(tmp_path):
    _foreign_tree(tmp_path)
    index_root = tmp_path / "index"
    before = _fingerprint(index_root)

    layout = establish_run(_env(tmp_path, **{ENV_PHASE: "PH"}))
    _monitoring_index(tmp_path, DEFAULT_PROJECT, "PH", layout.run_root)

    after = _fingerprint(index_root)
    for key, value in before.items():
        assert after[key] == value, key

