from __future__ import annotations

import os

import pytest

from repomap_kg.artifacts import (
    ManifestArtifact,
    ManifestBinding,
    PortableSnapshotManifest,
)
from repomap_kg.artifacts.store import ArtifactIntegrityError, FileSystemArtifactStore
from repomap_kg.coordinator._portable_materialization import MaterializedWorkspace
from repomap_kg.storage.staging_family_contracts import PrivacyClassification


BINDING_ID = "bind1:" + "1" * 64


def sealed_manifest(store: FileSystemArtifactStore) -> PortableSnapshotManifest:
    source = ManifestBinding(
        BINDING_ID,
        1,
        "snap1:" + "2" * 64,
        "src1:fixture",
        "local-directory",
        "sealed-local-copy",
        "select1:" + "3" * 64,
        "ignore1:fixture",
        "public-dev",
        "source",
        None,
    )
    reference = store.put(
        b"print('portable')\n",
        media_type="application/octet-stream",
        record_format="bytes-v1",
        privacy=PrivacyClassification.RAW_SOURCE,
    )
    return PortableSnapshotManifest.create(
        graph_id="graph-a",
        bindings=(source,),
        entries=(ManifestArtifact(BINDING_ID, "src/main.py", reference, True),),
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


def test_materialization_is_private_verified_read_only_and_exactly_cleaned(tmp_path) -> None:
    store = FileSystemArtifactStore(tmp_path / "store")
    manifest = sealed_manifest(store)
    root = tmp_path / "work"
    root.mkdir(mode=0o700)

    with MaterializedWorkspace(store, manifest, root, job_id="job-1", attempt=1) as view:
        materialized = view.binding_roots[BINDING_ID] / "src/main.py"
        assert materialized.read_bytes() == b"print('portable')\n"
        if os.name != "nt":
            assert materialized.stat().st_mode & 0o777 == 0o500
        owned = view.attempt_root

    assert not owned.exists()


def test_materialization_fails_closed_on_stale_object_version_and_cleans(tmp_path) -> None:
    store = FileSystemArtifactStore(tmp_path / "store")
    manifest = sealed_manifest(store)
    entry = manifest.entries[0]
    stale = entry.reference.with_store_version("filesystem-v1-stale")
    changed = PortableSnapshotManifest.create_from(
        manifest,
        entries=(ManifestArtifact(BINDING_ID, entry.source_relative_path, stale, True),),
    )
    root = tmp_path / "work"
    root.mkdir(mode=0o700)

    with pytest.raises(ArtifactIntegrityError, match="version"):
        with MaterializedWorkspace(store, changed, root, job_id="job-1", attempt=1):
            pass
    assert list(root.iterdir()) == []


def test_materialization_checks_cancellation_before_every_artifact_read(tmp_path) -> None:
    store = FileSystemArtifactStore(tmp_path / "store")
    manifest = sealed_manifest(store)
    root = tmp_path / "work"
    root.mkdir(mode=0o700)
    checks = 0

    def cancel() -> None:
        nonlocal checks
        checks += 1
        raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        with MaterializedWorkspace(
            store,
            manifest,
            root,
            job_id="job-1",
            attempt=1,
            cancel_check=cancel,
        ):
            pass
    assert checks == 1
    assert list(root.iterdir()) == []
