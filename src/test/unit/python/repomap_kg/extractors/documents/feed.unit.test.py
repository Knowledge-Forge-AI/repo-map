import json
import unittest

from repomap_kg.extractors.documents.feed import extract_feed_file_observations
from repomap_kg.observations.raw import RawObservation


RSS_FIXTURE = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>RepoMap Release Feed</title>
    <link>https://example.com/repomap/</link>
    <description>Local RSS fixture</description>
    <item>
      <guid isPermaLink="false">release-1</guid>
      <title>Release One</title>
      <link>https://example.com/repomap/releases/1</link>
      <pubDate>Tue, 30 Jun 2026 12:00:00 GMT</pubDate>
      <author>noreply@example.com (Fixture Writer)</author>
      <category>Release Notes</category>
      <description><![CDATA[<p>Released safely.</p>]]></description>
      <enclosure url="media/release-one.mp3" type="audio/mpeg" length="1234" />
    </item>
    <item>
      <title>Fallback Link Item</title>
      <link>articles/fallback.html</link>
      <pubDate>Tue, 30 Jun 2026 13:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Weak Identity Item</title>
      <pubDate>Tue, 30 Jun 2026 14:00:00 GMT</pubDate>
    </item>
    <item>
      <guid>duplicate-id</guid>
      <title>Duplicate A</title>
    </item>
    <item>
      <guid>duplicate-id</guid>
      <title>Duplicate B</title>
    </item>
  </channel>
</rss>
"""


ATOM_FIXTURE = """\
<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>RepoMap Atom Feed</title>
  <id>urn:repomap:atom</id>
  <updated>2026-06-30T12:00:00Z</updated>
  <link rel="self" href="https://example.com/repomap/atom.xml" />
  <entry>
    <id>urn:repomap:atom:item:1</id>
    <title>Atom Entry</title>
    <updated>2026-06-30T12:30:00Z</updated>
    <link rel="alternate" href="https://example.com/repomap/atom/1" />
    <author><name>Atom Writer</name><email>atom-writer@example.com</email></author>
    <category term="atom-category" />
    <summary>Atom summary</summary>
  </entry>
</feed>
"""


JSON_FEED_FIXTURE = json.dumps(
    {
        "version": "https://jsonfeed.org/version/1.1",
        "title": "RepoMap JSON Feed",
        "home_page_url": "https://example.com/repomap/",
        "feed_url": "https://example.com/repomap/feed.json",
        "authors": [{"name": "JSON Writer", "email": "json-writer@example.com"}],
        "items": [
            {
                "id": "json-item-1",
                "url": "https://example.com/repomap/json/1",
                "title": "JSON Item",
                "content_html": "<p>No scripts run.</p><script>throw new Error()</script>",
                "date_published": "2026-06-30T12:45:00Z",
                "tags": ["json-category"],
                "attachments": [{"url": "assets/item.json", "mime_type": "application/json"}],
            }
        ],
    },
    sort_keys=True,
)


class FeedExtractorUnitTests(unittest.TestCase):
    def test_extracts_rss_channel_items_links_enclosures_authors_and_categories(self):
        observations = extract_feed_file_observations("feeds/rss.xml", RSS_FIXTURE)
        payload = json.dumps(
            [observation.to_dict() for observation in observations],
            sort_keys=True,
        )
        by_kind = _by_kind(observations)

        self.assertIn("feed.document", by_kind)
        self.assertIn("feed.channel", by_kind)
        self.assertGreaterEqual(len(by_kind["feed.item"]), 5)
        self.assertIn("feed.link", by_kind)
        self.assertIn("feed.enclosure", by_kind)
        self.assertIn("feed.author", by_kind)
        self.assertIn("feed.category", by_kind)
        self.assertIn("feed.content", by_kind)
        self.assertNotIn("<script>", payload)

        first_item = by_kind["feed.item"][0]
        self.assertEqual(first_item.metadata["identity_source"], "guid")
        self.assertEqual(first_item.metadata["identity_strength"], "strong")
        self.assertEqual(first_item.metadata["published_at"], "2026-06-30T12:00:00Z")
        duplicate_items = [
            item for item in by_kind["feed.item"] if item.metadata.get("duplicate_identity")
        ]
        self.assertEqual(len(duplicate_items), 2)

        references = {(item.kind, item.target) for item in by_kind["feed.link"]}
        self.assertIn(("feed.link", "external.url:https%3A%2F%2Fexample.com%2Frepomap%2Freleases%2F1"), references)
        self.assertIn(("feed.link", "file:feeds/articles/fallback.html"), references)
        enclosure = by_kind["feed.enclosure"][0]
        self.assertEqual(enclosure.target, "file:feeds/media/release-one.mp3")
        self.assertTrue(enclosure.metadata["not_fetched"])

    def test_extracts_atom_and_json_feed_documents(self):
        atom_observations = extract_feed_file_observations("feeds/atom.xml", ATOM_FIXTURE)
        json_observations = extract_feed_file_observations("feeds/feed.json", JSON_FEED_FIXTURE)

        atom = _by_kind(atom_observations)
        json_feed = _by_kind(json_observations)

        self.assertEqual(atom["feed.document"][0].metadata["feed_format"], "atom")
        self.assertEqual(atom["feed.item"][0].metadata["identity_source"], "id")
        self.assertEqual(atom["feed.item"][0].metadata["updated_at"], "2026-06-30T12:30:00Z")
        self.assertEqual(json_feed["feed.document"][0].metadata["feed_format"], "json-feed")
        self.assertEqual(json_feed["feed.item"][0].metadata["identity_source"], "id")
        self.assertEqual(json_feed["feed.item"][0].metadata["published_at"], "2026-06-30T12:45:00Z")
        self.assertIn("feed.enclosure", json_feed)
        self.assertNotIn("throw new Error", json.dumps([item.to_dict() for item in json_observations], sort_keys=True))

    def test_non_feed_documents_are_ignored_by_feed_extractor(self):
        self.assertEqual(
            extract_feed_file_observations("config/settings.json", '{"enabled": true}'),
            (),
        )
        self.assertEqual(
            extract_feed_file_observations("config/context.xml", "<project />"),
            (),
        )

    def test_malformed_and_dangerous_feed_xml_emit_parse_error_only(self):
        malformed = extract_feed_file_observations("feeds/malformed-rss.xml", "<rss><channel>")
        dangerous = extract_feed_file_observations(
            "feeds/dangerous.xml",
            '<!DOCTYPE rss [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><rss />',
        )
        unsafe_pi = extract_feed_file_observations(
            "feeds/unsafe-pi.xml",
            '<?xml version="1.0"?><rss><?xml-stylesheet href="remote.xsl"?></rss>',
        )
        missing_channel = extract_feed_file_observations(
            "feeds/missing-channel.xml",
            '<rss version="2.0" />',
        )

        self.assertEqual([item.kind for item in malformed], ["feed.parse_error"])
        self.assertEqual(malformed[0].metadata["error_kind"], "xml-parse-error")
        self.assertEqual([item.kind for item in dangerous], ["feed.parse_error"])
        self.assertEqual(dangerous[0].metadata["error_kind"], "unsafe-xml-declaration")
        self.assertEqual([item.kind for item in unsafe_pi], ["feed.parse_error"])
        self.assertEqual(unsafe_pi[0].metadata["error_kind"], "unsafe-processing-instruction")
        self.assertEqual([item.kind for item in missing_channel], ["feed.parse_error"])
        self.assertEqual(missing_channel[0].metadata["error_kind"], "rss-missing-channel")

    def test_reference_placeholders_for_ambiguous_feed_targets(self):
        observations = extract_feed_file_observations(
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
            item.target
            for item in observations
            if item.kind == "feed.link"
        }

        self.assertIn("unknown:file:repo-escaping-feed-reference", targets)
        self.assertIn("external:file:absolute-feed-reference", targets)
        self.assertIn("dynamic:file:feed-reference-expanded-from-variable", targets)
        self.assertIn("dynamic:url:unsupported-url-scheme", targets)
        self.assertIn("unknown:external.url:malformed-feed-reference", targets)

    def test_json_feed_shape_detection_is_conservative(self):
        self.assertEqual(
            extract_feed_file_observations(
                "settings.json",
                '{"version": "1", "title": "not a feed", "items": []}',
            ),
            (),
        )
        self.assertEqual(
            extract_feed_file_observations(
                "broken.json",
                '{"version": "https://jsonfeed.org/version/1.1",',
            ),
            (),
        )

    def test_identity_fallbacks_and_email_redaction_across_formats(self):
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
	  </channel>
	</rss>
""",
        )
        atom = extract_feed_file_observations(
            "atom.xml",
            """\
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Alternate Channel</title>
  <link rel="alternate" href="https://example.com/atom/" />
  <entry>
    <title>Atom Weak</title>
    <updated>2026-06-30T16:00:00Z</updated>
  </entry>
</feed>
""",
        )
        json_feed = extract_feed_file_observations(
            "feed.json",
            json.dumps(
                {
                    "version": "https://jsonfeed.org/version/1.1",
                    "title": "JSON Home Channel",
                    "home_page_url": "https://example.com/json/",
                    "items": [
                        {
                            "external_url": "https://example.com/external",
                            "title": "External URL Identity",
                        },
                        {
                            "id": "duplicate",
                            "title": "Duplicate One",
                        },
                        {
                            "id": "duplicate",
                            "title": "Duplicate Two",
                        },
                    ],
                }
            ),
        )

        rss_by_kind = _by_kind(rss)
        atom_by_kind = _by_kind(atom)
        json_by_kind = _by_kind(json_feed)

        self.assertEqual(rss_by_kind["feed.channel"][0].metadata["identity_strength"], "weak")
        self.assertEqual(rss_by_kind["feed.item"][0].metadata["identity_source"], "structural-ordinal")
        self.assertTrue(rss_by_kind["feed.author"][0].metadata["email_redacted"])
        self.assertEqual(atom_by_kind["feed.channel"][0].metadata["identity_source"], "link")
        self.assertEqual(atom_by_kind["feed.item"][0].metadata["identity_strength"], "weak")
        self.assertEqual(json_by_kind["feed.channel"][0].metadata["identity_source"], "home_page_url")
        self.assertEqual(json_by_kind["feed.item"][0].metadata["identity_source"], "url")
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

    def test_additional_feed_identity_and_summary_branches(self):
        rss = extract_feed_file_observations(
            "untitled.xml",
            """\
<rss version="2.0">
  <channel>
    <item>
      <title>RSS weak fallback</title>
      <pubDate>not a real date</pubDate>
      <author>Plain Writer</author>
      <description>""" + ("long summary " * 30) + """</description>
    </item>
    <item>
      <guid>mailto-reference</guid>
      <title>Mailto Reference</title>
      <link>mailto:team@example.com</link>
    </item>
  </channel>
</rss>
""",
        )
        atom = extract_feed_file_observations(
            "atom-id.xml",
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
            "feed-title.json",
            json.dumps(
                {
                    "version": "https://jsonfeed.org/version/1.1",
                    "title": "Title Only JSON Feed",
                    "items": [
                        {
                            "title": "JSON Structural",
                            "authors": [{"url": "https://example.com/authors/one"}],
                        }
                    ],
                }
            ),
        )

        rss_by_kind = _by_kind(rss)
        atom_by_kind = _by_kind(atom)
        json_by_kind = _by_kind(json_feed)

        self.assertEqual(rss_by_kind["feed.channel"][0].metadata["identity_source"], "document")
        self.assertEqual(rss_by_kind["feed.item"][0].metadata["identity_source"], "title+pubDate")
        self.assertIsNone(rss_by_kind["feed.item"][0].metadata.get("published_at"))
        self.assertEqual(rss_by_kind["feed.author"][0].metadata["name"], "Plain Writer")
        self.assertEqual(
            rss_by_kind["feed.link"][0].target,
            "external.url:mailto%3Ateam%40example.com",
        )
        self.assertTrue(
            rss_by_kind["feed.content"][0].metadata["value_summary"].endswith("...")
        )
        self.assertEqual(atom_by_kind["feed.channel"][0].metadata["identity_source"], "id")
        self.assertEqual(atom_by_kind["feed.item"][0].metadata["identity_source"], "structural-ordinal")
        self.assertEqual(json_by_kind["feed.channel"][0].metadata["identity_source"], "title+document")
        self.assertEqual(json_by_kind["feed.item"][0].metadata["identity_source"], "structural-ordinal")
        self.assertIn("feed.author", json_by_kind)

    def test_secret_prone_feed_content_is_redacted(self):
        observations = extract_feed_file_observations(
            "feeds/secret-feed.xml",
            """\
<rss version="2.0">
  <channel>
    <title>Secret Feed</title>
    <item>
      <guid>secret-item</guid>
      <title>API token</title>
      <description>api_key=fixture-feed-secret</description>
    </item>
  </channel>
</rss>
""",
        )

        payload = json.dumps(
            [observation.to_dict() for observation in observations],
            sort_keys=True,
        )

        self.assertNotIn("fixture-feed-secret", payload)
        content = _by_kind(observations)["feed.content"][0]
        self.assertTrue(content.metadata["redacted"])


def _by_kind(observations: list[RawObservation] | tuple[RawObservation, ...]) -> dict[str, list[RawObservation]]:
    kinds = dict.fromkeys(observation.kind for observation in observations)
    return {kind: [item for item in observations if item.kind == kind] for kind in kinds}
