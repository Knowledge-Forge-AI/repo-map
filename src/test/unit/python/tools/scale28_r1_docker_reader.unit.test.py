from __future__ import annotations

from collections.abc import Mapping

import docker
import pytest
import requests

import scale12_resource_sampling as resource_sampling
from repomap_test_support.process_boundary import RecordingProcessBoundary
from scale12_resource_sampling import read_container_rss_upper_bound


class _Client:
    def __init__(
        self,
        stats: object | None = None,
        *,
        error: BaseException | None = None,
    ) -> None:
        self._stats = stats
        self._error = error
        self.timeout = 2.0
        self.calls: list[tuple[str, bool, bool, float]] = []
        self.closed = False

    @property
    def api_version(self) -> str:
        return "1.41"

    def version(self) -> object:
        return {}

    def info(self) -> object:
        return {}

    def inspect_container(self, container: str) -> object:
        return {}

    def stats(
        self, container: str, *, stream: bool = False, one_shot: bool = True
    ) -> object:
        self.calls.append((container, stream, one_shot, self.timeout))
        if self._error is not None:
            raise self._error
        return self._stats

    def close(self) -> None:
        self.closed = True


def _stats(usage: object = 900, inactive_file: object = 250) -> dict[str, object]:
    return {
        "memory_stats": {
            "usage": usage,
            "stats": {"inactive_file": inactive_file},
        }
    }


def _install_client(
    monkeypatch: pytest.MonkeyPatch,
    client: _Client,
    *,
    transport: str = "unix_socket",
) -> None:
    monkeypatch.setattr(
        resource_sampling,
        "_create_docker_api_client",
        lambda _runtime: (client, transport),
        raising=False,
    )


def test_container_reader_uses_exact_one_shot_stats_and_whole_reader_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _Client(_stats())
    _install_client(monkeypatch, client)
    times = iter((10.0, 10.5, 11.0))
    monkeypatch.setattr(resource_sampling.time, "monotonic", lambda: next(times))
    boundary = RecordingProcessBoundary().install(monkeypatch)

    assert read_container_rss_upper_bound("docker", "public-postgres") == 650
    assert client.calls == [("public-postgres", False, True, 1.5)]
    assert client.closed is True
    assert boundary.host_process_count == 0


@pytest.mark.parametrize(
    "payload",
    [
        {"memory_stats": {"usage": 900, "stats": {}}},
        {"memory_stats": {"stats": {"inactive_file": 250}}},
        {"memory_stats": {"usage": 100, "stats": {"inactive_file": 101}}},
        {"memory_stats": {"usage": True, "stats": {"inactive_file": 1}}},
        {"memory_stats": {"usage": 100, "stats": {"inactive_file": False}}},
        {"memory_stats": {"usage": 1.5, "stats": {"inactive_file": 1}}},
        {"memory_stats": []},
        {},
    ],
)
def test_container_reader_refuses_non_equivalent_or_unsupported_stats(
    monkeypatch: pytest.MonkeyPatch, payload: Mapping[str, object]
) -> None:
    client = _Client(payload)
    _install_client(monkeypatch, client)
    monkeypatch.setattr(resource_sampling.time, "monotonic", lambda: 10.0)

    assert read_container_rss_upper_bound("docker", "public-postgres") is None
    assert client.closed is True


@pytest.mark.parametrize(
    "error",
    [
        docker.errors.NotFound("missing"),
        docker.errors.APIError("daemon failed"),
        requests.exceptions.ReadTimeout("timed out"),
    ],
)
def test_container_reader_maps_sdk_and_transport_failures_and_closes(
    monkeypatch: pytest.MonkeyPatch, error: BaseException
) -> None:
    client = _Client(error=error)
    _install_client(monkeypatch, client)
    monkeypatch.setattr(resource_sampling.time, "monotonic", lambda: 10.0)

    assert read_container_rss_upper_bound("docker", "public-postgres") is None
    assert client.closed is True


def test_docker_client_uses_supported_environment_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructed: list[dict[str, object]] = []
    client = _Client(_stats())
    monkeypatch.setenv("DOCKER_HOST", "unix:///public/docker.sock")
    monkeypatch.setattr(
        resource_sampling,
        "kwargs_from_env",
        lambda environment=None: {"base_url": environment["DOCKER_HOST"]},
        raising=False,
    )
    def make_client(**kwargs: object) -> _Client:
        constructed.append(kwargs)
        return client

    monkeypatch.setattr(
        resource_sampling.docker,
        "APIClient",
        make_client,
    )

    opened = resource_sampling._create_docker_api_client("docker")

    assert opened == (client, "unix_socket")
    assert constructed == [
        {
            "base_url": "unix:///public/docker.sock",
            "timeout": 2.0,
            "version": "auto",
        }
    ]


def test_docker_client_uses_current_context_when_host_is_not_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _Client(_stats())
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.setattr(
        resource_sampling, "kwargs_from_env", lambda environment=None: {}, raising=False
    )
    monkeypatch.setattr(
        resource_sampling.ContextAPI,
        "kwargs_from_context",
        lambda environment=None: {"base_url": "unix:///public/context.sock"},
        raising=False,
    )
    monkeypatch.setattr(
        resource_sampling.docker, "APIClient", lambda **_kwargs: client
    )

    assert resource_sampling._create_docker_api_client("docker") == (
        client,
        "unix_socket",
    )


def test_explicit_context_overrides_docker_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _Client(_stats())
    monkeypatch.setenv("DOCKER_HOST", "unix:///wrong/docker.sock")
    monkeypatch.setenv("DOCKER_CONTEXT", "public-context")
    monkeypatch.setattr(
        resource_sampling,
        "kwargs_from_env",
        lambda environment=None: pytest.fail("DOCKER_HOST overrode explicit context"),
    )
    monkeypatch.setattr(
        resource_sampling.ContextAPI,
        "kwargs_from_context",
        lambda environment=None: {"base_url": "unix:///public/context.sock"},
    )
    monkeypatch.setattr(
        resource_sampling.docker, "APIClient", lambda **_kwargs: client
    )

    assert resource_sampling._create_docker_api_client("docker") == (
        client,
        "unix_socket",
    )


def test_podman_without_an_explicit_compatible_endpoint_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    monkeypatch.delenv("CONTAINER_HOST", raising=False)
    monkeypatch.setattr(
        resource_sampling.docker,
        "APIClient",
        lambda **_kwargs: pytest.fail("ambiguous Podman endpoint was opened"),
    )

    assert resource_sampling._create_docker_api_client("podman") is None


def test_podman_container_host_is_mapped_through_the_sdk_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _Client(_stats())
    observed_environment: dict[str, str] = {}
    monkeypatch.setenv("CONTAINER_HOST", "unix:///public/podman.sock")
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.setenv("DOCKER_CONTEXT", "unrelated-docker-context")

    def resolve(environment=None):
        observed_environment.update(environment)
        return {"base_url": environment["DOCKER_HOST"]}

    monkeypatch.setattr(
        resource_sampling, "kwargs_from_env", resolve, raising=False
    )
    monkeypatch.setattr(
        resource_sampling.ContextAPI,
        "kwargs_from_context",
        lambda **_kwargs: pytest.fail("Docker context overrode Podman endpoint"),
    )
    monkeypatch.setattr(
        resource_sampling.docker, "APIClient", lambda **_kwargs: client
    )

    assert resource_sampling._create_docker_api_client("podman") == (
        client,
        "unix_socket",
    )
    assert observed_environment["DOCKER_HOST"] == "unix:///public/podman.sock"
    assert "DOCKER_CONTEXT" not in observed_environment
