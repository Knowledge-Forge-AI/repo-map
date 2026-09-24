from __future__ import annotations

from dataclasses import replace
import json
from collections.abc import Mapping
from typing import cast

import pytest

from repomap_kg.artifacts import (
    ArtifactLimits,
    ArtifactLocator,
    ArtifactReference,
    ManifestArtifact,
    ManifestBinding,
    PortableSnapshotManifest,
)
from repomap_kg.storage.staging_family_contracts import PrivacyClassification


DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64


def reference(
    *, digest: str = DIGEST_A, locator: str = "objects/a"
) -> ArtifactReference:
    return ArtifactReference(
        content_digest=digest,
        size_bytes=3,
        media_type="application/octet-stream",
        record_format="bytes-v1",
        privacy=PrivacyClassification.RAW_SOURCE,
        locator=ArtifactLocator("filesystem", locator, "version-1"),
    )


def binding(*, binding_id: str = "bind1:" + "1" * 64) -> ManifestBinding:
    return ManifestBinding(
        binding_id=binding_id,
        revision=2,
        snapshot_id="snap1:" + "2" * 64,
        source_definition_id="src1:fixture",
        source_kind="local-directory",
        acquisition_method="sealed-local-copy",
        selection_policy_id="select1:" + "3" * 64,
        ignore_policy_id="ignore1:fixture",
        privacy_policy="private-ops",
        role="source",
        input_name=None,
    )


def manifest(
    *, entries: tuple[ManifestArtifact, ...] | None = None
) -> PortableSnapshotManifest:
    source = binding()
    return PortableSnapshotManifest.create(
        graph_id="graph-a",
        bindings=(source,),
        entries=entries
        or (ManifestArtifact(source.binding_id, "src/main.py", reference(), False),),
        source_generation="sg1:" + "4" * 64,
        config_generation="cg1:" + "5" * 64,
        extractor_generation="eg1:" + "6" * 64,
        canonicalizer_generation="kg1:" + "7" * 64,
        extractor_capability_identity="cap1:python-static-v1",
        resolver_identity="resolver1:nix-v1",
        canonicalizer_identity="canon1:graph-v1",
        semantic_contract_identity="semantic1:graph-key-v1",
        quality_rule_identity="quality1:accepted-v1",
    )


def test_manifest_canonical_bytes_bind_complete_vector_and_semantic_roles() -> None:
    value = manifest()
    decoded = PortableSnapshotManifest.from_bytes(value.canonical_bytes())

    assert decoded == value
    assert value.snapshot_vector == (("bind1:" + "1" * 64, 2, "snap1:" + "2" * 64),)
    assert value.manifest_id.startswith("snapmanifest1:")
    assert b'"resolver_identity":"resolver1:nix-v1"' in value.canonical_bytes()
    assert value.effective_privacy is PrivacyClassification.RAW_SOURCE


def test_locator_and_backend_relocation_do_not_change_manifest_identity() -> None:
    original = manifest()
    relocated_ref = replace(
        reference(locator="objects/a"),
        locator=ArtifactLocator("object", "tenant-neutral/a", "object-v9"),
    )
    relocated = manifest(
        entries=(
            ManifestArtifact(binding().binding_id, "src/main.py", relocated_ref, False),
        )
    )

    assert relocated.manifest_id == original.manifest_id
    assert relocated.canonical_bytes() == original.canonical_bytes()
    assert (
        relocated.entries[0].reference.locator != original.entries[0].reference.locator
    )


def test_artifact_semantics_change_manifest_identity() -> None:
    original = manifest()
    for changed_ref in (
        replace(reference(), content_digest=DIGEST_B),
        replace(reference(), size_bytes=4),
        replace(reference(), record_format="bytes-v2"),
        replace(reference(), privacy=PrivacyClassification.CANONICAL_PROVENANCE),
    ):
        changed = manifest(
            entries=(
                ManifestArtifact(binding().binding_id, "src/main.py", changed_ref, False),
            )
        )
        assert changed.manifest_id != original.manifest_id


def test_path_and_mode_change_manifest_identity() -> None:
    original = manifest()
    for changed_entry in (
        replace(original.entries[0], executable=True),
        replace(original.entries[0], source_relative_path="src/other.py"),
    ):
        assert manifest(entries=(changed_entry,)).manifest_id != original.manifest_id


def test_duplicate_paths_from_different_bindings_remain_distinct() -> None:
    one = binding()
    two = binding(binding_id="bind1:" + "8" * 64)
    value = PortableSnapshotManifest.create(
        graph_id="graph-a",
        bindings=(one, two),
        entries=(
            ManifestArtifact(one.binding_id, "flake.nix", reference(), False),
            ManifestArtifact(
                two.binding_id, "flake.nix", reference(digest=DIGEST_B), False
            ),
        ),
        source_generation="sg1:" + "4" * 64,
        config_generation="cg1:" + "5" * 64,
        extractor_generation="eg1:" + "6" * 64,
        canonicalizer_generation="kg1:" + "7" * 64,
        extractor_capability_identity="cap1:python-static-v1",
        resolver_identity="resolver1:nix-v1",
        canonicalizer_identity="canon1:graph-v1",
        semantic_contract_identity="semantic1:graph-key-v1",
        quality_rule_identity="quality1:accepted-v1",
    )

    assert len(value.entries) == 2


@pytest.mark.parametrize(
    "path",
    ["", ".", "../escape", "a/../b", "/absolute", "a//b", "a\\b", "a/./b"],
)
def test_manifest_rejects_non_portable_paths(path: str) -> None:
    with pytest.raises(ValueError, match="artifact path"):
        ManifestArtifact(binding().binding_id, path, reference(), False)
    payload = json.loads(manifest().canonical_bytes())
    payload["entries"][0]["source_relative_path"] = path
    with pytest.raises(ValueError, match="^manifest entry is invalid$") as refused:
        PortableSnapshotManifest.from_bytes(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        )
    assert str(refused.value.__cause__) == "artifact path is not portable"


def test_manifest_rejects_duplicates_case_ambiguity_and_bounds() -> None:
    first = ManifestArtifact(binding().binding_id, "README.md", reference(), False)
    duplicate = replace(first, reference=reference(digest=DIGEST_B))
    case_alias = replace(first, source_relative_path="readme.md")

    with pytest.raises(ValueError, match="duplicate artifact"):
        manifest(entries=(first, duplicate))
    with pytest.raises(ValueError, match="case-ambiguous"):
        manifest(entries=(first, case_alias))
    with pytest.raises(ValueError, match="artifact count"):
        PortableSnapshotManifest.create_from(
            manifest(),
            entries=(first, duplicate),
            limits=ArtifactLimits(max_artifacts=1),
        )


@pytest.mark.parametrize(
    "kind,value",
    [
        ("unknown", "object"),
        ("filesystem", "/host/path"),
        ("filesystem", "../escape"),
        ("object", "https://example.invalid/signed?token=value"),
        ("object", "bucket/key"),
        ("object", "user:password@host/key"),
    ],
)
def test_locator_vocabulary_rejects_authority_and_secret_material(
    kind: str, value: str
) -> None:
    with pytest.raises(ValueError, match="locator"):
        ArtifactLocator(kind, value, "version-1")


def test_public_projection_redacts_private_location_and_store_version() -> None:
    value = reference(locator="private/object")

    public = value.to_public_mapping()
    assert "locator" not in public
    assert "store_version" not in public
    assert "private/object" not in repr(public)


@pytest.mark.parametrize("target", ["bindings", "entries"])
def test_manifest_decoder_rejects_unknown_nested_fields(target: str) -> None:
    payload = json.loads(manifest().canonical_bytes())
    payload[target][0]["unexpected"] = "authority-extension"
    encoded = (
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    )

    with pytest.raises(ValueError, match="manifest"):
        PortableSnapshotManifest.from_bytes(encoded)


def test_manifest_decoder_rejects_coerced_binding_revision() -> None:
    payload = json.loads(manifest().canonical_bytes())
    payload["bindings"][0]["revision"] = "2"
    encoded = (
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    )

    with pytest.raises(ValueError, match="manifest"):
        PortableSnapshotManifest.from_bytes(encoded)


def test_worker_semantic_binding_fields_round_trip_without_physical_roots() -> None:
    source = replace(
        binding(),
        alias="root",
        logical_root=".",
        evidence_retention_policy="inherit",
        extractor_profile="python-static-v1",
        resolution_policy="isolated",
        repository_scope="graph-a",
    )
    value = PortableSnapshotManifest.create_from(
        manifest(),
        bindings=(source,),
    )

    decoded = PortableSnapshotManifest.from_bytes(value.canonical_bytes())

    assert decoded.bindings[0] == source
    assert b'"alias":"root"' in value.canonical_bytes()
    assert b"/Users/" not in value.canonical_bytes()


@pytest.mark.parametrize(
    ("value", "version"),
    [
        ("a" * 513, None),
        ("a\0b", None),
        ("a b", None),
        ("objects/a", "v?1"),
    ],
)
def test_locator_bounds_and_tokens_fail_closed(value: str, version: str | None) -> None:
    with pytest.raises(ValueError, match="locator|store version"):
        ArtifactLocator("filesystem", value, version)


def test_locator_mapping_contract_is_exact_and_version_is_optional() -> None:
    assert ArtifactLocator("object", "tenant-neutral/a").to_mapping() == {
        "kind": "object",
        "value": "tenant-neutral/a",
    }
    payload: object
    for payload in (
        [],
        {"kind": "object", "value": "tenant-neutral/a", "extra": "x"},
        {"kind": 1, "value": "tenant-neutral/a"},
        {"kind": "object", "value": "tenant-neutral/a", "store_version": 1},
    ):
        with pytest.raises(ValueError, match="locator"):
            ArtifactLocator.from_mapping(cast(Mapping[str, object], payload))


def test_reference_semantic_fields_fail_closed() -> None:
    base = reference().to_mapping()
    for change in (
        {"privacy": "secret"},
        {"content_digest": "sha256:short"},
        {"size_bytes": True},
        {"size_bytes": -1},
        {"media_type": "application/ octet-stream"},
        {"locator": "objects/a"},
    ):
        with pytest.raises(ValueError):
            ArtifactReference.from_mapping({**base, **change})


def test_reference_comparison_and_decoders_reject_non_contract_shapes() -> None:
    assert reference().__lt__(object()) is NotImplemented
    payload: object
    for payload in (
        [],
        {**reference().to_mapping(), "extra": "x"},
        {
            key: value
            for key, value in reference().to_mapping().items()
            if key != "locator"
        },
    ):
        with pytest.raises(ValueError, match="reference"):
            ArtifactReference.from_mapping(cast(Mapping[str, object], payload))

    semantic = reference().semantic_mapping()
    sem_payload: object
    for sem_payload in (
        [],
        {key: value for key, value in semantic.items() if key != "privacy"},
        {**semantic, "content_digest": "sha256:short"},
    ):
        with pytest.raises(ValueError, match="reference|digest"):
            ArtifactReference.from_semantic_mapping(cast(Mapping[str, object], sem_payload))


def test_artifact_limits_and_manifest_binding_contract_rejections() -> None:
    with pytest.raises(ValueError, match="artifact limits"):
        ArtifactLimits(max_artifacts=-1)
    with pytest.raises(ValueError, match="artifact limits"):
        ArtifactLimits(max_total_bytes=0)
    with pytest.raises(ValueError, match="artifact limits"):
        ArtifactLimits(max_artifacts=cast(int, True))
    with pytest.raises(ValueError, match="artifact limits"):
        ArtifactLimits(max_path_bytes=cast(int, "invalid"))

    base_binding = binding()
    with pytest.raises(ValueError):
        replace(base_binding, revision=0)
    with pytest.raises(ValueError):
        replace(base_binding, revision=cast(int, True))
    with pytest.raises(ValueError):
        replace(base_binding, source_kind="ftp-server")
    with pytest.raises(ValueError):
        replace(base_binding, acquisition_method="raw-socket")
    with pytest.raises(ValueError):
        replace(base_binding, privacy_policy="top-secret")
    with pytest.raises(ValueError):
        replace(base_binding, role="bad role with spaces")
    with pytest.raises(ValueError):
        replace(base_binding, input_name="bad input with spaces")
    with pytest.raises(ValueError):
        replace(base_binding, binding_id="wrong_prefix:123")
    with pytest.raises(ValueError):
        replace(base_binding, snapshot_id="wrong_prefix:123")
