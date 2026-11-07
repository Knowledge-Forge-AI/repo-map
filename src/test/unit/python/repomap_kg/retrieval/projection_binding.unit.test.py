"""Unit tests for publication binding correspondence and refusal vocabulary (S1)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from common_lore_index.artifacts._manifest_records import ManifestArtifact, ManifestBinding
from common_lore_index.artifacts.bundle import PUBLICATION_FAMILIES, PublicationBundle
from common_lore_index.artifacts.manifest import PortableSnapshotManifest
from common_lore_index.artifacts.receipt import ExtractionReceipt
from common_lore_index.artifacts.store import InMemoryArtifactStore
from common_lore_index.retrieval.publication_binding import (
    AcceptedPublicationReference,
    CorrespondenceErrorCode,
    CorrespondenceRefusal,
    ProjectionInputs,
    check_correspondence,
)
from common_lore_index.storage.authority import (
    AttemptNumber,
    JobId,
)
from common_lore_index.storage.publication import (
    PortablePublicationBinding,
    RunPublicationAttempt,
    RunPublicationGenerations,
    RunPublicationReceipt,
)
from common_lore_index.storage.staging_family_contracts import PrivacyClassification


def _build_matching_projection_inputs(*, spool_dir: Path | None = None) -> ProjectionInputs:
    store = InMemoryArtifactStore()
    content = b"def run_pipeline() -> str:\n    return 'ok'\n"
    blob_ref = store.put(
        content,
        media_type="text/x-python",
        record_format="raw-source-v1",
        privacy=PrivacyClassification.RAW_SOURCE,
    )
    binding = ManifestBinding(
        binding_id="bind1:" + "1" * 64,
        revision=1,
        snapshot_id="snap1:" + "2" * 64,
        source_definition_id="src1:core",
        source_kind="local-directory",
        acquisition_method="sealed-local-copy",
        selection_policy_id="select1:default",
        ignore_policy_id="ignore1:default",
        privacy_policy="public-dev",
        role="source",
        input_name="core",
        alias="core",
        logical_root="core",
        evidence_retention_policy="full-authorized",
        extractor_profile="default",
        resolution_policy="isolated",
        repository_scope="core",
    )
    entry = ManifestArtifact(
        binding_id=binding.binding_id,
        source_relative_path="pkg/pipeline.py",
        reference=blob_ref,
        executable=False,
    )
    manifest = PortableSnapshotManifest.create(
        graph_id="mixed-v1",
        bindings=(binding,),
        entries=(entry,),
        source_generation="sg1:" + "3" * 64,
        config_generation="cg1:" + "4" * 64,
        extractor_generation="eg1:" + "5" * 64,
        canonicalizer_generation="kg1:" + "6" * 64,
        extractor_capability_identity="cap1:python-static-v1",
        resolver_identity="resolver1:isolated",
        canonicalizer_identity="canon1:graph-key-v1-binding-path",
        semantic_contract_identity="semantic1:multi-source-v1",
        quality_rule_identity="quality1:default",
    )
    manifest_ref = store.put(
        manifest.canonical_bytes(),
        media_type="application/json",
        record_format="portable-snapshot-manifest-v1",
        privacy=PrivacyClassification.PUBLIC,
    )
    families = {family: () for family in PUBLICATION_FAMILIES}
    bundle = PublicationBundle.create(
        request_id="job-retrieval-1",
        job_id="job-retrieval-1",
        attempt=1,
        graph_id="mixed-v1",
        candidate_id="cand1:" + "7" * 64,
        snapshot_manifest_id=manifest.manifest_id,
        snapshot_vector=manifest.snapshot_vector,
        source_generation=manifest.source_generation,
        config_generation=manifest.config_generation,
        extractor_generation=manifest.extractor_generation,
        canonicalizer_generation=manifest.canonicalizer_generation,
        extractor_capability_identity=manifest.extractor_capability_identity,
        resolver_identity=manifest.resolver_identity,
        canonicalizer_identity=manifest.canonicalizer_identity,
        semantic_contract_identity=manifest.semantic_contract_identity,
        quality_rule_identity=manifest.quality_rule_identity,
        privacy=manifest.effective_privacy,
        families=families,
        row_stage_contract="stage-unassigned-v1",
    )
    bundle_ref = store.put(
        bundle.canonical_bytes(),
        media_type="application/json",
        record_format="publication-bundle-v1",
        privacy=PrivacyClassification.CANONICAL_PROVENANCE,
    )
    ext_receipt = ExtractionReceipt.create(
        request_id="job-retrieval-1",
        job_id="job-retrieval-1",
        attempt=1,
        graph_id="mixed-v1",
        worker_capability_identity="worker1:portable-v1",
        contract_version="1.0",
        source_generation=manifest.source_generation,
        config_generation=manifest.config_generation,
        extractor_generation=manifest.extractor_generation,
        canonicalizer_generation=manifest.canonicalizer_generation,
        snapshot_manifest_id=manifest.manifest_id,
        snapshot_vector=manifest.snapshot_vector,
        resolver_identity=manifest.resolver_identity,
        extractor_capability_identity=manifest.extractor_capability_identity,
        canonicalizer_identity=manifest.canonicalizer_identity,
        semantic_contract_identity=manifest.semantic_contract_identity,
        quality_rule_identity=manifest.quality_rule_identity,
        outcome="completed",
        cancellation="not-requested",
        bundle_reference=bundle_ref,
        bundle_id=bundle.bundle_id,
        family_counts=bundle.family_counts,
        diagnostic_category=None,
        diagnostic_summary=(),
        producer_identity="worker1:portable-v1",
        attestation_class="untrusted-worker",
    )
    receipt_ref = store.put(
        ext_receipt.canonical_bytes(),
        media_type="application/json",
        record_format="extraction-receipt-v1",
        privacy=PrivacyClassification.CANONICAL_PROVENANCE,
    )
    portable_binding = PortablePublicationBinding(
        route="portable-worker-v1",
        snapshot_manifest_id=manifest.manifest_id,
        snapshot_vector=manifest.snapshot_vector,
        extraction_receipt_id=ext_receipt.receipt_id,
        publication_bundle_id=bundle.bundle_id,
        candidate_id=bundle.candidate_id,
        resolver_identity=bundle.resolver_identity,
        canonicalizer_identity=bundle.canonicalizer_identity,
        semantic_contract_identity=bundle.semantic_contract_identity,
        quality_rule_identity=bundle.quality_rule_identity,
        protocol_version="1.0",
        worker_capability_identity="worker1:portable-v1",
        stage_id="stage-unassigned",
        execution_mode="direct",
        singleton_fencing_epoch=1,
        graph_lease_fencing_epoch=1,
        family_receipts={
            item.family: {
                "count": item.record_count,
                "byte_length": item.byte_length,
                "digest": item.content_digest,
            }
            for item in bundle.family_summaries
        },
    ).validate()
    pub_receipt = RunPublicationReceipt(
        attempt=RunPublicationAttempt(JobId("job-retrieval-1"), AttemptNumber(1)),
        generations=RunPublicationGenerations(
            source_generation=manifest.source_generation,
            config_generation=manifest.config_generation,
            extractor_generation=manifest.extractor_generation,
            canonicalizer_generation=manifest.canonicalizer_generation,
        ),
        portable=portable_binding,
    ).validate()
    accepted = AcceptedPublicationReference(
        graph_id="mixed-v1",
        repository_id="repo1:mixed-v1",
        backend="sqlite",
        run_id=1,
        publication_bundle_id=bundle.bundle_id,
        job_id="job-retrieval-1",
        attempt=1,
        accepted_generation=1,
        snapshot_manifest_id=manifest.manifest_id,
        extraction_receipt_id=ext_receipt.receipt_id,
        trusted_caller=True,
    )
    if spool_dir is not None:
        spool_dir.mkdir(parents=True, exist_ok=True)
    return ProjectionInputs(
        accepted_reference=accepted,
        receipt=pub_receipt,
        manifest=manifest,
        bundle=bundle,
        store=store,
        manifest_reference=manifest_ref,
        bundle_reference=bundle_ref,
        receipt_reference=receipt_ref,
        extraction_receipt=ext_receipt,
        spool_dir=spool_dir,
    )


def test_matching_correspondence_succeeds_and_roundtrips(tmp_path: Path) -> None:
    """Matching accepted reference, receipt, manifest, bundle, and store pass correspondence."""
    inputs = _build_matching_projection_inputs(spool_dir=tmp_path / "spool")
    verified = check_correspondence(inputs)
    assert verified == inputs.accepted_reference
    assert AcceptedPublicationReference.from_mapping(verified.to_dict()) == verified
    for bad_field, bad_val in (
        ("trusted_caller", "false"),
        ("trusted_caller", 1),
        ("attempt", True),
        ("accepted_generation", False),
        ("graph_id", 123),
    ):
        with pytest.raises(ValueError):
            AcceptedPublicationReference.from_mapping({**verified.to_dict(), bad_field: bad_val})
    with pytest.raises(CorrespondenceRefusal) as exc_info:
        check_correspondence(replace(inputs, max_bundle_bytes=16))
    assert exc_info.value.code == CorrespondenceErrorCode.BUNDLE_VALIDATION_FAILED


def test_untrusted_caller_and_missing_portable_receipt_refused(tmp_path: Path) -> None:
    """Untrusted caller references and receipts without portable bindings are refused."""
    inputs = _build_matching_projection_inputs(spool_dir=tmp_path / "spool")
    untrusted = replace(inputs.accepted_reference, trusted_caller=False)
    with pytest.raises(CorrespondenceRefusal) as exc_info:
        check_correspondence(replace(inputs, accepted_reference=untrusted))
    assert exc_info.value.code == CorrespondenceErrorCode.UNTRUSTED_CALLER_REFERENCE

    no_portable = RunPublicationReceipt(
        attempt=inputs.receipt.attempt,
        generations=inputs.receipt.generations,
        portable=None,
    )
    with pytest.raises(CorrespondenceRefusal) as exc_info:
        check_correspondence(replace(inputs, receipt=no_portable))
    assert exc_info.value.code == CorrespondenceErrorCode.MISSING_PORTABLE_BINDING


def test_correspondence_refuses_every_identity_and_generation_mismatch(tmp_path: Path) -> None:
    """Every identity, vector, generation, and receipt mismatch raises the exact refusal code."""
    inputs = _build_matching_projection_inputs(spool_dir=tmp_path / "spool")

    bad_graph = replace(inputs.accepted_reference, graph_id="other-graph")
    with pytest.raises(CorrespondenceRefusal) as exc_info:
        check_correspondence(replace(inputs, accepted_reference=bad_graph))
    assert exc_info.value.code == CorrespondenceErrorCode.GRAPH_ID_MISMATCH

    bad_attempt = replace(inputs.accepted_reference, attempt=2)
    with pytest.raises(CorrespondenceRefusal) as exc_info:
        check_correspondence(replace(inputs, accepted_reference=bad_attempt))
    assert exc_info.value.code == CorrespondenceErrorCode.ATTEMPT_MISMATCH

    bad_bundle = replace(inputs.accepted_reference, publication_bundle_id="bundle1:" + "f" * 64)
    with pytest.raises(CorrespondenceRefusal) as exc_info:
        check_correspondence(replace(inputs, accepted_reference=bad_bundle))
    assert exc_info.value.code == CorrespondenceErrorCode.BUNDLE_ID_MISMATCH

    assert inputs.receipt.portable is not None
    bad_candidate_portable = replace(inputs.receipt.portable, candidate_id="cand1:" + "e" * 64)
    with pytest.raises(CorrespondenceRefusal) as exc_info:
        check_correspondence(
            replace(inputs, receipt=replace(inputs.receipt, portable=bad_candidate_portable))
        )
    assert exc_info.value.code == CorrespondenceErrorCode.CANDIDATE_ID_MISMATCH

    bad_manifest_id = replace(
        inputs.accepted_reference, snapshot_manifest_id="snapmanifest1:" + "9" * 64
    )
    with pytest.raises(CorrespondenceRefusal) as exc_info:
        check_correspondence(replace(inputs, accepted_reference=bad_manifest_id))
    assert exc_info.value.code == CorrespondenceErrorCode.MANIFEST_ID_MISMATCH

    bad_vector_portable = replace(
        inputs.receipt.portable,
        snapshot_vector=(("bind1:" + "8" * 64, 1, "snap1:" + "2" * 64),),
    )
    with pytest.raises(CorrespondenceRefusal) as exc_info:
        check_correspondence(
            replace(inputs, receipt=replace(inputs.receipt, portable=bad_vector_portable))
        )
    assert exc_info.value.code == CorrespondenceErrorCode.SNAPSHOT_VECTOR_MISMATCH

    bad_gen = replace(
        inputs.receipt.generations,
        source_generation="sg1:" + "9" * 64,
    )
    with pytest.raises(CorrespondenceRefusal) as exc_info:
        check_correspondence(replace(inputs, receipt=replace(inputs.receipt, generations=bad_gen)))
    assert exc_info.value.code == CorrespondenceErrorCode.GENERATION_MISMATCH

    bad_receipt_id = replace(inputs.accepted_reference, extraction_receipt_id="receipt1:" + "0" * 64)
    with pytest.raises(CorrespondenceRefusal) as exc_info:
        check_correspondence(replace(inputs, accepted_reference=bad_receipt_id))
    assert exc_info.value.code == CorrespondenceErrorCode.RECEIPT_ID_MISMATCH


def test_store_verification_and_advancement_checks(tmp_path: Path) -> None:
    """Missing/foreign store references and advanced accepted publications are refused."""
    inputs = _build_matching_projection_inputs(spool_dir=tmp_path / "spool")
    empty_store = InMemoryArtifactStore()
    with pytest.raises(CorrespondenceRefusal) as exc_info:
        check_correspondence(replace(inputs, store=empty_store))
    assert exc_info.value.code == CorrespondenceErrorCode.STORE_VERIFICATION_FAILED

    advanced = replace(inputs.accepted_reference, accepted_generation=2, run_id=2)
    assert inputs.accepted_reference.matches_current(inputs.accepted_reference) is True
    assert inputs.accepted_reference.matches_current(advanced) is False
    assert inputs.accepted_reference.matches_current(None) is False
