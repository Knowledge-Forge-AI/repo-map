"""Docker SDK adapter for exact resource-ledger observations and cleanup."""

from __future__ import annotations

from typing import Any, Iterable

from repomap_test_support.resource_docker import DockerObject
from repomap_test_support.resource_ledger import ResourceKind


class DockerSdkApi:
    """Project only Docker SDK identities into the closed ownership protocol."""

    def __init__(self, client: Any) -> None:
        self.client = client

    def list_objects(self, kind: ResourceKind) -> tuple[DockerObject, ...]:
        kind = ResourceKind(kind)
        if kind is ResourceKind.DOCKER_CONTAINER:
            return tuple(self._container(item) for item in self.client.containers.list(all=True))
        if kind is ResourceKind.DOCKER_IMAGE:
            return tuple(self._image(item) for item in self.client.images.list(all=True))
        if kind is ResourceKind.DOCKER_TAG:
            return tuple(self._tags(self.client.images.list(all=True)))
        if kind is ResourceKind.DOCKER_NETWORK:
            return tuple(self._network(item) for item in self.client.networks.list())
        if kind in {ResourceKind.DOCKER_VOLUME, ResourceKind.BUILDKIT_STATE_VOLUME}:
            return tuple(self._volume(item, kind) for item in self.client.volumes.list())
        if kind in {ResourceKind.BUILDX_BUILDER, ResourceKind.BUILD_HISTORY_RECORD}:
            raise NotImplementedError("Docker SDK does not expose exact Buildx ownership")
        raise ValueError("unsupported Docker resource kind")

    def inspect(self, kind: ResourceKind, identity: str) -> DockerObject | None:
        kind = ResourceKind(kind)
        try:
            if kind is ResourceKind.DOCKER_CONTAINER:
                return self._container(self.client.containers.get(identity))
            if kind is ResourceKind.DOCKER_IMAGE:
                return self._image(self.client.images.get(identity))
            if kind is ResourceKind.DOCKER_TAG:
                image = self.client.images.get(identity)
                return DockerObject(
                    kind,
                    identity,
                    self._image_labels(image),
                    image_id=image.id,
                    references=tuple(image.tags),
                )
            if kind is ResourceKind.DOCKER_NETWORK:
                return self._network(self.client.networks.get(identity))
            if kind in {ResourceKind.DOCKER_VOLUME, ResourceKind.BUILDKIT_STATE_VOLUME}:
                return self._volume(self.client.volumes.get(identity), kind)
        except Exception as error:
            if error.__class__.__name__ in {"NotFound", "ImageNotFound"}:
                return None
            raise
        if kind in {ResourceKind.BUILDX_BUILDER, ResourceKind.BUILD_HISTORY_RECORD}:
            raise NotImplementedError("Docker SDK does not expose exact Buildx ownership")
        raise ValueError("unsupported Docker resource kind")

    def remove(self, kind: ResourceKind, identity: str) -> None:
        kind = ResourceKind(kind)
        if kind is ResourceKind.DOCKER_CONTAINER:
            self.client.containers.get(identity).remove(force=True, v=False)
            return
        if kind in {ResourceKind.DOCKER_IMAGE, ResourceKind.DOCKER_TAG}:
            self.client.images.remove(identity, force=False, noprune=True)
            return
        if kind is ResourceKind.DOCKER_NETWORK:
            self.client.networks.get(identity).remove()
            return
        if kind in {ResourceKind.DOCKER_VOLUME, ResourceKind.BUILDKIT_STATE_VOLUME}:
            self.client.volumes.get(identity).remove(force=False)
            return
        raise ValueError("resource kind requires a purpose-owned cleanup adapter")

    def image_references(self, image_id: str) -> set[str]:
        references = set()
        for container in self.client.containers.list(all=True):
            try:
                if container.image.id == image_id:
                    references.add(container.id)
            except Exception as error:
                if error.__class__.__name__ in {"NotFound", "ImageNotFound"}:
                    continue
                raise
        return references

    def volume_references(self, volume_id: str) -> set[str]:
        references = set()
        for container in self.client.containers.list(all=True):
            mounts = container.attrs.get("Mounts") or []
            if any(
                mount.get("Name") == volume_id or mount.get("Source") == volume_id
                for mount in mounts
            ):
                references.add(container.id)
        return references

    @staticmethod
    def _container(container: Any) -> DockerObject:
        labels = container.attrs.get("Config", {}).get("Labels") or {}
        mounts = container.attrs.get("Mounts") or []
        references = tuple(
            sorted(
                str(mount.get("Name") or mount.get("Source"))
                for mount in mounts
                if mount.get("Name") or mount.get("Source")
            )
        )
        volume_references = tuple(
            sorted(
                str(mount.get("Name") or mount.get("Source"))
                for mount in mounts
                if str(mount.get("Type", "")).lower() == "volume"
                and (mount.get("Name") or mount.get("Source"))
            )
        )
        image_id = container.attrs.get("Image")
        return DockerObject(
            ResourceKind.DOCKER_CONTAINER,
            container.id,
            labels,
            image_id=image_id,
            references=references,
            volume_references=volume_references,
        )

    @classmethod
    def _image(cls, image: Any) -> DockerObject:
        return DockerObject(
            ResourceKind.DOCKER_IMAGE,
            image.id,
            cls._image_labels(image),
            references=tuple(image.tags),
        )

    @classmethod
    def _tags(cls, images: Iterable[Any]) -> Iterable[DockerObject]:
        for image in images:
            labels = cls._image_labels(image)
            for tag in image.tags:
                yield DockerObject(
                    ResourceKind.DOCKER_TAG,
                    tag,
                    labels,
                    image_id=image.id,
                    references=tuple(image.tags),
                )

    @staticmethod
    def _image_labels(image: Any) -> dict[str, str]:
        return dict(image.attrs.get("Config", {}).get("Labels") or {})

    @staticmethod
    def _network(network: Any) -> DockerObject:
        return DockerObject(
            ResourceKind.DOCKER_NETWORK,
            network.id,
            network.attrs.get("Labels") or {},
            references=tuple((network.attrs.get("Containers") or {}).keys()),
        )

    @staticmethod
    def _volume(volume: Any, kind: ResourceKind) -> DockerObject:
        return DockerObject(
            kind,
            volume.id,
            volume.attrs.get("Labels") or {},
        )


__all__ = ["DockerSdkApi"]
