from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path

import pytest

from repomap_kg.artifacts import ArtifactLocator, ArtifactReference
from repomap_kg.coordinator._portable_capability import (
    PortableExecutionCapability,
    create_portable_capability,
    load_portable_capability,
    remove_portable_capability,
)
from repomap_kg.storage.staging_family_contracts import PrivacyClassification


def manifest_reference() -> ArtifactReference:
    return ArtifactReference(
        "sha256:" + "a" * 64,
        123,
        "application/x-repomap-snapshot-manifest-v1+json",
        "canonical-json-v1",
        PrivacyClassification.RAW_SOURCE,
        ArtifactLocator("filesystem", "objects/aa/value", "filesystem-v1-abc"),
    )


def capability(tmp_path) -> PortableExecutionCapability:
    store = tmp_path / "store"
    workspace = tmp_path / "workspace"
    private = tmp_path / "private"
    for path in (store, workspace, private):
        path.mkdir(mode=0o700)
    return PortableExecutionCapability(
        schema_version=1,
        job_id="job-1",
        attempt=1,
        graph_id="graph-a",
        store_root=store.resolve(),
        workspace_root=workspace.resolve(),
        manifest_reference=manifest_reference(),
        source_generation="sg1:" + "1" * 64,
        config_generation="cg1:" + "2" * 64,
        extractor_generation="eg1:" + "3" * 64,
        canonicalizer_generation="kg1:" + "4" * 64,
        max_artifact_bytes=1024,
        max_bundle_bytes=4096,
    )


def test_capability_round_trip_is_exact_owner_private_and_parent_removed(tmp_path) -> None:
    value = capability(tmp_path)
    path = create_portable_capability(tmp_path / "private", value)

    assert load_portable_capability(path) == value
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600

    remove_portable_capability(path)
    assert not path.exists()


@pytest.mark.parametrize("field", ["postgres_password", "database_url", "command", "source_root"])
def test_capability_rejects_authority_extension_fields(tmp_path, field: str) -> None:
    path = create_portable_capability(tmp_path / "private", capability(tmp_path))
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload[field] = "forbidden"
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.chmod(0o600)

    with pytest.raises(ValueError, match="portable capability"):
        load_portable_capability(path)


def test_capability_is_sealed_to_exact_attempt_and_manifest_version(tmp_path) -> None:
    value = capability(tmp_path)
    with pytest.raises(ValueError, match="portable capability"):
        PortableExecutionCapability(
            **{
                **value.__dict__,
                "attempt": 0,
            }
        ).validate()
    with pytest.raises(ValueError, match="portable capability"):
        PortableExecutionCapability(
            **{
                **value.__dict__,
                "manifest_reference": value.manifest_reference.with_store_version(None),
            }
        ).validate()


def test_capability_physical_store_reference_supports_locator_and_version_preserving_semantics(tmp_path) -> None:
    value = capability(tmp_path)
    # with_store_version preserves semantic equality
    updated_version = value.manifest_reference.with_store_version("fs-v2")
    assert updated_version.store_version == "fs-v2"
    assert updated_version == value.manifest_reference
    assert updated_version.content_digest == value.manifest_reference.content_digest

    cap_with_version = replace(value, manifest_reference=updated_version).validate()
    assert cap_with_version.manifest_reference.store_version == "fs-v2"

    # with_locator preserves semantic equality
    new_locator = ArtifactLocator("filesystem", f"objects/{'a' * 64}", "fs-v3")
    updated_locator = value.manifest_reference.with_locator(new_locator)
    assert updated_locator.locator == new_locator
    assert updated_locator == value.manifest_reference
    assert updated_locator.content_digest == value.manifest_reference.content_digest

    cap_with_locator = replace(value, manifest_reference=updated_locator).validate()
    assert cap_with_locator.manifest_reference.locator == new_locator

    # Refusal when store_root or workspace_root escapes / is relative
    with pytest.raises(ValueError, match="portable capability"):
        replace(value, store_root=Path("relative/store")).validate()
    with pytest.raises(ValueError, match="portable capability"):
        replace(value, workspace_root=Path("relative/workspace")).validate()
