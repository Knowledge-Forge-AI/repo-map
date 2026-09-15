import json
import unittest

from repomap_kg.extractors.config.generic import (
    extract_config_file_observations,
)
from repomap_test_support.config_extractor import observations_format


class ConfigExtractorTomlYamlBoundariesUnitTests(unittest.TestCase):
    def test_toml_malformed_parse_error_is_raw_only(self):
        observations = extract_config_file_observations(
            "bad.toml",
            "[mcp_servers.repomap]\ncommand =\n",
        )

        self.assertEqual([item.kind for item in observations], ["config.parse_error"])
        self.assertEqual(observations[0].confidence, "unknown")
        self.assertEqual(observations[0].metadata["format"], "toml")
        self.assertEqual(observations[0].metadata["parser"], "stdlib-tomllib")
        self.assertEqual(observations[0].metadata["error_kind"], "malformed-toml")

    def test_toml_dynamic_and_unknown_references_use_placeholders(self):
        observations = extract_config_file_observations(
            "settings.toml",
            """
outside_path = "../outside.toml"
absolute_path = "/var/db/config.toml"
dynamic_path = "${PROJECT_ROOT}/config.toml"
program = "echo hello"

[env]
"${NAME}" = "value"
""",
        )

        references = [item for item in observations if item.kind == "config.reference"]
        self.assertIn("unknown:file:repo-escaping-config-reference", {item.target for item in references})
        self.assertIn("external:file:absolute-config-reference", {item.target for item in references})
        self.assertIn("dynamic:file:config-reference-expanded-from-variable", {item.target for item in references})
        self.assertIn("dynamic:tool:config-command-fragment", {item.target for item in references})
        self.assertIn("dynamic:env:dynamic-config-env-name", {item.target for item in references})

    def test_yaml_custom_tags_anchors_aliases_merge_and_duplicate_keys_are_safe(self):
        tagged = extract_config_file_observations(
            "custom-tags.yaml",
            """
defaults: &defaults
  image: example/base:1.0
service:
  <<: *defaults
  token_ref: !vault fake-vault-secret
  include_file: !include ./values-extra.yml
""",
        )
        duplicate = extract_config_file_observations(
            "duplicate-keys.yaml",
            "service: one\nservice: two\n",
        )

        payload = json.dumps(
            [observation.to_dict() for observation in tagged],
            sort_keys=True,
        )
        paths = [item for item in tagged if item.kind == "config.path"]
        references = [item for item in tagged if item.kind == "config.reference"]
        pointer_by_path = {item.metadata["pointer"]: item for item in paths}

        self.assertNotIn("fake-vault-secret", payload)
        self.assertEqual(observations_format(tagged), "yaml")
        self.assertEqual(pointer_by_path["/defaults"].metadata["anchor"], "defaults")
        self.assertTrue(pointer_by_path["/service/<<"].metadata["merge_key"])
        self.assertEqual(pointer_by_path["/service/<<"].metadata["alias"], "defaults")
        self.assertEqual(
            pointer_by_path["/service/token_ref"].metadata["yaml_tag"],
            "!vault",
        )
        self.assertTrue(pointer_by_path["/service/token_ref"].metadata["redacted"])
        self.assertIn(
            (
                "/service/include_file",
                "file:values-extra.yml",
                "file",
            ),
            {
                (item.metadata["pointer"], item.target, item.metadata["reference_kind"])
                for item in references
            },
        )
        self.assertEqual([item.kind for item in duplicate], ["config.parse_error"])
        self.assertEqual(duplicate[0].metadata["format"], "yaml")
        self.assertEqual(duplicate[0].metadata["error_kind"], "duplicate-yaml-key")
        self.assertEqual(
            duplicate[0].metadata["duplicate_key_policy"],
            "parse-error",
        )

    def test_yaml_inline_collections_nested_scalars_and_errors_are_safe(self):
        observations = extract_config_file_observations(
            "inline.yaml",
            """
empty_list: []
empty_map: {}
inline:
  values: [one, "two, too", {nested: [true, false, null, ~, -7, 3.14], quoted: 'yes'}, [inner, list]]
  mapping: {alpha: one, beta: [x, y], gamma: {nested: value}}
  trailing: [one, two,]
""",
        )
        duplicate = extract_config_file_observations(
            "inline-duplicate.yaml",
            "inline: {a: one, a: two}\n",
        )
        malformed = extract_config_file_observations(
            "inline-malformed.yaml",
            "inline: [one, {nested: bad]]\n",
        )

        paths = [item for item in observations if item.kind == "config.path"]
        pointer_by_path = {item.metadata["pointer"]: item for item in paths}

        self.assertEqual(observations_format(observations), "yaml")
        self.assertEqual(pointer_by_path["/empty_list"].metadata["value_type"], "array")
        self.assertEqual(pointer_by_path["/empty_map"].metadata["value_type"], "object")
        self.assertEqual(pointer_by_path["/inline/values"].metadata["value_type"], "array")
        self.assertEqual(pointer_by_path["/inline/mapping"].metadata["value_type"], "object")
        self.assertEqual(
            pointer_by_path["/inline/mapping/alpha"].metadata["value_summary"],
            "one",
        )
        self.assertEqual(
            pointer_by_path["/inline/mapping/gamma/nested"].metadata["value_summary"],
            "value",
        )
        self.assertEqual(pointer_by_path["/inline/trailing"].metadata["value_type"], "array")
        self.assertEqual([item.kind for item in duplicate], ["config.parse_error"])
        self.assertEqual(duplicate[0].metadata["error_kind"], "duplicate-yaml-key")
        self.assertEqual([item.kind for item in malformed], ["config.parse_error"])
        self.assertEqual(malformed[0].metadata["error_kind"], "malformed-yaml")

    def test_yaml_malformed_and_limit_errors_are_raw_only(self):
        malformed = extract_config_file_observations("bad.yaml", "name: [unterminated\n")
        too_large_scalar = extract_config_file_observations(
            "long.yaml",
            "description: " + ("x" * 5000) + "\n",
        )

        self.assertEqual([item.kind for item in malformed], ["config.parse_error"])
        self.assertEqual(malformed[0].metadata["format"], "yaml")
        self.assertEqual(malformed[0].metadata["error_kind"], "malformed-yaml")
        self.assertEqual([item.kind for item in too_large_scalar], ["config.parse_error"])
        self.assertEqual(
            too_large_scalar[0].metadata["error_kind"],
            "yaml-scalar-length-limit",
        )


if __name__ == "__main__":
    unittest.main()
