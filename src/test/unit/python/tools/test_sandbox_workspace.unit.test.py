from __future__ import annotations

import test_sandbox as sandbox_owner

import test_sandbox_entrypoint as sandbox_entrypoint



import os

from pathlib import Path



import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]

from src.test.unit.python.tools.sandbox_test_fixtures import _capacity_boundary as _capacity_boundary, completed, finished_follower


def test_entrypoint_environment_points_to_dedicated_sandbox_scratch_root(tmp_path, monkeypatch):
    entrypoint_module = sandbox_entrypoint

    owner_file = tmp_path / "owner"
    token = "a" * 64
    owner_file.write_text(token + "\n", encoding="utf-8")
    monkeypatch.setattr(entrypoint_module, "OWNER_PATH", owner_file)

    env = entrypoint_module._test_environment()
    assert env["REPOMAP_TEST_SCRATCH_ROOT"] == "/sandbox-scratch/test-scratch"
    assert env["REPOMAP_TEST_SCRATCH_ROOT"] != "/sandbox-scratch"
    assert env["_REPOMAP_TEST_SANDBOX_TOKEN"] == token
    assert env["TMPDIR"] == "/sandbox-scratch/tmp"
    assert env["XDG_CACHE_HOME"] == "/sandbox-scratch/cache"
    assert env["PIP_CACHE_DIR"] == "/sandbox-scratch/pip-cache"
    assert env["GOMODCACHE"] == "/sandbox-scratch/go-mod-cache"
    assert env["HOME"] == "/sandbox-scratch/operator-home"
    assert env["PYTHONPATH"] == "/workspace:/workspace/tools"



def test_entrypoint_infrastructure_probe_uses_fixed_no_test_payload():
    entrypoint = sandbox_entrypoint

    argv = [
        entrypoint.INFRASTRUCTURE_PROBE_FLAG,
        *entrypoint.INFRASTRUCTURE_PROBE_PAYLOAD,
    ]
    command = entrypoint._test_command(argv)
    assert command[:2] == ("python3", "-c")
    assert "/workspace/tools/run_tests.py" not in command
    assert "sys.path.insert(0, '/workspace/tools')" in command[2]
    assert "from test_sandbox import active_sandbox" in command[2]
    assert command[-2:] == entrypoint.INFRASTRUCTURE_PROBE_PAYLOAD
    with pytest.raises(RuntimeError, match="payload is invalid"):
        entrypoint._test_command([entrypoint.INFRASTRUCTURE_PROBE_FLAG, "changed"])



def test_dedicated_test_scratch_distinctness():
    module = sandbox_owner
    scratch_root = module.INNER_TEST_SCRATCH_ROOT

    assert str(scratch_root).startswith("/sandbox-scratch/")
    assert scratch_root != Path("/sandbox-scratch")

    other_paths = {
        module.INNER_REPORT_ROOT,
        Path("/sandbox-scratch/workspace-upper"),
        Path("/sandbox-scratch/workspace-work"),
        Path("/sandbox-scratch/project-build"),
        Path("/sandbox-scratch/project-egg-info"),
        Path("/sandbox-scratch/start-tests"),
        Path("/sandbox-scratch/pycache"),
        Path("/sandbox-scratch/go-tmp"),
        Path("/sandbox-scratch/go-cache"),
        Path("/sandbox-scratch/golangci-cache"),
        Path("/sandbox-scratch/operator-home"),
        Path("/sandbox-scratch/bin"),
    }
    assert scratch_root not in other_paths



def test_dedicated_test_scratch_created_before_inner_test_release(tmp_path):
    module = sandbox_owner
    calls = []
    outer_id = "e" * 64
    empty = module.HostSnapshot(frozenset(), frozenset(), frozenset(), frozenset())

    def fake_runner(command, **kwargs):
        calls.append(command)
        if command[:3] == ["docker", "run", "-d"]:
            return completed(command, stdout=outer_id + "\n")
        if command[:2] == ["docker", "wait"]:
            return completed(command, stdout="0\n")
        if command[:2] == ["docker", "logs"]:
            return completed(command)
        if command[:3] == ["docker", "container", "inspect"]:
            return completed(command, status=1)
        return completed(command)

    exit_code = module.run_in_sandbox(
        ["--suite", "int"],
        repo_root=tmp_path / "repo",
        image_id="sha256:" + "f" * 64,
        runner=fake_runner,
        follower_factory=finished_follower,
        snapshotter=lambda _runner: empty,
        boundary_prover=lambda *_args, **_kwargs: None,
    )
    assert exit_code == 0

    mkdir_scratch = [
        "docker",
        "exec",
        outer_id,
        "mkdir",
        "-p",
        "/workspace",
        "/sandbox-scratch/bin",
        "/sandbox-scratch/project-build",
        "/sandbox-scratch/project-egg-info",
        "/sandbox-scratch/workspace-upper",
        "/sandbox-scratch/workspace-work",
        "/sandbox-scratch/tmp",
        "/sandbox-scratch/cache",
        "/sandbox-scratch/pip-cache",
        "/sandbox-scratch/go-tmp",
        "/sandbox-scratch/go-cache",
        "/sandbox-scratch/go-mod-cache",
        "/sandbox-scratch/go-path",
        "/sandbox-scratch/golangci-cache",
        "/sandbox-scratch/operator-home",
        str(module.INNER_REPORT_ROOT.parent),
        str(module.INNER_TEST_SCRATCH_ROOT),
    ]
    release_sentinel = ["docker", "exec", outer_id, "touch", "/sandbox-scratch/start-tests"]

    assert mkdir_scratch in calls
    assert release_sentinel in calls
    assert calls.index(mkdir_scratch) < calls.index(release_sentinel)



def test_scratch_root_ownership_contract_against_sandbox_environment(tmp_path, monkeypatch):
    from repomap_test_support.test_scratch import (
        ENV_SCRATCH_ROOT,
        TestScratchError,
        select_scratch_root,
    )

    dedicated = tmp_path / "test-scratch"
    dedicated.mkdir(mode=0o700)

    # When owned by current UID (sandbox root), select_scratch_root succeeds
    selected = select_scratch_root({ENV_SCRATCH_ROOT: str(dedicated)})
    assert selected == dedicated

    # Simulate host-owned transport root where UID != os.getuid()
    transport_host_root = tmp_path / "host-owned-transport"
    transport_host_root.mkdir(mode=0o700)

    original_lstat = Path.lstat

    def foreign_uid_lstat(self, *args, **kwargs):
        stat_result = original_lstat(self, *args, **kwargs)
        if self == transport_host_root:
            # Simulate host runner UID (e.g. 1001) different from process UID (e.g. 0)
            return os.stat_result(
                (
                    stat_result.st_mode,
                    stat_result.st_ino,
                    stat_result.st_dev,
                    stat_result.st_nlink,
                    os.getuid() + 1001,
                    stat_result.st_gid,
                    stat_result.st_size,
                    stat_result.st_atime,
                    stat_result.st_mtime,
                    stat_result.st_ctime,
                )
            )
        return stat_result

    monkeypatch.setattr(Path, "lstat", foreign_uid_lstat)

    # Host-owned transport root is rejected by safety ownership check
    with pytest.raises(TestScratchError, match="is not a safe, writable directory"):
        select_scratch_root({ENV_SCRATCH_ROOT: str(transport_host_root)})

    # Dedicated child owned by current UID remains accepted
    assert select_scratch_root({ENV_SCRATCH_ROOT: str(dedicated)}) == dedicated

