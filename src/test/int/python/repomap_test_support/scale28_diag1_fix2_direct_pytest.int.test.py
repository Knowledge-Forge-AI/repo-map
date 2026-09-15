"""SCALE28-FIX12-DIAG1-FIX2: the standalone direct-pytest run lifecycle.

DIAG1-FIX1 gave a direct ``pytest`` invocation a run root but nothing ever
closed it, so every standalone run left a manifest reading ``running`` forever
and an operator could not tell an abandoned run from a live one. These are real
subprocesses, because that is the only way to observe what a separate pytest
process leaves behind after it exits.

Each test uses its own isolated scratch root. None uses the ambient run this
test session is itself executing inside — borrowing that would make the
assertions depend on the outer runner's lifecycle.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from repomap_test_support.test_scratch import (
    ENV_PHASE,
    ENV_PROJECT,
    ENV_RUN_ROOT,
    ENV_SCRATCH_ROOT,
    establish_run,
    finalize_run,
)

REPO_ROOT = Path(__file__).resolve().parents[5]
FIXTURES = REPO_ROOT / "src" / "test" / "fixtures" / "direct_pytest"

PASSING = FIXTURES / "passing.test.py"
FAILING = FIXTURES / "failing.test.py"
COLLECTION_ERROR = FIXTURES / "collection_error.test.py"


def _isolated_scratch(tmp_path: Path) -> Path:
    scratch = tmp_path / "scratch"
    scratch.mkdir(mode=0o700)
    (scratch / "r").mkdir(mode=0o700)
    return scratch


def _run_ids(scratch: Path) -> set[str]:
    return {p.name for p in (scratch / "r").iterdir() if p.is_dir()}


def _run_direct_pytest(fixture: Path, scratch: Path, tmp_path: Path, *,
                       inherited_run_root: Path | None = None,
                       phase: str = "DIRECT-PYTEST-FIXTURE"):
    record = tmp_path / "record.json"
    env = dict(os.environ)
    env.pop(ENV_RUN_ROOT, None)
    env[ENV_SCRATCH_ROOT] = str(scratch)
    env[ENV_PROJECT] = "repo-map_dev"
    env[ENV_PHASE] = phase
    env["DIRECT_PYTEST_RECORD"] = str(record)
    if inherited_run_root is not None:
        env[ENV_RUN_ROOT] = str(inherited_run_root)

    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(fixture), "-q",
         "-p", "no:cacheprovider", "-p", "no:randomly"],
        cwd=str(REPO_ROOT), env=env, capture_output=True, text=True,
        timeout=300,
    )
    recorded = (
        json.loads(record.read_text(encoding="utf-8"))
        if record.is_file() else {}
    )
    return proc, recorded


def _manifest_of(scratch: Path, run_id: str) -> dict:
    return json.loads(
        (scratch / "r" / run_id / "manifest.json").read_text(encoding="utf-8")
    )


# --- D1 ---------------------------------------------------------------------


def test_d1_passing_standalone_run_is_marked_passed(tmp_path):
    scratch = _isolated_scratch(tmp_path)

    proc, recorded = _run_direct_pytest(PASSING, scratch, tmp_path)

    created = sorted(_run_ids(scratch))
    assert len(created) == 1, proc.stdout + proc.stderr
    run_id = created[0]

    manifest = _manifest_of(scratch, run_id)
    assert manifest["state"] == "passed"
    assert manifest["exit_status"] == 0
    assert proc.returncode == 0

    run_root = scratch / "r" / run_id
    assert Path(recorded["tmp_path"]).is_relative_to(run_root)


# --- D2 ---------------------------------------------------------------------


def test_d2_failing_standalone_run_is_marked_failed(tmp_path):
    scratch = _isolated_scratch(tmp_path)

    proc, _ = _run_direct_pytest(FAILING, scratch, tmp_path)

    created = sorted(_run_ids(scratch))
    assert len(created) == 1, proc.stdout + proc.stderr

    manifest = _manifest_of(scratch, created[0])
    assert manifest["state"] == "failed"
    assert manifest["exit_status"] != 0
    assert proc.returncode != 0


# --- D3 ---------------------------------------------------------------------


def test_d3_collection_error_run_is_marked_failed(tmp_path):
    scratch = _isolated_scratch(tmp_path)

    proc, _ = _run_direct_pytest(COLLECTION_ERROR, scratch, tmp_path)

    created = sorted(_run_ids(scratch))
    assert len(created) == 1, proc.stdout + proc.stderr

    manifest = _manifest_of(scratch, created[0])
    assert manifest["state"] == "failed"
    assert manifest["exit_status"] != 0
    assert proc.returncode != 0


# --- D4 ---------------------------------------------------------------------


def test_d4_inherited_run_is_not_terminalized_by_the_borrower(tmp_path):
    """A pytest launched under an owner must not close the owner's run."""
    scratch = _isolated_scratch(tmp_path)
    phase = "DIRECT-PYTEST-OWNER"
    owner = establish_run({ENV_SCRATCH_ROOT: str(scratch), ENV_PHASE: phase})
    assert owner.allocated is True
    before = sorted(_run_ids(scratch))

    proc, _ = _run_direct_pytest(
        PASSING, scratch, tmp_path,
        inherited_run_root=owner.run_root, phase=phase,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert sorted(_run_ids(scratch)) == before

    manifest = json.loads(owner.manifest.read_text(encoding="utf-8"))
    assert manifest["state"] == "running"

    finalize_run(owner, "passed", exit_status=0)
    assert json.loads(owner.manifest.read_text(encoding="utf-8"))["state"] == (
        "passed"
    )


def test_d4_borrower_of_a_foreign_project_run_refuses_to_start(tmp_path):
    """Inheritance is refused outright when the run is not ours to borrow."""
    scratch = _isolated_scratch(tmp_path)
    foreign = scratch / "r" / "foreign-owner-1"
    foreign.mkdir(mode=0o700)
    (foreign / "manifest.json").write_text(
        json.dumps(
            {
                "schema": "repomap-test-scratch-manifest-v1",
                "project": "repo-map_ctrl",
                "phase": "OTHER",
                "run_kind": "test",
                "run_id": "foreign-owner-1",
                "physical_run_root": str(foreign),
                "state": "running",
            },
            indent=2, sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    before = (foreign / "manifest.json").read_bytes()

    proc, _ = _run_direct_pytest(
        PASSING, scratch, tmp_path, inherited_run_root=foreign,
    )

    assert proc.returncode != 0
    assert (foreign / "manifest.json").read_bytes() == before


# --- the dead hook must stay dead -------------------------------------------


def test_common_conftest_defines_no_initial_conftests_hook():
    """The predecessor's basetemp claim was never true; the hook is removed.

    pytest loads a conftest *during* pytest_load_initial_conftests, and that
    hook is not historic, so a conftest's own implementation is registered too
    late ever to be called. Keeping it would document ownership the file does
    not have.
    """
    conftest = (REPO_ROOT / "src" / "test" / "conftest.py").read_text(
        encoding="utf-8"
    )
    assert "pytest_load_initial_conftests" not in conftest
    assert "pytest_sessionfinish" in conftest


def test_standalone_basetemp_is_not_claimed_to_be_the_runner_spelling(tmp_path):
    """Standalone pytest stays in the run root, at pytest's own basename."""
    scratch = _isolated_scratch(tmp_path)

    proc, recorded = _run_direct_pytest(PASSING, scratch, tmp_path)
    created = sorted(_run_ids(scratch))
    assert len(created) == 1, proc.stdout + proc.stderr

    run_root = scratch / "r" / created[0]
    resolved = Path(recorded["tmp_path"])
    assert resolved.is_relative_to(run_root / "tmp")
    assert not resolved.is_relative_to(run_root / "pt")


@pytest.mark.parametrize("fixture", (PASSING, FAILING, COLLECTION_ERROR))
def test_every_standalone_outcome_leaves_a_terminal_manifest(fixture, tmp_path):
    """No ordinary exit path may leave a run reading `running` forever."""
    scratch = _isolated_scratch(tmp_path)

    _run_direct_pytest(fixture, scratch, tmp_path)

    created = sorted(_run_ids(scratch))
    assert len(created) == 1
    assert _manifest_of(scratch, created[0])["state"] in ("passed", "failed")
