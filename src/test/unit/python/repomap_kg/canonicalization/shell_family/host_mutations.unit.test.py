import unittest
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from repomap_kg.canonicalization.main import canonicalize_observations
    from repomap_kg.observations.raw import RawObservation
else:
    from repomap_kg.canonicalization import canonicalize_observations
    from repomap_kg.observations import RawObservation

from repomap_kg.canonicalization.records import canonical_edge_key


class CanonicalizationShellHostMutationUnitTests(unittest.TestCase):
    def test_shell_host_mutation_creates_mutates_host_edge(self):
        observation = RawObservation(
            kind="shell.host_mutation",
            source_id="scripts/maintain.sh#host-mutation:5:brew-install",
            path="scripts/maintain.sh",
            start_line=5,
            end_line=5,
            name="brew install",
            target="host:package-management",
            confidence="heuristic",
            extractor="repo-shell",
            extractor_version="0.1.0",
            metadata={
                "tool": "brew",
                "category": "package-management",
                "argv": ["brew", "install", "jq"],
                "effective_argv": ["brew", "install", "jq"],
                "privileged": False,
                "reason": "brew install",
                "raw": "brew install jq",
            },
        )
        edge_key = canonical_edge_key(
            graph_key_version=1,
            source_key="file:scripts/maintain.sh",
            kind="mutates_host",
            target_key="host.category:package-management",
            identity_metadata={},
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["diagnostics"], [])
        self.assertEqual(
            [node["canonical_key"] for node in payload["nodes"]],
            ["file:scripts/maintain.sh", "host.category:package-management"],
        )
        self.assertEqual(
            payload["edges"],
            [
                {
                    "edge_key": edge_key,
                    "graph_key_version": 1,
                    "source_key": "file:scripts/maintain.sh",
                    "kind": "mutates_host",
                    "target_key": "host.category:package-management",
                    "identity_metadata": {},
                    "metadata": {
                        "argv_examples": [["brew", "install", "jq"]],
                        "effective_argv_examples": [["brew", "install", "jq"]],
                        "privileged_observed": False,
                        "reasons": ["brew install"],
                        "tools": ["brew"],
                    },
                    "confidence": "heuristic",
                    "conflict": False,
                }
            ],
        )

    def test_shell_host_mutations_to_same_category_collapse_privilege_flag(self):
        observations = [
            RawObservation(
                kind="shell.host_mutation",
                source_id="scripts/maintain.sh#host-mutation:5:brew-install",
                path="scripts/maintain.sh",
                start_line=5,
                end_line=5,
                target="host:package-management",
                confidence="heuristic",
                extractor="repo-shell",
                extractor_version="0.1.0",
                metadata={
                    "tool": "brew",
                    "category": "package-management",
                    "argv": ["brew", "install", "jq"],
                    "effective_argv": ["brew", "install", "jq"],
                    "privileged": False,
                    "reason": "brew install",
                },
            ),
            RawObservation(
                kind="shell.host_mutation",
                source_id="scripts/maintain.sh#host-mutation:6:nix-profile-install",
                path="scripts/maintain.sh",
                start_line=6,
                end_line=6,
                target="host:package-management",
                confidence="manual",
                extractor="repo-shell",
                extractor_version="0.1.0",
                metadata={
                    "tool": "nix",
                    "category": "package-management",
                    "argv": ["sudo", "nix", "profile", "install", "hello"],
                    "effective_argv": ["nix", "profile", "install", "hello"],
                    "privileged": True,
                    "reason": "nix profile install",
                },
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["edges"], 1)
        self.assertEqual(payload["summary"]["edge_evidence_links"], 2)
        self.assertEqual(payload["edges"][0]["confidence"], "manual")
        self.assertEqual(
            payload["edges"][0]["metadata"],
            {
                "argv_examples": [
                    ["brew", "install", "jq"],
                    ["sudo", "nix", "profile", "install", "hello"],
                ],
                "effective_argv_examples": [
                    ["brew", "install", "jq"],
                    ["nix", "profile", "install", "hello"],
                ],
                "privileged_observed": True,
                "reasons": ["brew install", "nix profile install"],
                "tools": ["brew", "nix"],
            },
        )

    def test_shell_host_mutation_missing_category_uses_unknown_target(self):
        observation = RawObservation(
            kind="shell.host_mutation",
            source_id="scripts/maintain.sh#host-mutation:7:unknown",
            path="scripts/maintain.sh",
            start_line=7,
            end_line=7,
            target="host:unknown",
            confidence="heuristic",
            extractor="repo-shell",
            extractor_version="0.1.0",
            metadata={
                "tool": "mystery",
                "argv": ["mystery", "mutate"],
                "privileged": False,
            },
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["warnings"], 1)
        self.assertEqual(
            payload["diagnostics"][0]["category"],
            "missing_required_metadata",
        )
        self.assertEqual(
            payload["diagnostics"][0]["placeholder_key"],
            "unknown:host.category:missing-host-category",
        )
        self.assertEqual(
            payload["edges"][0]["target_key"],
            "unknown:host.category:missing-host-category",
        )

    def test_shell_host_mutation_unregistered_category_uses_unknown_target(self):
        observation = RawObservation(
            kind="shell.host_mutation",
            source_id="scripts/maintain.sh#host-mutation:8:network",
            path="scripts/maintain.sh",
            start_line=8,
            end_line=8,
            target="host:network",
            confidence="heuristic",
            extractor="repo-shell",
            extractor_version="0.1.0",
            metadata={
                "tool": "networksetup",
                "category": "network",
                "argv": ["networksetup", "-setwebproxy"],
                "privileged": False,
            },
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["warnings"], 1)
        self.assertEqual(payload["diagnostics"][0]["category"], "unregistered_category")
        self.assertEqual(
            payload["diagnostics"][0]["placeholder_key"],
            "unknown:host.category:unregistered-network",
        )
        self.assertEqual(
            payload["edges"][0]["target_key"],
            "unknown:host.category:unregistered-network",
        )

    def test_shell_host_mutation_with_bad_source_path_reports_error_without_evidence(self):
        observation = RawObservation(
            kind="shell.host_mutation",
            source_id="../maintain.sh#host-mutation:1:brew",
            path="../maintain.sh",
            start_line=1,
            end_line=1,
            target="host:package-management",
            confidence="heuristic",
            extractor="repo-shell",
            extractor_version="0.1.0",
            metadata={"category": "package-management", "tool": "brew"},
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["summary"]["nodes"], 0)
        self.assertEqual(payload["summary"]["edges"], 0)
        self.assertEqual(payload["summary"]["evidence"], 0)
        self.assertEqual(payload["diagnostics"][0]["category"], "repo_escaping_path")
