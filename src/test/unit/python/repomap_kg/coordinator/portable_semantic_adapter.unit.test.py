"""Unit tests for portable semantic adapter branches, diagnostics, and error mapping."""

from __future__ import annotations
from typing import Callable

import threading
import unittest
from unittest.mock import MagicMock

from repomap_kg.artifacts.store import (
    ArtifactErrorCode,
    ArtifactIntegrityError,
    ArtifactStore,
)
from repomap_kg.coordinator import _portable_semantic_adapter as psa
from repomap_kg.coordinator._portable_capability import PortableExecutionCapability


class PortableSemanticAdapterDiagnosticUnitTests(unittest.TestCase):
    """Test error categorization and receipt write diagnostics."""

    def test_artifact_error_category_mapping(self):
        for code, expected in (
            (ArtifactErrorCode.ARTIFACT_MISSING, "artifact_missing"),
            (ArtifactErrorCode.ARTIFACT_STALE, "artifact_stale"),
            (ArtifactErrorCode.ARTIFACT_CORRUPT, "artifact_corrupt"),
            (ArtifactErrorCode.ARTIFACT_BOUNDS, "custom_bounds"),
            (ArtifactErrorCode.STORE_UNAVAILABLE, "artifact_corrupt"),
            (ArtifactErrorCode.PERMISSION_DENIED, "artifact_corrupt"),
        ):
            with self.subTest(code=code):
                err = ArtifactIntegrityError("test error", code=code)
                cat = psa._artifact_error_category(err, bounds_category="custom_bounds")
                self.assertEqual(cat, expected)

    def test_receipt_write_diagnostic_mapping(self):
        cases = [
            (ArtifactIntegrityError("err", code=ArtifactErrorCode.STORE_UNAVAILABLE), "store_unavailable"),
            (ArtifactIntegrityError("err", code=ArtifactErrorCode.ARTIFACT_MISSING), "store_unavailable"),
            (ArtifactIntegrityError("err", code=ArtifactErrorCode.PERMISSION_DENIED), "permission_denied"),
            (ArtifactIntegrityError("err", code=ArtifactErrorCode.ARTIFACT_BOUNDS), "receipt_bounds"),
            (ArtifactIntegrityError("err", code=ArtifactErrorCode.WRITE_FAILED), "write_failed"),
            (ArtifactIntegrityError("err", code=ArtifactErrorCode.ARTIFACT_STALE), "write_failed"),
            (ArtifactIntegrityError("err", code=ArtifactErrorCode.ARTIFACT_CORRUPT), "write_failed"),
            (PermissionError("denied"), "permission_denied"),
            (RuntimeError("generic failure"), "write_failed"),
        ]
        for err, expected in cases:
            with self.subTest(err=err):
                diag = psa._receipt_write_diagnostic(err)
                self.assertEqual(diag, expected)

    def test_cancellation_and_checkpoint_helpers(self):
        event = threading.Event()
        cancelled: Callable[[threading.Event], object] = psa._cancelled
        psa_res = cancelled(event)
        self.assertIsNone(psa_res)

        observed: list[str] = []
        psa._checkpoint("step1", event, observed.append)
        self.assertEqual(observed, ["step1"])

        event.set()
        with self.assertRaises(psa.PortableExecutionError) as caught:
            psa._cancelled(event)
        self.assertEqual(caught.exception.category, "cancelled")

        with self.assertRaises(psa.PortableExecutionError):
            psa._checkpoint("step2", event, observed.append)


class CreateFailureReceiptUnitTests(unittest.TestCase):
    """Test create_failure_receipt branches."""

    def _make_capability(self):
        ref = MagicMock()
        ref.content_digest = "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        cap = MagicMock(spec=PortableExecutionCapability)
        cap.job_id = "job-1"
        cap.attempt = 1
        cap.graph_id = "graph-test"
        cap.source_generation = "sg1"
        cap.config_generation = "cg1"
        cap.extractor_generation = "eg1"
        cap.canonicalizer_generation = "kg1"
        cap.manifest_reference = ref
        cap.store_root = "/nonexistent/store"
        return cap

    def test_create_failure_receipt_cancelled_status(self):
        store = MagicMock(spec=ArtifactStore)
        stored_ref = MagicMock()
        store.put.return_value = stored_ref
        cap = self._make_capability()

        res = psa.create_failure_receipt(
            cap, "cancelled", store=store, manifest=None, cancellation_requested=True
        )
        self.assertEqual(res.status, "stored")
        self.assertEqual(res.reference, stored_ref)
        self.assertIsNone(res.diagnostic)

    def test_create_failure_receipt_handles_store_error_gracefully(self):
        store = MagicMock(spec=ArtifactStore)
        store.put.side_effect = PermissionError("no write permission")
        cap = self._make_capability()

        res = psa.create_failure_receipt(
            cap, "source_unavailable", store=store, manifest=None
        )
        self.assertEqual(res.status, "unavailable")
        self.assertIsNone(res.reference)
        self.assertEqual(res.diagnostic, "permission_denied")

    def test_sealed_bindings_rejects_missing_alias(self):
        binding = MagicMock()
        binding.alias = None
        manifest = MagicMock()
        manifest.bindings = [binding]

        with self.assertRaises(psa.PortableExecutionError) as caught:
            psa._sealed_bindings(manifest, {})
        self.assertEqual(caught.exception.category, "unsupported_contract")


if __name__ == "__main__":
    unittest.main()
