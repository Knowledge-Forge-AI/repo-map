import unittest

from repomap_kg.canonicalization.main import (
    canonicalize_observations,
)
from repomap_kg.observations.raw import RawObservation



class CanonicalizationMarkdownFamilyUnitTests(unittest.TestCase):
    def test_markdown_document_heading_adr_and_skill_define_doc_nodes(self):
        observations = [
            RawObservation(
                kind="markdown.document",
                source_id="README.md#markdown-document",
                path="README.md",
                target="doc.page:file%3AREADME.md",
                confidence="extracted",
                extractor="repo-markdown",
                extractor_version="0.1.0",
                metadata={
                    "doc_path": "README.md",
                    "doc_role": "readme",
                    "title": "RepoMap",
                    "frontmatter_present": False,
                },
            ),
            RawObservation(
                kind="markdown.heading",
                source_id="README.md#heading:current-status",
                path="README.md",
                start_line=3,
                end_line=3,
                name="Current Status",
                target="doc.section:file%3AREADME.md:current-status",
                confidence="extracted",
                extractor="repo-markdown",
                extractor_version="0.1.0",
                metadata={
                    "level": 2,
                    "text": "Current Status",
                    "anchor": "current-status",
                    "page_key": "doc.page:file%3AREADME.md",
                },
            ),
            RawObservation(
                kind="markdown.adr_metadata",
                source_id="docs/adr/0008-markdown-documentation-graph-model.md#adr-metadata",
                path="docs/adr/0008-markdown-documentation-graph-model.md",
                name="0008",
                target="doc.adr:0008",
                confidence="extracted",
                extractor="repo-markdown",
                extractor_version="0.1.0",
                metadata={
                    "adr_number": "0008",
                    "title": "Markdown Documentation Graph Model",
                    "status": "Accepted",
                    "date": "2026-06-29",
                },
            ),
            RawObservation(
                kind="markdown.skill_metadata",
                source_id="docs/skills/example/SKILL.md#skill-metadata",
                path="docs/skills/example/SKILL.md",
                name="example",
                target="doc.skill:example",
                confidence="heuristic",
                extractor="repo-markdown",
                extractor_version="0.1.0",
                metadata={
                    "skill_name": "example",
                    "description": "Example skill.",
                    "parse_status": "parsed",
                },
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(
            sorted(node["canonical_key"] for node in payload["nodes"]),
            [
                "doc.adr:0008",
                "doc.page:file%3AREADME.md",
                "doc.section:file%3AREADME.md:current-status",
                "doc.skill:example",
                "file:README.md",
                "file:docs/adr/0008-markdown-documentation-graph-model.md",
                "file:docs/skills/example/SKILL.md",
            ],
        )
        self.assertEqual(
            sorted((edge["source_key"], edge["kind"], edge["target_key"]) for edge in payload["edges"]),
            [
                (
                    "file:README.md",
                    "defines",
                    "doc.page:file%3AREADME.md",
                ),
                (
                    "file:README.md",
                    "defines",
                    "doc.section:file%3AREADME.md:current-status",
                ),
                (
                    "file:docs/adr/0008-markdown-documentation-graph-model.md",
                    "defines",
                    "doc.adr:0008",
                ),
                (
                    "file:docs/skills/example/SKILL.md",
                    "defines",
                    "doc.skill:example",
                ),
            ],
        )

    def test_markdown_link_creates_links_to_from_section(self):
        observation = RawObservation(
            kind="markdown.link",
            source_id="README.md#link:4:0",
            path="README.md",
            start_line=4,
            end_line=4,
            name="ADR 0008",
            target="doc.page:file%3Adocs%2Fadr%2F0008-markdown-documentation-graph-model.md",
            confidence="extracted",
            extractor="repo-markdown",
            extractor_version="0.1.0",
            metadata={
                "link_text": "ADR 0008",
                "raw_target": "docs/adr/0008-markdown-documentation-graph-model.md",
                "link_syntax": "inline",
                "source_anchor": "current-status",
                "source_key": "doc.section:file%3AREADME.md:current-status",
                "resolved_target_kind": "doc.page",
                "resolved_path": "docs/adr/0008-markdown-documentation-graph-model.md",
            },
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["edges"], 1)
        self.assertEqual(payload["edges"][0]["kind"], "links_to")
        self.assertEqual(
            payload["edges"][0]["source_key"],
            "doc.section:file%3AREADME.md:current-status",
        )
        self.assertEqual(
            payload["edges"][0]["target_key"],
            "doc.page:file%3Adocs%2Fadr%2F0008-markdown-documentation-graph-model.md",
        )
        self.assertEqual(payload["edges"][0]["metadata"]["link_texts"], ["ADR 0008"])
        self.assertEqual(payload["edges"][0]["metadata"]["syntaxes"], ["inline"])

    def test_markdown_link_defaults_to_page_source_and_uses_placeholders(self):
        observations = [
            RawObservation(
                kind="markdown.link",
                source_id="README.md#link:4:0",
                path="README.md",
                start_line=4,
                end_line=4,
                name="Missing",
                confidence="extracted",
                extractor="repo-markdown",
                extractor_version="0.1.0",
                metadata={
                    "link_text": "Missing",
                    "raw_target": "",
                    "link_syntax": "inline",
                    "resolved_target_kind": "unknown",
                },
            ),
            RawObservation(
                kind="markdown.link",
                source_id="README.md#link:5:0",
                path="README.md",
                start_line=5,
                end_line=5,
                name="Bad",
                target="bogus:target",
                confidence="extracted",
                extractor="repo-markdown",
                extractor_version="0.1.0",
                metadata={
                    "link_text": "Bad",
                    "raw_target": "bogus:target",
                    "link_syntax": "inline",
                    "resolved_target_kind": "unknown",
                    "resolution_reason": "malformed-percent-escape",
                },
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["warnings"], 2)
        self.assertEqual(
            sorted(edge["source_key"] for edge in payload["edges"]),
            ["doc.page:file%3AREADME.md", "doc.page:file%3AREADME.md"],
        )
        self.assertEqual(
            sorted(edge["target_key"] for edge in payload["edges"]),
            [
                "unknown:external.url:malformed-markdown-link",
                "unknown:external.url:missing-markdown-link-target",
            ],
        )
        self.assertEqual(
            [diagnostic["field"] for diagnostic in payload["diagnostics"]],
            ["target", "target"],
        )

    def test_markdown_frontmatter_and_code_fence_attach_page_evidence(self):
        observations = [
            RawObservation(
                kind="markdown.frontmatter",
                source_id="README.md#frontmatter",
                path="README.md",
                start_line=1,
                end_line=4,
                confidence="heuristic",
                extractor="repo-markdown",
                extractor_version="0.1.0",
                metadata={
                    "keys": ["title"],
                    "values": {"title": "RepoMap"},
                    "parse_status": "parsed",
                },
            ),
            RawObservation(
                kind="markdown.code_fence",
                source_id="README.md#code-fence:8:0",
                path="README.md",
                start_line=8,
                end_line=10,
                name="python",
                confidence="extracted",
                extractor="repo-markdown",
                extractor_version="0.1.0",
                metadata={
                    "fence": "```",
                    "fence_length": 3,
                    "info_string": "python",
                    "language": "python",
                    "closed": True,
                },
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["nodes"], 1)
        self.assertEqual(payload["summary"]["edges"], 0)
        self.assertEqual(payload["nodes"][0]["canonical_key"], "doc.page:file%3AREADME.md")
        self.assertEqual(payload["summary"]["node_evidence_links"], 2)


    def test_markdown_optional_semantics_are_projected_without_invention(self):
        observations = [
            RawObservation(
                kind="markdown.frontmatter",
                source_id="guide.md#frontmatter",
                path="guide.md",
                confidence="extracted",
                extractor="repo-markdown",
                extractor_version="0.1.0",
                metadata={"keys": ("title", "status"), "parse_status": "parsed"},
            ),
            RawObservation(
                kind="markdown.frontmatter",
                source_id="guide.md#frontmatter-invalid-keys",
                path="guide.md",
                confidence="heuristic",
                extractor="repo-markdown",
                extractor_version="0.1.0",
                metadata={"keys": "not-a-sequence-contract"},
            ),
            RawObservation(
                kind="markdown.code_fence",
                source_id="guide.md#code-fence",
                path="guide.md",
                confidence="extracted",
                extractor="repo-markdown",
                extractor_version="0.1.0",
                metadata={"language": "python", "closed": False},
            ),
            RawObservation(
                kind="markdown.code_fence",
                source_id="guide.md#code-fence-unspecified",
                path="guide.md",
                confidence="heuristic",
                extractor="repo-markdown",
                extractor_version="0.1.0",
                metadata={},
            ),
            RawObservation(
                kind="markdown.link",
                source_id="guide.md#section-link",
                path="guide.md",
                target="file:other.md",
                confidence="extracted",
                extractor="repo-markdown",
                extractor_version="0.1.0",
                metadata={"source_anchor": "overview", "is_image": False},
            ),
        ]

        frontmatter_payload = canonicalize_observations(observations[:2]).to_dict()
        code_payload = canonicalize_observations(observations[2:4]).to_dict()
        link_payload = canonicalize_observations(observations[4:]).to_dict()
        page = next(
            node
            for node in frontmatter_payload["nodes"]
            if node["canonical_key"] == "doc.page:file%3Aguide.md"
        )
        code_page = next(
            node
            for node in code_payload["nodes"]
            if node["canonical_key"] == "doc.page:file%3Aguide.md"
        )
        section_edge = next(
            edge
            for edge in link_payload["edges"]
            if edge["source_key"] == "doc.section:file%3Aguide.md:overview"
        )

        self.assertTrue(frontmatter_payload["ok"])
        self.assertTrue(code_payload["ok"])
        self.assertTrue(link_payload["ok"])
        self.assertEqual(page["metadata"]["frontmatter_keys"], ["title", "status"])
        self.assertEqual(
            page["metadata"]["frontmatter_parse_statuses"],
            ["parsed"],
        )
        self.assertEqual(code_page["metadata"]["code_fence_languages"], ["python"])
        self.assertEqual(code_page["metadata"]["code_fence_closed_observed"], False)
        self.assertEqual(section_edge["target_key"], "file:other.md")
        self.assertEqual(section_edge["metadata"]["image_link_observed"], False)


if __name__ == "__main__":
    unittest.main()
