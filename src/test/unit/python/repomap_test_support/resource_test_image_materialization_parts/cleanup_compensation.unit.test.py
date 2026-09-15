"""Container cleanup validation and candidate image compensation unit tests."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from repomap_test_support.resource_docker_boundary import RunWideDockerBoundary
from repomap_test_support.resource_docker_mediation import CanonicalDockerAuthority
from repomap_test_support.resource_docker_operations import DockerOperationJournal
from repomap_test_support.resource_ledger import (
    ResourceKind,
    ResourceLedger,
    RunIdentity,
)
from repomap_test_support.resource_test_image_base import (
    TestImageError as ImageLifecycleError,
)
from repomap_test_support.resource_test_image_cleanup import (
    MaterializationCleanupError,
)
from repomap_test_support.resource_test_image_materialization import (
    RuntimeMaterializationError,
)
from repomap_test_support.resource_test_images import TestImageManager as ImageManager
from src.test.unit.python.repomap_test_support.resource_test_image_materialization_parts.fixtures import (
    BASE_ID,
    BASE_REFERENCE,
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


def test_cleanup_refuses_exact_lookup_returning_a_different_container_id(tmp_path: Path):
    materializer, client = _materializer(tmp_path)
    container_id = materializer.containers.create(BASE_ID, ["-c", "pass"])
    container = client.containers.objects[container_id]
    container._id = "2" * 64
    assert container.id == "2" * 64

    with pytest.raises(
        MaterializationCleanupError,
        match="identity_or_state_validation_refused:container_id",
    ) as caught:
        materializer.containers.cleanup(container_id)

    assert container.remove_calls == []
    assert "ID differs" in caught.value.cleanup_evidence["validation_category"]
    assert caught.value.cleanup_evidence["validation_predicate"] == "container_id"
    record = materializer.containers.ledger.get(
        ResourceKind.DOCKER_CONTAINER, container_id
    )
    assert record.cleanup_result.value == "failed"
    assert record.final_presence.value == "present"


@pytest.mark.parametrize(
    ("field", "value", "predicate"),
    (
        ("RestartPolicy", {"Name": "always"}, "restart_policy"),
        ("AutoRemove", True, "auto_remove"),
    ),
)
def test_cleanup_records_policy_drift_and_removes_owned_container(
    tmp_path: Path, field: str, value: object, predicate: str
):
    materializer, client = _materializer(tmp_path)
    container_id = materializer.containers.create(BASE_ID, ["-c", "pass"])
    container = client.containers.objects[container_id]
    container.attrs["HostConfig"][field] = value

    evidence = materializer.containers.cleanup(container_id)

    assert evidence["execution_conformance"] == {
        "status": "drifted",
        "predicate": predicate,
    }
    assert container.remove_calls[0][:2] == (True, False)


def test_cleanup_refuses_manifest_container_id_mismatch(tmp_path: Path):
    materializer, client = _materializer(tmp_path)
    container_id = materializer.containers.create(BASE_ID, ["-c", "pass"])
    container = client.containers.objects[container_id]

    with pytest.raises(
        MaterializationCleanupError, match="identity_or_state_validation_refused"
    ) as caught:
        materializer.containers.cleanup("2" * 64)

    assert "manifest container ID differs" in caught.value.cleanup_evidence[
        "validation_category"
    ]
    assert caught.value.cleanup_evidence["validation_predicate"] == "manifest_container_id"
    assert container.remove_calls == []


def test_cleanup_refuses_ledger_owner_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    materializer, _client = _materializer(tmp_path)
    container_id = materializer.containers.create(BASE_ID, ["-c", "pass"])
    record = materializer.containers.ledger.get(
        ResourceKind.DOCKER_CONTAINER, container_id
    )
    foreign_record = replace(
        record, creation_owner="foreign", creation_observed=True, cleanup_required=True
    )
    monkeypatch.setattr(materializer.containers.ledger, "get", lambda *_args: foreign_record)

    with pytest.raises(MaterializationCleanupError) as caught:
        materializer.containers.cleanup(container_id)

    assert caught.value.failure_kind == (
        "identity_or_state_validation_refused:ledger_ownership"
    )
    assert "ledger ownership differs" in caught.value.cleanup_evidence[
        "validation_category"
    ]
    assert caught.value.cleanup_evidence["validation_predicate"] == "ledger_ownership"


def test_failed_candidate_compensation_refuses_without_deleting_image(tmp_path: Path):
    materializer, client = _materializer(tmp_path)
    client.fail_container_cleanup = True
    client.images.fail_remove = True

    with pytest.raises(
        RuntimeMaterializationError,
        match="managed_runtime_build_cleanup_failed: failure_compensation_refused",
    ) as caught:
        materializer.materialize(
            base_image_id=BASE_ID,
            tag="repomap-test-runtime:compensation-refused",
            labels={"org.repomap.test.managed": "true"},
            dependencies=("psycopg[binary]==3.2.12",),
            psycopg_release_version="3.2.12",
        )

    assert caught.value.materialization_evidence["final_image_compensation"] == (
        "failure_compensation_refused"
    )
    assert "sha256:" + "3" * 64 in client.images.objects


def test_cleanup_failure_compensates_candidate_but_preserves_unexpected_delta(tmp_path: Path):
    materializer, client = _materializer(tmp_path)
    client.fail_container_cleanup = True
    client.unexpected_image = True

    with pytest.raises(ImageLifecycleError, match="remove_api_rejected"):
        materializer.materialize(
            base_image_id=BASE_ID,
            tag="repomap-test-runtime:unexpected-cleanup-failure",
            labels={"org.repomap.test.managed": "true"},
            dependencies=("psycopg[binary]==3.2.12",),
            psycopg_release_version="3.2.12",
        )

    assert "sha256:" + "3" * 64 not in client.images.objects
    assert "sha256:" + "4" * 64 in client.images.objects
    assert client.images.remove_calls == [("sha256:" + "3" * 64, False, True)]


def test_failed_manager_materialization_records_one_compensated_candidate(
    tmp_path: Path, install_authority
):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    repo_root.joinpath("pyproject.toml").write_text(
        """[project]
name = "fixture"
version = "0.1"
dependencies = ["psycopg[binary]==3.2.12"]
""",
        encoding="utf-8",
    )
    ledger = ResourceLedger.create(
        tmp_path / "failed-manager-ledger.json",
        RunIdentity("repo-map", "REPOMAP-CI0B-FIX19", "failed-manager"),
    )
    resource_run = FakeResourceRun(
        ledger=ledger,
        materialization_manifest_path=tmp_path / "failed-manager-manifest.json",
    )
    client = FakeClient()
    client.fail_container_cleanup = True
    boundary = RunWideDockerBoundary(
        resource_run, client, authority=install_authority(ledger)
    )
    manager = ImageManager(
        repo_root=repo_root,
        resource_run=resource_run,
        client=client,
        base_reference=BASE_REFERENCE,
        python_base_family="python:3.12-slim-bookworm",
        python_version="3.12.13",
        psycopg_release_version="3.2.12",
        boundary=boundary,
        probe=lambda _image_id: pytest.fail("failed materialization reached probe"),
    )

    with pytest.raises(ImageLifecycleError, match="remove_api_rejected"):
        manager.ensure_runtime_image()

    observations = boundary.journal.materializations()
    assert len(observations) == 1
    assert observations[0].final_image_id == "sha256:" + "3" * 64
    assert observations[0].intermediate_created_ids == ()
    assert "sha256:" + "3" * 64 not in client.images.objects


def test_unexpected_delta_image_is_not_deleted_as_owned_output(tmp_path: Path):
    materializer, client = _materializer(tmp_path)
    client.unexpected_image = True

    with pytest.raises(ImageLifecycleError, match="materialization failed"):
        materializer.materialize(
            base_image_id=BASE_ID,
            tag="repomap-test-runtime:unexpected",
            labels={"org.repomap.test.managed": "true"},
            dependencies=("psycopg[binary]==3.2.12",),
            psycopg_release_version="3.2.12",
        )

    assert client.images.remove_calls == []
    assert "sha256:" + "4" * 64 in client.images.objects
