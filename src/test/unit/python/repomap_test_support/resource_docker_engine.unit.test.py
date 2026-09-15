"""TEST-HYGIENE1 Docker SDK projection and cleanup contracts."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from repomap_test_support.resource_docker_engine import DockerSdkApi
from repomap_test_support.resource_ledger import ResourceKind


def test_sdk_container_cleanup_does_not_remove_unregistered_volumes():
    container = Mock()
    containers = SimpleNamespace(get=Mock(return_value=container))
    client = SimpleNamespace(containers=containers)

    DockerSdkApi(client).remove(ResourceKind.DOCKER_CONTAINER, "container-1")

    container.remove.assert_called_once_with(force=True, v=False)


def test_sdk_container_mount_projection_is_order_independent():
    first = SimpleNamespace(
        id="container-1",
        attrs={
            "Config": {"Labels": {}},
            "Image": "sha256:image",
            "Mounts": [{"Source": "/z"}, {"Name": "a-volume"}],
        },
    )
    second = SimpleNamespace(
        id="container-1",
        attrs={
            "Config": {"Labels": {}},
            "Image": "sha256:image",
            "Mounts": [{"Name": "a-volume"}, {"Source": "/z"}],
        },
    )

    assert DockerSdkApi._container(first) == DockerSdkApi._container(second)


def test_sdk_tag_observation_keeps_exact_image_and_all_tag_references():
    image = SimpleNamespace(
        id="image-1",
        tags=["phase:test", "shared:tag"],
        attrs={"Config": {"Labels": {}}},
    )
    client = SimpleNamespace(images=SimpleNamespace(get=Mock(return_value=image)))

    observed = DockerSdkApi(client).inspect(ResourceKind.DOCKER_TAG, "phase:test")

    assert observed is not None
    assert observed.image_id == "image-1"
    assert observed.references == ("phase:test", "shared:tag")


def test_sdk_refuses_to_infer_buildx_objects_from_engine_absence():
    api = DockerSdkApi(SimpleNamespace())

    with pytest.raises(NotImplementedError, match="Buildx ownership"):
        api.list_objects(ResourceKind.BUILDX_BUILDER)
    with pytest.raises(NotImplementedError, match="Buildx ownership"):
        api.inspect(ResourceKind.BUILD_HISTORY_RECORD, "history-1")
