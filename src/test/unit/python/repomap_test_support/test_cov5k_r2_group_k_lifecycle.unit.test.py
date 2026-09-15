from __future__ import annotations
from pathlib import Path
from typing import Any
import json
import subprocess
import pytest
from repomap_test_support.resource_docker import ownership_labels
from repomap_test_support.test_cov5k_r2_group_k_container import execute_group_k_docker

from src.test.unit.python.repomap_test_support.test_cov5k_r2_group_k_lifecycle_parts.fixtures import FakeContainer, FakeDockerClient, _make_resource_run, _make_entry

def test_group_k_clean_creation_registers_and_cleans_up(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _make_resource_run(tmp_path)
    monkeypatch.setattr("repomap_test_support.test_cov5k_r2_group_k_container.active_resource_run", lambda: run)

    fake_client = FakeDockerClient()
    monkeypatch.setattr("docker.from_env", lambda: fake_client)

    cid = "exact-container-id-12345678"
    role = "group-k-k09"
    name = "repomap-fix1-k09-test"
    expected_labels = ownership_labels(run.ledger.identity, role=role, retained=False)
    created_container = FakeContainer(cid, expected_labels)

    def setup_creates(*a: Any, **kw: Any) -> subprocess.CompletedProcess[str]:
        fake_client.containers.register(name, created_container)
        return subprocess.CompletedProcess([], 0, stdout=f"{cid}\n", stderr="")

    monkeypatch.setattr(
        "repomap_test_support.test_cov5k_r2_group_k_container._run_checked_setup",
        setup_creates,
    )

    runner_called = False

    def fake_runner(cmd: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        nonlocal runner_called
        runner_called = True
        assert cmd[-1] == cid
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    case_root = tmp_path / "k09"
    case_root.mkdir()
    observed_argv, completed = execute_group_k_docker(
        entry=_make_entry("K09"),
        case_root=case_root,
        container_name=name,
        shape=("docker", "inspect", "{container_id}"),
        command=["docker", "inspect", "{container_id}"],
        environment={},
        runner=fake_runner,
    )

    assert runner_called
    assert completed.returncode == 0
    assert observed_argv == ("docker", "inspect", "{container_id}")
    assert created_container.removed is True
    assert fake_client.closed is True


def test_group_k_no_object_on_refusal_raises_primary_error_and_closes_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _make_resource_run(tmp_path)
    monkeypatch.setattr("repomap_test_support.test_cov5k_r2_group_k_container.active_resource_run", lambda: run)

    fake_client = FakeDockerClient()
    monkeypatch.setattr("docker.from_env", lambda: fake_client)

    def failing_setup(*a: Any, **kw: Any) -> Any:
        raise RuntimeError("Group K disposable setup failed (image_unavailable, exit 125)")

    monkeypatch.setattr("repomap_test_support.test_cov5k_r2_group_k_container._run_checked_setup", failing_setup)

    case_root = tmp_path / "k09"
    case_root.mkdir()

    with pytest.raises(RuntimeError, match="image_unavailable"):
        execute_group_k_docker(
            entry=_make_entry("K09"),
            case_root=case_root,
            container_name="repomap-fix1-k09-refused",
            shape=("docker", "inspect", "{container_id}"),
            command=["docker", "inspect", "{container_id}"],
            environment={},
        )

    assert fake_client.closed is True
    assert not case_root.joinpath("unresolved_cleanup.json").exists()


def test_group_k_partial_creation_cleans_up_owned_container_and_raises_primary_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _make_resource_run(tmp_path)
    monkeypatch.setattr("repomap_test_support.test_cov5k_r2_group_k_container.active_resource_run", lambda: run)

    fake_client = FakeDockerClient()
    monkeypatch.setattr("docker.from_env", lambda: fake_client)

    cid = "partial-container-id-87654321"
    name = "repomap-fix1-k09-partial"
    role = "group-k-k09"
    expected_labels = ownership_labels(run.ledger.identity, role=role, retained=False)
    partial_container = FakeContainer(cid, expected_labels)

    def partial_failure_setup(*a: Any, **kw: Any) -> Any:
        fake_client.containers.register(name, partial_container)
        raise RuntimeError("Group K disposable setup failed (setup_failed, exit 1)")

    monkeypatch.setattr("repomap_test_support.test_cov5k_r2_group_k_container._run_checked_setup", partial_failure_setup)

    case_root = tmp_path / "k09"
    case_root.mkdir()

    with pytest.raises(RuntimeError, match="setup_failed"):
        execute_group_k_docker(
            entry=_make_entry("K09"),
            case_root=case_root,
            container_name=name,
            shape=("docker", "inspect", "{container_id}"),
            command=["docker", "inspect", "{container_id}"],
            environment={},
        )

    assert partial_container.removed is True
    assert fake_client.closed is True


def test_group_k_foreign_name_collision_protects_foreign_container(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _make_resource_run(tmp_path)
    monkeypatch.setattr("repomap_test_support.test_cov5k_r2_group_k_container.active_resource_run", lambda: run)

    name = "repomap-fix1-k09-colliding"
    # Container exists before run starts (preexisting baseline)
    foreign_container = FakeContainer("foreign-preexisting-id-11112222", {"org.repomap.test.resource.run_id": "foreign-run"})
    fake_client = FakeDockerClient(preexisting=(foreign_container,))
    fake_client.containers.register(name, foreign_container)
    monkeypatch.setattr("docker.from_env", lambda: fake_client)

    def collision_setup(*a: Any, **kw: Any) -> Any:
        raise RuntimeError("Group K disposable setup failed (setup_failed, exit 125)")

    monkeypatch.setattr("repomap_test_support.test_cov5k_r2_group_k_container._run_checked_setup", collision_setup)

    case_root = tmp_path / "k09"
    case_root.mkdir()

    with pytest.raises(RuntimeError, match="setup_failed"):
        execute_group_k_docker(
            entry=_make_entry("K09"),
            case_root=case_root,
            container_name=name,
            shape=("docker", "inspect", "{container_id}"),
            command=["docker", "inspect", "{container_id}"],
            environment={},
        )

    assert foreign_container.removed is False
    assert fake_client.closed is True
    unresolved_file = case_root / "unresolved_cleanup.json"
    assert unresolved_file.exists()
    payload = json.loads(unresolved_file.read_text(encoding="utf-8"))
    assert payload["reason"] == "pre_existing_baseline_collision"


def test_group_k_owner_mismatch_protects_foreign_container(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _make_resource_run(tmp_path)
    monkeypatch.setattr("repomap_test_support.test_cov5k_r2_group_k_container.active_resource_run", lambda: run)

    name = "repomap-fix1-k09-mismatch"
    fake_client = FakeDockerClient()
    # Container created by another run / role
    mismatched_container = FakeContainer("mismatched-container-id-33334444", {"org.repomap.test.resource.run_id": "other-run"})
    monkeypatch.setattr("docker.from_env", lambda: fake_client)

    def mismatch_setup(*a: Any, **kw: Any) -> Any:
        fake_client.containers.register(name, mismatched_container)
        raise RuntimeError("Group K disposable setup failed (setup_failed, exit 1)")

    monkeypatch.setattr("repomap_test_support.test_cov5k_r2_group_k_container._run_checked_setup", mismatch_setup)

    case_root = tmp_path / "k09"
    case_root.mkdir()

    with pytest.raises(RuntimeError, match="setup_failed"):
        execute_group_k_docker(
            entry=_make_entry("K09"),
            case_root=case_root,
            container_name=name,
            shape=("docker", "inspect", "{container_id}"),
            command=["docker", "inspect", "{container_id}"],
            environment={},
        )

    assert mismatched_container.removed is False
    assert fake_client.closed is True
    unresolved_file = case_root / "unresolved_cleanup.json"
    assert unresolved_file.exists()
    payload = json.loads(unresolved_file.read_text(encoding="utf-8"))
    assert payload["reason"] == "foreign_or_mismatched_ownership_labels"


def test_group_k_malformed_id_output_handles_cleanup_and_raises_malformed_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _make_resource_run(tmp_path)
    monkeypatch.setattr("repomap_test_support.test_cov5k_r2_group_k_container.active_resource_run", lambda: run)

    fake_client = FakeDockerClient()
    name = "repomap-fix1-k09-malformed"
    cid = "malformed-fallback-owned-id-5555"
    role = "group-k-k09"
    expected_labels = ownership_labels(run.ledger.identity, role=role, retained=False)
    owned_container = FakeContainer(cid, expected_labels)
    monkeypatch.setattr("docker.from_env", lambda: fake_client)

    # Setup returned 0 but stdout is invalid (e.g. whitespace)
    def malformed_setup(*a: Any, **kw: Any) -> subprocess.CompletedProcess[str]:
        fake_client.containers.register(name, owned_container)
        return subprocess.CompletedProcess([], 0, stdout="   \n", stderr="")

    monkeypatch.setattr(
        "repomap_test_support.test_cov5k_r2_group_k_container._run_checked_setup",
        malformed_setup,
    )

    case_root = tmp_path / "k09"
    case_root.mkdir()

    with pytest.raises(RuntimeError, match="malformed container ID"):
        execute_group_k_docker(
            entry=_make_entry("K09"),
            case_root=case_root,
            container_name=name,
            shape=("docker", "inspect", "{container_id}"),
            command=["docker", "inspect", "{container_id}"],
            environment={},
        )

    assert owned_container.removed is True
    assert fake_client.closed is True


def test_group_k_registration_refusal_rolls_back_and_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _make_resource_run(tmp_path)
    monkeypatch.setattr("repomap_test_support.test_cov5k_r2_group_k_container.active_resource_run", lambda: run)

    fake_client = FakeDockerClient()
    cid = "refused-volume-container-66667777"
    name = "repomap-fix1-k09-refused"
    role = "group-k-k09"
    expected_labels = ownership_labels(run.ledger.identity, role=role, retained=False)
    refused_container = FakeContainer(cid, expected_labels, volume_mount=True)
    monkeypatch.setattr("docker.from_env", lambda: fake_client)

    def refused_setup(*a: Any, **kw: Any) -> subprocess.CompletedProcess[str]:
        fake_client.containers.register(name, refused_container)
        return subprocess.CompletedProcess([], 0, stdout=f"{cid}\n", stderr="")

    monkeypatch.setattr(
        "repomap_test_support.test_cov5k_r2_group_k_container._run_checked_setup",
        refused_setup,
    )

    case_root = tmp_path / "k09"
    case_root.mkdir()

    with pytest.raises(RuntimeError, match="registration failed"):
        execute_group_k_docker(
            entry=_make_entry("K09"),
            case_root=case_root,
            container_name=name,
            shape=("docker", "inspect", "{container_id}"),
            command=["docker", "inspect", "{container_id}"],
            environment={},
        )

    assert refused_container.removed is False
    assert fake_client.closed is True
