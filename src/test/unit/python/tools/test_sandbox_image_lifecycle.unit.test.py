from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest
import test_sandbox as sandbox_owner

from src.test.unit.python.tools.sandbox_test_fixtures import _capacity_boundary as _capacity_boundary, completed

REPO_ROOT = Path(__file__).resolve().parents[5]


def test_managed_image_build_context_contains_only_sandbox_recipe(tmp_path):
    module = sandbox_owner
    context = tmp_path / "sandbox-context"
    context.mkdir()
    dockerfile = context / "Dockerfile"
    dockerfile.write_text("FROM scratch\n", encoding="utf-8")
    recipe = hashlib.sha256(dockerfile.read_bytes()).hexdigest()
    image_id = "sha256:" + "3" * 64
    inspect_payload = json.dumps(
        {
            "Id": image_id,
            "Config": {
                "Labels": {
                    module.IMAGE_OWNER_LABEL: "true",
                    module.IMAGE_RECIPE_LABEL: recipe,
                }
            },
        }
    )
    inspect_count = 0
    calls = []

    def fake_runner(command, **kwargs):
        nonlocal inspect_count
        calls.append(command)
        if command[:3] == ["docker", "image", "inspect"]:
            inspect_count += 1
            if inspect_count == 1:
                return completed(command, status=1)
            return completed(command, stdout=inspect_payload + "\n")
        if command[:3] == ["docker", "image", "ls"]:
            return completed(command, stdout=image_id + "\n")
        if command[:3] == ["docker", "container", "ls"]:
            return completed(command)
        return completed(command)

    assert module.ensure_sandbox_image(dockerfile=dockerfile, runner=fake_runner) == image_id
    build = next(command for command in calls if command[:2] == ["docker", "build"])
    assert build[-1] == str(context)
    assert str(REPO_ROOT) not in " ".join(build)
    assert ["--build-arg", f"REPOMAP_SANDBOX_RECIPE={recipe}"] == build[4:6]



def test_managed_image_rebuilds_a_stale_owned_recipe(tmp_path):
    module = sandbox_owner
    context = tmp_path / "sandbox-context"
    context.mkdir()
    dockerfile = context / "Dockerfile"
    source = (REPO_ROOT / "tools/test_sandbox/Dockerfile").read_text()
    dockerfile.write_text(source, encoding="utf-8")
    previous = source.replace(" " + chr(92) + "\n    && go clean -cache -modcache", "")
    old_recipe = hashlib.sha256(previous.encode()).hexdigest()
    recipe = hashlib.sha256(dockerfile.read_bytes()).hexdigest()
    assert recipe != old_recipe
    image_id = "sha256:" + "a" * 64
    calls = []
    inspections = 0

    def fake_runner(command, **kwargs):
        nonlocal inspections
        calls.append(command)
        if command[:3] == ["docker", "image", "inspect"] and command[-1] == "{{json .}}":
            inspections += 1
            selected_recipe = old_recipe if inspections == 1 else recipe
            payload = {
                "Id": image_id,
                "Config": {
                    "Labels": {
                        module.IMAGE_OWNER_LABEL: "true",
                        module.IMAGE_RECIPE_LABEL: selected_recipe,
                    }
                },
            }
            return completed(command, stdout=json.dumps(payload) + "\n")
        if command[:3] == ["docker", "image", "ls"]:
            return completed(command, stdout=image_id + "\n")
        if command[:3] == ["docker", "container", "ls"]:
            return completed(command)
        return completed(command)

    assert module.ensure_sandbox_image(dockerfile=dockerfile, runner=fake_runner) == image_id
    assert any(command[:2] == ["docker", "build"] for command in calls)



def test_inner_boundary_probe_uses_identical_source_and_scratch_paths(tmp_path):
    module = sandbox_owner
    calls = []
    child_id = "4" * 64
    volume_name = "repomap-sandbox-probe-volume-" + "6" * 16

    def fake_runner(command, **kwargs):
        calls.append(command)
        if "go" in command and "version" in command:
            return completed(command, stdout="go version go1.25.10 linux/arm64\n")
        if "golangci-lint" in command:
            return completed(command, stdout="golangci-lint has version 2.6.2\n")
        if "git" in command and "config" in command:
            return completed(command, stdout="/workspace\n")
        if "git" in command and "rev-parse" in command:
            return completed(command, stdout="/workspace\n")
        if "git" in command and "status" in command:
            return completed(command, stdout="")
        if "cat" in command and "/sandbox-scratch/bind-proof" in command:
            return completed(command, stdout="ok\n")
        if "docker" in command and "run" in command:
            return completed(command, stdout=child_id + "\n")
        if "volume" in command and "create" in command:
            return completed(command, stdout=volume_name + "\n")
        if "inspect" in command:
            return completed(command, status=1)
        return completed(command)

    module.prove_inner_boundary(
        fake_runner,
        container_id="5" * 64,
        token="6" * 16,
    )

    nested = next(command for command in calls if "docker" in command and "run" in command)
    text = " ".join(nested)
    assert "type=bind,src=/workspace,dst=/workspace,readonly" in text
    assert "type=bind,src=/sandbox-scratch,dst=/sandbox-scratch" in text
    assert ["docker", "exec", "5" * 64, "cat", "/sandbox-scratch/bind-proof"] in calls
    assert any("volume" in command and "rm" in command for command in calls)



def test_managed_image_retention_deletes_only_exact_owned_unreferenced_image():
    module = sandbox_owner
    current = "sha256:" + "7" * 64
    retained = "sha256:" + "8" * 64
    stale = "sha256:" + "9" * 64
    calls = []

    def fake_runner(command, **kwargs):
        calls.append(command)
        if command[:3] == ["docker", "image", "ls"]:
            return completed(command, stdout=f"{current}\n{retained}\n{stale}\n")
        if command[:3] == ["docker", "container", "ls"]:
            return completed(command)
        if command[:3] == ["docker", "image", "inspect"]:
            if command[-1] == "{{json .Config.Labels}}":
                labels = json.dumps({module.IMAGE_OWNER_LABEL: "true"})
                return completed(command, stdout=labels + "\n")
            return completed(command, status=1)
        return completed(command)

    module.prune_managed_sandbox_images(fake_runner, keep_image_id=current)

    assert ["docker", "image", "rm", "--no-prune", stale] in calls
    assert not any(command[-1:] == [retained] and "rm" in command for command in calls)



def test_workspace_mountpoint_preparation_orders_overlay_before_bind_targets():
    module = sandbox_owner
    calls = []
    container_id = "8" * 64

    def fake_runner(command, **kwargs):
        calls.append(command)
        return completed(command)

    module._prepare_workspace_and_identity(fake_runner, container_id)

    inner_commands = [
        command[3:]
        for command in calls
        if command[:3] == ["docker", "exec", container_id]
    ]

    pre_overlay_mkdir = [
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
    chmod_scratch = [
        "chmod",
        "0700",
        str(module.INNER_TEST_SCRATCH_ROOT),
    ]
    overlay_mount = [
        "mount",
        "-t",
        "overlay",
        "overlay",
        "-o",
        "lowerdir=/workspace-ro,upperdir=/sandbox-scratch/workspace-upper,"
        "workdir=/sandbox-scratch/workspace-work",
        "/workspace",
    ]
    post_overlay_mkdir = [
        "mkdir",
        "-p",
        "/workspace/build",
        "/workspace/src/main/python/repomap_kg.egg-info",
    ]
    bind_build = [
        "mount",
        "--bind",
        "/sandbox-scratch/project-build",
        "/workspace/build",
    ]
    bind_egg_info = [
        "mount",
        "--bind",
        "/sandbox-scratch/project-egg-info",
        "/workspace/src/main/python/repomap_kg.egg-info",
    ]
    git_safe_config = [
        "git",
        "config",
        "--file",
        "/sandbox-scratch/operator-home/.gitconfig",
        "--add",
        "safe.directory",
        "/workspace",
    ]

    assert inner_commands[0] == pre_overlay_mkdir
    assert "/workspace/build" not in pre_overlay_mkdir
    assert "/workspace/src/main/python/repomap_kg.egg-info" not in pre_overlay_mkdir
    assert str(module.INNER_TEST_SCRATCH_ROOT) in pre_overlay_mkdir

    assert inner_commands[1] == chmod_scratch
    assert inner_commands[2] == overlay_mount
    assert inner_commands[3] == post_overlay_mkdir
    assert inner_commands[4] == bind_build
    assert inner_commands[5] == bind_egg_info
    assert inner_commands[8] == git_safe_config

    overlay_idx = inner_commands.index(overlay_mount)
    post_mkdir_idx = inner_commands.index(post_overlay_mkdir)
    bind_build_idx = inner_commands.index(bind_build)
    bind_egg_idx = inner_commands.index(bind_egg_info)
    git_safe_idx = inner_commands.index(git_safe_config)

    assert overlay_idx < post_mkdir_idx
    assert post_mkdir_idx < bind_build_idx
    assert post_mkdir_idx < bind_egg_idx
    assert overlay_idx < git_safe_idx


def test_query_container_processes_uses_ps_when_available() -> None:
    from runner_coverage_container import _query_container_processes

    expected = "  PID ARGS\n    1 /bin/sh\n   10 python3 worker.py\n"
    fake = subprocess.CompletedProcess(
        args=["docker", "exec", "c1", "ps", "-eo", "pid,args"],
        returncode=0, stdout=expected, stderr="",
    )
    with patch("subprocess.run", return_value=fake) as mock_run:
        assert _query_container_processes("c1") == expected
        assert mock_run.call_args[0][0] == ["docker", "exec", "c1", "ps", "-eo", "pid,args"]


def test_query_container_processes_falls_back_to_python_proc_reader() -> None:
    from runner_coverage_container import _query_container_processes

    ps_failed = subprocess.CompletedProcess(args=[], returncode=127, stdout="", stderr="")
    proc_out = "PID ARGS\n1 /bin/sleep 60\n15 python3 -c import time; # tok-xyz\n"
    py_ok = subprocess.CompletedProcess(args=[], returncode=0, stdout=proc_out, stderr="")

    def fake_run(cmd, **kwargs):
        return ps_failed if "ps" in cmd else py_ok if "python3" in cmd else None

    with patch("subprocess.run", side_effect=fake_run):
        assert _query_container_processes("c2") == proc_out


def test_query_container_processes_fails_closed_when_all_fail() -> None:
    from runner_coverage_container import _query_container_processes

    failed = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")
    with patch("subprocess.run", return_value=failed):
        with pytest.raises(RuntimeError, match="failed to query process table in container c3"):
            _query_container_processes("c3")


def test_extract_pid_from_container_ps_with_proc_output() -> None:
    from runner_coverage_container import extract_pid_from_container_ps

    proc_out = "PID ARGS\n1 /bin/sleep 60\n42 python3 -c import time; # tok-match-123\n"
    assert extract_pid_from_container_ps(proc_out, "tok-match-123") == 42


def test_run_smoke_suite_exports_runtime_image() -> None:
    from runner_unit_execution import run_smoke_suite

    real_source_root = REPO_ROOT / "src" / "main" / "python"
    args = MagicMock(smoke_image_reference="sha256:" + "a" * 64, smoke_timeout=10, pg_container_port=55433)
    orig_sys_path = sys.path[:]
    try:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("REPOMAP_TEST_RUNTIME_IMAGE", None)
            with patch("smoke.container_smoke.run_container_smoke", return_value=0):
                code = run_smoke_suite(args, resource_run=None, docker_boundary=None, repo_root=REPO_ROOT, source_root=real_source_root)
                assert code == 0
                assert os.environ.get("REPOMAP_TEST_RUNTIME_IMAGE") == "sha256:" + "a" * 64
    finally:
        sys.path[:] = orig_sys_path


def test_run_selected_suites_exports_runtime_image_for_int() -> None:
    from runner_unit_execution import run_selected_suites

    args = MagicMock(suite="int", smoke_image_reference="sha256:" + "b" * 64)
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("REPOMAP_TEST_RUNTIME_IMAGE", None)
        code = run_selected_suites(
            args, [], resource_run=None, docker_boundary=None,
            require_integration_sandbox_fn=lambda s: None, validate_runner_options_fn=lambda a, s: None,
            run_system_suite_fn=None, run_smoke_suite_fn=lambda *a, **kw: 0,
            prepare_go_test_environment_fn=lambda s: None, run_pytest_suites_fn=lambda *a, **kw: 0,
            report_docker_projection_fn=lambda *a, **kw: None,
        )
        assert code == 0
        assert os.environ.get("REPOMAP_TEST_RUNTIME_IMAGE") == "sha256:" + "b" * 64


def test_staging_runtime_image_absent_fails_closed_in_sandbox() -> None:
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("REPOMAP_TEST_RUNTIME_IMAGE", None)
        with patch("test_sandbox.active_sandbox", return_value=True):
            image = os.environ.get("REPOMAP_TEST_RUNTIME_IMAGE")
            assert not image
            with pytest.raises(pytest.fail.Exception, match="authoritative runtime image identity"):
                if not image:
                    pytest.fail(
                        "required staging execution failed: authoritative runtime image identity "
                        "(REPOMAP_TEST_RUNTIME_IMAGE) is absent"
                    )
