import unittest

from repomap_kg.extractors.documents.markdown import (
    extract_markdown_file_observations,
)


class MarkdownExtractorBoundariesUnitTests(unittest.TestCase):
    def test_markdown_frontmatter_malformed_and_redacted_text(self):
        observations = extract_markdown_file_observations(
            "docs/malformed.md",
            """---
[unclosed yaml mapping
# Heading
Content
""",
        )
        fm = next(o for o in observations if o.kind == "markdown.frontmatter")
        self.assertEqual(fm.metadata["parse_status"], "malformed")
        self.assertEqual(fm.metadata["malformed_reason"], "missing-closing-delimiter")

    def test_markdown_skill_metadata_and_adr_boundaries(self):
        skill_obs = extract_markdown_file_observations(
            "skills/my-skill/SKILL.md",
            """---
name: my-skill
description: A useful skill
---
# My Skill
""",
        )
        skill = next(o for o in skill_obs if o.kind == "markdown.skill_metadata")
        self.assertEqual(skill.metadata["description"], "A useful skill")

        not_adr = extract_markdown_file_observations(
            "docs/adr/readme.md",
            "# Architecture Decision Records\n",
        )
        self.assertNotIn("markdown.adr", {o.kind for o in not_adr})

    def test_markdown_links_reference_definitions_and_percent_escapes(self):
        observations = extract_markdown_file_observations(
            "docs/guide.md",
            """# Title
## Empty Section
## Section With Links
Here is a [missing reference][unresolved-ref].
Here is a link with [title](./relative/page.md "Page Title").
Here is a link with spaces in [http url](https://example.com/a b).
Here is a link with malformed percent escape: [bad](file%2.md).
Here is a link with bad hex: [bad hex](file%ZZ.md).

```
code without language
```
""",
        )
        kinds = {o.kind for o in observations}
        self.assertIn("markdown.code_fence", kinds)
        links = [o for o in observations if o.kind == "markdown.link"]
        reasons = {o.metadata.get("resolution_reason") for o in links}
        self.assertIn("malformed-percent-escape", reasons)
        self.assertIn("missing-markdown-link-target", reasons)

    def test_markdown_fence_nesting_and_adr_heading_boundaries(self):
        observations = extract_markdown_file_observations(
            "docs/adr/0001-record.md",
            """---
title: ADR 1

tags:
  - architecture
  - doc
---
# ADR 0001: My Decision
## Empty Section 1
## Empty Section 2
````
```python
code inside 4-tick fence
~~~
still inside
```
````
```
unanchored fence
```
Here is an autolink in link text: [<https://example.com>](https://example.com).
Here is a relative link with dot: [dot link](././file.md).
Here is a link with valid escape: [escaped](file%20name.md).
[ref-link]: https://example.com/target
[ref-link-2]: ./target.md
[ref-link-2]: ./shadowed.md
""",
        )
        kinds = {o.kind for o in observations}
        self.assertIn("markdown.adr_metadata", kinds)
        adr = next(o for o in observations if o.kind == "markdown.adr_metadata")
        self.assertEqual(adr.metadata["title"], "My Decision")

        from repomap_kg.extractors.documents.markdown import (
            _document_observation,
            _code_fence_observation,
            _resolve_repo_relative_path,
            _section_value,
        )
        from repomap_kg.extractors.documents.markdown_structure import parse_frontmatter

        doc_obs = _document_observation("doc.md", title="Title", frontmatter_present=False, content_hash="hash123", generated=True)
        self.assertEqual(doc_obs.metadata["content_hash"], "hash123")
        self.assertTrue(doc_obs.metadata["generated"])

        fence_obs = _code_fence_observation("doc.md", start_line=1, end_line=3, marker="```", info_string="", section_anchor=None, closed=True, ordinal=0)
        self.assertNotIn("section_anchor", fence_obs.metadata)

        self.assertEqual(_resolve_repo_relative_path("docs/page.md", "././target.md"), "docs/target.md")
        self.assertEqual(_resolve_repo_relative_path("docs/page.md", "../root.md"), "root.md")
        self.assertIsNone(_section_value("# Head 1\n# Head 2\n", "Head 1"))

        # frontmatter list item following scalar key
        fm = parse_frontmatter("---\nkey: scalar\n- item\n---\n")
        self.assertIsNotNone(fm)


if __name__ == "__main__":
    unittest.main()
