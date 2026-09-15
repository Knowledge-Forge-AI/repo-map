from __future__ import annotations

import os
import unittest
from pathlib import PurePosixPath
from typing import cast

from repomap_kg.graph.keys import (
    GRAPH_KEY_VERSION,
    GraphKeyError,
    config_path_key,
    css_rule_key,
    css_selector_key,
    doc_page_key,
    dynamic_key,
    external_key,
    feed_channel_key,
    file_key,
    js_component_key,
    js_file_key,
    js_test_case_key,
    parse_key,
    tool_key,
    unknown_key,
    validate_key,
)


class GraphKeysUnitTests(unittest.TestCase):
    def test_file_key_normalizes_repo_relative_paths(self):
        self.assertEqual(file_key("scripts/../bin/tool"), "file:bin/tool")
        self.assertEqual(file_key(PurePosixPath("./docs/guide.md")), "file:docs/guide.md")
        self.assertEqual(file_key("."), "file:.")

    def test_file_key_encodes_each_path_component(self):
        key = file_key("docs/My Tool:guide#1.md")

        self.assertEqual(key, "file:docs/My%20Tool%3Aguide%231.md")

    def test_file_key_rejects_absolute_and_repo_escaping_paths(self):
        with self.assertRaisesRegex(GraphKeyError, "absolute"):
            file_key("/etc/hosts")

        with self.assertRaisesRegex(GraphKeyError, "escape"):
            file_key("../outside")

        with self.assertRaisesRegex(GraphKeyError, "path"):
            file_key(cast(str, 17))

    def test_placeholder_builders_encode_domain_and_reason(self):
        self.assertEqual(
            dynamic_key("file", "shell source expanded"),
            "dynamic:file:shell%20source%20expanded",
        )
        self.assertEqual(
            external_key("python.module", "requests"),
            "external:python.module:requests",
        )
        self.assertEqual(
            unknown_key("env", "missing variable"),
            "unknown:env:missing%20variable",
        )

    def test_parse_key_decodes_file_and_segment_keys(self):
        parsed_file = parse_key("file:docs/My%20Tool%3Aguide%231.md")
        parsed_method = parse_key("python.method:repomap_kg.storage:Record:to_dict")
        parsed_doc_section = parse_key(
            "doc.section:file%3AREADME.md:current-status"
        )
        parsed_config_path = parse_key(
            "config.path:file%3Asettings.json:%2Fa~01b%2Fc~11d"
        )
        parsed_html_element = parse_key(
            "html.element:file%3Asite%2Findex.html:%2Fhtml%2Fbody%2Fmain"
        )
        parsed_css_selector = parse_key(
            "css.selector:file%3Atools%2Freport.css:%2Frule%3A1%2Fselector%3A2"
        )
        parsed_xml_attribute = parse_key(
            "xml.attribute:file%3Abeans.xml:%2Fbeans%2Fbean:class"
        )
        parsed_warc_record = parse_key(
            "warc.record:warc.document%3Afile%253Aarchives%252Fexample.warc:record-1"
        )
        parsed_ruby_route = parse_key("ruby.route:file%3Aapp.rb:%2Froutes%2Fget")
        parsed_email_part = parse_key(
            (
                "email.part:"
                "email.message%3Afile%253Amail%252Fsingle-message.eml%3Amessage%253Aabc123:"
                "%2Fparts%2F1"
            )
        )

        self.assertEqual(parsed_file.graph_key_version, GRAPH_KEY_VERSION)
        self.assertEqual(parsed_file.namespace, "file")
        self.assertEqual(parsed_file.segments, ("docs", "My Tool:guide#1.md"))
        self.assertEqual(parsed_file.path, "docs/My Tool:guide#1.md")
        self.assertEqual(parsed_method.namespace, "python.method")
        self.assertEqual(
            parsed_method.segments,
            ("repomap_kg.storage", "Record", "to_dict"),
        )
        self.assertIsNone(parsed_method.path)
        self.assertEqual(parsed_doc_section.namespace, "doc.section")
        self.assertEqual(parsed_doc_section.segments, ("file:README.md", "current-status"))
        self.assertEqual(parsed_config_path.namespace, "config.path")
        self.assertEqual(
            parsed_config_path.segments,
            ("file:settings.json", "/a~01b/c~11d"),
        )
        self.assertEqual(parsed_html_element.namespace, "html.element")
        self.assertEqual(
            parsed_html_element.segments,
            ("file:site/index.html", "/html/body/main"),
        )
        self.assertEqual(parsed_css_selector.namespace, "css.selector")
        self.assertEqual(
            parsed_css_selector.segments,
            ("file:tools/report.css", "/rule:1/selector:2"),
        )
        self.assertEqual(parsed_xml_attribute.namespace, "xml.attribute")
        self.assertEqual(
            parsed_xml_attribute.segments,
            ("file:beans.xml", "/beans/bean", "class"),
        )
        self.assertEqual(parsed_warc_record.namespace, "warc.record")
        self.assertEqual(
            parsed_warc_record.segments,
            ("warc.document:file%3Aarchives%2Fexample.warc", "record-1"),
        )
        self.assertEqual(parsed_ruby_route.namespace, "ruby.route")
        self.assertEqual(parsed_ruby_route.segments, ("file:app.rb", "/routes/get"))
        self.assertEqual(parsed_email_part.namespace, "email.part")
        self.assertEqual(
            parsed_email_part.segments,
            (
                "email.message:file%3Amail%2Fsingle-message.eml:message%3Aabc123",
                "/parts/1",
            ),
        )

    def test_parse_key_rejects_bad_grammar_and_malformed_escapes(self):
        cases = (
            ("tool:nix%2", "percent"),
            ("tool:nix%2fbuild", "uppercase"),
            ("tool:nix#build", "reserved"),
            ("python.module:repomap_kg.cli:extra", "segments"),
            ("file:../outside", "escape"),
            ("file:docs//guide.md", "empty"),
            ("not-a-key", "separator"),
            ("unknown.namespace:value", "namespace"),
            ("config.path:file%3Asettings.json:", "segment"),
            ("css.rule:file%3Astyle.css:", "segment"),
            ("xml.attribute:file%3Abeans.xml:%2Fbeans", "segments"),
            ("warc.record:warc.document%3Afile%253Aarchives%252Fexample.warc", "segments"),
            ("email.part:email.message%3Afile%253Amail%252Fsingle-message.eml", "segments"),
        )

        for key, message in cases:
            with self.subTest(key=key):
                with self.assertRaisesRegex(GraphKeyError, message):
                    parse_key(key)

    def test_validate_key_returns_diagnostics_without_raising(self):
        valid = validate_key("tool:nix")
        invalid = validate_key("file:../outside")
        wrong_type = validate_key(os.PathLike)

        self.assertTrue(valid.valid)
        self.assertIsNone(valid.error)
        self.assertFalse(invalid.valid)
        assert invalid.error is not None
        self.assertIn("escape", invalid.error)
        self.assertFalse(wrong_type.valid)
        assert wrong_type.error is not None
        self.assertIn("string", wrong_type.error)

    def test_config_path_key_requires_non_empty_pointer(self):
        with self.assertRaisesRegex(GraphKeyError, "pointer"):
            config_path_key("settings.json", "")

    def test_css_rule_and_selector_keys_require_normalized_pointers(self):
        with self.assertRaisesRegex(GraphKeyError, "pointer"):
            css_rule_key("style.css", "")

        with self.assertRaisesRegex(GraphKeyError, "pointer"):
            css_selector_key("style.css", "rule:1/selector:1")

    def test_builders_accept_canonical_file_parents_and_generic_pathlikes(self):
        class FixturePath(os.PathLike[str]):
            def __fspath__(self) -> str:
                return "docs/guide.md"

        self.assertEqual(doc_page_key("file:README.md"), "doc.page:file%3AREADME.md")
        self.assertEqual(file_key(FixturePath()), "file:docs/guide.md")

    def test_parent_key_builders_reject_wrong_namespaces(self):
        with self.assertRaisesRegex(GraphKeyError, "feed.document parent"):
            feed_channel_key(tool_key("feed"), "channel")

        with self.assertRaisesRegex(GraphKeyError, "js.file or js.test_suite"):
            js_test_case_key(tool_key("suite"), "/tests/example")

    def test_javascript_builders_validate_public_pointer_contracts(self):
        owner = js_file_key("src/example.js")

        self.assertEqual(
            js_test_case_key(owner, "/tests/example"),
            "js.test_case:js.file%3Afile%253Asrc%252Fexample.js:%2Ftests%2Fexample",
        )
        self.assertEqual(
            js_component_key("src/example.jsx", "FixtureComponent"),
            "js.component:file%3Asrc%2Fexample.jsx:FixtureComponent",
        )
        with self.assertRaisesRegex(GraphKeyError, "JavaScript pointer"):
            js_component_key("src/example.jsx", " ")

    def test_key_parser_rejects_empty_and_noncanonical_segments(self):
        cases = (
            ("", "required"),
            ("file:", "path"),
            ("file:docs/./guide.md", "normalized"),
            ("tool:", "segment"),
            ("tool:%GG", "percent"),
            ("tool:%FF", "UTF-8"),
        )

        for key, message in cases:
            with self.subTest(key=key):
                with self.assertRaisesRegex(GraphKeyError, message):
                    parse_key(key)

        self.assertEqual(parse_key("file:.").path, ".")

    def test_file_and_segment_builders_reject_empty_values(self):
        with self.assertRaisesRegex(GraphKeyError, "file path"):
            file_key("")

        with self.assertRaisesRegex(GraphKeyError, "segment"):
            tool_key("")


if __name__ == "__main__":
    unittest.main()
