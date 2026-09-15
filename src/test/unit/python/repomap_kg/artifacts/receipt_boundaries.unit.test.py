"""Unit tests for extraction receipt validation boundaries and serialization checks."""

from __future__ import annotations

import unittest

from repomap_kg.artifacts.receipt import (
    DIAGNOSTIC_CATEGORIES,
    PUBLIC_DIAGNOSTIC_PROJECTION,
    RECEIPT_OUTCOMES,
    ExtractionReceipt,
)


def _base_receipt_kwargs():
    return {
        "request_id": "req-1",
        "job_id": "job-1",
        "attempt": 1,
        "graph_id": "graph-1",
        "worker_capability_identity": "cap1:standard",
        "contract_version": "1.0",
        "source_generation": "sg1",
        "config_generation": "cg1",
        "extractor_generation": "eg1",
        "canonicalizer_generation": "kg1",
        "snapshot_manifest_id": "man-1",
        "snapshot_vector": (),
        "resolver_identity": "res1",
        "extractor_capability_identity": "cap1",
        "canonicalizer_identity": "canon1",
        "semantic_contract_identity": "sem1",
        "quality_rule_identity": "qual1",
        "outcome": "failed",
        "cancellation": "not-requested",
        "bundle_reference": None,
        "bundle_id": None,
        "family_counts": {},
        "diagnostic_category": "source_unavailable",
        "diagnostic_summary": ("failed to read source",),
        "producer_identity": "producer-1",
        "attestation_class": "untrusted-self-assertion",
    }


class ReceiptValidationBoundariesUnitTests(unittest.TestCase):
    """Test ExtractionReceipt creation and validation edge branches."""

    def test_valid_failed_receipt_and_public_projection(self):
        self.assertTrue(set(DIAGNOSTIC_CATEGORIES).issubset(PUBLIC_DIAGNOSTIC_PROJECTION.keys()))
        self.assertIn("completed", RECEIPT_OUTCOMES)
        self.assertIn("failed", RECEIPT_OUTCOMES)
        kwargs = _base_receipt_kwargs()
        receipt = ExtractionReceipt.create(**kwargs)
        self.assertEqual(receipt.outcome, "failed")
        pub = receipt.to_public_mapping()
        self.assertEqual(pub["error_category"], "source_error")
        self.assertEqual(pub["outcome"], "failed")

    def test_invalid_attempt(self):
        for bad_attempt in (0, -1, False, "1"):
            with self.subTest(bad_attempt=bad_attempt):
                kwargs = _base_receipt_kwargs()
                kwargs["attempt"] = bad_attempt
                with self.assertRaises(ValueError):
                    ExtractionReceipt.create(**kwargs)

    def test_invalid_outcome(self):
        kwargs = _base_receipt_kwargs()
        kwargs["outcome"] = "unrecognized_outcome"
        with self.assertRaises(ValueError) as caught:
            ExtractionReceipt.create(**kwargs)
        self.assertIn("receipt outcome is invalid", str(caught.exception))

    def test_invalid_diagnostic_category(self):
        kwargs = _base_receipt_kwargs()
        kwargs["diagnostic_category"] = "unrecognized_category"
        with self.assertRaises(ValueError) as caught:
            ExtractionReceipt.create(**kwargs)
        self.assertIn("receipt diagnostic category is invalid", str(caught.exception))

    def test_diagnostic_summary_bounds(self):
        kwargs = _base_receipt_kwargs()
        kwargs["diagnostic_summary"] = tuple(f"diag-{i}" for i in range(33))
        with self.assertRaises(ValueError) as caught:
            ExtractionReceipt.create(**kwargs)
        self.assertIn("receipt diagnostics exceed bounds", str(caught.exception))

        kwargs2 = _base_receipt_kwargs()
        kwargs2["diagnostic_summary"] = ("x" * 257,)
        with self.assertRaises(ValueError) as caught:
            ExtractionReceipt.create(**kwargs2)
        self.assertIn("receipt diagnostics exceed bounds", str(caught.exception))

    def test_failed_outcome_missing_diagnostic(self):
        kwargs = _base_receipt_kwargs()
        kwargs["outcome"] = "failed"
        kwargs["diagnostic_category"] = None
        with self.assertRaises(ValueError) as caught:
            ExtractionReceipt.create(**kwargs)
        self.assertIn("terminal receipt diagnostic is missing", str(caught.exception))

    def test_cancelled_outcome_validation(self):
        kwargs = _base_receipt_kwargs()
        kwargs["outcome"] = "cancelled"
        kwargs["diagnostic_category"] = "cancelled"
        kwargs["cancellation"] = "not-requested"
        with self.assertRaises(ValueError) as caught:
            ExtractionReceipt.create(**kwargs)
        self.assertIn("cancelled receipt cancellation state is invalid", str(caught.exception))

        # Valid cancelled
        kwargs["cancellation"] = "requested"
        receipt = ExtractionReceipt.create(**kwargs)
        self.assertEqual(receipt.outcome, "cancelled")

    def test_non_completed_receipt_cannot_accept_bundle(self):
        kwargs = _base_receipt_kwargs()
        kwargs["outcome"] = "failed"
        kwargs["bundle_id"] = "bundle-1"
        with self.assertRaises(ValueError) as caught:
            ExtractionReceipt.create(**kwargs)
        self.assertIn("non-completed receipt cannot accept a bundle", str(caught.exception))

        kwargs2 = _base_receipt_kwargs()
        kwargs2["outcome"] = "failed"
        kwargs2["family_counts"] = {"files": 5}
        with self.assertRaises(ValueError) as caught:
            ExtractionReceipt.create(**kwargs2)
        self.assertIn("non-completed receipt cannot accept a bundle", str(caught.exception))

    def test_from_bytes_round_trip_and_version_checks(self):
        kwargs = _base_receipt_kwargs()
        receipt = ExtractionReceipt.create(**kwargs)
        data = receipt.canonical_bytes()
        restored = ExtractionReceipt.from_bytes(data)
        self.assertEqual(restored.receipt_id, receipt.receipt_id)

        # Unsupported schema version
        bad_version = data.replace(b'"schema_version":1', b'"schema_version":2')
        with self.assertRaises(ValueError) as caught:
            ExtractionReceipt.from_bytes(bad_version)
        self.assertIn("unsupported extraction receipt version", str(caught.exception))

    def test_completed_outcome_inconsistency_branches(self):
        from repomap_kg.artifacts.references import ArtifactLocator, ArtifactReference
        from repomap_kg.storage.staging_family_contracts import PrivacyClassification

        dummy_ref = ArtifactReference(
            "sha256:" + "0" * 64,
            100,
            "application/x-repomap-publication-bundle-v1+jsonl",
            "canonical-jsonl-v1",
            PrivacyClassification.PUBLIC,
            ArtifactLocator("filesystem", "bundle.jsonl"),
        )

        # completed with bundle_reference is None
        kwargs = _base_receipt_kwargs()
        kwargs["outcome"] = "completed"
        kwargs["bundle_reference"] = None
        kwargs["bundle_id"] = "bundle-1"
        kwargs["diagnostic_category"] = None
        kwargs["diagnostic_summary"] = ()
        with self.assertRaises(ValueError) as caught:
            ExtractionReceipt.create(**kwargs)
        self.assertIn("completed receipt is inconsistent", str(caught.exception))

        # completed with bundle_id is None
        kwargs["bundle_reference"] = dummy_ref
        kwargs["bundle_id"] = None
        with self.assertRaises(ValueError) as caught:
            ExtractionReceipt.create(**kwargs)
        self.assertIn("completed receipt is inconsistent", str(caught.exception))

        # completed with diagnostic_category is not None
        kwargs["bundle_id"] = "bundle-1"
        kwargs["diagnostic_category"] = "source_unavailable"
        with self.assertRaises(ValueError) as caught:
            ExtractionReceipt.create(**kwargs)
        self.assertIn("completed receipt is inconsistent", str(caught.exception))

    def test_terminal_receipt_missing_diagnostic_branches(self):
        for term_outcome in ("unsupported_contract", "malformed_input"):
            with self.subTest(term_outcome=term_outcome):
                kwargs = _base_receipt_kwargs()
                kwargs["outcome"] = term_outcome
                kwargs["diagnostic_category"] = None
                with self.assertRaises(ValueError) as caught:
                    ExtractionReceipt.create(**kwargs)
                self.assertIn("terminal receipt diagnostic is missing", str(caught.exception))

    def test_identity_string_validation_branches(self):
        for field in (
            "request_id", "job_id", "graph_id", "worker_capability_identity",
            "contract_version", "source_generation", "producer_identity", "attestation_class",
        ):
            with self.subTest(field=field, case="empty"):
                kwargs = _base_receipt_kwargs()
                kwargs[field] = ""
                with self.assertRaises(ValueError) as caught:
                    ExtractionReceipt.create(**kwargs)
                self.assertIn("receipt identity field is invalid", str(caught.exception))

            with self.subTest(field=field, case="too_long"):
                kwargs = _base_receipt_kwargs()
                kwargs[field] = "x" * 257
                with self.assertRaises(ValueError) as caught:
                    ExtractionReceipt.create(**kwargs)
                self.assertIn("receipt identity field is invalid", str(caught.exception))

            with self.subTest(field=field, case="non_string"):
                kwargs = _base_receipt_kwargs()
                kwargs[field] = 99999
                with self.assertRaises(ValueError) as caught:
                    ExtractionReceipt.create(**kwargs)
                self.assertIn("receipt identity field is invalid", str(caught.exception))

    def test_from_bytes_validation_branches(self):
        kwargs = _base_receipt_kwargs()
        receipt = ExtractionReceipt.create(**kwargs)
        data = receipt.canonical_bytes()

        # bundle_reference present in payload but not a Mapping
        bad_ref = data.replace(b'"bundle_reference":null', b'"bundle_reference":12345')
        with self.assertRaises(ValueError) as caught:
            ExtractionReceipt.from_bytes(bad_ref)
        self.assertIn("extraction receipt is malformed", str(caught.exception))

        # family_counts not dict
        bad_counts = data.replace(b'"family_counts":{}', b'"family_counts":[1,2,3]')
        with self.assertRaises(ValueError) as caught:
            ExtractionReceipt.from_bytes(bad_counts)
        self.assertIn("extraction receipt is malformed", str(caught.exception))

        # diagnostic_summary not list
        bad_diag = data.replace(
            b'"diagnostic_summary":["failed to read source"]',
            b'"diagnostic_summary":"not-a-list"',
        )
        with self.assertRaises(ValueError) as caught:
            ExtractionReceipt.from_bytes(bad_diag)
        self.assertIn("extraction receipt is malformed", str(caught.exception))

        # Non-canonical content (extra key decoded but not preserved by canonical_bytes)
        from repomap_kg.artifacts._canonical import canonical_json, decode_canonical_json
        payload = decode_canonical_json(data)
        payload["extra_field"] = "not_part_of_receipt"
        extra_key_data = canonical_json(payload)
        with self.assertRaises(ValueError) as caught:
            ExtractionReceipt.from_bytes(extra_key_data)
        self.assertIn("extraction receipt is not canonical", str(caught.exception))

    def test_vector_and_reidentify_branches(self):
        from repomap_kg.artifacts.receipt import _int, _str, _vector

        # _vector validations
        with self.assertRaises(ValueError) as caught:
            _vector("not-a-list")
        self.assertIn("snapshot vector is invalid", str(caught.exception))

        with self.assertRaises(ValueError) as caught:
            _vector(["not-a-list-item"])
        self.assertIn("snapshot vector is invalid", str(caught.exception))

        with self.assertRaises(ValueError) as caught:
            _vector([["a", 1]])
        self.assertIn("snapshot vector is invalid", str(caught.exception))

        # _str and _int validations
        with self.assertRaises(ValueError) as caught:
            _str(123)
        self.assertIn("receipt string field is invalid", str(caught.exception))

        with self.assertRaises(ValueError) as caught:
            _int("123")
        self.assertIn("receipt integer field is invalid", str(caught.exception))

        with self.assertRaises(ValueError) as caught:
            _int(True)
        self.assertIn("receipt integer field is invalid", str(caught.exception))

        # reidentify method
        kwargs = _base_receipt_kwargs()
        receipt = ExtractionReceipt.create(**kwargs)
        reidentified = receipt.reidentify()
        self.assertEqual(reidentified.receipt_id, receipt.receipt_id)


if __name__ == "__main__":
    unittest.main()
