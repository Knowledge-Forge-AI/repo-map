"""Cross-authority isolation and ambient suspension mediation tests."""

from __future__ import annotations

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
    JOURNAL_FILENAME,
)


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

def test_obs1_recover4_a_ticket_never_authorizes_another_authoritys_guard(
    tmp_path,
) -> None:
    """Tickets are instance-local in both directions, so nesting cannot borrow.

    This deliberately reproduces the nested state the isolation fixture exists
    to remove, and pins the security property that makes isolation the only
    correct remedy: neither authority's ticket reaches the other's guard.
    """
    from docker.models.images import ImageCollection

    outer = _make_authority(tmp_path / "outer", "outer")
    subject = _make_authority(tmp_path / "subject", "subject")
    outer.install()
    try:
        subject.install()
        try:
            # The outer holds a pull ticket; the innermost guard is the
            # subject's, which owns no ticket and refuses.
            with outer.authorize(
                kind=DockerOperationKind.DOCKER_PULL,
                authority=DockerAuthorityClass.MANAGED_EXTERNAL_BASE,
                owner="TestImageManager",
                mechanism="docker-sdk-high",
                request="repo@sha256:abc",
            ) as ticket:
                with pytest.raises(DockerOperationRefused):
                    ImageCollection.pull(Daemon(), "repo@sha256:abc")
                outer.complete(ticket)

            # The subject holds a pull ticket; it passes its own guard and is
            # then refused by the outer guard it delegates to.
            with subject.authorize(
                kind=DockerOperationKind.DOCKER_PULL,
                authority=DockerAuthorityClass.MANAGED_EXTERNAL_BASE,
                owner="TestImageManager",
                mechanism="docker-sdk-high",
                request="repo@sha256:abc",
            ) as ticket:
                with pytest.raises(DockerOperationRefused):
                    ImageCollection.pull(Daemon(), "repo@sha256:abc")
                subject.complete(ticket)
        finally:
            subject.uninstall()
    finally:
        outer.uninstall()

    assert subject.journal.derive_counters()["unmanaged_pull_count"] == 1
    assert outer.journal.derive_counters()["unmanaged_pull_count"] == 1


def test_obs1_recover4_a_self_test_subject_is_isolated_from_a_run_wide_authority(
    tmp_path,
) -> None:
    """Isolation gives the self-test a real subject and returns the outer exactly.

    Attribution is proved by which journal received each event: the subject
    records both its authorized pull and its refusal, and the run-wide
    authority records nothing at all.
    """
    from docker.models.images import ImageCollection

    outer = _make_authority(tmp_path / "outer", "outer")
    outer.install()
    try:
        outer_callables = _mediated_callables()
        daemon = Daemon()

        with ambient_authorities_suspended() as suspended:
            assert suspended == (outer,)
            assert not outer.installed
            pristine = _mediated_callables()
            assert all(a is not b for a, b in zip(outer_callables, pristine))

            subject = _make_authority(tmp_path / "subject", "subject")
            subject.install()
            try:
                with subject.authorize(
                    kind=DockerOperationKind.DOCKER_PULL,
                    authority=DockerAuthorityClass.MANAGED_EXTERNAL_BASE,
                    owner="TestImageManager",
                    mechanism="docker-sdk-high",
                    request="repo@sha256:abc",
                ) as ticket:
                    ImageCollection.pull(daemon, "repo@sha256:abc")
                    subject.complete(ticket, image_ids=("sha256:base",))
                with pytest.raises(DockerOperationRefused):
                    ImageCollection.build(Daemon(), path="/tmp/context")
            finally:
                subject.uninstall()

        assert daemon.calls == ["pull"]
        counters = subject.journal.derive_counters()
        assert counters["managed_external_base_pull_count"] == 1
        assert counters["unmanaged_build_count"] == 1
        # The run-wide authority neither answered for nor observed any of it.
        assert outer.journal.events() == ()

        # Reinstalling builds fresh guard closures, so restoration is asserted
        # behaviourally rather than by callable identity: every route is
        # mediated again and the outer instance is the one now accounting.
        assert getattr(outer, "installed")
        restored = _mediated_callables()
        assert all(a is not b for a, b in zip(pristine, restored))
        with pytest.raises(DockerOperationRefused):
            ImageCollection.build(Daemon(), path="/tmp/context")
        assert outer.journal.derive_counters()["unmanaged_build_count"] == 1
        assert subject.journal.derive_counters()["unmanaged_build_count"] == 1
    finally:
        outer.uninstall()


def test_obs1_recover4_suspension_refuses_an_authority_with_work_in_flight(
    tmp_path,
) -> None:
    """Restoring mediation around a live operation would drop its in-flight state."""
    outer = _make_authority(tmp_path / "outer", "outer")
    outer.install()
    try:
        with outer.authorize(
            kind=DockerOperationKind.DOCKER_PULL,
            authority=DockerAuthorityClass.MANAGED_EXTERNAL_BASE,
            owner="TestImageManager",
            mechanism="docker-sdk-high",
            request="repo@sha256:abc",
        ) as ticket:
            with pytest.raises(RuntimeError, match="work in flight"):
                with ambient_authorities_suspended():
                    pass
            outer.complete(ticket)
        assert getattr(outer, "installed")
    finally:
        outer.uninstall()


def test_obs1_recover4_a_failed_install_leaves_no_registry_residue(tmp_path) -> None:
    """install()'s own error path reaches uninstall() on a partial instance."""
    from repomap_test_support.resource_docker_mediation import installed_authorities

    def explode(self) -> None:
        raise RuntimeError("boom")

    subject = _make_authority(tmp_path / "subject", "subject")
    before = _mediated_callables()
    with pytest.raises(RuntimeError, match="boom"):
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(CanonicalDockerAuthority, "_install_cli", explode)
            subject.install()

    assert not subject.installed
    assert subject not in installed_authorities()
    assert _mediated_callables() == before
