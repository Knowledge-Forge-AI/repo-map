"""Process-wide mediation of every canonical Docker build and pull route."""

from __future__ import annotations

import subprocess

import pytest
from docker.api.build import BuildApiMixin
from docker.api.image import ImageApiMixin

from repomap_test_support.resource_docker_mediation import (
    LOW_LEVEL_PULL_ROUTES,
    CanonicalDockerAuthority,
    DockerOperationRefused,
    classify_container_cli,
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
    """Every self-test here needs the SDK classes unmediated before it patches.

    Under the canonical runner a run-wide authority is already installed, and an
    authority installed on top of it would delegate authorized calls into that
    outer guard, which holds no ticket and refuses. Without this the subject of
    each test is the ambient authority rather than the instance under test.
    """
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
    from docker.models.images import ImageCollection

    targets = [
        (ImageCollection, "build"),
        (ImageCollection, "pull"),
        (BuildApiMixin, "build"),
        *((ImageApiMixin, name) for name in LOW_LEVEL_PULL_ROUTES),
        (subprocess.Popen, "__init__"),
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


def test_obs1_recover1_high_level_build_is_refused_before_daemon_mutation(
    authority,
) -> None:
    from docker.models.images import ImageCollection

    daemon = Daemon()

    with pytest.raises(DockerOperationRefused, match="refused before daemon mutation"):
        ImageCollection.build(daemon, path="/tmp/context")

    assert daemon.calls == []
    assert authority.journal.derive_counters()["unmanaged_build_count"] == 1


def test_obs1_recover1_high_level_pull_is_refused_before_daemon_mutation(
    authority,
) -> None:
    from docker.models.images import ImageCollection

    daemon = Daemon()

    with pytest.raises(DockerOperationRefused):
        ImageCollection.pull(daemon, "busybox", tag="latest")

    assert daemon.calls == []
    assert authority.journal.derive_counters()["unmanaged_pull_count"] == 1


def test_obs1_recover1_low_level_api_build_cannot_bypass_the_high_level_guard(
    authority,
) -> None:
    engine = Engine()

    with pytest.raises(DockerOperationRefused):
        BuildApiMixin.build(engine, path="/tmp/context")

    assert engine.calls == []
    (event,) = authority.journal.events()
    assert event.mechanism == "docker-sdk-low"
    assert event.authority is DockerAuthorityClass.UNMANAGED_FORBIDDEN


@pytest.mark.parametrize("name", LOW_LEVEL_PULL_ROUTES)
def test_obs1_recover1_low_level_api_pull_routes_are_closed(authority, name) -> None:
    engine = Engine()
    setattr(engine, name, lambda *a, **k: engine.calls.append(name))

    with pytest.raises(DockerOperationRefused):
        getattr(ImageApiMixin, name)(engine, "busybox")

    assert engine.calls == []
    assert authority.journal.derive_counters()["unmanaged_pull_count"] == 1


def test_obs1_recover1_import_helpers_cannot_acquire_an_image(authority) -> None:
    """The ``import_image_from_*`` helpers all funnel through a closed route."""
    engine = Engine()

    with pytest.raises(DockerOperationRefused):
        engine.import_image_from_url("https://example.invalid/x.tar")

    assert engine.calls == []
    assert authority.journal.derive_counters()["unmanaged_pull_count"] == 1


def test_obs1_recover1_a_second_independent_client_is_also_mediated(
    authority,
) -> None:
    """Mediation is on the class, so another client instance inherits it."""
    from docker.models.images import ImageCollection

    first, second = Daemon(), Daemon()

    for daemon in (first, second):
        with pytest.raises(DockerOperationRefused):
            ImageCollection.build(daemon, path="/tmp/context")

    assert first.calls == [] and second.calls == []
    assert authority.journal.derive_counters()["unmanaged_build_count"] == 2


@pytest.mark.parametrize(
    ("argv", "kind"),
    [
        (["docker", "build", "."], DockerOperationKind.DOCKER_BUILD),
        (["docker", "pull", "busybox"], DockerOperationKind.DOCKER_PULL),
        (["docker", "buildx", "build", "."], DockerOperationKind.DOCKER_BUILD),
        (["docker", "compose", "build"], DockerOperationKind.DOCKER_BUILD),
        (["docker", "compose", "up", "--build"], DockerOperationKind.DOCKER_BUILD),
        (["docker", "image", "pull", "busybox"], DockerOperationKind.DOCKER_PULL),
        (["/usr/bin/podman", "build", "."], DockerOperationKind.DOCKER_BUILD),
        (["nerdctl", "pull", "busybox"], DockerOperationKind.DOCKER_PULL),
        (["docker", "builder", "build", "."], DockerOperationKind.DOCKER_BUILD),
        (["docker", "-H", "tcp://h:1", "build", "."], DockerOperationKind.DOCKER_BUILD),
        (
            ["docker", "--host", "tcp://h:1", "pull", "busybox"],
            DockerOperationKind.DOCKER_PULL,
        ),
        (["docker", "--context", "remote", "build", "."], DockerOperationKind.DOCKER_BUILD),
        (["docker", "--host=tcp://h:1", "build", "."], DockerOperationKind.DOCKER_BUILD),
        (
            ["docker", "-l", "debug", "builder", "build", "."],
            DockerOperationKind.DOCKER_BUILD,
        ),
    ],
)
def test_obs1_recover1_container_cli_build_and_pull_intents_are_classified(
    argv, kind
) -> None:
    assert classify_container_cli(argv) is kind


@pytest.mark.parametrize(
    "argv",
    [
        ["env", "docker", "build", "."],
        ["sh", "-c", "docker build ."],
        ["/bin/bash", "-lc", "docker pull busybox"],
        ["xargs", "docker", "pull"],
    ],
)
def test_obs1_recover4_wrapper_launched_builds_are_outside_the_closure_set(argv) -> None:
    """Characterizes the boundary of the claim rather than asserting closure.

    Only ``argv[0]`` names the runtime, so a wrapper process hides the intent.
    No canonical code path constructs these forms; the W1 CLI reachability
    audit records them as CANONICAL_NOT_REACHABLE, and the closure claim is
    scoped to direct runtime argv accordingly.
    """
    assert classify_container_cli(argv) is None


@pytest.mark.parametrize(
    "argv",
    [
        ["docker", "ps"],
        ["docker", "image", "inspect", "busybox"],
        ["docker", "buildx", "create", "--name", "x"],
        ["git", "pull"],
        ["make", "build"],
        [],
    ],
)
def test_obs1_recover1_unrelated_commands_are_not_attributed(argv) -> None:
    assert classify_container_cli(argv) is None


@pytest.mark.parametrize(
    "argv",
    [
        ["docker", "build", "."],
        ["docker", "pull", "busybox"],
        ["docker", "compose", "build"],
        ["docker", "compose", "up", "--build"],
    ],
)
def test_obs1_recover1_container_cli_operations_are_refused_before_spawn(
    authority, argv
) -> None:
    with pytest.raises(DockerOperationRefused, match="container-CLI"):
        subprocess.run(argv, capture_output=True)

    (event,) = authority.journal.events()
    assert event.mechanism == "container-cli"
    assert event.result is DockerOperationResult.REFUSED
    assert event.started is False


def test_obs1_recover1_unrelated_subprocesses_still_run(authority) -> None:
    result = subprocess.run(
        ["/bin/echo", "docker build"], capture_output=True, text=True
    )

    assert result.stdout.strip() == "docker build"
    assert authority.journal.events() == ()


def test_obs1_recover1_authorized_operation_yields_exactly_one_event(
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
        ImageCollection.pull(daemon, "repo@sha256:abc")
        authority.complete(ticket, image_ids=("sha256:base",))

    (event,) = authority.journal.events()
    assert daemon.calls == ["pull"]
    assert event.result is DockerOperationResult.SUCCEEDED
    assert authority.journal.derive_counters()["managed_external_base_pull_count"] == 1


def test_obs1_recover1_reentrant_low_level_call_does_not_double_count(
    tmp_path, monkeypatch
) -> None:
    """One logical operation stays one event even through both SDK layers."""
    from docker.models.images import ImageCollection

    calls: list[str] = []

    def low(inner, **kwargs):
        calls.append("low")
        return "sha256:built"

    def high(inner, **kwargs):
        calls.append("high")
        return BuildApiMixin.build(inner, **kwargs)

    # Both layers are replaced before install, so the authority mediates the
    # pair exactly as it mediates the real ones and the real bodies stay out.
    monkeypatch.setattr(ImageCollection, "build", high)
    monkeypatch.setattr(BuildApiMixin, "build", low)
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
            ImageCollection.build(Daemon(), path="/tmp/context")
            subject.complete(ticket)
    finally:
        subject.uninstall()

    assert calls == ["high", "low"]
    assert len(subject.journal.events()) == 1
