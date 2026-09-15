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
from pathlib import Path

import pytest

from repomap_test_support.test_scratch import (
    DEFAULT_PROJECT,
    ENV_RUN_ROOT,
    ENV_SCRATCH_ROOT,
    TestScratchError,
    establish_run,
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

def test_inherited_run_with_its_own_valid_manifest_is_accepted(tmp_path):
    layout = _valid_run(tmp_path)

    assert _validate(layout.run_root, tmp_path) == layout.run_root.resolve()

def test_inherited_directory_without_a_manifest_is_rejected(tmp_path):
    """A bare directory beneath the shared root is not this project's run."""
    layout = _valid_run(tmp_path)
    layout.manifest.unlink()

    with pytest.raises(TestScratchError):
        _validate(layout.run_root, tmp_path)

def test_inherited_run_with_a_foreign_schema_is_rejected(tmp_path):
    layout = _valid_run(tmp_path, schema="apg-run-manifest-v2")

    with pytest.raises(TestScratchError):
        _validate(layout.run_root, tmp_path)

def test_inherited_run_belonging_to_another_project_is_rejected(tmp_path):
    layout = _valid_run(tmp_path, project="repo-map_ctrl")

    with pytest.raises(TestScratchError):
        _validate(layout.run_root, tmp_path)

def test_inherited_run_of_another_phase_is_rejected_when_phase_is_supplied(
    tmp_path,
):
    layout = _valid_run(tmp_path, phase="SOME-OTHER-PHASE")

    with pytest.raises(TestScratchError):
        _validate(layout.run_root, tmp_path, phase="EXPECTED-PHASE")

def test_inherited_run_phase_is_not_checked_when_none_is_supplied(tmp_path):
    layout = _valid_run(tmp_path, phase="SOME-OTHER-PHASE")

    assert _validate(layout.run_root, tmp_path) == layout.run_root.resolve()

def test_inherited_run_with_a_mismatched_run_id_is_rejected(tmp_path):
    layout = _valid_run(tmp_path, run_id="some-other-run")

    with pytest.raises(TestScratchError):
        _validate(layout.run_root, tmp_path)

def test_inherited_run_with_a_mismatched_physical_root_is_rejected(tmp_path):
    other = tmp_path / "r" / "elsewhere"
    other.mkdir(parents=True)
    layout = _valid_run(tmp_path, physical_run_root=str(other))

    with pytest.raises(TestScratchError):
        _validate(layout.run_root, tmp_path)

def test_inherited_run_that_is_already_terminal_is_rejected(tmp_path):
    layout = _valid_run(tmp_path, state="passed", exit_status=0)

    with pytest.raises(TestScratchError):
        _validate(layout.run_root, tmp_path)

def test_inherited_run_that_is_not_a_test_run_is_rejected(tmp_path):
    layout = _valid_run(tmp_path, run_kind="phase")

    with pytest.raises(TestScratchError):
        _validate(layout.run_root, tmp_path)

def test_inherited_run_with_malformed_manifest_json_is_rejected(tmp_path):
    layout = _valid_run(tmp_path)
    layout.manifest.write_text("{ not json", encoding="utf-8")

    with pytest.raises(TestScratchError):
        _validate(layout.run_root, tmp_path)

def test_inherited_run_with_a_symlinked_manifest_is_rejected(tmp_path):
    layout = _valid_run(tmp_path)
    real = tmp_path / "elsewhere.json"
    real.write_text(layout.manifest.read_text(encoding="utf-8"), encoding="utf-8")
    layout.manifest.unlink()
    layout.manifest.symlink_to(real)

    with pytest.raises(TestScratchError):
        _validate(layout.run_root, tmp_path)

def test_establish_run_rejects_an_inherited_run_it_does_not_own(tmp_path):
    """The rejection reaches the real entry point, not only the validator."""
    layout = _valid_run(tmp_path, project="repo-map_ctrl")

    with pytest.raises(TestScratchError):
        establish_run(_env(tmp_path, **{ENV_RUN_ROOT: str(layout.run_root)}))

