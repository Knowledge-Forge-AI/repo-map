import unittest
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from repomap_kg.canonicalization.main import canonicalize_observations
    from repomap_kg.observations.raw import RawObservation
else:
    from repomap_kg.canonicalization import canonicalize_observations
    from repomap_kg.observations import RawObservation

from repomap_kg.graph.keys import feed_channel_key, feed_document_key


class CanonicalizationFeedXmlBoundariesUnitTests(unittest.TestCase):
    def test_feed_channel_fallback_document_key_and_definition_target(self):
        doc_key = feed_document_key("feeds/fallback.xml")
        ch_key = feed_channel_key(doc_key, "main")
        doc_obs = RawObservation(
            kind="feed.document",
            source_id="feeds/fallback.xml#doc",
            path="feeds/fallback.xml",
            target=None,
            confidence="extracted",
            extractor="repo-feed",
            extractor_version="0.1.0",
            metadata={"format": "rss"},
        )
        channel_obs = RawObservation(
            kind="feed.channel",
            source_id="feeds/fallback.xml#channel",
            path="feeds/fallback.xml",
            target=ch_key,
            confidence="extracted",
            extractor="repo-feed",
            extractor_version="0.1.0",
            metadata={},
        )

        result = canonicalize_observations((doc_obs, channel_obs))
        self.assertTrue(result.ok)
        node_keys = {node["canonical_key"] for node in result.to_dict()["nodes"]}
        self.assertIn(doc_key, node_keys)
        self.assertIn(ch_key, node_keys)

    def test_feed_definition_and_reference_diagnostics_reject_invalid_keys(self):
        doc_key = feed_document_key("feeds/rss.xml")
        channel_key = feed_channel_key(doc_key, "main")

        invalid_definitions = [
            RawObservation(
                kind="feed.channel",
                source_id="feeds/rss.xml#bad-doc-key",
                path="feeds/rss.xml",
                target=channel_key,
                confidence="extracted",
                extractor="repo-feed",
                extractor_version="0.1.0",
                metadata={"document_key": "file:feeds/rss.xml"},
            ),
            RawObservation(
                kind="feed.item",
                source_id="feeds/rss.xml#bad-channel-key",
                path="feeds/rss.xml",
                target="feed.item:feed.channel%3Aparent:item1",
                confidence="extracted",
                extractor="repo-feed",
                extractor_version="0.1.0",
                metadata={"channel_key": "file:feeds/rss.xml"},
            ),
            RawObservation(
                kind="feed.channel",
                source_id="feeds/rss.xml#missing-target",
                path="feeds/rss.xml",
                target=None,
                confidence="extracted",
                extractor="repo-feed",
                extractor_version="0.1.0",
                metadata={"document_key": doc_key},
            ),
            RawObservation(
                kind="feed.channel",
                source_id="feeds/rss.xml#bad-target-ns",
                path="feeds/rss.xml",
                target="file:feeds/rss.xml",
                confidence="extracted",
                extractor="repo-feed",
                extractor_version="0.1.0",
                metadata={"document_key": doc_key},
            ),
            RawObservation(
                kind="feed.link",
                source_id="feeds/rss.xml#missing-source",
                path="feeds/rss.xml",
                target="file:feeds/article.html",
                confidence="extracted",
                extractor="repo-feed",
                extractor_version="0.1.0",
                metadata={},
            ),
        ]

        result = canonicalize_observations(invalid_definitions)
        self.assertFalse(result.ok)
        self.assertEqual(result.to_dict()["summary"]["errors"], 5)


if __name__ == "__main__":
    unittest.main()
