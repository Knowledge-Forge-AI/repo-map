import json
import unittest


from repomap_kg.extractors.config.generic import (
    extract_config_file_observations,
)


class ConfigExtractorPlistXmlUnitTests(unittest.TestCase):
    def test_plist_document_paths_references_and_redaction(self):
        observations = extract_config_file_observations(
            "chrome-policy.plist",
            """<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0">
  <dict>
    <key>HomepageLocation</key>
    <string>https://example.com/home</string>
    <key>PolicyPath</key>
    <string>./managed/policy.json</string>
    <key>Environment</key>
    <dict>
      <key>CHROME_POLICY_HOME</key>
      <string>$CHROME_POLICY_HOME</string>
    </dict>
    <key>api_key</key>
    <string>plist-secret-value</string>
  </dict>
</plist>
""",
        )

        payload = json.dumps(
            [observation.to_dict() for observation in observations],
            sort_keys=True,
        )
        paths = [item for item in observations if item.kind == "config.path"]
        references = [item for item in observations if item.kind == "config.reference"]
        pointer_by_path = {item.metadata["pointer"]: item for item in paths}

        self.assertNotIn("plist-secret-value", payload)
        self.assertEqual(observations[0].kind, "config.document")
        self.assertEqual(observations[0].metadata["format"], "plist-xml")
        self.assertEqual(observations[0].metadata["parser"], "stdlib-elementtree-safe")
        self.assertEqual(observations[0].metadata["document_role"], "chrome-policy")
        self.assertEqual(
            observations[0].metadata["safety_mode"],
            "pre-scan-no-doctype-entity-no-external-resources",
        )
        self.assertIn("/HomepageLocation", pointer_by_path)
        self.assertIn("/Environment/CHROME_POLICY_HOME", pointer_by_path)
        self.assertTrue(pointer_by_path["/api_key"].metadata["redacted"])
        self.assertNotIn("value_summary", pointer_by_path["/api_key"].metadata)
        self.assertIn(
            "external.url:https%3A%2F%2Fexample.com%2Fhome",
            {item.target for item in references},
        )
        self.assertIn("file:managed/policy.json", {item.target for item in references})
        self.assertIn("env:CHROME_POLICY_HOME", {item.target for item in references})

    def test_plist_arrays_use_summary_or_stable_member_identity_without_indexes(self):
        observations = extract_config_file_observations(
            "policies/chrome-policy.plist",
            """<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0">
  <dict>
    <key>ExtensionInstallForcelist</key>
    <array>
      <string>abcdefghijklmnopabcdefghijklmnop;https://example.com/update.xml</string>
    </array>
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
        <string>../docs/help.html</string>
      </dict>
    </array>
    <key>AnonymousRules</key>
    <array>
      <dict>
        <key>url</key>
        <string>https://example.com/anonymous</string>
      </dict>
    </array>
  </dict>
</plist>
""",
        )

        paths = [item for item in observations if item.kind == "config.path"]
        pointers = {item.metadata["pointer"] for item in paths}
        references = [item for item in observations if item.kind == "config.reference"]
        install_list = next(
            item for item in paths if item.metadata["pointer"] == "/ExtensionInstallForcelist"
        )
        bookmarks = next(
            item for item in paths if item.metadata["pointer"] == "/ManagedBookmarks"
        )
        anonymous = next(
            item for item in paths if item.metadata["pointer"] == "/AnonymousRules"
        )

        self.assertEqual(install_list.metadata["array_policy"], "summary-only")
        self.assertEqual(bookmarks.metadata["array_policy"], "stable-member-key")
        self.assertEqual(anonymous.metadata["array_policy"], "summary-only")
        self.assertIn("/ManagedBookmarks/Docs/url", pointers)
        self.assertIn("/ManagedBookmarks/LocalHelp/path", pointers)
        self.assertNotIn("/ManagedBookmarks/0/url", pointers)
        self.assertNotIn("/AnonymousRules/0/url", pointers)
        self.assertIn(
            "external.url:https%3A%2F%2Fexample.com%2Fdocs",
            {item.target for item in references},
        )
        self.assertIn("file:docs/help.html", {item.target for item in references})

    def test_plist_reference_placeholders_are_conservative(self):
        observations = extract_config_file_observations(
            "policies/chrome-policy.plist",
            """<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0">
  <dict>
    <key>OutsidePath</key>
    <string>../../outside.json</string>
    <key>AbsolutePath</key>
    <string>/Library/Managed Preferences/com.google.Chrome.plist</string>
    <key>DynamicPath</key>
    <string>${POLICY_DIR}/chrome.json</string>
  </dict>
</plist>
""",
        )

        references = [item for item in observations if item.kind == "config.reference"]

        self.assertIn(
            "unknown:file:repo-escaping-config-reference",
            {item.target for item in references},
        )
        self.assertIn(
            "external:file:absolute-config-reference",
            {item.target for item in references},
        )
        self.assertIn(
            "dynamic:file:config-reference-expanded-from-variable",
            {item.target for item in references},
        )

    def test_plist_malformed_and_unsafe_xml_emit_parse_errors(self):
        malformed = extract_config_file_observations(
            "bad.plist",
            "<plist><dict><key>MissingValue</key></dict></plist>",
        )
        unsafe = extract_config_file_observations(
            "dangerous.plist",
            """<?xml version="1.0"?>
<!DOCTYPE plist [
  <!ENTITY xxe SYSTEM "file:///etc/passwd">
]>
<plist><dict><key>Bad</key><string>&xxe;</string></dict></plist>
""",
        )
        processing_instruction = extract_config_file_observations(
            "stylesheet.plist",
            """<?xml version="1.0"?>
<?xml-stylesheet href="https://example.com/style.xsl" type="text/xsl"?>
<plist><dict/></plist>
""",
        )

        self.assertEqual([item.kind for item in malformed], ["config.parse_error"])
        self.assertEqual(
            malformed[0].metadata["error_kind"],
            "unsupported-plist-shape",
        )
        self.assertEqual([item.kind for item in unsafe], ["config.parse_error"])
        self.assertEqual(unsafe[0].metadata["error_kind"], "unsafe-xml-construct")
        self.assertNotIn("file:///etc/passwd", unsafe[0].metadata["message_summary"])
        self.assertEqual(
            processing_instruction[0].metadata["error_kind"],
            "unsafe-xml-construct",
        )

    def test_generic_xml_extracts_spring_structure_references_and_redacts(self):
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
    <property name="api_key" value="spring-secret-value"/>
    <constructor-arg ref="repository"/>
  </bean>
  <bean id="repository" class="com.example.Repository"/>
</beans>
""",
        )
        plist_xml = extract_config_file_observations(
            "policies/chrome-policy.xml",
            "<plist><dict><key>HomepageLocation</key><string>https://example.com</string></dict></plist>",
        )

        payload = json.dumps(
            [observation.to_dict() for observation in observations],
            sort_keys=True,
        )
        kinds = [item.kind for item in observations]
        document = observations[0]
        elements = [item for item in observations if item.kind == "xml.element"]
        attributes = [item for item in observations if item.kind == "xml.attribute"]
        references = [item for item in observations if item.kind == "xml.reference"]
        element_by_pointer = {item.metadata["xml_pointer"]: item for item in elements}
        attr_by_pointer_name = {
            (item.metadata["element_pointer"], item.metadata["attribute_name"]): item
            for item in attributes
        }

        self.assertNotIn("spring-secret-value", payload)
        self.assertEqual(document.kind, "xml.document")
        self.assertEqual(document.metadata["format"], "xml")
        self.assertEqual(document.metadata["document_role"], "spring-config")
        self.assertEqual(document.metadata["root_local_name"], "beans")
        self.assertIn("xml.document", kinds)
        self.assertIn("xml.element", kinds)
        self.assertIn("xml.attribute", kinds)
        self.assertIn("xml.reference", kinds)
        self.assertIn("/beans/bean", element_by_pointer)
        self.assertIn("/beans/bean[2]", element_by_pointer)
        self.assertEqual(
            element_by_pointer["/beans/bean"].metadata["role_hint"],
            "spring-bean",
        )
        self.assertEqual(element_by_pointer["/beans/bean"].metadata["bean_id"], "service")
        self.assertEqual(
            element_by_pointer["/beans/bean"].metadata["class_name"],
            "com.example.Service",
        )
        self.assertEqual(
            attr_by_pointer_name[("/beans/bean/property[4]", "value")].metadata[
                "redacted"
            ],
            True,
        )
        self.assertNotIn(
            "value_summary",
            attr_by_pointer_name[("/beans/bean/property[4]", "value")].metadata,
        )
        self.assertIn(
            "external.url:https%3A%2F%2Fwww.springframework.org%2Fschema%2Fbeans%2Fspring-beans.xsd",
            {item.target for item in references},
        )
        self.assertIn("file:src/main/resources/config/service.properties", {item.target for item in references})
        self.assertIn("env:DB_PASSWORD", {item.target for item in references})
        self.assertIn("dynamic:xml.property-placeholder:spring-maven-property", {item.target for item in references})
        self.assertEqual(plist_xml[0].kind, "config.document")
        self.assertEqual(plist_xml[0].metadata["format"], "plist-xml")

    def test_generic_xml_extracts_maven_metadata_and_safety_errors(self):
        pom_observations = extract_config_file_observations(
            "pom.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>demo</artifactId>
  <version>${revision}</version>
  <properties>
    <revision>1.0.0</revision>
    <api.token>maven-secret-value</api.token>
  </properties>
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
            "src/main/resources/bad-dangerous.xml",
            """<?xml version="1.0"?>
<!DOCTYPE beans [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<beans><bean id="bad">&xxe;</bean></beans>
""",
        )
        malformed = extract_config_file_observations(
            "src/main/resources/bad.xml",
            "<beans><bean></beans>",
        )

        payload = json.dumps(
            [observation.to_dict() for observation in pom_observations],
            sort_keys=True,
        )
        document = pom_observations[0]
        elements = [item for item in pom_observations if item.kind == "xml.element"]
        references = [item for item in pom_observations if item.kind == "xml.reference"]
        dependency = next(
            item
            for item in elements
            if item.metadata["xml_pointer"] == "/project/dependencies/dependency"
        )

        self.assertNotIn("maven-secret-value", payload)
        self.assertEqual(document.metadata["document_role"], "maven-pom")
        self.assertEqual(dependency.metadata["role_hint"], "maven-dependency")
        self.assertEqual(dependency.metadata["maven_group_id"], "org.springframework")
        self.assertEqual(dependency.metadata["maven_artifact_id"], "spring-context")
        self.assertEqual(dependency.metadata["maven_version"], "${spring.version}")
        self.assertIn(
            "external.url:https%3A%2F%2Fmaven.apache.org%2Fxsd%2Fmaven-4.0.0.xsd",
            {item.target for item in references},
        )
        self.assertIn(
            "dynamic:xml.property-placeholder:spring-maven-property",
            {item.target for item in references},
        )
        self.assertEqual([item.kind for item in unsafe], ["xml.parse_error"])
        self.assertEqual(unsafe[0].metadata["error_kind"], "unsafe-xml-construct")
        self.assertNotIn("file:///etc/passwd", unsafe[0].metadata["message_summary"])
        self.assertEqual([item.kind for item in malformed], ["xml.parse_error"])
        self.assertEqual(malformed[0].metadata["error_kind"], "malformed-xml")

    def test_generic_xml_classifies_conservative_reference_targets(self):
        observations = extract_config_file_observations(
            "src/main/resources/paths.xml",
            """<?xml version="1.0"?>
<settings>
  <path value="../../../../outside.properties"/>
  <path value="/Library/Application Support/config.xml"/>
  <path value="${CONFIG_DIR}/app.xml"/>
  <path value="~/Library/config.xml"/>
  <path value="*.xml"/>
  <url>mailto:dev@example.com</url>
  <env>${env.SERVICE_TOKEN}</env>
</settings>
""",
        )

        references = [item for item in observations if item.kind == "xml.reference"]
        targets = {item.target for item in references}
        reference_by_target = {item.target: item for item in references}

        self.assertIn("unknown:file:repo-escaping-xml-reference", targets)
        self.assertIn("external:file:absolute-xml-reference", targets)
        self.assertIn("dynamic:file:xml-reference-expanded-from-variable", targets)
        self.assertIn(
            "external.url:mailto%3Adev%40example.com",
            targets,
        )
        self.assertIn("env:SERVICE_TOKEN", targets)
        self.assertEqual(
            reference_by_target[
                "unknown:file:repo-escaping-xml-reference"
            ].metadata["reference_kind"],
            "unknown",
        )

    def test_generic_xml_processing_instruction_is_safety_error(self):
        observations = extract_config_file_observations(
            "src/main/resources/stylesheet.xml",
            """<?xml version="1.0"?>
<?xml-stylesheet href="https://example.com/style.xsl" type="text/xsl"?>
<beans/>
""",
        )

        self.assertEqual([item.kind for item in observations], ["xml.parse_error"])
        self.assertEqual(
            observations[0].metadata["error_kind"],
            "unsafe-xml-construct",
        )
        self.assertNotIn("https://example.com/style.xsl", observations[0].metadata)
