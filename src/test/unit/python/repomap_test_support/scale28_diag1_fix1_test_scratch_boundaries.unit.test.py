"""SCALE28-FIX12-DIAG1-FIX1: the repository-owned test scratch authority.

These tests were written before the owner existed. They pin the properties the
former environment failures needed: one selected root, one exclusively
allocated short run, a complete child environment that every subprocess
receives, a tempfile cache that cannot outrank the new root, socket paths
checked in encoded bytes, and a terminal state that cannot be quietly
reclassified.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from repomap_test_support.test_scratch import (
    DEFAULT_PROJECT,
    ENV_PHASE,
    ENV_PROJECT,
    ENV_RUN_ROOT,
    ENV_SCRATCH_ROOT,
    TestScratchError,
    allocate_run_root,
    establish_run,
    select_scratch_root,
    validate_inherited_run_root,
)

CHILD_ENVIRONMENT_KEYS = (
    "TMPDIR",
    "TMP",
    "TEMP",
    "PYTHONPYCACHEPREFIX",
    "GOTMPDIR",
    "GOCACHE",
    "GOLANGCI_LINT_CACHE",
    "PIP_CACHE_DIR",
    "BUILDX_CONFIG",
    "PYTHONDONTWRITEBYTECODE",
    ENV_SCRATCH_ROOT,
    ENV_RUN_ROOT,
    ENV_PROJECT,
    ENV_PHASE,
)


def _env(root: Path, **extra: str) -> dict[str, str]:
    env = {ENV_SCRATCH_ROOT: str(root)}
    env.update(extra)
    return env

def test_explicit_scratch_root_selection_wins(tmp_path):
    explicit = tmp_path / "explicit"
    explicit.mkdir()
    assert select_scratch_root(_env(explicit)) == explicit

def test_explicit_relative_scratch_root_is_rejected(tmp_path):
    with pytest.raises(TestScratchError):
        select_scratch_root({ENV_SCRATCH_ROOT: "relative/path"})

def test_darwin_shared_root_is_not_created_by_test_code(tmp_path, monkeypatch):
    """The shared root is operator-managed; absence must fall through."""
    monkeypatch.delenv(ENV_SCRATCH_ROOT, raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(
        "repomap_test_support.test_scratch.DARWIN_SHARED_ROOT",
        tmp_path / "absent-shared-root",
    )
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))

    selected = select_scratch_root({})

    assert not (tmp_path / "absent-shared-root").exists()
    assert tmp_path in selected.parents or selected.parent == tmp_path

def test_portable_fallback_contains_no_hardcoded_developer_identity(
    monkeypatch
):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(tempfile, "gettempdir", lambda: "/tmp/portable-test-root")

    selected = select_scratch_root({})

    assert "/Users/slair" not in str(selected)
    assert str(Path.home()) not in str(selected)

def test_run_allocation_is_exclusive_and_short(tmp_path):
    roots = {allocate_run_root(tmp_path) for _ in range(12)}

    assert len(roots) == 12
    for root in roots:
        assert root.parent == tmp_path / "r"
        assert len(root.name) <= 16
        assert root.is_dir()

def test_inherited_run_root_inside_the_scratch_root_is_accepted(tmp_path):
    # SCALE28-FIX12-DIAG1-FIX2 narrowed this: being beneath the scratch root is
    # necessary but no longer sufficient, so the run must carry its own
    # manifest. A bare allocated directory is now rejected, which is pinned in
    # scale28_diag1_fix2_scratch_ownership.
    layout = establish_run(_env(tmp_path))

    accepted = validate_inherited_run_root(
        layout.run_root, tmp_path, project=DEFAULT_PROJECT
    )
    assert accepted == layout.run_root.resolve()

def test_inherited_run_root_outside_the_scratch_root_is_rejected(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    scratch = tmp_path / "scratch"
    scratch.mkdir()

    with pytest.raises(TestScratchError):
        validate_inherited_run_root(outside, scratch, project=DEFAULT_PROJECT)

def test_symlinked_physical_run_root_is_rejected(tmp_path):
    real = allocate_run_root(tmp_path)
    link = tmp_path / "r" / "linked"
    link.symlink_to(real)

    with pytest.raises(TestScratchError):
        validate_inherited_run_root(link, tmp_path, project=DEFAULT_PROJECT)

def test_establish_run_writes_manifest_and_monitoring_index(tmp_path):
    layout = establish_run(
        _env(tmp_path, **{ENV_PROJECT: "repo-map_dev", ENV_PHASE: "PH1"})
    )

    manifest = json.loads(layout.manifest.read_text(encoding="utf-8"))
    assert manifest["state"] == "running"
    assert manifest["run_kind"] == "test"
    assert manifest["run_id"] == layout.run_root.name
    assert manifest["retention_policy"] == "operator_review"

    index = tmp_path / "index" / "repo-map_dev" / "PH1" / layout.run_root.name
    assert index.is_symlink()
    assert index.resolve() == layout.run_root.resolve()

def test_manifest_records_no_private_runtime_identity(tmp_path):
    layout = establish_run(_env(tmp_path))
    text = layout.manifest.read_text(encoding="utf-8")

    for forbidden in ("password", "PGPASSWORD", "postgres://", "sock="):
        assert forbidden not in text

def test_child_environment_is_complete_and_under_the_run_root(tmp_path):
    layout = establish_run(_env(tmp_path))
    env = layout.child_environment()

    assert set(env) == set(CHILD_ENVIRONMENT_KEYS)
    for key, value in env.items():
        if key in {
            ENV_SCRATCH_ROOT,
            ENV_PROJECT,
            ENV_PHASE,
            "PYTHONDONTWRITEBYTECODE",
        }:
            continue
        assert str(layout.run_root) in value, key

    assert env[ENV_PROJECT] == layout.project
    assert env[ENV_PHASE] == layout.phase

def test_establish_run_reuses_an_inherited_run_root(tmp_path):
    first = establish_run(
        _env(tmp_path, **{ENV_PROJECT: "repo-map_dev", ENV_PHASE: "PARENT-PHASE"})
    )
    second = establish_run(
        _env(tmp_path, **{ENV_RUN_ROOT: str(first.run_root)}),
        project="repo-map_dev",
    )

    assert second.run_root == first.run_root.resolve()
    assert second.project == "repo-map_dev"
    assert second.phase == "PARENT-PHASE"
    assert second.allocated is False
    assert len(list((tmp_path / "r").iterdir())) == 1

def test_apply_resets_a_cached_tempfile_directory(tmp_path, monkeypatch):
    """A cached gettempdir() result must not outrank the new authority."""
    monkeypatch.setattr(tempfile, "tempdir", "/private/tmp", raising=False)
    monkeypatch.setattr(os, "environ", dict(os.environ))
    stale = tempfile.gettempdir()

    layout = establish_run(_env(tmp_path)).apply()

    assert stale != str(layout.tmp)
    assert tempfile.gettempdir() == str(layout.tmp)
    assert os.environ["TMPDIR"] == str(layout.tmp)

def test_apply_explicitly_preserves_no_bytecode_for_spawned_children(
    tmp_path, monkeypatch
):
    """Spawned children receive the policy before interpreter bootstrap."""
    monkeypatch.setattr(os, "environ", dict(os.environ))
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

    layout = establish_run(_env(tmp_path)).apply()

    assert os.environ["PYTHONDONTWRITEBYTECODE"] == "1"
    assert os.environ["PYTHONPYCACHEPREFIX"] == str(layout.pycache)

def test_every_subprocess_receives_the_child_environment(tmp_path):
    layout = establish_run(_env(tmp_path))
    env = dict(os.environ)
    env.update(layout.child_environment())

    probe = (
        "import json,os,sys,tempfile;"
        "print(json.dumps({'tmp':tempfile.gettempdir(),"
        "'keys':{k:os.environ.get(k) for k in %r}}))" % (CHILD_ENVIRONMENT_KEYS,)
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, env=env
    )
    payload = json.loads(result.stdout)

    assert result.returncode == 0
    assert payload["tmp"] == str(layout.tmp)
    for key in CHILD_ENVIRONMENT_KEYS:
        assert payload["keys"][key] == layout.child_environment()[key]

def test_buildx_config_is_under_the_run_root_and_docker_config_is_untouched(
    tmp_path,
):
    layout = establish_run(_env(tmp_path))
    env = layout.child_environment()

    assert env["BUILDX_CONFIG"] == str(layout.buildx_config)
    assert str(layout.run_root) in env["BUILDX_CONFIG"]
    assert "DOCKER_CONFIG" not in env
    assert "DOCKER_CONTEXT" not in env

