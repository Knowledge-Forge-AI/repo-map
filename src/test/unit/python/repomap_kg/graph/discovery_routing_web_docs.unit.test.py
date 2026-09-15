from __future__ import annotations

import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path

from repomap_kg.graph.discovery import (
    discover_observations,
    extract_css_file_observations_from_file,
    extract_feed_file_observations_from_file,
)

FIXTURE_ROOT = Path(__file__).parents[4] / "fixtures" / "discovery"

ODF_NS = (
    "xmlns:office=\"urn:oasis:names:tc:opendocument:xmlns:office:1.0\" "
    "xmlns:text=\"urn:oasis:names:tc:opendocument:xmlns:text:1.0\" "
    "xmlns:table=\"urn:oasis:names:tc:opendocument:xmlns:table:1.0\""
)


def odf_package(content_xml: str) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr("content.xml", content_xml.encode("utf-8"))
    return buffer.getvalue()


def odt_content() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {ODF_NS}>
  <office:body><office:text><text:h text:outline-level="1">Overview</text:h></office:text></office:body>
</office:document-content>
"""


def ods_content() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {ODF_NS}>
  <office:body>
    <office:spreadsheet>
      <table:table table:name="Budget">
        <table:table-row><table:table-cell><text:p>amount</text:p></table:table-cell></table:table-row>
        <table:table-row><table:table-cell><text:p>12</text:p></table:table-cell></table:table-row>
      </table:table>
    </office:spreadsheet>
  </office:body>
</office:document-content>
"""


class DiscoveryRoutingWebDocsUnitTests(unittest.TestCase):
    def test_discover_observations_keeps_plist_config_and_extracts_generic_xml(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write(
                root / "chrome-policy.plist",
                """<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0">
  <dict>
    <key>PolicyPath</key>
    <string>managed/policy.json</string>
  </dict>
</plist>
""",
            )
            self.write(
                root / "dangerous.plist",
                """<?xml version="1.0"?>
<!DOCTYPE plist [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<plist><dict><key>Bad</key><string>&xxe;</string></dict></plist>
""",
            )
            self.write(
                root / "generic.xml",
                """<?xml version="1.0"?>
<beans xmlns="http://www.springframework.org/schema/beans">
  <bean id="service" class="com.example.Service"/>
</beans>
""",
            )
            self.write(root / "managed" / "policy.json", "{}\n")

            observations = discover_observations(root)

        payload = "\n".join(item.to_json_line() for item in observations)
        kinds = [observation.kind for observation in observations]
        plist_file = next(
            item
            for item in observations
            if item.kind == "file" and item.path == "chrome-policy.plist"
        )
        generic_file = next(
            item
            for item in observations
            if item.kind == "file" and item.path == "generic.xml"
        )

        self.assertEqual(plist_file.metadata["language"], "plist")
        self.assertEqual(plist_file.metadata["role"], "config")
        self.assertEqual(generic_file.metadata["language"], "xml")
        self.assertIn("config.document", kinds)
        self.assertIn("config.path", kinds)
        self.assertIn("config.reference", kinds)
        self.assertIn("config.parse_error", kinds)
        self.assertIn("xml.document", kinds)
        self.assertIn("xml.element", kinds)
        self.assertIn("xml.attribute", kinds)
        self.assertNotIn("file:///etc/passwd", payload)

    def test_discover_observations_includes_static_html_facts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write(
                root / "site" / "index.html",
                """<!doctype html>
<html lang="en">
  <head><title>Fixture</title><link rel="stylesheet" href="assets/site.css"></head>
  <body>
    <h1 id="welcome">Welcome</h1>
    <a href="#welcome">Jump</a>
    <a href="https://example.com/docs">Docs</a>
    <script src="assets/app.js">alert("nope")</script>
    <form action="submit/login"><input name="password" value="html-secret"></form>
  </body>
</html>
""",
            )

            observations = discover_observations(root)

        payload = "\n".join(item.to_json_line() for item in observations)
        kinds = [observation.kind for observation in observations]
        html_file = next(
            item
            for item in observations
            if item.kind == "file" and item.path == "site/index.html"
        )

        self.assertEqual(html_file.metadata["language"], "html")
        self.assertIn("html.document", kinds)
        self.assertIn("html.element", kinds)
        self.assertIn("html.heading", kinds)
        self.assertIn("html.link", kinds)
        self.assertIn("html.asset", kinds)
        self.assertIn("html.form", kinds)
        self.assertNotIn("html-secret", payload)
        self.assertNotIn('alert("nope")', payload)

    def test_discover_observations_includes_static_css_facts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write(
                root / "tools" / "test" / "report" / "static" / "report.css",
                """
@import url("./reset.css");

:root {
  --surface: #111827;
  --api-token: "fixture-secret-token";
}

.report-header,
.status-badge[data-status="pass"]:hover::before,
#summary {
  background-image: url("../../assets/panel.svg");
  mask-image: url(data:image/svg+xml;base64,PHNlY3JldD4=);
}

@media (max-width: 720px) {
  .tree-grid { grid-template-columns: minmax(0, 1fr); }
}

@supports (overflow-wrap: anywhere) {
  .path-cell { overflow-wrap: anywhere; }
}

@font-face {
  font-family: "Report Mono";
  src: url("/Library/Fonts/report.woff2");
}

.broken {
  color: red;
""",
            )
            self.write(root / "tools" / "test" / "report" / "static" / "reset.css", "")

            observations = discover_observations(root)

        payload = "\n".join(item.to_json_line() for item in observations)
        kinds = [observation.kind for observation in observations]
        css_file = next(
            item
            for item in observations
            if item.kind == "file"
            and item.path == "tools/test/report/static/report.css"
        )

        self.assertEqual(css_file.metadata["language"], "css")
        self.assertIn("css.document", kinds)
        self.assertIn("css.rule", kinds)
        self.assertIn("css.selector", kinds)
        self.assertIn("css.declaration", kinds)
        self.assertIn("css.custom_property", kinds)
        self.assertIn("css.reference", kinds)
        self.assertIn("css.parse_error", kinds)
        self.assertNotIn("fixture-secret-token", payload)
        self.assertNotIn("PHNlY3JldD4=", payload)

    def test_css_fixture_discovery_emits_report_stylesheet_facts(self):
        observations = discover_observations(FIXTURE_ROOT / "css_static_basic")

        payload = "\n".join(item.to_json_line() for item in observations)
        kinds = [observation.kind for observation in observations]
        selectors = [
            observation
            for observation in observations
            if observation.kind == "css.selector"
        ]
        references = [
            observation
            for observation in observations
            if observation.kind == "css.reference"
        ]

        self.assertIn("css.document", kinds)
        self.assertIn("css.rule", kinds)
        self.assertIn("css.selector", kinds)
        self.assertIn("css.declaration", kinds)
        self.assertIn("css.custom_property", kinds)
        self.assertIn("css.reference", kinds)
        self.assertIn("css.parse_error", kinds)
        self.assertTrue(
            any(
                "status-badge" in observation.metadata["classes"]
                for observation in selectors
            )
        )
        self.assertTrue(
            any(
                observation.target == "file:tools/test/assets/panel.svg"
                for observation in references
            )
        )
        self.assertTrue(
            any(
                observation.target == "unknown:file:repo-escaping-css-reference"
                for observation in references
            )
        )
        self.assertNotIn("fixture-secret-token", payload)
        self.assertNotIn("PHNlY3JldD4=", payload)

    def test_feed_fixture_discovery_emits_local_feed_facts(self):
        observations = discover_observations(FIXTURE_ROOT / "feed_static_basic")

        payload = "\n".join(item.to_json_line() for item in observations)
        kinds = [observation.kind for observation in observations]
        references = [
            observation
            for observation in observations
            if observation.kind in ("feed.link", "feed.enclosure")
        ]

        self.assertIn("feed.document", kinds)
        self.assertIn("feed.channel", kinds)
        self.assertIn("feed.item", kinds)
        self.assertIn("feed.link", kinds)
        self.assertIn("feed.enclosure", kinds)
        self.assertIn("feed.author", kinds)
        self.assertIn("feed.category", kinds)
        self.assertIn("feed.content", kinds)
        self.assertIn("feed.parse_error", kinds)
        self.assertNotIn("fixture-feed-secret", payload)
        self.assertNotIn("throw new Error", payload)
        self.assertTrue(
            any(
                observation.target
                == "external.url:https%3A%2F%2Fexample.com%2Frepomap%2Frss%2F1"
                for observation in references
            )
        )
        self.assertTrue(
            any(
                observation.target
                == "file:media/rss-audio.mp3"
                or observation.target == "file:feeds/media/rss-audio.mp3"
                for observation in references
            )
        )

    def test_css_file_extraction_skips_non_utf8_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            css_file = root / "bad.css"
            css_file.write_bytes(b"\xff\xfe\x00")

            observations = extract_css_file_observations_from_file(root, "bad.css")

        self.assertEqual(observations, ())

    def test_feed_file_extraction_skips_non_utf8_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            feed_file = root / "bad.xml"
            feed_file.write_bytes(b"\xff\xfe\x00")

            observations = extract_feed_file_observations_from_file(root, "bad.xml")

        self.assertEqual(observations, ())

    def test_discover_observations_routes_docs1_text_table_and_latex_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write(root / "notes.txt", "# Overview\nSee data.csv\n")
            self.write(root / "data.csv", "name,amount\nalpha,1\n")
            self.write(root / "data.tsv", "name\tactive\nalpha\ttrue\n")
            self.write(root / "paper.tex", "\\section{Intro}\n\\input{chapter}\n")
            self.write(root / "chapter.tex", "\\section{Chapter}\n")
            self.write(root / "README.md", "# Markdown\n")
            self.write(root / "ignored.pdf", "%PDF\n")

            observations = discover_observations(root)

        kinds = {observation.kind for observation in observations}
        self.assertIn("document.text_document", kinds)
        self.assertIn("document.text_section", kinds)
        self.assertIn("document.table_document", kinds)
        self.assertIn("document.table_column", kinds)
        self.assertIn("document.latex_document", kinds)
        self.assertIn("document.latex_section", kinds)
        self.assertIn("document.latex_command", kinds)
        self.assertIn("document.reference", kinds)
        self.assertIn("markdown.document", kinds)
        self.assertNotIn("document.pdf", kinds)

    def test_discover_observations_routes_docs2_odf_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_bytes(root / "notes.odt", odf_package(odt_content()))
            self.write_bytes(root / "spreadsheet.ods", odf_package(ods_content()))
            self.write_bytes(root / "template.ott", odf_package(odt_content()))
            self.write_bytes(root / "sheet-template.ots", odf_package(ods_content()))
            self.write(root / "notes.txt", "# DOCS1\n")
            self.write(root / "README.md", "# Markdown\n")
            self.write(root / "ignored.xlsx", "not-supported\n")

            observations = discover_observations(root)

        kinds = {observation.kind for observation in observations}
        self.assertIn("document.odf_document", kinds)
        self.assertIn("document.odf_text", kinds)
        self.assertIn("document.odf_sheet", kinds)
        self.assertIn("document.odf_column", kinds)
        self.assertIn("document.text_document", kinds)
        self.assertIn("markdown.document", kinds)
        self.assertNotIn("document.xlsx", kinds)

    def write(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def write_bytes(self, path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


if __name__ == "__main__":
    unittest.main()
