import unittest


from repomap_kg.canonicalization.main import canonicalize_observations
from repomap_kg.canonicalization._shell_powershell_metadata import (
    _powershell_command_name,
    _powershell_container_key,
    _powershell_file_node_metadata,
)
from repomap_kg.canonicalization.document_css_family import (
    _css_reference_source_key,
    _css_selector_source_key,
)
from repomap_kg.canonicalization.language_javascript_family import (
    _js_definition_source_key,
    _js_definition_target_key,
)
from repomap_kg.graph.keys import (
    GraphKeyError,
    external_url_key,
    warc_document_key,
    warc_record_key,
)
from repomap_kg.extractors.documents.markdown import (
    extract_markdown_file_observations,
    parse_frontmatter,
    resolve_markdown_link_target,
)
from repomap_kg.observations.raw import RawObservation


class CanonicalMarkdownWarcIntegrationTests(unittest.TestCase):
    def test_markdown_extractor_ambiguity_contracts(self):
        frontmatter = parse_frontmatter(
            "---\n"
            "title: \"Docs\"\n"
            "published: true\n"
            "draft: false\n"
            "tags:\n"
            "  - graph\n"
            "not yaml\n"
            "api_key: hidden\n"
            "---\n"
        )
        self.assertIsNotNone(frontmatter)
        assert frontmatter is not None
        self.assertEqual(frontmatter.parse_status, "partial")
        self.assertIs(frontmatter.values["published"], True)
        self.assertIs(frontmatter.values["draft"], False)
        self.assertIn("api_key", frontmatter.redacted_keys)

        observations = extract_markdown_file_observations(
            "docs/guide.md",
            (
                "---\n"
                "title: Docs\n"
                "---\n"
                "# Guide\n"
                "## Usage\n"
                "### Details\n"
                "## Usage\n"
                "See [same](#usage), [missing](missing.md), "
                "[template]({{ site.url }}/docs), [bad](bad%zz), "
                "[asset](../assets/logo.png), and <https://EXAMPLE.com/docs a>.\n"
                "[ref][] [missing-ref][missing]\n"
                "\n"
                "[ref]: #usage-1 \"title\"\n"
                "```sh\n"
                "echo not executed\n"
            ),
            repository_paths={"docs/guide.md", "assets/logo.png"},
            markdown_anchors={"docs/guide.md": {"guide", "usage", "details", "usage-1"}},
        )

        links = [item for item in observations if item.kind == "markdown.link"]
        fences = [item for item in observations if item.kind == "markdown.code_fence"]
        headings = [item for item in observations if item.kind == "markdown.heading"]

        self.assertEqual(
            [heading.metadata["anchor"] for heading in headings],
            ["guide", "usage", "details", "usage-1"],
        )
        self.assertEqual(headings[2].metadata["parent_anchor"], "usage")
        self.assertEqual(headings[3].metadata["parent_anchor"], "guide")
        self.assertFalse(fences[0].metadata["closed"])
        self.assertEqual(
            {item.target for item in links},
            {
                "doc.section:file%3Adocs%2Fguide.md:usage",
                "unknown:doc.page:missing-markdown-link-target",
                "dynamic:external.url:markdown-link-template",
                "unknown:external.url:malformed-markdown-link",
                "file:assets/logo.png",
                "doc.section:file%3Adocs%2Fguide.md:usage-1",
            },
        )

        repo_escape = resolve_markdown_link_target(
            "docs/guide.md",
            "../../outside.md",
            repository_paths={"docs/guide.md"},
            markdown_anchors={"docs/guide.md": {"guide"}},
        )
        self.assertEqual(repo_escape.target, "unknown:file:repo-escaping-markdown-link")
        malformed = parse_frontmatter("---\ntitle: Broken\n")
        self.assertIsNotNone(malformed)
        assert malformed is not None
        self.assertEqual(malformed.malformed_reason, "missing-closing-delimiter")

    def test_markdown_canonicalization_error_contracts(self):
        observations = [
            RawObservation(
                kind="markdown.link",
                source_id="README.md#link:1:0",
                path="README.md",
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
                source_id="README.md#link:2:0",
                path="README.md",
                name="Bad",
                target="bogus:target",
                confidence="extracted",
                extractor="repo-markdown",
                extractor_version="0.1.0",
                metadata={
                    "source_anchor": "current-status",
                    "link_text": "Bad",
                    "raw_target": "bogus:target",
                    "link_syntax": "inline",
                    "resolution_reason": "malformed-percent-escape",
                },
            ),
            RawObservation(
                kind="markdown.heading",
                source_id="README.md#heading:missing",
                path="README.md",
                name="Missing Anchor",
                confidence="extracted",
                extractor="repo-markdown",
                extractor_version="0.1.0",
                metadata={"text": "Missing Anchor"},
            ),
            RawObservation(
                kind="markdown.frontmatter",
                source_id="README.md#frontmatter",
                path="README.md",
                confidence="heuristic",
                extractor="repo-markdown",
                extractor_version="0.1.0",
                metadata={"page_key": "bad%zz", "parse_status": "parsed"},
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["summary"]["warnings"], 2)
        self.assertEqual(payload["summary"]["errors"], 2)
        self.assertIn(
            "unknown:external.url:missing-markdown-link-target",
            {edge["target_key"] for edge in payload["edges"]},
        )
        self.assertIn(
            "unknown:external.url:malformed-markdown-link",
            {edge["target_key"] for edge in payload["edges"]},
        )
        self.assertEqual(
            [diagnostic["field"] for diagnostic in payload["diagnostics"]],
            ["target", "target", "target", "metadata.page_key"],
        )

    def test_warc_observations_create_archive_nodes_and_reference_edges(self):
        document_key = warc_document_key("archives/example.warc")
        record_key = warc_record_key(document_key, "record:<urn:uuid:html-1>")
        target_key = external_url_key("https://example.invalid/page.html")
        observations = (
            RawObservation(
                kind="warc.document",
                source_id="archives/example.warc#warc-document",
                path="archives/example.warc",
                target=document_key,
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
                    "document_key": document_key,
                    "record_type": "response",
                    "record_ordinal": 1,
                    "identity_source": "warc_record_id",
                    "identity_strength": "strong",
                    "duplicate_identity": False,
                    "target_uri_summary": "https://example.invalid/page.html",
                    "content_type": "text/html",
                    "payload_byte_length": 42,
                    "extractor_route": "html",
                },
            ),
            RawObservation(
                kind="warc.reference",
                source_id="archives/example.warc#warc-reference:1",
                path="archives/example.warc",
                target=target_key,
                confidence="extracted",
                extractor="source-ingestion",
                extractor_version="0.1.0",
                metadata={
                    "source_key": record_key,
                    "reference_kind": "warc-target-uri",
                    "not_fetched": True,
                    "record_type": "response",
                    "record_ordinal": 1,
                    "target_uri_summary": "https://example.invalid/page.html",
                },
            ),
            RawObservation(
                kind="warc.header",
                source_id="archives/example.warc#warc-header:1",
                path="archives/example.warc",
                confidence="extracted",
                extractor="source-ingestion",
                extractor_version="0.1.0",
                metadata={"safe_headers": {"content-type": "text/html"}},
            ),
            RawObservation(
                kind="warc.payload",
                source_id="archives/example.warc#warc-payload:1",
                path=".repomap/source-artifacts/example/warc-payloads/record-0001/payload.html",
                confidence="extracted",
                extractor="source-ingestion",
                extractor_version="0.1.0",
                metadata={"warc_payload_path": "payload.html"},
            ),
        )

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["edges"], 3)
        self.assertIn(
            ("file", "file:archives/example.warc"),
            {(node["kind"], node["canonical_key"]) for node in payload["nodes"]},
        )
        self.assertEqual(
            {
                (edge["source_key"], edge["kind"], edge["target_key"])
                for edge in payload["edges"]
            },
            {
                ("file:archives/example.warc", "defines", document_key),
                (document_key, "defines", record_key),
                (record_key, "references", target_key),
            },
        )

    def test_canonicalization_powershell_css_and_javascript_branches(self) -> None:
        self.assertIn("powershell.module", _powershell_container_key("Module.psm1"))
        self.assertIn("powershell.manifest", _powershell_container_key("Manifest.psd1"))
        self.assertIn("powershell.script", _powershell_container_key("Script.ps1"))

        obs_name = RawObservation(
            kind="powershell.command", source_id="s:1", path="s.ps1",
            confidence="extracted", extractor="pwsh", extractor_version="1.0",
            name="Get-Item", metadata={},
        )
        self.assertEqual(_powershell_command_name(obs_name), "Get-Item")

        obs_target = RawObservation(
            kind="powershell.command", source_id="s:2", path="s.ps1",
            confidence="extracted", extractor="pwsh", extractor_version="1.0",
            name="", target="tool:pwsh.cmd", metadata={},
        )
        self.assertEqual(_powershell_command_name(obs_target), "pwsh.cmd")

        meta_file = _powershell_file_node_metadata(RawObservation(
            kind="powershell.file", source_id="s:3", path="s.ps1",
            confidence="extracted", extractor="pwsh", extractor_version="1.0",
            name="s.ps1", metadata={"file_type": "script"},
        ))
        self.assertEqual(meta_file.get("file_type"), "script")

        obs_css_bad = RawObservation(
            kind="css.selector", source_id="c:1", path="style.css",
            confidence="extracted", extractor="css", extractor_version="1.0",
            name="sel", metadata={"source_rule_key": "file:style.css"},
        )
        with self.assertRaises(GraphKeyError):
            _css_selector_source_key(obs_css_bad)

        obs_css_ptr = RawObservation(
            kind="css.selector", source_id="c:2", path="style.css",
            confidence="extracted", extractor="css", extractor_version="1.0",
            name="sel", metadata={"rule_pointer": "/rules/0"},
        )
        self.assertIn("css.rule", _css_selector_source_key(obs_css_ptr))

        obs_css_ref_bad = RawObservation(
            kind="css.reference", source_id="c:3", path="style.css",
            confidence="extracted", extractor="css", extractor_version="1.0",
            name="ref", metadata={"source_key": "file:style.css"},
        )
        with self.assertRaises(GraphKeyError):
            _css_reference_source_key(obs_css_ref_bad)

        obs_method_cls = RawObservation(
            kind="js.method", source_id="j:1", path="app.js",
            confidence="extracted", extractor="js", extractor_version="1.0",
            name="render", metadata={"class_name": "App"},
        )
        self.assertIn("js.class", _js_definition_source_key(obs_method_cls))

        obs_test_suite = RawObservation(
            kind="js.test_case", source_id="j:2", path="test.js",
            confidence="extracted", extractor="js", extractor_version="1.0",
            name="test1", metadata={"test_suite_key": "js.test_suite:file%3Atest.js:suite1"},
        )
        self.assertIn("js.test_suite", _js_definition_source_key(obs_test_suite))

        obs_test_no_suite = RawObservation(
            kind="js.test_case", source_id="j:3", path="test.js",
            confidence="extracted", extractor="js", extractor_version="1.0",
            name="test2", metadata={},
        )
        self.assertIn("js.file", _js_definition_source_key(obs_test_no_suite))

        obs_js_target = RawObservation(
            kind="js.function", source_id="j:4", path="fn.js",
            confidence="extracted", extractor="js", extractor_version="1.0",
            name="", target="file:fn.js", metadata={},
        )
        self.assertEqual(_js_definition_target_key(obs_js_target), "file:fn.js")

        obs_js_noname = RawObservation(
            kind="js.function", source_id="j:5", path="fn.js",
            confidence="extracted", extractor="js", extractor_version="1.0",
            name="", metadata={},
        )
        with self.assertRaises(GraphKeyError):
            _js_definition_target_key(obs_js_noname)
