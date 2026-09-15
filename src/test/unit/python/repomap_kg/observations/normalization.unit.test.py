import unittest
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from repomap_kg.observations.raw import RawObservation
else:
    from repomap_kg.observations import RawObservation

from repomap_kg.observations.normalization import normalize_observation, normalize_observations


class NormalizationUnitTests(unittest.TestCase):
    def test_normalize_observation_creates_node_edge_and_evidence(self):
        observation = RawObservation(
            kind="shell.command",
            source_id="scripts/build.sh#call:nix-build",
            path="scripts/build.sh",
            start_line=21,
            end_line=21,
            name="nix-build",
            target="tool:nix",
            confidence="heuristic",
            extractor="shell-static",
            extractor_version="0.1.0",
            metadata={"argv": ["nix", "build"]},
        )

        normalized = normalize_observation(observation)
        payload = normalized.to_dict()

        self.assertEqual(len(payload["nodes"]), 1)
        self.assertEqual(len(payload["edges"]), 1)
        self.assertEqual(len(payload["evidence"]), 1)
        self.assertEqual(
            payload["nodes"][0]["stable_key"],
            "node:scripts/build.sh:shell.command:scripts/build.sh#call:nix-build",
        )
        self.assertEqual(payload["edges"][0]["dst_node_key"], "tool:nix")
        self.assertEqual(payload["edges"][0]["confidence"], "heuristic")
        self.assertEqual(payload["evidence"][0]["start_line"], 21)

    def test_normalize_observations_deduplicates_nodes_and_evidence(self):
        observation = RawObservation(
            kind="file",
            source_id="README.md",
            path="README.md",
            confidence="extracted",
            extractor="discovery",
            extractor_version="0.1.0",
        )

        normalized = normalize_observations([observation, observation])
        payload = normalized.to_dict()

        self.assertEqual(payload["summary"]["raw_observations"], 2)
        self.assertEqual(payload["summary"]["nodes"], 1)
        self.assertEqual(payload["summary"]["edges"], 0)
        self.assertEqual(payload["summary"]["evidence"], 1)
        self.assertEqual(payload["nodes"][0]["name"], "README.md")


if __name__ == "__main__":
    unittest.main()
