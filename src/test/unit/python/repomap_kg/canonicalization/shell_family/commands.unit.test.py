import unittest
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from repomap_kg.canonicalization.main import canonicalize_observations
    from repomap_kg.observations.raw import RawObservation
else:
    from repomap_kg.canonicalization import canonicalize_observations
    from repomap_kg.observations import RawObservation

from repomap_kg.canonicalization.records import canonical_edge_key


class CanonicalizationShellCommandUnitTests(unittest.TestCase):
    def test_shell_command_creates_executes_edge_and_inferred_nodes(self):
        observation = RawObservation(
            kind="shell.command",
            source_id="bin/tool#call:12:nix-build",
            path="bin/tool",
            start_line=12,
            end_line=12,
            name="nix build",
            target="tool:nix",
            confidence="heuristic",
            extractor="repo-shell",
            extractor_version="0.1.0",
            metadata={
                "command": "nix",
                "argv": ["nix", "build", ".#checks"],
                "raw": "nix build .#checks",
            },
        )
        edge_key = canonical_edge_key(
            graph_key_version=1,
            source_key="file:bin/tool",
            kind="executes",
            target_key="tool:nix",
            identity_metadata={},
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["diagnostics"], [])
        self.assertEqual(
            payload["nodes"],
            [
                {
                    "canonical_key": "file:bin/tool",
                    "graph_key_version": 1,
                    "kind": "file",
                    "display_name": "bin/tool",
                    "metadata": {},
                    "confidence": "heuristic",
                    "conflict": False,
                },
                {
                    "canonical_key": "tool:nix",
                    "graph_key_version": 1,
                    "kind": "tool",
                    "display_name": "nix",
                    "metadata": {},
                    "confidence": "heuristic",
                    "conflict": False,
                },
            ],
        )
        self.assertEqual(
            payload["edges"],
            [
                {
                    "edge_key": edge_key,
                    "graph_key_version": 1,
                    "source_key": "file:bin/tool",
                    "kind": "executes",
                    "target_key": "tool:nix",
                    "identity_metadata": {},
                    "metadata": {
                        "argv_examples": [["nix", "build", ".#checks"]],
                        "commands": ["nix"],
                    },
                    "confidence": "heuristic",
                    "conflict": False,
                }
            ],
        )
        self.assertEqual(payload["summary"]["edge_evidence_links"], 1)
        self.assertEqual(
            payload["node_evidence_links"],
            [
                {
                    "canonical_key": "file:bin/tool",
                    "evidence_key": "evidence:0:bin/tool:12-12:repo-shell:bin/tool#call:12:nix-build",
                    "link_kind": "inferred_from_edge",
                },
                {
                    "canonical_key": "tool:nix",
                    "evidence_key": "evidence:0:bin/tool:12-12:repo-shell:bin/tool#call:12:nix-build",
                    "link_kind": "inferred_from_edge",
                },
            ],
        )

    def test_shell_commands_to_same_tool_collapse_to_one_edge(self):
        observations = [
            RawObservation(
                kind="shell.command",
                source_id="bin/tool#call:1:nix-build",
                path="bin/tool",
                start_line=1,
                end_line=1,
                target="tool:nix",
                confidence="heuristic",
                extractor="repo-shell",
                extractor_version="0.1.0",
                metadata={"command": "nix", "argv": ["nix", "build"]},
            ),
            RawObservation(
                kind="shell.command",
                source_id="bin/tool#call:2:nix-flake-check",
                path="bin/tool",
                start_line=2,
                end_line=2,
                target="tool:nix",
                confidence="manual",
                extractor="repo-shell",
                extractor_version="0.1.0",
                metadata={"command": "nix", "argv": ["nix", "flake", "check"]},
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["raw_observations"], 2)
        self.assertEqual(payload["summary"]["nodes"], 2)
        self.assertEqual(payload["summary"]["edges"], 1)
        self.assertEqual(payload["summary"]["evidence"], 2)
        self.assertEqual(payload["summary"]["node_evidence_links"], 4)
        self.assertEqual(payload["summary"]["edge_evidence_links"], 2)
        self.assertEqual(payload["nodes"][0]["confidence"], "manual")
        self.assertEqual(payload["nodes"][1]["confidence"], "manual")
        self.assertEqual(payload["edges"][0]["confidence"], "manual")
        self.assertEqual(
            payload["edges"][0]["metadata"],
            {
                "argv_examples": [
                    ["nix", "build"],
                    ["nix", "flake", "check"],
                ],
                "commands": ["nix"],
            },
        )
        self.assertEqual(
            [link["link_kind"] for link in payload["edge_evidence_links"]],
            ["supports", "supports"],
        )

    def test_shell_command_uses_argv_zero_when_command_metadata_is_missing(self):
        observation = RawObservation(
            kind="shell.command",
            source_id="bin/tool#call:3:nix",
            path="bin/tool",
            start_line=3,
            end_line=3,
            target="tool:nix",
            confidence="heuristic",
            extractor="repo-shell",
            extractor_version="0.1.0",
            metadata={"argv": ["nix", "develop"]},
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["nodes"][1]["canonical_key"], "tool:nix")
        self.assertEqual(payload["nodes"][1]["display_name"], "nix")
        self.assertEqual(
            payload["edges"][0]["metadata"],
            {"argv_examples": [["nix", "develop"]], "commands": ["nix"]},
        )

    def test_shell_command_dynamic_target_uses_placeholder(self):
        observation = RawObservation(
            kind="shell.command",
            source_id="bin/tool#call:4:dynamic",
            path="bin/tool",
            start_line=4,
            end_line=4,
            target="dynamic:tool:shell-variable-command",
            confidence="heuristic",
            extractor="repo-shell",
            extractor_version="0.1.0",
            metadata={
                "dynamic_reason": "shell-variable-command",
                "raw": '"$COMMAND" --help',
            },
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["infos"], 1)
        self.assertEqual(payload["diagnostics"][0]["category"], "dynamic_target")
        self.assertEqual(payload["diagnostics"][0]["field"], "metadata.dynamic_reason")
        self.assertEqual(
            payload["diagnostics"][0]["placeholder_key"],
            "dynamic:tool:shell-variable-command",
        )
        self.assertEqual(
            payload["edges"][0]["target_key"],
            "dynamic:tool:shell-variable-command",
        )
        self.assertEqual(
            payload["edges"][0]["metadata"],
            {"dynamic_reasons": ["shell-variable-command"]},
        )

    def test_shell_command_dynamic_reason_without_target_uses_placeholder(self):
        observation = RawObservation(
            kind="shell.command",
            source_id="bin/tool#call:5:dynamic",
            path="bin/tool",
            start_line=5,
            end_line=5,
            confidence="heuristic",
            extractor="repo-shell",
            extractor_version="0.1.0",
            metadata={"dynamic_reason": "shell-variable-command"},
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["infos"], 1)
        self.assertEqual(
            payload["diagnostics"][0]["placeholder_key"],
            "dynamic:tool:shell-variable-command",
        )
        self.assertEqual(
            payload["edges"][0]["target_key"],
            "dynamic:tool:shell-variable-command",
        )

    def test_shell_command_missing_command_uses_unknown_placeholder(self):
        observation = RawObservation(
            kind="shell.command",
            source_id="bin/tool#call:6:missing",
            path="bin/tool",
            start_line=6,
            end_line=6,
            confidence="heuristic",
            extractor="repo-shell",
            extractor_version="0.1.0",
            metadata={},
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["warnings"], 1)
        self.assertEqual(
            payload["diagnostics"][0]["category"], "missing_required_metadata"
        )
        self.assertEqual(payload["diagnostics"][0]["field"], "metadata.command")
        self.assertEqual(
            payload["diagnostics"][0]["placeholder_key"],
            "unknown:tool:missing-command",
        )
        self.assertEqual(
            payload["edges"][0]["target_key"], "unknown:tool:missing-command"
        )
        self.assertEqual(payload["summary"]["edge_evidence_links"], 1)

    def test_shell_command_with_bad_path_reports_error_without_evidence(self):
        observation = RawObservation(
            kind="shell.command",
            source_id="../tool#call:1:nix",
            path="../tool",
            start_line=1,
            end_line=1,
            target="tool:nix",
            confidence="heuristic",
            extractor="repo-shell",
            extractor_version="0.1.0",
            metadata={"command": "nix", "argv": ["nix", "build"]},
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["summary"]["nodes"], 0)
        self.assertEqual(payload["summary"]["edges"], 0)
        self.assertEqual(payload["summary"]["evidence"], 0)
        self.assertEqual(payload["diagnostics"][0]["category"], "repo_escaping_path")

    def test_shell_command_metadata_merge_keeps_first_seen_distinct_values(self):
        observations = [
            RawObservation(
                kind="shell.command",
                source_id="bin/tool#call:1:nix",
                path="bin/tool",
                start_line=1,
                end_line=1,
                target="tool:nix",
                confidence="heuristic",
                extractor="repo-shell",
                extractor_version="0.1.0",
                metadata={"command": "nix"},
            ),
            RawObservation(
                kind="shell.command",
                source_id="bin/tool#call:2:nix-build",
                path="bin/tool",
                start_line=2,
                end_line=2,
                target="tool:nix",
                confidence="heuristic",
                extractor="repo-shell",
                extractor_version="0.1.0",
                metadata={"command": "nix", "argv": ["nix", "build"]},
            ),
            RawObservation(
                kind="shell.command",
                source_id="bin/tool#call:3:nix-build",
                path="bin/tool",
                start_line=3,
                end_line=3,
                target="tool:nix",
                confidence="heuristic",
                extractor="repo-shell",
                extractor_version="0.1.0",
                metadata={"command": "nix", "argv": ["nix", "build"]},
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["nodes"][0]["confidence"], "heuristic")
        self.assertEqual(payload["edges"][0]["confidence"], "heuristic")
        self.assertEqual(
            payload["edges"][0]["metadata"],
            {"argv_examples": [["nix", "build"]], "commands": ["nix"]},
        )

    def test_shell_command_with_malformed_target_rebuilds_from_metadata(self):
        observation = RawObservation(
            kind="shell.command",
            source_id="bin/tool#call:1:nix",
            path="bin/tool",
            start_line=1,
            end_line=1,
            target="tool:nix%2",
            confidence="heuristic",
            extractor="repo-shell",
            extractor_version="0.1.0",
            metadata={"command": "nix", "argv": ["nix", "build"]},
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["warnings"], 1)
        self.assertEqual(
            payload["diagnostics"][0]["category"], "malformed_percent_escape"
        )
        self.assertEqual(payload["diagnostics"][0]["field"], "target")
        self.assertEqual(payload["diagnostics"][0]["value"], "tool:nix%2")
        self.assertEqual(payload["edges"][0]["target_key"], "tool:nix")
