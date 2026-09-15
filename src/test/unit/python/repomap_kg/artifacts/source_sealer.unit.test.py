from __future__ import annotations

from pathlib import Path

import pytest

from repomap_kg.artifacts.source_sealer import seal_configured_sources
from repomap_kg.artifacts.store import FileSystemArtifactStore
from repomap_kg.graph.multi_source import (
    SourceKind,
    graph_source_binding_id,
    source_selection_policy_id,
)
from repomap_kg.ops.config_binding_records import OpsGraphSourceBindingConfig
from repomap_kg.ops.config_records import OpsGraphConfig


def _graph(root):
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


def test_parent_seals_complete_inventory_without_source_locator_in_manifest(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
    store = FileSystemArtifactStore(tmp_path / "private-store")

    manifest, reference, candidate_id = seal_configured_sources(
        _graph(source),
        store,
        extractor_generation="eg1:portable",
        canonicalizer_generation="kg1:portable",
    )

    assert manifest.total_files == 1
    assert len(manifest.snapshot_vector) == 1
    assert reference.content_digest
    assert candidate_id.startswith("cand1:")
    assert str(source).encode() not in manifest.canonical_bytes()
    assert store.read(reference) == manifest.canonical_bytes()


def test_seal_configured_sources_rejects_unsealable_file(tmp_path, monkeypatch):
    import os
    import repomap_kg.artifacts.source_sealer as sealer_mod

    source = tmp_path / "source"
    source.mkdir()
    (source / "main.py").write_text("X = 1\n", encoding="utf-8")
    store = FileSystemArtifactStore(tmp_path / "store")

    orig_lstat = Path.lstat
    sealing_active = False

    orig_scan = sealer_mod.scan_multi_source_generations

    def instrumented_scan(g):
        nonlocal sealing_active
        res = orig_scan(g)
        sealing_active = True
        return res

    monkeypatch.setattr(sealer_mod, "scan_multi_source_generations", instrumented_scan)

    def tampered_lstat(self):
        st = orig_lstat(self)
        if sealing_active and self.name == "main.py":
            return os.stat_result(
                (st.st_mode, st.st_ino, st.st_dev, 2, st.st_uid, st.st_gid, st.st_size, int(st.st_atime), int(st.st_mtime), int(st.st_ctime))
            )
        return st

    monkeypatch.setattr(Path, "lstat", tampered_lstat)

    with pytest.raises(ValueError, match="source inventory is not sealable"):
        seal_configured_sources(
            _graph(source),
            store,
            extractor_generation="eg1:portable",
            canonicalizer_generation="kg1:portable",
        )


def test_seal_configured_sources_detects_content_hash_mutation(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
    store = FileSystemArtifactStore(tmp_path / "store")

    orig_read_bytes = Path.read_bytes

    def tampered_read(self):
        if self.name == "main.py":
            return b"MUTATED"
        return orig_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", tampered_read)

    with pytest.raises(ValueError, match="source changed while sealing"):
        seal_configured_sources(
            _graph(source),
            store,
            extractor_generation="eg1:portable",
            canonicalizer_generation="kg1:portable",
        )


def test_seal_configured_sources_detects_generation_drift(tmp_path, monkeypatch):
    import pytest
    from dataclasses import replace
    import repomap_kg.artifacts.source_sealer as sealer_mod

    source = tmp_path / "source"
    source.mkdir()
    (source / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
    store = FileSystemArtifactStore(tmp_path / "store")

    real_scan = sealer_mod.scan_multi_source_generations
    call_count = 0

    def drifted_scan(g):
        nonlocal call_count
        call_count += 1
        res = real_scan(g)
        if call_count == 2:
            return replace(res, source_generation="sg1:drifted")
        return res

    monkeypatch.setattr(sealer_mod, "scan_multi_source_generations", drifted_scan)

    with pytest.raises(ValueError, match="source changed while sealing"):
        seal_configured_sources(
            _graph(source),
            store,
            extractor_generation="eg1:portable",
            canonicalizer_generation="kg1:portable",
        )


def test_seal_configured_sources_falls_back_to_graph_id_scope(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
    store = FileSystemArtifactStore(tmp_path / "store")

    g = _graph(source)
    g = replace_repo_name(g, "")

    manifest, _, _ = seal_configured_sources(
        g,
        store,
        extractor_generation="eg1:portable",
        canonicalizer_generation="kg1:portable",
    )
    assert manifest.bindings[0].repository_scope == "fixture-graph"


def replace_repo_name(g: OpsGraphConfig, name: str) -> OpsGraphConfig:
    from dataclasses import replace
    return replace(g, repository_name=name)
