"""TEST-HYGIENE1 exact Docker and Buildx ownership contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from repomap_test_support.resource_docker import (
    DockerBaseline,
    DockerObject,
    DockerOwnershipError,
    DockerResourceOwner,
    ownership_labels,
)
from repomap_test_support.resource_ledger import (
    ResourceKind,
    ResourceLedger,
    RunIdentity,
)


@dataclass
class FakeDockerApi:
    objects: dict[tuple[ResourceKind, str], DockerObject] = field(
        default_factory=dict
    )
    removed: list[tuple[ResourceKind, str]] = field(default_factory=list)
    shared_builder_touched: bool = False

    def list_objects(self, kind):
        return [item for (found, _), item in self.objects.items() if found is kind]

    def inspect(self, kind, identity):
        return self.objects.get((kind, identity))

    def remove(self, kind, identity):
        if identity == "shared-default":
            self.shared_builder_touched = True
        self.removed.append((kind, identity))
        self.objects.pop((kind, identity), None)

    def image_references(self, image_id):
        return {
            key[1]
            for key, value in self.objects.items()
            if key[0] is ResourceKind.DOCKER_CONTAINER
            and value.image_id == image_id
        }

    def volume_references(self, volume_id):
        return {
            key[1]
            for key, value in self.objects.items()
            if key[0] is ResourceKind.DOCKER_CONTAINER
            and volume_id in value.references
        }


def _identity() -> RunIdentity:
    return RunIdentity("repo-map_dev", "TEST-HYGIENE1", "run1")


def _owner(tmp_path: Path, api: FakeDockerApi):
    ledger = ResourceLedger.create(tmp_path / "ledger.json", _identity())
    baseline = DockerBaseline.capture(
        api,
        kinds=(
            ResourceKind.DOCKER_CONTAINER,
            ResourceKind.DOCKER_IMAGE,
            ResourceKind.DOCKER_TAG,
            ResourceKind.DOCKER_NETWORK,
            ResourceKind.DOCKER_VOLUME,
            ResourceKind.BUILDX_BUILDER,
            ResourceKind.BUILDKIT_STATE_VOLUME,
            ResourceKind.BUILD_HISTORY_RECORD,
        ),
    )
    return DockerResourceOwner(_identity(), ledger, api, baseline), ledger


def _object(kind, identity, *, role="test", image_id=None, references=()):
    return DockerObject(
        kind=kind,
        identity=identity,
        labels=ownership_labels(_identity(), role=role, retained=False),
        image_id=image_id,
        references=tuple(references),
    )


def test_docker_labels_and_ledger_are_both_required(tmp_path):
    api = FakeDockerApi()
    owner, _ = _owner(tmp_path, api)
    api.objects[(ResourceKind.DOCKER_CONTAINER, "new")] = _object(
        ResourceKind.DOCKER_CONTAINER, "new"
    )

    with pytest.raises(DockerOwnershipError, match="ledger"):
        owner.cleanup(ResourceKind.DOCKER_CONTAINER, "new")


def test_label_only_ownership_is_refused(tmp_path):
    api = FakeDockerApi()
    owner, ledger = _owner(tmp_path, api)
    api.objects[(ResourceKind.DOCKER_CONTAINER, "new")] = _object(
        ResourceKind.DOCKER_CONTAINER, "new"
    )
    ledger.register(
        ResourceKind.DOCKER_CONTAINER,
        "new",
        creation_owner="another-owner",
        created_before_run=False,
        creation_observed=False,
        cleanup_required=False,
    )

    with pytest.raises(DockerOwnershipError):
        owner.cleanup(ResourceKind.DOCKER_CONTAINER, "new")


def test_pre_existing_container_is_protected(tmp_path):
    api = FakeDockerApi()
    api.objects[(ResourceKind.DOCKER_CONTAINER, "old")] = _object(
        ResourceKind.DOCKER_CONTAINER, "old"
    )
    owner, _ = _owner(tmp_path, api)

    with pytest.raises(DockerOwnershipError, match="pre-existing"):
        owner.register_created(ResourceKind.DOCKER_CONTAINER, "old", role="test")
    assert api.removed == []


def test_pre_existing_image_reference_protects_new_tag_and_image(tmp_path):
    api = FakeDockerApi()
    api.objects[(ResourceKind.DOCKER_CONTAINER, "old-container")] = DockerObject(
        kind=ResourceKind.DOCKER_CONTAINER,
        identity="old-container",
        labels={},
        image_id="image-1",
    )
    owner, _ = _owner(tmp_path, api)
    api.objects[(ResourceKind.DOCKER_IMAGE, "image-1")] = _object(
        ResourceKind.DOCKER_IMAGE, "image-1", role="image"
    )
    owner.register_created(ResourceKind.DOCKER_IMAGE, "image-1", role="image")

    with pytest.raises(DockerOwnershipError, match="pre-existing container"):
        owner.cleanup(ResourceKind.DOCKER_IMAGE, "image-1")
    assert (ResourceKind.DOCKER_IMAGE, "image-1") not in api.removed


@pytest.mark.parametrize(
    "kind",
    [ResourceKind.DOCKER_CONTAINER, ResourceKind.DOCKER_NETWORK, ResourceKind.DOCKER_VOLUME],
)
def test_exact_object_cleanup_requires_matching_labels_and_final_absence(
    tmp_path, kind
):
    api = FakeDockerApi()
    owner, ledger = _owner(tmp_path, api)
    api.objects[(kind, "new")] = _object(kind, "new")
    owner.register_created(kind, "new", role="test")

    owner.cleanup(kind, "new")

    assert (kind, "new") in api.removed
    assert ledger.public_projection()[owner.remaining_field(kind)] == 0


def test_foreign_labels_are_not_counted_as_current_run_cleanup(tmp_path):
    api = FakeDockerApi()
    owner, _ = _owner(tmp_path, api)
    labels = ownership_labels(_identity(), role="test", retained=False)
    labels["org.repomap.test.resource.run_id"] = "another-run"
    api.objects[(ResourceKind.DOCKER_NETWORK, "foreign")] = DockerObject(
        ResourceKind.DOCKER_NETWORK, "foreign", labels
    )

    with pytest.raises(DockerOwnershipError, match="labels"):
        owner.register_created(ResourceKind.DOCKER_NETWORK, "foreign", role="test")


def test_image_tag_cleanup_does_not_delete_shared_layers(tmp_path):
    api = FakeDockerApi()
    owner, _ = _owner(tmp_path, api)
    api.objects[(ResourceKind.DOCKER_IMAGE, "image-1")] = _object(
        ResourceKind.DOCKER_IMAGE,
        "image-1",
        role="image",
        references=("phase:test", "preexisting:tag"),
    )
    api.objects[(ResourceKind.DOCKER_TAG, "phase:test")] = DockerObject(
        ResourceKind.DOCKER_TAG,
        "phase:test",
        ownership_labels(_identity(), role="tag", retained=False),
        image_id="image-1",
        references=("phase:test", "preexisting:tag"),
    )
    owner.register_created(ResourceKind.DOCKER_TAG, "phase:test", role="tag")

    owner.cleanup(ResourceKind.DOCKER_TAG, "phase:test")

    assert (ResourceKind.DOCKER_TAG, "phase:test") in api.removed
    assert api.inspect(ResourceKind.DOCKER_IMAGE, "image-1") is not None


def test_last_image_tag_cleanup_is_refused(tmp_path):
    api = FakeDockerApi()
    owner, _ = _owner(tmp_path, api)
    api.objects[(ResourceKind.DOCKER_IMAGE, "image-1")] = _object(
        ResourceKind.DOCKER_IMAGE,
        "image-1",
        role="image",
        references=("phase:test",),
    )
    api.objects[(ResourceKind.DOCKER_TAG, "phase:test")] = DockerObject(
        ResourceKind.DOCKER_TAG,
        "phase:test",
        ownership_labels(_identity(), role="tag", retained=False),
        image_id="image-1",
        references=("phase:test",),
    )
    owner.register_created(ResourceKind.DOCKER_TAG, "phase:test", role="tag")

    with pytest.raises(DockerOwnershipError, match="last image tag"):
        owner.cleanup(ResourceKind.DOCKER_TAG, "phase:test")


def test_pre_existing_container_reference_protects_new_tag(tmp_path):
    api = FakeDockerApi()
    api.objects[(ResourceKind.DOCKER_CONTAINER, "old-container")] = DockerObject(
        ResourceKind.DOCKER_CONTAINER,
        "old-container",
        {},
        image_id="image-1",
    )
    owner, _ = _owner(tmp_path, api)
    api.objects[(ResourceKind.DOCKER_IMAGE, "image-1")] = _object(
        ResourceKind.DOCKER_IMAGE,
        "image-1",
        role="image",
        references=("phase:test", "other:tag"),
    )
    api.objects[(ResourceKind.DOCKER_TAG, "phase:test")] = DockerObject(
        ResourceKind.DOCKER_TAG,
        "phase:test",
        ownership_labels(_identity(), role="tag", retained=False),
        image_id="image-1",
        references=("phase:test", "other:tag"),
    )
    owner.register_created(ResourceKind.DOCKER_TAG, "phase:test", role="tag")

    with pytest.raises(DockerOwnershipError, match="pre-existing container"):
        owner.cleanup(ResourceKind.DOCKER_TAG, "phase:test")


def test_preexisting_baseline_requires_explicit_unchanged_readback(tmp_path):
    api = FakeDockerApi()
    api.objects[(ResourceKind.DOCKER_NETWORK, "old-network")] = DockerObject(
        ResourceKind.DOCKER_NETWORK, "old-network", {}
    )
    owner, ledger = _owner(tmp_path, api)

    owner.verify_preexisting_unchanged()

    assert ledger.public_projection()["pre_existing_objects_mutated"] is False


def test_preexisting_baseline_detects_changed_object_metadata(tmp_path):
    api = FakeDockerApi()
    key = (ResourceKind.DOCKER_NETWORK, "old-network")
    api.objects[key] = DockerObject(ResourceKind.DOCKER_NETWORK, "old-network", {})
    owner, ledger = _owner(tmp_path, api)
    api.objects[key] = DockerObject(
        ResourceKind.DOCKER_NETWORK, "old-network", {"changed": "true"}
    )

    with pytest.raises(DockerOwnershipError, match="baseline changed"):
        owner.verify_preexisting_unchanged()

    assert ledger.public_projection()["pre_existing_objects_mutated"] is True


def test_unregistered_current_run_docker_object_fails_completeness(tmp_path):
    api = FakeDockerApi()
    owner, _ = _owner(tmp_path, api)
    api.objects[(ResourceKind.DOCKER_NETWORK, "unregistered")] = _object(
        ResourceKind.DOCKER_NETWORK, "unregistered"
    )

    with pytest.raises(DockerOwnershipError, match="absent from the ledger"):
        owner.verify_preexisting_unchanged()


def test_preexisting_container_attachment_protects_new_network(tmp_path):
    api = FakeDockerApi()
    api.objects[(ResourceKind.DOCKER_CONTAINER, "old-container")] = DockerObject(
        ResourceKind.DOCKER_CONTAINER, "old-container", {}
    )
    owner, _ = _owner(tmp_path, api)
    api.objects[(ResourceKind.DOCKER_NETWORK, "new-network")] = _object(
        ResourceKind.DOCKER_NETWORK,
        "new-network",
        references=("old-container",),
    )
    owner.register_created(ResourceKind.DOCKER_NETWORK, "new-network", role="test")

    with pytest.raises(DockerOwnershipError, match="uses the network"):
        owner.cleanup(ResourceKind.DOCKER_NETWORK, "new-network")


def test_missing_tag_does_not_prove_image_cleanup(tmp_path):
    api = FakeDockerApi()
    owner, ledger = _owner(tmp_path, api)
    api.objects[(ResourceKind.DOCKER_IMAGE, "image-1")] = _object(
        ResourceKind.DOCKER_IMAGE, "image-1", role="image"
    )
    owner.register_created(ResourceKind.DOCKER_IMAGE, "image-1", role="image")

    with pytest.raises(DockerOwnershipError, match="exact image"):
        owner.observe_image_absent_from_missing_tag("missing:tag", "image-1")
    assert ledger.public_projection()["phase_images_remaining"] == 1


def test_dedicated_builder_cleanup_proves_container_and_state_volume_absent(
    tmp_path,
):
    api = FakeDockerApi()
    owner, ledger = _owner(tmp_path, api)
    for kind, identity, role in (
        (ResourceKind.BUILDX_BUILDER, "builder-1", "builder"),
        (ResourceKind.DOCKER_CONTAINER, "builder-container", "buildkit"),
        (ResourceKind.BUILDKIT_STATE_VOLUME, "builder-state", "buildkit-state"),
    ):
        api.objects[(kind, identity)] = _object(kind, identity, role=role)
        owner.register_created(kind, identity, role=role)

    owner.cleanup_builder(
        "builder-1", container_id="builder-container", state_volume_id="builder-state"
    )

    projection = ledger.public_projection()
    assert projection["phase_builders_remaining"] == 0
    assert projection["phase_buildkit_state_volumes_remaining"] == 0


def test_stopped_builder_container_alone_does_not_prove_builder_cleanup(tmp_path):
    api = FakeDockerApi()
    owner, _ = _owner(tmp_path, api)

    with pytest.raises(DockerOwnershipError, match="builder identity"):
        owner.cleanup_builder(
            "missing-builder",
            container_id="stopped-container",
            state_volume_id="state-volume",
        )


def test_shared_builder_is_never_mutated(tmp_path):
    api = FakeDockerApi()
    api.objects[(ResourceKind.BUILDX_BUILDER, "shared-default")] = DockerObject(
        ResourceKind.BUILDX_BUILDER, "shared-default", {}
    )
    owner, _ = _owner(tmp_path, api)

    with pytest.raises(DockerOwnershipError, match="pre-existing"):
        owner.register_created(
            ResourceKind.BUILDX_BUILDER, "shared-default", role="builder"
        )
    assert not api.shared_builder_touched


def test_build_history_is_counted_until_exact_record_is_removed(tmp_path):
    api = FakeDockerApi()
    owner, ledger = _owner(tmp_path, api)
    api.objects[(ResourceKind.BUILD_HISTORY_RECORD, "history-1")] = _object(
        ResourceKind.BUILD_HISTORY_RECORD, "history-1", role="history"
    )
    owner.register_created(
        ResourceKind.BUILD_HISTORY_RECORD, "history-1", role="history"
    )

    assert ledger.public_projection()["phase_build_history_remaining"] == 1
    owner.cleanup(ResourceKind.BUILD_HISTORY_RECORD, "history-1")
    assert ledger.public_projection()["phase_build_history_remaining"] == 0
