from __future__ import annotations
import pytest
from repomap_test_support.resource_test_images import (
    DEPLOYMENT_IMAGE_PREFIX,
    RUNTIME_CACHE_IMAGE_PREFIX,
    TestImageError as ImageLifecycleError,
)
from src.test.unit.python.repomap_test_support.resource_test_images_fixtures import (
    FakeImage,
    _uninstall_authorities as _uninstall_authorities,
    _manager,
    _runtime_labels,
)


@pytest.mark.parametrize("defect", ["unlabelled", "wrong_repository"])
def test_lookalike_runtime_tag_fails_closed(tmp_path, defect):
    manager, client = _manager(tmp_path)
    identity = manager.runtime_identity()
    labels = {} if defect == "unlabelled" else _runtime_labels(
        identity.fingerprint, repository="other"
    )
    lookalike = FakeImage(
        "sha256:" + "9" * 64,
        tags=(manager.runtime_tag(identity.fingerprint),),
        labels=labels,
    )
    client.images.objects[lookalike.id] = lookalike

    with pytest.raises(ImageLifecycleError, match="ownership ambiguity"):
        manager.ensure_runtime_image()

    assert client.images.remove_calls == []


def test_unlabelled_test_namespace_lookalike_with_other_tag_fails_closed(tmp_path):
    manager, client = _manager(tmp_path)
    lookalike = FakeImage(
        "sha256:" + "c" * 64,
        tags=(f"{RUNTIME_CACHE_IMAGE_PREFIX}some-other-fingerprint",),
    )
    client.images.objects[lookalike.id] = lookalike

    with pytest.raises(ImageLifecycleError, match="ownership ambiguity"):
        manager.ensure_runtime_image()

    assert client.images.runtime_commit_calls == []


def test_deployment_tag_on_managed_test_image_fails_closed(tmp_path):
    manager, client = _manager(tmp_path)
    identity = manager.runtime_identity()
    ambiguous = FakeImage(
        "sha256:" + "8" * 64,
        tags=(
            manager.runtime_tag(identity.fingerprint),
            f"{DEPLOYMENT_IMAGE_PREFIX}release-2",
        ),
        labels=_runtime_labels(identity.fingerprint),
    )
    client.images.objects[ambiguous.id] = ambiguous

    with pytest.raises(ImageLifecycleError, match="deployment tag"):
        manager.ensure_runtime_image()

    assert client.images.remove_calls == []


def test_duplicate_matching_images_select_newest_and_remove_safe_extra(tmp_path):
    manager, client = _manager(tmp_path)
    identity = manager.runtime_identity()
    old = FakeImage(
        "sha256:" + "1" * 64,
        tags=(f"{RUNTIME_CACHE_IMAGE_PREFIX}duplicate-old",),
        labels=_runtime_labels(identity.fingerprint),
        created="2026-08-14T00:00:00Z",
    )
    new = FakeImage(
        "sha256:" + "2" * 64,
        tags=(manager.runtime_tag(identity.fingerprint),),
        labels=_runtime_labels(identity.fingerprint),
        created="2026-08-15T00:00:00Z",
    )
    client.images.objects.update({old.id: old, new.id: new})

    assert manager.ensure_runtime_image() == new.id
    assert old.id not in client.images.objects
    assert client.images.remove_calls == [(old.id, False, True)]


def test_manager_and_boundary_refuse_second_current_run_build(tmp_path):
    manager, client = _manager(tmp_path, with_boundary=True)
    identity = manager.runtime_identity()
    first = manager._build_runtime_image(identity, f"{RUNTIME_CACHE_IMAGE_PREFIX}first")
    with pytest.raises(RuntimeError, match="build count exceeds one"):
        manager._build_runtime_image(identity, manager.runtime_tag(identity.fingerprint))

    assert manager.ensure_runtime_image() == first.image_id
    assert first.image_id in client.images.objects
    projection = manager.verify_boundary()
    assert projection["managed_test_runtime_image_build_count"] == 1
    assert projection["new_managed_test_runtime_cache_images"] == 1


def test_untagged_managed_cache_is_gc_owned_but_never_selected(tmp_path):
    manager, client = _manager(tmp_path)
    identity = manager.runtime_identity()
    orphan = FakeImage(
        "sha256:" + "d" * 64,
        labels=_runtime_labels(identity.fingerprint),
        created="2026-08-01T00:00:00Z",
    )
    previous = FakeImage(
        "sha256:" + "e" * 64,
        tags=(f"{RUNTIME_CACHE_IMAGE_PREFIX}previous",),
        labels=_runtime_labels("e" * 64),
        created="2026-08-02T00:00:00Z",
    )
    client.images.objects.update({orphan.id: orphan, previous.id: previous})

    selected = manager.ensure_runtime_image()

    assert selected != orphan.id
    assert orphan.id not in client.images.objects
    assert client.images.remove_calls == [(orphan.id, False, True)]


def test_gc_keeps_current_and_newest_previous_cache(tmp_path):
    manager, client = _manager(tmp_path)
    current_identity = manager.runtime_identity()
    records = []
    for ordinal in range(3):
        fingerprint = f"{ordinal:064x}"
        records.append(
            FakeImage(
                "sha256:" + str(ordinal + 3) * 64,
                tags=(f"{RUNTIME_CACHE_IMAGE_PREFIX}old-{ordinal}",),
                labels=_runtime_labels(fingerprint),
                created=f"2026-08-1{ordinal}T00:00:00Z",
            )
        )
    current = FakeImage(
        "sha256:" + "7" * 64,
        tags=(manager.runtime_tag(current_identity.fingerprint),),
        labels=_runtime_labels(current_identity.fingerprint),
        created="2026-08-16T00:00:00Z",
    )
    client.images.objects.update({item.id: item for item in (*records, current)})

    result = manager.gc_runtime_cache(
        protected_image_id=current.id,
        protected_fingerprint=current_identity.fingerprint,
    )

    remaining = manager.inventory().runtime_cache
    assert {item.image_id for item in remaining} == {records[-1].id, current.id}
    assert result.removed == (records[0].id, records[1].id)


def test_gc_protects_container_referenced_stale_cache(tmp_path):
    manager, client = _manager(tmp_path)
    identity = manager.runtime_identity()
    current = FakeImage(
        "sha256:" + "6" * 64,
        tags=(manager.runtime_tag(identity.fingerprint),),
        labels=_runtime_labels(identity.fingerprint),
    )
    stale = FakeImage(
        "sha256:" + "5" * 64,
        tags=(f"{RUNTIME_CACHE_IMAGE_PREFIX}stale",),
        labels=_runtime_labels("f" * 64),
        created="2026-08-01T00:00:00Z",
    )
    other = FakeImage(
        "sha256:" + "4" * 64,
        tags=(f"{RUNTIME_CACHE_IMAGE_PREFIX}other",),
        labels=_runtime_labels("e" * 64),
        created="2026-08-02T00:00:00Z",
    )
    client.images.objects.update({item.id: item for item in (current, stale, other)})
    client.containers.image_references[stale.id] = {"container-1"}

    result = manager.gc_runtime_cache(current.id, identity.fingerprint)

    assert stale.id in client.images.objects
    assert result.deferred_in_use == (stale.id,)


def test_cache_removal_revalidates_tags_and_live_container_references(tmp_path):
    manager, client = _manager(tmp_path)
    identity = manager.runtime_identity()
    stale = FakeImage(
        "sha256:" + "4" * 64,
        tags=(f"{RUNTIME_CACHE_IMAGE_PREFIX}stale",),
        labels=_runtime_labels(identity.fingerprint),
    )
    client.images.objects[stale.id] = stale
    record = manager._record(stale)

    stale.tags.append(f"{DEPLOYMENT_IMAGE_PREFIX}release-race")
    with pytest.raises(ImageLifecycleError, match="deployment tag"):
        manager._remove_cache(record)
    stale.tags.pop()
    client.containers.image_references[stale.id] = {"late-container"}

    assert manager._remove_cache(record) is False
    assert client.images.remove_calls == []
