from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import TypedDict

import pytest

from repomap_kg.artifacts import (
    ArtifactExtractionConformanceAdapter,
    ConformanceRequest,
    FileSystemArtifactStore,
    ManifestArtifact,
    ManifestBinding,
    MemoryArtifactStore,
    PortableSnapshotManifest,
    PublicationBundle,
)
from repomap_kg.storage.staging_family_contracts import PrivacyClassification
from repomap_kg.storage.staging_family_rows import StageFamily

EMPTY_FAMILIES: Mapping[StageFamily, Sequence[Mapping[str, object]]] = {
    "files": (),
    "raw_observations": (),
    "canonical_nodes": (),
    "canonical_edges": (),
    "canonical_evidence": (),
    "canonical_node_evidence": (),
    "canonical_edge_evidence": (),
}


def binding() -> ManifestBinding:
    return ManifestBinding(
        binding_id="bind1:" + "1" * 64,
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


def manifest(*, entries: tuple[ManifestArtifact, ...]) -> PortableSnapshotManifest:
    return PortableSnapshotManifest.create(
        graph_id="graph-a",
        bindings=(binding(),),
        entries=entries,
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


def request(snapshot_manifest_id: str) -> ConformanceRequest:
    return ConformanceRequest(
        request_id="request-1",
        job_id="job-1",
        attempt=1,
        candidate_id="cand1:" + "3" * 64,
        snapshot_manifest_id=snapshot_manifest_id,
        worker_capability_identity="cap1:portable-worker-v1",
        contract_version="1.0",
        producer_identity="producer1:conformance-python",
    )


def sealed_manifest(store, content: bytes):
    ref = store.put(
        content,
        media_type="application/octet-stream",
        record_format="bytes-v1",
        privacy=PrivacyClassification.RAW_SOURCE,
    )
    return manifest(
        entries=(ManifestArtifact(binding().binding_id, "src/main.py", ref, False),)
    )


def test_worker_reads_sealed_store_after_original_checkout_changes(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    original = checkout / "main.py"
    original.write_bytes(b"before")
    store = MemoryArtifactStore()
    sealed = sealed_manifest(store, original.read_bytes())
    original.write_bytes(b"after")

    observed: list[dict[tuple[str, str], bytes]] = []

    def engine(files):
        observed.append(files)
        return EMPTY_FAMILIES

    result = ArtifactExtractionConformanceAdapter(store).run(
        manifest=sealed,
        request=request(sealed.manifest_id),
        semantic_engine=engine,
    )

    assert observed == [{(binding().binding_id, "src/main.py"): b"before"}]
    assert result.receipt.outcome == "completed"
    assert result.bundle_reference is not None
    assert result.bundle is not None
    assert PublicationBundle.from_bytes(store.read(result.bundle_reference)) == result.bundle


def test_filesystem_and_fake_backend_produce_identical_bundle_and_receipt_bytes(tmp_path: Path) -> None:
    stores = (MemoryArtifactStore(), FileSystemArtifactStore(tmp_path / "store"))
    outputs = []
    for store in stores:
        sealed = sealed_manifest(store, b"same")
        result = ArtifactExtractionConformanceAdapter(store).run(
            manifest=sealed,
            request=request(sealed.manifest_id),
            semantic_engine=lambda _files: EMPTY_FAMILIES,
        )
        assert result.bundle is not None
        outputs.append((result.bundle.canonical_bytes(), result.receipt.canonical_bytes()))

    assert outputs[0] == outputs[1]


def test_cancellation_before_completion_emits_no_accepted_bundle_reference() -> None:
    store = MemoryArtifactStore()
    sealed = sealed_manifest(store, b"same")
    invoked = False

    def engine(_files):
        nonlocal invoked
        invoked = True
        return EMPTY_FAMILIES

    result = ArtifactExtractionConformanceAdapter(store).run(
        manifest=sealed,
        request=request(sealed.manifest_id),
        semantic_engine=engine,
        cancellation_requested=True,
    )

    assert not invoked
    assert result.receipt.outcome == "cancelled"
    assert result.bundle is None
    assert result.bundle_reference is None


def test_manifest_identity_mismatch_fails_before_semantic_engine() -> None:
    store = MemoryArtifactStore()
    sealed = sealed_manifest(store, b"same")

    with pytest.raises(ValueError, match="manifest identity"):
        ArtifactExtractionConformanceAdapter(store).run(
            manifest=sealed,
            request=request("snapmanifest1:" + "9" * 64),
            semantic_engine=lambda _files: EMPTY_FAMILIES,
        )



class ConformanceChanges(TypedDict, total=False):
    request_id: str
    job_id: str
    attempt: int
    candidate_id: str
    snapshot_manifest_id: str
    worker_capability_identity: str
    contract_version: str
    producer_identity: str

@pytest.mark.parametrize(
    "kwargs",
    [
        {"request_id": ""},
        {"job_id": ""},
        {"attempt": 0},
        {"attempt": True},
        {"attempt": "one"},
        {"candidate_id": "invalid:123"},
        {"snapshot_manifest_id": "invalid:123"},
        {"worker_capability_identity": "invalid:123"},
        {"contract_version": "2.0"},
        {"producer_identity": "invalid:123"},
    ],
)
def test_conformance_request_validation_rejections(kwargs: ConformanceChanges) -> None:
    base = ConformanceRequest(
        request_id="request-1",
        job_id="job-1",
        attempt=1,
        candidate_id="cand1:" + "3" * 64,
        snapshot_manifest_id="snapmanifest1:" + "4" * 64,
        worker_capability_identity="cap1:portable-worker-v1",
        contract_version="1.0",
        producer_identity="producer1:conformance-python",
    )
    with pytest.raises(ValueError, match="conformance request is invalid"):
        replace(base, **kwargs)


def test_artifact_integrity_error_returns_failed_result() -> None:
    store = MemoryArtifactStore()
    ref = store.put(
        b"data",
        media_type="application/octet-stream",
        record_format="bytes-v1",
        privacy=PrivacyClassification.RAW_SOURCE,
    )
    del store._objects[ref.locator.value]
    bad_manifest = manifest(
        entries=(ManifestArtifact(binding().binding_id, "src/main.py", ref, False),)
    )

    result = ArtifactExtractionConformanceAdapter(store).run(
        manifest=bad_manifest,
        request=request(bad_manifest.manifest_id),
        semantic_engine=lambda _files: EMPTY_FAMILIES,
    )

    assert result.receipt.outcome == "failed"
    assert result.receipt.cancellation == "not-observed"
    assert result.receipt.diagnostic_category == "artifact_missing"
    assert result.bundle is None
    assert result.bundle_reference is None
