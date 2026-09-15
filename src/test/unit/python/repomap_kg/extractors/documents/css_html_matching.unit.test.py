import unittest
from collections.abc import Iterator, Sequence
from unittest.mock import patch

from repomap_kg.extractors.documents import css_html_matching
from repomap_kg.extractors.documents.css import extract_css_file_observations
from repomap_kg.extractors.documents.css_html_matching import extract_css_selector_match_observations
from repomap_kg.extractors.documents.html import extract_html_file_observations
from repomap_kg.observations.raw import RawObservation


class _CountingElements(Sequence[css_html_matching._HtmlElement]):
    def __init__(
        self,
        elements: tuple[css_html_matching._HtmlElement, ...],
    ) -> None:
        self._elements = elements
        self.items_yielded = 0

    def __getitem__(self, index):
        return self._elements[index]

    def __len__(self) -> int:
        return len(self._elements)

    def __iter__(self) -> Iterator[css_html_matching._HtmlElement]:
        for element in self._elements:
            self.items_yielded += 1
            yield element


def _descendant_elements(size: int) -> tuple[css_html_matching._HtmlElement, ...]:
    ancestor = css_html_matching._HtmlElement(
        path="index.html",
        key="html.element:ancestor",
        pointer="/html/body/section",
        tag="section",
        classes=("ancestor",),
        element_id=None,
        id_is_unique=False,
    )
    descendants = tuple(
        css_html_matching._HtmlElement(
            path="index.html",
            key=f"html.element:descendant-{index}",
            pointer=f"/html/body/section/span[{index}]",
            tag="span",
            classes=("target",),
            element_id=None,
            id_is_unique=False,
        )
        for index in range(size)
    )
    return (ancestor, *descendants)


HTML_FIXTURE = """\
<!doctype html>
<html>
  <head>
    <link rel="stylesheet" href="static/report.css">
    <link rel="stylesheet" href="https://example.com/remote.css">
  </head>
  <body>
    <header class="report-header">
      <span class="status-badge status-passed">Passed</span>
    </header>
    <main id="welcome" class="report-body">
      <a class="external" href="https://example.com/docs">Docs</a>
      <section class="tree-grid">
        <span class="path-cell">src/main.py</span>
        <span class="metric-cell">99%</span>
        <span class="status-cell">pass</span>
      </section>
      <div class="row">row</div>
      <h1 id="heading">Heading</h1>
      <div id="dup" class="status-badge">dup one</div>
      <div id="dup">dup two</div>
    </main>
  </body>
</html>
"""


CSS_FIXTURE = """\
.status-badge,
#welcome,
#heading,
a,
a.external,
.status-badge.status-passed,
.report-header .status-badge,
.a > .b,
.status-badge:hover,
#dup {
  color: #f8fafc;
}
"""


class CssHtmlMatchingUnitTests(unittest.TestCase):
    def test_descendant_matching_element_traversals_grow_near_linearly(self):
        observations = (
            extract_html_file_observations(
                "index.html",
                "<html><head>"
                '<link rel="stylesheet" href="static/first.css">'
                '<link rel="stylesheet" href="static/second.css">'
                "</head></html>",
            )
            + extract_css_file_observations(
                "static/first.css",
                ".ancestor .target { color: green; }\n",
            )
            + extract_css_file_observations(
                "static/second.css",
                "section .target { color: blue; }\n",
            )
        )
        traversal_counts = []

        for size in (16, 32, 64):
            elements = _CountingElements(_descendant_elements(size))
            with patch.object(
                css_html_matching,
                "_html_elements_by_file",
                return_value={"index.html": elements},
            ):
                matches = extract_css_selector_match_observations(observations)

            self.assertEqual(len(matches), size * 2)
            self.assertLessEqual(elements.items_yielded, len(elements) * 4)
            traversal_counts.append(elements.items_yielded)

        self.assertLessEqual(traversal_counts[1], traversal_counts[0] * 2.2)
        self.assertLessEqual(traversal_counts[2], traversal_counts[1] * 2.2)

    def test_matches_only_supported_selectors_for_linked_local_stylesheet(self):
        observations = (
            extract_html_file_observations("index.html", HTML_FIXTURE)
            + extract_css_file_observations("static/report.css", CSS_FIXTURE)
        )

        matches = extract_css_selector_match_observations(observations)

        self.assertTrue(matches)
        self.assertTrue(all(item.kind == "css.selector_match" for item in matches))
        by_selector: dict[str, set[str | None]] = {}
        for match in matches:
            by_selector.setdefault(match.metadata["selector_text"], set()).add(
                match.target
            )
            self.assertEqual(match.metadata["scope"], "local-html-css")
            self.assertTrue(match.metadata["not_runtime_style"])
            self.assertEqual(match.metadata["css_file"], "static/report.css")
            self.assertEqual(match.metadata["html_file"], "index.html")
            self.assertIn("selector_key", match.metadata)
            self.assertIn("html_key", match.metadata)
            self.assertIn("matched_components", match.metadata)

        self.assertIn(
            "html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fheader%2Fspan",
            by_selector[".status-badge"],
        )
        self.assertIn(
            "html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fmain",
            by_selector["#welcome"],
        )
        self.assertIn(
            "html.anchor:file%3Aindex.html:heading",
            by_selector["#heading"],
        )
        self.assertIn(
            "html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fmain%2Fa",
            by_selector["a"],
        )
        self.assertIn(
            "html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fmain%2Fa",
            by_selector["a.external"],
        )
        self.assertIn(
            "html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fheader%2Fspan",
            by_selector[".status-badge.status-passed"],
        )
        self.assertIn(
            "html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fheader%2Fspan",
            by_selector[".report-header .status-badge"],
        )
        self.assertNotIn(".a > .b", by_selector)
        self.assertNotIn(".status-badge:hover", by_selector)
        self.assertNotIn("#dup", by_selector)

    def test_compound_selector_identity_is_deduplicated_and_fail_closed(self):
        observations = (
            extract_html_file_observations(
                "index.html",
                """<html><head>
<link rel="stylesheet" href="static/compound.css">
<link rel="stylesheet" href="static/compound.css">
</head><body>
<section class="container"><span id="notice" class="status-badge">ok</span></section>
</body></html>""",
            )
            + extract_css_file_observations(
                "static/compound.css",
                """
span.status-badge,
.status-badge.status-badge,
#notice,
#notice#other,
section.status-badge,
.missing,
span..broken,
section..broken .status-badge,
.container span..broken {
  color: green;
}
""",
            )
        )

        matches = extract_css_selector_match_observations(observations)
        by_selector: dict[str, list[RawObservation]] = {}
        for match in matches:
            by_selector.setdefault(match.metadata["selector_text"], []).append(match)

        self.assertEqual(
            set(by_selector),
            {"span.status-badge", ".status-badge.status-badge", "#notice"},
        )
        self.assertTrue(all(len(items) == 1 for items in by_selector.values()))
        self.assertEqual(
            by_selector["#notice"][0].target,
            "html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fsection%2Fspan",
        )
        self.assertEqual(
            by_selector["span.status-badge"][0].metadata["match_kind"],
            "compound",
        )
        self.assertEqual(
            by_selector[".status-badge.status-badge"][0].metadata[
                "matched_components"
            ]["classes"],
            ["status-badge"],
        )

    def test_does_not_match_remote_or_unpaired_stylesheets(self):
        observations = (
            extract_html_file_observations("index.html", HTML_FIXTURE)
            + extract_css_file_observations(
                "unlinked.css",
                ".status-badge { color: red; }\n",
            )
            + extract_css_file_observations(
                "remote.css",
                ".status-badge { color: blue; }\n",
            )
        )

        matches = extract_css_selector_match_observations(observations)

        self.assertEqual(matches, ())

    def test_ignores_malformed_or_unsupported_candidate_facts(self):
        observations = (
            RawObservation(
                kind="html.asset",
                source_id="index.html#remote-css",
                path="index.html",
                name="/html/head/link",
                target="external.url:https%3A%2F%2Fexample.com%2Fremote.css",
                confidence="heuristic",
                extractor="repo-html",
                extractor_version="0.1.0",
                metadata={"tag": "link", "attribute": "href"},
            ),
            RawObservation(
                kind="html.asset",
                source_id="index.html#non-css",
                path="index.html",
                name="/html/head/link[2]",
                target="file:README.md",
                confidence="heuristic",
                extractor="repo-html",
                extractor_version="0.1.0",
                metadata={"tag": "link", "attribute": "href"},
            ),
            RawObservation(
                kind="html.asset",
                source_id="index.html#bad-target",
                path="index.html",
                name="/html/head/link[3]",
                target="not a key",
                confidence="heuristic",
                extractor="repo-html",
                extractor_version="0.1.0",
                metadata={"tag": "link", "attribute": "href"},
            ),
            RawObservation(
                kind="css.selector",
                source_id="static/report.css#missing-target",
                path="static/report.css",
                name="/rule:1/selector:1",
                confidence="extracted",
                extractor="repo-css",
                extractor_version="0.1.0",
                metadata={
                    "selector_pointer": "/rule:1/selector:1",
                    "selector_text": ".status-badge",
                },
            ),
        )

        matches = extract_css_selector_match_observations(observations)

        self.assertEqual(matches, ())

    def test_skips_descendant_without_matching_ancestor_and_deep_descendant(self):
        observations = (
            extract_html_file_observations(
                "index.html",
                """<html><head><link rel="stylesheet" href="static/report.css"></head>
<body><main><span class="status-badge">ok</span></main></body></html>""",
            )
            + extract_css_file_observations(
                "static/report.css",
                ".report-header .status-badge { color: green; }\n"
                ".one .two .status-badge { color: blue; }\n",
            )
        )

        matches = extract_css_selector_match_observations(observations)

        self.assertEqual(matches, ())



if __name__ == "__main__":
    unittest.main()
