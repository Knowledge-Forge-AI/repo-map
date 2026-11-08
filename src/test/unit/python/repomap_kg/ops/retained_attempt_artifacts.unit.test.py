"""Bounded retained manifest, receipt, and bundle proof matrices."""

from __future__ import annotations

from io import BytesIO
import hashlib
import json
from types import SimpleNamespace
from typing import cast
from unittest import mock

import pytest

from common_lore_index.artifacts._canonical import canonical_json
from common_lore_index.artifacts.bundle import PUBLICATION_FAMILIES
from common_lore_index.ops import _retained_attempt_artifacts as artifacts


VECTOR = (("bind1:" + "1" * 64, 1, "snap1:" + "2" * 64),)
MANIFEST_ID = "snapmanifest1:" + "3" * 64
CANDIDATE_ID = "cand1:" + "4" * 64


def _evidence() -> tuple[SimpleNamespace, SimpleNamespace]:
    manifest = SimpleNamespace(
        graph_id="graph-a",
        source_generation="sg1:" + "5" * 64,
        config_generation="cg1:" + "6" * 64,
        extractor_generation="eg1:" + "7" * 64,
        canonicalizer_generation="kg1:" + "8" * 64,
        extractor_capability_identity="cap1:test",
        resolver_identity="resolver1:test",
        canonicalizer_identity="canon1:test",
        semantic_contract_identity="semantic1:test",
        quality_rule_identity="quality1:test",
        snapshot_vector=VECTOR,
        manifest_id=MANIFEST_ID,
        effective_privacy=SimpleNamespace(value="public"),
    )
    receipt = SimpleNamespace(
        graph_id="graph-a",
        source_generation=manifest.source_generation,
        config_generation=manifest.config_generation,
        extractor_generation=manifest.extractor_generation,
        canonicalizer_generation=manifest.canonicalizer_generation,
        resolver_identity=manifest.resolver_identity,
        canonicalizer_identity=manifest.canonicalizer_identity,
        semantic_contract_identity=manifest.semantic_contract_identity,
        quality_rule_identity=manifest.quality_rule_identity,
        snapshot_vector=VECTOR,
        snapshot_manifest_id=MANIFEST_ID,
        extractor_capability_identity="cap1:test",
        attempt=1,
        request_id="request-1",
        job_id="job-1",
        contract_version="1.0",
        worker_capability_identity="cap1:test",
        outcome="completed",
        cancellation="not-requested",
        bundle_reference=None,
        bundle_id=None,
        family_counts={family: 0 for family in PUBLICATION_FAMILIES},
    )
    return manifest, receipt


def _bundle_bytes(receipt: SimpleNamespace) -> tuple[bytes, str, str]:
    header = {
        "attempt": 1,
        "candidate_id": CANDIDATE_ID,
        "canonicalizer_generation": receipt.canonicalizer_generation,
        "canonicalizer_identity": receipt.canonicalizer_identity,
        "config_generation": receipt.config_generation,
        "extractor_capability_identity": "cap1:test",
        "extractor_generation": receipt.extractor_generation,
        "frame": "header",
        "framing_version": "repomap-publication-bundle-jsonl-v1",
        "graph_id": receipt.graph_id,
        "job_id": receipt.job_id,
        "privacy": "public",
        "quality_rule_identity": receipt.quality_rule_identity,
        "request_id": receipt.request_id,
        "resolver_identity": receipt.resolver_identity,
        "schema_version": 1,
        "semantic_contract_identity": receipt.semantic_contract_identity,
        "snapshot_manifest_id": MANIFEST_ID,
        "snapshot_vector": [list(item) for item in VECTOR],
        "source_generation": receipt.source_generation,
    }
    trailer = {
        "complete": True,
        "families": [
            {"byte_length": 0, "content_digest": "sha256:" + hashlib.sha256().hexdigest(), "family": family, "record_count": 0}
            for family in PUBLICATION_FAMILIES
        ],
        "frame": "trailer",
        "total_family_bytes": 0,
        "total_records": 0,
    }
    data = canonical_json(header) + canonical_json(trailer)
    return (
        data,
        "bundle1:" + hashlib.sha256(b"repomap-publication-bundle-v1\x00" + data).hexdigest(),
        "sha256:" + hashlib.sha256(data).hexdigest(),
    )


class _Store:
    def __init__(self, bundle: bytes, bundle_ref: object) -> None:
        self.bundle = bundle
        self.bundle_ref = bundle_ref
        self.bounds: list[int | None] = []

    def read(self, reference: object, *, max_bytes: int | None = None) -> bytes:
        self.bounds.append(max_bytes)
        return b"object"

    def open_stream(self, reference: object, *, max_bytes: int | None = None) -> BytesIO:
        self.bounds.append(max_bytes)
        return BytesIO(self.bundle)


def _read(record: SimpleNamespace, store: _Store) -> artifacts.RetainedArtifactProof:
    return artifacts.read_retained_artifacts(
        cast(artifacts.RetainedRecord, record), cast(artifacts.FileSystemArtifactStore, store),
    )


def test_header_rejects_boolean_snapshot_revision() -> None:
    manifest, receipt = _evidence()
    proof = artifacts.RetainedArtifactProof(
        cast(artifacts.PortableSnapshotManifest, manifest),
        cast(artifacts.ExtractionReceipt, receipt), "", "", (),
    )
    header = {
        "attempt": 1,
        "candidate_id": CANDIDATE_ID,
        "canonicalizer_generation": receipt.canonicalizer_generation,
        "canonicalizer_identity": receipt.canonicalizer_identity,
        "config_generation": receipt.config_generation,
        "extractor_capability_identity": "cap1:test",
        "extractor_generation": receipt.extractor_generation,
        "frame": "header",
        "framing_version": "repomap-publication-bundle-jsonl-v1",
        "graph_id": receipt.graph_id,
        "job_id": receipt.job_id,
        "privacy": "public",
        "quality_rule_identity": receipt.quality_rule_identity,
        "request_id": receipt.request_id,
        "resolver_identity": receipt.resolver_identity,
        "schema_version": 1,
        "semantic_contract_identity": receipt.semantic_contract_identity,
        "snapshot_manifest_id": MANIFEST_ID,
        "snapshot_vector": [[VECTOR[0][0], True, VECTOR[0][2]]],
        "source_generation": receipt.source_generation,
    }

    with pytest.raises(artifacts.RetainedArtifactError, match="bundle-invalid"):
        artifacts._header(proof, header)


def test_stream_proof_hashes_trailer_and_applies_existing_receipt_bound() -> None:
    manifest, receipt = _evidence()
    bundle, bundle_id, digest = _bundle_bytes(receipt)
    bundle_ref = SimpleNamespace(content_digest=digest, size_bytes=len(bundle))
    receipt.bundle_reference = bundle_ref
    receipt.bundle_id = bundle_id
    record = SimpleNamespace(
        payload={"manifest_id": MANIFEST_ID},
        references=(SimpleNamespace(), SimpleNamespace(), bundle_ref),
    )
    store = _Store(bundle, bundle_ref)

    with mock.patch.object(artifacts.PortableSnapshotManifest, "from_bytes", return_value=manifest):
        with mock.patch.object(artifacts.ExtractionReceipt, "from_bytes", return_value=receipt):
            proof = _read(record, store)

    assert proof.candidate_id == CANDIDATE_ID
    assert store.bounds[0] == artifacts.DEFAULT_ARTIFACT_LIMITS.max_manifest_bytes
    assert store.bounds[1] == artifacts.DEFAULT_ARTIFACT_LIMITS.max_manifest_bytes
    assert store.bounds[2] == artifacts.STREAMING_MAX_BUNDLE_BYTES

    without_trailer_digest = "sha256:" + hashlib.sha256(bundle.splitlines(keepends=True)[0]).hexdigest()
    bad_ref = SimpleNamespace(content_digest=without_trailer_digest, size_bytes=len(bundle))
    receipt.bundle_reference = bad_ref
    record.references = (SimpleNamespace(), SimpleNamespace(), bad_ref)
    with mock.patch.object(artifacts.PortableSnapshotManifest, "from_bytes", return_value=manifest):
        with mock.patch.object(artifacts.ExtractionReceipt, "from_bytes", return_value=receipt):
            with pytest.raises(artifacts.RetainedArtifactError, match="bundle-mismatch"):
                _read(record, _Store(bundle, bad_ref))


@pytest.mark.parametrize("case", [
    "extra-header", "bad-header-frame", "missing-trailer", "trailing-frame",
    "boolean-summary", "missing-family", "unknown-record-family", "wrong-stage",
    "oversize-line", "observed-cancellation",
])
def test_invalid_retained_framing_or_terminal_state_is_held(case: str) -> None:
    manifest, receipt = _evidence()
    bundle, _bundle_id, _digest = _bundle_bytes(receipt)
    header_bytes, trailer_bytes = bundle.splitlines(keepends=True)
    header = json.loads(header_bytes)
    trailer = json.loads(trailer_bytes)
    middle = b""
    if case == "extra-header":
        header["unknown"] = "untrusted"
    elif case == "bad-header-frame":
        header["frame"] = "record"
    elif case == "boolean-summary":
        trailer["families"][0]["record_count"] = True
    elif case == "missing-family":
        trailer["families"].pop()
    elif case == "unknown-record-family":
        middle = canonical_json({"frame": "record", "family": "unknown", "record": {}})
    elif case == "wrong-stage":
        header["row_stage_contract"] = "stage-unassigned-v1"
        middle = canonical_json({"frame": "record", "family": "files", "record": {"stage_id": "other"}})
    elif case == "oversize-line":
        middle = b"x" * (artifacts.MAX_BUNDLE_LINE_BYTES + 1) + b"\n"
    elif case == "observed-cancellation":
        receipt.cancellation = "observed"
    bundle = canonical_json(header) + middle + canonical_json(trailer)
    if case == "missing-trailer":
        bundle = canonical_json(header)
    elif case == "trailing-frame":
        bundle += canonical_json({"frame": "unexpected"})
    reference = SimpleNamespace(
        content_digest="sha256:" + hashlib.sha256(bundle).hexdigest(), size_bytes=len(bundle),
    )
    receipt.bundle_reference = reference
    receipt.bundle_id = "bundle1:" + hashlib.sha256(b"repomap-publication-bundle-v1\x00" + bundle).hexdigest()
    record = SimpleNamespace(
        payload={"manifest_id": MANIFEST_ID}, references=(SimpleNamespace(), SimpleNamespace(), reference),
    )
    with mock.patch.object(artifacts.PortableSnapshotManifest, "from_bytes", return_value=manifest), \
        mock.patch.object(artifacts.ExtractionReceipt, "from_bytes", return_value=receipt):
        with pytest.raises(artifacts.RetainedArtifactError):
            _read(record, _Store(bundle, reference))
