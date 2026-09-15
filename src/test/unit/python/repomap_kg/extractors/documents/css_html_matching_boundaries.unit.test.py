import unittest

from repomap_kg.extractors.documents.css import extract_css_file_observations
from repomap_kg.extractors.documents.css_html_matching import (
    extract_css_selector_match_observations,
)
from repomap_kg.extractors.documents.html import extract_html_file_observations
from repomap_kg.observations.raw import RawObservation


class CssHtmlMatchingBoundariesUnitTests(unittest.TestCase):
    def test_css_html_matching_boundary_and_rejection_contracts(self):
        html_obs = extract_html_file_observations(
            "index.html",
            """<!doctype html>
<html>
  <head>
    <link rel="stylesheet" href="style.css">
  </head>
  <body>
    <div id="my-id" class="my-class">matched</div>
    <h2 id="heading-unique">Heading</h2>
    <span id="standalone-id">span</span>
  </body>
</html>
""",
        )
        css_obs = extract_css_file_observations(
            "style.css",
            """
div#my-id.my-class {
  color: red;
}
#heading-unique {
  font-weight: bold;
}
#standalone-id {
  color: yellow;
}
divdiv {
  color: gray;
}
[data-attr='x'] {
  color: green;
}
.a > .b, .a + .b, .a ~ .b {
  color: blue;
}
""",
        )

        malformed_and_boundary_obs = [
            RawObservation(
                kind="html.asset",
                source_id="index.html#asset_link_rel",
                path="index.html",
                target="file:style.css",
                confidence="extracted",
                extractor="repo-html",
                extractor_version="0.1.0",
                metadata={"format": "html", "tag": "link", "attribute": "rel"},
            ),
            RawObservation(
                kind="html.asset",
                source_id="index.html#asset_link_none_target",
                path="index.html",
                target=None,
                confidence="extracted",
                extractor="repo-html",
                extractor_version="0.1.0",
                metadata={"format": "html", "tag": "link", "attribute": "href"},
            ),
            RawObservation(
                kind="html.asset",
                source_id="index.html#asset1",
                path="index.html",
                target="external.url:https%3A%2F%2Fexample.com%2Fstyle.css",
                confidence="extracted",
                extractor="repo-html",
                extractor_version="0.1.0",
                metadata={"format": "html", "tag": "link", "attribute": "href"},
            ),
            RawObservation(
                kind="html.asset",
                source_id="index.html#asset2",
                path="index.html",
                target="bad key!",
                confidence="extracted",
                extractor="repo-html",
                extractor_version="0.1.0",
                metadata={"format": "html", "tag": "link", "attribute": "href"},
            ),
            RawObservation(
                kind="html.asset",
                source_id="index.html#asset3",
                path="index.html",
                target="file:not-css.js",
                confidence="extracted",
                extractor="repo-html",
                extractor_version="0.1.0",
                metadata={"format": "html", "tag": "link", "attribute": "href"},
            ),
            RawObservation(
                kind="html.asset",
                source_id="index.html#asset4",
                path="index.html",
                target="file:style.css",
                confidence="extracted",
                extractor="repo-html",
                extractor_version="0.1.0",
                metadata={"format": "html", "tag": "script", "attribute": "src"},
            ),
            RawObservation(
                kind="css.selector",
                source_id="style.css#sel_empty",
                path="style.css",
                target="css.selector:file%3Astyle.css:%2Frule%3A1%2Fselector%3A99",
                confidence="extracted",
                extractor="repo-css",
                extractor_version="0.1.0",
                metadata={"selector_text": "", "selector_pointer": "/rule:1/selector:99"},
            ),
            RawObservation(
                kind="css.selector",
                source_id="style.css#sel1",
                path="style.css",
                target=None,
                confidence="extracted",
                extractor="repo-css",
                extractor_version="0.1.0",
                metadata={"selector_text": ".a"},
            ),
            RawObservation(
                kind="css.selector",
                source_id="style.css#sel2",
                path="style.css",
                target="bad selector key",
                confidence="extracted",
                extractor="repo-css",
                extractor_version="0.1.0",
                metadata={"selector_text": ".b", "selector_pointer": "/rule:1/selector:1"},
            ),
            RawObservation(
                kind="css.selector",
                source_id="style.css#sel3",
                path="style.css",
                target="file:style.css",
                confidence="extracted",
                extractor="repo-css",
                extractor_version="0.1.0",
                metadata={"selector_text": ".c", "selector_pointer": "/rule:1/selector:2"},
            ),
            RawObservation(
                kind="html.element",
                source_id="index.html#el1",
                path="index.html",
                target=None,
                confidence="extracted",
                extractor="repo-html",
                extractor_version="0.1.0",
                metadata={"classes": ["a"]},
            ),
            RawObservation(
                kind="html.heading",
                source_id="index.html#head1",
                path="index.html",
                target="html.anchor:file%3Aindex.html:h1",
                confidence="extracted",
                extractor="repo-html",
                extractor_version="0.1.0",
                metadata={
                    "id_is_unique": False,
                    "source_element_pointer": "/html/body/h1",
                },
            ),
            RawObservation(
                kind="html.heading",
                source_id="index.html#head2",
                path="index.html",
                target=None,
                confidence="extracted",
                extractor="repo-html",
                extractor_version="0.1.0",
                metadata={
                    "id_is_unique": True,
                    "source_element_pointer": None,
                },
            ),
            RawObservation(
                kind="html.heading",
                source_id="index.html#head3",
                path="index.html",
                target="config.document:file%3Aindex.html",
                confidence="extracted",
                extractor="repo-html",
                extractor_version="0.1.0",
                metadata={
                    "id_is_unique": True,
                    "source_element_pointer": "/html/body/h3",
                },
            ),
        ]

        matches = extract_css_selector_match_observations(
            (*html_obs, *css_obs, *malformed_and_boundary_obs)
        )
        self.assertEqual(len(matches), 3)
        matched_targets = {match.target for match in matches}
        self.assertIn("html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fdiv", matched_targets)
        self.assertIn("html.anchor:file%3Aindex.html:heading-unique", matched_targets)
        self.assertIn("html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fspan", matched_targets)

    def test_css_html_matching_selector_component_boundaries(self):
        css_obs = extract_css_file_observations(
            "style2.css",
            """
.class div { color: red; }
#id div { color: blue; }
""",
        )
        html_obs = extract_html_file_observations(
            "index2.html",
            """<!doctype html>
<html><body><div class="class"><div>text</div></div></body></html>
""",
        )
        matches = extract_css_selector_match_observations((*html_obs, *css_obs))
        self.assertIsInstance(matches, tuple)

        from repomap_kg.extractors.documents.css_html_matching import _parse_compound_selector
        self.assertIsNone(_parse_compound_selector(""))
        self.assertIsNone(_parse_compound_selector(".cls div"))
        self.assertIsNotNone(_parse_compound_selector("div.cls#id"))


if __name__ == "__main__":
    unittest.main()
