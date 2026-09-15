from __future__ import annotations
from pathlib import Path
from typing import Any
import json
import subprocess
import pytest
from repomap_test_support.resource_docker import ownership_labels
from repomap_test_support.test_cov5k_r2_group_k_container import execute_group_k_docker

from src.test.unit.python.repomap_test_support.test_cov5k_r2_group_k_lifecycle_parts.fixtures import FakeContainer, FakeDockerClient, _make_resource_run, _make_entry

def test_group_k_setup_failure_plus_lookup_uncertainty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _make_resource_run(tmp_path)
    monkeypatch.setattr("repomap_test_support.test_cov5k_r2_group_k_container.active_resource_run", lambda: run)

    fake_client = FakeDockerClient()
    monkeypatch.setattr("docker.from_env", lambda: fake_client)

    def failing_setup(*a: Any, **kw: Any) -> Any:
        raise RuntimeError("disposable setup command failed")

    monkeypatch.setattr("repomap_test_support.test_cov5k_r2_group_k_container._run_checked_setup", failing_setup)

    def uncertain_get(name: str) -> Any:
        raise ConnectionError("docker daemon socket disconnected")

    monkeypatch.setattr(fake_client.containers, "get", uncertain_get)

    case_root = tmp_path / "k09"
    case_root.mkdir()

    with pytest.raises(RuntimeError, match="disposable setup command failed") as excinfo:
        execute_group_k_docker(
            entry=_make_entry("K09"),
            case_root=case_root,
            container_name="repomap-fix1-k09-uncertain",
            shape=("docker", "inspect", "{container_id}"),
            command=["docker", "inspect", "{container_id}"],
            environment={},
        )

    assert excinfo.value.__context__ is not None
    assert isinstance(excinfo.value.__context__, ConnectionError)
    assert fake_client.closed is True
    unresolved_file = case_root / "unresolved_cleanup.json"
    assert unresolved_file.exists()
    payload = json.loads(unresolved_file.read_text(encoding="utf-8"))
    assert "discovery_uncertainty" in payload["reason"]


def test_group_k_registration_refusal_baseline_object_preserved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _make_resource_run(tmp_path)
    monkeypatch.setattr("repomap_test_support.test_cov5k_r2_group_k_container.active_resource_run", lambda: run)

    cid = "baseline-container-99990000"
    baseline_container = FakeContainer(cid, {"some": "foreign_label"})
    fake_client = FakeDockerClient(preexisting=(baseline_container,))
    monkeypatch.setattr("docker.from_env", lambda: fake_client)

    name = "repomap-fix1-k09-baseline"

    def colliding_setup(*a: Any, **kw: Any) -> subprocess.CompletedProcess[str]:
        fake_client.containers.register(name, baseline_container)
        return subprocess.CompletedProcess([], 0, stdout=f"{cid}\n", stderr="")

    monkeypatch.setattr("repomap_test_support.test_cov5k_r2_group_k_container._run_checked_setup", colliding_setup)

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

    assert baseline_container.removed is False, "Pre-existing baseline container must never be removed"
    assert fake_client.closed is True


def test_group_k_foreign_labels_refuses_deletion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _make_resource_run(tmp_path)
    monkeypatch.setattr("repomap_test_support.test_cov5k_r2_group_k_container.active_resource_run", lambda: run)

    cid = "foreign-container-33334444"
    foreign_container = FakeContainer(cid, {"org.repomap.test.resource.project": "other_project"})
    fake_client = FakeDockerClient()
    name = "repomap-fix1-k09-foreign"
    fake_client.containers.register(name, foreign_container)
    monkeypatch.setattr("docker.from_env", lambda: fake_client)

    def foreign_setup(*a: Any, **kw: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 0, stdout=f"{cid}\n", stderr="")

    monkeypatch.setattr("repomap_test_support.test_cov5k_r2_group_k_container._run_checked_setup", foreign_setup)

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

    assert foreign_container.removed is False, "Foreign container must never be deleted"
    assert fake_client.closed is True


def test_group_k_client_close_failure_preserves_primary_operation_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _make_resource_run(tmp_path)
    monkeypatch.setattr("repomap_test_support.test_cov5k_r2_group_k_container.active_resource_run", lambda: run)

    cid = "close-fail-id-55556666"
    role = "group-k-k09"
    expected_labels = ownership_labels(run.ledger.identity, role=role, retained=False)
    container = FakeContainer(cid, expected_labels)
    fake_client = FakeDockerClient()
    name = "repomap-fix1-k09-closefail"
    monkeypatch.setattr("docker.from_env", lambda: fake_client)

    def ok_setup(*a: Any, **kw: Any) -> subprocess.CompletedProcess[str]:
        fake_client.containers.register(name, container)
        return subprocess.CompletedProcess([], 0, stdout=f"{cid}\n", stderr="")

    monkeypatch.setattr("repomap_test_support.test_cov5k_r2_group_k_container._run_checked_setup", ok_setup)

    def failing_close() -> None:
        fake_client.closed = True
        raise RuntimeError("client close socket failure")

    monkeypatch.setattr(fake_client, "close", failing_close)

    def failing_runner(cmd: list[str], cwd: Path, env: dict[str, str]) -> Any:
        raise RuntimeError("runner primary failure")

    case_root = tmp_path / "k09"
    case_root.mkdir()

    with pytest.raises(RuntimeError, match="runner primary failure") as excinfo:
        execute_group_k_docker(
            entry=_make_entry("K09"),
            case_root=case_root,
            container_name=name,
            shape=("docker", "inspect", "{container_id}"),
            command=["docker", "inspect", "{container_id}"],
            environment={},
            runner=failing_runner,
        )

    assert excinfo.value.__context__ is not None
    assert "client close socket failure" in str(excinfo.value.__context__)
    assert fake_client.closed is True
