from __future__ import annotations

from pathlib import Path

import pytest

from repomap_test_support.resource_docker_boundary import RunWideDockerBoundary
from repomap_test_support.resource_docker_mediation import CanonicalDockerAuthority
from repomap_test_support.resource_docker_operations import DockerOperationJournal
from repomap_test_support.resource_ledger import ResourceKind, ResourceLedger, RunIdentity
from repomap_test_support.resource_test_image_base import (
    TestImageError as ImageLifecycleError,
)
from repomap_test_support.resource_test_image_materialization import (
    MATERIALIZATION_NETWORK_MODE,
    MATERIALIZATION_NETWORK_POLICY,
    MaterializationContainerOwner,
    RuntimeMaterializationError,
    recover_interrupted_runtime_materialization,
)
from repomap_test_support.resource_test_images import TestImageManager as ImageManager
from src.test.unit.python.repomap_test_support.resource_test_image_materialization_parts.fixtures import (
    BASE_ID,
    BASE_REFERENCE,
    BRIDGE_ID,
    FakeClient,
    FakeResourceRun,
    _materializer,
)


@pytest.fixture
def install_authority():
    """Boundaries need a live observer, so tests install a real one."""
    installed: list[CanonicalDockerAuthority] = []

    def make(ledger) -> CanonicalDockerAuthority:
        authority = CanonicalDockerAuthority(DockerOperationJournal.for_ledger(ledger))
        authority.install()
        installed.append(authority)
        return authority

    yield make
    for authority in reversed(installed):
        authority.uninstall()


@pytest.mark.parametrize("project", ("repo-map_dev", "repo-map"))
def test_exact_run_materialization_creates_only_the_final_engine_image(
    tmp_path: Path,
    install_authority,
    project,
):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    repo_root.joinpath("pyproject.toml").write_text(
        """[project]
name = "fixture"
version = "0.1"
dependencies = ["psycopg[binary]==3.2.12", "typing-extensions==4.16.0"]
""",
        encoding="utf-8",
    )
    ledger = ResourceLedger.create(
        tmp_path / "ledger.json",
        RunIdentity(project, "TEST-IMAGE-LIFECYCLE1-R1-INTERMEDIATE1", "run-1"),
    )
    resource_run = FakeResourceRun(
        ledger=ledger,
        materialization_manifest_path=tmp_path / "materialization.json",
    )
    client = FakeClient()
    client.normalize_bridge_mode_after_wait = True
    boundary = RunWideDockerBoundary(
        resource_run, client, authority=install_authority(ledger)
    )
    probe_calls: list[str] = []
    manager = ImageManager(
        repo_root=repo_root,
        resource_run=resource_run,
        client=client,
        base_reference=BASE_REFERENCE,
        python_base_family="python:3.12-slim-bookworm",
        python_version="3.12.13",
        psycopg_release_version="3.2.12",
        boundary=boundary,
        probe=probe_calls.append,
    )

    selected = manager.ensure_runtime_image()
    projection = boundary.verify_terminal()

    assert selected == "sha256:" + "3" * 64
    assert projection["managed_runtime_build_intermediate_created_count"] == 0
    assert projection["managed_runtime_build_intermediate_removed_count"] == 0
    assert projection["managed_runtime_build_intermediate_residue_count"] == 0
    assert projection["new_unattributed_images"] == 0
    assert projection["managed_test_runtime_image_build_count"] == 1
    assert projection["new_managed_test_runtime_cache_images"] == 1
    assert probe_calls == [selected]
    assert client.images.remove_calls == []
    assert client.images.build_calls == []
    assert client.containers.objects == {}
    assert client.containers.create_calls
    assert client.containers.create_calls[0][4]["network_mode"] == "bridge"
    assert client.containers.create_calls[0][2] == {}
    assert MATERIALIZATION_NETWORK_MODE == "bridge"
    assert MATERIALIZATION_NETWORK_POLICY == "dependency-acquisition-built-in-bridge-v1"
    evidence = manager.last_materialization_evidence
    assert evidence is not None
    assert evidence["stage"] == "completed"
    assert evidence["execution"]["exit_code"] == 0
    assert evidence["cleanup_result"] == "removed"
    assert evidence["final_container_presence"] == "absent"
    assert client.commit_calls[0][0:2] == (
        "repomap-test-runtime",
        manager.runtime_tag(manager.runtime_identity().fingerprint).split(":", 1)[1],
    )
    assert client.commit_calls[0][2] == {
        "Cmd": ["python3"],
        "Entrypoint": None,
        "Labels": {
            "org.repomap.test.image.class": "runtime-cache",
            "org.repomap.test.image.schema": "1",
            "org.repomap.test.managed": "true",
            "org.repomap.test.repository": "repo-map",
            "org.repomap.test.runtime-fingerprint": manager.runtime_identity().fingerprint,
        },
    }


def test_interrupted_label_free_materialization_is_recovered_from_manifest(tmp_path: Path):
    ledger = ResourceLedger.create(
        tmp_path / "recovery-ledger.json",
        RunIdentity("repo-map_dev", "TEST-IMAGE-LIFECYCLE1-R1-LABEL1", "run-recovery"),
    )
    manifest = tmp_path / "materialization-recovery.json"
    resource_run = FakeResourceRun(
        ledger=ledger,
        materialization_manifest_path=manifest,
    )
    client = FakeClient()
    owner = MaterializationContainerOwner(resource_run, client)
    container_id = owner.create(BASE_ID, ["-c", "pass"])
    container = client.containers.objects[container_id]
    container.attrs["HostConfig"]["NetworkMode"] = "default"
    container.attrs["NetworkSettings"]["Networks"] = {"bridge": {"NetworkID": BRIDGE_ID}}

    recovered = recover_interrupted_runtime_materialization(
        client, manifest_path=manifest
    )

    assert recovered == container_id
    assert container.remove_calls[0][:2] == (True, False)
    assert client.containers.objects == {}
    assert not manifest.exists()
    record = ResourceLedger.open(ledger.path, ledger.identity).get(
        ResourceKind.DOCKER_CONTAINER, container_id
    )
    assert record.cleanup_result.value == "removed"
    assert record.final_presence.value == "absent"


def test_failed_materialization_cleans_exact_temporary_container(tmp_path: Path):
    materializer, client = _materializer(tmp_path)
    client.wait_status = 7
    client.stdout = b"install stdout\n"
    client.stderr = b"network resolution failed\n"

    with pytest.raises(RuntimeMaterializationError, match="materialization failed") as caught:
        materializer.materialize(
            base_image_id=BASE_ID,
            tag="repomap-test-runtime:failure",
            labels={"org.repomap.test.managed": "true"},
            dependencies=("psycopg[binary]==3.2.12",),
            psycopg_release_version="3.2.12",
        )

    evidence = caught.value.materialization_evidence
    assert evidence["stage"] == "dependency-install-and-probe"
    assert evidence["container_id"] == "1" * 64
    container_name = evidence["container_name"]
    assert isinstance(container_name, str)
    assert container_name.startswith("repomap-test-materialization-")
    assert evidence["configured_network_mode"] == "bridge"
    assert evidence["readback_network_mode"] == "bridge"
    assert evidence["command_category"] == "exact-runtime-dependency-install-and-probe"
    assert evidence["execution"] == {
        "exit_code": 7,
        "stdout": "install stdout\n",
        "stderr": "network resolution failed\n",
    }
    nested_exception = evidence["nested_exception"]
    assert isinstance(nested_exception, dict)
    assert nested_exception["type"] == "TestImageError"
    assert nested_exception["message"] == (
        "managed runtime dependency installation failed"
    )
    assert evidence["cleanup_result"] == "removed"
    assert evidence["final_container_presence"] == "absent"
    assert caught.value.__cause__ is not None
    assert client.containers.objects == {}
    assert set(client.images.objects) == {BASE_ID}
    assert client.images.remove_calls == []


def test_recovery_removes_owned_container_after_network_mode_drift(tmp_path: Path):
    ledger = ResourceLedger.create(
        tmp_path / "wrong-network-ledger.json",
        RunIdentity("repo-map", "TEST-IMAGE-LIFECYCLE1-R1-NET1", "wrong-network"),
    )
    manifest = tmp_path / "wrong-network-materialization.json"
    client = FakeClient()
    owner = MaterializationContainerOwner(
        FakeResourceRun(ledger=ledger, materialization_manifest_path=manifest),
        client,
    )
    container_id = owner.create(BASE_ID, ["-c", "pass"])
    client.containers.objects[container_id].attrs["HostConfig"]["NetworkMode"] = "none"

    recovered = recover_interrupted_runtime_materialization(
        client, manifest_path=manifest
    )

    assert recovered == container_id
    assert container_id not in client.containers.objects
    assert not manifest.exists()


@pytest.mark.parametrize(
    ("network_mode", "networks"),
    (
        ("default", {}),
        ("default", {"bridge": {"NetworkID": "e" * 64}}),
        ("none", {"none": {"NetworkID": ""}}),
        ("host", {"host": {"NetworkID": ""}}),
        ("custom", {"custom": {"NetworkID": "e" * 64}}),
        ("default", {
            "bridge": {"NetworkID": BRIDGE_ID},
            "unexpected": {"NetworkID": "e" * 64},
        }),
    ),
)
def test_cleanup_records_network_drift_and_removes_owned_container(
    tmp_path: Path, network_mode: str, networks: dict
):
    materializer, client = _materializer(tmp_path)
    container_id = materializer.containers.create(BASE_ID, ["-c", "pass"])
    container = client.containers.objects[container_id]
    container.attrs["HostConfig"]["NetworkMode"] = network_mode
    container.attrs["NetworkSettings"]["Networks"] = networks

    evidence = materializer.containers.cleanup(container_id)

    assert evidence["execution_conformance"] == {
        "status": "drifted",
        "predicate": "network_authority",
    }
    assert container.remove_calls[0][:2] == (True, False)
    assert client.containers.objects == {}


def test_materialization_refuses_absent_builtin_bridge_without_creating_container(
    tmp_path: Path,
):
    materializer, client = _materializer(tmp_path)
    client.bridge_available = False

    with pytest.raises(ImageLifecycleError, match="built-in bridge is unavailable"):
        materializer.materialize(
            base_image_id=BASE_ID,
            tag="repomap-test-runtime:no-bridge",
            labels={"org.repomap.test.managed": "true"},
            dependencies=("psycopg[binary]==3.2.12",),
            psycopg_release_version="3.2.12",
        )

    assert client.containers.create_calls == []


def test_materialization_container_cleanup_failure_is_terminal(tmp_path: Path):
    materializer, client = _materializer(tmp_path)
    client.fail_container_cleanup = True

    with pytest.raises(
        RuntimeMaterializationError,
        match="managed_runtime_build_cleanup_failed: remove_api_rejected",
    ) as caught:
        materializer.materialize(
            base_image_id=BASE_ID,
            tag="repomap-test-runtime:cleanup-failure",
            labels={"org.repomap.test.managed": "true"},
            dependencies=("psycopg[binary]==3.2.12",),
            psycopg_release_version="3.2.12",
        )

    assert set(client.containers.objects) == {"1" * 64}
    assert "private detail" not in str(caught.value)
    evidence = caught.value.materialization_evidence
    cleanup_failure = evidence["cleanup_failure"]
    assert isinstance(cleanup_failure, dict)
    assert cleanup_failure["http_status_code"] == 409
    assert cleanup_failure["daemon_explanation_category"] == (
        "removal_in_progress"
    )
    assert cleanup_failure["exact_container_exists_afterward"] is True
    assert evidence["final_image_compensation"] == "removed_exact_candidate"
    assert "sha256:" + "3" * 64 not in client.images.objects
    record = materializer.containers.ledger.get(
        ResourceKind.DOCKER_CONTAINER, "1" * 64
    )
    assert record.cleanup_result.value == "failed"
    assert record.final_presence.value == "present"
    container = next(iter(client.containers.objects.values()))
    assert len(container.remove_calls) == 1


def test_cleanup_refreshes_state_and_stops_before_exact_force_removal(tmp_path: Path):
    materializer, client = _materializer(tmp_path)
    client.wait_leaves_running = True

    result = materializer.materialize(
        base_image_id=BASE_ID,
        tag="repomap-test-runtime:state-refresh",
        labels={"org.repomap.test.managed": "true"},
        dependencies=("psycopg[binary]==3.2.12",),
        psycopg_release_version="3.2.12",
    )

    cleanup = result.evidence["cleanup"]
    assert isinstance(cleanup, dict)
    pre_state, term_state = cleanup["pre_remove_state"], cleanup["terminal_state"]
    assert isinstance(pre_state, dict) and isinstance(term_state, dict)
    assert pre_state["Status"] == "running"
    assert term_state["Status"] == "exited"
    assert cleanup["force"] is True
    assert cleanup["stop_attempted"] is True
    removed = client.removed_containers[0]
    assert removed.stop_calls == [10]
    assert removed.remove_calls[0][:2] == (True, False)
    assert removed.remove_calls[0][2] >= 3
    assert client.containers.objects == {}


def test_cleanup_records_nonterminal_state_and_force_removes_owned_container(tmp_path: Path):
    materializer, client = _materializer(tmp_path)
    container_id = materializer.containers.create(BASE_ID, ["-c", "pass"])
    container = client.containers.objects[container_id]
    container.start()
    client.stop_leaves_running = True

    evidence = materializer.containers.cleanup(container_id)

    pre_state, term_state = evidence["pre_remove_state"], evidence["terminal_state"]
    assert isinstance(pre_state, dict) and isinstance(term_state, dict)
    assert pre_state["Status"] == "running"
    assert term_state["Status"] == "running"
    assert evidence["stop_attempted"] is True
    assert evidence["stop_result"] == "nonterminal"
    assert evidence["terminal_state_confirmed"] is False
    assert container.remove_calls[0][:2] == (True, False)
    assert client.containers.objects == {}


def test_cleanup_remove_returning_with_container_present_is_terminal(tmp_path: Path):
    materializer, client = _materializer(tmp_path)
    client.leave_container_after_remove = True

    with pytest.raises(
        RuntimeMaterializationError,
        match="managed_runtime_build_cleanup_failed: remove_returned_container_present",
    ) as caught:
        materializer.materialize(
            base_image_id=BASE_ID,
            tag="repomap-test-runtime:remove-returned-present",
            labels={"org.repomap.test.managed": "true"},
            dependencies=("psycopg[binary]==3.2.12",),
            psycopg_release_version="3.2.12",
        )

    assert caught.value.materialization_evidence["final_image_compensation"] == (
        "removed_exact_candidate"
    )
    assert "1" * 64 in client.containers.objects
