import unittest
from repomap_kg.extractors.config.generic import extract_config_file_observations
from repomap_kg.extractors.config.jsonc import (
    JsoncNormalizationError,
    normalize_jsonc,
    _strip_jsonc_comments,
)

class ConfigStructureBoundariesUnitTests(unittest.TestCase):
    def test_jsonc_strip_comments_and_trailing_commas(self):
        jsonc_text = """// Header comment
{
    /* multi-line
       comment */
    "key": "value", // line comment
    "escaped_quote": "hello \"world\"",
    "list": [1, 2, 3,],
}
"""
        normalized = normalize_jsonc(jsonc_text)
        self.assertIn('"key": "value"', normalized)
        self.assertIn('"list": [1, 2, 3]', normalized)

        with self.assertRaises(JsoncNormalizationError):
            _strip_jsonc_comments("/* unterminated comment")

    def test_generic_structure_deep_nesting_and_scalars(self):
        content = """{
    "root": {
        "level1": {
            "level2": {
                "items": ["a", "b", null, true, false, 42]
            }
        }
    }
}"""
        obs = extract_config_file_observations("nested.json", content)
        self.assertEqual(obs[0].kind, "config.document")
        kinds = {o.kind for o in obs}
        self.assertIn("config.path", kinds)

    def test_generic_structure_empty_structures(self):
        content = """{
    "empty_dict": {},
    "empty_list": [],
    "empty_string": ""
}"""
        obs = extract_config_file_observations("empty.json", content)
        self.assertEqual(obs[0].kind, "config.document")

if __name__ == "__main__":
    unittest.main()
