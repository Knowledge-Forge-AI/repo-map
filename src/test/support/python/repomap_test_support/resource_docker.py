"""Exact Docker ownership cross-checks for one test resource ledger."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol, Sequence

from repomap_test_support.resource_ledger import (
    CleanupResult,
    FinalPresence,
    ResourceKind,
    ResourceLedger,
    ResourceLedgerError,
    RunIdentity,
)

LABEL_PREFIX = "org.repomap.test.resource"


class DockerOwnershipError(RuntimeError):
    """Exact current-run Docker ownership cannot be proved."""


@dataclass(frozen=True)
class DockerObject:
    kind: ResourceKind
    identity: str
    labels: Mapping[str, str]
    image_id: str | None = None
    references: tuple[str, ...] = ()
    volume_references: tuple[str, ...] = ()


class DockerApi(Protocol):
    def list_objects(self, kind: ResourceKind) -> Sequence[DockerObject]: ...

    def inspect(self, kind: ResourceKind, identity: str) -> DockerObject | None: ...

    def remove(self, kind: ResourceKind, identity: str) -> None: ...

    def image_references(self, image_id: str) -> set[str]: ...

    def volume_references(self, volume_id: str) -> set[str]: ...


@dataclass(frozen=True)
class DockerBaseline:
    identities: Mapping[ResourceKind, frozenset[str]]
    snapshots: Mapping[ResourceKind, Mapping[str, DockerObject]]

    @classmethod
    def capture(
        cls,
        api: DockerApi,
        *,
        kinds: Sequence[ResourceKind],
    ) -> "DockerBaseline":
        selected = tuple(ResourceKind(kind) for kind in kinds)
        if not selected:
            raise DockerOwnershipError("Docker baseline requires explicit kinds")
        snapshots = {}
        for kind in selected:
            observed = tuple(api.list_objects(kind))
            snapshots[kind] = {item.identity: item for item in observed}
        identities = {
            kind: frozenset(items)
            for kind, items in snapshots.items()
        }
        return cls(identities, snapshots)

    def contains(self, kind: ResourceKind, identity: str) -> bool:
        return identity in self.identities.get(kind, frozenset())


_DOCKER_KINDS = (
    ResourceKind.DOCKER_CONTAINER,
    ResourceKind.DOCKER_IMAGE,
    ResourceKind.DOCKER_TAG,
    ResourceKind.DOCKER_NETWORK,
    ResourceKind.DOCKER_VOLUME,
    ResourceKind.BUILDX_BUILDER,
    ResourceKind.BUILDKIT_STATE_VOLUME,
    ResourceKind.BUILD_HISTORY_RECORD,
)

_REMAINING_FIELDS = {
    ResourceKind.DOCKER_CONTAINER: "phase_containers_remaining",
    ResourceKind.DOCKER_IMAGE: "phase_images_remaining",
    ResourceKind.DOCKER_TAG: "phase_tags_remaining",
    ResourceKind.DOCKER_NETWORK: "phase_networks_remaining",
    ResourceKind.DOCKER_VOLUME: "phase_volumes_remaining",
    ResourceKind.BUILDX_BUILDER: "phase_builders_remaining",
    ResourceKind.BUILDKIT_STATE_VOLUME: "phase_buildkit_state_volumes_remaining",
    ResourceKind.BUILD_HISTORY_RECORD: "phase_build_history_remaining",
}


def ownership_labels(
    identity: RunIdentity,
    *,
    role: str,
    retained: bool,
) -> dict[str, str]:
    return {
        f"{LABEL_PREFIX}.project": identity.project,
        f"{LABEL_PREFIX}.phase": identity.phase,
        f"{LABEL_PREFIX}.run_id": identity.run_id,
        f"{LABEL_PREFIX}.role": role,
        f"{LABEL_PREFIX}.retention": "retained" if retained else "transient",
    }


class DockerResourceOwner:
    """Requires baseline, Engine observation, labels, and ledger to agree."""

    def __init__(
        self,
        identity: RunIdentity,
        ledger: ResourceLedger,
        api: DockerApi,
        baseline: DockerBaseline,
    ) -> None:
        if ledger.identity != identity:
            raise DockerOwnershipError("Docker owner and ledger run identity differ")
        self.identity = identity
        self.ledger = ledger
        self.api = api
        self.baseline = baseline

    def register_created(
        self,
        kind: ResourceKind,
        identity: str,
        *,
        role: str,
    ) -> None:
        kind = ResourceKind(kind)
        if kind not in _DOCKER_KINDS:
            raise DockerOwnershipError("resource kind is not Docker-owned")
        if self.baseline.contains(kind, identity):
            raise DockerOwnershipError("pre-existing Docker object cannot be registered")
        observed = self.api.inspect(kind, identity)
        if observed is None:
            raise DockerOwnershipError("created Docker object is not observable")
        expected = ownership_labels(self.identity, role=role, retained=False)
        if any(observed.labels.get(key) != value for key, value in expected.items()):
            raise DockerOwnershipError("Docker ownership labels do not match the run")
        self.ledger.register(
            kind,
            identity,
            creation_owner=f"docker-resource-owner:{role}",
            created_before_run=False,
            creation_observed=True,
            cleanup_required=True,
        )

    def cleanup(self, kind: ResourceKind, identity: str) -> None:
        kind = ResourceKind(kind)
        try:
            record = self.ledger.get(kind, identity)
        except ResourceLedgerError as error:
            raise DockerOwnershipError("Docker object is absent from the ledger") from error
        owner_prefix = "docker-resource-owner:"
        if not record.creation_owner.startswith(owner_prefix) or not record.creation_observed:
            raise DockerOwnershipError("ledger does not prove Docker creation ownership")
        if self.baseline.contains(kind, identity):
            raise DockerOwnershipError("pre-existing Docker object is protected")
        observed = self.api.inspect(kind, identity)
        if observed is None:
            raise DockerOwnershipError("exact Docker object is absent before cleanup")
        expected_prefix = ownership_labels(
            self.identity,
            role=record.creation_owner.removeprefix(owner_prefix),
            retained=False,
        )
        if any(observed.labels.get(key) != value for key, value in expected_prefix.items()):
            raise DockerOwnershipError("Docker ownership labels changed before cleanup")
        self._protect_references(kind, observed)
        self.ledger.mark_cleanup_attempted(kind, identity)
        try:
            self.api.remove(kind, identity)
        except Exception as error:
            self.ledger.mark_cleanup_result(kind, identity, CleanupResult.FAILED)
            self.ledger.mark_final_presence(kind, identity, FinalPresence.PRESENT)
            raise DockerOwnershipError("exact Docker cleanup failed") from error
        final = self.api.inspect(kind, identity)
        if final is not None:
            self.ledger.mark_cleanup_result(kind, identity, CleanupResult.FAILED)
            self.ledger.mark_final_presence(kind, identity, FinalPresence.PRESENT)
            raise DockerOwnershipError("exact Docker object remains after cleanup")
        if kind is ResourceKind.DOCKER_TAG:
            if observed.image_id is None:
                self.ledger.mark_cleanup_result(kind, identity, CleanupResult.FAILED)
                self.ledger.mark_final_presence(kind, identity, FinalPresence.ABSENT)
                raise DockerOwnershipError("tag cleanup lacks exact image identity")
            if self.api.inspect(ResourceKind.DOCKER_IMAGE, observed.image_id) is None:
                self.ledger.mark_cleanup_result(kind, identity, CleanupResult.FAILED)
                self.ledger.mark_final_presence(kind, identity, FinalPresence.ABSENT)
                raise DockerOwnershipError("tag cleanup deleted the referenced image")
        self.ledger.mark_cleanup_result(kind, identity, CleanupResult.REMOVED)
        self.ledger.mark_final_presence(kind, identity, FinalPresence.ABSENT)

    def verify_preexisting_unchanged(self) -> None:
        """Read back every baselined identity before accepting teardown."""
        changed = set()
        for kind, expected in self.baseline.snapshots.items():
            current = {item.identity: item for item in self.api.list_objects(kind)}
            if any(current.get(identity) != item for identity, item in expected.items()):
                changed.add(kind)
        self.ledger.set_fact("pre_existing_objects_mutated", bool(changed))
        if changed:
            raise DockerOwnershipError("pre-existing Docker baseline changed")
        for kind in self.baseline.snapshots:
            for item in self.api.list_objects(kind):
                labels = item.labels
                owned = (
                    labels.get(f"{LABEL_PREFIX}.project") == self.identity.project
                    and labels.get(f"{LABEL_PREFIX}.phase") == self.identity.phase
                    and labels.get(f"{LABEL_PREFIX}.run_id") == self.identity.run_id
                )
                if not owned or self.baseline.contains(kind, item.identity):
                    continue
                try:
                    record = self.ledger.get(kind, item.identity)
                except ResourceLedgerError as error:
                    raise DockerOwnershipError(
                        "current-run Docker object is absent from the ledger"
                    ) from error
                if not record.creation_observed or record.created_before_run:
                    raise DockerOwnershipError(
                        "current-run Docker creation is not proved"
                    )

    def cleanup_builder(
        self,
        builder_id: str,
        *,
        container_id: str,
        state_volume_id: str,
    ) -> None:
        identities = (
            (ResourceKind.BUILDX_BUILDER, builder_id),
            (ResourceKind.DOCKER_CONTAINER, container_id),
            (ResourceKind.BUILDKIT_STATE_VOLUME, state_volume_id),
        )
        for kind, identity in identities:
            if self.api.inspect(kind, identity) is None:
                raise DockerOwnershipError("builder identity bundle is incomplete")
            try:
                self.ledger.get(kind, identity)
            except ResourceLedgerError as error:
                raise DockerOwnershipError("builder identity is absent from the ledger") from error
        for kind, identity in identities:
            self.cleanup(kind, identity)

    def observe_image_absent_from_missing_tag(
        self,
        tag: str,
        image_id: str,
    ) -> None:
        del tag
        if self.api.inspect(ResourceKind.DOCKER_IMAGE, image_id) is not None:
            raise DockerOwnershipError("exact image remains despite the missing tag")
        raise DockerOwnershipError("missing tag alone cannot prove exact image cleanup")

    @staticmethod
    def remaining_field(kind: ResourceKind) -> str:
        try:
            return _REMAINING_FIELDS[ResourceKind(kind)]
        except KeyError as error:
            raise DockerOwnershipError("resource kind has no Docker projection") from error

    def _protect_references(self, kind: ResourceKind, observed: DockerObject) -> None:
        if kind in {ResourceKind.DOCKER_IMAGE, ResourceKind.DOCKER_TAG}:
            image_id = observed.identity
            if kind is ResourceKind.DOCKER_TAG:
                if observed.image_id is None:
                    raise DockerOwnershipError("tag has no exact image identity")
                if len(observed.references) <= 1:
                    raise DockerOwnershipError("last image tag cannot be removed safely")
                image_id = observed.image_id
            references = self.api.image_references(image_id)
            pre_existing = self.baseline.identities.get(
                ResourceKind.DOCKER_CONTAINER, frozenset()
            )
            if references & set(pre_existing):
                raise DockerOwnershipError("pre-existing container references the image")
        if kind in {ResourceKind.DOCKER_VOLUME, ResourceKind.BUILDKIT_STATE_VOLUME}:
            references = self.api.volume_references(observed.identity)
            pre_existing = self.baseline.identities.get(
                ResourceKind.DOCKER_CONTAINER, frozenset()
            )
            if references & set(pre_existing):
                raise DockerOwnershipError("pre-existing container references the volume")
        if kind is ResourceKind.DOCKER_NETWORK:
            pre_existing = self.baseline.identities.get(
                ResourceKind.DOCKER_CONTAINER, frozenset()
            )
            if set(observed.references) & set(pre_existing):
                raise DockerOwnershipError("pre-existing container uses the network")


__all__ = [
    "DockerApi",
    "DockerBaseline",
    "DockerObject",
    "DockerOwnershipError",
    "DockerResourceOwner",
    "LABEL_PREFIX",
    "ownership_labels",
]
