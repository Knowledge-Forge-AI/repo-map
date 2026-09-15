from __future__ import annotations

import test_sandbox as sandbox_owner


import hashlib

import json

import os

from pathlib import Path



import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]

from src.test.unit.python.tools.sandbox_test_fixtures import _capacity_boundary as _capacity_boundary, completed, finished_follower


def test_outer_command_uses_owned_tmpfs_dind_without_host_socket(tmp_path):
    module = sandbox_owner
    command = module.outer_run_command(
        image_id="sha256:" + "a" * 64,
        container_name="repomap-test-sandbox-owned",
        repo_root=tmp_path / "repo",
        host_gid=20,
        argv=["--suite", "int"],
    )
    text = " ".join(command)

    assert command[:3] == ["docker", "run", "-d"]
    assert "--privileged" in command
    assert "--cgroupns=host" in command
    assert command[-5:] == ["--docker-group", "20", "--", "--suite", "int"]
    assert "docker-init" in command
    assert "org.repomap.test.sandbox=true" in command
    assert "/var/lib/docker:rw,exec,nosuid,nodev,size=4g" in command
    assert "/sandbox-scratch:rw,exec,nosuid,nodev,size=8g" in command
    assert "/run:rw,nosuid,nodev,mode=0755,size=64m" in command
    assert "dst=/workspace-ro,readonly" in text
    assert "dst=/workspace,readonly" not in text
    assert "dst=/sandbox-scratch" not in text
    assert "repomap-test-sandbox-owner" not in text
    assert "/var/run/docker.sock:" not in text
    assert "unix:///run/repomap-docker.sock" in text
    assert "--publish" not in command
    assert "-p" not in command
    mounts = [command[index + 1] for index, value in enumerate(command) if value == "--mount"]
    assert mounts == [f"type=bind,src={tmp_path / 'repo'},dst=/workspace-ro,readonly"]



def test_active_marker_is_closed_and_requires_owned_file(tmp_path):
    module = sandbox_owner
    marker = tmp_path / "owner"
    token = "c" * 64
    environment = {
        module.ENV_ACTIVE: "1",
        module.ENV_TOKEN: token,
        "DOCKER_HOST": module.INNER_DOCKER_HOST,
    }

    with pytest.raises(RuntimeError, match="owner marker"):
        module.active_sandbox(environment, marker_path=marker)

    marker.write_bytes(b"\xff")
    with pytest.raises(RuntimeError, match="owner marker"):
        module.active_sandbox(environment, marker_path=marker)

    marker.write_text(token + "\n", encoding="utf-8")
    assert module.active_sandbox(
        environment,
        marker_path=marker,
        host_socket_exists=False,
        inner_socket_exists=True,
    )

    with pytest.raises(RuntimeError, match="inner Docker socket"):
        module.active_sandbox(
            environment,
            marker_path=marker,
            host_socket_exists=False,
            inner_socket_exists=False,
        )

    with pytest.raises(RuntimeError, match="host Docker socket"):
        module.active_sandbox(
            environment,
            marker_path=marker,
            host_socket_exists=True,
            inner_socket_exists=True,
        )



def test_launcher_preserves_exact_args_and_cleans_outer_on_test_failure(tmp_path):
    module = sandbox_owner
    calls = []
    recorded_calls = []
    outer_id = "d" * 64
    snapshots = iter(
        [
            module.HostSnapshot(frozenset(), frozenset(), frozenset(), frozenset()),
            module.HostSnapshot(frozenset(), frozenset(), frozenset(), frozenset()),
        ]
    )

    def fake_runner(command, **kwargs):
        calls.append(command)
        recorded_calls.append((command, kwargs))
        if command[:3] == ["docker", "run", "-d"]:
            return completed(command, stdout=outer_id + "\n")
        if command[:3] == ["docker", "container", "inspect"]:
            return completed(command, status=1)
        if command[:2] == ["docker", "wait"]:
            return completed(command, stdout="7\n")
        if command[:2] == ["docker", "logs"]:
            return completed(command)
        return completed(command)

    result = module.run_in_sandbox(
        ["--suite", "int", "--no-coverage", "--", "file.py::test_case[param]"],
        repo_root=tmp_path / "repo",
        image_id="sha256:" + "e" * 64,
        runner=fake_runner,
        follower_factory=finished_follower,
        snapshotter=lambda _runner: next(snapshots),
        boundary_prover=lambda *_args, **_kwargs: None,
    )

    assert result == 7
    outer = next(
        command
        for command in calls
        if command[:3] == ["docker", "run", "-d"]
    )
    assert outer[-8:] == [
        "--docker-group",
        str(os.getgid()),
        "--",
        "--suite",
        "int",
        "--no-coverage",
        "--",
        "file.py::test_case[param]",
    ]
    assert "/workspace-ro/tools/test_sandbox_entrypoint.py" in outer
    assert ["docker", "rm", "-f", "-v", outer_id] in calls
    marker_install = next(
        (command, kwargs)
        for command, kwargs in recorded_calls
        if command[:4] == ["docker", "exec", "-i", outer_id]
    )
    assert marker_install[1]["input"].endswith("\n")
    assert marker_install[1]["input"].strip() not in " ".join(marker_install[0])



def test_launcher_does_not_create_or_change_persistent_shared_scratch(tmp_path, monkeypatch):
    module = sandbox_owner
    outer_id = "9" * 64
    persistent = tmp_path / "persistent-shared-scratch"
    persistent.mkdir()
    sentinel = persistent / "operator-owned"
    sentinel.write_text("unchanged\n", encoding="utf-8")
    before = {path.name: path.read_bytes() for path in persistent.iterdir()}
    empty = module.HostSnapshot(frozenset(), frozenset(), frozenset(), frozenset())
    monkeypatch.setenv("REPOMAP_TEST_SCRATCH_ROOT", str(persistent))

    def fake_runner(command, **kwargs):
        if command[:3] == ["docker", "run", "-d"]:
            return completed(command, stdout=outer_id + "\n")
        if command[:2] == ["docker", "wait"]:
            return completed(command, stdout="0\n")
        if command[:3] == ["docker", "container", "inspect"]:
            return completed(command, status=1)
        return completed(command)

    assert module.run_in_sandbox(
        ["--suite", "int"],
        repo_root=tmp_path / "repo",
        image_id="sha256:" + "8" * 64,
        runner=fake_runner,
        follower_factory=finished_follower,
        snapshotter=lambda _runner: empty,
        boundary_prover=lambda *_args, **_kwargs: None,
        archive_reader=lambda *_args: (_ for _ in ()).throw(
            AssertionError("report export must be absent")
        ),
    ) == 0

    assert {path.name: path.read_bytes() for path in persistent.iterdir()} == before



def test_launcher_cleans_outer_when_interrupted(tmp_path):
    module = sandbox_owner
    calls = []
    outer_id = "f" * 64
    empty = module.HostSnapshot(frozenset(), frozenset(), frozenset(), frozenset())

    def fake_runner(command, **kwargs):
        calls.append(command)
        if command[:3] == ["docker", "run", "-d"]:
            return completed(command, stdout=outer_id + "\n")
        if command[:2] == ["docker", "wait"]:
            raise KeyboardInterrupt
        if command[:3] == ["docker", "container", "inspect"]:
            return completed(command, status=1)
        return completed(command)

    result = module.run_in_sandbox(
        ["--suite", "int"],
        repo_root=tmp_path / "repo",
        image_id="sha256:" + "1" * 64,
        runner=fake_runner,
        follower_factory=finished_follower,
        snapshotter=lambda _runner: empty,
        boundary_prover=lambda *_args, **_kwargs: None,
    )

    assert result == 130
    assert ["docker", "rm", "-f", "-v", outer_id] in calls
    assert not any(path.name == "owner" for path in tmp_path.rglob("*"))



def test_host_snapshot_delta_fails_without_deleting_unattributed_resources():
    module = sandbox_owner
    before = module.HostSnapshot(frozenset(), frozenset(), frozenset(), frozenset())
    after = module.HostSnapshot(frozenset({"new"}), frozenset(), frozenset(), frozenset())

    with pytest.raises(RuntimeError, match="unexpected host Docker residue"):
        module.verify_host_snapshot(before, after)



def test_managed_image_reuses_only_exact_recipe_identity(tmp_path):
    module = sandbox_owner
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM scratch\n", encoding="utf-8")
    recipe = hashlib.sha256(dockerfile.read_bytes()).hexdigest()
    image_id = "sha256:" + "2" * 64
    payload = json.dumps(
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
    calls = []

    def fake_runner(command, **kwargs):
        calls.append(command)
        if command[:3] == ["docker", "image", "ls"]:
            return completed(command, stdout=image_id + "\n")
        if command[:3] == ["docker", "container", "ls"]:
            return completed(command)
        return completed(command, stdout=payload + "\n")

    assert module.ensure_sandbox_image(dockerfile=dockerfile, runner=fake_runner) == image_id
    assert not any(command[:2] == ["docker", "build"] for command in calls)
