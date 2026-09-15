import unittest

from repomap_kg.canonicalization.main import (
    canonicalize_observations,
)
from repomap_kg.observations.raw import RawObservation


class CanonicalizationMarkdownFamilyBoundariesUnitTests(unittest.TestCase):
    def test_markdown_link_rejects_non_document_source_key(self):
        observation = RawObservation(
            kind="markdown.link",
            source_id="README.md#link:6:0",
            path="README.md",
            start_line=6,
            end_line=6,
            name="README",
            target="doc.page:file%3AREADME.md",
            confidence="extracted",
            extractor="repo-markdown",
            extractor_version="0.1.0",
            metadata={
                "link_text": "README",
                "raw_target": "README.md",
                "link_syntax": "inline",
                "source_key": "file:README.md",
            },
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["summary"]["errors"], 1)
        self.assertEqual(payload["diagnostics"][0]["field"], "target")
        self.assertIn("source_key", payload["diagnostics"][0]["message"])


    def test_markdown_page_evidence_rejects_invalid_page_key(self):
        observation = RawObservation(
            kind="markdown.frontmatter",
            source_id="README.md#frontmatter",
            path="README.md",
            start_line=1,
            end_line=3,
            confidence="heuristic",
            extractor="repo-markdown",
            extractor_version="0.1.0",
            metadata={
                "page_key": "bad%zz",
                "keys": ["title"],
                "parse_status": "parsed",
            },
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["summary"]["errors"], 1)
        self.assertEqual(payload["diagnostics"][0]["field"], "metadata.page_key")

    def test_markdown_page_evidence_rejects_non_doc_page_key(self):
        observation = RawObservation(
            kind="markdown.code_fence",
            source_id="README.md#code-fence:4:0",
            path="README.md",
            start_line=4,
            end_line=6,
            confidence="extracted",
            extractor="repo-markdown",
            extractor_version="0.1.0",
            metadata={
                "page_key": "file:README.md",
                "language": "python",
                "closed": True,
            },
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["summary"]["errors"], 1)
        self.assertEqual(payload["diagnostics"][0]["field"], "metadata.page_key")
        self.assertIn("doc.page", payload["diagnostics"][0]["message"])

    def test_markdown_definition_missing_identity_metadata_is_error(self):
        observations = [
            RawObservation(
                kind="markdown.heading",
                source_id="README.md#heading:missing-anchor",
                path="README.md",
                name="No Anchor",
                target="doc.section:file%3AREADME.md:no-anchor",
                confidence="extracted",
                extractor="repo-markdown",
                extractor_version="0.1.0",
                metadata={"text": "No Anchor"},
            ),
            RawObservation(
                kind="markdown.adr_metadata",
                source_id="docs/adr/bad.md#adr-metadata",
                path="docs/adr/bad.md",
                confidence="extracted",
                extractor="repo-markdown",
                extractor_version="0.1.0",
                metadata={},
            ),
            RawObservation(
                kind="markdown.skill_metadata",
                source_id="docs/skills/bad/SKILL.md#skill-metadata",
                path="docs/skills/bad/SKILL.md",
                confidence="heuristic",
                extractor="repo-markdown",
                extractor_version="0.1.0",
                metadata={},
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["summary"]["errors"], 3)
        self.assertEqual(payload["summary"]["nodes"], 0)
        self.assertEqual(
            [diagnostic["field"] for diagnostic in payload["diagnostics"]],
            ["target", "target", "target"],
        )



if __name__ == "__main__":
    unittest.main()
