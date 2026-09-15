import unittest
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from repomap_kg.canonicalization.main import canonicalize_observations
    from repomap_kg.observations.raw import RawObservation
else:
    from repomap_kg.canonicalization import canonicalize_observations
    from repomap_kg.observations import RawObservation

from repomap_kg.extractors.config.generic import extract_config_file_observations
from repomap_kg.extractors.documents.feed import extract_feed_file_observations


class CanonicalizationFeedXmlFamilyUnitTests(unittest.TestCase):
    def test_feed_observations_create_feed_nodes_and_reference_edges(self):
        observations = extract_feed_file_observations(
            "feeds/rss.xml",
            """\
<rss version="2.0">
  <channel>
    <title>RepoMap Feed</title>
    <link>https://example.com/repomap/</link>
    <item>
      <guid>release-1</guid>
      <title>Release One</title>
      <link>articles/release-one.html</link>
      <author>Fixture Author</author>
      <category>Release Notes</category>
      <description>Short safe summary.</description>
      <enclosure url="media/release-one.mp3" type="audio/mpeg" />
    </item>
  </channel>
</rss>
""",
        ) + (
            RawObservation(
                kind="feed.parse_error",
                source_id="feeds/broken.xml#feed-parse-error:xml-parse-error",
                path="feeds/broken.xml",
                confidence="unknown",
                extractor="repo-feed",
                extractor_version="0.1.0",
                metadata={"error_kind": "xml-parse-error", "raw_only": True},
            ),
        )

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["diagnostics"], [])
        node_kinds = {node["kind"] for node in payload["nodes"]}
        self.assertIn("feed.document", node_kinds)
        self.assertIn("feed.channel", node_kinds)
        self.assertIn("feed.item", node_kinds)
        self.assertIn("feed.author", node_kinds)
        self.assertIn("feed.category", node_kinds)
        self.assertNotIn("feed.content", node_kinds)
        self.assertNotIn("feed.parse_error", node_kinds)
        edge_kinds = {edge["kind"] for edge in payload["edges"]}
        self.assertEqual(edge_kinds, {"defines", "references"})
        references = {
            (edge["source_key"].split(":", 1)[0], edge["target_key"])
            for edge in payload["edges"]
            if edge["kind"] == "references"
        }
        self.assertIn(("feed.item", "file:feeds/articles/release-one.html"), references)
        self.assertIn(("feed.item", "file:feeds/media/release-one.mp3"), references)
        self.assertTrue(
            any(target.startswith("feed.author:") for _, target in references)
        )
        self.assertTrue(
            any(target.startswith("feed.category:") for _, target in references)
        )

    def test_feed_reference_diagnostics_use_placeholders(self):
        observations = [
            RawObservation(
                kind="feed.link",
                source_id="feeds/rss.xml#missing-target",
                path="feeds/rss.xml",
                confidence="extracted",
                extractor="repo-feed",
                extractor_version="0.1.0",
                metadata={"source_key": "feed.item:bad-parent:item"},
            ),
            RawObservation(
                kind="feed.link",
                source_id="feeds/rss.xml#malformed-target",
                path="feeds/rss.xml",
                target="bad key",
                confidence="extracted",
                extractor="repo-feed",
                extractor_version="0.1.0",
                metadata={"source_key": "feed.item:bad-parent:item"},
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["warnings"], 2)
        self.assertEqual(
            {
                diagnostic["placeholder_key"]
                for diagnostic in payload["diagnostics"]
            },
            {
                "unknown:feed.reference:missing-target",
                "unknown:feed.reference:malformed-target",
            },
        )
        self.assertIn(
            "unknown:feed.reference:missing-target",
            {edge["target_key"] for edge in payload["edges"]},
        )

    def test_feed_diagnostics_reject_bad_source_and_parent_keys(self):
        observations = [
            RawObservation(
                kind="feed.link",
                source_id="feeds/rss.xml#bad-source",
                path="feeds/rss.xml",
                target="external.url:https%3A%2F%2Fexample.com",
                confidence="extracted",
                extractor="repo-feed",
                extractor_version="0.1.0",
                metadata={"source_key": "config.document:file%3Asettings.json"},
            ),
            RawObservation(
                kind="feed.item",
                source_id="feeds/rss.xml#missing-channel",
                path="feeds/rss.xml",
                target="feed.item:feed.channel%3Aparent:item",
                confidence="extracted",
                extractor="repo-feed",
                extractor_version="0.1.0",
                metadata={},
            ),
            RawObservation(
                kind="feed.author",
                source_id="feeds/rss.xml#bad-item-key",
                path="feeds/rss.xml",
                target="feed.author:feed.channel%3Aparent:fixture",
                confidence="extracted",
                extractor="repo-feed",
                extractor_version="0.1.0",
                metadata={
                    "channel_key": "feed.channel:feed.document%3Afile%253Arss.xml:channel",
                    "item_key": "config.path:file%3Asettings.json:%2Fname",
                },
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["summary"]["errors"], 3)
        self.assertEqual(
            [diagnostic["category"] for diagnostic in payload["diagnostics"]],
            [
                "invalid_canonical_key",
                "invalid_canonical_key",
                "invalid_canonical_key",
            ],
        )

    def test_generic_xml_observations_create_structure_and_reference_edges(self):
        observations = extract_config_file_observations(
            "src/main/resources/applicationContext.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<beans xmlns="http://www.springframework.org/schema/beans"
       xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
       xsi:schemaLocation="http://www.springframework.org/schema/beans https://www.springframework.org/schema/beans/spring-beans.xsd">
  <bean id="service" class="com.example.Service">
    <property name="configPath" value="./config/service.properties"/>
  </bean>
</beans>
""",
        )
        unsafe = extract_config_file_observations(
            "src/main/resources/bad-dangerous.xml",
            """<?xml version="1.0"?>
<!DOCTYPE beans [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<beans><bean id="bad">&xxe;</bean></beans>
""",
        )

        result = canonicalize_observations((*observations, *unsafe))
        payload = result.to_dict()
        node_keys = {node["canonical_key"] for node in payload["nodes"]}
        edge_triples = {
            (edge["source_key"], edge["kind"], edge["target_key"])
            for edge in payload["edges"]
        }

        self.assertTrue(result.ok)
        self.assertIn(
            "xml.document:file%3Asrc%2Fmain%2Fresources%2FapplicationContext.xml",
            node_keys,
        )
        self.assertIn(
            (
                "xml.element:"
                "file%3Asrc%2Fmain%2Fresources%2FapplicationContext.xml:"
                "%2Fbeans%2Fbean"
            ),
            node_keys,
        )
        self.assertIn(
            (
                "xml.attribute:"
                "file%3Asrc%2Fmain%2Fresources%2FapplicationContext.xml:"
                "%2Fbeans%2Fbean:class"
            ),
            node_keys,
        )
        self.assertIn(
            (
                "file:src/main/resources/applicationContext.xml",
                "defines",
                (
                    "xml.document:"
                    "file%3Asrc%2Fmain%2Fresources%2FapplicationContext.xml"
                ),
            ),
            edge_triples,
        )
        self.assertIn(
            (
                (
                    "xml.attribute:"
                    "file%3Asrc%2Fmain%2Fresources%2FapplicationContext.xml:"
                    "%2Fbeans%2Fbean%2Fproperty:value"
                ),
                "references",
                "file:src/main/resources/config/service.properties",
            ),
            edge_triples,
        )
        self.assertNotIn(
            "xml.document:file%3Asrc%2Fmain%2Fresources%2Fbad-dangerous.xml",
            node_keys,
        )

    def test_generic_xml_parse_error_is_raw_only(self):
        observations = extract_config_file_observations(
            "src/main/resources/bad.xml",
            "<beans><bean></beans>",
        )

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["nodes"], 0)
        self.assertEqual(payload["summary"]["edges"], 0)
        self.assertEqual(payload["summary"]["evidence"], 1)
        self.assertEqual(payload["evidence"][0]["raw_kind"], "xml.parse_error")

    def test_generic_xml_definition_diagnostics_reject_bad_identity_metadata(self):
        observations = [
            RawObservation(
                kind="xml.document",
                source_id="bad-abs.xml#xml-document",
                path="/absolute/bad.xml",
                target="xml.document:file%3Abad.xml",
                confidence="extracted",
                extractor="repo-config",
                extractor_version="0.1.0",
                metadata={"format": "xml"},
            ),
            RawObservation(
                kind="xml.element",
                source_id="bad.xml#xml-element",
                path="bad.xml",
                target="xml.element:file%3Abad.xml:%2Fbad",
                confidence="extracted",
                extractor="repo-config",
                extractor_version="0.1.0",
                metadata={"format": "xml"},
            ),
            RawObservation(
                kind="xml.attribute",
                source_id="bad.xml#xml-attribute",
                path="bad.xml",
                target="xml.attribute:file%3Abad.xml:%2Fbad:value",
                confidence="extracted",
                extractor="repo-config",
                extractor_version="0.1.0",
                metadata={"format": "xml", "element_pointer": "/bad"},
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["summary"]["nodes"], 0)
        self.assertEqual(payload["summary"]["edges"], 0)
        self.assertEqual(payload["summary"]["errors"], 3)
        self.assertEqual(
            {diagnostic["category"] for diagnostic in payload["diagnostics"]},
            {"invalid_canonical_key"},
        )

    def test_generic_xml_reference_diagnostics_reject_bad_sources(self):
        observations = [
            RawObservation(
                kind="xml.reference",
                source_id="bad.xml#xml-reference:missing",
                path="bad.xml",
                target="file:target.xml",
                confidence="heuristic",
                extractor="repo-config",
                extractor_version="0.1.0",
                metadata={"format": "xml"},
            ),
            RawObservation(
                kind="xml.reference",
                source_id="bad.xml#xml-reference:file-source",
                path="bad.xml",
                target="file:target.xml",
                confidence="heuristic",
                extractor="repo-config",
                extractor_version="0.1.0",
                metadata={"format": "xml", "source_key": "file:bad.xml"},
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["summary"]["nodes"], 0)
        self.assertEqual(payload["summary"]["edges"], 0)
        self.assertEqual(payload["summary"]["errors"], 2)
        self.assertEqual(
            [diagnostic["field"] for diagnostic in payload["diagnostics"]],
            ["target", "target"],
        )

    def test_generic_xml_reference_bad_targets_use_unknown_placeholders(self):
        observations = [
            RawObservation(
                kind="xml.reference",
                source_id="settings.xml#xml-reference:missing-target",
                path="settings.xml",
                confidence="heuristic",
                extractor="repo-config",
                extractor_version="0.1.0",
                metadata={
                    "format": "xml",
                    "source_key": "xml.element:file%3Asettings.xml:%2Fsettings",
                    "element_pointer": "/settings",
                    "source_kind": "element",
                },
            ),
            RawObservation(
                kind="xml.reference",
                source_id="settings.xml#xml-reference:malformed-target",
                path="settings.xml",
                target="not a canonical key",
                confidence="heuristic",
                extractor="repo-config",
                extractor_version="0.1.0",
                metadata={
                    "format": "xml",
                    "source_key": "xml.attribute:file%3Asettings.xml:%2Fsettings%2Fpath:value",
                    "element_pointer": "/settings/path",
                    "attribute_name": "value",
                    "source_kind": "attribute",
                },
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["warnings"], 2)
        self.assertEqual(payload["summary"]["edges"], 2)
        self.assertEqual(
            {edge["target_key"] for edge in payload["edges"]},
            {"unknown:xml.reference:missing-target", "unknown:xml.reference:malformed-target"},
        )
        self.assertEqual(
            [diagnostic["field"] for diagnostic in payload["diagnostics"]],
            ["target", "target"],
        )
