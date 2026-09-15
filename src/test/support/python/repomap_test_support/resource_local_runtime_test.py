"""Exact future teardown contract for deferred local-runtime build tests."""

from __future__ import annotations

import re
from dataclasses import dataclass

from repomap_test_support.resource_ledger import ResourceKind


class LocalRuntimeTestOwnershipError(RuntimeError):
    """Deferred test resources cannot be proved exact and test-owned."""


@dataclass(frozen=True, slots=True)
class LocalRuntimeTestCreationPlan:
    """Pre-creation Compose contract for a future authorized build test."""

    compose_project: str
    named_volume_ids: tuple[str, ...]
    postgres_data_mount_type: str = "tmpfs"
    postgres_data_target: str = "/var/lib/postgresql/data"

    def __post_init__(self) -> None:
        if re.fullmatch(r"[a-z0-9][a-z0-9_-]{2,62}", self.compose_project) is None:
            raise LocalRuntimeTestOwnershipError("Compose project identity is invalid")
        if (
            not self.named_volume_ids
            or len(set(self.named_volume_ids)) != len(self.named_volume_ids)
            or any(not identity for identity in self.named_volume_ids)
        ):
            raise LocalRuntimeTestOwnershipError("named-volume plan is invalid")
        if self.postgres_data_mount_type != "tmpfs":
            raise LocalRuntimeTestOwnershipError(
                "Postgres image-declared data volume must be prevented with tmpfs"
            )
        if self.postgres_data_target != "/var/lib/postgresql/data":
            raise LocalRuntimeTestOwnershipError("Postgres tmpfs target is invalid")


@dataclass(frozen=True, slots=True)
class LocalRuntimeTestManifest:
    """Exact IDs produced by one future explicitly authorized build test."""

    compose_project: str
    container_ids: tuple[str, ...]
    named_volume_ids: tuple[str, ...]
    created_image_ids: tuple[str, ...]
    created_tags: tuple[str, ...]
    creation_plan: LocalRuntimeTestCreationPlan

    def __post_init__(self) -> None:
        if re.fullmatch(r"[a-z0-9][a-z0-9_-]{2,62}", self.compose_project) is None:
            raise LocalRuntimeTestOwnershipError("Compose project identity is invalid")
        groups = (
            self.container_ids,
            self.named_volume_ids,
            self.created_image_ids,
            self.created_tags,
        )
        if any(not group or len(set(group)) != len(group) for group in groups):
            raise LocalRuntimeTestOwnershipError("owned Docker identity set is invalid")
        if any(not identity for group in groups for identity in group):
            raise LocalRuntimeTestOwnershipError("owned Docker identity is empty")
        if self.creation_plan.compose_project != self.compose_project:
            raise LocalRuntimeTestOwnershipError("creation and teardown projects differ")
        if self.creation_plan.named_volume_ids != self.named_volume_ids:
            raise LocalRuntimeTestOwnershipError("creation and teardown volumes differ")

    def register_and_teardown(self, owner) -> None:
        """Register all exact IDs, prevent anonymous volumes, then remove exactly."""
        roles = (
            (ResourceKind.DOCKER_CONTAINER, self.container_ids, "local-runtime-container"),
            (ResourceKind.DOCKER_VOLUME, self.named_volume_ids, "local-runtime-volume"),
            (ResourceKind.DOCKER_IMAGE, self.created_image_ids, "local-runtime-image"),
            (ResourceKind.DOCKER_TAG, self.created_tags, "local-runtime-tag"),
        )
        for kind, identities, role in roles:
            for identity in identities:
                owner.register_created(kind, identity, role=role)

        allowed_volumes = set(self.named_volume_ids)
        for identity in self.container_ids:
            observed = owner.api.inspect(ResourceKind.DOCKER_CONTAINER, identity)
            if observed is None:
                raise LocalRuntimeTestOwnershipError(
                    "exact local-runtime container is absent"
                )
            if observed.labels.get("com.docker.compose.project") != self.compose_project:
                raise LocalRuntimeTestOwnershipError(
                    "Compose project identity does not match the exact test project"
                )
            unexpected = set(observed.volume_references).difference(allowed_volumes)
            if unexpected:
                raise LocalRuntimeTestOwnershipError(
                    "anonymous or unowned local-runtime volume is present"
                )

        cleanup_order = (
            (ResourceKind.DOCKER_CONTAINER, self.container_ids),
            (ResourceKind.DOCKER_VOLUME, self.named_volume_ids),
            (ResourceKind.DOCKER_TAG, self.created_tags),
            (ResourceKind.DOCKER_IMAGE, self.created_image_ids),
        )
        for kind, identities in cleanup_order:
            for identity in identities:
                owner.cleanup(kind, identity)
        owner.verify_preexisting_unchanged()


__all__ = [
    "LocalRuntimeTestCreationPlan",
    "LocalRuntimeTestManifest",
    "LocalRuntimeTestOwnershipError",
]
