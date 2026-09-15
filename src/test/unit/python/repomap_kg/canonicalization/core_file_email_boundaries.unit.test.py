import unittest

from repomap_kg.canonicalization import canonicalize_observations
from repomap_kg.observations import RawObservation


class CanonicalizationCoreFileEmailBoundariesUnitTests(unittest.TestCase):
    def test_file_observation_with_repo_escaping_path_reports_error(self):
        observation = RawObservation(
            kind="file",
            source_id="../secret.txt",
            path="../secret.txt",
            confidence="extracted",
            extractor="repo-discovery",
            extractor_version="0.1.0",
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["summary"]["raw_observations"], 1)
        self.assertEqual(payload["summary"]["nodes"], 0)
        self.assertEqual(payload["summary"]["evidence"], 0)
        self.assertEqual(payload["summary"]["errors"], 1)
        self.assertEqual(payload["diagnostics"][0]["severity"], "error")
        self.assertEqual(payload["diagnostics"][0]["category"], "repo_escaping_path")
        self.assertEqual(payload["diagnostics"][0]["field"], "path")
        self.assertEqual(payload["diagnostics"][0]["value"], "../secret.txt")

    def test_file_observation_with_absolute_path_reports_invalid_key_error(self):
        observation = RawObservation(
            kind="file",
            source_id="/tmp/secret.txt",
            path="/tmp/secret.txt",
            confidence="extracted",
            extractor="repo-discovery",
            extractor_version="0.1.0",
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["diagnostics"][0]["category"], "invalid_canonical_key")
        self.assertEqual(payload["diagnostics"][0]["value"], "/tmp/secret.txt")

    def test_file_observations_with_conflicting_hashes_set_node_conflict(self):
        observations = [
            RawObservation(
                kind="file",
                source_id="src/app.py:first",
                path="src/app.py",
                confidence="heuristic",
                extractor="repo-discovery",
                extractor_version="0.1.0",
                metadata={
                    "language": "python",
                    "role": "source",
                    "content_hash": "sha256:first",
                    "executable": False,
                    "generated": False,
                },
            ),
            RawObservation(
                kind="file",
                source_id="src/app.py:second",
                path="src/app.py",
                confidence="manual",
                extractor="repo-discovery",
                extractor_version="0.1.0",
                metadata={
                    "language": "python",
                    "role": "source",
                    "content_hash": "sha256:second",
                    "executable": False,
                    "generated": False,
                },
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["warnings"], 1)
        self.assertEqual(payload["diagnostics"][0]["category"], "conflicting_evidence")
        self.assertEqual(payload["diagnostics"][0]["field"], "metadata.content_hash")
        self.assertEqual(payload["nodes"][0]["confidence"], "manual")
        self.assertTrue(payload["nodes"][0]["conflict"])
        self.assertEqual(
            payload["nodes"][0]["metadata"]["content_hash"],
            ["sha256:first", "sha256:second"],
        )

    def test_file_observation_with_raw_percent_in_path_encodes_canonical_key(self):
        observation = RawObservation(
            kind="file",
            source_id="raw%ZZname.txt",
            path="raw%ZZname.txt",
            confidence="extracted",
            extractor="repo-discovery",
            extractor_version="0.1.0",
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["errors"], 0)
        self.assertEqual(payload["nodes"][0]["canonical_key"], "file:raw%25ZZname.txt")
        self.assertEqual(payload, canonicalize_observations([observation]).to_dict())

    def test_malformed_canonical_target_remains_distinct_from_raw_percent_path(self):
        observation = RawObservation(
            kind="shell.command", source_id="fixture:command", path="script.sh",
            target="tool:primary%ZZmalformed", confidence="extracted",
            extractor="fixture", extractor_version="1",
            metadata={"command": "fixture", "argv": ["fixture"]},
        )
        result = canonicalize_observations([observation])
        diagnostics = [d for d in result.diagnostics if d.category == "malformed_percent_escape"]
        self.assertTrue(result.ok)
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(diagnostics[0].severity, "warning")
        self.assertEqual(diagnostics[0].field, "target")
        self.assertEqual(result.to_dict(), canonicalize_observations([observation]).to_dict())
