"""Intermediate build cleanup and failed proof runtime cache disposition unit tests."""

from __future__ import annotations

import pytest

from repomap_test_support.resource_test_image_base import (
    TestImageError as ImageLifecycleError,
)
from repomap_test_support.resource_test_image_materialization import (
    RuntimeBuildIntermediateCleaner,
)
from repomap_test_support.resource_test_images import dispose_failed_proof_runtime_cache
from src.test.unit.python.repomap_test_support.resource_test_image_materialization_parts.fixtures import (
    BASE_ID,
    PROOF_FINGERPRINT,
    PROOF_ID,
    PROOF_TAG,
    TRANSIENT_LABELS,
    FakeContainer,
    FakeImage,
    _failed_proof_image,
    _intermediate_chain,
    _materializer,
)


def test_historical_intermediate_cleanup_requires_exact_positive_chain(tmp_path):
    _materializer_instance, client = _materializer(tmp_path)
    first, second, final = _intermediate_chain(client)
    cleaner = RuntimeBuildIntermediateCleaner(client)

    result = cleaner.cleanup(
        final_image_id=final.id,
        candidate_ids=(second.id, first.id),
        expected_created_by=("install", "label"),
        expected_labels=({}, {"org.repomap.test.managed": "true"}),
    )

    assert result.positive_owned == (first.id, second.id)
    assert result.removed == (second.id, first.id)
    assert result.retained_ambiguous == ()
    assert client.images.remove_calls == [
        (second.id, False, True),
        (first.id, False, True),
    ]
    assert final.id in client.images.objects


@pytest.mark.parametrize("conflict", ["foreign_tag", "container_reference"])
def test_intermediate_cleanup_refuses_conflicting_authority(tmp_path, conflict):
    _materializer_instance, client = _materializer(tmp_path)
    first, second, final = _intermediate_chain(client)
    if conflict == "foreign_tag":
        first.tags.append("repomap-runtime:deployment")
        first.attrs["RepoTags"] = list(first.tags)
    else:
        reference = FakeContainer(client.containers, "container-ref", first.id, {})
        client.containers.objects[reference.id] = reference

    result = RuntimeBuildIntermediateCleaner(client).cleanup(
        final_image_id=final.id,
        candidate_ids=(first.id, second.id),
        expected_created_by=("install", "label"),
        expected_labels=({}, {"org.repomap.test.managed": "true"}),
    )

    assert first.id in result.retained_ambiguous
    assert client.images.remove_calls == []


def test_delta_only_image_and_final_runtime_are_never_cleanup_authority(tmp_path):
    _materializer_instance, client = _materializer(tmp_path)
    first, second, final = _intermediate_chain(client)
    unrelated = FakeImage("sha256:" + "9" * 64, created_by="install")
    client.images.objects[unrelated.id] = unrelated
    cleaner = RuntimeBuildIntermediateCleaner(client)

    result = cleaner.cleanup(
        final_image_id=final.id,
        candidate_ids=(unrelated.id, second.id),
        expected_created_by=("install", "label"),
        expected_labels=({}, {"org.repomap.test.managed": "true"}),
    )
    assert result.positive_owned == ()
    assert set(result.retained_ambiguous) == {unrelated.id, second.id}
    assert client.images.remove_calls == []
    with pytest.raises(ImageLifecycleError, match="final runtime image"):
        cleaner.cleanup(
            final_image_id=final.id,
            candidate_ids=(first.id, final.id),
            expected_created_by=("install", "label"),
            expected_labels=({}, {}),
        )


def test_exact_intermediate_removal_failure_is_terminal(tmp_path):
    _materializer_instance, client = _materializer(tmp_path)
    first, second, final = _intermediate_chain(client)
    client.images.fail_remove = True

    with pytest.raises(ImageLifecycleError, match="managed_runtime_build_cleanup_failed"):
        RuntimeBuildIntermediateCleaner(client).cleanup(
            final_image_id=final.id,
            candidate_ids=(first.id, second.id),
            expected_created_by=("install", "label"),
            expected_labels=({}, {"org.repomap.test.managed": "true"}),
        )

    assert client.images.remove_calls == [(second.id, False, True)]


def test_failed_proof_cache_exact_disposition_is_nonforce_noprune(tmp_path):
    _materializer_instance, client = _materializer(tmp_path)
    _failed_proof_image(client)

    removed = dispose_failed_proof_runtime_cache(
        client=client,
        image_id=PROOF_ID,
        tag=PROOF_TAG,
        fingerprint=PROOF_FINGERPRINT,
        parent_image_id=BASE_ID,
        transient_labels=TRANSIENT_LABELS,
    )

    assert removed == PROOF_ID
    assert PROOF_ID not in client.images.objects
    assert client.images.remove_calls == [(PROOF_ID, False, True)]


@pytest.mark.parametrize("defect", ["fingerprint", "parent", "foreign_tag"])
def test_failed_proof_cache_disposition_refuses_identity_conflict(tmp_path, defect):
    _materializer_instance, client = _materializer(tmp_path)
    tags = (PROOF_TAG, "repomap-runtime:deployment") if defect == "foreign_tag" else (PROOF_TAG,)
    _failed_proof_image(client, tags=tags)

    with pytest.raises(ImageLifecycleError):
        dispose_failed_proof_runtime_cache(
            client=client,
            image_id=PROOF_ID,
            tag=PROOF_TAG,
            fingerprint=("8" * 64 if defect == "fingerprint" else PROOF_FINGERPRINT),
            parent_image_id=("sha256:" + "6" * 64 if defect == "parent" else BASE_ID),
            transient_labels=TRANSIENT_LABELS,
        )

    assert client.images.remove_calls == []


def test_failed_proof_cache_disposition_refuses_container_reference(tmp_path):
    _materializer_instance, client = _materializer(tmp_path)
    _failed_proof_image(client)
    reference = FakeContainer(client.containers, "2" * 64, PROOF_ID, {})
    client.containers.objects[reference.id] = reference

    with pytest.raises(ImageLifecycleError, match="container-referenced"):
        dispose_failed_proof_runtime_cache(
            client=client,
            image_id=PROOF_ID,
            tag=PROOF_TAG,
            fingerprint=PROOF_FINGERPRINT,
            parent_image_id=BASE_ID,
            transient_labels=TRANSIENT_LABELS,
        )

    assert client.images.remove_calls == []
