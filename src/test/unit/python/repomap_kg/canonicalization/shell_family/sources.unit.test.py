import unittest
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from repomap_kg.canonicalization.main import canonicalize_observations
    from repomap_kg.observations.raw import RawObservation
else:
    from repomap_kg.canonicalization import canonicalize_observations
    from repomap_kg.observations import RawObservation

from repomap_kg.canonicalization.records import canonical_edge_key


class CanonicalizationShellSourceUnitTests(unittest.TestCase):
    def test_shell_source_static_repo_path_creates_sources_edge(self):
        observation = RawObservation(
            kind="shell.source",
            source_id="scripts/build.sh#source:3:lib/common.sh",
            path="scripts/build.sh",
            start_line=3,
            end_line=3,
            target="file:lib/common.sh",
            confidence="heuristic",
            extractor="repo-shell",
            extractor_version="0.1.0",
            metadata={
                "source": "../lib/common.sh",
                "resolved_path": "lib/common.sh",
                "raw": "source ../lib/common.sh",
            },
        )
        edge_key = canonical_edge_key(
            graph_key_version=1,
            source_key="file:scripts/build.sh",
            kind="sources",
            target_key="file:lib/common.sh",
            identity_metadata={},
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["diagnostics"], [])
        self.assertEqual(
            [node["canonical_key"] for node in payload["nodes"]],
            ["file:lib/common.sh", "file:scripts/build.sh"],
        )
        self.assertEqual(
            payload["edges"],
            [
                {
                    "edge_key": edge_key,
                    "graph_key_version": 1,
                    "source_key": "file:scripts/build.sh",
                    "kind": "sources",
                    "target_key": "file:lib/common.sh",
                    "identity_metadata": {},
                    "metadata": {
                        "resolved_paths": ["lib/common.sh"],
                        "sources": ["../lib/common.sh"],
                    },
                    "confidence": "heuristic",
                    "conflict": False,
                }
            ],
        )
        self.assertEqual(payload["edge_evidence_links"][0]["link_kind"], "supports")

    def test_shell_source_dynamic_path_uses_placeholder_and_info_diagnostic(self):
        observation = RawObservation(
            kind="shell.source",
            source_id="scripts/build.sh#source:4:dynamic",
            path="scripts/build.sh",
            start_line=4,
            end_line=4,
            target="dynamic:file:shell-source-expanded-from-variable",
            confidence="heuristic",
            extractor="repo-shell",
            extractor_version="0.1.0",
            metadata={
                "source": "$COMMON_SH",
                "dynamic_reason": "shell-source-expanded-from-variable",
                "raw": "source \"$COMMON_SH\"",
            },
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["infos"], 1)
        self.assertEqual(
            payload["diagnostics"][0]["category"],
            "dynamic_target",
        )
        self.assertEqual(
            payload["diagnostics"][0]["placeholder_key"],
            "dynamic:file:shell-source-expanded-from-variable",
        )
        self.assertEqual(
            payload["edges"][0]["target_key"],
            "dynamic:file:shell-source-expanded-from-variable",
        )
        self.assertEqual(
            payload["edges"][0]["metadata"],
            {"sources": ["$COMMON_SH"]},
        )

    def test_shell_source_with_bad_source_path_reports_error_without_evidence(self):
        observation = RawObservation(
            kind="shell.source",
            source_id="../build.sh#source:1:common",
            path="../build.sh",
            start_line=1,
            end_line=1,
            target="file:lib/common.sh",
            confidence="heuristic",
            extractor="repo-shell",
            extractor_version="0.1.0",
            metadata={
                "source": "lib/common.sh",
                "resolved_path": "lib/common.sh",
            },
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["summary"]["nodes"], 0)
        self.assertEqual(payload["summary"]["edges"], 0)
        self.assertEqual(payload["summary"]["evidence"], 0)
        self.assertEqual(payload["diagnostics"][0]["category"], "repo_escaping_path")

    def test_shell_source_with_repo_escaping_resolved_path_uses_unknown_target(self):
        observation = RawObservation(
            kind="shell.source",
            source_id="scripts/build.sh#source:5:escape",
            path="scripts/build.sh",
            start_line=5,
            end_line=5,
            target="file:../secret.sh",
            confidence="heuristic",
            extractor="repo-shell",
            extractor_version="0.1.0",
            metadata={
                "source": "../secret.sh",
                "resolved_path": "../secret.sh",
            },
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["warnings"], 1)
        self.assertEqual(payload["diagnostics"][0]["category"], "repo_escaping_path")
        self.assertEqual(
            payload["diagnostics"][0]["placeholder_key"],
            "unknown:file:repo-escaping-source",
        )
        self.assertEqual(
            payload["edges"][0]["target_key"],
            "unknown:file:repo-escaping-source",
        )

    def test_shell_source_without_static_or_dynamic_target_uses_unknown_target(self):
        observation = RawObservation(
            kind="shell.source",
            source_id="scripts/build.sh#source:6:unknown",
            path="scripts/build.sh",
            start_line=6,
            end_line=6,
            target=None,
            confidence="heuristic",
            extractor="repo-shell",
            extractor_version="0.1.0",
            metadata={"source": "$maybe_common"},
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["warnings"], 1)
        self.assertEqual(payload["diagnostics"][0]["category"], "unknown_target")
        self.assertEqual(
            payload["diagnostics"][0]["placeholder_key"],
            "unknown:file:unresolved-shell-source",
        )
        self.assertEqual(
            payload["edges"][0]["target_key"],
            "unknown:file:unresolved-shell-source",
        )

    def test_shell_source_with_malformed_target_uses_unknown_placeholder(self):
        observation = RawObservation(
            kind="shell.source",
            source_id="scripts/build.sh#source:7:malformed",
            path="scripts/build.sh",
            start_line=7,
            end_line=7,
            target="file:bad%2",
            confidence="heuristic",
            extractor="repo-shell",
            extractor_version="0.1.0",
            metadata={"source": "$maybe_common"},
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["warnings"], 1)
        self.assertEqual(
            payload["diagnostics"][0]["category"], "malformed_percent_escape"
        )
        self.assertEqual(payload["diagnostics"][0]["field"], "target")
        self.assertEqual(payload["diagnostics"][0]["value"], "file:bad%2")
        self.assertEqual(
            payload["diagnostics"][0]["placeholder_key"],
            "unknown:file:unresolved-shell-source",
        )
        self.assertEqual(
            payload["edges"][0]["target_key"],
            "unknown:file:unresolved-shell-source",
        )
