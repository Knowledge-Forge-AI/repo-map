import json
import unittest


from repomap_kg.canonicalization import canonicalize_observations
from repomap_kg.extractors.config.generic import extract_config_file_observations
from repomap_kg.observations import RawObservation


class CanonicalXmlConfigIntegrationTests(unittest.TestCase):
    def test_plist_xml_config_extraction_and_canonicalization_contract(self):
        observations = extract_config_file_observations(
            "chrome-policy.plist",
            """<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0">
  <dict>
    <key>HomepageLocation</key>
    <string>https://example.com/home</string>
    <key>PolicyPath</key>
    <string>managed/policy.json</string>
    <key>ManagedBookmarks</key>
    <array>
      <dict>
        <key>name</key>
        <string>Docs</string>
        <key>url</key>
        <string>https://example.com/docs</string>
      </dict>
      <dict>
        <key>id</key>
        <string>LocalHelp</string>
        <key>path</key>
        <string>managed/policy.json</string>
      </dict>
    </array>
    <key>AnonymousRules</key>
    <array>
      <dict>
        <key>url</key>
        <string>https://example.com/anonymous</string>
      </dict>
    </array>
    <key>api_key</key>
    <string>xml1-contract-secret</string>
  </dict>
</plist>
""",
        )
        unsafe = extract_config_file_observations(
            "dangerous.plist",
            """<?xml version="1.0"?>
<!DOCTYPE plist [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<plist><dict><key>Bad</key><string>&xxe;</string></dict></plist>
""",
        )

        serialized = json.dumps(
            [observation.to_dict() for observation in (*observations, *unsafe)],
            sort_keys=True,
        )
        paths = [item for item in observations if item.kind == "config.path"]
        references = [item for item in observations if item.kind == "config.reference"]
        pointers = {item.metadata["pointer"] for item in paths}
        pointer_by_path = {item.metadata["pointer"]: item for item in paths}
        result = canonicalize_observations((*observations, *unsafe))
        payload = result.to_dict()

        self.assertNotIn("xml1-contract-secret", serialized)
        self.assertNotIn("file:///etc/passwd", serialized)
        self.assertEqual(observations[0].metadata["format"], "plist-xml")
        self.assertEqual(observations[0].metadata["document_role"], "chrome-policy")
        self.assertEqual(unsafe[0].metadata["error_kind"], "unsafe-xml-construct")
        self.assertEqual(
            pointer_by_path["/ManagedBookmarks"].metadata["array_policy"],
            "stable-member-key",
        )
        self.assertEqual(
            pointer_by_path["/AnonymousRules"].metadata["array_policy"],
            "summary-only",
        )
        self.assertIn("/ManagedBookmarks/Docs/url", pointers)
        self.assertIn("/ManagedBookmarks/LocalHelp/path", pointers)
        self.assertNotIn("/ManagedBookmarks/0/url", pointers)
        self.assertNotIn("/AnonymousRules/0/url", pointers)
        self.assertIn("file:managed/policy.json", {item.target for item in references})
        self.assertIn(
            "external.url:https%3A%2F%2Fexample.com%2Fhome",
            {item.target for item in references},
        )
        self.assertTrue(result.ok)
        edge_tuples = {(edge["source_key"], edge["kind"], edge["target_key"]) for edge in payload["edges"]}
        self.assertIn(
            ("file:chrome-policy.plist", "defines", "config.document:file%3Achrome-policy.plist"),
            edge_tuples,
        )
        self.assertIn(
            ("config.path:file%3Achrome-policy.plist:%2FPolicyPath", "references", "file:managed/policy.json"),
            edge_tuples,
        )
        self.assertNotIn(
            "config.document:file%3Adangerous.plist",
            {node["canonical_key"] for node in payload["nodes"]},
        )

    def test_generic_xml_extraction_and_canonicalization_contract(self):
        observations = extract_config_file_observations(
            "src/main/resources/applicationContext.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<beans xmlns="http://www.springframework.org/schema/beans"
       xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
       xsi:schemaLocation="http://www.springframework.org/schema/beans https://www.springframework.org/schema/beans/spring-beans.xsd">
  <bean id="service" class="com.example.Service">
    <property name="configPath" value="./config/service.properties"/>
    <property name="jdbcUrl" value="${db.url}"/>
    <property name="DB_PASSWORD" value="${env.DB_PASSWORD}"/>
    <property name="api_key" value="xml2-contract-secret"/>
  </bean>
  <bean id="repository" class="com.example.Repository"/>
</beans>
""",
        )
        pom_observations = extract_config_file_observations(
            "pom.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>xml-smoke</artifactId>
  <version>1.0.0</version>
  <dependencies>
    <dependency>
      <groupId>org.springframework</groupId>
      <artifactId>spring-context</artifactId>
      <version>${spring.version}</version>
    </dependency>
  </dependencies>
</project>
""",
        )
        unsafe = extract_config_file_observations(
            "dangerous.xml",
            """<?xml version="1.0"?>
<!DOCTYPE beans [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<beans><bean id="bad">&xxe;</bean></beans>
""",
        )

        serialized = json.dumps(
            [
                observation.to_dict()
                for observation in (*observations, *pom_observations, *unsafe)
            ],
            sort_keys=True,
        )
        kinds = {item.kind for item in (*observations, *pom_observations)}
        result = canonicalize_observations(
            (*observations, *pom_observations, *unsafe)
        )
        payload = result.to_dict()

        self.assertNotIn("xml2-contract-secret", serialized)
        self.assertNotIn("file:///etc/passwd", serialized)
        self.assertTrue(
            {
                "xml.document",
                "xml.element",
                "xml.attribute",
                "xml.reference",
            }.issubset(kinds)
        )
        self.assertEqual(observations[0].metadata["document_role"], "spring-config")
        self.assertEqual(pom_observations[0].metadata["document_role"], "maven-pom")
        self.assertEqual(unsafe[0].kind, "xml.parse_error")
        self.assertEqual(unsafe[0].metadata["error_kind"], "unsafe-xml-construct")

        nodes = {node["canonical_key"]: node for node in payload["nodes"]}
        edges = {(edge["source_key"], edge["kind"], edge["target_key"]) for edge in payload["edges"]}
        self.assertIn("xml.document:file%3Asrc%2Fmain%2Fresources%2FapplicationContext.xml", nodes)
        dep_node = "xml.element:file%3Apom.xml:%2Fproject%2Fdependencies%2Fdependency"
        self.assertIn(dep_node, nodes)
        self.assertEqual(nodes[dep_node]["metadata"]["maven_group_id"], "org.springframework")
        self.assertIn(("file:src/main/resources/applicationContext.xml", "defines", "xml.document:file%3Asrc%2Fmain%2Fresources%2FapplicationContext.xml"), edges)
        self.assertIn(("xml.attribute:file%3Asrc%2Fmain%2Fresources%2FapplicationContext.xml:%2Fbeans%2Fbean%2Fproperty:value", "references", "file:src/main/resources/config/service.properties"), edges)
        self.assertIn(("xml.element:file%3Apom.xml:%2Fproject%2Fdependencies%2Fdependency%2Fversion", "references", "dynamic:xml.property-placeholder:spring-maven-property"), edges)
        self.assertNotIn("xml.document:file%3Adangerous.xml", nodes)

    def test_generic_xml_reference_and_diagnostic_contracts(self):
        observations = extract_config_file_observations(
            "src/main/resources/paths.xml",
            """<?xml version="1.0"?>
<settings>
  <path value="../../../../outside.properties"/>
  <path value="/Library/Application Support/config.xml"/>
  <path value="${CONFIG_DIR}/app.xml"/>
  <url>mailto:dev@example.com</url>
  <env>${env.SERVICE_TOKEN}</env>
</settings>
""",
        )
        malformed = extract_config_file_observations(
            "src/main/resources/bad.xml",
            "<settings><path></settings>",
        )
        def _diag_obs(
            kind: str,
            sid: str,
            path: str,
            target: str | None = None,
            conf: str = "extracted",
            meta: dict[str, str] | None = None,
        ) -> RawObservation:
            return RawObservation(
                kind=kind,
                source_id=sid,
                path=path,
                target=target,
                confidence=conf,
                extractor="repo-config",
                extractor_version="0.1.0",
                metadata=meta or {"format": "xml"},
            )

        diagnostic_observations = [
            _diag_obs("xml.document", "bad-abs.xml#xml-document", "/absolute/bad.xml", target="xml.document:file%3Abad.xml"),
            _diag_obs("xml.element", "bad.xml#xml-element", "bad.xml", target="xml.element:file%3Abad.xml:%2Fbad"),
            _diag_obs("xml.attribute", "bad.xml#xml-attribute", "bad.xml", target="xml.attribute:file%3Abad.xml:%2Fbad:value", meta={"format": "xml", "element_pointer": "/bad"}),
            _diag_obs("xml.reference", "settings.xml#xml-reference:missing-source", "settings.xml", target="file:target.xml", conf="heuristic"),
            _diag_obs("xml.reference", "settings.xml#xml-reference:file-source", "settings.xml", target="file:target.xml", conf="heuristic", meta={"format": "xml", "source_key": "file:settings.xml"}),
            _diag_obs("xml.reference", "settings.xml#xml-reference:missing-target", "settings.xml", conf="heuristic", meta={"format": "xml", "source_key": "xml.element:file%3Asettings.xml:%2Fsettings", "element_pointer": "/settings", "source_kind": "element"}),
            _diag_obs("xml.reference", "settings.xml#xml-reference:malformed-target", "settings.xml", target="not a canonical key", conf="heuristic", meta={"format": "xml", "source_key": "xml.attribute:file%3Asettings.xml:%2Fsettings%2Fpath:value", "element_pointer": "/settings/path", "attribute_name": "value", "source_kind": "attribute"}),
        ]

        targets = {
            observation.target
            for observation in observations
            if observation.kind == "xml.reference"
        }
        result = canonicalize_observations(
            (*observations, *malformed, *diagnostic_observations)
        )
        payload = result.to_dict()

        self.assertIn("unknown:file:repo-escaping-xml-reference", targets)
        self.assertIn("external:file:absolute-xml-reference", targets)
        self.assertIn("dynamic:file:xml-reference-expanded-from-variable", targets)
        self.assertIn("external.url:mailto%3Adev%40example.com", targets)
        self.assertIn("env:SERVICE_TOKEN", targets)
        self.assertFalse(result.ok)
        self.assertGreaterEqual(payload["summary"]["warnings"], 2)
        self.assertGreaterEqual(payload["summary"]["errors"], 5)
        self.assertIn(
            "unknown:xml.reference:missing-target",
            {edge["target_key"] for edge in payload["edges"]},
        )
        self.assertIn(
            "unknown:xml.reference:malformed-target",
            {edge["target_key"] for edge in payload["edges"]},
        )
        self.assertNotIn(
            "xml.document:file%3Asrc%2Fmain%2Fresources%2Fbad.xml",
            {node["canonical_key"] for node in payload["nodes"]},
        )

    def test_generic_xml_element_text_references_are_canonicalized(self):
        observations = extract_config_file_observations(
            "src/main/resources/settings.xml",
            """<?xml version="1.0"?>
<settings>
  <configPath>config/local.xml</configPath>
  <dotRelativePath>./config/local-dot.xml</dotRelativePath>
  <absolutePath>/Library/Application Support/app.xml</absolutePath>
  <templatePath>${CONFIG_DIR}/app.xml</templatePath>
  <supportUrl>mailto:support@example.com</supportUrl>
</settings>
""",
        )
        processing_instruction = extract_config_file_observations(
            "src/main/resources/stylesheet.xml",
            """<?xml version="1.0"?>
<?xml-stylesheet href="https://example.com/style.xsl" type="text/xsl"?>
<settings/>
""",
        )

        result = canonicalize_observations((*observations, *processing_instruction))
        payload = result.to_dict()
        reference_edges = [
            edge for edge in payload["edges"] if edge["kind"] == "references"
        ]

        self.assertTrue(result.ok)
        self.assertEqual([item.kind for item in processing_instruction], ["xml.parse_error"])
        self.assertTrue(
            all(edge["source_key"].startswith("xml.element:") for edge in reference_edges)
        )
        self.assertIn(
            "file:config/local.xml",
            {edge["target_key"] for edge in reference_edges},
        )
        self.assertIn(
            "file:src/main/resources/config/local-dot.xml",
            {edge["target_key"] for edge in reference_edges},
        )
        self.assertIn(
            "external:file:absolute-xml-reference",
            {edge["target_key"] for edge in reference_edges},
        )
        self.assertIn(
            "dynamic:file:xml-reference-expanded-from-variable",
            {edge["target_key"] for edge in reference_edges},
        )
        self.assertIn(
            "external.url:mailto%3Asupport%40example.com",
            {edge["target_key"] for edge in reference_edges},
        )

    def test_plist_xml_error_and_scalar_contracts(self):
        scalar_observations = extract_config_file_observations(
            "typed.plist",
            """<?xml version="1.0" encoding="UTF-8"?>
<plist xmlns="urn:fixture" version="1.0">
  <dict>
    <key>MaxConnections</key>
    <integer>25</integer>
    <key>Ratio</key>
    <real>1.5</real>
    <key>Enabled</key>
    <true/>
    <key>Disabled</key>
    <false/>
    <key>PolicyDate</key>
    <date>2026-06-30T00:00:00Z</date>
    <key>Blob</key>
    <data>QUJD</data>
  </dict>
</plist>
""",
        )
        malformed = extract_config_file_observations(
            "malformed.plist",
            "<plist><dict><key>MissingEnd</key><string>oops</dict></plist>",
        )
        unsupported = extract_config_file_observations(
            "unsupported.plist",
            "<plist><dict><key>Bad</key><unknown/></dict></plist>",
        )
        bad_processing_instruction = extract_config_file_observations(
            "processing-instruction.plist",
            """<?xml version="1.0"?>
<?xml-stylesheet href="https://example.com/style.xsl" type="text/xsl"?>
<plist><dict/></plist>
""",
        )

        paths = {
            item.metadata["pointer"]: item
            for item in scalar_observations
            if item.kind == "config.path"
        }

        self.assertEqual(scalar_observations[0].metadata["format"], "plist-xml")
        self.assertEqual(paths["/MaxConnections"].metadata["value_summary"], 25)
        self.assertEqual(paths["/Ratio"].metadata["value_summary"], 1.5)
        self.assertEqual(paths["/Enabled"].metadata["value_type"], "boolean")
        self.assertEqual(paths["/Enabled"].metadata["value_summary"], True)
        self.assertEqual(paths["/Disabled"].metadata["value_summary"], False)
        self.assertEqual(
            paths["/PolicyDate"].metadata["value_summary"],
            "2026-06-30T00:00:00Z",
        )
        self.assertEqual(paths["/Blob"].metadata["value_summary"], "QUJD")
        self.assertEqual([item.kind for item in malformed], ["config.parse_error"])
        self.assertEqual(
            malformed[0].metadata["error_kind"],
            "malformed-plist-xml",
        )
        self.assertEqual([item.kind for item in unsupported], ["config.parse_error"])
        self.assertEqual(
            unsupported[0].metadata["error_kind"],
            "unsupported-plist-shape",
        )
        self.assertEqual(
            bad_processing_instruction[0].metadata["error_kind"],
            "unsafe-xml-construct",
        )
