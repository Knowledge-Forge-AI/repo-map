"""Integration tests for service package validation refusals.

Exercises terminal receipt failure transitions, conflicting completed attempt
rejections, publication expectation mismatches, and platform adapter directive
refusals.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import shutil
import tempfile
import unittest

from repomap_kg.artifacts._store_filesystem import FileSystemArtifactStore
from repomap_kg.artifacts._store_common import ArtifactIntegrityError
from repomap_kg.artifacts.bundle import PublicationBundle
from repomap_kg.artifacts.receipt import ExtractionReceipt
from repomap_kg.artifacts.validator import (
    PublicationExpectation,
    PublisherBundleValidator,
)
from repomap_kg.service_package.contract import build_service_package_spec
from repomap_kg.service_package.launchd import LaunchdUserAdapter
from repomap_kg.service_package.systemd import SystemdUserAdapter
from repomap_kg.storage.staging_family_contracts import PrivacyClassification
from repomap_test_support.test_scratch import select_scratch_root
from repomap_test_support.service_publication_families import (
    sample_publication_families as _sample_publication_families,
)




class ServicePackageRefusalsIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = Path(
            tempfile.mkdtemp(
                dir=select_scratch_root(),
                prefix="repomap-int-service-refusals-",
            )
        ).resolve()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_terminal_receipt_validation_and_conflicting_completed_refusal(self) -> None:
        store = FileSystemArtifactStore(self.tmpdir / "terminal_store")
        vector = (("src:1", 1, "s" * 64),)
        families_dict = _sample_publication_families(vector)

        # 1. Non-completed terminal receipt validation
        term_receipt = ExtractionReceipt.create(
            request_id="req-term-1",
            job_id="job-term-1",
            attempt=1,
            graph_id="graph-main",
            worker_capability_identity="cap1:portable-worker-v1",
            contract_version="1.0",
            source_generation="sg1:" + "1" * 64,
            config_generation="cg1:" + "2" * 64,
            extractor_generation="eg1:" + "3" * 64,
            canonicalizer_generation="kg1:" + "4" * 64,
            snapshot_manifest_id="manifest-1",
            snapshot_vector=vector,
            resolver_identity="resolver1:standard-v1",
            extractor_capability_identity="cap1:service-pipeline-v1",
            canonicalizer_identity="canon1:canonical-v1",
            semantic_contract_identity="semantic1:core-v1",
            quality_rule_identity="quality1:standard-v1",
            outcome="failed",
            cancellation="not-requested",
            bundle_reference=None,
            bundle_id=None,
            family_counts={},
            diagnostic_category="artifact_corrupt",
            diagnostic_summary=("corrupt artifact input",),
            producer_identity="producer1:test-service-pipeline",
            attestation_class="untrusted-self-assertion",
        )
        term_ref = store.put(
            term_receipt.canonical_bytes(),
            media_type="application/json",
            record_format="canonical-json-v1",
            privacy=PrivacyClassification.PUBLIC,
        )
        validator = PublisherBundleValidator()
        validated_terminal = validator.validate_terminal_receipt(
            store=store,
            receipt_reference=term_ref,
        )
        self.assertEqual(validated_terminal.outcome, "failed")

        # 2. Conflicting attempt reuse: completed attempt cannot succeed failed terminal
        bundle = PublicationBundle.create(
            request_id="req-term-1",
            job_id="job-term-1",
            attempt=1,
            graph_id="graph-main",
            candidate_id="cand-1",
            snapshot_manifest_id="manifest-1",
            snapshot_vector=vector,
            source_generation=term_receipt.source_generation,
            config_generation=term_receipt.config_generation,
            extractor_generation=term_receipt.extractor_generation,
            canonicalizer_generation=term_receipt.canonicalizer_generation,
            extractor_capability_identity=term_receipt.extractor_capability_identity,
            resolver_identity=term_receipt.resolver_identity,
            canonicalizer_identity=term_receipt.canonicalizer_identity,
            semantic_contract_identity=term_receipt.semantic_contract_identity,
            quality_rule_identity=term_receipt.quality_rule_identity,
            privacy=PrivacyClassification.PUBLIC,
            families=families_dict,
            row_stage_contract="legacy-absent-v1",
        )
        b_ref = store.put(
            bundle.canonical_bytes(),
            media_type="application/x-repomap-publication-bundle-v1+jsonl",
            record_format="canonical-jsonl-v1",
            privacy=bundle.privacy,
        )
        comp_receipt = replace(
            term_receipt,
            outcome="completed",
            bundle_id=bundle.bundle_id,
            bundle_reference=b_ref,
            family_counts=bundle.family_counts,
            diagnostic_category=None,
            diagnostic_summary=(),
        ).reidentify()
        r_ref = store.put(
            comp_receipt.canonical_bytes(),
            media_type="application/json",
            record_format="canonical-json-v1",
            privacy=bundle.privacy,
        )
        expectation = PublicationExpectation.from_bundle(bundle, mutating_owner_count=1)

        with self.assertRaises(ValueError) as ctx_term:
            validator.validate_bundle(
                store=store,
                bundle_reference=b_ref,
                receipt_reference=r_ref,
                expectation=expectation,
            )
        self.assertIn("non-completed attempt cannot become completed", str(ctx_term.exception))

    def test_bundle_validator_semantic_mismatch_refusals(self) -> None:
        store = FileSystemArtifactStore(self.tmpdir / "mismatch_store")
        vector = (("src:1", 1, "s" * 64),)
        families_dict = _sample_publication_families(vector)

        bundle = PublicationBundle.create(
            request_id="req-mismatch-1",
            job_id="job-mismatch-1",
            attempt=1,
            graph_id="graph-main",
            candidate_id="cand-1",
            snapshot_manifest_id="manifest-1",
            snapshot_vector=vector,
            source_generation="sg1:" + "1" * 64,
            config_generation="cg1:" + "2" * 64,
            extractor_generation="eg1:" + "3" * 64,
            canonicalizer_generation="kg1:" + "4" * 64,
            extractor_capability_identity="cap1:service-pipeline-v1",
            resolver_identity="resolver1:standard-v1",
            canonicalizer_identity="canon1:canonical-v1",
            semantic_contract_identity="semantic1:core-v1",
            quality_rule_identity="quality1:standard-v1",
            privacy=PrivacyClassification.PUBLIC,
            families=families_dict,
            row_stage_contract="legacy-absent-v1",
        )
        b_ref = store.put(
            bundle.canonical_bytes(),
            media_type="application/x-repomap-publication-bundle-v1+jsonl",
            record_format="canonical-jsonl-v1",
            privacy=bundle.privacy,
        )
        receipt = ExtractionReceipt.create(
            request_id="req-mismatch-1",
            job_id="job-mismatch-1",
            attempt=1,
            graph_id="graph-main",
            worker_capability_identity="cap1:portable-worker-v1",
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
            outcome="completed",
            cancellation="not-requested",
            bundle_reference=b_ref,
            bundle_id=bundle.bundle_id,
            family_counts=bundle.family_counts,
            diagnostic_category=None,
            diagnostic_summary=(),
            producer_identity="producer1:test-service-pipeline",
            attestation_class="untrusted-self-assertion",
        )
        r_ref = store.put(
            receipt.canonical_bytes(),
            media_type="application/json",
            record_format="canonical-json-v1",
            privacy=bundle.privacy,
        )
        expectation = PublicationExpectation.from_bundle(bundle, mutating_owner_count=1)

        fresh_validator = PublisherBundleValidator()
        bad_owner_exp = replace(expectation, mutating_owner_count=2)
        with self.assertRaises(ValueError) as ctx_owner:
            fresh_validator.validate_bundle(
                store=store,
                bundle_reference=b_ref,
                receipt_reference=r_ref,
                expectation=bad_owner_exp,
            )
        self.assertIn("exactly one mutating owner is required", str(ctx_owner.exception))

        bad_priv_exp = replace(
            expectation,
            expected_privacy=PrivacyClassification.CANONICAL_GRAPH.value,
        )
        with self.assertRaises(ValueError) as ctx_priv:
            fresh_validator.validate_bundle(
                store=store,
                bundle_reference=b_ref,
                receipt_reference=r_ref,
                expectation=bad_priv_exp,
            )
        self.assertIn("bundle privacy mismatch", str(ctx_priv.exception))
        # Refusals preserve immutable artifacts and do not reserve the attempt.
        self.assertEqual(store.read(b_ref), bundle.canonical_bytes())
        self.assertEqual(store.read(r_ref), receipt.canonical_bytes())
        accepted = fresh_validator.validate_bundle(
            store=store, bundle_reference=b_ref, receipt_reference=r_ref,
            expectation=expectation,
        )
        self.assertFalse(accepted.idempotent_replay)
        for reference in (b_ref, r_ref):
            with self.subTest(unsafe_artifact=reference.content_digest):
                artifact_path = store.object_path(reference)
                artifact_path.chmod(0o644)
                try:
                    with self.assertRaisesRegex(ArtifactIntegrityError, "permissions are unsafe"):
                        fresh_validator.validate_bundle(
                            store=store, bundle_reference=b_ref, receipt_reference=r_ref,
                            expectation=expectation,
                        )
                finally:
                    artifact_path.chmod(0o600)
                self.assertEqual(store.read(reference), (
                    bundle.canonical_bytes() if reference == b_ref else receipt.canonical_bytes()
                ))
        replay = fresh_validator.validate_bundle(
            store=store, bundle_reference=b_ref, receipt_reference=r_ref,
            expectation=expectation,
        )
        self.assertTrue(replay.idempotent_replay)
        self.assertEqual(replay.bundle_id, bundle.bundle_id)
        self.assertEqual(store.read(b_ref), bundle.canonical_bytes())
        self.assertEqual(store.read(r_ref), receipt.canonical_bytes())


    def test_platform_adapter_negative_directive_refusals(self) -> None:
        repomap_home = self.tmpdir / "invalid_plat_home"
        repomap_home.mkdir(parents=True, exist_ok=True)
        spec = build_service_package_spec(repomap_home)

        sys_adapter = SystemdUserAdapter(user_home=self.tmpdir / "user_home", uid=1000)
        with self.assertRaises(ValueError) as ctx_sys:
            sys_adapter.validate(b"[Unit]\nDescription=Invalid\n", spec)
        self.assertEqual(str(ctx_sys.exception), "service_definition_invalid")

        launch_adapter = LaunchdUserAdapter(user_home=self.tmpdir / "user_home", uid=501)
        invalid_plist = (
            b"<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
            b"<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" "
            b"\"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">\n"
            b"<plist version=\"1.0\"><dict></dict></plist>"
        )
        with self.assertRaises(ValueError) as ctx_launch:
            launch_adapter.validate(invalid_plist, spec)
        self.assertEqual(str(ctx_launch.exception), "service_definition_invalid")

    def test_conflicting_completed_attempt_and_inconsistent_terminal_refusals(self) -> None:
        store = FileSystemArtifactStore(self.tmpdir / "conflict_store")
        vector = (("src:1", 1, "s" * 64),)
        families_dict = _sample_publication_families(vector)

        bundle = PublicationBundle.create(
            request_id="req-conf-1", job_id="job-conf-1", attempt=1,
            graph_id="graph-main", candidate_id="cand-1",
            snapshot_manifest_id="manifest-1", snapshot_vector=vector,
            source_generation="sg1:" + "1" * 64, config_generation="cg1:" + "2" * 64,
            extractor_generation="eg1:" + "3" * 64, canonicalizer_generation="kg1:" + "4" * 64,
            extractor_capability_identity="cap1:service-pipeline-v1",
            resolver_identity="resolver1:standard-v1", canonicalizer_identity="canon1:canonical-v1",
            semantic_contract_identity="semantic1:core-v1", quality_rule_identity="quality1:standard-v1",
            privacy=PrivacyClassification.PUBLIC, families=families_dict, row_stage_contract="legacy-absent-v1",
        )
        b_ref = store.put(
            bundle.canonical_bytes(), media_type="application/x-repomap-publication-bundle-v1+jsonl",
            record_format="canonical-jsonl-v1", privacy=bundle.privacy,
        )
        receipt = ExtractionReceipt.create(
            request_id="req-conf-1", job_id="job-conf-1", attempt=1, graph_id="graph-main",
            worker_capability_identity="cap1:portable-worker-v1", contract_version="1.0",
            source_generation=bundle.source_generation, config_generation=bundle.config_generation,
            extractor_generation=bundle.extractor_generation, canonicalizer_generation=bundle.canonicalizer_generation,
            snapshot_manifest_id=bundle.snapshot_manifest_id, snapshot_vector=bundle.snapshot_vector,
            resolver_identity=bundle.resolver_identity, extractor_capability_identity=bundle.extractor_capability_identity,
            canonicalizer_identity=bundle.canonicalizer_identity, semantic_contract_identity=bundle.semantic_contract_identity,
            quality_rule_identity=bundle.quality_rule_identity, outcome="completed", cancellation="not-requested",
            bundle_reference=b_ref, bundle_id=bundle.bundle_id, family_counts=bundle.family_counts,
            diagnostic_category=None, diagnostic_summary=(), producer_identity="producer1:test-service-pipeline", attestation_class="untrusted-self-assertion",
        )
        r_ref = store.put(
            receipt.canonical_bytes(), media_type="application/json",
            record_format="canonical-json-v1", privacy=bundle.privacy,
        )
        expectation = PublicationExpectation.from_bundle(bundle, mutating_owner_count=1)

        validator = PublisherBundleValidator()
        res = validator.validate_bundle(store=store, bundle_reference=b_ref, receipt_reference=r_ref, expectation=expectation)
        self.assertTrue(res.byte_integrity_valid)

        # 1. Inconsistent terminal state: cancellation requested refused
        bad_receipt = replace(receipt, cancellation="requested").reidentify()
        bad_r_ref = store.put(
            bad_receipt.canonical_bytes(), media_type="application/json",
            record_format="canonical-json-v1", privacy=bundle.privacy,
        )
        with self.assertRaises(ValueError) as ctx_incon:
            validator.validate_bundle(store=store, bundle_reference=b_ref, receipt_reference=bad_r_ref, expectation=expectation)
        self.assertIn("receipt and bundle terminal state is inconsistent", str(ctx_incon.exception))

        # 2. Conflicting attempt reuse: distinct candidate cannot replace completed attempt
        alt_bundle = PublicationBundle.create(
            request_id=bundle.request_id, job_id=bundle.job_id, attempt=bundle.attempt,
            graph_id=bundle.graph_id, candidate_id="cand-alt",
            snapshot_manifest_id=bundle.snapshot_manifest_id,
            snapshot_vector=bundle.snapshot_vector,
            source_generation=bundle.source_generation,
            config_generation=bundle.config_generation,
            extractor_generation=bundle.extractor_generation,
            canonicalizer_generation=bundle.canonicalizer_generation,
            extractor_capability_identity=bundle.extractor_capability_identity,
            resolver_identity=bundle.resolver_identity,
            canonicalizer_identity=bundle.canonicalizer_identity,
            semantic_contract_identity=bundle.semantic_contract_identity,
            quality_rule_identity=bundle.quality_rule_identity,
            privacy=bundle.privacy, families=bundle.families,
            row_stage_contract=bundle.row_stage_contract,
        )
        alt_b_ref = store.put(
            alt_bundle.canonical_bytes(), media_type="application/x-repomap-publication-bundle-v1+jsonl",
            record_format="canonical-jsonl-v1", privacy=alt_bundle.privacy,
        )
        alt_receipt = replace(receipt, bundle_id=alt_bundle.bundle_id, bundle_reference=alt_b_ref).reidentify()
        alt_r_ref = store.put(
            alt_receipt.canonical_bytes(), media_type="application/json",
            record_format="canonical-json-v1", privacy=alt_bundle.privacy,
        )
        alt_exp = PublicationExpectation.from_bundle(alt_bundle, mutating_owner_count=1)
        with self.assertRaises(ValueError) as ctx_conf:
            validator.validate_bundle(store=store, bundle_reference=alt_b_ref, receipt_reference=alt_r_ref, expectation=alt_exp)
        self.assertIn("conflicting attempt reuse", str(ctx_conf.exception))

        # 3. Preserved prior state: original attempt remains accepted on replay
        replay = validator.validate_bundle(store=store, bundle_reference=b_ref, receipt_reference=r_ref, expectation=expectation)
        self.assertTrue(replay.idempotent_replay)
        self.assertEqual(replay.bundle_id, bundle.bundle_id)
        self.assertEqual(store.read(b_ref), bundle.canonical_bytes())
        self.assertEqual(store.read(r_ref), receipt.canonical_bytes())


if __name__ == "__main__":
    import sys

    sys.exit(
        "Direct execution unsupported: RepoMap integration tests require container sandbox admission via pytest"
    )

