import unittest
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from repomap_kg.canonicalization.main import canonicalize_observations
    from repomap_kg.observations.raw import RawObservation
else:
    from repomap_kg.canonicalization import canonicalize_observations
    from repomap_kg.observations import RawObservation


class CanonicalizationWarcDocumentUnitTests(unittest.TestCase):
    def test_warc_document_record_and_reference_canonicalize_without_new_edges(self):
        record_key = (
            "warc.record:"
            "warc.document%3Afile%253Aarchives%252Fexample.warc:"
            "urn%3Auuid%3Ahtml-1"
        )
        observations = [
            RawObservation(
                kind="warc.document",
                source_id="archives/example.warc#warc-document",
                path="archives/example.warc",
                target="warc.document:file%3Aarchives%2Fexample.warc",
                confidence="extracted",
                extractor="source-ingestion",
                extractor_version="0.1.0",
                metadata={
                    "format": "warc",
                    "warc_version": "WARC/1.1",
                    "record_count": 1,
                    "routed_payload_count": 1,
                },
            ),
            RawObservation(
                kind="warc.record",
                source_id="archives/example.warc#warc-record:1",
                path="archives/example.warc",
                target=record_key,
                confidence="extracted",
                extractor="source-ingestion",
                extractor_version="0.1.0",
                metadata={
                    "document_key": "warc.document:file%3Aarchives%2Fexample.warc",
                    "record_type": "response",
                    "record_ordinal": 1,
                    "identity_source": "warc_record_id",
                    "identity_strength": "strong",
                    "duplicate_identity": False,
                    "target_uri_summary": "https://example.invalid/page.html",
                },
            ),
            RawObservation(
                kind="warc.reference",
                source_id="archives/example.warc#warc-record:1:target-uri",
                path="archives/example.warc",
                target="external.url:https%3A%2F%2Fexample.invalid%2Fpage.html",
                confidence="extracted",
                extractor="source-ingestion",
                extractor_version="0.1.0",
                metadata={
                    "source_key": record_key,
                    "reference_kind": "target-uri",
                    "not_fetched": True,
                },
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["nodes"], 4)
        self.assertEqual(payload["summary"]["edges"], 3)
        self.assertEqual(
            {(node["kind"], node["canonical_key"]) for node in payload["nodes"]},
            {
                ("file", "file:archives/example.warc"),
                ("warc.document", "warc.document:file%3Aarchives%2Fexample.warc"),
                ("warc.record", record_key),
                ("external.url", "external.url:https%3A%2F%2Fexample.invalid%2Fpage.html"),
            },
        )
        self.assertEqual(
            {
                (edge["source_key"], edge["kind"], edge["target_key"])
                for edge in payload["edges"]
            },
            {
                (
                    "file:archives/example.warc",
                    "defines",
                    "warc.document:file%3Aarchives%2Fexample.warc",
                ),
                (
                    "warc.document:file%3Aarchives%2Fexample.warc",
                    "defines",
                    record_key,
                ),
                (
                    record_key,
                    "references",
                    "external.url:https%3A%2F%2Fexample.invalid%2Fpage.html",
                ),
            },
        )

    def test_warc_document_definition_fallback_and_diagnostics(self):
        valid_doc = RawObservation(
            kind="warc.document",
            source_id="archives/default.warc#doc",
            path="archives/default.warc",
            target=None,
            confidence="extracted",
            extractor="source-ingestion",
            extractor_version="0.1.0",
            metadata={"format": "warc"},
        )
        result_valid = canonicalize_observations((valid_doc,))
        self.assertTrue(result_valid.ok)
        self.assertEqual(
            result_valid.to_dict()["nodes"][1]["canonical_key"],
            "warc.document:file%3Aarchives%2Fdefault.warc",
        )

        invalid_obs = [
            RawObservation(
                kind="warc.record",
                source_id="archives/bad.warc#rec1",
                path="archives/bad.warc",
                target=None,
                confidence="extracted",
                extractor="source-ingestion",
                extractor_version="0.1.0",
                metadata={"document_key": "warc.document:file%3Aarchives%2Fbad.warc"},
            ),
            RawObservation(
                kind="warc.record",
                source_id="archives/bad.warc#rec2",
                path="archives/bad.warc",
                target="file:archives/bad.warc",
                confidence="extracted",
                extractor="source-ingestion",
                extractor_version="0.1.0",
                metadata={"document_key": "warc.document:file%3Aarchives%2Fbad.warc"},
            ),
            RawObservation(
                kind="warc.record",
                source_id="archives/bad.warc#rec3",
                path="archives/bad.warc",
                target="warc.record:warc.document%3Afile%253Aarchives%252Fbad.warc:1",
                confidence="extracted",
                extractor="source-ingestion",
                extractor_version="0.1.0",
                metadata={},
            ),
            RawObservation(
                kind="warc.record",
                source_id="archives/bad.warc#rec4",
                path="archives/bad.warc",
                target="warc.record:warc.document%3Afile%253Aarchives%252Fbad.warc:2",
                confidence="extracted",
                extractor="source-ingestion",
                extractor_version="0.1.0",
                metadata={"document_key": "file:archives/bad.warc"},
            ),
        ]
        result_invalid = canonicalize_observations(invalid_obs)
        self.assertFalse(result_invalid.ok)
        self.assertEqual(result_invalid.to_dict()["summary"]["errors"], 4)

    def test_warc_reference_diagnostics_and_fallbacks(self):
        record_key = (
            "warc.record:"
            "warc.document%3Afile%253Aarchives%252Fexample.warc:"
            "urn%3Auuid%3Ahtml-1"
        )
        missing_target = RawObservation(
            kind="warc.reference",
            source_id="archives/example.warc#ref:missing",
            path="archives/example.warc",
            target=None,
            confidence="extracted",
            extractor="source-ingestion",
            extractor_version="0.1.0",
            metadata={"source_key": record_key},
        )
        result_missing = canonicalize_observations((missing_target,))
        self.assertTrue(result_missing.ok)
        self.assertIn(
            "unknown:warc.reference:missing-target",
            {edge["target_key"] for edge in result_missing.to_dict()["edges"]},
        )

        invalid_refs = [
            RawObservation(
                kind="warc.reference",
                source_id="archives/example.warc#ref:no-source",
                path="archives/example.warc",
                target="external.url:https%3A%2F%2Fexample.invalid",
                confidence="extracted",
                extractor="source-ingestion",
                extractor_version="0.1.0",
                metadata={},
            ),
            RawObservation(
                kind="warc.reference",
                source_id="archives/example.warc#ref:bad-source",
                path="archives/example.warc",
                target="external.url:https%3A%2F%2Fexample.invalid",
                confidence="extracted",
                extractor="source-ingestion",
                extractor_version="0.1.0",
                metadata={"source_key": "file:archives/example.warc"},
            ),
        ]
        result_invalid = canonicalize_observations(invalid_refs)
        self.assertFalse(result_invalid.ok)
        self.assertEqual(result_invalid.to_dict()["summary"]["errors"], 2)


if __name__ == "__main__":
    unittest.main()
