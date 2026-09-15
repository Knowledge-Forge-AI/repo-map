from __future__ import annotations

from dataclasses import replace
from unittest.mock import Mock

import pytest

from repomap_kg.artifacts import (
    ExtractionReceipt,
    MemoryArtifactStore,
    PublicationBundle,
    PublicationExpectation,
    PublisherBundleValidator,
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
    "raw_observations": ({
        "source_ordinal": 0, "schema_version": 1, "kind": "nix.input_reference", "source_id": "obs1",
        "path": "entry::flake.nix",
        "payload_json": {
            "candidate_id": "cand1:" + "3" * 64, "resolution_outcome": "ambiguous",
            "resolution_evidence_class": "bounded-unknown", "source_binding_id": VECTOR[0][0],
        },
        "payload_hash": "sha256:" + "b" * 64,
    },),
    "canonical_nodes": ({
        "family_ordinal": 0, "graph_key_version": 1, "canonical_key": "file:entry::flake.nix",
        "kind": "File", "display_name": "flake.nix", "metadata_json": {"source_binding_id": VECTOR[0][0]},
        "confidence": "exact", "conflict": False,
    },),
    "canonical_edges": (),
    "canonical_evidence": ({
        "family_ordinal": 0, "graph_key_version": 1, "evidence_key": "evidence:1",
        "raw_observation_ordinal": 0, "raw_schema_version": 1, "raw_kind": "nix.input_reference",
        "raw_source_id": "obs1", "path": "entry::flake.nix", "start_line": 1, "end_line": 1,
        "extractor": "nix-static", "extractor_version": "1", "confidence": "exact",
        "metadata_json": {"source_binding_id": VECTOR[0][0]},
    },),
    "canonical_node_evidence": ({
        "family_ordinal": 0, "graph_key_version": 1, "canonical_key": "file:entry::flake.nix",
        "evidence_key": "evidence:1", "link_kind": "supports",
    },),
    "canonical_edge_evidence": (),
}


def bundle(
    *,
    families: dict[StageFamily, tuple[dict[str, object], ...]] = FAMILIES,
    candidate_id: str = "cand1:" + "3" * 64,
    row_stage_contract: str = "legacy-absent-v1",
) -> PublicationBundle:
    return PublicationBundle.create(
        request_id="request-1", job_id="job-1", attempt=1, graph_id="graph-a",
        candidate_id=candidate_id, snapshot_manifest_id="snapmanifest1:" + "4" * 64,
        snapshot_vector=VECTOR, source_generation="sg1:" + "5" * 64,
        config_generation="cg1:" + "6" * 64, extractor_generation="eg1:" + "7" * 64,
        canonicalizer_generation="kg1:" + "8" * 64,
        extractor_capability_identity="cap1:python-static-v1",
        resolver_identity="resolver1:nix-static-v2",
        canonicalizer_identity="canon1:graph-key-v1-binding-path",
        semantic_contract_identity="semantic1:multi-source-v1",
        quality_rule_identity="quality1:default",
        privacy=PrivacyClassification.CANONICAL_PROVENANCE,
        families=families, row_stage_contract=row_stage_contract,
    )


def receipt(bundle_ref: object, value: PublicationBundle) -> ExtractionReceipt:
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
        quality_rule_identity=value.quality_rule_identity, outcome="completed",
        cancellation="not-requested",
        bundle_reference=bundle_ref if isinstance(bundle_ref, ArtifactReference) else None,
        bundle_id=value.bundle_id,
        family_counts=value.family_counts,
        diagnostic_category=None,
        diagnostic_summary=(),
        producer_identity="producer1:conformance-python",
        attestation_class="untrusted-self-assertion",
    )


def expectation(value: PublicationBundle) -> PublicationExpectation:
    return PublicationExpectation.from_bundle(value, mutating_owner_count=1)


def put_bundle(store: MemoryArtifactStore, value: PublicationBundle):
    return store.put(
        value.canonical_bytes(),
        media_type="application/x-repomap-publication-bundle-v1+jsonl",
        record_format="canonical-jsonl-v1",
        privacy=value.privacy,
    )


def put_receipt(store: MemoryArtifactStore, value: ExtractionReceipt):
    return store.put(
        value.canonical_bytes(),
        media_type="application/x-repomap-extraction-receipt-v1+json",
        record_format="canonical-json-v1",
        privacy=PrivacyClassification.CANONICAL_PROVENANCE,
    )


def test_validator_family_links_invalid_evidence() -> None:
    store = MemoryArtifactStore()

    bad_families1 = dict(FAMILIES)
    bad_ev1 = list(FAMILIES["canonical_evidence"])
    bad_ev1[0] = dict(bad_ev1[0])
    bad_ev1[0]["raw_observation_ordinal"] = 9999
    bad_families1["canonical_evidence"] = tuple(bad_ev1)
    b1 = bundle(families=bad_families1)
    b1_ref = put_bundle(store, b1)
    r1 = receipt(b1_ref, b1)
    r1_ref = put_receipt(store, r1)
    with pytest.raises(ValueError, match="bundle semantic evidence reference is invalid"):
        PublisherBundleValidator().validate_bundle(
            store=store, bundle_reference=b1_ref, receipt_reference=r1_ref,
            expectation=PublicationExpectation.from_bundle(b1, mutating_owner_count=1),
        )

    bad_families2 = dict(FAMILIES)
    bad_ne2 = list(FAMILIES["canonical_node_evidence"])
    bad_ne2[0] = dict(bad_ne2[0])
    bad_ne2[0]["canonical_key"] = "file:missing.py"
    bad_families2["canonical_node_evidence"] = tuple(bad_ne2)
    b2 = bundle(families=bad_families2)
    b2_ref = put_bundle(store, b2)
    r2 = receipt(b2_ref, b2)
    r2_ref = put_receipt(store, r2)
    with pytest.raises(ValueError, match="bundle semantic node evidence reference is invalid"):
        PublisherBundleValidator().validate_bundle(
            store=store, bundle_reference=b2_ref, receipt_reference=r2_ref,
            expectation=PublicationExpectation.from_bundle(b2, mutating_owner_count=1),
        )

    bad_families3 = dict(FAMILIES)
    bad_families3["canonical_edge_evidence"] = ({
        "family_ordinal": 0, "graph_key_version": 1, "source_canonical_key": "file:a",
        "edge_kind": "imports", "target_canonical_key": "file:b", "identity_metadata_hash": None,
        "evidence_key": "evidence:1", "link_kind": "supports",
    },)
    b3 = bundle(families=bad_families3)
    b3_ref = put_bundle(store, b3)
    r3 = receipt(b3_ref, b3)
    r3_ref = put_receipt(store, r3)
    with pytest.raises(ValueError, match="bundle semantic edge evidence reference is invalid"):
        PublisherBundleValidator().validate_bundle(
            store=store, bundle_reference=b3_ref, receipt_reference=r3_ref,
            expectation=PublicationExpectation.from_bundle(b3, mutating_owner_count=1),
        )


def test_validator_terminal_receipt_and_attempt_transitions() -> None:
    store = MemoryArtifactStore()
    b = bundle()
    bundle_ref = put_bundle(store, b)

    term_receipt = ExtractionReceipt.create(
        request_id="request-1", job_id="job-1", attempt=1, graph_id="graph-a",
        worker_capability_identity="cap1:portable-worker-v1", contract_version="1.0",
        source_generation=b.source_generation, config_generation=b.config_generation,
        extractor_generation=b.extractor_generation, canonicalizer_generation=b.canonicalizer_generation,
        snapshot_manifest_id=b.snapshot_manifest_id, snapshot_vector=b.snapshot_vector,
        resolver_identity=b.resolver_identity, extractor_capability_identity=b.extractor_capability_identity,
        canonicalizer_identity=b.canonicalizer_identity, semantic_contract_identity=b.semantic_contract_identity,
        quality_rule_identity=b.quality_rule_identity, outcome="failed", cancellation="not-requested",
        bundle_reference=None, bundle_id=None, family_counts={}, diagnostic_category="semantic_workload",
        diagnostic_summary=("failure",), producer_identity="producer1:conformance-python",
        attestation_class="untrusted-self-assertion",
    )
    term_ref = put_receipt(store, term_receipt)
    mock_store = Mock()
    mock_store.read.return_value = term_receipt.canonical_bytes()
    bad_ref = replace(term_ref, content_digest="sha256:" + "0" * 64)
    validator = PublisherBundleValidator()
    with pytest.raises(ValueError, match="receipt byte integrity failed"):
        validator.validate_terminal_receipt(store=mock_store, receipt_reference=bad_ref)

    val_term = validator.validate_terminal_receipt(store=store, receipt_reference=term_ref)
    assert val_term.outcome == "failed"

    completed_receipt = receipt(bundle_ref, b)
    comp_ref = put_receipt(store, completed_receipt)
    with pytest.raises(ValueError, match="terminal receipt is not a non-completed attempt"):
        validator.validate_terminal_receipt(store=store, receipt_reference=comp_ref)

    exp = PublicationExpectation.from_bundle(b, mutating_owner_count=1)
    with pytest.raises(ValueError, match="non-completed attempt cannot become completed"):
        validator.validate_bundle(
            store=store, bundle_reference=bundle_ref, receipt_reference=comp_ref, expectation=exp,
        )

    validator2 = PublisherBundleValidator()
    validator2.validate_bundle(
        store=store, bundle_reference=bundle_ref, receipt_reference=comp_ref, expectation=exp,
    )
    replay_result = validator2.validate_bundle(
        store=store, bundle_reference=bundle_ref, receipt_reference=comp_ref, expectation=exp,
    )
    assert replay_result.idempotent_replay is True

    b2 = bundle(candidate_id="cand1:" + "9" * 64)
    b2_ref = put_bundle(store, b2)
    r2 = receipt(b2_ref, b2)
    r2_ref = put_receipt(store, r2)
    exp2 = PublicationExpectation.from_bundle(b2, mutating_owner_count=1)
    with pytest.raises(ValueError, match="conflicting attempt reuse"):
        validator2.validate_bundle(
            store=store, bundle_reference=b2_ref, receipt_reference=r2_ref, expectation=exp2,
        )


def test_validator_byte_integrity_and_receipt_bundle_linkage_mismatch() -> None:
    store = MemoryArtifactStore()
    b = bundle()
    b_ref = put_bundle(store, b)
    r = receipt(b_ref, b)
    r_ref = put_receipt(store, r)
    exp = expectation(b)
    validator = PublisherBundleValidator()

    mock_store = Mock()
    mock_store.read.side_effect = lambda ref: b.canonical_bytes() if ref.media_type.endswith("jsonl") else r.canonical_bytes()

    bad_b_ref = replace(b_ref, content_digest="sha256:" + "0" * 64)
    with pytest.raises(ValueError, match="bundle byte integrity failed"):
        validator.validate_bundle(store=mock_store, bundle_reference=bad_b_ref, receipt_reference=r_ref, expectation=exp)

    bad_r_ref = replace(r_ref, content_digest="sha256:" + "0" * 64)
    with pytest.raises(ValueError, match="receipt byte integrity failed"):
        validator.validate_bundle(store=mock_store, bundle_reference=b_ref, receipt_reference=bad_r_ref, expectation=exp)

    bad_receipts = [
        (replace(r, bundle_id="bundle1:" + "0" * 64), "receipt and bundle terminal state is inconsistent"),
        (replace(r, cancellation="requested"), "receipt and bundle terminal state is inconsistent"),
        (replace(r, family_counts={"files": 999}), "receipt and bundle terminal state is inconsistent"),
        (replace(r, source_generation="sg1:" + "0" * 64), "receipt semantic authority mismatch"),
    ]
    for bad_r, match in bad_receipts:
        bad_ref = put_receipt(store, bad_r)
        with pytest.raises(ValueError, match=match):
            validator.validate_bundle(store=store, bundle_reference=b_ref, receipt_reference=bad_ref, expectation=exp)


@pytest.mark.parametrize("terminal_inconsistent", [False, True])
def test_validator_rejects_bundle_with_missing_publication_families(
    monkeypatch, terminal_inconsistent: bool,
) -> None:
    store = MemoryArtifactStore()
    b = bundle()
    b_ref = put_bundle(store, b)
    r = receipt(b_ref, b)
    if terminal_inconsistent:
        r = replace(r, cancellation="requested")
    r_ref = put_receipt(store, r)
    exp = expectation(b)
    validator = PublisherBundleValidator()

    partial_families = dict(b.families)
    del partial_families["canonical_edges"]
    bad_b = replace(b, families=partial_families)

    import repomap_kg.artifacts.validator as val_mod
    monkeypatch.setattr(val_mod.PublicationBundle, "from_bytes", lambda _data: bad_b)

    with pytest.raises(ValueError, match="required publication families are absent"):
        validator.validate_bundle(store=store, bundle_reference=b_ref, receipt_reference=r_ref, expectation=exp)
    assert validator._attempts == {}


def test_validator_rejects_bundle_with_invalid_stage_identity() -> None:
    store = MemoryArtifactStore()
    bad_families = dict(FAMILIES)
    bad_families["files"] = ({
        "family_ordinal": 0, "path": "entry::flake.nix", "language": "nix", "role": "source",
        "confidence": "exact", "content_hash": "sha256:" + "a" * 64, "executable": False,
        "generated": False, "metadata_json": {"binding_id": VECTOR[0][0], "snapshot_id": VECTOR[0][2]},
        "stage_id": "wrong-stage",
    },)
    b_staged = bundle(families=bad_families, row_stage_contract="stage-unassigned-v1")
    b_ref = put_bundle(store, b_staged)
    r = receipt(b_ref, b_staged)
    r_ref = put_receipt(store, r)
    exp = expectation(b_staged)
    validator = PublisherBundleValidator()

    with pytest.raises(ValueError, match="bundle stage representation is ambiguous: stage identity"):
        validator.validate_bundle(store=store, bundle_reference=b_ref, receipt_reference=r_ref, expectation=exp)


def test_validator_transition_semantic_rejection_then_acceptance_and_replay() -> None:
    store = MemoryArtifactStore()
    validator = PublisherBundleValidator()

    bad_families = dict(FAMILIES)
    bad_ev = list(FAMILIES["canonical_evidence"])
    bad_ev[0] = dict(bad_ev[0])
    bad_ev[0]["raw_observation_ordinal"] = 9999
    bad_families["canonical_evidence"] = tuple(bad_ev)
    bad_b = bundle(families=bad_families)
    bad_b_ref = put_bundle(store, bad_b)
    bad_r = receipt(bad_b_ref, bad_b)
    bad_r_ref = put_receipt(store, bad_r)
    with pytest.raises(ValueError, match="bundle semantic evidence reference is invalid"):
        validator.validate_bundle(
            store=store, bundle_reference=bad_b_ref, receipt_reference=bad_r_ref,
            expectation=expectation(bad_b),
        )

    b = bundle()
    b_ref = put_bundle(store, b)
    r = receipt(b_ref, b)
    r_ref = put_receipt(store, r)
    exp = expectation(b)

    accepted = validator.validate_bundle(
        store=store, bundle_reference=b_ref, receipt_reference=r_ref, expectation=exp,
    )
    assert accepted.bundle_id == b.bundle_id
    assert accepted.receipt_id == r.receipt_id
    assert accepted.byte_integrity_valid is True
    assert accepted.semantic_authority_valid is True
    assert accepted.idempotent_replay is False
    assert accepted.mutated is False

    replay = validator.validate_bundle(
        store=store, bundle_reference=b_ref, receipt_reference=r_ref, expectation=exp,
    )
    assert replay.bundle_id == b.bundle_id
    assert replay.receipt_id == r.receipt_id
    assert replay.byte_integrity_valid is True
    assert replay.semantic_authority_valid is True
    assert replay.idempotent_replay is True
    assert replay.mutated is False


def test_validator_transition_conflicting_candidate_rejected_and_original_remains_replayable() -> None:
    store = MemoryArtifactStore()
    validator = PublisherBundleValidator()
    b = bundle()
    b_ref = put_bundle(store, b)
    r = receipt(b_ref, b)
    r_ref = put_receipt(store, r)
    exp = expectation(b)

    accepted = validator.validate_bundle(
        store=store, bundle_reference=b_ref, receipt_reference=r_ref, expectation=exp,
    )
    assert accepted.bundle_id == b.bundle_id
    assert accepted.receipt_id == r.receipt_id
    assert accepted.byte_integrity_valid is True
    assert accepted.semantic_authority_valid is True
    assert accepted.idempotent_replay is False
    assert accepted.mutated is False

    conflict_b = bundle(candidate_id="cand1:" + "7" * 64)
    conflict_b_ref = put_bundle(store, conflict_b)
    conflict_r = receipt(conflict_b_ref, conflict_b)
    conflict_r_ref = put_receipt(store, conflict_r)
    with pytest.raises(ValueError, match="conflicting attempt reuse"):
        validator.validate_bundle(
            store=store, bundle_reference=conflict_b_ref, receipt_reference=conflict_r_ref,
            expectation=expectation(conflict_b),
        )

    replay = validator.validate_bundle(
        store=store, bundle_reference=b_ref, receipt_reference=r_ref, expectation=exp,
    )
    assert replay.bundle_id == b.bundle_id
    assert replay.receipt_id == r.receipt_id
    assert replay.byte_integrity_valid is True
    assert replay.semantic_authority_valid is True
    assert replay.idempotent_replay is True
    assert replay.mutated is False
