import unittest

from repomap_kg.canonicalization.main import (
    canonicalize_observations,
)
from repomap_kg.extractors.config.generic import extract_config_file_observations
from repomap_kg.observations.raw import RawObservation


class CanonicalizationConfigFamilyBoundariesUnitTests(unittest.TestCase):
    def test_plist_config_observations_reuse_config_canonicalization_contract(self):
        observations = extract_config_file_observations(
            "chrome-policy.plist",
            """<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0">
  <dict>
    <key>PolicyPath</key>
    <string>managed/policy.json</string>
  </dict>
</plist>
""",
        )
        unsafe = extract_config_file_observations(
            "dangerous.plist",
            """<?xml version="1.0"?>
<!DOCTYPE plist [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<plist><dict><key>Unsafe</key><string>&xxe;</string></dict></plist>
""",
        )

        result = canonicalize_observations((*observations, *unsafe))
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertIn(
            "config.document:file%3Achrome-policy.plist",
            {node["canonical_key"] for node in payload["nodes"]},
        )
        self.assertIn(
            "config.path:file%3Achrome-policy.plist:%2FPolicyPath",
            {node["canonical_key"] for node in payload["nodes"]},
        )
        self.assertIn(
            (
                "file:chrome-policy.plist",
                "defines",
                "config.document:file%3Achrome-policy.plist",
            ),
            {
                (edge["source_key"], edge["kind"], edge["target_key"])
                for edge in payload["edges"]
            },
        )
        self.assertIn(
            (
                "config.path:file%3Achrome-policy.plist:%2FPolicyPath",
                "references",
                "file:managed/policy.json",
            ),
            {
                (edge["source_key"], edge["kind"], edge["target_key"])
                for edge in payload["edges"]
            },
        )
        self.assertNotIn(
            "config.document:file%3Adangerous.plist",
            {node["canonical_key"] for node in payload["nodes"]},
        )

    def test_config_definition_and_reference_diagnostics_use_placeholders(self):
        observations = [
            RawObservation(
                kind="config.path",
                source_id="settings.json#config-path:missing",
                path="settings.json",
                confidence="extracted",
                extractor="repo-config",
                extractor_version="0.1.0",
                metadata={"format": "json"},
            ),
            RawObservation(
                kind="config.reference",
                source_id="settings.json#config-reference:/missing:0",
                path="settings.json",
                name="/missing",
                confidence="heuristic",
                extractor="repo-config",
                extractor_version="0.1.0",
                metadata={
                    "format": "json",
                    "pointer": "/missing",
                    "source_path_key": "config.path:file%3Asettings.json:%2Fmissing",
                },
            ),
            RawObservation(
                kind="config.reference",
                source_id="settings.json#config-reference:/bad:0",
                path="settings.json",
                name="/bad",
                target="bad target",
                confidence="heuristic",
                extractor="repo-config",
                extractor_version="0.1.0",
                metadata={
                    "format": "json",
                    "pointer": "/bad",
                    "source_path_key": "config.path:file%3Asettings.json:%2Fbad",
                },
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["summary"]["errors"], 1)
        self.assertEqual(payload["summary"]["warnings"], 2)
        self.assertEqual(payload["diagnostics"][0]["category"], "invalid_canonical_key")
        self.assertEqual(payload["diagnostics"][1]["category"], "missing_required_metadata")
        self.assertEqual(
            payload["diagnostics"][1]["placeholder_key"],
            "unknown:config.reference:missing-target",
        )
        self.assertEqual(payload["diagnostics"][2]["category"], "invalid_canonical_key")
        self.assertEqual(
            payload["diagnostics"][2]["placeholder_key"],
            "unknown:config.reference:malformed-target",
        )

    def test_config_reference_rejects_non_config_source_path_key(self):
        observation = RawObservation(
            kind="config.reference",
            source_id="settings.json#config-reference:/command:0",
            path="settings.json",
            name="/command",
            target="tool:repomap-kg",
            confidence="heuristic",
            extractor="repo-config",
            extractor_version="0.1.0",
            metadata={
                "format": "json",
                "pointer": "/command",
                "source_path_key": "file:settings.json",
            },
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["summary"]["errors"], 1)
        self.assertIn("config.path", payload["diagnostics"][0]["message"])


if __name__ == "__main__":
    unittest.main()
