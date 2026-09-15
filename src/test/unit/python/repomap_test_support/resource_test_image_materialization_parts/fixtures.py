"""Shared test doubles and fixtures for resource test image materialization unit tests."""

from __future__ import annotations

from builtins import list as _list
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Literal, overload

from docker import APIClient, DockerClient
from docker.models.containers import Container, ContainerCollection
from docker.models.images import Image, ImageCollection
from docker.models.networks import Network, NetworkCollection
from docker.models.volumes import Volume, VolumeCollection
from docker.types.daemon import CancellableStream

if TYPE_CHECKING:
    from docker._types import JSON, WaitContainerResponse

from repomap_test_support.resource_ledger import (
    ResourceLedger,
    RunIdentity,
)
from repomap_test_support.resource_run import TestResourceRun
from repomap_test_support.resource_test_image_materialization import (
    RuntimeImageMaterializer,
)

BASE_ID = "sha256:" + "b" * 64
BRIDGE_ID = "d" * 64
BASE_REFERENCE = "python:3.12-slim-bookworm@sha256:" + "c" * 64
BASE_CANONICAL_REFERENCE = "python@sha256:" + "c" * 64
PROOF_FINGERPRINT = "9" * 64
PROOF_ID = "sha256:" + "7" * 64
PROOF_TAG = f"repomap-test-runtime:py312-arm64-{PROOF_FINGERPRINT[:12]}"
TRANSIENT_LABELS = {
    "org.repomap.test.resource.phase": "TEST-IMAGE-LIFECYCLE1-R1-INTERMEDIATE1",
    "org.repomap.test.resource.project": "repo-map", "org.repomap.test.resource.retention": "transient",
    "org.repomap.test.resource.role": "test-runtime-image-materialization",
    "org.repomap.test.resource.run_id": "forced-proof",
}


class NotFound(Exception):
    pass


class FakeApiError(Exception):
    def __init__(self, explanation: str, *, status_code: int = 409) -> None:
        self.explanation = explanation
        self.status_code = status_code
        super().__init__(explanation)


class FakeImage(Image):
    def __init__(
        self, identity: str, *, tags: Iterable[str] = (), labels: Mapping[str, str] | None = None,
        parent: str | None = None, created_by: str = "commit",
    ) -> None:
        self._id, self._tags = identity, list(tags)
        self.attrs = {
            "Architecture": "arm64", "Created": "2026-08-16T12:00:00Z", "Size": 123, "Parent": parent,
            "RepoDigests": [BASE_CANONICAL_REFERENCE] if identity == BASE_ID else [],
            "Config": {"Labels": dict(labels or {})},
        }
        self.created_by = created_by

    @property
    def id(self) -> str:
        return self._id

    @property
    def tags(self) -> list[str]:
        return self._tags

    @tags.setter
    def tags(self, value: list[str]) -> None:
        self._tags = value


class FakeImages(ImageCollection):
    def __init__(self) -> None:
        base = FakeImage(BASE_ID)
        self.objects: dict[str, FakeImage] = {base.id: base}
        self.remove_calls: list[tuple[str, bool, bool]] = []
        self.build_calls: list[dict[str, object]] = []
        self.fail_remove: bool = False

    def list(
        self, name: str | None = None, all: bool = False,
        filters: dict[str, object] | None = None,
    ) -> _list[Image]:
        del name, all, filters
        return _list(self.objects.values())

    def get(self, *args: object, **kwargs: object) -> FakeImage:
        reference = str(args[0]) if args else str(kwargs.get("name", ""))
        if reference in self.objects:
            return self.objects[reference]
        for image in self.objects.values():
            if reference in image.tags or reference in image.attrs["RepoDigests"]:
                return image
        raise NotFound(reference)

    def build(self, **kwargs: object) -> tuple[Image, Iterator[JSON]]:
        self.build_calls.append(kwargs)
        raise AssertionError(f"Dockerfile build is prohibited: {kwargs}")

    def remove(self, image: str, force: bool = False, noprune: bool = False) -> None:
        self.remove_calls.append((image, force, noprune))
        if self.fail_remove:
            raise RuntimeError("dependent child")
        self.objects.pop(image)


class FakeContainer(Container):
    def __init__(
        self, owner: FakeContainers, identity: str, image_id: str, labels: Mapping[str, str], *,
        name: str = "container-1", network_mode: str = "none",
    ) -> None:
        self.owner, self._id, self._image_id = owner, identity, image_id
        self.reload_count: int = 0
        self.stop_calls: list[float | int | None] = []
        self.remove_calls: list[tuple[bool, bool, int]] = []
        self.attrs = {
            "Config": {"Labels": dict(labels)}, "Image": image_id, "Mounts": [],
            "Name": f"/{name}",
            "NetworkSettings": {"Networks": {network_mode: {"NetworkID": ""}}},
            "HostConfig": {
                "AutoRemove": False, "NetworkMode": network_mode,
                "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0},
            },
            "State": {
                "Status": "created", "Running": False, "Paused": False,
                "Restarting": False, "Dead": False, "ExitCode": 0,
            },
        }

    @property
    def id(self) -> str:
        return self._id

    @property
    def image(self) -> FakeImage:
        return FakeImage(self._image_id)

    def reload(self) -> None:
        self.reload_count += 1

    def start(self, **kwargs: object) -> None:
        self.attrs["State"].update(Status="running", Running=True)
        if self.attrs["HostConfig"]["NetworkMode"] == "bridge":
            self.attrs["NetworkSettings"]["Networks"]["bridge"]["NetworkID"] = BRIDGE_ID

    def wait(self, *args: object, **kwargs: object) -> WaitContainerResponse:
        timeout = args[0] if args else kwargs.get("timeout")
        assert timeout == 900
        if self.owner.client.normalize_bridge_mode_after_wait:
            self.attrs["HostConfig"]["NetworkMode"] = "default"
        if not self.owner.client.wait_leaves_running:
            self.attrs["State"].update(
                Status="exited", Running=False, ExitCode=self.owner.client.wait_status
            )
        return {"StatusCode": self.owner.client.wait_status}

    def stop(self, *, timeout: float | None = None) -> None:
        self.stop_calls.append(timeout)
        if not self.owner.client.stop_leaves_running:
            self.attrs["State"].update(Status="exited", Running=False)

    @overload
    def logs(
        self, *, stdout: bool = True, stderr: bool = True, stream: Literal[True], **kwargs: object,
    ) -> CancellableStream[bytes]: ...
    @overload
    def logs(
        self, *, stdout: bool = True, stderr: bool = True, stream: Literal[False] = False, **kwargs: object,
    ) -> bytes: ...
    def logs(self, *args: object, **kwargs: object) -> bytes | CancellableStream[bytes]:
        stdout = bool(kwargs.get("stdout", True))
        stderr = bool(kwargs.get("stderr", True))
        assert stdout is not stderr
        return self.owner.client.stdout if stdout else self.owner.client.stderr

    def commit(
        self,
        repository: str | None = None,
        tag: str | None = None,
        *,
        conf: dict[str, object] | None = None,
        **kwargs: object,
    ) -> FakeImage:
        conf_dict = conf or {}
        self.owner.client.commit_calls.append((repository, tag, conf_dict))
        raw_labels = conf_dict.get("Labels")
        conf_labels = raw_labels if isinstance(raw_labels, dict) else {}
        labels = {**self.attrs["Config"]["Labels"], **conf_labels}
        image = FakeImage(
            "sha256:" + "3" * 64,
            tags=(f"{repository}:{tag}",),
            labels=labels,
            parent=self.attrs["Image"],
        )
        self.owner.client.images.objects[image.id] = image
        if self.owner.client.unexpected_image:
            extra = FakeImage("sha256:" + "4" * 64)
            self.owner.client.images.objects[extra.id] = extra
        return image

    def remove(self, *, force: bool = False, v: bool = False, **kwargs: object) -> None:
        self.remove_calls.append((force, v, self.reload_count))
        assert force is True and v is False
        if self.owner.client.fail_container_cleanup:
            raise FakeApiError(self.owner.client.cleanup_explanation)
        if not self.owner.client.leave_container_after_remove:
            self.owner.client.removed_containers.append(self)
            self.owner.objects.pop(self.id)


class FakeContainers(ContainerCollection):
    client: FakeClient

    def __init__(self, client: FakeClient) -> None:
        self.client = client
        self.objects: dict[str, FakeContainer] = {}
        self.create_calls: list[tuple[str, tuple[object, ...], dict[str, str], str, dict[str, object]]] = []

    def list(
        self, all: bool = False, before: str | None = None,
        filters: dict[str, str | _list[str] | bool] | None = None, limit: int = -1,
        since: str | None = None, sparse: bool = False,
        ignore_removed: bool = False,
    ) -> _list[Container]:
        del all, before, filters, limit, since, sparse, ignore_removed
        return _list(self.objects.values())

    def create(self, *args: object, **kwargs: object) -> FakeContainer:
        raw_image = args[0] if args else kwargs.get("image", "")
        image_id = raw_image if isinstance(raw_image, str) else str(getattr(raw_image, "id", raw_image))
        raw_cmd = args[1] if len(args) > 1 else kwargs.get("command")
        assert isinstance(raw_cmd, list) and raw_cmd[0] == "-c"
        raw_labels = kwargs.get("labels")
        labels_dict: dict[str, str] = dict(raw_labels) if isinstance(raw_labels, Mapping) else {}
        name = str(kwargs.get("name", "container-1"))
        options = dict(kwargs)
        assert options.get("entrypoint") == ["python"]
        assert options.get("network_mode") in {"none", "bridge"}
        self.create_calls.append((image_id, tuple(raw_cmd), labels_dict, name, options))
        identity = "1" * 64
        container = FakeContainer(
            self, identity, image_id, labels_dict, name=name,
            network_mode=str(options.get("network_mode", "none")),
        )
        self.objects[identity] = container
        return container

    def get(self, *args: object, **kwargs: object) -> FakeContainer:
        identity = str(args[0]) if args else str(kwargs.get("key", ""))
        for container in self.objects.values():
            if container.attrs["Name"] == f"/{identity}":
                return container
        try:
            return self.objects[identity]
        except KeyError as error:
            raise NotFound(identity) from error


class FakeNetwork(Network):
    def __init__(self, network_id: str, attrs: dict[str, object]) -> None:
        self._id, self.attrs = network_id, attrs

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
        if name != "bridge" or not self.client.bridge_available:
            raise NotFound(name)
        attrs = {
            "Id": BRIDGE_ID, "Name": "bridge", "Driver": "bridge", "Scope": "local",
            "Internal": False, "Options": {"com.docker.network.bridge.default_bridge": "true"},
        }
        return FakeNetwork(network_id=BRIDGE_ID, attrs=attrs)

    def create(self, *args: object, **kwargs: object) -> FakeNetwork:
        raise AssertionError("custom network creation is prohibited")


class FakeVolumes(VolumeCollection):
    def __init__(self, client: FakeClient) -> None:
        self.client = client

    def list(self, *args: object, **kwargs: object) -> list[Volume]:
        return []


class FakeApi(APIClient):
    def __init__(self, client: FakeClient) -> None:
        self._client = client

    def history(self, resource_id: str) -> list[dict[str, object]]:
        return [{"Id": resource_id, "CreatedBy": self._client.images.get(resource_id).created_by}]


class FakeClient(DockerClient):
    def __init__(self) -> None:
        self.bridge_available: bool = True
        self.wait_status, self.stdout, self.stderr = 0, b"", b""
        self.fail_container_cleanup, self.leave_container_after_remove = False, False
        self.cleanup_explanation = "container removal already in progress: private detail"
        self.wait_leaves_running, self.stop_leaves_running = False, False
        self.normalize_bridge_mode_after_wait, self.unexpected_image = False, False
        self.removed_containers: list[FakeContainer] = []
        self.commit_calls: list[tuple[str | None, str | None, dict[str, object]]] = []
        self._images = FakeImages()
        self._containers = FakeContainers(self)
        self._volumes = FakeVolumes(self)
        self._networks = FakeNetworks(self)
        self.api = FakeApi(self)

    @property
    def images(self) -> FakeImages:
        return self._images

    @property
    def containers(self) -> FakeContainers:
        return self._containers

    @property
    def volumes(self) -> FakeVolumes:
        return self._volumes

    @property
    def networks(self) -> FakeNetworks:
        return self._networks

    def info(self) -> dict[str, object]:
        return {"Architecture": "arm64"}


class FakeResourceRun(TestResourceRun):
    def __init__(self, ledger: ResourceLedger, materialization_manifest_path: Path) -> None:
        self.ledger = ledger
        self.materialization_manifest_path = materialization_manifest_path


def make_fake_client() -> FakeClient:
    return FakeClient()


def _materializer(tmp_path: Path) -> tuple[RuntimeImageMaterializer, FakeClient]:
    ledger = ResourceLedger.create(
        tmp_path / "direct-ledger.json",
        RunIdentity("repo-map", "TEST-IMAGE-LIFECYCLE1-R1-INTERMEDIATE1", "run-2"),
    )
    client = make_fake_client()
    resource_run = FakeResourceRun(ledger, tmp_path / "materialization-direct.json")
    return RuntimeImageMaterializer(resource_run, client), client


def _intermediate_chain(client: FakeClient) -> tuple[FakeImage, FakeImage, FakeImage]:
    first = FakeImage("sha256:" + "1" * 64, parent=BASE_ID, created_by="install")
    second = FakeImage(
        "sha256:" + "2" * 64, labels={"org.repomap.test.managed": "true"}, parent=first.id, created_by="label",
    )
    final = FakeImage(
        "sha256:" + "3" * 64, tags=("repomap-test-runtime:final",), labels={"org.repomap.test.managed": "true"}, parent=second.id,
    )
    client.images.objects.update({item.id: item for item in (first, second, final)})
    return first, second, final


def _failed_proof_image(
    client: FakeClient,
    *,
    tags: tuple[str, ...] = (PROOF_TAG,),
    labels: dict[str, str] | None = None,
    parent: str = BASE_ID,
) -> FakeImage:
    durable = {
        "org.repomap.test.managed": "true", "org.repomap.test.image.class": "runtime-cache",
        "org.repomap.test.image.schema": "1", "org.repomap.test.repository": "repo-map",
        "org.repomap.test.runtime-fingerprint": PROOF_FINGERPRINT,
    }
    image = FakeImage(PROOF_ID, tags=tags, labels=labels or {**durable, **TRANSIENT_LABELS}, parent=parent)
    client.images.objects[image.id] = image
    return image
