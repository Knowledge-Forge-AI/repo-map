"""Portable manifest decoding preserves semantic inventory and privacy authority."""

from __future__ import annotations

import json
from dataclasses import replace

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


def _manifest() -> PortableSnapshotManifest:
    binding = ManifestBinding(
        binding_id="bind1:entry", revision=1, snapshot_id="snap1:entry",
        source_definition_id="src1:entry", source_kind="sealed-artifacts",
        acquisition_method="verified-object-read", selection_policy_id="select1:all",
        ignore_policy_id="ignore1:none", privacy_policy="public-dev", role="entry",
        input_name=None,
    )
    reference = ArtifactReference(
        content_digest="sha256:" + "a" * 64, size_bytes=3,
        media_type="text/plain", record_format="bytes-v1",
        privacy=PrivacyClassification.PUBLIC,
        locator=ArtifactLocator("object", "fixture/source"),
    )
    return PortableSnapshotManifest.create(
        graph_id="manifest-fixture", bindings=(binding,),
        entries=(ManifestArtifact(binding.binding_id, "src/main.py", reference, False),),
        source_generation="sg1:source", config_generation="cg1:config",
        extractor_generation="eg1:extractor", canonicalizer_generation="kg1:canonical",
        extractor_capability_identity="cap1:static", resolver_identity="resolver1:static",
        canonicalizer_identity="canon1:static", semantic_contract_identity="semantic1:static",
        quality_rule_identity="quality1:static",
    )


def _encoded(payload: dict[str, object]) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()


@pytest.mark.parametrize("field,value", [
    ("total_files", 2), ("total_bytes", 4), ("effective_privacy", "raw_source"),
])
def test_decoder_recomputes_summary_instead_of_trusting_wire_values(field, value):
    original = _manifest()
    payload = original.canonical_mapping()
    payload[field] = value
    with pytest.raises(ValueError, match="snapshot manifest summary is inconsistent"):
        PortableSnapshotManifest.from_bytes(_encoded(payload))
    assert PortableSnapshotManifest.from_bytes(original.canonical_bytes()) == original


@pytest.mark.parametrize("field", ["bindings", "entries"])
@pytest.mark.parametrize("value", [None, {}, "inventory"])
def test_decoder_requires_inventory_arrays(field, value):
    payload = _manifest().canonical_mapping()
    payload[field] = value
    with pytest.raises(ValueError, match=f"manifest {field} is invalid"):
        PortableSnapshotManifest.from_bytes(_encoded(payload))


@pytest.mark.parametrize("field", [
    "binding_id", "snapshot_id", "source_definition_id", "source_kind",
    "acquisition_method", "selection_policy_id", "ignore_policy_id",
    "privacy_policy", "role", "input_name",
])
def test_decoder_refuses_coerced_binding_text_fields(field):
    payload = _manifest().canonical_mapping()
    bindings = payload["bindings"]
    assert isinstance(bindings, list) and isinstance(bindings[0], dict)
    bindings[0][field] = 7
    with pytest.raises(ValueError, match="manifest binding is invalid"):
        PortableSnapshotManifest.from_bytes(_encoded(payload))


@pytest.mark.parametrize("semantic", [
    [], {}, {"alias": "entry"},
    {"alias": "entry", "logical_root": ".", "evidence_retention_policy": "inherit",
     "extractor_profile": "static", "resolution_policy": "isolated", "repository_scope": 7},
])
def test_decoder_rejects_incomplete_or_coerced_semantic_execution(semantic):
    payload = _manifest().canonical_mapping()
    bindings = payload["bindings"]
    assert isinstance(bindings, list) and isinstance(bindings[0], dict)
    bindings[0]["semantic_execution"] = semantic
    with pytest.raises(ValueError, match="manifest binding is invalid"):
        PortableSnapshotManifest.from_bytes(_encoded(payload))


@pytest.mark.parametrize("entries,bindings,error", [
    ("original", "empty", "snapshot manifest requires a binding"),
    ("original", "duplicate", "duplicate snapshot binding"),
    ("foreign", "original", "artifact binding is absent"),
])
def test_inventory_authority_refuses_missing_duplicate_and_foreign_bindings(entries, bindings, error):
    original = _manifest()
    selected_bindings = () if bindings == "empty" else original.bindings * (2 if bindings == "duplicate" else 1)
    selected_entries = original.entries
    if entries == "foreign":
        selected_entries = (replace(original.entries[0], binding_id="bind1:foreign"),)
    with pytest.raises(ValueError, match=error):
        PortableSnapshotManifest.create_from(original, bindings=selected_bindings, entries=selected_entries)
    assert original.total_files == 1 and original.total_bytes == 3


@pytest.mark.parametrize("privacy", list(PrivacyClassification))
def test_manifest_privacy_never_downgrades_artifact_authority(privacy):
    original = _manifest()
    entry = replace(original.entries[0], reference=replace(original.entries[0].reference, privacy=privacy))
    changed = PortableSnapshotManifest.create_from(original, entries=(entry,))
    assert changed.effective_privacy is privacy
    assert PortableSnapshotManifest.from_bytes(changed.canonical_bytes()).effective_privacy is privacy
    assert (changed.manifest_id != original.manifest_id) == (privacy is not PrivacyClassification.PUBLIC)


def test_private_binding_escalates_public_artifact_and_exact_limits_are_inclusive():
    original = _manifest()
    private = PortableSnapshotManifest.create_from(
        original, bindings=(replace(original.bindings[0], privacy_policy="private-ops"),),
    )
    assert private.effective_privacy is PrivacyClassification.RAW_SOURCE
    assert private.manifest_id != original.manifest_id
    size = len(original.canonical_bytes())
    limits = ArtifactLimits(max_path_bytes=len("src/main.py"), max_total_bytes=3, max_manifest_bytes=size)
    assert PortableSnapshotManifest.create_from(original, limits=limits) == original
    assert PortableSnapshotManifest.from_bytes(original.canonical_bytes(), limits=limits) == original
    for field, value, error in (
        ("max_path_bytes", len("src/main.py") - 1, "artifact path bounds exceeded"),
        ("max_total_bytes", 2, "artifact byte bounds exceeded"),
        ("max_manifest_bytes", size - 1, "manifest byte bounds exceeded"),
    ):
        with pytest.raises(ValueError, match=error):
            PortableSnapshotManifest.create_from(original, limits=replace(limits, **{field: value}))
    with pytest.raises(ValueError, match="manifest byte bounds exceeded"):
        PortableSnapshotManifest.from_bytes(original.canonical_bytes(), limits=replace(limits, max_manifest_bytes=size - 1))
