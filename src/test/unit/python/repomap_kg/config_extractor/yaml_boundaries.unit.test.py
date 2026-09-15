import unittest
from unittest.mock import patch

from repomap_kg.extractors.config.generic import extract_config_file_observations
from repomap_kg.extractors.config import yaml as config_yaml


class ConfigExtractorYamlBoundariesUnitTests(unittest.TestCase):
    def test_yaml_documents_multi_doc_and_ellipsis_separators(self):
        observations = extract_config_file_observations(
            "config.yaml",
            """---
first: 1
...
---
second: 2
...
""",
        )
        self.assertEqual(observations[0].kind, "config.document")
        pointers = {obs.metadata.get("pointer") for obs in observations if obs.kind == "config.path"}
        self.assertIn("/documents/0/first", pointers)
        self.assertIn("/documents/1/second", pointers)

    def test_yaml_duplicate_key_in_item_mapping_raises_parse_error(self):
        observations = extract_config_file_observations(
            "invalid.yaml",
            """
items:
  - key: one
    key: two
""",
        )
        errors = [obs for obs in observations if obs.kind == "config.parse_error"]
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].metadata["error_kind"], "duplicate-yaml-key")

    def test_yaml_tab_indentation_raises_parse_error(self):
        observations = extract_config_file_observations(
            "tab.yaml",
            "\tkey: value\n",
        )
        errors = [obs for obs in observations if obs.kind == "config.parse_error"]
        self.assertEqual(len(errors), 1)
        self.assertIn("tabs are not supported", errors[0].metadata["message_summary"])

    def test_yaml_conservative_limits_emit_bounded_parse_errors(self):
        with patch.object(config_yaml, "_yaml_max_file_bytes", return_value=10):
            obs = extract_config_file_observations("limit.yaml", "key: value_exceeding_ten_bytes")
            errors = [o for o in obs if o.kind == "config.parse_error"]
            self.assertEqual(len(errors), 1)
            self.assertEqual(errors[0].metadata["error_kind"], "yaml-file-byte-limit")

        with patch.object(config_yaml, "_yaml_max_documents", return_value=1):
            obs = extract_config_file_observations("limit.yaml", "---\na: 1\n---\nb: 2\n")
            errors = [o for o in obs if o.kind == "config.parse_error"]
            self.assertEqual(len(errors), 1)
            self.assertEqual(errors[0].metadata["error_kind"], "yaml-document-count-limit")

        with patch.object(config_yaml, "_yaml_max_depth", return_value=1):
            obs = extract_config_file_observations("limit.yaml", "a:\n  b:\n    c: 1\n")
            errors = [o for o in obs if o.kind == "config.parse_error"]
            self.assertEqual(len(errors), 1)
            self.assertEqual(errors[0].metadata["error_kind"], "yaml-depth-limit")

        with patch.object(config_yaml, "_yaml_max_nodes", return_value=1):
            obs = extract_config_file_observations("limit.yaml", "a: 1\nb: 2\nc: 3\n")
            errors = [o for o in obs if o.kind == "config.parse_error"]
            self.assertEqual(len(errors), 1)
            self.assertEqual(errors[0].metadata["error_kind"], "yaml-node-count-limit")

        with patch.object(config_yaml, "_yaml_max_nodes", return_value=1):
            obs = extract_config_file_observations("limit.yaml", "- item1\n- item2\n- item3\n")
            errors = [o for o in obs if o.kind == "config.parse_error"]
            self.assertEqual(len(errors), 1)
            self.assertEqual(errors[0].metadata["error_kind"], "yaml-node-count-limit")

    def test_yaml_unexpected_indentation_and_structure_errors(self):
        obs = extract_config_file_observations(
            "bad_indent.yaml",
            """
root:
    child: 1
   bad: 2
""",
        )
        errors = [o for o in obs if o.kind == "config.parse_error"]
        self.assertEqual(len(errors), 1)
        self.assertIn("unexpected YAML indentation", errors[0].metadata["message_summary"])

        seq_bad_indent = extract_config_file_observations(
            "bad_seq.yaml",
            """
items:
  - one
   - two
""",
        )
        seq_errors = [o for o in seq_bad_indent if o.kind == "config.parse_error"]
        self.assertEqual(len(seq_errors), 1)

    def test_yaml_sequence_and_mapping_edge_syntax(self):
        obs = extract_config_file_observations(
            "complex.yaml",
            """
items:
  - nested: true
  - "quoted string"
  - 123
mapping:
  empty_key: ""
  nested_key:
    sub: 1
""",
        )
        self.assertEqual(obs[0].kind, "config.document")


if __name__ == "__main__":
    unittest.main()
