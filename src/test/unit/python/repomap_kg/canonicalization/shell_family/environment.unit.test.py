import unittest
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from repomap_kg.canonicalization.main import canonicalize_observations
    from repomap_kg.observations.raw import RawObservation
else:
    from repomap_kg.canonicalization import canonicalize_observations
    from repomap_kg.observations import RawObservation

from repomap_kg.canonicalization.records import canonical_edge_key


class CanonicalizationShellEnvironmentUnitTests(unittest.TestCase):
    def test_shell_env_read_creates_reads_env_edge(self):
        observation = RawObservation(
            kind="shell.env",
            source_id="scripts/build.sh#env-read:8:path",
            path="scripts/build.sh",
            start_line=8,
            end_line=8,
            name="PATH",
            target="env:PATH",
            confidence="heuristic",
            extractor="repo-shell",
            extractor_version="0.1.0",
            metadata={
                "operation": "read",
                "variable": "PATH",
                "raw": 'echo "$PATH"',
            },
        )
        edge_key = canonical_edge_key(
            graph_key_version=1,
            source_key="file:scripts/build.sh",
            kind="reads_env",
            target_key="env:PATH",
            identity_metadata={},
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["diagnostics"], [])
        self.assertEqual(
            [node["canonical_key"] for node in payload["nodes"]],
            ["env:PATH", "file:scripts/build.sh"],
        )
        self.assertEqual(
            payload["edges"],
            [
                {
                    "edge_key": edge_key,
                    "graph_key_version": 1,
                    "source_key": "file:scripts/build.sh",
                    "kind": "reads_env",
                    "target_key": "env:PATH",
                    "identity_metadata": {},
                    "metadata": {"operations": ["read"]},
                    "confidence": "heuristic",
                    "conflict": False,
                }
            ],
        )

    def test_shell_env_write_creates_writes_env_edge_with_value_metadata(self):
        observation = RawObservation(
            kind="shell.env",
            source_id="scripts/build.sh#env-write:9:foo",
            path="scripts/build.sh",
            start_line=9,
            end_line=9,
            name="FOO",
            target="env:FOO=value:bar",
            confidence="heuristic",
            extractor="repo-shell",
            extractor_version="0.1.0",
            metadata={
                "operation": "write",
                "variable": "FOO",
                "value": "bar",
                "scope": "shell",
                "raw": "FOO=bar",
            },
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["diagnostics"], [])
        self.assertEqual(payload["edges"][0]["kind"], "writes_env")
        self.assertEqual(payload["edges"][0]["target_key"], "env:FOO")
        self.assertEqual(
            payload["edges"][0]["metadata"],
            {
                "operations": ["write"],
                "scopes": ["shell"],
                "values": ["bar"],
            },
        )

    def test_shell_env_writes_to_same_variable_collapse_to_one_edge(self):
        observations = [
            RawObservation(
                kind="shell.env",
                source_id="scripts/build.sh#env-write:1:foo",
                path="scripts/build.sh",
                start_line=1,
                end_line=1,
                target="env:FOO",
                confidence="heuristic",
                extractor="repo-shell",
                extractor_version="0.1.0",
                metadata={
                    "operation": "write",
                    "variable": "FOO",
                    "value": "bar",
                    "scope": "shell",
                },
            ),
            RawObservation(
                kind="shell.env",
                source_id="scripts/build.sh#env-write:2:foo",
                path="scripts/build.sh",
                start_line=2,
                end_line=2,
                target="env:FOO",
                confidence="manual",
                extractor="repo-shell",
                extractor_version="0.1.0",
                metadata={
                    "operation": "write",
                    "variable": "FOO",
                    "value": "baz",
                    "scope": "command",
                },
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["edges"], 1)
        self.assertEqual(payload["summary"]["evidence"], 2)
        self.assertEqual(payload["summary"]["edge_evidence_links"], 2)
        self.assertEqual(payload["edges"][0]["confidence"], "manual")
        self.assertEqual(
            payload["edges"][0]["metadata"],
            {
                "operations": ["write"],
                "scopes": ["shell", "command"],
                "values": ["bar", "baz"],
            },
        )

    def test_shell_env_secret_prone_write_redacts_summary_and_evidence_value(self):
        observation = RawObservation(
            kind="shell.env",
            source_id="scripts/deploy.sh#env-write:4:api-token",
            path="scripts/deploy.sh",
            start_line=4,
            end_line=4,
            name="API_TOKEN",
            target="env:API_TOKEN",
            confidence="heuristic",
            extractor="repo-shell",
            extractor_version="0.1.0",
            metadata={
                "operation": "write",
                "variable": "API_TOKEN",
                "value": "not-for-summary",
                "scope": "shell",
                "raw": "API_TOKEN=not-for-summary",
            },
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["infos"], 1)
        self.assertEqual(payload["diagnostics"][0]["category"], "secret_prone_value")
        self.assertEqual(
            payload["edges"][0]["metadata"],
            {
                "operations": ["write"],
                "scopes": ["shell"],
                "value_redacted": True,
            },
        )
        self.assertNotIn("value", payload["evidence"][0]["metadata"])
        self.assertTrue(payload["evidence"][0]["metadata"]["value_present"])
        self.assertTrue(payload["evidence"][0]["metadata"]["value_redacted"])

    def test_shell_env_missing_operation_is_warning_and_skipped(self):
        observation = RawObservation(
            kind="shell.env",
            source_id="scripts/build.sh#env:1:path",
            path="scripts/build.sh",
            start_line=1,
            end_line=1,
            target="env:PATH",
            confidence="heuristic",
            extractor="repo-shell",
            extractor_version="0.1.0",
            metadata={"variable": "PATH"},
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["warnings"], 1)
        self.assertEqual(payload["summary"]["edges"], 0)
        self.assertEqual(payload["summary"]["evidence"], 0)
        self.assertEqual(
            payload["diagnostics"][0]["category"],
            "missing_required_metadata",
        )
        self.assertEqual(payload["diagnostics"][0]["field"], "metadata.operation")

    def test_shell_env_unsupported_operation_is_warning_and_skipped(self):
        observation = RawObservation(
            kind="shell.env",
            source_id="scripts/build.sh#env-unset:1:path",
            path="scripts/build.sh",
            start_line=1,
            end_line=1,
            target="env:PATH",
            confidence="heuristic",
            extractor="repo-shell",
            extractor_version="0.1.0",
            metadata={"operation": "unset", "variable": "PATH"},
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["warnings"], 1)
        self.assertEqual(payload["summary"]["edges"], 0)
        self.assertEqual(payload["diagnostics"][0]["category"], "unsupported_operation")
        self.assertEqual(payload["diagnostics"][0]["value"], "unset")

    def test_shell_env_missing_variable_uses_unknown_target(self):
        observation = RawObservation(
            kind="shell.env",
            source_id="scripts/build.sh#env-read:1:missing",
            path="scripts/build.sh",
            start_line=1,
            end_line=1,
            target=None,
            confidence="heuristic",
            extractor="repo-shell",
            extractor_version="0.1.0",
            metadata={"operation": "read"},
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["warnings"], 1)
        self.assertEqual(payload["diagnostics"][0]["category"], "missing_required_metadata")
        self.assertEqual(
            payload["diagnostics"][0]["placeholder_key"],
            "unknown:env:missing-variable",
        )
        self.assertEqual(payload["edges"][0]["kind"], "reads_env")
        self.assertEqual(payload["edges"][0]["target_key"], "unknown:env:missing-variable")

    def test_shell_env_with_bad_source_path_reports_error_without_evidence(self):
        observation = RawObservation(
            kind="shell.env",
            source_id="../build.sh#env-read:1:path",
            path="../build.sh",
            start_line=1,
            end_line=1,
            target="env:PATH",
            confidence="heuristic",
            extractor="repo-shell",
            extractor_version="0.1.0",
            metadata={"operation": "read", "variable": "PATH"},
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["summary"]["nodes"], 0)
        self.assertEqual(payload["summary"]["edges"], 0)
        self.assertEqual(payload["summary"]["evidence"], 0)
        self.assertEqual(payload["diagnostics"][0]["category"], "repo_escaping_path")
