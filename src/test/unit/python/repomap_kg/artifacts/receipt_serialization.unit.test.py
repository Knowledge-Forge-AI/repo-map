from __future__ import annotations

from dataclasses import replace
import json

import pytest

from repomap_kg.artifacts import (
    ExtractionReceipt,
    MemoryArtifactStore,
    PublicationBundle,
)
from repomap_kg.artifacts._canonical import (
    CanonicalEncodingError,
    canonical_json,
    decode_canonical_json,
    prefixed_digest,
    sha256_digest,
)
from repomap_kg.storage.staging_family_contracts import PrivacyClassification
from repomap_kg.storage.staging_family_rows import StageFamily


VECTOR = (("bind1:" + "1" * 64, 1, "snap1:" + "2" * 64),)
FAMILIES: dict[StageFamily, tuple[dict[str, object], ...]] = {
    "files": ({
        "family_ordinal": 0, "path": "entry::flake.nix", "language": "nix", "role": "source",
        "confidence": "exact", "content_hash": "sha256:" + "a" * 64, "executable": False,
        "generated": False, "metadata_json": {"binding_id": VECTOR[0][0], "snapshot_id": VECTOR[0][2]},
    },),
    "raw_observations": (),
    "canonical_nodes": (),
    "canonical_edges": (),
    "canonical_evidence": (),
    "canonical_node_evidence": (),
    "canonical_edge_evidence": (),
}


def bundle() -> PublicationBundle:
    return PublicationBundle.create(
        request_id="request-1", job_id="job-1", attempt=1, graph_id="graph-a",
        candidate_id="cand1:" + "3" * 64, snapshot_manifest_id="snapmanifest1:" + "4" * 64,
        snapshot_vector=VECTOR, source_generation="sg1:" + "5" * 64,
        config_generation="cg1:" + "6" * 64, extractor_generation="eg1:" + "7" * 64,
        canonicalizer_generation="kg1:" + "8" * 64,
        extractor_capability_identity="cap1:python-static-v1",
        resolver_identity="resolver1:nix-static-v2",
        canonicalizer_identity="canon1:graph-key-v1-binding-path",
        semantic_contract_identity="semantic1:multi-source-v1",
        quality_rule_identity="quality1:default",
        privacy=PrivacyClassification.CANONICAL_PROVENANCE,
        families=FAMILIES, row_stage_contract="legacy-absent-v1",
    )


def receipt(bundle_ref: object, value: PublicationBundle, *, outcome: str = "completed") -> ExtractionReceipt:
    from repomap_kg.artifacts.references import ArtifactReference

    return ExtractionReceipt.create(
        request_id="request-1", job_id="job-1", attempt=1, graph_id="graph-a",
        worker_capability_identity="cap1:portable-worker-v1", contract_version="1.0",
        source_generation=value.source_generation, config_generation=value.config_generation,
        extractor_generation=value.extractor_generation,
        canonicalizer_generation=value.canonicalizer_generation,
        snapshot_manifest_id=value.snapshot_manifest_id,
        snapshot_vector=value.snapshot_vector, resolver_identity=value.resolver_identity,
        extractor_capability_identity=value.extractor_capability_identity,
        canonicalizer_identity=value.canonicalizer_identity,
        semantic_contract_identity=value.semantic_contract_identity,
        quality_rule_identity=value.quality_rule_identity, outcome=outcome,
        cancellation="not-requested" if outcome == "completed" else "requested",
        bundle_reference=bundle_ref if outcome == "completed" and isinstance(bundle_ref, ArtifactReference) else None,
        bundle_id=value.bundle_id if outcome == "completed" else None,
        family_counts=value.family_counts if outcome == "completed" else {},
        diagnostic_category=None if outcome == "completed" else "source_unavailable",
        diagnostic_summary=() if outcome == "completed" else ("diagnostic summary",),
        producer_identity="producer1:conformance-python",
        attestation_class="untrusted-self-assertion",
    )


def put_bundle(store: MemoryArtifactStore, value: PublicationBundle):
    return store.put(
        value.canonical_bytes(),
        media_type="application/x-repomap-publication-bundle-v1+jsonl",
        record_format="canonical-jsonl-v1",
        privacy=value.privacy,
    )


def test_receipts_are_deterministic_for_completed_cancelled_failed_and_unsupported() -> None:
    store = MemoryArtifactStore()
    value = bundle()
    bundle_ref = put_bundle(store, value)

    completed = receipt(bundle_ref, value)
    assert ExtractionReceipt.from_bytes(completed.canonical_bytes()) == completed
    for outcome, category in (
        ("cancelled", "cancelled"),
        ("failed", "source_changed"),
        ("unsupported_contract", "unsupported_contract"),
        ("malformed_input", "contract_validation"),
    ):
        item = replace(
            receipt(bundle_ref, value, outcome="cancelled"),
            outcome=outcome,
            diagnostic_category=category,
        ).reidentify()
        assert ExtractionReceipt.from_bytes(item.canonical_bytes()) == item


@pytest.mark.parametrize(
    "category,public_category",
    [
        ("source_unavailable", "source_error"),
        ("source_changed", "source_error"),
        ("source_invalid", "source_error"),
        ("source_capture", "source_error"),
        ("cancelled", "cancelled"),
        ("contract_validation", "contract_error"),
    ],
)
def test_receipt_retains_exact_internal_class_with_explicit_public_projection(
    category: str, public_category: str
) -> None:
    store = MemoryArtifactStore()
    value = bundle()
    item = replace(
        receipt(put_bundle(store, value), value, outcome="cancelled"),
        outcome="failed",
        diagnostic_category=category,
    ).reidentify()

    assert item.diagnostic_category == category
    assert item.to_public_mapping()["error_category"] == public_category


def test_receipt_negative_validation_and_malformed_bytes() -> None:
    b = bundle()
    store = MemoryArtifactStore()
    b_ref = put_bundle(store, b)
    r = receipt(b_ref, b)
    raw = json.loads(r.canonical_bytes().decode("utf-8"))

    for bad in [dict(raw, schema_version=99), dict(raw, canonicalization_version="wrong-v2")]:
        with pytest.raises(ValueError, match="unsupported extraction receipt version"):
            ExtractionReceipt.from_bytes(canonical_json(bad))

    for bad in [
        dict(raw, bundle_reference="not-a-mapping"),
        dict(raw, snapshot_vector=[["bind", 1]]),
        dict(raw, family_counts="not-a-dict"),
        dict(raw, diagnostic_summary="not-a-list"),
    ]:
        with pytest.raises(ValueError, match="extraction receipt is malformed"):
            ExtractionReceipt.from_bytes(canonical_json(bad))

    extra_payload = canonical_json(dict(raw, unexpected_extra_field="spurious"))
    with pytest.raises(ValueError, match="extraction receipt is not canonical"):
        ExtractionReceipt.from_bytes(extra_payload)

    with pytest.raises(ValueError, match="receipt identity field is invalid"):
        ExtractionReceipt.create(
            request_id="", job_id="j", attempt=1, graph_id="g", worker_capability_identity="w",
            contract_version="1.0", source_generation="s", config_generation="c", extractor_generation="e",
            canonicalizer_generation="k", snapshot_manifest_id="m", snapshot_vector=VECTOR,
            resolver_identity="r", extractor_capability_identity="x", canonicalizer_identity="k",
            semantic_contract_identity="s", quality_rule_identity="q", outcome="completed",
            cancellation="not-requested", bundle_reference=b_ref, bundle_id=b.bundle_id,
            family_counts=b.family_counts, diagnostic_category=None, diagnostic_summary=(),
            producer_identity="p", attestation_class="a",
        )

    with pytest.raises(ValueError, match="receipt attempt is invalid"):
        replace(r, attempt=0).reidentify()
    with pytest.raises(ValueError, match="receipt outcome is invalid"):
        replace(r, outcome="unknown_outcome").reidentify()
    with pytest.raises(ValueError, match="receipt diagnostic category is invalid"):
        replace(r, outcome="failed", bundle_id=None, bundle_reference=None, family_counts={}, diagnostic_category="invalid_cat").reidentify()
    with pytest.raises(ValueError, match="receipt diagnostics exceed bounds"):
        replace(r, outcome="failed", bundle_id=None, bundle_reference=None, family_counts={}, diagnostic_category="semantic_workload", diagnostic_summary=tuple(str(i) for i in range(35))).reidentify()
    with pytest.raises(ValueError, match="completed receipt is inconsistent"):
        replace(r, bundle_id=None).reidentify()
    with pytest.raises(ValueError, match="non-completed receipt cannot accept a bundle"):
        replace(r, outcome="failed", diagnostic_category="semantic_workload").reidentify()
    with pytest.raises(ValueError, match="terminal receipt diagnostic is missing"):
        replace(r, outcome="failed", bundle_id=None, bundle_reference=None, family_counts={}, diagnostic_category=None).reidentify()
    with pytest.raises(ValueError, match="cancelled receipt cancellation state is invalid"):
        replace(r, outcome="cancelled", bundle_id=None, bundle_reference=None, family_counts={}, diagnostic_category="cancelled", cancellation="not-requested").reidentify()

    failed_r = replace(r, outcome="failed", bundle_id=None, bundle_reference=None, family_counts={}, diagnostic_category="source_unavailable").reidentify()
    pub = failed_r.to_public_mapping()
    assert pub["outcome"] == "failed"
    assert pub["error_category"] == "source_error"


def test_canonical_json_codec_contracts_and_rejections() -> None:
    encoded = canonical_json({"b": 2, "a": 1})
    assert encoded == b'{"a":1,"b":2}\n'
    assert decode_canonical_json(encoded) == {"a": 1, "b": 2}

    with pytest.raises(CanonicalEncodingError, match="floats"):
        canonical_json({"ratio": 3.14})

    with pytest.raises(CanonicalEncodingError, match="must be strings"):
        canonical_json({1: "integer-key"})

    with pytest.raises(CanonicalEncodingError, match="LF"):
        decode_canonical_json(b'{"a":1}')

    with pytest.raises(CanonicalEncodingError, match="root must be an object"):
        decode_canonical_json(b'[1,2,3]\n')

    with pytest.raises(CanonicalEncodingError, match="invalid") as float_err:
        decode_canonical_json(b'{"a":1.5}\n')
    assert "floats" in str(float_err.value.__cause__)

    with pytest.raises(CanonicalEncodingError, match="invalid") as dup_err:
        decode_canonical_json(b'{"a":1,"a":2}\n')
    assert "duplicate" in str(dup_err.value.__cause__)

    with pytest.raises(CanonicalEncodingError, match="not canonical"):
        decode_canonical_json(b'{"b": 2, "a": 1}\n')

    assert sha256_digest(b"test").startswith("sha256:")
    assert prefixed_digest("pref:", b"dom", b"content").startswith("pref:")
