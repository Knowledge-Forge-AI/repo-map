from __future__ import annotations

import unittest

from repomap_kg.extractors.documents.markdown import (
    extract_markdown_file_observations,
    markdown_anchor,
    markdown_anchors_for_content,
    parse_frontmatter,
    resolve_markdown_link_target,
)


class MarkdownExtractorUnitTests(unittest.TestCase):
    def test_extracts_document_headings_frontmatter_and_code_fences(self):
        observations = extract_markdown_file_observations(
            "README.md",
            (
                "---\n"
                "title: RepoMap\n"
                "tags:\n"
                "  - graph\n"
                "api_key: secret-value\n"
                "---\n"
                "# RepoMap\n"
                "\n"
                "## Current Status\n"
                "```python\n"
                "print('[not a link](ignored.md)')\n"
                "```\n"
                "## Current Status\n"
            ),
            repository_paths={"README.md"},
            markdown_anchors={"README.md": {"repomap", "current-status", "current-status-1"}},
        )

        self.assertEqual([item.kind for item in observations], [
            "markdown.document",
            "markdown.frontmatter",
            "markdown.heading",
            "markdown.heading",
            "markdown.code_fence",
            "markdown.heading",
        ])
        document = observations[0]
        frontmatter = observations[1]
        first_heading = observations[2]
        fence = observations[4]
        duplicate_heading = observations[5]

        self.assertEqual(document.target, "doc.page:file%3AREADME.md")
        self.assertEqual(document.metadata["doc_role"], "readme")
        self.assertEqual(document.metadata["title"], "RepoMap")
        self.assertTrue(document.metadata["frontmatter_present"])
        self.assertEqual(frontmatter.start_line, 1)
        self.assertEqual(frontmatter.end_line, 6)
        self.assertEqual(frontmatter.metadata["keys"], ["api_key", "tags", "title"])
        self.assertEqual(frontmatter.metadata["values"]["title"], "RepoMap")
        self.assertIn("api_key", frontmatter.metadata["redacted_keys"])
        self.assertEqual(first_heading.target, "doc.section:file%3AREADME.md:repomap")
        self.assertEqual(first_heading.metadata["level"], 1)
        self.assertEqual(fence.metadata["language"], "python")
        self.assertEqual(fence.metadata["section_anchor"], "current-status")
        self.assertTrue(fence.metadata["closed"])
        self.assertEqual(
            duplicate_heading.target,
            "doc.section:file%3AREADME.md:current-status-1",
        )

    def test_extracts_inline_reference_autolink_and_image_links(self):
        observations = extract_markdown_file_observations(
            "docs/guide.md",
            (
                "# Guide\n"
                "See [README](../README.md#current-status), "
                "[site](https://example.com/docs), "
                "![logo](../assets/logo.png), and <mailto:dev@example.com>.\n"
                "Also [ADR][adr8].\n"
                "\n"
                "[adr8]: ../docs/adr/0008-markdown-documentation-graph-model.md\n"
            ),
            repository_paths={
                "README.md",
                "docs/guide.md",
                "docs/adr/0008-markdown-documentation-graph-model.md",
                "assets/logo.png",
            },
            markdown_anchors={
                "README.md": {"current-status"},
                "docs/guide.md": {"guide"},
                "docs/adr/0008-markdown-documentation-graph-model.md": {
                    "decision",
                },
            },
        )

        links = [item for item in observations if item.kind == "markdown.link"]

        self.assertEqual(
            [(item.name, item.target, item.metadata["link_syntax"]) for item in links],
            [
                (
                    "README",
                    "doc.section:file%3AREADME.md:current-status",
                    "inline",
                ),
                (
                    "site",
                    "external.url:https%3A%2F%2Fexample.com%2Fdocs",
                    "inline",
                ),
                ("logo", "file:assets/logo.png", "inline"),
                (
                    "mailto:dev@example.com",
                    "external.url:mailto%3Adev%40example.com",
                    "autolink",
                ),
                (
                    "ADR",
                    "doc.page:file%3Adocs%2Fadr%2F0008-markdown-documentation-graph-model.md",
                    "reference",
                ),
            ],
        )
        self.assertTrue(links[2].metadata["is_image"])
        self.assertEqual(links[0].metadata["source_anchor"], "guide")

    def test_resolves_missing_repo_escaping_dynamic_and_malformed_links(self):
        known = {"README.md", "docs/guide.md"}
        anchors: dict[str, set[str] | frozenset[str]] = {
            "README.md": {"known"},
            "docs/guide.md": {"guide"},
        }

        self.assertEqual(
            resolve_markdown_link_target(
                "docs/guide.md",
                "../missing.md",
                repository_paths=known,
                markdown_anchors=anchors,
            ).target,
            "unknown:doc.page:missing-markdown-link-target",
        )
        self.assertEqual(
            resolve_markdown_link_target(
                "docs/guide.md",
                "../../outside.md",
                repository_paths=known,
                markdown_anchors=anchors,
            ).target,
            "unknown:file:repo-escaping-markdown-link",
        )
        self.assertEqual(
            resolve_markdown_link_target(
                "docs/guide.md",
                "{{ site.url }}/docs",
                repository_paths=known,
                markdown_anchors=anchors,
            ).target,
            "dynamic:external.url:markdown-link-template",
        )
        self.assertEqual(
            resolve_markdown_link_target(
                "docs/guide.md",
                "bad%zz",
                repository_paths=known,
                markdown_anchors=anchors,
            ).target,
            "unknown:external.url:malformed-markdown-link",
        )
        self.assertEqual(
            resolve_markdown_link_target(
                "docs/guide.md",
                "../README.md#missing",
                repository_paths=known,
                markdown_anchors=anchors,
            ).target,
            "unknown:doc.section:missing-anchor",
        )

    def test_resolves_same_file_anchors_empty_targets_and_missing_files(self):
        known = {"README.md", "docs/guide.md", "assets/logo.png"}
        anchors: dict[str, set[str] | frozenset[str]] = {"docs/guide.md": {"guide", "usage"}}

        same_file = resolve_markdown_link_target(
            "docs/guide.md",
            "#usage",
            repository_paths=known,
            markdown_anchors=anchors,
        )
        self.assertEqual(same_file.target, "doc.section:file%3Adocs%2Fguide.md:usage")
        self.assertEqual(same_file.resolved_path, "docs/guide.md")
        self.assertEqual(same_file.resolved_anchor, "usage")

        empty = resolve_markdown_link_target(
            "docs/guide.md",
            "",
            repository_paths=known,
            markdown_anchors=anchors,
        )
        self.assertEqual(empty.target, "unknown:external.url:malformed-markdown-link")
        self.assertEqual(empty.resolution_reason, "empty-target")

        missing_asset = resolve_markdown_link_target(
            "docs/guide.md",
            "../assets/missing.png",
            repository_paths=known,
            markdown_anchors=anchors,
        )
        self.assertEqual(
            missing_asset.target,
            "unknown:file:missing-markdown-link-target",
        )

    def test_extracts_unclosed_fence_parent_anchor_and_reference_variants(self):
        observations = extract_markdown_file_observations(
            "docs/status/md1.md",
            (
                "---\n"
                "title: \"MD1\"\n"
                "published: true\n"
                "draft: false\n"
                "tags:\n"
                "  - docs\n"
                "not yaml\n"
                "secret_token: hidden\n"
                "---\n"
                "# Status\n"
                "## Detail\n"
                "### Nested\n"
                "## Sibling\n"
                "[Same file](#detail) and [Collapsed][].\n"
                "\n"
                "[Collapsed]: ../status/md1.md#sibling \"title\"\n"
                "```sh\n"
                "echo not executed\n"
            ),
            repository_paths={"docs/status/md1.md"},
            markdown_anchors={"docs/status/md1.md": {"status", "detail", "nested", "sibling"}},
        )

        frontmatter = next(item for item in observations if item.kind == "markdown.frontmatter")
        fences = [item for item in observations if item.kind == "markdown.code_fence"]
        links = [item for item in observations if item.kind == "markdown.link"]
        nested = next(
            item
            for item in observations
            if item.kind == "markdown.heading" and item.metadata["anchor"] == "nested"
        )
        sibling = next(
            item
            for item in observations
            if item.kind == "markdown.heading" and item.metadata["anchor"] == "sibling"
        )

        self.assertEqual(frontmatter.metadata["parse_status"], "partial")
        self.assertEqual(frontmatter.metadata["values"]["title"], "MD1")
        self.assertIs(frontmatter.metadata["values"]["published"], True)
        self.assertIs(frontmatter.metadata["values"]["draft"], False)
        self.assertIn("secret_token", frontmatter.metadata["redacted_keys"])
        self.assertEqual(nested.metadata["parent_anchor"], "detail")
        self.assertEqual(sibling.metadata["parent_anchor"], "status")
        self.assertEqual(fences[0].metadata["language"], "sh")
        self.assertFalse(fences[0].metadata["closed"])
        self.assertEqual(
            [(item.name, item.target, item.metadata["link_syntax"]) for item in links],
            [
                ("Same file", "doc.section:file%3Adocs%2Fstatus%2Fmd1.md:detail", "inline"),
                ("Collapsed", "doc.section:file%3Adocs%2Fstatus%2Fmd1.md:sibling", "reference"),
            ],
        )

    def test_extracts_document_roles_adr_and_path_based_skill_metadata(self):
        role_cases = {
            "AGENTS.md": "agents",
            "docs/status/md1.md": "status",
            "docs/skills/example/SKILL.md": "skill",
            "notes/design.md": "markdown",
        }
        for path, role in role_cases.items():
            with self.subTest(path=path):
                observations = extract_markdown_file_observations(
                    path,
                    "# Title\n",
                    repository_paths={path},
                    markdown_anchors={path: {"title"}},
                )
                self.assertEqual(observations[0].metadata["doc_role"], role)

        adr_observations = extract_markdown_file_observations(
            "docs/adr/0009-example-decision.md",
            "# Example Decision\n\n## Status\n\nAccepted\n\n## Date\n\n2026-06-29\n",
            repository_paths={"docs/adr/0009-example-decision.md"},
            markdown_anchors={"docs/adr/0009-example-decision.md": {"example-decision"}},
        )
        adr = next(item for item in adr_observations if item.kind == "markdown.adr_metadata")
        self.assertEqual(adr.target, "doc.adr:0009")
        self.assertEqual(adr.metadata["metadata_source"], "heading")
        self.assertEqual(adr.metadata["status"], "Accepted")
        self.assertEqual(adr.metadata["date"], "2026-06-29")

        fallback_adr = extract_markdown_file_observations(
            "docs/adr/0010-filename-title.md",
            "No heading here.\n",
            repository_paths={"docs/adr/0010-filename-title.md"},
            markdown_anchors={"docs/adr/0010-filename-title.md": set()},
        )
        fallback = next(item for item in fallback_adr if item.kind == "markdown.adr_metadata")
        self.assertEqual(fallback.metadata["title"], "filename title")
        self.assertEqual(fallback.metadata["metadata_source"], "filename")

        skill_observations = extract_markdown_file_observations(
            "docs/skills/path-only/SKILL.md",
            "# Path Only\n",
            repository_paths={"docs/skills/path-only/SKILL.md"},
            markdown_anchors={"docs/skills/path-only/SKILL.md": {"path-only"}},
        )
        skill = next(item for item in skill_observations if item.kind == "markdown.skill_metadata")
        self.assertEqual(skill.target, "doc.skill:path-only")
        self.assertEqual(skill.metadata["metadata_source"], "path")
        self.assertEqual(skill.metadata["parse_status"], "missing")

    def test_parse_frontmatter_handles_missing_closing_delimiter(self):
        frontmatter = parse_frontmatter("---\ntitle: Broken\n")

        self.assertIsNotNone(frontmatter)
        assert frontmatter is not None
        self.assertEqual(frontmatter.parse_status, "malformed")
        self.assertEqual(frontmatter.malformed_reason, "missing-closing-delimiter")

    def test_markdown_anchor_normalization_is_deterministic(self):
        self.assertEqual(markdown_anchor("Current Status"), "current-status")
        self.assertEqual(markdown_anchor("`API` & [Usage](#x)!"), "api-usagex")
        self.assertEqual(markdown_anchor("!!!"), "section")
        self.assertEqual(
            markdown_anchors_for_content("# Usage\n## Usage\n## Usage\n"),
            {"usage", "usage-1", "usage-2"},
        )


if __name__ == "__main__":
    unittest.main()
