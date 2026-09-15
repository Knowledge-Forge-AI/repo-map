"""Authorization ticket boundaries, lifecycle, and expiration tests."""

from __future__ import annotations

import subprocess
import pytest
from docker.api.build import BuildApiMixin
from docker.api.image import ImageApiMixin

from repomap_test_support.resource_docker_mediation import (
    LOW_LEVEL_PULL_ROUTES,
    CanonicalDockerAuthority,
    DockerOperationRefused,
)
from repomap_test_support.resource_docker_mediation_isolation import (
    ambient_authorities_suspended,
)
from repomap_test_support.resource_docker_operations import (
    DockerAuthorityClass,
    DockerOperationJournal,
    DockerOperationKind,
    DockerOperationResult,
    JOURNAL_FILENAME,
)


@pytest.fixture(autouse=True)
def pristine_mediation():
    with ambient_authorities_suspended():
        yield


@pytest.fixture
def authority(tmp_path, pristine_mediation):
    subject = CanonicalDockerAuthority(
        DockerOperationJournal(tmp_path / JOURNAL_FILENAME, run_id="run-1")
    )
    subject.install()
    try:
        yield subject
    finally:
        subject.uninstall()


def _make_authority(directory, name: str) -> CanonicalDockerAuthority:
    directory.mkdir(parents=True, exist_ok=True)
    return CanonicalDockerAuthority(
        DockerOperationJournal(directory / JOURNAL_FILENAME, run_id=name)
    )


def _mediated_callables() -> list:
    targets = [
        (ImageCollection, "build"),
        (ImageCollection, "pull"),
        (BuildApiMixin, "build"),
        *((ImageApiMixin, name) for name in LOW_LEVEL_PULL_ROUTES),
    ]
    return [getattr(target, name) for target, name in targets]


from collections.abc import Generator
from docker import APIClient, DockerClient
from docker.models.images import Image, ImageCollection


class Engine(APIClient):
    """Stands in for ``client.api`` so a bypass would be visible, not harmless."""

    calls: list[str]

    def __init__(self) -> None:
        self.calls = []

    def build(
        self,
        path: str | None = None,
        tag: str | None = None,
        *args: object,
        **kwargs: object,
    ) -> Generator[bytes, None, None]:
        self.calls.append("build")
        def chunks() -> Generator[bytes, None, None]:
            yield b"sha256:built"

        return chunks()

    def pull(self, *args: object, **kwargs: object) -> tuple[()]:
        self.calls.append("pull")
        return ()


class Daemon(ImageCollection, DockerClient):
    """Shaped like a real ``ImageCollection``: a collection bound to a client."""

    api: Engine
    client: Daemon

    def __init__(self) -> None:
        self.api = Engine()
        self.client = self

    @property
    def calls(self) -> list[str]:
        return self.api.calls

    def get(self, reference: str) -> Image:
        return self.prepare_model({"Id": reference})

def test_obs1_recover4_pull_nested_in_an_authorized_build_is_still_refused(
    tmp_path, monkeypatch
) -> None:
    """Re-entrancy must not become a blanket pass for a different operation.

    While an authorized build is in flight the thread holds a build ticket
    only. A pull issued from inside that build is a distinct image
    acquisition, so it has to be journalled and refused rather than inheriting
    the build's pass-through. An unscoped in-flight gate would run it
    unmediated and unjournalled.
    """
    from docker.models.images import ImageCollection

    pulled: list[str] = []

    def high_build(inner, **kwargs):
        # A build that reaches for a base image mid-flight, which is the
        # realistic shape of an implicit pull.
        ImageCollection.pull(inner, "busybox")
        return "sha256:built"

    def high_pull(inner, *args, **kwargs):
        pulled.append("pull")
        return "sha256:pulled"

    monkeypatch.setattr(ImageCollection, "build", high_build)
    monkeypatch.setattr(ImageCollection, "pull", high_pull)
    subject = CanonicalDockerAuthority(
        DockerOperationJournal(tmp_path / JOURNAL_FILENAME, run_id="run-1")
    )
    subject.install()
    try:
        with subject.authorize(
            kind=DockerOperationKind.MANAGED_RUNTIME_LOGICAL_BUILD,
            authority=DockerAuthorityClass.MANAGED_TEST_RUNTIME,
            owner="TestImageManager",
            mechanism="managed-runtime-materialization",
            request="repomap-test-runtime:x",
        ) as ticket:
            with pytest.raises(DockerOperationRefused):
                ImageCollection.build(Daemon(), path="/tmp/context")
            subject.complete(ticket)
    finally:
        subject.uninstall()

    assert pulled == []
    counters = subject.journal.derive_counters()
    assert counters["unmanaged_pull_count"] == 1
    assert counters["managed_external_base_pull_count"] == 0


def test_obs1_recover1_authorized_operation_that_raises_stays_counted(
    authority,
) -> None:
    from docker.models.images import ImageCollection

    def explode(**kwargs):
        raise OSError("engine refused")

    daemon = Daemon()
    setattr(daemon.api, "build", explode)

    with pytest.raises(OSError):
        with authority.authorize(
            kind=DockerOperationKind.MANAGED_RUNTIME_LOGICAL_BUILD,
            authority=DockerAuthorityClass.MANAGED_TEST_RUNTIME,
            owner="TestImageManager",
            mechanism="managed-runtime-materialization",
            request="repomap-test-runtime:x",
        ):
            ImageCollection.build(daemon, path="/tmp/context")

    (event,) = authority.journal.events()
    assert event.result is DockerOperationResult.FAILED
    assert event.failure_category == "authorized_operation_raised"
    assert (
        authority.journal.derive_counters()["managed_test_runtime_image_build_count"]
        == 1
    )


def test_obs1_recover1_a_ticket_does_not_authorize_a_different_operation(
    authority,
) -> None:
    from docker.models.images import ImageCollection

    daemon = Daemon()

    with authority.authorize(
        kind=DockerOperationKind.DOCKER_PULL,
        authority=DockerAuthorityClass.MANAGED_EXTERNAL_BASE,
        owner="TestImageManager",
        mechanism="docker-sdk-high",
        request="repo@sha256:abc",
    ) as ticket:
        with pytest.raises(DockerOperationRefused):
            ImageCollection.build(daemon, path="/tmp/context")
        authority.complete(ticket)

    assert daemon.calls == []
    counters = authority.journal.derive_counters()
    assert counters["unmanaged_build_count"] == 1


def test_obs1_recover1_authorization_expires_with_its_scope(authority) -> None:
    from docker.models.images import ImageCollection

    daemon = Daemon()
    with authority.authorize(
        kind=DockerOperationKind.DOCKER_PULL,
        authority=DockerAuthorityClass.MANAGED_EXTERNAL_BASE,
        owner="TestImageManager",
        mechanism="docker-sdk-high",
        request="repo@sha256:abc",
    ) as ticket:
        authority.complete(ticket)

    with pytest.raises(DockerOperationRefused):
        ImageCollection.pull(daemon, "repo@sha256:abc")

    assert daemon.calls == []
    # Naming the journal is what makes this a claim about ``authority``. A bare
    # ``raises`` is satisfied by any live authority, including an ambient one.
    assert authority.journal.derive_counters()["unmanaged_pull_count"] == 1


def test_obs1_recover1_forbidden_authority_cannot_be_pre_authorized(
    authority,
) -> None:
    with pytest.raises(ValueError, match="forbidden authority"):
        with authority.authorize(
            kind=DockerOperationKind.DOCKER_BUILD,
            authority=DockerAuthorityClass.UNMANAGED_FORBIDDEN,
            owner="anyone",
            mechanism="docker-sdk-high",
            request="path=/tmp",
        ):
            pass


def test_obs1_recover1_uninstall_restores_every_patched_route(tmp_path) -> None:
    from docker.api.build import BuildApiMixin
    from docker.api.image import ImageApiMixin
    from docker.models.images import ImageCollection

    originals = [
        (ImageCollection, "build"),
        (ImageCollection, "pull"),
        (BuildApiMixin, "build"),
        *((ImageApiMixin, name) for name in LOW_LEVEL_PULL_ROUTES),
        (subprocess.Popen, "__init__"),
    ]
    before = [getattr(target, name) for target, name in originals]
    subject = CanonicalDockerAuthority(
        DockerOperationJournal(tmp_path / JOURNAL_FILENAME, run_id="run-1")
    )

    subject.install()
    patched = [getattr(target, name) for target, name in originals]
    subject.uninstall()

    assert all(a is not b for a, b in zip(before, patched))
    assert all(
        getattr(target, name) is original
        for (target, name), original in zip(originals, before)
    )


def test_obs1_recover1_double_install_is_refused(authority) -> None:
    with pytest.raises(RuntimeError, match="already installed"):
        authority.install()


