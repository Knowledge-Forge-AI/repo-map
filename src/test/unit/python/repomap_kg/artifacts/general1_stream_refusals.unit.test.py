"""Streaming publication refuses malformed wire evidence and retires its spools."""
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path

import pytest

from repomap_kg.artifacts import PublicationExpectation
from repomap_kg.artifacts._bundle_stream import StreamingBundleParser
from repomap_kg.artifacts.receipt import ExtractionReceipt
from repomap_kg.artifacts.references import ArtifactLocator, ArtifactReference
from repomap_test_support.portable_publication_fixtures import _bundle


@pytest.fixture
def wire():
    bundle = _bundle()
    data = bundle.canonical_bytes()
    reference = ArtifactReference(
        "sha256:" + hashlib.sha256(data).hexdigest(), len(data),
        "application/x-repomap-publication-bundle-v1+jsonl", "canonical-jsonl-v1",
        bundle.privacy, ArtifactLocator("filesystem", "objects/fixture"),
    )
    names = (
        "request_id", "job_id", "attempt", "graph_id", "source_generation",
        "config_generation", "extractor_generation", "canonicalizer_generation",
        "snapshot_manifest_id", "snapshot_vector", "resolver_identity",
        "extractor_capability_identity", "canonicalizer_identity",
        "semantic_contract_identity", "quality_rule_identity",
    )
    receipt = ExtractionReceipt.create(
        **{name: getattr(bundle, name) for name in names},
        worker_capability_identity="cap1:portable-worker-v1", contract_version="1.0",
        outcome="completed", cancellation="not-requested", bundle_reference=reference,
        bundle_id=bundle.bundle_id, family_counts=bundle.family_counts,
        diagnostic_category=None, diagnostic_summary=(),
        producer_identity="producer1:fixture", attestation_class="untrusted-self-assertion",
    )
    return data, PublicationExpectation.from_bundle(bundle, mutating_owner_count=1), receipt


def _encode(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


@pytest.mark.parametrize("change,message", [
    ("empty", "framing is invalid"),
    ("unterminated-header", "framing is invalid"),
    ("wrong-first-frame", "framing is invalid"),
    ("unsupported-version", "unsupported publication bundle version"),
    ("unsupported-row-contract", "row stage contract is invalid"),
    ("unterminated-record", "line bounds exceeded"),
    ("unknown-frame", "record frame is invalid"),
    ("unknown-family", "family is invalid"),
    ("foreign-stage", "stage representation is ambiguous: stage identity"),
    ("legacy-staged-row", "legacy bundle stage representation is ambiguous"),
    ("missing-trailer", "framing is invalid"),
])
def test_streaming_wire_refusal_cleans_only_owned_spools(tmp_path, wire, change, message):
    data, expectation, receipt = wire
    frames = [json.loads(line) for line in data.splitlines()]
    if change == "empty":
        data = b""
    elif change == "unterminated-header":
        data = data.splitlines()[0]
    elif change == "unterminated-record":
        data = _encode(frames[0]) + _encode(frames[1]).rstrip(b"\n")
    elif change == "missing-trailer":
        data = b"".join(_encode(frame) for frame in frames[:-1])
    else:
        if change == "wrong-first-frame":
            frames[0]["frame"] = "record"
        elif change == "unsupported-version":
            frames[0]["schema_version"] = 2
        elif change == "unsupported-row-contract":
            frames[0]["row_stage_contract"] = "foreign-v1"
        elif change == "unknown-frame":
            frames[1]["frame"] = "unknown"
        elif change == "unknown-family":
            frames[1]["family"] = "unknown"
        elif change == "foreign-stage":
            frames[1]["record"]["stage_id"] = "stage-foreign"
        elif change == "legacy-staged-row":
            frames[0].pop("row_stage_contract")
        data = b"".join(_encode(frame) for frame in frames)
    spool = tmp_path / "owned-spools"
    sentinel = tmp_path / "unrelated.txt"
    sentinel.write_text("preserve")
    with pytest.raises(ValueError, match=message):
        StreamingBundleParser(spool_dir=spool).parse_and_validate(
            io.BytesIO(data), expectation, receipt, stage_id="stage-fixture",
        )
    assert not list(spool.iterdir())
    assert sentinel.read_text() == "preserve"


@pytest.mark.parametrize("authority,message", [
    ("multiple-owners", "exactly one mutating owner"),
    ("receipt-generation", "receipt semantic authority mismatch"),
    ("receipt-contract", "receipt contract version mismatch"),
    ("privacy", "bundle privacy mismatch"),
    ("cancellation", "terminal state is inconsistent"),
    ("bundle-digest", "terminal state is inconsistent"),
    ("content-digest", "terminal state is inconsistent"),
    ("family-counts", "terminal state is inconsistent"),
])
def test_streaming_authority_refusal_never_retains_prepared_rows(tmp_path, wire, authority, message):
    data, expectation, receipt = wire
    if authority == "multiple-owners":
        expectation = replace(expectation, mutating_owner_count=2)
    elif authority == "receipt-generation":
        receipt = replace(receipt, source_generation="sg1:" + "0" * 64).reidentify()
    elif authority == "receipt-contract":
        receipt = replace(receipt, contract_version="2.0").reidentify()
    elif authority == "privacy":
        expectation = replace(expectation, expected_privacy="public")
    elif authority == "cancellation":
        receipt = replace(receipt, cancellation="requested").reidentify()
    elif authority == "bundle-digest":
        receipt = replace(receipt, bundle_id="bundle1:" + "0" * 64).reidentify()
    elif authority == "content-digest":
        ref = replace(receipt.bundle_reference, content_digest="sha256:" + "0" * 64)
        receipt = replace(receipt, bundle_reference=ref).reidentify()
    elif authority == "family-counts":
        receipt = replace(receipt, family_counts={**receipt.family_counts, "files": 99}).reidentify()
    spool = tmp_path / "spools"
    with pytest.raises(ValueError, match=message):
        StreamingBundleParser(spool_dir=spool).parse_and_validate(
            io.BytesIO(data), expectation, receipt, stage_id="stage-fixture",
        )
    assert not list(spool.iterdir())


def test_stream_validation_without_staging_cannot_transfer_row_ownership(tmp_path: Path, wire):
    data, expectation, receipt = wire
    spool = tmp_path / "spools"
    descriptor = StreamingBundleParser(spool_dir=spool).parse_and_validate(
        io.BytesIO(data), expectation, receipt,
    )
    try:
        assert descriptor.bundle_id == receipt.bundle_id
        assert descriptor.validation_result.semantic_authority_valid
        with pytest.raises(ValueError, match="stage rows were not prepared"):
            descriptor.to_prepared_stage_rows()
    finally:
        descriptor.close()
    assert not list(spool.iterdir())
