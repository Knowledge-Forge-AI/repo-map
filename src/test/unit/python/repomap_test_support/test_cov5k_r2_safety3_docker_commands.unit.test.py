from __future__ import annotations

from repomap_test_support.postgres_container import TEST_POSTGRES_IMAGE
from repomap_test_support.test_cov5k_r2_group_k_container import (
    _group_k_container_create_command,
)


def test_safety3_group_k_postgres_creation_prevents_anonymous_volume() -> None:
    command = _group_k_container_create_command(
        container_name="repomap-safety3-k09",
        run_detached=True,
        password="public-safe-fixture",
        ownership_labels={"org.repomap.test.resource.run_id": "run-1"},
    )

    assert "--pull=never" in command
    assert "--tmpfs" in command
    assert "/var/lib/postgresql/data" in command
    assert "--rm" not in command
    assert command[-1] == TEST_POSTGRES_IMAGE
    assert "org.repomap.test.resource.run_id=run-1" in command


def test_safety3_group_k_docker_create_argument_shape_k08_k10() -> None:
    labels = {
        "org.repomap.test.resource.project": "repo-map_dev",
        "org.repomap.test.resource.run_id": "run-create",
        "org.repomap.test.resource.role": "group-k-k08",
    }
    command = _group_k_container_create_command(
        container_name="repomap-safety3-k08",
        run_detached=False,
        password="public-safe-fixture-create",
        ownership_labels=labels,
    )

    assert command[0:2] == ["docker", "create"]
    assert "-d" not in command
    assert "--pull=never" in command
    assert "--name" in command and command[command.index("--name") + 1] == "repomap-safety3-k08"
    assert "--tmpfs" in command
    assert "/var/lib/postgresql/data" in command
    assert "--rm" not in command
    assert command[-1] == TEST_POSTGRES_IMAGE
    for k, v in labels.items():
        assert f"{k}={v}" in command


def test_safety3_group_k_docker_detached_run_argument_shape_k09_k12() -> None:
    labels = {
        "org.repomap.test.resource.project": "repo-map_dev",
        "org.repomap.test.resource.run_id": "run-detached",
        "org.repomap.test.resource.role": "group-k-k09",
    }
    command = _group_k_container_create_command(
        container_name="repomap-safety3-k09-shape",
        run_detached=True,
        password="public-safe-fixture-detached",
        ownership_labels=labels,
    )

    assert command[0:3] == ["docker", "run", "-d"]
    assert "--pull=never" in command
    assert "--name" in command and command[command.index("--name") + 1] == "repomap-safety3-k09-shape"
    assert "--tmpfs" in command
    assert "/var/lib/postgresql/data" in command
    assert "--rm" not in command
    assert command[-1] == TEST_POSTGRES_IMAGE
    for k, v in labels.items():
        assert f"{k}={v}" in command


def test_safety3_group_k_command_builder_owner_regression() -> None:
    import repomap_test_support.test_cov5k_r2_fix1_executors as fix1_executors
    import repomap_test_support.test_cov5k_r2_group_k_container as group_k_container

    assert hasattr(group_k_container, "_group_k_container_create_command")
    assert not hasattr(fix1_executors, "_group_k_container_create_command")


def test_safety3_group_k_command_builder_behavior_and_volume_prevention() -> None:
    labels = {
        "org.repomap.test.resource.project": "repo-map_dev",
        "org.repomap.test.resource.run_id": "run-strict-safety",
        "org.repomap.test.resource.role": "group-k-k07",
    }
    password = "strict-safety-secret"
    command = _group_k_container_create_command(
        container_name="repomap-safety3-strict",
        run_detached=True,
        password=password,
        ownership_labels=labels,
    )

    # Invariants preventing anonymous volumes
    assert "-v" not in command
    assert "--volume" not in command
    assert "--tmpfs" in command
    tmpfs_index = command.index("--tmpfs")
    assert command[tmpfs_index + 1] == "/var/lib/postgresql/data"

    # Command builder argument sequence and contents
    assert command[:3] == ["docker", "run", "-d"]
    assert command[3:5] == ["--pull=never", "--name"]
    assert command[5] == "repomap-safety3-strict"

    sorted_labels = sorted(labels.items())
    label_indices = [i for i, arg in enumerate(command) if arg == "--label"]
    assert len(label_indices) == len(sorted_labels)
    for idx, (k, v) in zip(label_indices, sorted_labels):
        assert command[idx + 1] == f"{k}={v}"

    assert "-e" in command
    e_idx = command.index("-e")
    assert command[e_idx + 1] == f"POSTGRES_PASSWORD={password}"
    assert command[-1] == TEST_POSTGRES_IMAGE
    assert "--rm" not in command
