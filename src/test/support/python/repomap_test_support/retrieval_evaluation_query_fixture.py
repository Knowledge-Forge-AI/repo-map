"""Controlled publication inputs for projection query and paging tests."""

from __future__ import annotations

from pathlib import Path
from common_lore_index.artifacts._manifest_records import ManifestArtifact, ManifestBinding
from common_lore_index.artifacts.bundle import PUBLICATION_FAMILIES, PublicationBundle
from common_lore_index.artifacts.manifest import PortableSnapshotManifest
from common_lore_index.artifacts.receipt import ExtractionReceipt
from common_lore_index.artifacts.store import InMemoryArtifactStore
from common_lore_index.retrieval.projection_policy import BodyProjectionPolicy, ResolvedBindingPolicy
from common_lore_index.retrieval.publication_binding import AcceptedPublicationReference, ProjectionInputs
from common_lore_index.storage.authority import AttemptNumber, JobId
from common_lore_index.storage.publication import PortablePublicationBinding, RunPublicationAttempt, RunPublicationGenerations, RunPublicationReceipt
from common_lore_index.storage.staging_family_contracts import PrivacyClassification
from common_lore_index.storage.staging_family_rows import StageFamily


def _make_binding(
    binding_id: str,
    alias: str,
    *,
    privacy: str = "public-dev",
    retention: str = "full-authorized",
) -> ManifestBinding:
    return ManifestBinding(
        binding_id=binding_id,
        revision=1,
        snapshot_id="snap1:" + alias.encode().hex().ljust(64, "0")[:64],
        source_definition_id=f"src1:{alias}",
        source_kind="local-directory",
        acquisition_method="sealed-local-copy",
        selection_policy_id="select1:default",
        ignore_policy_id="ignore1:default",
        privacy_policy=privacy,
        role="source",
        input_name=alias,
        alias=alias,
        logical_root=alias,
        evidence_retention_policy=retention,
        extractor_profile="default",
        resolution_policy="isolated",
        repository_scope=alias,
    )


def build_fixture_projection(*, extra_tail: bytes = b"", spool_dir: Path | None = None) -> tuple[ProjectionInputs, BodyProjectionPolicy]:
    store = InMemoryArtifactStore()
    b_core = _make_binding("bind1:" + "1" * 64, "core")
    b_mail = _make_binding(
        "bind1:" + "2" * 64, "mailbox", privacy="private-memory", retention="metadata-only"
    )

    lines = [f"line {i:03d}: ordinary code\n" for i in range(1, 80)]
    lines.append("line 080: BOUNDARY_START_TOKEN\n")
    lines.append("line 081: BOUNDARY_END_TOKEN\n")
    lines.extend(f"line {i:03d}: tail code\n" for i in range(82, 100))
    file_a_bytes = "".join(lines).encode("utf-8") + extra_tail
    file_b_bytes = b"SECOND_FILE_HEAD\nnormal line\n"
    canary_bytes = b"Subject: Secret\n\nCANARY_PRIVATE_BODY_DO_NOT_READ_991\n"

    ref_a = store.put(
        file_a_bytes,
        media_type="text/x-python",
        record_format="raw-source-v1",
        privacy=PrivacyClassification.RAW_SOURCE,
    )
    ref_b = store.put(
        file_b_bytes,
        media_type="text/x-python",
        record_format="raw-source-v1",
        privacy=PrivacyClassification.RAW_SOURCE,
    )
    ref_mail = store.put(
        canary_bytes,
        media_type="message/rfc822",
        record_format="raw-source-v1",
        privacy=PrivacyClassification.RAW_SOURCE,
    )

    entries = (
        ManifestArtifact(b_core.binding_id, "pkg/alpha.py", ref_a, False),
        ManifestArtifact(b_core.binding_id, "pkg/beta.py", ref_b, False),
        ManifestArtifact(b_mail.binding_id, "mailbox/secret.eml", ref_mail, False),
    )
    manifest = PortableSnapshotManifest.create(
        graph_id="mixed-v1",
        bindings=(b_core, b_mail),
        entries=entries,
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
    families: dict[StageFamily, tuple[dict[str, object], ...]] = {
        family: () for family in PUBLICATION_FAMILIES
    }
    families["raw_observations"] = ({
        "source_ordinal": 0, "schema_version": 1, "kind": "python.function",
        "source_id": "boundary-fixture", "path": "core/pkg/alpha.py", "payload_json": {},
        "payload_hash": "sha256:" + "a" * 64, "stage_id": "stage-unassigned",
    },)
    families["canonical_nodes"] = ({
        "family_ordinal": 0, "graph_key_version": 1,
        "canonical_key": "python.function:pkg.alpha:boundary_fn", "kind": "Function",
        "display_name": "boundary_fn", "metadata_json": {}, "confidence": "extracted",
        "conflict": False, "stage_id": "stage-unassigned",
    },)
    families["canonical_evidence"] = (
        {
            "family_ordinal": 0, "graph_key_version": 1,
            "evidence_key": "ev1:alpha80",
            "raw_observation_ordinal": 0, "stage_id": "stage-unassigned",
            "raw_kind": "python.function",
            "path": "core/pkg/alpha.py",
            "start_line": 80,
            "end_line": 81,
            "confidence": "extracted",
            "metadata_json": {
                "binding_id": b_core.binding_id,
                "source_relative_path": "pkg/alpha.py",
            },
        },
    )
    families["canonical_node_evidence"] = (
        {
            "canonical_key": "python.function:pkg.alpha:boundary_fn", "stage_id": "stage-unassigned",
            "family_ordinal": 0, "graph_key_version": 1,
            "evidence_key": "ev1:alpha80",
            "link_kind": "defined_by",
        },
    )
    bundle = PublicationBundle.create(
        request_id="job-q-1",
        job_id="job-q-1",
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
        request_id="job-q-1",
        job_id="job-q-1",
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
        attempt=RunPublicationAttempt(JobId("job-q-1"), AttemptNumber(1)),
        generations=RunPublicationGenerations(
            manifest.source_generation,
            manifest.config_generation,
            manifest.extractor_generation,
            manifest.canonicalizer_generation,
        ),
        portable=portable_binding,
    ).validate()
    accepted = AcceptedPublicationReference(
        graph_id="mixed-v1",
        repository_id="repo1:mixed-v1",
        backend="sqlite",
        run_id=1,
        publication_bundle_id=bundle.bundle_id,
        job_id="job-q-1",
        attempt=1,
        accepted_generation=1,
        snapshot_manifest_id=manifest.manifest_id,
        extraction_receipt_id=ext_receipt.receipt_id,
        trusted_caller=True,
    )
    policy = BodyProjectionPolicy(
        graph_id="mixed-v1",
        selected_binding_ids=frozenset({b_core.binding_id}),
        bindings={
            b_core.binding_id: ResolvedBindingPolicy(
                binding_id=b_core.binding_id,
                alias="core",
                role="source",
                source_kind="folder",
                original_graph_privacy="public-dev",
                resolved_graph_privacy="public-dev",
                original_binding_privacy="public-dev",
                resolved_binding_privacy="public-dev",
                original_evidence_retention="full-authorized",
                resolved_evidence_retention="full-authorized",
            ),
            b_mail.binding_id: ResolvedBindingPolicy(
                binding_id=b_mail.binding_id,
                alias="mailbox",
                role="source",
                source_kind="folder",
                original_graph_privacy="public-dev",
                resolved_graph_privacy="public-dev",
                original_binding_privacy="private-memory",
                resolved_binding_privacy="private-memory",
                original_evidence_retention="metadata-only",
                resolved_evidence_retention="metadata-only",
            ),
        },
    ).validate()
    if spool_dir is not None:
        spool_dir.mkdir(parents=True, exist_ok=True)
    return (
        ProjectionInputs(
            accepted,
            pub_receipt,
            manifest,
            bundle,
            store,
            manifest_reference=store.put(
                manifest.canonical_bytes(),
                media_type="application/json",
                record_format="portable-snapshot-manifest-v1",
                privacy=PrivacyClassification.PUBLIC,
            ),
            bundle_reference=bundle_ref,
            receipt_reference=receipt_ref,
            extraction_receipt=ext_receipt,
            spool_dir=spool_dir,
        ),
        policy,
    )
