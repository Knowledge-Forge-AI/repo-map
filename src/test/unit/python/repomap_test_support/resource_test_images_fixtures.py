from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import TypedDict

import pytest

from repomap_test_support.resource_ledger import ResourceLedger, RunIdentity
from repomap_test_support.resource_docker_boundary import RunWideDockerBoundary
from repomap_test_support.resource_docker_mediation import CanonicalDockerAuthority
from repomap_test_support.resource_docker_operations import DockerOperationJournal
from repomap_test_support.resource_test_images import (
    TestImageManager as ImageManager,
)


BASE_ID = "sha256:" + "b" * 64
BRIDGE_ID = "d" * 64
BASE_REFERENCE = "python:3.12-slim-bookworm@sha256:" + "c" * 64
BASE_CANONICAL_REFERENCE = "python@sha256:" + "c" * 64


class NotFound(Exception):
    pass


class ImageAttrs(TypedDict):
    Created: str
    Size: int
    RepoDigests: list[str]
    Architecture: str
    Config: dict[str, dict[str, str]]


class FakeImage:
    def __init__(
        self,
        identity: str,
        *,
        tags: tuple[str, ...] = (),
        labels: dict[str, str] | None = None,
        created: str = "2026-08-16T12:00:00Z",
        repo_digests: tuple[str, ...] = (),
        architecture: str = "arm64",
    ) -> None:
        self.id = identity
        self.tags = list(tags)
        self.attrs: ImageAttrs = {
            "Created": created,
            "Size": 123,
            "RepoDigests": list(repo_digests),
            "Architecture": architecture,
            "Config": {"Labels": dict(labels or {})},
        }


class FakeImages:
    def __init__(self, images: tuple[FakeImage, ...]) -> None:
        self.objects = {image.id: image for image in images}
        self.build_calls: list[dict] = []
        self.runtime_commit_calls: list[tuple] = []
        self.pull_calls: list[tuple] = []
        self.remove_calls: list[tuple[str, bool, bool]] = []

    def list(self, all: bool = False):
        del all
        return list(self.objects.values())

    def get(self, reference: str):
        if reference in self.objects:
            return self.objects[reference]
        for image in self.objects.values():
            if reference in image.tags or reference in image.attrs["RepoDigests"]:
                return image
        raise NotFound(reference)

    def build(self, **kwargs):
        self.build_calls.append(kwargs)
        identity = "sha256:" + f"{len(self.build_calls):064x}"
        image = FakeImage(
            identity,
            tags=(kwargs["tag"],),
            labels=kwargs["labels"],
            created=f"2026-08-16T12:00:0{len(self.build_calls)}Z",
        )
        self.objects[identity] = image
        return image, [{"stream": "public build output"}]

    def pull(self, *args, **kwargs):
        self.pull_calls.append((args, kwargs))
        raise AssertionError("pull-on-miss is disabled")

    def commit_runtime(self, repository, tag, conf):
        self.runtime_commit_calls.append((repository, tag, conf))
        labels = dict(conf["Labels"])
        identity = "sha256:" + f"{len(self.runtime_commit_calls):064x}"
        image = FakeImage(identity, tags=(f"{repository}:{tag}",), labels=labels)
        self.objects[identity] = image
        return image

    def remove(self, identity: str, *, force: bool, noprune: bool):
        self.remove_calls.append((identity, force, noprune))
        if identity not in self.objects:
            raise NotFound(identity)
        self.objects.pop(identity)


class FakeContainers:
    def __init__(self, client) -> None:
        self.client = client
        self.objects: dict[str, SimpleNamespace] = {}
        self.create_calls: list[tuple[str, tuple[str, ...], dict[str, str], dict[str, str | bool | dict[str, str]]]] = []
        self.image_references: dict[str, set[str]] = {}

    def list(self, all: bool = False):
        del all
        containers = list(self.objects.values())
        for image_id, identities in self.image_references.items():
            for identity in identities:
                containers.append(
                    SimpleNamespace(
                        id=identity,
                        image=SimpleNamespace(id=image_id),
                        attrs={"Config": {"Labels": {}}, "Mounts": [], "Image": image_id},
                    )
                )
        return containers

    def create(self, image, command, *, labels, name, **options):
        self.create_calls.append((image, tuple(command), dict(labels), dict(options)))
        identity = f"{len(self.objects) + 1:064x}"
        container = SimpleNamespace(
            id=identity, image=SimpleNamespace(id=image),
            attrs={
                "Config": {"Labels": labels},
                "Mounts": [],
                "Image": image,
                "Name": f"/{name}",
                "NetworkSettings": {
                    "Networks": {"bridge": {"NetworkID": BRIDGE_ID}}
                },
                "HostConfig": {
                    "AutoRemove": False,
                    "NetworkMode": options["network_mode"],
                    "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0},
                },
                "State": {
                    "Status": "exited",
                    "Running": False,
                    "Paused": False,
                    "Restarting": False,
                    "Dead": False,
                    "ExitCode": 0,
                },
            },
        )
        container.reload = lambda: None
        container.start = lambda: None
        container.wait = lambda timeout: {"StatusCode": 0}
        container.stop = lambda timeout: None
        container.logs = lambda *, stdout, stderr: b""
        container.commit = lambda **kwargs: self.client.images.commit_runtime(**kwargs)
        container.remove = lambda **kwargs: self.objects.pop(identity)
        self.objects[identity] = container
        return container

    def get(self, identity):
        for container in self.objects.values():
            if container.attrs.get("Name") == f"/{identity}":
                return container
        if identity not in self.objects:
            raise NotFound(identity)
        return self.objects[identity]


class FakeClient:
    def __init__(self, images: tuple[FakeImage, ...]) -> None:
        self.images = FakeImages(images)
        self.containers = FakeContainers(self)
        self.volumes = SimpleNamespace(list=lambda: [])
        bridge = SimpleNamespace(
            id=BRIDGE_ID,
            attrs={
                "Id": BRIDGE_ID,
                "Name": "bridge",
                "Driver": "bridge",
                "Scope": "local",
                "Internal": False,
                "Options": {"com.docker.network.bridge.default_bridge": "true"},
            },
            reload=lambda: None,
        )
        self.networks = SimpleNamespace(
            get=lambda name: bridge if name == "bridge" else (_ for _ in ()).throw(NotFound(name)),
            create=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("custom network creation is prohibited")
            ),
        )

    def info(self):
        return {"Architecture": "arm64"}


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    root.joinpath("pyproject.toml").write_text(
        """[project]
name = "fixture"
version = "0.1"
dependencies = ["psycopg[binary]==3.2.12", "typing-extensions==4.16.0"]
""",
        encoding="utf-8",
    )
    return root


_INSTALLED: list[CanonicalDockerAuthority] = []


@pytest.fixture(autouse=True)
def _uninstall_authorities():
    yield
    while _INSTALLED:
        _INSTALLED.pop().uninstall()


def _installed_authority(ledger) -> CanonicalDockerAuthority:
    """Boundaries require a live observer, so zeros have an observed population."""
    authority = CanonicalDockerAuthority(DockerOperationJournal.for_ledger(ledger))
    authority.install()
    _INSTALLED.append(authority)
    return authority


def _resource_run(tmp_path: Path):
    ledger = ResourceLedger.create(
        tmp_path / "ledger.json",
        RunIdentity("repo-map", "TEST-IMAGE-LIFECYCLE1", "run-1"),
    )
    return SimpleNamespace(
        ledger=ledger,
        materialization_manifest_path=tmp_path / "materialization.json",
    )


def _manager(
    tmp_path: Path,
    images: tuple[FakeImage, ...] | None = None,
    *,
    with_boundary: bool = False,
    include_base: bool = True,
    recipe_schema: int = 1,
):
    base = FakeImage(
        BASE_ID,
        repo_digests=(BASE_CANONICAL_REFERENCE,),
        created="2026-08-01T00:00:00Z",
    )
    initial = ((base,) if include_base else ()) + tuple(images or ())
    client = FakeClient(initial)
    resource_run = _resource_run(tmp_path)
    boundary = (
        RunWideDockerBoundary(
            resource_run,
            client,
            authority=_installed_authority(resource_run.ledger),
        )
        if with_boundary
        else None
    )
    manager = ImageManager(
        repo_root=_project(tmp_path),
        resource_run=resource_run,
        client=client,
        base_reference=BASE_REFERENCE,
        python_base_family="python:3.12-slim-bookworm",
        python_version="3.12.13",
        psycopg_release_version="3.2.12",
        runtime_extras=(),
        recipe_schema=recipe_schema,
        boundary=boundary,
        probe=lambda _identity: None,
    )
    return manager, client


def _runtime_labels(fingerprint: str, *, repository: str = "repo-map"):
    return {
        "org.repomap.test.managed": "true",
        "org.repomap.test.image.class": "runtime-cache",
        "org.repomap.test.image.schema": "1",
        "org.repomap.test.runtime-fingerprint": fingerprint,
        "org.repomap.test.repository": repository,
    }
