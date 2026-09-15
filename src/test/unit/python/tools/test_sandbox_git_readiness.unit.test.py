from __future__ import annotations

import test_sandbox as sandbox_owner




import os

from pathlib import Path

import subprocess


import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]

from src.test.unit.python.tools.sandbox_test_fixtures import _capacity_boundary as _capacity_boundary, completed, finished_follower


def test_inner_boundary_probe_rejects_wildcard_safe_directory(tmp_path):
    module = sandbox_owner

    def fake_runner(command, **kwargs):
        if "go" in command and "version" in command:
            return completed(command, stdout="go version go1.25.10 linux/arm64\n")
        if "golangci-lint" in command:
            return completed(command, stdout="golangci-lint has version 2.6.2\n")
        if "git" in command and "config" in command:
            return completed(command, stdout="*\n")
        return completed(command)

    with pytest.raises(RuntimeError, match="git safe.directory configuration is invalid"):
        module.prove_inner_boundary(
            fake_runner,
            container_id="5" * 64,
            token="6" * 16,
        )



def test_inner_boundary_probe_rejects_mismatched_safe_directory(tmp_path):
    module = sandbox_owner

    def fake_runner(command, **kwargs):
        if "go" in command and "version" in command:
            return completed(command, stdout="go version go1.25.10 linux/arm64\n")
        if "golangci-lint" in command:
            return completed(command, stdout="golangci-lint has version 2.6.2\n")
        if "git" in command and "config" in command:
            return completed(command, stdout="/unexpected/workspace\n")
        return completed(command)

    with pytest.raises(RuntimeError, match="git safe.directory configuration is invalid"):
        module.prove_inner_boundary(
            fake_runner,
            container_id="5" * 64,
            token="6" * 16,
        )



def test_inner_boundary_probe_rejects_mismatched_toplevel_repo(tmp_path):
    module = sandbox_owner

    def fake_runner(command, **kwargs):
        if "go" in command and "version" in command:
            return completed(command, stdout="go version go1.25.10 linux/arm64\n")
        if "golangci-lint" in command:
            return completed(command, stdout="golangci-lint has version 2.6.2\n")
        if "git" in command and "config" in command:
            return completed(command, stdout="/workspace\n")
        if "git" in command and "rev-parse" in command:
            return completed(command, stdout="/unexpected/workspace\n")
        return completed(command)

    with pytest.raises(RuntimeError, match="git repository root probe failed"):
        module.prove_inner_boundary(
            fake_runner,
            container_id="5" * 64,
            token="6" * 16,
        )



def test_inner_boundary_probe_rejects_failed_git_status(tmp_path):
    module = sandbox_owner

    def fake_runner(command, **kwargs):
        if "go" in command and "version" in command:
            return completed(command, stdout="go version go1.25.10 linux/arm64\n")
        if "golangci-lint" in command:
            return completed(command, stdout="golangci-lint has version 2.6.2\n")
        if "git" in command and "config" in command:
            return completed(command, stdout="/workspace\n")
        if "git" in command and "rev-parse" in command:
            return completed(command, stdout="/workspace\n")
        if "git" in command and "status" in command:
            return completed(command, status=128)
        return completed(command)

    with pytest.raises(RuntimeError, match="boundary probe failed"):
        module.prove_inner_boundary(
            fake_runner,
            container_id="5" * 64,
            token="6" * 16,
        )



def test_workspace_git_readiness_precedes_inner_test_release(tmp_path):
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
        if "inspect" in command:
            return completed(command, status=1)
        if "git" in command and "config" in command:
            return completed(command, stdout="/workspace\n")
        if "git" in command and "rev-parse" in command:
            return completed(command, stdout="/workspace\n")
        if "git" in command and "status" in command:
            return completed(command, stdout="")
        if "cat" in command and "/sandbox-scratch/bind-proof" in command:
            return completed(command, stdout="ok\n")
        if "go" in command and "version" in command:
            return completed(command, stdout="go version go1.25.10 linux/arm64\n")
        if "golangci-lint" in command:
            return completed(command, stdout="golangci-lint has version 2.6.2\n")
        if "docker" in command and "run" in command:
            return completed(command, stdout=("4" * 64) + "\n")
        if "volume" in command and "create" in command:
            return completed(command, stdout=f"{command[-1]}\n")
        return completed(command)

    exit_code = module.run_in_sandbox(
        ["--suite", "int"],
        repo_root=tmp_path / "repo",
        image_id="sha256:" + "f" * 64,
        runner=fake_runner,
        follower_factory=finished_follower,
        snapshotter=lambda _runner: empty,
    )
    assert exit_code == 0

    git_config_cmd = [
        "docker",
        "exec",
        outer_id,
        "git",
        "config",
        "--file",
        "/sandbox-scratch/operator-home/.gitconfig",
        "--add",
        "safe.directory",
        "/workspace",
    ]
    release_sentinel = ["docker", "exec", outer_id, "touch", "/sandbox-scratch/start-tests"]

    assert git_config_cmd in calls
    assert release_sentinel in calls
    assert calls.index(git_config_cmd) < calls.index(release_sentinel)



def test_real_git_safe_directory_exact_authorization_semantics(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo_dir, check=True)

    operator_home = tmp_path / "operator-home"
    operator_home.mkdir()
    gitconfig_file = operator_home / ".gitconfig"

    # Configure exact safe.directory
    subprocess.run(
        [
            "git",
            "config",
            "--file",
            str(gitconfig_file),
            "--add",
            "safe.directory",
            str(repo_dir),
        ],
        check=True,
    )

    # Prove config is exact and not wildcard
    configured = subprocess.run(
        [
            "git",
            "config",
            "--file",
            str(gitconfig_file),
            "--get-all",
            "safe.directory",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert configured.stdout.strip() == str(repo_dir)
    assert "*" not in configured.stdout.splitlines()

    # Prove rev-parse and status succeed under this config
    env = dict(os.environ, HOME=str(operator_home))
    toplevel = subprocess.run(
        ["git", "-C", str(repo_dir), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    assert Path(toplevel.stdout.strip()).resolve() == repo_dir.resolve()

    status = subprocess.run(
        ["git", "-C", str(repo_dir), "status", "--porcelain=v1", "--untracked-files=no"],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    assert status.returncode == 0

