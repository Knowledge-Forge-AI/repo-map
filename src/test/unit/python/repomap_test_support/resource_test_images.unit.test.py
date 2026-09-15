from __future__ import annotations
import pytest
from repomap_test_support.resource_test_images import (
    DEPLOYMENT_IMAGE_PREFIX,
    RUNTIME_MATERIALIZATION_PROOF_RECIPE_SCHEMA,
    TestImageError as ImageLifecycleError,
    TestImageManager as ImageManager,
    canonical_runtime_fingerprint,
)
from src.test.unit.python.repomap_test_support.resource_test_images_fixtures import (
    FakeImage,
    FakeClient,
    _project,
    _uninstall_authorities as _uninstall_authorities,
    _resource_run,
    _manager,
    _runtime_labels,
    BASE_ID,
    BASE_REFERENCE,
    BASE_CANONICAL_REFERENCE,
)


def test_runtime_fingerprint_ignores_candidate_source_and_changes_on_inputs():
    fields = {
        "recipe_schema": 1,
        "architecture": "arm64",
        "base_image_id": BASE_ID,
        "dependencies": ["a==1"],
    }
    original = canonical_runtime_fingerprint(fields)
    assert original == canonical_runtime_fingerprint(
        {**fields, "candidate_source_sha256": "ignored-by-contract"}
    )
    for key, value in (
        ("recipe_schema", 2),
        ("architecture", "amd64"),
        ("base_image_id", "sha256:" + "d" * 64),
        ("dependencies", ["a==2"]),
    ):
        assert canonical_runtime_fingerprint({**fields, key: value}) != original


def test_fixed_materialization_proof_schema_changes_only_recipe_identity(tmp_path):
    canonical, _client = _manager(tmp_path)
    proof_root = tmp_path / "proof"
    proof_root.mkdir()
    proof, _proof_client = _manager(
        proof_root,
        recipe_schema=RUNTIME_MATERIALIZATION_PROOF_RECIPE_SCHEMA,
    )

    canonical_identity = canonical.runtime_identity()
    proof_identity = proof.runtime_identity()

    assert proof_identity.fingerprint != canonical_identity.fingerprint
    differing = {
        key for key in canonical_identity.fields
        if canonical_identity.fields[key] != proof_identity.fields[key]
    }
    assert differing == {"recipe_schema"}
    assert proof_identity.fields["recipe_schema"] == 2


def test_unowned_materialization_recipe_schema_is_refused(tmp_path):
    with pytest.raises(ImageLifecycleError, match="not repository-owned"):
        _manager(tmp_path, recipe_schema=3)


def test_dynamic_project_dependencies_fail_closed(tmp_path):
    manager, _client = _manager(tmp_path)
    manager.repo_root.joinpath("pyproject.toml").write_text(
        """[project]
name = "fixture"
version = "0.1"
dynamic = ["dependencies"]
""",
        encoding="utf-8",
    )

    with pytest.raises(ImageLifecycleError, match="dynamic project dependencies"):
        manager.runtime_identity()


def test_deployment_and_legacy_namespaces_are_never_selected_or_deleted(tmp_path):
    deployment = FakeImage(
        "sha256:" + "d" * 64,
        tags=(f"{DEPLOYMENT_IMAGE_PREFIX}release-1",),
    )
    legacy = FakeImage(
        "sha256:" + "e" * 64,
        tags=("repomap-runtime-deadbeef:latest",),
    )
    manager, client = _manager(tmp_path, (deployment, legacy))

    selected = manager.ensure_runtime_image()

    assert selected not in {deployment.id, legacy.id}
    assert deployment.id in client.images.objects
    assert legacy.id in client.images.objects
    assert client.images.remove_calls == []
    assert [item.image_id for item in manager.inventory().legacy_unclassified] == [legacy.id]


def test_matching_managed_cache_is_reused_without_build(tmp_path):
    manager, client = _manager(tmp_path)
    identity = manager.runtime_identity()
    cached = FakeImage(
        "sha256:" + "a" * 64,
        tags=(manager.runtime_tag(identity.fingerprint),),
        labels=_runtime_labels(identity.fingerprint),
    )
    client.images.objects[cached.id] = cached

    assert manager.ensure_runtime_image() == cached.id
    assert client.images.runtime_commit_calls == []


@pytest.mark.parametrize("unexpected_value", ["dynamic", ""])
def test_runtime_cache_with_unexpected_resource_label_is_never_reused(
    tmp_path, unexpected_value
):
    manager, client = _manager(tmp_path)
    identity = manager.runtime_identity()
    labels = _runtime_labels(identity.fingerprint)
    labels["org.repomap.test.resource.run_id"] = unexpected_value
    cached = FakeImage(
        "sha256:" + "7" * 64,
        tags=(manager.runtime_tag(identity.fingerprint),),
        labels=labels,
    )
    client.images.objects[cached.id] = cached

    with pytest.raises(ImageLifecycleError, match="ownership ambiguity"):
        manager.ensure_runtime_image()

    assert client.images.runtime_commit_calls == []
    assert client.images.remove_calls == []


def test_missing_runtime_cache_builds_dependency_only_image_exactly_once(tmp_path):
    manager, client = _manager(tmp_path)

    selected = manager.ensure_runtime_image()
    selected_again = manager.ensure_runtime_image()

    assert selected_again == selected
    assert len(client.images.runtime_commit_calls) == 1
    configuration = client.images.runtime_commit_calls[0][2]
    assert configuration["Cmd"] == ["python3"]
    assert configuration["Entrypoint"] is None
    assert configuration["Labels"] == _runtime_labels(
        manager.runtime_identity().fingerprint
    )
    materialization_command = client.containers.create_calls[0][1][1]
    materialization_options = client.containers.create_calls[0][3]
    assert "psycopg[binary]==3.2.12" in materialization_command
    assert "typing-extensions==4.16.0" in materialization_command
    assert "REPOMAP_DEPENDENCY_VERSIONS=" in materialization_command
    assert "COPY src/main/python" not in materialization_command
    assert materialization_options == {
        "entrypoint": ["python"],
        "network_mode": "bridge",
    }
    assert client.images.pull_calls == []


def test_mutable_configured_base_cannot_authorize_pull(tmp_path):
    resource_run = _resource_run(tmp_path)
    client = FakeClient(())

    with pytest.raises(ImageLifecycleError, match="exact repository digest"):
        ImageManager(
            repo_root=_project(tmp_path),
            resource_run=resource_run,
            client=client,
            base_reference="python:3.12-slim-bookworm",
            python_base_family="python:3.12-slim-bookworm",
            python_version="3.12.13",
            psycopg_release_version="3.2.12",
            probe=lambda _identity: None,
        )

    assert client.images.pull_calls == []


def test_missing_exact_configured_base_pulls_that_digest_once(tmp_path):
    manager, client = _manager(tmp_path, include_base=False)

    def pull(reference):
        client.images.pull_calls.append(((reference,), {}))
        image = FakeImage(BASE_ID, repo_digests=(BASE_CANONICAL_REFERENCE,))
        client.images.objects[image.id] = image
        return image

    client.images.pull = pull

    selected = manager.ensure_runtime_image()
    selected_again = manager.ensure_runtime_image()

    assert selected_again == selected
    assert client.images.pull_calls == [((BASE_CANONICAL_REFERENCE,), {})]
    assert manager.base_provenance.reference == BASE_REFERENCE
    assert manager.base_provenance.image_id == BASE_ID
    assert manager.base_provenance.pulled is True
    inventory = manager.inventory()
    assert BASE_ID not in {item.image_id for item in inventory.runtime_cache}
    assert len(inventory.runtime_cache) == 1


def test_pulled_base_completes_canonical_boundary_attribution(tmp_path):
    manager, client = _manager(tmp_path, with_boundary=True, include_base=False)

    def pull(reference):
        client.images.pull_calls.append(((reference,), {}))
        image = FakeImage(BASE_ID, repo_digests=(BASE_CANONICAL_REFERENCE,))
        client.images.objects[image.id] = image
        return image

    client.images.pull = pull

    manager.ensure_runtime_image()
    projection = manager.verify_boundary()

    assert client.images.pull_calls == [((BASE_CANONICAL_REFERENCE,), {})]
    assert projection["managed_external_base_pull_count"] == 1
    assert projection["new_managed_external_test_base_images"] == 1
    assert projection["new_unattributed_images"] == 0


def test_pulled_base_repodigest_mismatch_refuses(tmp_path):
    manager, client = _manager(tmp_path, include_base=False)

    def pull(reference):
        client.images.pull_calls.append(((reference,), {}))
        image = FakeImage(
            BASE_ID,
            tags=(reference,),
            repo_digests=("python:3.12-slim-bookworm@sha256:" + "d" * 64,),
        )
        client.images.objects[image.id] = image
        return image

    client.images.pull = pull

    with pytest.raises(ImageLifecycleError, match="RepoDigest"):
        manager.ensure_runtime_image()


def test_configured_base_architecture_mismatch_refuses_without_pull(tmp_path):
    manager, client = _manager(tmp_path)
    client.images.objects[BASE_ID].attrs["Architecture"] = "amd64"

    with pytest.raises(ImageLifecycleError, match="architecture"):
        manager.ensure_runtime_image()

    assert client.images.pull_calls == []
