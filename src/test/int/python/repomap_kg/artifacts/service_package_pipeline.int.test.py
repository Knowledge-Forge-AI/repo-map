"""Cross-component integration tests for service package definitions and artifact pipelines.

Exercises:
1. Service package definitions and platform adapter rendering (Linux systemd and macOS launchd).
2. Immutable artifact storage and retrieval via FileSystemArtifactStore.
3. Artifact integrity verification and on-disk tamper rejection.
4. PublicationBundle and ExtractionReceipt publication with PublisherBundleValidator.
5. Idempotent replay and tamper detection across the store boundary.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from typing import Mapping, Sequence

from repomap_kg.artifacts.bundle import PublicationBundle
from repomap_kg.artifacts.receipt import ExtractionReceipt
from repomap_kg.artifacts.store import (
    ArtifactIntegrityError,
    FileSystemArtifactStore,
)
from repomap_kg.artifacts.validator import (
    PublicationExpectation,
    PublisherBundleValidator,
)
from repomap_kg.service_package.contract import build_service_package_spec
from repomap_kg.service_package.launchd import LaunchdUserAdapter
from repomap_kg.service_package.systemd import SystemdUserAdapter
from repomap_kg.storage.staging_family_contracts import PrivacyClassification
from repomap_kg.storage.staging_family_rows import StageFamily


from repomap_test_support.test_scratch import select_scratch_root


class ServicePackagePipelineIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = Path(
            tempfile.mkdtemp(dir=select_scratch_root(), prefix="repomap-int-service-pkg-")
        ).resolve()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_service_package_platform_adapters_and_artifact_store_lifecycle(self) -> None:
        repomap_home = self.tmpdir / "repomap_home"
        repomap_home.mkdir(parents=True, exist_ok=True)
        spec = build_service_package_spec(repomap_home)

        user_home = self.tmpdir / "user_home"
        user_home.mkdir(parents=True, exist_ok=True)

        # 1. Systemd user adapter: render and validate
        sys_adapter = SystemdUserAdapter(user_home=user_home, uid=1000)
        sys_bytes = sys_adapter.render(spec)
        self.assertTrue(len(sys_bytes) > 0)
        sys_adapter.validate(sys_bytes, spec)
        self.assertTrue(sys_adapter.recognizes(sys_bytes))

        # 2. Launchd user adapter: render and validate
        launch_adapter = LaunchdUserAdapter(user_home=user_home, uid=501)
        launch_bytes = launch_adapter.render(spec)
        self.assertTrue(len(launch_bytes) > 0)
        launch_adapter.validate(launch_bytes, spec)
        self.assertTrue(launch_adapter.recognizes(launch_bytes))

        # 3. FileSystemArtifactStore: put and read roundtrip
        store = FileSystemArtifactStore(self.tmpdir / "artifact_store")
        sys_ref = store.put(
            sys_bytes,
            media_type="text/plain",
            privacy=PrivacyClassification.PUBLIC,
        )
        launch_ref = store.put(
            launch_bytes,
            media_type="application/x-apple-plist",
            privacy=PrivacyClassification.PUBLIC,
        )

        self.assertEqual(sys_ref.size_bytes, len(sys_bytes))
        self.assertEqual(launch_ref.size_bytes, len(launch_bytes))
        self.assertTrue(store.verify(sys_ref))
        self.assertTrue(store.verify(launch_ref))

        # Validate content read back from store matches adapter contracts
        sys_read = store.read(sys_ref)
        self.assertEqual(sys_read, sys_bytes)
        sys_adapter.validate(sys_read, spec)

        launch_read = store.read(launch_ref)
        self.assertEqual(launch_read, launch_bytes)
        launch_adapter.validate(launch_read, spec)

        # 4. Tamper rejection: corrupt the artifact on disk
        obj_path = store.object_path(sys_ref)
        obj_path.write_bytes(b"TAMPERED_CONTENT_CORRUPTED_BYTES")

        self.assertFalse(store.verify(sys_ref))
        with self.assertRaises(ArtifactIntegrityError):
            store.read(sys_ref)

        # 5. Cleanup
        self.assertTrue(store.delete(launch_ref))
        self.assertFalse(store.verify(launch_ref))

    def test_publication_bundle_and_receipt_validation_with_store(self) -> None:
        store = FileSystemArtifactStore(self.tmpdir / "bundle_store")

        vector = (("src:1", 1, "s" * 64),)

        families_dict: dict[StageFamily, Sequence[Mapping[str, object]]] = {
            "files": (
                {
                    "family_ordinal": 0,
                    "path": "entry::service_config.json",
                    "language": "json",
                    "role": "source",
                    "confidence": "exact",
                    "content_hash": "sha256:" + "a" * 64,
                    "executable": False,
                    "generated": False,
                    "metadata_json": {"binding_id": vector[0][0]},
                },
            ),
            "raw_observations": (
                {
                    "source_ordinal": 0,
                    "schema_version": 1,
                    "kind": "service.definition",
                    "source_id": "obs1",
                    "path": "entry::service_config.json",
                    "payload_json": {"service": "coordinator"},
                    "payload_hash": "sha256:" + "b" * 64,
                },
            ),
            "canonical_nodes": (
                {
                    "family_ordinal": 0,
                    "graph_key_version": 1,
                    "canonical_key": "service:coordinator",
                    "kind": "Service",
                    "display_name": "Coordinator",
                    "metadata_json": {"binding_id": vector[0][0]},
                    "confidence": "exact",
                    "conflict": False,
                },
            ),
            "canonical_edges": (),
            "canonical_evidence": (
                {
                    "family_ordinal": 0,
                    "graph_key_version": 1,
                    "evidence_key": "evidence:1",
                    "raw_observation_ordinal": 0,
                    "raw_schema_version": 1,
                    "raw_kind": "service.definition",
                    "raw_source_id": "obs1",
                    "path": "entry::service_config.json",
                    "start_line": 1,
                    "end_line": 5,
                    "extractor": "service-pkg",
                    "extractor_version": "1.0",
                    "confidence": "exact",
                    "metadata_json": {"binding_id": vector[0][0]},
                },
            ),
            "canonical_node_evidence": (
                {
                    "family_ordinal": 0,
                    "graph_key_version": 1,
                    "canonical_key": "service:coordinator",
                    "evidence_key": "evidence:1",
                    "link_kind": "supports",
                },
            ),
            "canonical_edge_evidence": (),
        }

        bundle = PublicationBundle.create(
            request_id="req-int-1",
            job_id="job-int-1",
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

        bundle_ref = store.put(
            bundle.canonical_bytes(),
            media_type="application/x-repomap-publication-bundle-v1+jsonl",
            record_format="canonical-jsonl-v1",
            privacy=bundle.privacy,
        )

        receipt = ExtractionReceipt.create(
            request_id="req-int-1",
            job_id="job-int-1",
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
            bundle_reference=bundle_ref,
            bundle_id=bundle.bundle_id,
            family_counts=bundle.family_counts,
            diagnostic_category=None,
            diagnostic_summary=(),
            producer_identity="producer1:test-service-pipeline",
            attestation_class="untrusted-self-assertion",
        )

        receipt_ref = store.put(
            receipt.canonical_bytes(),
            media_type="application/json",
            record_format="canonical-json-v1",
            privacy=bundle.privacy,
        )

        expectation = PublicationExpectation.from_bundle(
            bundle,
            mutating_owner_count=1,
            expected_privacy=bundle.privacy.value,
        )

        validator = PublisherBundleValidator()
        result = validator.validate_bundle(
            store=store,
            bundle_reference=bundle_ref,
            receipt_reference=receipt_ref,
            expectation=expectation,
        )

        self.assertTrue(result.byte_integrity_valid)
        self.assertTrue(result.semantic_authority_valid)
        self.assertFalse(result.idempotent_replay)

        # Replay validation is idempotent
        result_replay = validator.validate_bundle(
            store=store,
            bundle_reference=bundle_ref,
            receipt_reference=receipt_ref,
            expectation=expectation,
        )
        self.assertTrue(result_replay.idempotent_replay)

        # Tamper rejection test: corrupt stored bundle bytes
        bundle_obj_path = store.object_path(bundle_ref)
        bundle_obj_path.write_bytes(b"tampered bundle content")

        tamper_validator = PublisherBundleValidator()
        with self.assertRaises((ArtifactIntegrityError, ValueError)):
            tamper_validator.validate_bundle(
                store=store,
                bundle_reference=bundle_ref,
                receipt_reference=receipt_ref,
                expectation=expectation,
            )

    def test_service_package_platform_adapter_rich_render_and_tamper_boundaries(self) -> None:
        repomap_home = self.tmpdir / "platform_home"
        repomap_home.mkdir(parents=True, exist_ok=True)
        spec = build_service_package_spec(repomap_home)

        user_home = self.tmpdir / "platform_user_home"
        user_home.mkdir(parents=True, exist_ok=True)

        # 1. Systemd user adapter rich unit rendering
        systemd = SystemdUserAdapter(user_home=user_home, uid=1000)
        unit_bytes = systemd.render(spec)
        unit_text = unit_bytes.decode("utf-8")
        self.assertIn("[Unit]", unit_text)
        self.assertIn("[Service]", unit_text)
        self.assertIn("[Install]", unit_text)
        self.assertIn("WantedBy=", unit_text)
        self.assertIn(str(repomap_home), unit_text)

        # 2. Launchd user adapter rich plist rendering
        launchd = LaunchdUserAdapter(user_home=user_home, uid=501)
        plist_bytes = launchd.render(spec)
        plist_text = plist_bytes.decode("utf-8")
        self.assertIn("<?xml", plist_text)
        self.assertIn("<plist", plist_text)
        self.assertIn("Label", plist_text)
        self.assertIn("ProgramArguments", plist_text)

        # 3. Store and receipt tamper boundaries
        store_dir = self.tmpdir / "tamper_store"
        store = FileSystemArtifactStore(store_dir)
        bundle_content = b'{"schema": "publication-bundle-v1", "payload": "sample"}'
        receipt_content = b'{"schema": "extraction-receipt-v1", "status": "ok"}'

        b_ref = store.put(
            bundle_content,
            media_type="application/json",
            record_format="canonical-json-v1",
            privacy=PrivacyClassification.RAW_SOURCE,
        )
        r_ref = store.put(
            receipt_content,
            media_type="application/json",
            record_format="canonical-json-v1",
            privacy=PrivacyClassification.RAW_SOURCE,
        )

        self.assertTrue(store.verify(b_ref))
        self.assertTrue(store.verify(r_ref))

        # Truncate receipt content on disk to trigger length / digest failure
        r_path = store.object_path(r_ref)
        r_path.write_bytes(b"truncated")
        with self.assertRaises(ArtifactIntegrityError):
            store.read(r_ref)


if __name__ == "__main__":
    import sys

    sys.exit(
        "Direct execution unsupported: RepoMap integration tests require container sandbox admission via pytest"
    )
