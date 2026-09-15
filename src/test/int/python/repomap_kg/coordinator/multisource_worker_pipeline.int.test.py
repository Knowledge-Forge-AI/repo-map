"""Integration tests for multi-source capture and semantic worker pipeline composition.

Exercises:
1. Multi-source snapshot capture with identical relative paths in distinct bindings.
2. Namespace isolation in candidate observations across distinct source bindings.
3. Artifact manifest sealing and relocation invariance across FileSystemArtifactStore instances.
4. Supervised portable semantic worker execution, receipt validation, and bundle verification.
5. Supervised extraction execution against relocated artifact stores.
6. Failure and refusal branches with fresh workspaces (capability mismatch, cancellation, bounds, missing manifest and file artifacts).
7. In-flight cancellation at materialization and pre-semantic checkpoints.
8. Recovery lifecycle with failure receipt persistence and terminal validator admission.
9. Bundle validator refusal on worker capability and mutating owner count mismatch.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import shutil
import tempfile
import threading
import unittest

from repomap_kg.artifacts.references import ArtifactReference
from repomap_kg.artifacts.receipt import ExtractionReceipt
from repomap_kg.artifacts.source_sealer import seal_configured_sources
from repomap_kg.artifacts.store import (
    ArtifactIntegrityError,
    FileSystemArtifactStore,
)
from repomap_kg.artifacts._store_filesystem import _filesystem_version
from repomap_kg.artifacts.validator import (
    PublicationExpectation,
    PublisherBundleValidator,
)
from repomap_kg.coordinator._portable_capability import (
    PortableExecutionCapability,
    create_portable_capability,
)
from repomap_kg.coordinator._portable_worker_launch import run_portable_worker
from repomap_kg.coordinator._portable_semantic_adapter import (
    PortableExecutionError,
    create_failure_receipt,
    execute_portable_extraction,
)
from repomap_kg.graph.multi_source import (
    graph_source_binding_id,
)
from repomap_kg.graph.multi_source_pipeline import capture_multi_source_candidate
from repomap_kg.ops.config_records import OpsGraphConfig
from repomap_test_support.portable_publication_fixtures import (
    make_test_binding,
)
from repomap_test_support.portable_worker_scenarios import (
    assert_supervised_run_portable_worker_lifecycle,
    coordinator_test_limits,
    create_test_sealed_capability,
    make_missing_manifest_reference,
)


class MultiSourceWorkerPipelineIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory(prefix="repomap-worker-pipe-")
        self.root = Path(self.tmpdir.name).resolve()
        self.store_root = self.root / "artifact_store"
        self.store_root.mkdir(mode=0o700)
        self.store = FileSystemArtifactStore(self.store_root)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    _make_binding = staticmethod(make_test_binding)

    def _ws(self, name: str) -> Path:
        d = self.root / name
        d.mkdir(mode=0o700, exist_ok=True)
        d.chmod(0o700)
        return d

    def _assert_portable_error(self, cap: PortableExecutionCapability, category: str, *, cancel: threading.Event | None = None) -> None:
        with self.assertRaises(PortableExecutionError) as cm:
            execute_portable_extraction(cap, emit_progress=lambda *_: None, cancel_event=cancel or threading.Event())
        self.assertEqual(cm.exception.category, category)

    def test_overlapping_relative_paths_in_distinct_bindings_preserve_namespaces(self) -> None:
        # Binding A
        src_a = self.root / "source_a"
        src_a.mkdir()
        (src_a / "README.md").write_text("# Source A\nShared name.\n", encoding="utf-8")
        src_a_code = src_a / "src"
        src_a_code.mkdir()
        (src_a_code / "index.ts").write_text("export const A = 1;\n", encoding="utf-8")

        # Binding B (identical relative paths README.md and src/index.ts)
        src_b = self.root / "source_b"
        src_b.mkdir()
        (src_b / "README.md").write_text("# Source B\nShared name.\n", encoding="utf-8")
        src_b_code = src_b / "src"
        src_b_code.mkdir()
        (src_b_code / "index.ts").write_text("export const B = 2;\n", encoding="utf-8")

        binding_a = self._make_binding("multi-graph", "alpha", src_a, "entry")
        binding_b = self._make_binding("multi-graph", "beta", src_b, "dependency")
        config = OpsGraphConfig(
            id="multi-graph", name="Multi Graph", root_path="", root_path_expanded="",
            repository_name="repo-alpha", privacy="public-dev", enabled=True, mcp_visible=True,
            extractor_profile="default", refresh_policy="manual",
            source_bindings=(binding_a, binding_b), explicit_source_bindings=True,
        )

        # 1. Capture candidate and assert namespace isolation via actual production contract
        candidate = capture_multi_source_candidate(config)
        self.assertGreater(len(candidate.observations), 0)

        # Observations are namespaced with binding_id prefix on source_id
        for obs in candidate.observations:
            binding_id = obs.metadata.get("binding_id")
            self.assertIn(binding_id, (binding_a.binding_id, binding_b.binding_id))
            self.assertTrue(obs.source_id.startswith(f"{binding_id}:"))
            alias = obs.metadata.get("binding_alias")
            self.assertIn(alias, ("alpha", "beta"))
            self.assertTrue(obs.path.startswith(f"{alias}/"))
            self.assertIn("source_relative_path", obs.metadata)

        # Cross-binding separation: assert both aliases are present and overlapping files are separated
        aliases = {obs.metadata.get("binding_alias") for obs in candidate.observations}
        self.assertEqual(aliases, {"alpha", "beta"})
        paths = {obs.path for obs in candidate.observations}
        self.assertIn("alpha/README.md", paths)
        self.assertIn("beta/README.md", paths)
        self.assertIn("alpha/src/index.ts", paths)
        self.assertIn("beta/src/index.ts", paths)

        # 2. Seal sources into store and verify relocation-invariant manifest
        manifest, reference, candidate_id = seal_configured_sources(
            config,
            self.store,
            extractor_generation="eg1:portable",
            canonicalizer_generation="kg1:portable",
        )
        self.assertIsNotNone(manifest)
        self.assertTrue(self.store.verify(reference))
        self.assertTrue(candidate_id.startswith("cand1:"))
        manifest_bytes = manifest.canonical_bytes()
        self.assertEqual(self.store.read(reference), manifest_bytes)

        # Relocation-invariant verification: copy artifact directory to new root and verify via second store
        relocated_dir = self.root / "relocated_store"
        shutil.copytree(self.store_root, relocated_dir)
        relocated_store = FileSystemArtifactStore(relocated_dir)
        self.assertFalse(relocated_store.verify(reference))
        relocated_reference = ArtifactReference.from_semantic_mapping(reference.semantic_mapping())
        self.assertTrue(relocated_store.verify(relocated_reference))
        self.assertEqual(relocated_store.read(relocated_reference), manifest_bytes)
        relocated_version = _filesystem_version(relocated_store.object_path(reference).stat())
        relocated_physical_reference = reference.with_store_version(relocated_version)
        self.assertTrue(relocated_store.verify(relocated_physical_reference))

        # 3. Supervised semantic worker execution and bundle validation
        ws = self._ws("worker_ws")
        capability = PortableExecutionCapability(
            schema_version=1,
            job_id="job-multi-worker-1",
            attempt=1,
            graph_id=manifest.graph_id,
            store_root=self.store_root,
            workspace_root=ws,
            manifest_reference=reference,
            source_generation=manifest.source_generation,
            config_generation=manifest.config_generation,
            extractor_generation=manifest.extractor_generation,
            canonicalizer_generation=manifest.canonicalizer_generation,
            max_artifact_bytes=10 * 1024 * 1024,
            max_bundle_bytes=10 * 1024 * 1024,
        )

        progress_events: list[tuple[str, int, int]] = []
        result = execute_portable_extraction(
            capability,
            emit_progress=lambda stage, current, total: progress_events.append((stage, current, total)),
            cancel_event=threading.Event(),
        )
        self.assertEqual(result.receipt.outcome, "completed")
        self.assertEqual(result.receipt.snapshot_manifest_id, manifest.manifest_id)
        self.assertEqual(result.candidate_id, candidate_id)
        self.assertGreater(len(progress_events), 0)

        # Relocated store worker execution produces invariant candidate and bundle references
        ws_relocated = self._ws("worker_ws_relocated")
        relocated_cap = replace(capability, store_root=relocated_dir, workspace_root=ws_relocated, manifest_reference=relocated_physical_reference)
        relocated_result = execute_portable_extraction(
            relocated_cap,
            emit_progress=lambda *_: None,
            cancel_event=threading.Event(),
        )
        self.assertEqual(relocated_result.receipt.outcome, "completed")
        self.assertEqual(relocated_result.candidate_id, candidate_id)
        self.assertEqual(relocated_result.bundle_reference, result.bundle_reference)

        # Verify publication bundle through PublisherBundleValidator
        validator = PublisherBundleValidator()
        expected = PublicationExpectation(
            request_id=capability.job_id, job_id=capability.job_id, attempt=capability.attempt,
            graph_id=config.id, candidate_id=candidate_id,
            snapshot_manifest_id=manifest.manifest_id, snapshot_vector=manifest.snapshot_vector,
            source_generation=capability.source_generation,
            config_generation=capability.config_generation,
            extractor_generation=capability.extractor_generation,
            canonicalizer_generation=capability.canonicalizer_generation,
            extractor_capability_identity=manifest.extractor_capability_identity,
            resolver_identity=manifest.resolver_identity,
            canonicalizer_identity=manifest.canonicalizer_identity,
            semantic_contract_identity=manifest.semantic_contract_identity,
            quality_rule_identity=manifest.quality_rule_identity, mutating_owner_count=1,
            worker_capability_identity="cap1:portable-python-worker-v1",
            expected_privacy=manifest.effective_privacy.value,
        )
        validation = validator.validate_bundle(
            store=self.store,
            bundle_reference=result.bundle_reference,
            receipt_reference=result.receipt_reference,
            expectation=expected,
        )
        self.assertTrue(validation.byte_integrity_valid)
        self.assertTrue(validation.semantic_authority_valid)

        # 4. Refusal and failure branches with fresh workspaces and specific error categories
        # Capability identity mismatch rejects execution with contract_validation category
        self._assert_portable_error(
            replace(capability, graph_id="wrong-graph-id", workspace_root=self._ws("worker_ws_mismatch")),
            "contract_validation",
        )
        # Pre-set cancellation event cancels cleanly with cancelled category
        cancel_ev = threading.Event()
        cancel_ev.set()
        self._assert_portable_error(
            replace(capability, workspace_root=self._ws("worker_ws_cancelled")),
            "cancelled",
            cancel=cancel_ev,
        )
        # Manifest bounds refusal when manifest exceeds max_artifact_bytes
        self._assert_portable_error(
            replace(capability, max_artifact_bytes=32, workspace_root=self._ws("worker_ws_bounds")),
            "manifest_bounds",
        )
        # Missing manifest artifact refusal
        self._assert_portable_error(
            replace(capability, manifest_reference=make_missing_manifest_reference(), workspace_root=self._ws("worker_ws_missing")),
            "artifact_missing",
        )

        # Dynamic in-flight cancellation via checkpoint callback
        ws_inflight = self._ws("worker_ws_inflight")
        inflight_cap = replace(capability, workspace_root=ws_inflight)
        inflight_cancel = threading.Event()
        checkpoint_stages: list[str] = []

        def on_checkpoint(stage: str) -> None:
            checkpoint_stages.append(stage)
            if stage == "before_semantic":
                inflight_cancel.set()

        with self.assertRaises(PortableExecutionError) as cm_inflight:
            execute_portable_extraction(
                inflight_cap,
                emit_progress=lambda *_: None,
                cancel_event=inflight_cancel,
                checkpoint=on_checkpoint,
            )
        self.assertEqual(cm_inflight.exception.category, "cancelled")
        self.assertIn("before_semantic", checkpoint_stages)

        # Missing source content artifact during workspace materialization raises artifact_missing
        ws_missing_blob = self._ws("worker_ws_missing_blob")
        tampered_store_dir = self.root / "tampered_store"
        shutil.copytree(self.store_root, tampered_store_dir)
        tampered_store = FileSystemArtifactStore(tampered_store_dir)
        entry = next(item for item in manifest.entries
                     if item.source_relative_path == "README.md"
                     and item.binding_id == graph_source_binding_id("multi-graph", "alpha"))
        tampered_entry_ref = ArtifactReference.from_semantic_mapping(entry.reference.semantic_mapping())
        with self.assertRaises(ArtifactIntegrityError) as cm_del:
            tampered_store.delete(entry.reference)
        self.assertEqual(cm_del.exception.code, "artifact_stale")
        self.assertTrue(tampered_store.delete(tampered_entry_ref))
        self.assertFalse(tampered_store.verify(reference))
        tampered_version = _filesystem_version(tampered_store.object_path(reference).stat())
        tampered_manifest_ref = reference.with_store_version(tampered_version)
        self.assertTrue(tampered_store.verify(tampered_manifest_ref))
        tampered_cap = replace(capability, store_root=tampered_store_dir, workspace_root=ws_missing_blob, manifest_reference=tampered_manifest_ref)
        with self.assertRaises(PortableExecutionError) as cm_missing_blob:
            execute_portable_extraction(tampered_cap, emit_progress=lambda *_: None, cancel_event=threading.Event())
        self.assertEqual(cm_missing_blob.exception.category, "artifact_missing")

        # Dynamic in-flight cancellation during workspace materialization
        ws_cancel_mat = self._ws("worker_ws_cancel_mat")
        mat_cap = replace(capability, workspace_root=ws_cancel_mat)
        mat_cancel = threading.Event()
        with self.assertRaises(PortableExecutionError) as cm_mat_cancel:
            execute_portable_extraction(
                mat_cap,
                emit_progress=lambda *_: None,
                cancel_event=mat_cancel,
                checkpoint=lambda s: mat_cancel.set() if s == "during_materialization" else None,
            )
        self.assertEqual(cm_mat_cancel.exception.category, "cancelled")

        # 5. Recovery lifecycle: create_failure_receipt persistence and validator admission
        failure_write = create_failure_receipt(
            replace(capability, job_id="job-failed-attempt"),
            category="contract_validation",
            store=self.store,
            manifest=manifest,
        )
        self.assertEqual(failure_write.status, "stored")
        assert failure_write.reference is not None
        self.assertIsNone(failure_write.diagnostic)
        self.assertTrue(self.store.verify(failure_write.reference))

        failure_receipt_bytes = self.store.read(failure_write.reference)
        failure_receipt = ExtractionReceipt.from_bytes(failure_receipt_bytes)
        self.assertEqual(failure_receipt.outcome, "failed")
        self.assertEqual(failure_receipt.cancellation, "not-requested")
        self.assertEqual(failure_receipt.diagnostic_category, "contract_validation")
        self.assertIsNone(failure_receipt.bundle_reference)
        self.assertIsNone(failure_receipt.bundle_id)

        # Non-completed failure receipt admitted by PublisherBundleValidator
        terminal_receipt = validator.validate_terminal_receipt(
            store=self.store,
            receipt_reference=failure_write.reference,
        )
        self.assertEqual(terminal_receipt.receipt_id, failure_receipt.receipt_id)

        # Cancellation receipt persistence verification
        cancelled_write = create_failure_receipt(
            replace(capability, job_id="job-cancelled-attempt"),
            category="cancelled",
            store=self.store,
            manifest=manifest,
            cancellation_requested=True,
        )
        self.assertEqual(cancelled_write.status, "stored")
        assert cancelled_write.reference is not None
        cancelled_receipt = ExtractionReceipt.from_bytes(
            self.store.read(cancelled_write.reference)
        )
        self.assertEqual(cancelled_receipt.outcome, "cancelled")
        self.assertEqual(cancelled_receipt.cancellation, "requested")

        # 6. Bundle validator refusal on mismatched expectations
        valid_exp = expected
        # Worker capability identity mismatch rejected
        mismatched_worker_exp = replace(
            valid_exp,
            worker_capability_identity="cap1:unauthorized-worker-identity",
        )
        with self.assertRaises(ValueError) as cm_val_worker:
            validator.validate_bundle(
                store=self.store,
                bundle_reference=result.bundle_reference,
                receipt_reference=result.receipt_reference,
                expectation=mismatched_worker_exp,
            )
        self.assertIn("worker capability identity mismatch", str(cm_val_worker.exception))

        # Mutating owner count mismatch rejected
        mismatched_owner_exp = replace(valid_exp, mutating_owner_count=2)
        with self.assertRaises(ValueError) as cm_val_owner:
            validator.validate_bundle(
                store=self.store,
                bundle_reference=result.bundle_reference,
                receipt_reference=result.receipt_reference,
                expectation=mismatched_owner_exp,
            )
        self.assertIn("exactly one mutating owner is required", str(cm_val_owner.exception))

    def test_supervised_run_portable_worker_coordinator_validation_and_refusals(self) -> None:
        priv = self._ws("sup_priv")
        cap = create_test_sealed_capability(self.root, self.store, self._ws("sup_ws"))
        assert_supervised_run_portable_worker_lifecycle(self, priv, cap)
        # Artifact store relocation invariance under supervised worker
        reloc_dir = self.root / "relocated_store"
        shutil.copytree(self.store_root, reloc_dir)
        reloc_store = FileSystemArtifactStore(reloc_dir)
        reloc_version = _filesystem_version(reloc_store.object_path(cap.manifest_reference).stat())
        reloc_ref = cap.manifest_reference.with_store_version(reloc_version)
        reloc_cap = replace(cap, store_root=reloc_dir, job_id="job-reloc-worker", workspace_root=self._ws("reloc_ws"), manifest_reference=reloc_ref)
        reloc_cap_path = create_portable_capability(priv, reloc_cap)
        res = run_portable_worker(reloc_cap_path, {"job_id": "job-reloc-worker", "attempt": 1}, coordinator_test_limits())
        self.assertEqual(res.terminal.get("status"), "succeeded")
        self.assertFalse(reloc_cap_path.exists())
        self.assertIsNone(res.cleanup_error)
        self.assertEqual(tuple(reloc_cap.workspace_root.iterdir()), ())
