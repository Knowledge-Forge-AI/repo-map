"""Cross-component integration tests for coordinator storage and publication pipeline.

Exercises:
1. FileSystemArtifactStore initialization and directory boundary isolation.
2. PublicationBundle creation across canonical publication families (empty and populated).
3. Bundle and receipt serialization and persistence in artifact store.
4. Publication validation through PublisherBundleValidator.
5. Idempotent replay and conflicting attempt reuse guards.
6. Semantic authority and evidence referential integrity checks.
7. File-level store tampering detection via ArtifactIntegrityError.
8. Terminal non-completed receipt validation and transition guards.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import shutil
import tempfile
from typing import Mapping, Sequence
import unittest

from repomap_kg.artifacts.bundle import PUBLICATION_FAMILIES, PublicationBundle
from repomap_kg.artifacts.receipt import ExtractionReceipt
from repomap_kg.artifacts.references import ArtifactReference
from repomap_kg.artifacts.store import ArtifactIntegrityError, FileSystemArtifactStore
from repomap_kg.artifacts.validator import (
    PublicationExpectation,
    PublisherBundleValidator,
)
from repomap_kg.storage.staging_family_contracts import PrivacyClassification
from repomap_kg.storage.staging_family_rows import StageFamily
from repomap_test_support.test_scratch import select_scratch_root


class StoragePublicationPipelineIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = Path(
            tempfile.mkdtemp(
                dir=select_scratch_root(),
                prefix="repomap-int-storage-pub-",
            )
        ).resolve()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _create_bundle(
        self,
        *,
        request_id: str = "req-int-1",
        job_id: str = "job-int-1",
        attempt: int = 1,
        graph_id: str = "graph-int-1",
        families: Mapping[StageFamily, Sequence[Mapping[str, object]]] | None = None,
        row_stage_contract: str = "stage-unassigned-v1",
        privacy: PrivacyClassification = PrivacyClassification.PUBLIC,
    ) -> PublicationBundle:
        if families is None:
            families = {family: () for family in PUBLICATION_FAMILIES}
        return PublicationBundle.create(
            request_id=request_id,
            job_id=job_id,
            attempt=attempt,
            graph_id=graph_id,
            candidate_id="cand-int-1",
            snapshot_manifest_id="man-int-1",
            snapshot_vector=(),
            source_generation="sg1",
            config_generation="cg1",
            extractor_generation="eg1",
            canonicalizer_generation="kg1",
            extractor_capability_identity="cap1:standard-v1",
            resolver_identity="res1:standard-v1",
            canonicalizer_identity="canon1:standard-v1",
            semantic_contract_identity="sem1:standard-v1",
            quality_rule_identity="qual1:standard-v1",
            privacy=privacy,
            families=families,
            row_stage_contract=row_stage_contract,
        )

    def _create_receipt(
        self,
        bundle: PublicationBundle,
        bundle_ref: ArtifactReference,
        *,
        outcome: str = "completed",
    ) -> ExtractionReceipt:
        return ExtractionReceipt.create(
            request_id=bundle.request_id,
            job_id=bundle.job_id,
            attempt=bundle.attempt,
            graph_id=bundle.graph_id,
            worker_capability_identity="cap1:portable-python-worker-v1",
            contract_version="1.0",
            source_generation=bundle.source_generation,
            config_generation=bundle.config_generation,
            extractor_generation=bundle.extractor_generation,
            canonicalizer_generation=bundle.canonicalizer_generation,
            snapshot_manifest_id=bundle.snapshot_manifest_id,
            snapshot_vector=bundle.snapshot_vector,
            resolver_identity=bundle.resolver_identity,
            extractor_capability_identity=bundle.extractor_capability_identity,
            canonicalizer_identity=bundle.canonicalizer_identity,
            semantic_contract_identity=bundle.semantic_contract_identity,
            quality_rule_identity=bundle.quality_rule_identity,
            outcome=outcome,
            cancellation="not-requested",
            bundle_reference=bundle_ref,
            bundle_id=bundle.bundle_id,
            family_counts=bundle.family_counts,
            diagnostic_category=None,
            diagnostic_summary=(),
            producer_identity="producer1:portable-python-worker-v1",
            attestation_class="untrusted-self-assertion",
        )

    def _store_bundle_and_receipt(
        self,
        store: FileSystemArtifactStore,
        bundle: PublicationBundle,
        receipt: ExtractionReceipt | None = None,
    ) -> tuple[ArtifactReference, ArtifactReference]:
        b_ref = store.put(
            bundle.canonical_bytes(),
            media_type="application/x-repomap-publication-bundle-v1+jsonl",
            record_format="canonical-jsonl-v1",
            privacy=bundle.privacy,
        )
        if receipt is None:
            receipt = self._create_receipt(bundle, b_ref)
        r_ref = store.put(
            receipt.canonical_bytes(),
            media_type="application/x-repomap-extraction-receipt-v1+json",
            record_format="canonical-json-v1",
            privacy=bundle.privacy,
        )
        return b_ref, r_ref

    def _expectation(
        self,
        bundle: PublicationBundle,
        *,
        graph_id: str | None = None,
    ) -> PublicationExpectation:
        exp = PublicationExpectation.from_bundle(
            bundle,
            mutating_owner_count=1,
            worker_capability_identity="cap1:portable-python-worker-v1",
        )
        if graph_id is not None:
            return replace(exp, graph_id=graph_id)
        return exp

    def test_bundle_publication_empty_families_lifecycle(self) -> None:
        store = FileSystemArtifactStore(self.tmpdir / "artifact_store")
        bundle = self._create_bundle()
        b_ref, r_ref = self._store_bundle_and_receipt(store, bundle)
        self.assertTrue(store.verify(b_ref) and store.verify(r_ref))

        validator = PublisherBundleValidator()
        res = validator.validate_bundle(
            store=store,
            bundle_reference=b_ref,
            receipt_reference=r_ref,
            expectation=self._expectation(bundle),
        )
        self.assertTrue(res.byte_integrity_valid and res.semantic_authority_valid)
        self.assertFalse(res.idempotent_replay)
        self.assertEqual(res.bundle_id, bundle.bundle_id)

    def test_bundle_publication_non_empty_linked_families_lifecycle(self) -> None:
        store = FileSystemArtifactStore(self.tmpdir / "artifact_store")
        families: dict[StageFamily, Sequence[Mapping[str, object]]] = {
            "files": ({"stage_id": "stage-unassigned", "path": "src/app.py"},),
            "raw_observations": (
                {"stage_id": "stage-unassigned", "source_ordinal": 0, "kind": "file"},
            ),
            "canonical_nodes": ({"stage_id": "stage-unassigned", "canonical_key": "node:1"},),
            "canonical_evidence": (
                {"stage_id": "stage-unassigned", "evidence_key": "ev:1", "raw_observation_ordinal": 0},
            ),
            "canonical_edges": (
                {"stage_id": "stage-unassigned", "source_canonical_key": "node:1", "edge_kind": "contains", "target_canonical_key": "node:1", "identity_metadata_hash": "hash1"},
            ),
            "canonical_node_evidence": (
                {"stage_id": "stage-unassigned", "canonical_key": "node:1", "evidence_key": "ev:1"},
            ),
            "canonical_edge_evidence": (
                {"stage_id": "stage-unassigned", "source_canonical_key": "node:1", "edge_kind": "contains", "target_canonical_key": "node:1", "identity_metadata_hash": "hash1", "evidence_key": "ev:1"},
            ),
        }
        bundle = self._create_bundle(families=families)
        b_ref, r_ref = self._store_bundle_and_receipt(store, bundle)
        validator = PublisherBundleValidator()
        res = validator.validate_bundle(
            store=store,
            bundle_reference=b_ref,
            receipt_reference=r_ref,
            expectation=self._expectation(bundle),
        )
        self.assertTrue(res.byte_integrity_valid and res.semantic_authority_valid)

    def test_idempotent_replay_and_conflicting_attempt_reuse(self) -> None:
        store = FileSystemArtifactStore(self.tmpdir / "artifact_store")
        bundle = self._create_bundle()
        b_ref, r_ref = self._store_bundle_and_receipt(store, bundle)
        validator = PublisherBundleValidator()
        exp = self._expectation(bundle)

        res1 = validator.validate_bundle(
            store=store, bundle_reference=b_ref, receipt_reference=r_ref, expectation=exp
        )
        self.assertFalse(res1.idempotent_replay)
        res2 = validator.validate_bundle(
            store=store, bundle_reference=b_ref, receipt_reference=r_ref, expectation=exp
        )
        self.assertTrue(res2.idempotent_replay)

        alt_receipt = replace(
            self._create_receipt(bundle, b_ref), diagnostic_summary=("conflict",)
        ).reidentify()
        alt_ref = store.put(
            alt_receipt.canonical_bytes(),
            media_type="application/x-repomap-extraction-receipt-v1+json",
            record_format="canonical-json-v1",
            privacy=bundle.privacy,
        )
        with self.assertRaises(ValueError) as ctx:
            validator.validate_bundle(
                store=store, bundle_reference=b_ref, receipt_reference=alt_ref, expectation=exp
            )
        self.assertIn("conflicting attempt reuse", str(ctx.exception))

    def test_semantic_authority_mismatch_rejected(self) -> None:
        store = FileSystemArtifactStore(self.tmpdir / "artifact_store")
        bundle = self._create_bundle()
        b_ref, r_ref = self._store_bundle_and_receipt(store, bundle)
        validator = PublisherBundleValidator()
        with self.assertRaises(ValueError) as ctx:
            validator.validate_bundle(
                store=store,
                bundle_reference=b_ref,
                receipt_reference=r_ref,
                expectation=self._expectation(bundle, graph_id="different-graph-id"),
            )
        self.assertIn("bundle semantic authority mismatch", str(ctx.exception))

        accepted = validator.validate_bundle(
            store=store, bundle_reference=b_ref, receipt_reference=r_ref,
            expectation=self._expectation(bundle),
        )
        self.assertFalse(accepted.idempotent_replay)
        self.assertFalse(accepted.mutated)
        replay = validator.validate_bundle(
            store=store, bundle_reference=b_ref, receipt_reference=r_ref,
            expectation=self._expectation(bundle),
        )
        self.assertTrue(replay.idempotent_replay)
        self.assertFalse(replay.mutated)

    def test_semantic_evidence_link_violation_rejected(self) -> None:
        store = FileSystemArtifactStore(self.tmpdir / "artifact_store")
        invalid_families: dict[StageFamily, Sequence[Mapping[str, object]]] = {
            f: () for f in PUBLICATION_FAMILIES
        }
        invalid_families["canonical_evidence"] = (
            {"stage_id": "stage-unassigned", "evidence_key": "ev:1", "raw_observation_ordinal": 999},
        )
        bundle = self._create_bundle(families=invalid_families)
        b_ref, r_ref = self._store_bundle_and_receipt(store, bundle)
        validator = PublisherBundleValidator()
        with self.assertRaises(ValueError) as ctx:
            validator.validate_bundle(
                store=store,
                bundle_reference=b_ref,
                receipt_reference=r_ref,
                expectation=self._expectation(bundle),
            )
        self.assertIn("bundle semantic evidence reference is invalid", str(ctx.exception))

    def test_tampered_storage_byte_assertion_raises_integrity_error(self) -> None:
        store = FileSystemArtifactStore(self.tmpdir / "artifact_store")
        bundle = self._create_bundle()
        b_ref, r_ref = self._store_bundle_and_receipt(store, bundle)

        stored_file = store._objects / b_ref.content_digest[7:]
        stored_file.write_bytes(b"tampered-bundle-payload-corrupted")

        validator = PublisherBundleValidator()
        with self.assertRaises(ArtifactIntegrityError):
            validator.validate_bundle(
                store=store,
                bundle_reference=b_ref,
                receipt_reference=r_ref,
                expectation=self._expectation(bundle),
            )

    def test_terminal_non_completed_receipt_lifecycle_and_transition_guard(self) -> None:
        store = FileSystemArtifactStore(self.tmpdir / "artifact_store")
        failed_receipt = ExtractionReceipt.create(
            request_id="req-term-1",
            job_id="job-term-1",
            attempt=1,
            graph_id="graph-int-1",
            worker_capability_identity="cap1:portable-python-worker-v1",
            contract_version="1.0",
            source_generation="sg1",
            config_generation="cg1",
            extractor_generation="eg1",
            canonicalizer_generation="kg1",
            snapshot_manifest_id="man-int-1",
            snapshot_vector=(),
            resolver_identity="res1:standard-v1",
            extractor_capability_identity="cap1:standard-v1",
            canonicalizer_identity="canon1:standard-v1",
            semantic_contract_identity="sem1:standard-v1",
            quality_rule_identity="qual1:standard-v1",
            outcome="failed",
            cancellation="not-requested",
            bundle_reference=None,
            bundle_id=None,
            family_counts={},
            diagnostic_category="source_unavailable",
            diagnostic_summary=("upstream service offline",),
            producer_identity="producer1:portable-python-worker-v1",
            attestation_class="untrusted-self-assertion",
        )
        failed_ref = store.put(
            failed_receipt.canonical_bytes(),
            media_type="application/x-repomap-extraction-receipt-v1+json",
            record_format="canonical-json-v1",
            privacy=PrivacyClassification.PUBLIC,
        )

        validator = PublisherBundleValidator()
        validated_receipt = validator.validate_terminal_receipt(
            store=store, receipt_reference=failed_ref
        )
        self.assertEqual(validated_receipt.receipt_id, failed_receipt.receipt_id)

        bundle = self._create_bundle(job_id="job-term-1", attempt=1)
        b_ref, r_ref = self._store_bundle_and_receipt(store, bundle)
        with self.assertRaises(ValueError) as ctx:
            validator.validate_bundle(
                store=store,
                bundle_reference=b_ref,
                receipt_reference=r_ref,
                expectation=self._expectation(bundle),
            )
        self.assertIn("non-completed attempt cannot become completed", str(ctx.exception))


if __name__ == "__main__":
    import sys

    sys.exit(
        "Direct execution unsupported: RepoMap integration tests require container sandbox admission via pytest"
    )
