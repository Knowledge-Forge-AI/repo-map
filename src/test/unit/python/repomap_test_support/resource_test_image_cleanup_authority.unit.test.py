from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
from types import SimpleNamespace

from docker import DockerClient
from docker.models.containers import Container, ContainerCollection
from docker.models.networks import Network, NetworkCollection
import pytest

from repomap_test_support.resource_run import TestResourceRun

from repomap_test_support.resource_test_image_cleanup import (
    MaterializationCleanupError,
)

from repomap_test_support.resource_ledger import (
    CleanupResult,
    FinalPresence,
    ResourceKind,
    ResourceLedger,
    RunIdentity,
)
from repomap_test_support.resource_test_image_base import (
    TestImageError as ImageLifecycleError,
)
from repomap_test_support.resource_test_image_materialization import (
    MaterializationContainerOwner,
    recover_interrupted_runtime_materialization,
)


BASE_ID = "sha256:" + "b" * 64
BRIDGE_ID = "d" * 64


class NotFound(Exception):
    pass


class FakeApiError(Exception):
    def __init__(self, explanation: str, *, status_code: int = 409) -> None:
        self.explanation = explanation
        self.status_code = status_code
        super().__init__(explanation)


class FakeContainer(Container):
    def __init__(
        self, owner: FakeContainers, identity: str, image_id: str, name: str, network_mode: str
    ) -> None:
        self.owner = owner
        self._id = identity
        self.stop_calls: list[int] = []
        self.remove_calls: list[tuple[bool, bool]] = []
        self.state: dict[str, object] = {
            "Status": "created", "Running": False, "Paused": False,
            "Restarting": False, "Dead": False, "ExitCode": 0,
        }
        self.attrs = {
            "Config": {"Labels": {}}, "Image": image_id, "Mounts": [], "Name": f"/{name}",
            "NetworkSettings": {"Networks": {network_mode: {"NetworkID": BRIDGE_ID}}},
            "HostConfig": {
                "AutoRemove": False, "NetworkMode": network_mode,
                "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0},
            },
            "State": self.state,
        }

    @property
    def id(self) -> str:
        return self._id

    def reload(self) -> None:
        return None

    def stop(self, *, timeout: float | None = None) -> None:
        if timeout is not None:
            self.stop_calls.append(int(timeout))
        if self.owner.client.stop_error:
            raise FakeApiError("container still running")
        if not self.owner.client.stop_leaves_running:
            self.state.update(Status="exited", Running=False)

    def remove(self, *, force: bool = False, v: bool = False, **kwargs: object) -> None:
        self.remove_calls.append((force, v))
        if self.owner.client.remove_error:
            raise FakeApiError("container removal rejected")
        if not self.owner.client.leave_after_remove:
            self.owner.objects.pop(self.owner.lookup_key, None)


class FakeContainers(ContainerCollection):
    client: FakeClient

    def __init__(self, client: FakeClient) -> None:
        self.client = client
        self.objects: dict[str, FakeContainer] = {}
        self.lookup_key = "1" * 64

    def create(self, *args: object, **kwargs: object) -> FakeContainer:
        image = str(args[0]) if args else str(kwargs.get("image", ""))
        name = str(kwargs.get("name", ""))
        assert kwargs.get("labels", {}) == {} and kwargs.get("entrypoint", []) == ["python"]
        container = FakeContainer(self, self.lookup_key, image, name, str(kwargs.get("network_mode", "bridge")))
        self.objects[self.lookup_key] = container
        if self.client.create_mutator is not None:
            self.client.create_mutator(container)
        return container

    def get(self, *args: object, **kwargs: object) -> FakeContainer:
        identity = str(args[0]) if args else str(kwargs.get("container_id", ""))
        for container in self.objects.values():
            if container.attrs["Name"] == f"/{identity}":
                return container
        try:
            return self.objects[identity]
        except KeyError as error:
            raise NotFound(identity) from error


class FakeNetwork(Network):
    def __init__(self, network_id: str, attrs: dict[str, object]) -> None:
        self._id = network_id
        self.attrs = attrs

    @property
    def id(self) -> str:
        return self._id

    def reload(self) -> None:
        return None


class FakeNetworks(NetworkCollection):
    client: FakeClient

    def __init__(self, client: FakeClient) -> None:
        self.client = client

    def get(self, *args: object, **kwargs: object) -> FakeNetwork:
        name = str(args[0]) if args else str(kwargs.get("network_id", ""))
        return self.client._network(name)


class FakeClient(DockerClient):
    def __init__(self) -> None:
        self.create_mutator: Callable[[FakeContainer], None] | None = None
        self.stop_error: bool = False
        self.stop_leaves_running: bool = False
        self.remove_error: bool = False
        self.leave_after_remove: bool = False
        self.bridge_available: bool = True
        self._containers = FakeContainers(self)
        self._networks = FakeNetworks(self)

    @property
    def containers(self) -> FakeContainers:
        return self._containers

    @property
    def networks(self) -> FakeNetworks:
        return self._networks

    def _network(self, name: str) -> FakeNetwork:
        if name != "bridge" or not self.bridge_available:
            raise NotFound(name)
        return FakeNetwork(
            network_id=BRIDGE_ID,
            attrs={
                "Id": BRIDGE_ID, "Name": "bridge", "Driver": "bridge", "Scope": "local",
                "Internal": False, "Options": {"com.docker.network.bridge.default_bridge": "true"},
            },
        )


class FakeResourceRun(TestResourceRun):
    def __init__(self, ledger: ResourceLedger, materialization_manifest_path: Path) -> None:
        self.ledger = ledger
        self.materialization_manifest_path = materialization_manifest_path


def _owner(tmp_path):
    ledger = ResourceLedger.create(
        tmp_path / "ledger.json",
        RunIdentity("repo-map", "REPOMAP-CI0B-FIX23", "focused-run"),
    )
    client = FakeClient()
    owner = MaterializationContainerOwner(
        FakeResourceRun(
            ledger=ledger,
            materialization_manifest_path=tmp_path / "materialization.json",
        ),
        client,
    )
    return owner, client


def _create(owner: MaterializationContainerOwner) -> str:
    return owner.create(BASE_ID, ["-c", "pass"])


@pytest.mark.parametrize(
    ("mutate", "predicate"),
    (
        (lambda c: c.attrs["NetworkSettings"].update(Networks={"bridge": {"NetworkID": "e" * 64}}), "network_authority"),
        (lambda c: c.attrs.update(Name="/renamed-after-create"), "container_name"),
        (lambda c: c.attrs["Config"].update(Labels={"changed": "true"}), "labels"),
        (lambda c: c.attrs.update(Image="sha256:" + "9" * 64), "base_image"),
        (lambda c: c.attrs.update(Mounts=[{"Type": "bind"}]), "mounts"),
    ),
)
def test_owned_cleanup_removes_exact_id_and_records_conformance_drift(
    tmp_path, mutate, predicate
):
    owner, client = _owner(tmp_path)
    container_id = _create(owner)
    container = client.containers.objects[container_id]
    mutate(container)

    evidence = owner.cleanup(container_id)

    assert evidence["execution_conformance"] == {
        "status": "drifted",
        "predicate": predicate,
    }
    assert container.remove_calls == [(True, False)]
    assert client.containers.objects == {}


def test_owned_cleanup_does_not_require_live_bridge_after_create(tmp_path):
    owner, client = _owner(tmp_path)
    container_id = _create(owner)
    container = client.containers.objects[container_id]
    client.bridge_available = False

    evidence = owner.cleanup(container_id)

    assert evidence["execution_conformance"] == {
        "status": "drifted",
        "predicate": "network_authority",
    }
    assert container.remove_calls == [(True, False)]


@pytest.mark.parametrize("stop_outcome", ("error", "nonterminal"))
def test_owned_nonterminal_cleanup_records_stop_outcome_and_force_removes(
    tmp_path, stop_outcome
):
    owner, client = _owner(tmp_path)
    container_id = _create(owner)
    container = client.containers.objects[container_id]
    container.attrs["State"].update(Status="running", Running=True)
    client.stop_error = stop_outcome == "error"
    client.stop_leaves_running = stop_outcome == "nonterminal"

    evidence = owner.cleanup(container_id)

    assert evidence["stop_attempted"] is True
    assert evidence["terminal_state_confirmed"] is False
    assert evidence["stop_result"] == stop_outcome
    assert container.stop_calls == [10]
    assert container.remove_calls == [(True, False)]
    assert client.containers.objects == {}


def test_manifest_mismatch_reports_closed_subtype_and_preserves_owned_object(tmp_path):
    owner, client = _owner(tmp_path)
    container_id = _create(owner)
    container = client.containers.objects[container_id]

    with pytest.raises(
        ImageLifecycleError,
        match=(
            "identity_or_state_validation_refused:manifest_container_id"
        ),
    ) as caught:
        owner.cleanup("2" * 64)

    assert isinstance(caught.value, MaterializationCleanupError)
    assert caught.value.failure_kind.endswith(":manifest_container_id")
    assert container.remove_calls == []


def test_ledger_mismatch_reports_closed_subtype_and_preserves_owned_object(tmp_path):
    owner, client = _owner(tmp_path)
    container_id = _create(owner)
    container = client.containers.objects[container_id]
    owner.ledger.get = lambda *_args: SimpleNamespace(
        creation_owner="foreign",
        creation_observed=True,
        cleanup_required=True,
    )

    with pytest.raises(
        ImageLifecycleError,
        match="identity_or_state_validation_refused:ledger_ownership",
    ):
        owner.cleanup(container_id)

    assert container.remove_calls == []


def test_foreign_object_returned_for_exact_lookup_is_never_removed(tmp_path):
    owner, client = _owner(tmp_path)
    container_id = _create(owner)
    foreign = FakeContainer(
        client.containers,
        "2" * 64,
        BASE_ID,
        "foreign",
        "bridge",
    )
    client.containers.objects[container_id] = foreign

    with pytest.raises(
        ImageLifecycleError,
        match="identity_or_state_validation_refused:container_id",
    ):
        owner.cleanup(container_id)

    assert foreign.remove_calls == []


def test_exact_remove_failure_records_failed_and_present(tmp_path):
    owner, client = _owner(tmp_path)
    container_id = _create(owner)
    client.remove_error = True

    with pytest.raises(ImageLifecycleError, match="remove_api_rejected"):
        owner.cleanup(container_id)

    record = owner.ledger.get(ResourceKind.DOCKER_CONTAINER, container_id)
    assert record.cleanup_result is CleanupResult.FAILED
    assert record.final_presence is FinalPresence.PRESENT


def test_interrupted_recovery_uses_owned_exact_id_without_live_bridge_or_name(tmp_path):
    owner, client = _owner(tmp_path)
    container_id = _create(owner)
    container = client.containers.objects[container_id]
    container.attrs["Name"] = "/renamed-after-interruption"
    client.bridge_available = False

    recovered = recover_interrupted_runtime_materialization(
        client, manifest_path=owner.manifest_path
    )

    assert recovered == container_id
    assert container.remove_calls == [(True, False)]
    assert client.containers.objects == {}
    record = ResourceLedger.open(owner.ledger.path, owner.ledger.identity).get(
        ResourceKind.DOCKER_CONTAINER, container_id
    )
    assert record.cleanup_result is CleanupResult.REMOVED
    assert record.final_presence is FinalPresence.ABSENT


@pytest.mark.parametrize(
    ("mutate", "message"),
    (
        (lambda container: container.attrs.update(Name="/wrong"), "name differs"),
        (lambda container: container.attrs.update(Image="sha256:" + "9" * 64), "image differs"),
        (lambda container: container.attrs["Config"].update(Labels={"unauthorized": "true"}), "label-free"),
        (lambda container: container.attrs.update(Mounts=[{"Type": "bind"}]), "has mounts"),
        (lambda container: container.attrs["HostConfig"].update(RestartPolicy={"Name": "always"}), "restart policy differs"),
        (lambda container: container.attrs["HostConfig"].update(AutoRemove=True), "auto-remove policy differs"),
        (lambda container: container.attrs["HostConfig"].update(NetworkMode="host"), "network mode differs"),
    ),
)
def test_create_time_execution_conformance_still_refuses_unsafe_configuration(
    tmp_path, mutate, message
):
    owner, client = _owner(tmp_path)
    client.create_mutator = mutate

    with pytest.raises(ImageLifecycleError, match=message):
        _create(owner)

    assert next(iter(client.containers.objects.values())).remove_calls == []


def test_failed_cleanup_evidence_remains_private_and_bounded(tmp_path):
    owner, client = _owner(tmp_path)
    container_id = _create(owner)
    client.remove_error = True

    with pytest.raises(ImageLifecycleError) as caught:
        owner.cleanup(container_id)

    assert isinstance(caught.value, MaterializationCleanupError)
    serialized = json.dumps(caught.value.cleanup_evidence, sort_keys=True)
    assert "container removal rejected" not in serialized
    assert "daemon_explanation_category" in serialized
