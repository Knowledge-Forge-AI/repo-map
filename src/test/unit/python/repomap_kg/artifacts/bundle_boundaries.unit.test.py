"""Unit tests for publication bundle validation, framing bounds, and family summaries."""

from __future__ import annotations

import unittest

from repomap_kg.artifacts.bundle import (
    PUBLICATION_FAMILIES,
    FamilySummary,
    PublicationBundle,
)
from repomap_kg.storage.staging_family_contracts import PrivacyClassification


def _base_bundle_kwargs():
    families = {family: () for family in PUBLICATION_FAMILIES}
    return {
        "request_id": "req-1",
        "job_id": "job-1",
        "attempt": 1,
        "graph_id": "graph-1",
        "candidate_id": "cand-1",
        "snapshot_manifest_id": "man-1",
        "snapshot_vector": (),
        "source_generation": "sg1",
        "config_generation": "cg1",
        "extractor_generation": "eg1",
        "canonicalizer_generation": "kg1",
        "extractor_capability_identity": "cap1",
        "resolver_identity": "res1",
        "canonicalizer_identity": "canon1",
        "semantic_contract_identity": "sem1",
        "quality_rule_identity": "qual1",
        "privacy": PrivacyClassification.PUBLIC,
        "families": families,
        "row_stage_contract": "stage-unassigned-v1",
        "terminal_complete": True,
        "schema_version": 1,
    }


class BundleBoundariesUnitTests(unittest.TestCase):
    """Test PublicationBundle validation branches and framing parsing."""

    def test_valid_bundle_create_and_header_mapping(self):
        kwargs = _base_bundle_kwargs()
        bundle = PublicationBundle.create(**kwargs)
        header = bundle.header_mapping()
        self.assertEqual(header["row_stage_contract"], "stage-unassigned-v1")
        self.assertEqual(header["attempt"], 1)

        # Legacy absent contract omits row_stage_contract key
        kwargs2 = _base_bundle_kwargs()
        kwargs2["row_stage_contract"] = "legacy-absent-v1"
        bundle2 = PublicationBundle.create(**kwargs2)
        header2 = bundle2.header_mapping()
        self.assertNotIn("row_stage_contract", header2)

    def test_family_summary_mapping(self):
        summary = FamilySummary(
            family="files",
            record_count=10,
            byte_length=1024,
            content_digest="sha256:abcd",
        )
        mapping = summary.mapping()
        self.assertEqual(mapping["record_count"], 10)
        self.assertEqual(mapping["family"], "files")

    def test_invalid_privacy_classification(self):
        kwargs = _base_bundle_kwargs()
        kwargs["privacy"] = "public"  # Not enum instance
        with self.assertRaises(ValueError) as caught:
            PublicationBundle.create(**kwargs)
        self.assertIn("bundle privacy is invalid", str(caught.exception))

    def test_invalid_row_stage_contract(self):
        kwargs = _base_bundle_kwargs()
        kwargs["row_stage_contract"] = "unsupported-contract"
        with self.assertRaises(ValueError) as caught:
            PublicationBundle.create(**kwargs)
        self.assertIn("bundle row stage contract is invalid", str(caught.exception))

    def test_invalid_terminal_completeness(self):
        kwargs = _base_bundle_kwargs()
        kwargs["terminal_complete"] = "true"  # Not bool
        with self.assertRaises(ValueError) as caught:
            PublicationBundle.create(**kwargs)
        self.assertIn("bundle terminal completeness is invalid", str(caught.exception))

    def test_missing_family_inventory(self):
        kwargs = _base_bundle_kwargs()
        partial_families = dict(kwargs["families"])
        del partial_families["files"]
        kwargs["families"] = partial_families
        with self.assertRaises(ValueError) as caught:
            PublicationBundle.create(**kwargs)
        self.assertIn("publication bundle family inventory is invalid", str(caught.exception))

    def test_from_bytes_framing_validation(self):
        # Missing trailing newline
        with self.assertRaises(ValueError) as caught:
            PublicationBundle.from_bytes(b'{"frame":"header"}')
        self.assertIn("publication bundle framing is invalid", str(caught.exception))

        # Less than 2 lines
        with self.assertRaises(ValueError) as caught:
            PublicationBundle.from_bytes(b'{"frame":"header"}\n')
        self.assertIn("publication bundle framing is invalid", str(caught.exception))

        # Unsupported schema version in header
        kwargs = _base_bundle_kwargs()
        bundle = PublicationBundle.create(**kwargs)
        data = bundle.canonical_bytes()
        bad_version = data.replace(b'"schema_version":1', b'"schema_version":2')
        with self.assertRaises(ValueError) as caught:
            PublicationBundle.from_bytes(bad_version)
        self.assertIn("unsupported publication bundle version", str(caught.exception))

    def test_metadata_validation_branches(self):
        # Attempt validation: boolean, negative, zero, non-int
        for bad_attempt in (True, False, 0, -1, "1", 2.5):
            with self.subTest(bad_attempt=bad_attempt):
                kwargs = _base_bundle_kwargs()
                kwargs["attempt"] = bad_attempt
                with self.assertRaises(ValueError) as caught:
                    PublicationBundle.create(**kwargs)
                self.assertIn("bundle attempt is invalid", str(caught.exception))

        # String metadata validation: empty, too long (>256), non-string
        for field in ("request_id", "job_id", "graph_id", "candidate_id", "source_generation"):
            with self.subTest(field=field, case="empty"):
                kwargs = _base_bundle_kwargs()
                kwargs[field] = ""
                with self.assertRaises(ValueError) as caught:
                    PublicationBundle.create(**kwargs)
                self.assertIn(f"bundle {field} is invalid", str(caught.exception))

            with self.subTest(field=field, case="too_long"):
                kwargs = _base_bundle_kwargs()
                kwargs[field] = "x" * 257
                with self.assertRaises(ValueError) as caught:
                    PublicationBundle.create(**kwargs)
                self.assertIn(f"bundle {field} is invalid", str(caught.exception))

            with self.subTest(field=field, case="non_string"):
                kwargs = _base_bundle_kwargs()
                kwargs[field] = 12345
                with self.assertRaises(ValueError) as caught:
                    PublicationBundle.create(**kwargs)
                self.assertIn(f"bundle {field} is invalid", str(caught.exception))

    def test_vector_validation_branches(self):
        from repomap_kg.artifacts.bundle import _vector

        with self.assertRaises(ValueError) as caught:
            _vector("not-a-list")
        self.assertIn("snapshot vector is invalid", str(caught.exception))

        # Item not a list or length != 3
        with self.assertRaises(ValueError) as caught:
            _vector(["not-a-list-item"])
        self.assertIn("snapshot vector is invalid", str(caught.exception))

        with self.assertRaises(ValueError) as caught:
            _vector([["a", 1]])
        self.assertIn("snapshot vector is invalid", str(caught.exception))

        # Item elements wrong types
        with self.assertRaises(ValueError) as caught:
            _vector([[123, 1, "h"]])
        self.assertIn("snapshot vector is invalid", str(caught.exception))

        with self.assertRaises(ValueError) as caught:
            _vector([["a", True, "h"]])
        self.assertIn("snapshot vector is invalid", str(caught.exception))

        with self.assertRaises(ValueError) as caught:
            _vector([["a", "not-int", "h"]])
        self.assertIn("snapshot vector is invalid", str(caught.exception))

        with self.assertRaises(ValueError) as caught:
            _vector([["a", 1, 456]])
        self.assertIn("snapshot vector is invalid", str(caught.exception))

    def test_from_bytes_record_and_family_validation(self):
        kwargs = _base_bundle_kwargs()
        bundle = PublicationBundle.create(**kwargs)
        data = bundle.canonical_bytes()

        # Record frame invalid: missing required keys
        lines = data.splitlines(keepends=True)
        bad_record_line = b'{"family":"files","frame":"record"}\n'
        tampered_data = b"".join([lines[0], bad_record_line, lines[-1]])
        with self.assertRaises(ValueError) as caught:
            PublicationBundle.from_bytes(tampered_data)
        self.assertIn("publication bundle record frame is invalid", str(caught.exception))

        # Family not in PUBLICATION_FAMILIES
        bad_family_line = b'{"family":"nonexistent","frame":"record","record":{}}\n'
        tampered_family = b"".join([lines[0], bad_family_line, lines[-1]])
        with self.assertRaises(ValueError) as caught:
            PublicationBundle.from_bytes(tampered_family)
        self.assertIn("publication bundle family is invalid", str(caught.exception))

        # Record is not a dict
        bad_record_val = b'{"family":"files","frame":"record","record":"not-a-dict"}\n'
        tampered_val = b"".join([lines[0], bad_record_val, lines[-1]])
        with self.assertRaises(ValueError) as caught:
            PublicationBundle.from_bytes(tampered_val)
        self.assertIn("publication bundle family is invalid", str(caught.exception))

        # Family ordering inverted (out of canonical order)
        # In PUBLICATION_FAMILIES, files is index 0, raw_observations is index 1
        rec1 = b'{"family":"raw_observations","frame":"record","record":{}}\n'
        rec2 = b'{"family":"files","frame":"record","record":{}}\n'
        tampered_order = b"".join([lines[0], rec1, rec2, lines[-1]])
        with self.assertRaises(ValueError) as caught:
            PublicationBundle.from_bytes(tampered_order)
        self.assertIn("publication bundle family ordering is invalid", str(caught.exception))

        # Header frame mismatch
        bad_header = b"".join([b'{"frame":"wrong"}\n', lines[-1]])
        with self.assertRaises(ValueError) as caught:
            PublicationBundle.from_bytes(bad_header)
        self.assertIn("publication bundle framing is invalid", str(caught.exception))

        # Trailer frame mismatch
        bad_trailer = b"".join([lines[0], b'{"frame":"wrong"}\n'])
        with self.assertRaises(ValueError) as caught:
            PublicationBundle.from_bytes(bad_trailer)
        self.assertIn("publication bundle framing is invalid", str(caught.exception))

    def test_mutate_for_testing_branches(self):
        kwargs = _base_bundle_kwargs()
        kwargs["families"]["files"] = ({"test": "row"},)
        bundle = PublicationBundle.create(**kwargs)
        data = bundle.canonical_bytes()

        truncated = PublicationBundle.malformed_for_test(data, "truncated")
        self.assertEqual(truncated, data[:-1])

        partial = PublicationBundle.malformed_for_test(data, "partial")
        self.assertTrue(len(partial) < len(data))

        unknown = PublicationBundle.malformed_for_test(data, "unknown-family")
        self.assertIn(b'"family":"unknown"', unknown)

        dup = PublicationBundle.malformed_for_test(data, "duplicate")
        self.assertTrue(len(dup) > len(data))

        with self.assertRaises(ValueError) as caught:
            PublicationBundle.malformed_for_test(data, "unknown-mutation-code")
        self.assertIn("unknown test mutation", str(caught.exception))

    def test_from_bytes_header_field_types(self):
        kwargs = _base_bundle_kwargs()
        bundle = PublicationBundle.create(**kwargs)
        data = bundle.canonical_bytes()

        # Non-string header field (e.g. request_id as int)
        bad_str = data.replace(b'"request_id":"req-1"', b'"request_id":12345')
        with self.assertRaises(ValueError) as caught:
            PublicationBundle.from_bytes(bad_str)
        self.assertIn("publication bundle field is invalid", str(caught.exception))

        # Non-integer header field (e.g. attempt as string or bool)
        bad_int = data.replace(b'"attempt":1', b'"attempt":"one"')
        with self.assertRaises(ValueError) as caught:
            PublicationBundle.from_bytes(bad_int)
        self.assertIn("publication bundle field is invalid", str(caught.exception))

        bad_bool = data.replace(b'"attempt":1', b'"attempt":true')
        with self.assertRaises(ValueError) as caught:
            PublicationBundle.from_bytes(bad_bool)
        self.assertIn("publication bundle field is invalid", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
