"""Unit tests for streaming publication bundle encoder, parser, and validator."""

from __future__ import annotations

import io
from pathlib import Path
import pytest

from repomap_kg.artifacts import (
    ArtifactIntegrityError,
    FileSystemArtifactStore,
    PublicationBundle,
    PublicationExpectation,
    PublisherBundleValidator,
)
from repomap_kg.artifacts._bundle_stream import (
    BoundedExternalRowSorter,
    DiskFamilyLinkValidator,
    StreamingBundleEncoder,
    StreamingBundleParser,
)
from repomap_kg.artifacts._canonical import canonical_json
from repomap_kg.artifacts.bundle import (
    MAX_BUNDLE_LINE_BYTES,
)
from repomap_kg.artifacts.receipt import ExtractionReceipt
from repomap_kg.storage.portable_ingestion import prepare_portable_bundle_rows
from repomap_kg.storage.staging_family_contracts import PrivacyClassification
from repomap_kg.storage.staging_family_rows import StageFamily

VECTOR = (("bind1:" + "1" * 64, 1, "snap1:" + "2" * 64),)


def _base_families() -> dict[StageFamily, tuple[dict[str, object], ...]]:
    return {
        "files": ({"family_ordinal": 0, "path": "entry::f.nix", "language": "nix", "role": "source", "confidence": "exact", "content_hash": "sha256:" + "a" * 64, "executable": False, "generated": False, "metadata_json": {"binding_id": VECTOR[0][0]}, "stage_id": "stage-unassigned"},),
        "raw_observations": ({"source_ordinal": 0, "schema_version": 1, "kind": "nix.input", "source_id": "obs1", "path": "entry::f.nix", "payload_json": {"source_binding_id": VECTOR[0][0]}, "payload_hash": "sha256:" + "b" * 64, "stage_id": "stage-unassigned"},),
        "canonical_nodes": ({"family_ordinal": 0, "graph_key_version": 1, "canonical_key": "file:entry::f.nix", "kind": "File", "display_name": "f.nix", "metadata_json": {"source_binding_id": VECTOR[0][0]}, "confidence": "exact", "conflict": False, "stage_id": "stage-unassigned"},),
        "canonical_edges": ({"family_ordinal": 0, "graph_key_version": 1, "source_canonical_key": "file:entry::f.nix", "edge_kind": "depends_on", "target_canonical_key": "file:entry::f.nix", "identity_metadata_hash": "sha256:" + "c" * 64, "stage_id": "stage-unassigned"},),
        "canonical_evidence": ({"family_ordinal": 0, "graph_key_version": 1, "evidence_key": "ev:1", "raw_observation_ordinal": 0, "raw_schema_version": 1, "raw_kind": "nix.input", "raw_source_id": "obs1", "path": "entry::f.nix", "start_line": 1, "end_line": 1, "extractor": "nix", "extractor_version": "1", "confidence": "exact", "metadata_json": {"source_binding_id": VECTOR[0][0]}, "stage_id": "stage-unassigned"},),
        "canonical_node_evidence": ({"family_ordinal": 0, "graph_key_version": 1, "canonical_key": "file:entry::f.nix", "evidence_key": "ev:1", "link_kind": "supports", "stage_id": "stage-unassigned"},),
        "canonical_edge_evidence": ({"family_ordinal": 0, "graph_key_version": 1, "source_canonical_key": "file:entry::f.nix", "edge_kind": "depends_on", "target_canonical_key": "file:entry::f.nix", "identity_metadata_hash": "sha256:" + "c" * 64, "evidence_key": "ev:1", "link_kind": "supports", "stage_id": "stage-unassigned"},),
    }


def _make_bundle(families=None, row_stage_contract="stage-unassigned-v1"):
    return PublicationBundle.create(
        request_id="req-1", job_id="job-1", attempt=1, graph_id="graph-a",
        candidate_id="cand1:" + "3" * 64, snapshot_manifest_id="snap1:" + "4" * 64,
        snapshot_vector=VECTOR, source_generation="sg1:" + "5" * 64,
        config_generation="cg1:" + "6" * 64, extractor_generation="eg1:" + "7" * 64,
        canonicalizer_generation="kg1:" + "8" * 64,
        extractor_capability_identity="cap1:python-static-v1",
        resolver_identity="resolver1:nix-static-v2",
        canonicalizer_identity="canon1:graph-key-v1-binding-path",
        semantic_contract_identity="semantic1:multi-source-v1",
        quality_rule_identity="quality1:default",
        privacy=PrivacyClassification.CANONICAL_PROVENANCE,
        families=families or _base_families(), row_stage_contract=row_stage_contract,
    )


def _make_encoder(families=None, row_stage_contract="stage-unassigned-v1", spool_dir=None, **kwargs):
    return StreamingBundleEncoder(
        request_id="req-1", job_id="job-1", attempt=1, graph_id="graph-a",
        candidate_id="cand1:" + "3" * 64, snapshot_manifest_id="snap1:" + "4" * 64,
        snapshot_vector=VECTOR, source_generation="sg1:" + "5" * 64,
        config_generation="cg1:" + "6" * 64, extractor_generation="eg1:" + "7" * 64,
        canonicalizer_generation="kg1:" + "8" * 64,
        extractor_capability_identity="cap1:python-static-v1",
        resolver_identity="resolver1:nix-static-v2",
        canonicalizer_identity="canon1:graph-key-v1-binding-path",
        semantic_contract_identity="semantic1:multi-source-v1",
        quality_rule_identity="quality1:default",
        privacy=PrivacyClassification.CANONICAL_PROVENANCE,
        family_rows=families or _base_families(), row_stage_contract=row_stage_contract,
        spool_dir=spool_dir, **kwargs,
    )


def _make_receipt(bundle_ref, bundle_val):
    return ExtractionReceipt.create(
        request_id="req-1", job_id="job-1", attempt=1, graph_id="graph-a",
        worker_capability_identity="cap1:portable-worker-v1", contract_version="1.0",
        source_generation=bundle_val.source_generation, config_generation=bundle_val.config_generation,
        extractor_generation=bundle_val.extractor_generation,
        canonicalizer_generation=bundle_val.canonicalizer_generation,
        snapshot_manifest_id=bundle_val.snapshot_manifest_id,
        snapshot_vector=bundle_val.snapshot_vector, resolver_identity=bundle_val.resolver_identity,
        extractor_capability_identity=bundle_val.extractor_capability_identity,
        canonicalizer_identity=bundle_val.canonicalizer_identity,
        semantic_contract_identity=bundle_val.semantic_contract_identity,
        quality_rule_identity=bundle_val.quality_rule_identity,
        outcome="completed", cancellation="not-requested",
        bundle_reference=bundle_ref, bundle_id=bundle_val.bundle_id,
        family_counts=bundle_val.family_counts, diagnostic_category=None,
        diagnostic_summary=(), producer_identity="producer1:conformance-python",
        attestation_class="untrusted-self-assertion",
    )


def _make_expectation(bundle_val):
    return PublicationExpectation(
        request_id=bundle_val.request_id, job_id=bundle_val.job_id, attempt=bundle_val.attempt,
        graph_id=bundle_val.graph_id, candidate_id=bundle_val.candidate_id,
        snapshot_manifest_id=bundle_val.snapshot_manifest_id,
        snapshot_vector=bundle_val.snapshot_vector,
        source_generation=bundle_val.source_generation, config_generation=bundle_val.config_generation,
        extractor_generation=bundle_val.extractor_generation,
        canonicalizer_generation=bundle_val.canonicalizer_generation,
        extractor_capability_identity=bundle_val.extractor_capability_identity,
        resolver_identity=bundle_val.resolver_identity,
        canonicalizer_identity=bundle_val.canonicalizer_identity,
        semantic_contract_identity=bundle_val.semantic_contract_identity,
        quality_rule_identity=bundle_val.quality_rule_identity, mutating_owner_count=1,
        worker_capability_identity="cap1:portable-worker-v1",
        expected_privacy=bundle_val.privacy.value,
    )


def test_streaming_encoder_byte_for_byte_parity_with_publication_bundle():
    bundle = _make_bundle()
    expected_bytes = bundle.canonical_bytes()
    encoder = _make_encoder()
    streamed_bytes = b"".join(encoder.stream_chunks())

    assert streamed_bytes == expected_bytes
    descriptor = encoder.descriptor()
    assert descriptor.bundle_id == bundle.bundle_id
    assert descriptor.total_bytes == len(expected_bytes)
    assert descriptor.family_counts == bundle.family_counts


def test_streaming_encoder_and_parser_legacy_absent_contract(tmp_path: Path):
    fams = _base_families()
    fams_stripped = {fam: tuple({k: v for k, v in r.items() if k != "stage_id"} for r in rows) for fam, rows in fams.items()}
    bundle = _make_bundle(families=fams_stripped, row_stage_contract="legacy-absent-v1")
    expected_bytes = bundle.canonical_bytes()
    encoder = _make_encoder(families=fams_stripped, row_stage_contract="legacy-absent-v1", spool_dir=tmp_path / "enc")
    streamed_bytes = b"".join(encoder.stream_chunks())
    assert streamed_bytes == expected_bytes

    store = FileSystemArtifactStore(tmp_path / "store")
    bundle_ref = store.put(streamed_bytes, media_type="application/x-repomap-publication-bundle-v1+jsonl", record_format="canonical-jsonl-v1", privacy=bundle.privacy)
    receipt = _make_receipt(bundle_ref, bundle)
    expectation = _make_expectation(bundle)
    parser = StreamingBundleParser(spool_dir=tmp_path / "spool")
    with store.open_stream(bundle_ref) as stream:
        validated = parser.parse_and_validate(stream, expectation, receipt, stage_id="stg-leg")
    assert validated.row_stage_contract == "legacy-absent-v1"
    assert validated.canonical_bytes() == expected_bytes
    prep = validated.to_prepared_stage_rows()
    assert all("stg-leg" in repr(r) for r in prep.family_rows["files"])
    prep.close()


def test_bounded_external_row_sorter_spill_and_merge(tmp_path: Path):
    rows = [{"path": f"entry::{i:04d}.nix", "stage_id": "stage-unassigned"} for i in reversed(range(50))]
    sorter = BoundedExternalRowSorter(max_buffer_bytes=200, spool_dir=tmp_path)
    lines = list(sorter.sort_family_records("files", rows))
    assert sorter.spill_run_count >= 2
    assert sorter.spill_bytes > 0
    sorter.close()

    assert len(lines) == 50
    expected_lines = [
        canonical_json({"family": "files", "frame": "record", "record": r})
        for r in sorted(rows, key=canonical_json)
    ]
    assert lines == expected_lines


def test_disk_family_link_validator_detects_violations(tmp_path: Path):
    with DiskFamilyLinkValidator(spool_dir=tmp_path) as val:
        val.record_raw_observation({"source_ordinal": 0})
        val.finish_family("raw_observations")
        val.record_canonical_node({"canonical_key": "node:1"})
        val.finish_family("canonical_nodes")
        val.record_canonical_edge({
            "source_canonical_key": "node:1", "edge_kind": "link",
            "target_canonical_key": "node:1", "identity_metadata_hash": "hash:1",
        })
        val.finish_family("canonical_edges")

        with pytest.raises(ValueError, match="semantic evidence reference"):
            val.record_and_validate_evidence({"raw_observation_ordinal": 99, "evidence_key": "ev:1"})
        val.record_and_validate_evidence({"raw_observation_ordinal": 0, "evidence_key": "ev:1"})
        val.finish_family("canonical_evidence")

        with pytest.raises(ValueError, match="semantic node evidence reference"):
            val.validate_node_evidence({"canonical_key": "node:99", "evidence_key": "ev:1"})
        val.validate_node_evidence({"canonical_key": "node:1", "evidence_key": "ev:1"})
        val.finish_family("canonical_node_evidence")

        with pytest.raises(ValueError, match="semantic edge evidence reference"):
            val.validate_edge_evidence({
                "source_canonical_key": "node:1", "edge_kind": "missing",
                "target_canonical_key": "node:1", "identity_metadata_hash": "hash:1",
                "evidence_key": "ev:1",
            })


def test_streaming_bundle_parser_and_spool_preparation(tmp_path: Path):
    bundle = _make_bundle()
    bundle_bytes = bundle.canonical_bytes()
    store = FileSystemArtifactStore(tmp_path / "store")
    bundle_ref = store.put(
        bundle_bytes, media_type="application/x-repomap-publication-bundle-v1+jsonl",
        record_format="canonical-jsonl-v1", privacy=bundle.privacy,
    )
    receipt = _make_receipt(bundle_ref, bundle)
    expectation = _make_expectation(bundle)

    parser = StreamingBundleParser(spool_dir=tmp_path / "spool")
    with store.open_stream(bundle_ref) as stream:
        validated = parser.parse_and_validate(stream, expectation, receipt, stage_id="stage-test-1")

    assert validated.bundle_id == bundle.bundle_id
    assert validated.family_counts == bundle.family_counts
    assert validated.validation_result.byte_integrity_valid
    assert validated.validation_result.semantic_authority_valid

    prepared_expected = prepare_portable_bundle_rows(bundle, stage_id="stage-test-1")
    prepared_streamed = validated.to_prepared_stage_rows()

    assert prepared_streamed.row_counts == prepared_expected.row_counts
    assert prepared_streamed.normalized_byte_counts == prepared_expected.normalized_byte_counts
    for f in _base_families():
        assert list(prepared_streamed.family_rows[f]) == list(prepared_expected.family_rows[f])

    prepared_streamed.close()
    prepared_expected.close()


def test_streaming_bundle_parser_ordering_violations(tmp_path: Path):
    bundle = _make_bundle()
    lines = bundle.canonical_bytes().splitlines(keepends=True)
    store = FileSystemArtifactStore(tmp_path / "store")
    bundle_ref = store.put(bundle.canonical_bytes(), media_type="application/x-repomap-publication-bundle-v1+jsonl", record_format="canonical-jsonl-v1", privacy=bundle.privacy)
    receipt = _make_receipt(bundle_ref, bundle)
    expectation = _make_expectation(bundle)

    # 1. Intra-family record ordering violation (smaller content_hash placed second)
    record_smaller = {**_base_families()["files"][0], "content_hash": "sha256:" + "0" * 64}
    out_of_order = canonical_json({"family": "files", "frame": "record", "record": record_smaller})
    corrupt_stream = io.BytesIO(b"".join([lines[0], lines[1], out_of_order, *lines[2:]]))
    with pytest.raises(ValueError, match="publication bundle intra-family ordering is invalid"):
        StreamingBundleParser(spool_dir=tmp_path / "sp1").parse_and_validate(corrupt_stream, expectation, receipt)

    # 2. Family ordering violation (files row appearing under raw_observations)
    misplaced = canonical_json({"family": "files", "frame": "record", "record": _base_families()["files"][0]})
    corrupt_fam = io.BytesIO(b"".join([lines[0], lines[1], lines[2], misplaced, *lines[3:]]))
    with pytest.raises(ValueError, match="publication bundle family ordering is invalid"):
        StreamingBundleParser(spool_dir=tmp_path / "sp2").parse_and_validate(corrupt_fam, expectation, receipt)


def test_publisher_bundle_validator_stream_end_to_end(tmp_path: Path):
    bundle = _make_bundle()
    store = FileSystemArtifactStore(tmp_path / "store")
    bundle_ref = store.put(
        bundle.canonical_bytes(), media_type="application/x-repomap-publication-bundle-v1+jsonl",
        record_format="canonical-jsonl-v1", privacy=bundle.privacy,
    )
    receipt = _make_receipt(bundle_ref, bundle)
    receipt_ref = store.put(
        receipt.canonical_bytes(), media_type="application/x-repomap-extraction-receipt-v1+json",
        record_format="canonical-json-v1", privacy=bundle.privacy,
    )
    expectation = _make_expectation(bundle)

    validator = PublisherBundleValidator()
    desc1 = validator.validate_bundle_stream(
        store=store, bundle_reference=bundle_ref, receipt_reference=receipt_ref,
        expectation=expectation, stage_id="stage-1", spool_dir=tmp_path / "spool",
    )
    assert not desc1.validation_result.idempotent_replay
    assert desc1.bundle_id == bundle.bundle_id
    desc1.close()

    desc2 = validator.validate_bundle_stream(
        store=store, bundle_reference=bundle_ref, receipt_reference=receipt_ref,
        expectation=expectation, stage_id="stage-1", spool_dir=tmp_path / "spool",
    )
    assert desc2.validation_result.idempotent_replay
    desc2.close()


def test_store_stream_open_and_integrity_checks(tmp_path: Path):
    store = FileSystemArtifactStore(tmp_path / "store")
    chunks = [b"chunk-1\n", b"chunk-2\n"]
    ref = store.put(chunks, media_type="application/octet-stream", record_format="bytes-v1", privacy=PrivacyClassification.PUBLIC)
    assert store.read(ref) == b"chunk-1\nchunk-2\n"

    # Full stream read
    with store.open_stream(ref) as s:
        assert s.read() == b"chunk-1\nchunk-2\n"

    # Early exit before EOF raises ArtifactIntegrityError
    with pytest.raises(ArtifactIntegrityError, match="artifact stream verification incomplete"):
        with store.open_stream(ref) as s:
            assert s.read(4) == b"chun"

    # Truncated file on disk
    obj_path = store.object_path(ref)
    obj_path.write_bytes(b"chunk-1\n")
    with pytest.raises(ArtifactIntegrityError):
        with store.open_stream(ref) as s:
            s.read()

    # Extra bytes on disk
    obj_path.write_bytes(b"chunk-1\nchunk-2\nextra")
    with pytest.raises(ArtifactIntegrityError):
        with store.open_stream(ref) as s:
            s.read()


def test_streaming_bounds_refusals(tmp_path: Path):
    # Line length bound
    oversized = "a" * (MAX_BUNDLE_LINE_BYTES + 1)
    fams = _base_families()
    fams["files"] = ({"family_ordinal": 0, "path": oversized, "language": "nix", "role": "source", "confidence": "exact", "content_hash": "sha256:" + "a" * 64, "executable": False, "generated": False, "metadata_json": {}, "stage_id": "stage-unassigned"},)
    encoder = _make_encoder(families=fams, spool_dir=tmp_path / "sp")
    with pytest.raises(ValueError, match="publication bundle line bounds exceeded"):
        list(encoder.stream_chunks())

    # Parser max_bundle_bytes refusal
    bundle = _make_bundle()
    store = FileSystemArtifactStore(tmp_path / "store")
    ref = store.put(bundle.canonical_bytes(), media_type="application/x-repomap-publication-bundle-v1+jsonl", record_format="canonical-jsonl-v1", privacy=bundle.privacy)
    with pytest.raises(ArtifactIntegrityError, match="artifact bounds exceeded"):
        with store.open_stream(ref, max_bytes=10) as s:
            s.read()


def test_parser_refusal_and_spool_cleanup(tmp_path: Path):
    bundle = _make_bundle()
    lines = bundle.canonical_bytes().splitlines(keepends=True)
    store = FileSystemArtifactStore(tmp_path / "store")
    ref = store.put(bundle.canonical_bytes(), media_type="application/x-repomap-publication-bundle-v1+jsonl", record_format="canonical-jsonl-v1", privacy=bundle.privacy)
    receipt = _make_receipt(ref, bundle)
    expectation = _make_expectation(bundle)

    corrupt_line = canonical_json({"family": "canonical_nodes", "frame": "record", "record": {"invalid": True}})
    corrupt_data = b"".join([*lines[:3], corrupt_line, *lines[3:]])

    spool_dir = tmp_path / "spool_cleanup"
    spool_dir.mkdir(parents=True, exist_ok=True)
    parser = StreamingBundleParser(spool_dir=spool_dir)

    with pytest.raises(ValueError):
        parser.parse_and_validate(io.BytesIO(corrupt_data), expectation, receipt, stage_id="stg-clean")

    # Verify no leaked spool files remain
    assert not any(spool_dir.iterdir())


def test_parser_header_and_trailer_validation_refusals(tmp_path: Path):
    bundle = _make_bundle()
    lines = bundle.canonical_bytes().splitlines(keepends=True)
    store = FileSystemArtifactStore(tmp_path / "store")
    ref = store.put(bundle.canonical_bytes(), media_type="application/x-repomap-publication-bundle-v1+jsonl", record_format="canonical-jsonl-v1", privacy=bundle.privacy)
    receipt = _make_receipt(ref, bundle)
    expectation = _make_expectation(bundle)

    # 1. Unexpected header field
    hdr = dict(bundle.header_mapping())
    hdr["unauthorized_injected_field"] = "bad"
    stream_bad_hdr = io.BytesIO(b"".join([canonical_json(hdr), *lines[1:]]))
    with pytest.raises(ValueError, match="publication bundle framing is invalid"):
        StreamingBundleParser(spool_dir=tmp_path / "sp1").parse_and_validate(stream_bad_hdr, expectation, receipt)

    # 2. Corrupt trailer family summary
    trl = {"complete": True, "families": [{"byte_length": 999, "content_digest": "sha256:" + "0" * 64, "family": "files", "record_count": 99}], "frame": "trailer", "total_family_bytes": 999, "total_records": 99}
    stream_bad_trl = io.BytesIO(b"".join([*lines[:-1], canonical_json(trl)]))
    with pytest.raises(ValueError, match="publication bundle summary is inconsistent"):
        StreamingBundleParser(spool_dir=tmp_path / "sp2").parse_and_validate(stream_bad_trl, expectation, receipt)
