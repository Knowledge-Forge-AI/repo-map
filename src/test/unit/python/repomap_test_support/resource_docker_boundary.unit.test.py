from __future__ import annotations

from types import SimpleNamespace

import pytest

from repomap_test_support.resource_docker_boundary import (
    PROJECTION_FIELDS,
    RunWideDockerBoundary,
    RunWideDockerResidueError,
)
from repomap_test_support.resource_docker_mediation import CanonicalDockerAuthority
from repomap_test_support.resource_docker_operations import (
    DERIVED_OPERATION_FIELDS,
    DockerOperationJournal,
)
from repomap_test_support.resource_ledger import (
    ResourceKind,
    ResourceLedger,
    RunIdentity,
)
from repomap_test_support.resource_test_image_base import (
    BaseImageProvenance,
    parse_immutable_image_authority,
)


class Item:
    def __init__(
        self, identity: str, labels=None, tags=(), repo_digests=(), architecture="arm64"
    ):
        self.id = identity
        self.tags = list(tags)
        self.attrs = {
            "Config": {"Labels": labels or {}},
            "Labels": labels or {},
            "RepoDigests": list(repo_digests),
            "Architecture": architecture,
        }


class Collection:
    def __init__(self, items=()):
        self.items = {item.id: item for item in items}
        self.removed: list[str] = []

    def list(self, **_kwargs):
        return list(self.items.values())

    def get(self, identity: str):
        return self.items[identity]


class Client:
    def __init__(self, *, architecture="arm64"):
        self.images = Collection((Item("sha256:baseline"),))
        self.volumes = Collection((Item("baseline-volume"),))
        self.architecture = architecture

    def info(self):
        return {"Architecture": self.architecture}


def managed_run(tmp_path):
    identity = RunIdentity("repo-map_dev", "SAFETY3", "run-1")
    ledger = ResourceLedger.create(tmp_path / "ledger.json", identity)
    return SimpleNamespace(ledger=ledger)


_INSTALLED: list[CanonicalDockerAuthority] = []


@pytest.fixture(autouse=True)
def _uninstall_authorities():
    yield
    while _INSTALLED:
        _INSTALLED.pop().uninstall()


def make_boundary(run, client) -> RunWideDockerBoundary:
    """Build a boundary the only way production may: over a live observer.

    The authority is really installed, so the ``unmanaged_*`` zeros these
    tests read back describe a population something was actually watching.
    """
    authority = CanonicalDockerAuthority(DockerOperationJournal.for_ledger(run.ledger))
    authority.install()
    _INSTALLED.append(authority)
    return RunWideDockerBoundary(run, client, authority=authority)


def test_obs1_recover1_unchanged_engine_zeros_are_derived_from_an_empty_population(
    tmp_path,
) -> None:
    """Every zero here is read back out of an observed population of size zero."""
    boundary = make_boundary(managed_run(tmp_path), Client())

    projection = boundary.verify_terminal()
    evidence = boundary.operation_evidence()

    assert set(projection) == set(PROJECTION_FIELDS)
    assert projection == dict.fromkeys(PROJECTION_FIELDS, 0)
    assert evidence["event_count"] == 0
    assert evidence["materialization_count"] == 0
    assert evidence["derived"] == dict.fromkeys(DERIVED_OPERATION_FIELDS, 0)


def test_obs1_recover1_projection_is_unavailable_when_no_population_was_observed(
    tmp_path,
) -> None:
    """A boundary that cannot be constructed reports nothing, never zeros."""
    with pytest.raises(RunWideDockerResidueError, match="managed resource ledger is required") as e:
        RunWideDockerBoundary(SimpleNamespace(ledger=None), Client(), authority=None)

    assert e.value.projection == {}


def test_obs1_recover4_boundary_refuses_to_invent_an_authority(tmp_path) -> None:
    """The PROOF1 defect class: zeros over a population nobody observed.

    Default-constructing an authority here would leave it uninstalled, so the
    unmanaged counters would read zero because nothing could ever have seen an
    unmanaged operation, not because none occurred.
    """
    with pytest.raises(RunWideDockerResidueError, match="authority is required") as raised:
        RunWideDockerBoundary(managed_run(tmp_path), Client())

    assert raised.value.projection == {}


def test_obs1_recover4_uninstalled_authority_cannot_project_or_verify(
    tmp_path,
) -> None:
    """An authority that exists but never intercepted anything is not evidence."""
    run = managed_run(tmp_path)
    authority = CanonicalDockerAuthority(DockerOperationJournal.for_ledger(run.ledger))
    boundary = RunWideDockerBoundary(run, Client(), authority=authority)

    assert authority.installed is False
    for call in (boundary.projection, boundary.verify_terminal):
        with pytest.raises(RunWideDockerResidueError, match="authority is not installed") as raised:
            call()
        assert raised.value.projection == {}


def test_obs1_recover1_manager_evidence_disagreement_fails_closed(tmp_path) -> None:
    boundary = make_boundary(managed_run(tmp_path), Client())
    boundary.record_manager_evidence(
        {
            "runtime_build_intermediate_created_count": 3,
            "runtime_build_intermediate_removed_count": 0,
            "runtime_build_intermediate_residue_count": 3,
        }
    )

    with pytest.raises(RuntimeError, match="disagrees with the operation journal"):
        boundary.verify_terminal()


def test_obs1_recover1_manager_evidence_omitting_a_count_fails_closed(tmp_path) -> None:
    boundary = make_boundary(managed_run(tmp_path), Client())
    boundary.record_manager_evidence({"runtime_build_intermediate_created_count": 0})

    with pytest.raises(RuntimeError, match="omits an operation count"):
        boundary.verify_terminal()


def test_obs1_recover1_operation_evidence_survives_a_later_terminal_failure(
    tmp_path,
) -> None:
    """A report or assertion failure after the fact cannot erase the event."""
    client = Client()
    run = managed_run(tmp_path)
    boundary = make_boundary(run, client)
    with boundary.managed_external_base_pull(request="repo@sha256:abc") as ticket:
        boundary.complete_operation(ticket, image_ids=("sha256:base",))
    client.images.items["sha256:foreign"] = Item("sha256:foreign")

    with pytest.raises(RuntimeError):
        boundary.verify_terminal()
    retained = boundary.retain_operation_evidence()

    assert retained.stat().st_mode & 0o777 == 0o600
    assert boundary.operation_evidence()["derived"][
        "managed_external_base_pull_count"
    ] == 1


@pytest.mark.parametrize(
    ("kind", "identity", "field"),
    [
        ("images", "sha256:foreign", "new_unattributed_images"),
        ("volumes", "foreign-volume", "new_unattributed_volumes"),
    ],
)
def test_safety3_new_unattributed_ids_fail_closed_without_deletion(
    tmp_path,
    kind: str,
    identity: str,
    field: str,
) -> None:
    client = Client()
    boundary = make_boundary(managed_run(tmp_path), client)
    collection = getattr(client, kind)
    collection.items[identity] = Item(identity)

    with pytest.raises(RuntimeError, match="unattributed Docker residue") as raised:
        boundary.verify_terminal()

    assert getattr(client, kind).removed == []
    assert getattr(raised.value, "projection")[field] == 1


def test_safety3_baseline_ids_are_protected_not_owned(tmp_path) -> None:
    client = Client()
    boundary = make_boundary(managed_run(tmp_path), client)

    boundary.verify_terminal()

    assert set(client.images.items) == {"sha256:baseline"}
    assert set(client.volumes.items) == {"baseline-volume"}


def _cache_labels(fingerprint: str) -> dict[str, str]:
    return {
        "org.repomap.test.managed": "true",
        "org.repomap.test.image.class": "runtime-cache",
        "org.repomap.test.image.schema": "1",
        "org.repomap.test.runtime-fingerprint": fingerprint,
        "org.repomap.test.repository": "repo-map",
    }


def _external_base_provenance(
    reference: str,
    image_id: str,
    *,
    image_architecture: str = "arm64",
    server_architecture: str = "arm64",
) -> BaseImageProvenance:
    authority = parse_immutable_image_authority(reference)
    return BaseImageProvenance(
        reference=reference,
        repository=authority.repository,
        digest=authority.digest,
        canonical_reference=authority.canonical_reference,
        optional_tag=authority.optional_tag,
        image_id=image_id,
        repo_digests=(authority.canonical_reference,),
        architecture="arm64",
        image_architecture=image_architecture,
        server_architecture=server_architecture,
        canonical_image_architecture="arm64",
        canonical_server_architecture="arm64",
        pulled=True,
    )


def test_runwide_boundary_accepts_exact_manager_registered_persistent_cache(
    tmp_path,
) -> None:
    client = Client()
    run = managed_run(tmp_path)
    boundary = make_boundary(run, client)
    fingerprint = "f" * 64
    identity = "sha256:" + "a" * 64
    client.images.items[identity] = Item(
        identity,
        _cache_labels(fingerprint),
        (f"repomap-test-runtime:py312-arm64-{fingerprint[:12]}",),
    )
    run.ledger.register(
        ResourceKind.DOCKER_IMAGE,
        identity,
        creation_owner="TestImageManager",
        created_before_run=False,
        creation_observed=True,
        cleanup_required=False,
    )
    with boundary.managed_test_runtime_build(request="repomap-test-runtime:x") as ticket:
        boundary.record_materialization(
            ticket,
            final_image_id=identity,
            intermediate_created_ids=(),
            intermediate_removed_ids=(),
        )
        boundary.complete_operation(ticket, image_ids=(identity,))
    boundary.register_managed_runtime_cache(identity, fingerprint)

    projection = boundary.verify_terminal()

    assert projection["managed_test_runtime_image_build_count"] == 1
    assert projection["managed_runtime_build_intermediate_created_count"] == 0
    assert projection["managed_runtime_build_intermediate_residue_count"] == 0
    assert projection["new_managed_test_runtime_cache_images"] == 1
    assert projection["new_unattributed_images"] == 0


def test_runwide_boundary_rejects_labelled_cache_not_registered_by_manager(
    tmp_path,
) -> None:
    client = Client()
    boundary = make_boundary(managed_run(tmp_path), client)
    fingerprint = "e" * 64
    identity = "sha256:" + "b" * 64
    client.images.items[identity] = Item(
        identity,
        _cache_labels(fingerprint),
        (f"repomap-test-runtime:py312-arm64-{fingerprint[:12]}",),
    )

    with pytest.raises(RunWideDockerResidueError, match="unattributed Docker residue") as raised:
        boundary.verify_terminal()

    assert raised.value.projection["new_unattributed_images"] == 1


def test_runwide_boundary_classifies_manager_pulled_external_base_separately(
    tmp_path,
) -> None:
    client = Client(architecture="aarch64")
    run = managed_run(tmp_path)
    boundary = make_boundary(run, client)
    reference = "python:3.12-slim-bookworm@sha256:" + "c" * 64
    identity = "sha256:" + "f" * 64
    authority = parse_immutable_image_authority(reference)
    client.images.items[identity] = Item(
        identity,
        tags=("python:3.12-slim-bookworm:stable",),
        repo_digests=(authority.canonical_reference,),
        architecture="arm64",
    )
    run.ledger.register(
        ResourceKind.DOCKER_IMAGE,
        identity,
        creation_owner="TestImageManager",
        created_before_run=False,
        creation_observed=True,
        cleanup_required=False,
    )
    with boundary.managed_external_base_pull(request=reference) as ticket:
        boundary.complete_operation(ticket, image_ids=(identity,))
    boundary.register_managed_external_test_base(
        _external_base_provenance(
            reference,
            identity,
            image_architecture="arm64",
            server_architecture="aarch64",
        )
    )

    projection = boundary.verify_terminal()

    assert projection["managed_external_base_pull_count"] == 1
    assert projection["new_managed_external_test_base_images"] == 1
    assert projection["new_managed_test_runtime_cache_images"] == 0
    assert projection["new_unattributed_images"] == 0


def test_runwide_boundary_rejects_unattributed_base_like_image(tmp_path) -> None:
    client = Client()
    boundary = make_boundary(managed_run(tmp_path), client)
    reference = "python:3.12-slim-bookworm@sha256:" + "c" * 64
    identity = "sha256:" + "f" * 64
    client.images.items[identity] = Item(identity, repo_digests=(reference,))

    with pytest.raises(RunWideDockerResidueError, match="unattributed Docker residue") as raised:
        boundary.verify_terminal()

    assert raised.value.projection["new_unattributed_images"] == 1
