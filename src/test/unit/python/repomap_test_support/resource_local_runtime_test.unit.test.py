from __future__ import annotations

from types import SimpleNamespace

import pytest

from repomap_test_support.resource_local_runtime_test import (
    LocalRuntimeTestCreationPlan,
    LocalRuntimeTestManifest,
    LocalRuntimeTestOwnershipError,
)
from repomap_test_support.resource_ledger import ResourceKind


class Owner:
    def __init__(self, objects):
        self.api = SimpleNamespace(inspect=lambda kind, identity: objects.get((kind, identity)))
        self.registered = []
        self.cleaned = []
        self.baseline_verified = False

    def register_created(self, kind, identity, *, role):
        self.registered.append((kind, identity, role))

    def cleanup(self, kind, identity):
        self.cleaned.append((kind, identity))

    def verify_preexisting_unchanged(self):
        self.baseline_verified = True


def manifest() -> LocalRuntimeTestManifest:
    return LocalRuntimeTestManifest(
        compose_project="repomap-safety3-exact",
        container_ids=("server-id", "postgres-id"),
        named_volume_ids=("coordinator-volume", "admin-volume"),
        created_image_ids=("sha256:created",),
        created_tags=("repomap-safety3:test",),
        creation_plan=LocalRuntimeTestCreationPlan(
            compose_project="repomap-safety3-exact",
            named_volume_ids=("coordinator-volume", "admin-volume"),
        ),
    )


def test_safety3_future_build_teardown_registers_and_removes_exact_ids() -> None:
    expected_mounts = ("coordinator-volume", "admin-volume")
    objects = {
        (ResourceKind.DOCKER_CONTAINER, identity): SimpleNamespace(
            labels={"com.docker.compose.project": "repomap-safety3-exact"},
            references=("/private/source-bind", *expected_mounts),
            volume_references=expected_mounts,
        )
        for identity in ("server-id", "postgres-id")
    }
    owner = Owner(objects)

    manifest().register_and_teardown(owner)

    assert owner.cleaned == [
        (ResourceKind.DOCKER_CONTAINER, "server-id"),
        (ResourceKind.DOCKER_CONTAINER, "postgres-id"),
        (ResourceKind.DOCKER_VOLUME, "coordinator-volume"),
        (ResourceKind.DOCKER_VOLUME, "admin-volume"),
        (ResourceKind.DOCKER_TAG, "repomap-safety3:test"),
        (ResourceKind.DOCKER_IMAGE, "sha256:created"),
    ]
    assert owner.baseline_verified is True


def test_safety3_future_build_teardown_refuses_anonymous_volume() -> None:
    objects = {
        (ResourceKind.DOCKER_CONTAINER, "server-id"): SimpleNamespace(
            labels={"com.docker.compose.project": "repomap-safety3-exact"},
            references=("coordinator-volume", "anonymous-volume"),
            volume_references=("coordinator-volume", "anonymous-volume"),
        ),
        (ResourceKind.DOCKER_CONTAINER, "postgres-id"): SimpleNamespace(
            labels={"com.docker.compose.project": "repomap-safety3-exact"},
            references=("admin-volume",),
            volume_references=("admin-volume",),
        ),
    }
    owner = Owner(objects)

    with pytest.raises(LocalRuntimeTestOwnershipError, match="anonymous"):
        manifest().register_and_teardown(owner)

    assert owner.cleaned == []


def test_safety3_future_build_plan_prevents_postgres_anonymous_volume() -> None:
    with pytest.raises(LocalRuntimeTestOwnershipError, match="tmpfs"):
        LocalRuntimeTestCreationPlan(
            compose_project="repomap-safety3-exact",
            named_volume_ids=("coordinator-volume", "admin-volume"),
            postgres_data_mount_type="volume",
        )


def test_safety3_future_build_teardown_refuses_wrong_compose_project() -> None:
    objects = {
        (ResourceKind.DOCKER_CONTAINER, identity): SimpleNamespace(
            labels={"com.docker.compose.project": "foreign-project"},
            references=(),
            volume_references=(),
        )
        for identity in ("server-id", "postgres-id")
    }
    owner = Owner(objects)

    with pytest.raises(LocalRuntimeTestOwnershipError, match="Compose project"):
        manifest().register_and_teardown(owner)

    assert owner.cleaned == []
