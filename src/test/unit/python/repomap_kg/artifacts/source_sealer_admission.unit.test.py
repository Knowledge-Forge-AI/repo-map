from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from common_lore_index.artifacts import (
    ArtifactLimits,
    ArtifactLocator,
    ArtifactReference,
    DEFAULT_ARTIFACT_LIMITS,
    ManifestArtifact,
    ManifestBinding,
    PortableSnapshotManifest,
)
from common_lore_index.artifacts._manifest_records import _validate_inventory_shape
from common_lore_index.artifacts.source_sealer import seal_configured_sources
from common_lore_index.artifacts.store import FileSystemArtifactStore
from common_lore_index.graph.multi_source import (
    SourceKind,
    graph_source_binding_id,
    source_selection_policy_id,
)
from common_lore_index.ops.config_binding_records import OpsGraphSourceBindingConfig
from common_lore_index.ops.config_records import OpsGraphConfig
from common_lore_index.storage.staging_family_contracts import PrivacyClassification


def _graph(root: Path) -> OpsGraphConfig:
    binding = OpsGraphSourceBindingConfig(
        schema_version=1,
        binding_id=graph_source_binding_id("fixture-graph", "entry"),
        source_definition_id="src1:entry",
        alias="entry",
        revision=1,
        source_kind=SourceKind.FOLDER,
        root_path=str(root),
        root_path_expanded=str(root),
        repository_name="fixture",
        logical_root=".",
        privacy="public-dev",
        evidence_retention="metadata-only",
        extractor_profile="default",
        include_paths=(),
        exclude_paths=(),
        selection_policy_id=source_selection_policy_id((), ()),
        resolution_policy="allow-declared",
        enabled=True,
        role="entry",
        input_name=None,
    )
    return OpsGraphConfig(
        id="fixture-graph",
        name="Fixture",
        root_path="",
        root_path_expanded="",
        repository_name="fixture",
        privacy="public-dev",
        enabled=True,
        mcp_visible=True,
        extractor_profile="default",
        refresh_policy="manual",
        source_bindings=(binding,),
        explicit_source_bindings=True,
    )


def test_sealing_admits_inventory_before_store_writes(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "one.py").write_text("ONE = 1\n", encoding="utf-8")
    (source / "two.py").write_text("TWO = 2\n", encoding="utf-8")
    store = FileSystemArtifactStore(tmp_path / "store")
    writes = 0

    def unexpected_write(*args, **kwargs):
        nonlocal writes
        writes += 1
        raise AssertionError("inventory refusal must precede store writes")

    monkeypatch.setattr(store, "put", unexpected_write)

    with pytest.raises(ValueError, match="artifact count bounds exceeded"):
        seal_configured_sources(
            _graph(source),
            store,
            extractor_generation="eg1:portable",
            canonicalizer_generation="kg1:portable",
            limits=ArtifactLimits(max_artifacts=1),
        )

    assert writes == 0


@pytest.mark.parametrize(
    ("records", "message"),
    (
        (
            [("bind1:a", "a.py", 1), ("bind1:a", "a.py", 1)],
            "duplicate artifact path",
        ),
        (
            [("bind1:a", "a.py", 1), ("bind1:a", "A.PY", 1)],
            "case-ambiguous artifact path",
        ),
        (
            [("bind1:missing", "a.py", 1)],
            "artifact binding is absent",
        ),
        (
            [("bind1:a", "abcd.py", 1)],
            "artifact path bounds exceeded",
        ),
    ),
)
def test_inventory_shape_rejects_duplicate_case_binding_and_path(records, message):
    limits = ArtifactLimits(max_path_bytes=3)
    with pytest.raises(ValueError, match=message):
        _validate_inventory_shape(["bind1:a"], records, limits)


def test_inventory_shape_accepts_and_rejects_exact_total_boundary():
    limits = ArtifactLimits(max_total_bytes=3)
    _validate_inventory_shape(["bind1:a"], [("bind1:a", "a.py", 3)], limits)
    with pytest.raises(ValueError, match="artifact byte bounds exceeded"):
        _validate_inventory_shape(["bind1:a"], [("bind1:a", "a.py", 4)], limits)


def _manifest_fixture() -> PortableSnapshotManifest:
    binding = ManifestBinding(
        binding_id="bind1:entry",
        revision=1,
        snapshot_id="snap1:entry",
        source_definition_id="src1:entry",
        source_kind="sealed-artifacts",
        acquisition_method="verified-object-read",
        selection_policy_id="select1:all",
        ignore_policy_id="ignore1:none",
        privacy_policy="public-dev",
        role="entry",
        input_name=None,
    )
    reference = ArtifactReference(
        content_digest="sha256:" + "a" * 64,
        size_bytes=3,
        media_type="text/plain",
        record_format="bytes-v1",
        privacy=PrivacyClassification.PUBLIC,
        locator=ArtifactLocator("object", "fixture/source"),
    )
    return PortableSnapshotManifest.create(
        graph_id="manifest-fixture",
        bindings=(binding,),
        entries=(ManifestArtifact(binding.binding_id, "src/main.py", reference, False),),
        source_generation="sg1:source",
        config_generation="cg1:config",
        extractor_generation="eg1:extractor",
        canonicalizer_generation="kg1:canonical",
        extractor_capability_identity="cap1:static",
        resolver_identity="resolver1:static",
        canonicalizer_identity="canon1:static",
        semantic_contract_identity="semantic1:static",
        quality_rule_identity="quality1:static",
    )


def test_manifest_retains_looser_limits_while_sealer_rejects_them(tmp_path):
    manifest = _manifest_fixture()
    loose = replace(
        DEFAULT_ARTIFACT_LIMITS,
        max_artifacts=DEFAULT_ARTIFACT_LIMITS.max_artifacts + 1,
    )
    assert PortableSnapshotManifest.create_from(manifest, limits=loose) == manifest

    source = tmp_path / "source"
    source.mkdir()
    (source / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="artifact limits exceed defaults"):
        seal_configured_sources(
            _graph(source),
            FileSystemArtifactStore(tmp_path / "store"),
            extractor_generation="eg1:portable",
            canonicalizer_generation="kg1:portable",
            limits=loose,
        )
