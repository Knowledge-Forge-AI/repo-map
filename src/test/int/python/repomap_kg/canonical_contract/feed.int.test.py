import json
import tempfile
import unittest
from pathlib import Path

from repomap_test_support.canonical_contract import (
    DISCOVERY_FIXTURE_ROOT,
    observations_by_kind as _observations_by_kind,
)

from repomap_kg.canonicalization.main import canonicalize_observations
from repomap_kg.graph.discovery import (
    extract_feed_file_observations_from_file,
)
from repomap_kg.extractors.documents.feed import extract_feed_file_observations
from repomap_kg.observations.raw import RawObservation


class CanonicalFeedIntegrationTests(unittest.TestCase):
    def test_local_feed_extraction_and_canonicalization_contract(self):
        fixture = DISCOVERY_FIXTURE_ROOT / "feed_static_basic"
        rss = extract_feed_file_observations(
            "rss.xml",
            (fixture / "rss.xml").read_text(encoding="utf-8"),
        )
        atom = extract_feed_file_observations(
            "atom.xml",
            (fixture / "atom.xml").read_text(encoding="utf-8"),
        )
        json_feed = extract_feed_file_observations(
            "feed.json",
            (fixture / "feed.json").read_text(encoding="utf-8"),
        )
        malformed = extract_feed_file_observations(
            "malformed-rss.xml",
            (fixture / "malformed-rss.xml").read_text(encoding="utf-8"),
        )
        secret = extract_feed_file_observations(
            "secret-feed.xml",
            (fixture / "secret-feed.xml").read_text(encoding="utf-8"),
        )
        dangerous = extract_feed_file_observations(
            "dangerous.xml",
            '<!DOCTYPE rss [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><rss />',
        )

        observations = [*rss, *atom, *json_feed, *malformed, *secret, *dangerous]
        kinds = {observation.kind for observation in observations}
        self.assertTrue(
            {
                "feed.document",
                "feed.channel",
                "feed.item",
                "feed.link",
                "feed.enclosure",
                "feed.author",
                "feed.category",
                "feed.content",
                "feed.parse_error",
            }.issubset(kinds)
        )
        serialized = json.dumps(
            [observation.to_dict() for observation in observations],
            sort_keys=True,
        )
        self.assertNotIn("fixture-feed-secret", serialized)
        self.assertNotIn("throw new Error", serialized)

        result = canonicalize_observations(observations)
        payload = result.to_dict()
        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["errors"], 0)
        self.assertGreaterEqual(payload["summary"]["nodes"], 10)
        self.assertGreaterEqual(payload["summary"]["edges"], 10)

        nodes = {record["canonical_key"]: record for record in payload["nodes"]}
        edges = {
            (record["source_key"].split(":", 1)[0], record["kind"], record["target_key"])
            for record in payload["edges"]
        }
        self.assertIn("feed.document:file%3Arss.xml", nodes)
        self.assertTrue(any(key.startswith("feed.channel:") for key in nodes))
        self.assertTrue(any(key.startswith("feed.item:") for key in nodes))
        self.assertTrue(any(key.startswith("feed.author:") for key in nodes))
        self.assertTrue(any(key.startswith("feed.category:") for key in nodes))
        self.assertIn(
            (
                "feed.item",
                "references",
                "external.url:https%3A%2F%2Fexample.com%2Frepomap%2Frss%2F1",
            ),
            edges,
        )
        self.assertIn(("feed.item", "references", "file:media/rss-audio.mp3"), edges)
        evidence_kinds = {record["raw_kind"] for record in payload["evidence"]}
        self.assertIn("feed.content", evidence_kinds)
        self.assertIn("feed.parse_error", evidence_kinds)
        graph_text = json.dumps(
            {"nodes": payload["nodes"], "edges": payload["edges"]},
            sort_keys=True,
        )
        self.assertNotIn("feed.content:", graph_text)
        self.assertNotIn("feed.parse_error:", graph_text)

    def test_feed_error_identity_and_placeholder_contracts(self):
        self.assertEqual(
            extract_feed_file_observations("settings.json", '{"enabled": true}'),
            (),
        )
        self.assertEqual(
            extract_feed_file_observations("project.xml", "<project />"),
            (),
        )

        error_cases = [
            (
                "malformed.xml",
                "<rss><channel>",
                "xml-parse-error",
            ),
            (
                "unsafe.xml",
                '<!DOCTYPE rss [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><rss />',
                "unsafe-xml-declaration",
            ),
            (
                "unsafe-pi.xml",
                '<?xml version="1.0"?><rss><?xml-stylesheet href="remote.xsl"?></rss>',
                "unsafe-processing-instruction",
            ),
            (
                "missing-channel.xml",
                '<rss version="2.0" />',
                "rss-missing-channel",
            ),
        ]
        for path, content, error_kind in error_cases:
            with self.subTest(error_kind=error_kind):
                observations = extract_feed_file_observations(path, content)
                self.assertEqual([observation.kind for observation in observations], ["feed.parse_error"])
                self.assertEqual(observations[0].metadata["error_kind"], error_kind)

        references = extract_feed_file_observations(
            "feeds/rss.xml",
            """\
<rss version="2.0">
  <channel>
    <title>Reference Fixture</title>
    <item><guid>outside</guid><link>../../outside.html</link></item>
    <item><guid>absolute</guid><link>/Library/file.txt</link></item>
    <item><guid>dynamic</guid><link>${ARTICLE_URL}</link></item>
    <item><guid>unsupported</guid><link>ftp://example.com/file</link></item>
    <item><guid>malformed-http</guid><link>https:///missing-host</link></item>
  </channel>
</rss>
""",
        )
        targets = {
            observation.target
            for observation in references
            if observation.kind == "feed.link"
        }
        self.assertTrue(
            {
                "unknown:file:repo-escaping-feed-reference",
                "external:file:absolute-feed-reference",
                "dynamic:file:feed-reference-expanded-from-variable",
                "dynamic:url:unsupported-url-scheme",
                "unknown:external.url:malformed-feed-reference",
            }.issubset(targets)
        )

        rss = extract_feed_file_observations(
            "rss.xml",
            """\
<rss version="2.0">
  <channel>
    <title>Fallback Channel</title>
    <item>
      <title>Ordinal Item</title>
      <author>email-only@example.com</author>
    </item>
    <item>
      <title>Weak Item</title>
      <pubDate>not a real date</pubDate>
      <description>""" + ("summary " * 40) + """</description>
    </item>
  </channel>
</rss>
""",
        )
        atom = extract_feed_file_observations(
            "atom.xml",
            """\
<feed xmlns="http://www.w3.org/2005/Atom">
  <id>urn:example:atom-id-only</id>
  <entry>
    <title>Atom Structural</title>
  </entry>
</feed>
""",
        )
        json_feed = extract_feed_file_observations(
            "feed.json",
            json.dumps(
                {
                    "version": "https://jsonfeed.org/version/1.1",
                    "title": "JSON Fallback Feed",
                    "items": [
                        {"external_url": "https://example.com/external"},
                        {"id": "duplicate", "title": "Duplicate One"},
                        {"id": "duplicate", "title": "Duplicate Two"},
                        {"title": "Structural JSON"},
                    ],
                }
            ),
        )
        atom_alternate = extract_feed_file_observations(
            "atom-alternate.xml",
            """\
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Alternate Fallback</title>
  <link rel="alternate" href="https://example.com/atom/" />
  <entry>
    <title>Atom Alternate Entry</title>
    <published>2026-06-30T16:00:00</published>
    <link href="relative-entry.html" />
    <author><uri>https://example.com/writer</uri></author>
    <category label="Atom Label" />
    <content type="html"><p>Atom content</p></content>
  </entry>
</feed>
""",
        )
        json_extra = extract_feed_file_observations(
            "feed-extra.json",
            json.dumps(
                {
                    "version": "https://jsonfeed.org/version/1.1",
                    "title": "JSON Extra Feed",
                    "feed_url": "https://example.com/extra/feed.json",
                    "items": [
                        {
                            "id": "extra",
                            "date_modified": "2026-06-30T17:00:00",
                            "content_text": "JSON text content",
                            "authors": [{"name": "JSON Writer"}],
                            "tags": ["json-extra", 17],
                            "attachments": [
                                "not an object",
                                {},
                                {"url": "media/extra.bin", "size_in_bytes": 12},
                            ],
                        }
                    ],
                }
            ),
        )
        rss_by_kind = _observations_by_kind(rss)
        atom_by_kind = _observations_by_kind(atom)
        json_by_kind = _observations_by_kind(json_feed)
        atom_alternate_by_kind = _observations_by_kind(atom_alternate)
        json_extra_by_kind = _observations_by_kind(json_extra)

        self.assertEqual(rss_by_kind["feed.channel"][0].metadata["identity_strength"], "weak")
        self.assertEqual(rss_by_kind["feed.item"][0].metadata["identity_source"], "structural-ordinal")
        self.assertTrue(rss_by_kind["feed.author"][0].metadata["email_redacted"])
        self.assertEqual(rss_by_kind["feed.item"][1].metadata["identity_source"], "title+pubDate")
        self.assertTrue(rss_by_kind["feed.content"][0].metadata["value_summary"].endswith("..."))
        self.assertEqual(atom_by_kind["feed.channel"][0].metadata["identity_source"], "id")
        self.assertEqual(atom_by_kind["feed.item"][0].metadata["identity_source"], "structural-ordinal")
        self.assertEqual(json_by_kind["feed.channel"][0].metadata["identity_source"], "title+document")
        self.assertEqual(json_by_kind["feed.item"][0].metadata["identity_source"], "url")
        self.assertEqual(json_by_kind["feed.item"][-1].metadata["identity_source"], "structural-ordinal")
        self.assertEqual(
            atom_alternate_by_kind["feed.channel"][0].metadata["identity_source"],
            "link",
        )
        self.assertEqual(
            atom_alternate_by_kind["feed.item"][0].metadata["published_at"],
            "2026-06-30T16:00:00Z",
        )
        self.assertEqual(atom_alternate_by_kind["feed.link"][1].target, "file:relative-entry.html")
        self.assertIn("feed.author", atom_alternate_by_kind)
        self.assertIn("feed.category", atom_alternate_by_kind)
        self.assertEqual(json_extra_by_kind["feed.channel"][0].metadata["identity_source"], "feed_url")
        self.assertEqual(json_extra_by_kind["feed.item"][0].metadata["updated_at"], "2026-06-30T17:00:00Z")
        self.assertEqual(json_extra_by_kind["feed.enclosure"][0].target, "file:media/extra.bin")
        self.assertIn("feed.author", json_extra_by_kind)
        self.assertEqual(
            len(
                [
                    item
                    for item in json_by_kind["feed.item"]
                    if item.metadata.get("duplicate_identity")
                ]
            ),
            2,
        )

        feed_item_key_for_diagnostics = (
            "feed.item:feed.channel%3Afeed.document%253Afile%25253A"
            "feed.xml%3Aself:item"
        )
        diagnostics = canonicalize_observations(
            [
                RawObservation(
                    kind="feed.document",
                    source_id="feed.xml#feed-document:bad-target",
                    path="feed.xml",
                    target="bad target",
                    confidence="extracted",
                    extractor="repo-feed",
                    extractor_version="0.1.0",
                    metadata={"feed_format": "rss"},
                ),
                RawObservation(
                    kind="feed.item",
                    source_id="feed.xml#feed-item:missing-channel",
                    path="feed.xml",
                    target=feed_item_key_for_diagnostics,
                    confidence="extracted",
                    extractor="repo-feed",
                    extractor_version="0.1.0",
                    metadata={"feed_format": "rss"},
                ),
                RawObservation(
                    kind="feed.item",
                    source_id="feed.xml#feed-item:bad-parent",
                    path="feed.xml",
                    target="feed.item:bad-parent:item",
                    confidence="extracted",
                    extractor="repo-feed",
                    extractor_version="0.1.0",
                    metadata={"channel_key": "feed.channel:bad-parent:channel"},
                ),
                RawObservation(
                    kind="feed.link",
                    source_id="feed.xml#feed-link:missing",
                    path="feed.xml",
                    confidence="extracted",
                    extractor="repo-feed",
                    extractor_version="0.1.0",
                    metadata={"source_key": "feed.item:bad-parent:item"},
                ),
                RawObservation(
                    kind="feed.link",
                    source_id="feed.xml#feed-link:bad-target",
                    path="feed.xml",
                    target="bad target",
                    confidence="extracted",
                    extractor="repo-feed",
                    extractor_version="0.1.0",
                    metadata={"source_key": feed_item_key_for_diagnostics},
                ),
                RawObservation(
                    kind="feed.link",
                    source_id="feed.xml#feed-link:bad-source",
                    path="feed.xml",
                    target="external.url:https%3A%2F%2Fexample.com",
                    confidence="extracted",
                    extractor="repo-feed",
                    extractor_version="0.1.0",
                    metadata={"source_key": "file:feed.xml"},
                ),
            ]
        ).to_dict()["diagnostics"]
        self.assertEqual(
            [diagnostic["category"] for diagnostic in diagnostics],
            [
                "invalid_canonical_key",
                "invalid_canonical_key",
                "missing_required_metadata",
                "invalid_canonical_key",
                "invalid_canonical_key",
            ],
        )

    def test_feed_file_extraction_skips_non_utf8_local_artifacts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "feed.xml").write_bytes(b"\xff\xfe<rss></rss>")

            observations = extract_feed_file_observations_from_file(root, "feed.xml")

        self.assertEqual(observations, ())
