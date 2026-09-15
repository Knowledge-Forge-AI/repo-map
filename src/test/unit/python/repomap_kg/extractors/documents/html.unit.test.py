import json
import unittest

from repomap_kg.extractors.documents.html import (
    MAX_HTML_STRUCTURAL_BYTES,
    extract_html_file_observations,
)
from repomap_kg.observations.raw import RawObservation


HTML_FIXTURE = """\
<!doctype html>
<html lang="en">
  <head>
    <title>Static fixture</title>
    <link rel="stylesheet" href="assets/site.css">
    <script src="assets/app.js"></script>
    <style>.secret-token { color: red; }</style>
  </head>
  <body>
    <main id="intro" class="hero">
      <h1 id="welcome">Welcome Home</h1>
      <h2>Plain Heading</h2>
      <a href="#welcome">Jump</a>
      <a href="https://example.com/docs">Docs</a>
      <a href="mailto:dev@example.com">Email</a>
      <a href="javascript:alert('nope')">Bad</a>
      <img src="images/logo.png" alt="Logo">
      <video poster="media/poster.png"></video>
      <form id="login" method="post" action="submit/login">
        <input name="username" value="alice">
        <input name="password" type="password" value="html1-secret">
      </form>
    </main>
    <section><p>first</p><p>second</p></section>
    <div id="dup"></div><div id="dup"></div>
  </body>
</html>
"""


class HtmlExtractorUnitTests(unittest.TestCase):
    def test_extracts_document_elements_headings_links_assets_and_forms(self):
        observations = extract_html_file_observations("index.html", HTML_FIXTURE)
        payload = json.dumps(
            [observation.to_dict() for observation in observations],
            sort_keys=True,
        )
        by_kind: dict[str, list[RawObservation]] = {}
        for observation in observations:
            by_kind.setdefault(observation.kind, []).append(observation)

        self.assertNotIn("html1-secret", payload)
        self.assertNotIn("alert('nope')", payload)
        self.assertEqual(by_kind["html.document"][0].metadata["title"], "Static fixture")
        self.assertEqual(by_kind["html.document"][0].metadata["language"], "en")
        self.assertEqual(by_kind["html.document"][0].metadata["root_element"], "html")
        self.assertIn(
            "/html/body/main/a[2]",
            {item.metadata["pointer"] for item in by_kind["html.element"]},
        )
        self.assertIn(
            "/html/body/section/p[2]",
            {item.metadata["pointer"] for item in by_kind["html.element"]},
        )
        self.assertIn(
            "html.anchor:file%3Aindex.html:welcome",
            {item.target for item in by_kind["html.heading"]},
        )
        plain_heading = next(
            item
            for item in by_kind["html.heading"]
            if item.metadata["source_element_pointer"] == "/html/body/main/h2"
        )
        self.assertEqual(
            plain_heading.target,
            "html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fmain%2Fh2",
        )

        references = {
            (item.kind, item.metadata["attribute"], item.target)
            for item in by_kind["html.link"] + by_kind["html.asset"] + by_kind["html.form"]
        }
        self.assertIn(
            (
                "html.link",
                "href",
                "html.anchor:file%3Aindex.html:welcome",
            ),
            references,
        )
        self.assertIn(
            (
                "html.link",
                "href",
                "external.url:https%3A%2F%2Fexample.com%2Fdocs",
            ),
            references,
        )
        self.assertIn(
            (
                "html.link",
                "href",
                "external.url:mailto%3Adev%40example.com",
            ),
            references,
        )
        self.assertIn(
            (
                "html.link",
                "href",
                "dynamic:url:javascript-url",
            ),
            references,
        )
        self.assertIn(("html.asset", "src", "file:images/logo.png"), references)
        self.assertIn(("html.asset", "href", "file:assets/site.css"), references)
        self.assertIn(("html.asset", "src", "file:assets/app.js"), references)
        self.assertIn(("html.asset", "poster", "file:media/poster.png"), references)
        self.assertIn(("html.form", "action", "file:submit/login"), references)

        script = next(
            item
            for item in by_kind["html.element"]
            if item.metadata["pointer"] == "/html/head/script"
        )
        style = next(
            item
            for item in by_kind["html.element"]
            if item.metadata["pointer"] == "/html/head/style"
        )
        self.assertEqual(script.metadata["content_policy"], "not-executed")
        self.assertEqual(style.metadata["content_policy"], "not-parsed")

    def test_duplicate_ids_do_not_create_ambiguous_anchor_identity(self):
        observations = extract_html_file_observations(
            "duplicate.html",
            '<html><body><h1 id="dup">First</h1><h2 id="dup">Second</h2></body></html>',
        )

        headings = [item for item in observations if item.kind == "html.heading"]

        self.assertEqual(
            [item.target for item in headings],
            [
                "html.element:file%3Aduplicate.html:%2Fhtml%2Fbody%2Fh1",
                "html.element:file%3Aduplicate.html:%2Fhtml%2Fbody%2Fh2",
            ],
        )
        self.assertTrue(all(item.metadata["id_is_unique"] is False for item in headings))

    def test_malformed_html_emits_recoverable_parse_warning(self):
        observations = extract_html_file_observations(
            "broken.html",
            "<html><body><section><p>unterminated",
        )

        self.assertIn("html.document", [item.kind for item in observations])
        errors = [item for item in observations if item.kind == "html.parse_error"]

        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].metadata["error_kind"], "recoverable-unclosed-elements")
        self.assertEqual(errors[0].confidence, "unknown")

    def test_oversized_html_preserves_document_identity_without_element_tree(self):
        observations = extract_html_file_observations(
            "generated-report.html",
            "<html><body>" + ("x" * MAX_HTML_STRUCTURAL_BYTES) + "</body></html>",
        )

        by_kind: dict[str, list[RawObservation]] = {}
        for observation in observations:
            by_kind.setdefault(observation.kind, []).append(observation)

        self.assertEqual(set(by_kind), {"html.document", "html.parse_error"})
        document = by_kind["html.document"][0]
        self.assertEqual(document.metadata["extraction_policy"], "size-limited")
        self.assertEqual(document.metadata["element_count"], 0)
        self.assertEqual(
            by_kind["html.parse_error"][0].metadata["error_kind"],
            "document-size-limit",
        )

    def test_reference_placeholders_for_ambiguous_static_targets(self):
        observations = extract_html_file_observations(
            "pages/index.html",
            """<html><body>
<a href="../../outside.html">outside</a>
<a href="/Library/file.txt">absolute</a>
<a href="${ASSET_DIR}/logo.png">dynamic</a>
<a href="ftp://example.com/file">unsupported</a>
<form></form>
</body></html>
""",
        )

        references = {
            (item.kind, item.metadata["resolution_reason"], item.target)
            for item in observations
            if item.kind in ("html.link", "html.form")
        }

        self.assertIn(
            (
                "html.link",
                "repo-escaping-file-reference",
                "unknown:file:repo-escaping-config-reference",
            ),
            references,
        )
        self.assertIn(
            (
                "html.link",
                "absolute-file-reference",
                "external:file:absolute-config-reference",
            ),
            references,
        )
        self.assertIn(
            (
                "html.link",
                "dynamic-file-reference",
                "dynamic:file:html-reference-expanded-from-variable",
            ),
            references,
        )
        self.assertIn(
            (
                "html.link",
                "unsupported-url-scheme",
                "dynamic:url:unsupported-url-scheme",
            ),
            references,
        )
        self.assertIn(
            (
                "html.form",
                "missing-reference-target",
                "unknown:html.reference:missing-target",
            ),
            references,
        )

    def test_secret_title_and_unmatched_end_tag_are_not_overmodeled(self):
        observations = extract_html_file_observations(
            "secret-title.html",
            "<html><head><title>token value</title></head><body></span></body></html>",
        )

        document = next(item for item in observations if item.kind == "html.document")
        errors = [item for item in observations if item.kind == "html.parse_error"]

        self.assertNotIn("title", document.metadata)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].metadata["error_kind"], "recoverable-unmatched-end-tag")

    def test_empty_document_and_unsafe_identity_inputs_remain_bounded(self):
        empty_observations = extract_html_file_observations("empty.html", "")
        observations = extract_html_file_observations(
            "index.html",
            """<html><body>
<h1 id="bad id">unsafe\x00heading</h1>
<a href="#bad id">bad fragment</a>
<a password="public-fixture" href="./guide.html">redacted source</a>
<a href=".">empty relative target</a>
<div class="stable bad! stable-two"></div>
</body></html>""",
        )

        empty_document = next(
            item for item in empty_observations if item.kind == "html.document"
        )
        heading = next(item for item in observations if item.kind == "html.heading")
        elements = [item for item in observations if item.kind == "html.element"]
        references = [item for item in observations if item.kind == "html.link"]

        self.assertNotIn("root_element", empty_document.metadata)
        self.assertEqual(heading.target, heading.metadata["source_element_key"])
        self.assertNotIn("id", heading.metadata)
        self.assertNotIn("text_summary", heading.metadata)
        self.assertEqual(
            references[0].target,
            "unknown:html.anchor:unresolved-fragment",
        )
        self.assertTrue(references[1].metadata["redacted"])
        self.assertNotIn("raw_value_summary", references[1].metadata)
        self.assertEqual(references[1].target, "file:guide.html")
        self.assertEqual(
            references[2].target,
            "unknown:file:repo-escaping-config-reference",
        )
        classed = next(
            item for item in elements if item.metadata.get("tag") == "div"
        )
        self.assertEqual(classed.metadata["classes"], ["stable", "stable-two"])


if __name__ == "__main__":
    unittest.main()
