from __future__ import annotations

from dataclasses import replace

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
    quality: str = "quality1:default",
    candidate_id: str = "cand1:" + "3" * 64,
    snapshot_manifest_id: str = "snapmanifest1:" + "4" * 64,
    snapshot_vector: tuple[tuple[str, int, str], ...] = VECTOR,
    extractor_capability_identity: str = "cap1:python-static-v1",
    semantic_contract_identity: str = "semantic1:multi-source-v1",
    row_stage_contract: str = "legacy-absent-v1",
) -> PublicationBundle:
    return PublicationBundle.create(
        request_id="request-1", job_id="job-1", attempt=1, graph_id="graph-a",
        candidate_id=candidate_id, snapshot_manifest_id=snapshot_manifest_id,
        snapshot_vector=snapshot_vector, source_generation="sg1:" + "5" * 64,
        config_generation="cg1:" + "6" * 64, extractor_generation="eg1:" + "7" * 64,
        canonicalizer_generation="kg1:" + "8" * 64,
        extractor_capability_identity=extractor_capability_identity,
        resolver_identity="resolver1:nix-static-v2",
        canonicalizer_identity="canon1:graph-key-v1-binding-path",
        semantic_contract_identity=semantic_contract_identity,
        quality_rule_identity=quality, privacy=PrivacyClassification.CANONICAL_PROVENANCE,
        families=families, row_stage_contract=row_stage_contract,
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
        diagnostic_summary=() if outcome == "completed" else ("summary",),
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


def test_validator_separates_byte_integrity_from_semantic_authority_and_replay() -> None:
    store = MemoryArtifactStore()
    value = bundle()
    bundle_ref = put_bundle(store, value)
    completed = receipt(bundle_ref, value)
    receipt_ref = put_receipt(store, completed)
    validator = PublisherBundleValidator()

    accepted = validator.validate_bundle(
        store=store, bundle_reference=bundle_ref, receipt_reference=receipt_ref,
        expectation=expectation(value),
    )
    replay = validator.validate_bundle(
        store=store, bundle_reference=bundle_ref, receipt_reference=receipt_ref,
        expectation=expectation(value),
    )

    assert accepted.byte_integrity_valid and accepted.semantic_authority_valid
    assert replay.idempotent_replay
    assert not accepted.mutated


def test_hash_consistent_but_semantically_invalid_bundle_is_rejected() -> None:
    rows = dict(FAMILIES)
    dangling = dict(rows["canonical_node_evidence"][0])
    dangling["canonical_key"] = "missing:node"
    rows["canonical_node_evidence"] = (dangling,)
    value = bundle(families=rows)
    store = MemoryArtifactStore()
    bundle_ref = put_bundle(store, value)
    receipt_ref = put_receipt(store, receipt(bundle_ref, value))

    with pytest.raises(ValueError, match="semantic"):
        PublisherBundleValidator().validate_bundle(
            store=store, bundle_reference=bundle_ref, receipt_reference=receipt_ref,
            expectation=expectation(value),
        )


def test_conflicting_attempt_reuse_and_multiple_mutating_owners_fail_closed() -> None:
    store = MemoryArtifactStore()
    value = bundle()
    bundle_ref = put_bundle(store, value)
    receipt_ref = put_receipt(store, receipt(bundle_ref, value))
    validator = PublisherBundleValidator()
    validator.validate_bundle(
        store=store, bundle_reference=bundle_ref, receipt_reference=receipt_ref,
        expectation=expectation(value),
    )
    conflict = bundle(quality="quality1:strict")
    conflict_ref = put_bundle(store, conflict)
    conflict_receipt = put_receipt(store, receipt(conflict_ref, conflict))

    with pytest.raises(ValueError, match="conflicting attempt"):
        validator.validate_bundle(
            store=store, bundle_reference=conflict_ref, receipt_reference=conflict_receipt,
            expectation=expectation(conflict),
        )
    with pytest.raises(ValueError, match="mutating owner"):
        PublisherBundleValidator().validate_bundle(
            store=store, bundle_reference=bundle_ref, receipt_reference=receipt_ref,
            expectation=replace(expectation(value), mutating_owner_count=2),
        )


@pytest.mark.parametrize(
    "override",
    (
        {"candidate_id": "cand1:" + "9" * 64},
        {"snapshot_manifest_id": "snapmanifest1:" + "9" * 64},
        {"snapshot_vector": ((VECTOR[0][0], 2, "snap1:" + "9" * 64),)},
        {"extractor_capability_identity": "cap1:alternate-v1"},
        {"semantic_contract_identity": "semantic1:alternate-v1"},
        {"quality": "quality1:alternate-bundle"},
    ),
)
def test_attempt_reuse_rejects_each_conflicting_semantic_identity(override: dict[str, object]) -> None:
    store = MemoryArtifactStore()
    first = bundle()
    first_ref = put_bundle(store, first)
    first_receipt_ref = put_receipt(store, receipt(first_ref, first))
    validator = PublisherBundleValidator()
    validator.validate_bundle(
        store=store, bundle_reference=first_ref, receipt_reference=first_receipt_ref,
        expectation=expectation(first),
    )
    conflicting = bundle(
        candidate_id=str(override.get("candidate_id", "cand1:" + "3" * 64)),
        snapshot_manifest_id=str(override.get("snapshot_manifest_id", "snapmanifest1:" + "4" * 64)),
        snapshot_vector=VECTOR if "snapshot_vector" not in override else ((VECTOR[0][0], 2, "snap1:" + "9" * 64),),
        extractor_capability_identity=str(override.get("extractor_capability_identity", "cap1:python-static-v1")),
        semantic_contract_identity=str(override.get("semantic_contract_identity", "semantic1:multi-source-v1")),
        quality=str(override.get("quality", "quality1:default")),
    )
    conflicting_ref = put_bundle(store, conflicting)
    conflicting_receipt_ref = put_receipt(store, receipt(conflicting_ref, conflicting))

    with pytest.raises(ValueError, match="conflicting attempt"):
        validator.validate_bundle(
            store=store, bundle_reference=conflicting_ref, receipt_reference=conflicting_receipt_ref,
            expectation=expectation(conflicting),
        )


@pytest.mark.parametrize("outcome", ("failed", "cancelled"))
def test_noncompleted_attempt_cannot_be_replayed_as_completed(outcome: str) -> None:
    value = bundle()
    store = MemoryArtifactStore()
    bundle_ref = put_bundle(store, value)
    completed = receipt(bundle_ref, value)
    terminal = replace(
        completed, outcome=outcome,
        cancellation="requested" if outcome == "cancelled" else "not-requested",
        bundle_reference=None, bundle_id=None, family_counts={},
        diagnostic_category="cancelled" if outcome == "cancelled" else "source_capture",
        receipt_id="",
    ).reidentify()
    terminal_ref = put_receipt(store, terminal)
    completed_ref = put_receipt(store, completed)
    validator = PublisherBundleValidator()

    assert validator.validate_terminal_receipt(store=store, receipt_reference=terminal_ref) == terminal
    assert validator.validate_terminal_receipt(store=store, receipt_reference=terminal_ref) == terminal
    with pytest.raises(ValueError, match="cannot become completed"):
        validator.validate_bundle(
            store=store, bundle_reference=bundle_ref, receipt_reference=completed_ref,
            expectation=expectation(value),
        )


def test_validator_rejects_independent_expectation_disagreements() -> None:
    store = MemoryArtifactStore()
    value = bundle()
    bundle_ref = put_bundle(store, value)
    receipt_ref = put_receipt(store, receipt(bundle_ref, value))
    validator = PublisherBundleValidator()
    base_exp = expectation(value)

    cases = (
        (replace(base_exp, graph_id="graph-other"), "semantic authority mismatch"),
        (replace(base_exp, job_id="job-other"), "semantic authority mismatch"),
        (replace(base_exp, attempt=2), "semantic authority mismatch"),
        (replace(base_exp, candidate_id="cand1:" + "9" * 64), "semantic authority mismatch"),
        (replace(base_exp, snapshot_manifest_id="snapmanifest1:" + "9" * 64), "semantic authority mismatch"),
        (replace(base_exp, source_generation="sg1:" + "9" * 64), "semantic authority mismatch"),
        (replace(base_exp, config_generation="cg1:" + "9" * 64), "semantic authority mismatch"),
        (replace(base_exp, extractor_generation="eg1:" + "9" * 64), "semantic authority mismatch"),
        (replace(base_exp, canonicalizer_generation="kg1:" + "9" * 64), "semantic authority mismatch"),
        (replace(base_exp, contract_version="2.0"), "contract version mismatch"),
        (replace(base_exp, worker_capability_identity="cap1:unknown-v1"), "capability identity mismatch"),
        (replace(base_exp, expected_privacy="public"), "privacy mismatch"),
    )
    for exp, pattern in cases:
        with pytest.raises(ValueError, match=pattern):
            validator.validate_bundle(
                store=store, bundle_reference=bundle_ref, receipt_reference=receipt_ref,
                expectation=exp,
            )


def test_validator_mutating_owner_count_rejected() -> None:
    store = MemoryArtifactStore()
    b = bundle()
    bundle_ref = put_bundle(store, b)
    r = receipt(bundle_ref, b)
    receipt_ref = put_receipt(store, r)
    exp = PublicationExpectation.from_bundle(b, mutating_owner_count=2)

    with pytest.raises(ValueError, match="exactly one mutating owner is required"):
        PublisherBundleValidator().validate_bundle(
            store=store, bundle_reference=bundle_ref, receipt_reference=receipt_ref,
            expectation=exp,
        )


def test_validator_receipt_contract_version_and_worker_capability_mismatch() -> None:
    store = MemoryArtifactStore()
    b = bundle()
    bundle_ref = put_bundle(store, b)

    r_bad_ver = replace(receipt(bundle_ref, b), contract_version="2.0")
    bad_ver_ref = put_receipt(store, r_bad_ver)
    exp = PublicationExpectation.from_bundle(b, mutating_owner_count=1)

    with pytest.raises(ValueError, match="receipt contract version mismatch"):
        PublisherBundleValidator().validate_bundle(
            store=store, bundle_reference=bundle_ref, receipt_reference=bad_ver_ref,
            expectation=exp,
        )

    r_bad_cap = replace(receipt(bundle_ref, b), worker_capability_identity="cap2:other")
    bad_cap_ref = put_receipt(store, r_bad_cap)
    with pytest.raises(ValueError, match="receipt worker capability identity mismatch"):
        PublisherBundleValidator().validate_bundle(
            store=store, bundle_reference=bundle_ref, receipt_reference=bad_cap_ref,
            expectation=exp,
        )


def test_validator_bundle_privacy_mismatch() -> None:
    store = MemoryArtifactStore()
    b = bundle()
    bundle_ref = put_bundle(store, b)
    r = receipt(bundle_ref, b)
    receipt_ref = put_receipt(store, r)
    exp = PublicationExpectation.from_bundle(b, mutating_owner_count=1, expected_privacy="internal-proprietary")

    with pytest.raises(ValueError, match="bundle privacy mismatch"):
        PublisherBundleValidator().validate_bundle(
            store=store, bundle_reference=bundle_ref, receipt_reference=receipt_ref,
            expectation=exp,
        )


def test_validator_legacy_bundle_unexpected_stage_id() -> None:
    store = MemoryArtifactStore()
    bad_families = dict(FAMILIES)
    bad_files = list(FAMILIES["files"])
    bad_files[0] = dict(bad_files[0])
    bad_files[0]["stage_id"] = "stage-unassigned"
    bad_families["files"] = tuple(bad_files)

    b = bundle(families=bad_families, row_stage_contract="legacy-absent-v1")
    bundle_ref = put_bundle(store, b)
    r = receipt(bundle_ref, b)
    receipt_ref = put_receipt(store, r)
    exp = PublicationExpectation.from_bundle(b, mutating_owner_count=1)

    with pytest.raises(ValueError, match="legacy bundle stage representation is ambiguous"):
        PublisherBundleValidator().validate_bundle(
            store=store, bundle_reference=bundle_ref, receipt_reference=receipt_ref,
            expectation=exp,
        )
