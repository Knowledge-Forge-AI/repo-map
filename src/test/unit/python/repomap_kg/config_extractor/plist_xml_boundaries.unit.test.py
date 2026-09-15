import unittest

from repomap_kg.extractors.config.generic import extract_config_file_observations


class ConfigExtractorPlistXmlBoundariesUnitTests(unittest.TestCase):
    def test_plist_malformed_root_and_dict_errors(self):
        not_plist = extract_config_file_observations(
            "Info.plist",
            """<?xml version="1.0" encoding="UTF-8"?>
<notplist>
  <dict/>
</notplist>
""",
        )
        self.assertEqual(not_plist[0].kind, "config.parse_error")

        empty_plist = extract_config_file_observations(
            "Empty.plist",
            """<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0"/>
""",
        )
        self.assertEqual(empty_plist[0].kind, "config.parse_error")

        no_key_dict = extract_config_file_observations(
            "NoKey.plist",
            """<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0">
  <dict>
    <string>no key first</string>
  </dict>
</plist>
""",
        )
        self.assertEqual(no_key_dict[0].kind, "config.parse_error")

        empty_key = extract_config_file_observations(
            "EmptyKey.plist",
            """<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0">
  <dict>
    <key>   </key>
    <string>val</string>
  </dict>
</plist>
""",
        )
        self.assertEqual(empty_key[0].kind, "config.parse_error")

        dup_keys = extract_config_file_observations(
            "DupKey.plist",
            """<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0">
  <dict>
    <key>k</key>
    <string>1</string>
    <key>k</key>
    <string>2</string>
  </dict>
</plist>
""",
        )
        self.assertEqual(dup_keys[0].kind, "config.parse_error")

        missing_val = extract_config_file_observations(
            "MissingVal.plist",
            """<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0">
  <dict>
    <key>k1</key>
    <key>k2</key>
    <string>v2</string>
  </dict>
</plist>
""",
        )
        self.assertEqual(missing_val[0].kind, "config.parse_error")

    def test_xml_maven_plugins_and_spring_bean_class_properties(self):
        pom_obs = extract_config_file_observations(
            "pom.xml",
            """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <groupId>com.example</groupId>
  <artifactId>my-app</artifactId>
  <version>1.0.0</version>
  <build>
    <plugins>
      <plugin>
        <groupId>org.apache.maven.plugins</groupId>
        <artifactId>maven-compiler-plugin</artifactId>
        <version>3.8.1</version>
      </plugin>
    </plugins>
  </build>
</project>
""",
        )
        elements = [o for o in pom_obs if o.kind == "xml.element"]
        plugin_elem = next(o for o in elements if o.metadata.get("role_hint") == "maven-plugin")
        self.assertEqual(plugin_elem.metadata["maven_group_id"], "org.apache.maven.plugins")
        self.assertEqual(plugin_elem.metadata["maven_artifact_id"], "maven-compiler-plugin")
        self.assertEqual(plugin_elem.metadata["maven_version"], "3.8.1")

        spring_obs = extract_config_file_observations(
            "beans.xml",
            """<beans xmlns="http://www.springframework.org/schema/beans">
  <bean class="com.example.AnonymousService">
    <property name="helper" ref="otherBean"/>
  </bean>
</beans>
""",
        )
        spring_elements = [o for o in spring_obs if o.kind == "xml.element"]
        bean_elem = next(o for o in spring_elements if o.metadata.get("class_name") == "com.example.AnonymousService")
        self.assertNotIn("bean_id", bean_elem.metadata)
        prop_elem = next(o for o in spring_elements if o.metadata.get("property_name") == "helper")
        self.assertEqual(prop_elem.metadata["bean_ref"], "otherBean")

    def test_xml_edge_metadata_and_parse_error_lines(self):
        obs = extract_config_file_observations(
            "pom.xml",
            """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <dependencies>
    <dependency>
      <artifactId>standalone-lib</artifactId>
    </dependency>
  </dependencies>
</project>
""",
        )
        self.assertEqual(obs[0].kind, "xml.document")

        spring_obs = extract_config_file_observations(
            "beans.xml",
            """<beans xmlns="http://www.springframework.org/schema/beans">
  <bean id="onlyId">
    <property ref="onlyRef"/>
  </bean>
</beans>
""",
        )
        self.assertEqual(spring_obs[0].kind, "xml.document")

        from repomap_kg.extractors.config.xml import _xml_parse_error_line
        import xml.etree.ElementTree as ET
        err_no_pos = ET.ParseError("err")
        self.assertIsNone(_xml_parse_error_line(err_no_pos))


if __name__ == "__main__":
    unittest.main()
