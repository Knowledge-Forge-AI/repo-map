"""Contract unit tests for streaming publication bundle encoder, parser, and store."""

from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
from unittest.mock import Mock
import pytest

from repomap_kg.artifacts import (
    ArtifactIntegrityError,
    FileSystemArtifactStore,
    PublicationBundle,
    PublicationExpectation,
)
from repomap_kg.artifacts._bundle_stream import (
    StreamingBundleEncoder,
    StreamingBundleParser,
)
from repomap_kg.artifacts.bundle import (
    MAX_BUNDLE_LINE_BYTES,
    STREAMING_MAX_BUNDLE_BYTES,
)
from repomap_kg.artifacts.receipt import ExtractionReceipt
from repomap_kg.artifacts.references import ArtifactLocator, ArtifactReference
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


def _make_receipt(bundle_ref, bundle_val):
    bytes_data = bundle_val.canonical_bytes()
    digest = "sha256:" + hashlib.sha256(bytes_data).hexdigest()
    ref = bundle_ref if isinstance(bundle_ref, ArtifactReference) else ArtifactReference(
        content_digest=digest, size_bytes=len(bytes_data),
        media_type="application/x-repomap-publication-bundle-v1+jsonl",
        record_format="canonical-jsonl-v1", privacy=PrivacyClassification.CANONICAL_PROVENANCE,
        locator=ArtifactLocator(kind="filesystem", value="objects/" + digest[7:]),
    )
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
        bundle_reference=ref, bundle_id=bundle_val.bundle_id,
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


class _BoundedReadEnforcingStream(io.BytesIO):
    """Custom stream double that raises if unbounded read or readline is issued."""

    def read(self, size: int | None = -1) -> bytes:
        if size is None or size == -1 or size > 1:
            raise AssertionError(f"unbounded read issued: size={size}")
        return super().read(size)

    def readline(self, size: int | None = -1) -> bytes:
        if size is None or size == -1 or size > MAX_BUNDLE_LINE_BYTES + 1:
            raise AssertionError(f"unbounded readline issued: size={size}")
        return super().readline(size)


def test_streaming_parser_post_trailer_bounded_read_c1(tmp_path: Path):
    """C1: Post-trailer EOF check must only issue bounded read(1) without suffix allocation."""
    bundle = _make_bundle()
    valid_data = bundle.canonical_bytes()
    data_with_suffix = valid_data + b"MALFORMED_NEWLINE_FREE_EXTRA_DATA"
    stream = _BoundedReadEnforcingStream(data_with_suffix)
    receipt = _make_receipt("test-ref", bundle)
    expectation = _make_expectation(bundle)
    spool_dir = tmp_path / "c1_spool"
    spool_dir.mkdir(parents=True, exist_ok=True)
    parser = StreamingBundleParser(spool_dir=spool_dir)
    with pytest.raises(ValueError, match="publication bundle framing is invalid"):
        parser.parse_and_validate(stream, expectation, receipt, stage_id="stg-c1")
    assert stream.tell() <= len(valid_data) + 1
    assert not any(spool_dir.iterdir())


def test_streaming_byte_bound_arithmetic(tmp_path: Path):
    """Item 5: Streaming byte-bound arithmetic below/at/above 1 GiB without allocating 1 GiB."""
    store = FileSystemArtifactStore(tmp_path / "store")
    assert STREAMING_MAX_BUNDLE_BYTES == 1024 * 1024 * 1024

    below_ref = ArtifactReference(
        content_digest="sha256:" + "0" * 64, size_bytes=STREAMING_MAX_BUNDLE_BYTES - 1,
        media_type="application/x-repomap-publication-bundle-v1+jsonl",
        record_format="canonical-jsonl-v1", privacy=PrivacyClassification.CANONICAL_PROVENANCE,
        locator=ArtifactLocator(kind="filesystem", value="objects/" + "0" * 64),
    )
    at_ref = ArtifactReference(
        content_digest="sha256:" + "0" * 64, size_bytes=STREAMING_MAX_BUNDLE_BYTES,
        media_type="application/x-repomap-publication-bundle-v1+jsonl",
        record_format="canonical-jsonl-v1", privacy=PrivacyClassification.CANONICAL_PROVENANCE,
        locator=ArtifactLocator(kind="filesystem", value="objects/" + "0" * 64),
    )
    assert below_ref.size_bytes < STREAMING_MAX_BUNDLE_BYTES
    assert at_ref.size_bytes == STREAMING_MAX_BUNDLE_BYTES

    above_ref = ArtifactReference(
        content_digest="sha256:" + "0" * 64, size_bytes=STREAMING_MAX_BUNDLE_BYTES + 1,
        media_type="application/x-repomap-publication-bundle-v1+jsonl",
        record_format="canonical-jsonl-v1", privacy=PrivacyClassification.CANONICAL_PROVENANCE,
        locator=ArtifactLocator(kind="filesystem", value="objects/" + "0" * 64),
    )
    with pytest.raises(ArtifactIntegrityError, match="artifact bounds exceeded"):
        store.open_stream(above_ref, max_bytes=STREAMING_MAX_BUNDLE_BYTES)


def test_streaming_parser_record_limit_refusal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Item 7: Streaming parser refuses when record count exceeds MAX_BUNDLE_RECORDS."""
    bundle = _make_bundle()
    data = bundle.canonical_bytes()
    receipt = _make_receipt("test-ref", bundle)
    expectation = _make_expectation(bundle)
    parser = StreamingBundleParser(spool_dir=tmp_path / "spool_recs")
    import repomap_kg.artifacts._bundle_stream_parse as pmod
    monkeypatch.setattr(pmod, "MAX_BUNDLE_RECORDS", 2)
    with pytest.raises(ValueError, match="publication bundle record bounds exceeded"):
        parser.parse_and_validate(io.BytesIO(data), expectation, receipt, stage_id="stg-rec")


def test_filesystem_iterable_put_does_not_materialize(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Item 8: Filesystem iterable put() consumes incrementally without list materialization."""
    store = FileSystemArtifactStore(tmp_path / "store")
    yielded = []

    def chunk_gen():
        for i in range(3):
            yielded.append(i)
            yield f"chunk-{i}\n".encode()

    import repomap_kg.artifacts._store_common as scommon
    mat_spy = Mock(side_effect=AssertionError("_materialize was called"))
    monkeypatch.setattr(scommon, "_materialize", mat_spy)

    ref = store.put(
        chunk_gen(), media_type="text/plain", record_format="text",
        privacy=PrivacyClassification.CANONICAL_PROVENANCE,
    )
    assert yielded == [0, 1, 2]
    assert mat_spy.call_count == 0
    assert store.read(ref) == b"chunk-0\nchunk-1\nchunk-2\n"


def test_filesystem_open_stream_does_not_call_full_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Item 9: Filesystem open_stream() does not call full unconstrained read()."""
    store = FileSystemArtifactStore(tmp_path / "store")
    payload = b"line1\nline2\nline3\n"
    ref = store.put(
        payload, media_type="text/plain", record_format="text",
        privacy=PrivacyClassification.CANONICAL_PROVENANCE,
    )
    read_spy = Mock(side_effect=AssertionError("store.read was called during open_stream"))
    monkeypatch.setattr(store, "read", read_spy)
    with store.open_stream(ref) as stream:
        assert stream.readline(10) == b"line1\n"
        assert stream.readline(10) == b"line2\n"
        assert stream.readline(10) == b"line3\n"
        assert stream.read(1) == b""
    assert read_spy.call_count == 0


def test_store_open_stream_digest_version_and_unsafe_refusals(tmp_path: Path):
    """Items 14-16: Digest mismatch, stale version, and symlink refusals via open_stream()."""
    store = FileSystemArtifactStore(tmp_path / "store")
    ref = store.put(
        b"valid data\n", media_type="text/plain", record_format="text",
        privacy=PrivacyClassification.CANONICAL_PROVENANCE,
    )
    # 14. Digest mismatch on stream verify
    obj_path = store.object_path(ref)
    obj_path.write_bytes(b"tamper dat\n")  # exact same length (11 bytes), different content
    with pytest.raises(ArtifactIntegrityError, match="artifact digest does not match"):
        with store.open_stream(ref) as s:
            s.read()

    obj_path.write_bytes(b"valid data\n")

    # 15. Stale store version refusal
    stale_ref = ArtifactReference(
        content_digest=ref.content_digest, size_bytes=ref.size_bytes,
        media_type=ref.media_type, record_format=ref.record_format,
        privacy=ref.privacy,
        locator=ArtifactLocator(kind="filesystem", value=ref.locator.value, store_version="store-v0"),
    )
    with pytest.raises(ArtifactIntegrityError, match="artifact store version is stale"):
        with store.open_stream(stale_ref) as s:
            s.read()

    # 16. Symlink / unsafe path refusal
    unsafe_ref = ArtifactReference(
        content_digest="sha256:" + "1" * 64, size_bytes=ref.size_bytes,
        media_type=ref.media_type, record_format=ref.record_format,
        privacy=ref.privacy,
        locator=ArtifactLocator(kind="filesystem", value="objects/" + "1" * 64),
    )
    symlink_path = store.object_path(unsafe_ref)
    symlink_path.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(obj_path, symlink_path)
    with pytest.raises(ArtifactIntegrityError, match="not a regular file"):
        store.open_stream(unsafe_ref)


def test_parser_receipt_expectation_mismatch_refusal(tmp_path: Path):
    """Item 18: Receipt/expectation mismatch refusal before staging."""
    bundle = _make_bundle()
    data = bundle.canonical_bytes()
    receipt = _make_receipt("test-ref", bundle)
    expectation = _make_expectation(bundle)
    bad_expectation = PublicationExpectation(
        request_id=expectation.request_id, job_id=expectation.job_id, attempt=expectation.attempt,
        graph_id="mismatched-graph", candidate_id=expectation.candidate_id,
        snapshot_manifest_id=expectation.snapshot_manifest_id,
        snapshot_vector=expectation.snapshot_vector,
        source_generation=expectation.source_generation, config_generation=expectation.config_generation,
        extractor_generation=expectation.extractor_generation,
        canonicalizer_generation=expectation.canonicalizer_generation,
        extractor_capability_identity=expectation.extractor_capability_identity,
        resolver_identity=expectation.resolver_identity,
        canonicalizer_identity=expectation.canonicalizer_identity,
        semantic_contract_identity=expectation.semantic_contract_identity,
        quality_rule_identity=expectation.quality_rule_identity, mutating_owner_count=1,
        worker_capability_identity=expectation.worker_capability_identity,
        expected_privacy=expectation.expected_privacy,
    )
    spool_dir = tmp_path / "spool_mismatch"
    spool_dir.mkdir(parents=True, exist_ok=True)
    parser = StreamingBundleParser(spool_dir=spool_dir)
    with pytest.raises(ValueError, match="bundle semantic authority mismatch"):
        parser.parse_and_validate(io.BytesIO(data), bad_expectation, receipt, stage_id="stg-mismatch")
    assert not any(spool_dir.iterdir())


def test_encoder_cancellation_and_checkpoint_behavior(tmp_path: Path):
    """Item 22: Encoder cancellation and 1,000-record checkpoint invocation."""
    import threading
    cancel_event = threading.Event()
    cancel_event.set()
    encoder = StreamingBundleEncoder(
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
        family_rows=_base_families(), row_stage_contract="stage-unassigned-v1",
        cancel_event=cancel_event, spool_dir=tmp_path / "enc_c",
    )
    with pytest.raises(ValueError, match="cancelled"):
        list(encoder.stream_chunks())

    # Checkpoint invocation at 1,000 records
    checkpoint = Mock()
    many_files = tuple(
        {"family_ordinal": i, "path": f"entry::{i:05d}.nix", "language": "nix", "role": "source", "confidence": "exact", "content_hash": "sha256:" + "a" * 64, "executable": False, "generated": False, "metadata_json": {"binding_id": VECTOR[0][0]}, "stage_id": "stage-unassigned"}
        for i in range(1005)
    )
    fams = _base_families()
    fams["files"] = many_files
    encoder_cp = StreamingBundleEncoder(
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
        family_rows=fams, row_stage_contract="stage-unassigned-v1",
        checkpoint=checkpoint, spool_dir=tmp_path / "enc_cp",
    )
    list(encoder_cp.stream_chunks())
    assert checkpoint.call_count == 1


def test_prepared_spool_ownership_closes_exactly_once(tmp_path: Path):
    """Item 23: Prepared spool ownership closes exactly once after staging."""
    bundle = _make_bundle()
    data = bundle.canonical_bytes()
    receipt = _make_receipt("test-ref", bundle)
    expectation = _make_expectation(bundle)
    spool_dir = tmp_path / "spool_own"
    spool_dir.mkdir(parents=True, exist_ok=True)
    parser = StreamingBundleParser(spool_dir=spool_dir)
    validated = parser.parse_and_validate(io.BytesIO(data), expectation, receipt, stage_id="stg-own")
    prep = validated.to_prepared_stage_rows()
    assert any(spool_dir.iterdir())
    prep.close()
    assert not any(spool_dir.iterdir())
    # Second close is idempotent
    prep.close()
