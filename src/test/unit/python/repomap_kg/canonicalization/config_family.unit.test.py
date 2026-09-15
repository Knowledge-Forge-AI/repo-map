import unittest

from repomap_kg.canonicalization.main import (
    canonicalize_observations,
)
from repomap_kg.extractors.config.generic import extract_config_file_observations
from repomap_kg.observations.raw import RawObservation



class CanonicalizationConfigFamilyUnitTests(unittest.TestCase):
    def test_config_document_and_path_create_file_defines_edges(self):
        observations = [
            RawObservation(
                kind="config.document",
                source_id="mcp/repo-map/config.json#config-document",
                path="mcp/repo-map/config.json",
                confidence="extracted",
                extractor="repo-config",
                extractor_version="0.1.0",
                target="config.document:file%3Amcp%2Frepo-map%2Fconfig.json",
                metadata={
                    "format": "json",
                    "parser": "stdlib-json",
                    "top_level_type": "object",
                    "document_role": "mcp-config",
                    "path_count": 2,
                },
            ),
            RawObservation(
                kind="config.path",
                source_id=(
                    "mcp/repo-map/config.json#config-path:"
                    "/projects/repo-map/pg_database"
                ),
                path="mcp/repo-map/config.json",
                name="/projects/repo-map/pg_database",
                confidence="extracted",
                extractor="repo-config",
                extractor_version="0.1.0",
                target=(
                    "config.path:file%3Amcp%2Frepo-map%2Fconfig.json:"
                    "%2Fprojects%2Frepo-map%2Fpg_database"
                ),
                metadata={
                    "format": "json",
                    "pointer": "/projects/repo-map/pg_database",
                    "display_path": "/projects/repo-map/pg_database",
                    "value_type": "string",
                    "container_type": "object",
                    "redacted": False,
                    "value_summary": "repomap_repo_map",
                },
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["diagnostics"], [])
        self.assertEqual(
            sorted(node["canonical_key"] for node in payload["nodes"]),
            [
                "config.document:file%3Amcp%2Frepo-map%2Fconfig.json",
                (
                    "config.path:file%3Amcp%2Frepo-map%2Fconfig.json:"
                    "%2Fprojects%2Frepo-map%2Fpg_database"
                ),
                "file:mcp/repo-map/config.json",
            ],
        )
        self.assertEqual(
            sorted(
                (edge["source_key"], edge["kind"], edge["target_key"])
                for edge in payload["edges"]
            ),
            [
                (
                    "file:mcp/repo-map/config.json",
                    "defines",
                    "config.document:file%3Amcp%2Frepo-map%2Fconfig.json",
                ),
                (
                    "file:mcp/repo-map/config.json",
                    "defines",
                    (
                        "config.path:file%3Amcp%2Frepo-map%2Fconfig.json:"
                        "%2Fprojects%2Frepo-map%2Fpg_database"
                    ),
                ),
            ],
        )
        config_path = next(
            node for node in payload["nodes"] if node["kind"] == "config.path"
        )
        self.assertEqual(
            config_path["metadata"]["pointer"],
            "/projects/repo-map/pg_database",
        )
        self.assertEqual(config_path["metadata"]["value_summary"], "repomap_repo_map")

    def test_config_reference_creates_references_edge_from_config_path(self):
        observation = RawObservation(
            kind="config.reference",
            source_id=(
                "mcp/repo-map/config.json#config-reference:"
                "/mcp_servers/repomap/command:0"
            ),
            path="mcp/repo-map/config.json",
            name="/mcp_servers/repomap/command",
            target="tool:repomap-kg",
            confidence="heuristic",
            extractor="repo-config",
            extractor_version="0.1.0",
            metadata={
                "format": "json",
                "pointer": "/mcp_servers/repomap/command",
                "raw_key": "command",
                "reference_kind": "tool",
                "raw_value_summary": "repomap-kg",
                "redacted": False,
                "resolution_reason": "simple-command-field",
                "source_path_key": (
                    "config.path:file%3Amcp%2Frepo-map%2Fconfig.json:"
                    "%2Fmcp_servers%2Frepomap%2Fcommand"
                ),
            },
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["edges"], 1)
        self.assertEqual(payload["edges"][0]["kind"], "references")
        self.assertEqual(
            payload["edges"][0]["source_key"],
            (
                "config.path:file%3Amcp%2Frepo-map%2Fconfig.json:"
                "%2Fmcp_servers%2Frepomap%2Fcommand"
            ),
        )
        self.assertEqual(payload["edges"][0]["target_key"], "tool:repomap-kg")
        self.assertEqual(
            payload["edges"][0]["metadata"]["reference_kinds"],
            ["tool"],
        )
        self.assertEqual(
            payload["edges"][0]["metadata"]["resolution_reasons"],
            ["simple-command-field"],
        )

    def test_config_jsonl_record_and_parse_error_are_evidence_only(self):
        observations = [
            RawObservation(
                kind="config.jsonl_record",
                source_id="events.jsonl#jsonl-record:1",
                path="events.jsonl",
                start_line=1,
                end_line=1,
                confidence="extracted",
                extractor="repo-config",
                extractor_version="0.1.0",
                metadata={
                    "format": "jsonl",
                    "record_index": 0,
                    "line_number": 1,
                    "top_level_type": "object",
                    "safe_keys": ["event"],
                    "redacted_keys": [],
                },
            ),
            RawObservation(
                kind="config.parse_error",
                source_id="events.jsonl#config-parse-error:2",
                path="events.jsonl",
                start_line=2,
                end_line=2,
                confidence="unknown",
                extractor="repo-config",
                extractor_version="0.1.0",
                metadata={
                    "format": "jsonl",
                    "parser": "stdlib-json",
                    "error_kind": "malformed-jsonl-line",
                    "message_summary": "Expecting value",
                    "line_number": 2,
                    "recovered": True,
                },
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["diagnostics"], [])
        self.assertEqual(payload["summary"]["nodes"], 0)
        self.assertEqual(payload["summary"]["edges"], 0)
        self.assertEqual(payload["summary"]["evidence"], 2)
        self.assertEqual(payload["summary"]["node_evidence_links"], 0)
        self.assertEqual(payload["summary"]["edge_evidence_links"], 0)

    def test_tfjson_profile_observations_are_evidence_only(self):
        observations = [
            RawObservation(
                kind="npm.package",
                source_id="package.json#npm-package",
                path="package.json",
                confidence="extracted",
                extractor="repo-config",
                extractor_version="0.1.0",
                metadata={
                    "format": "json",
                    "profile": "package_json",
                    "package_name": "example",
                },
            ),
            RawObservation(
                kind="terraform.resource",
                source_id="infra/main.tf.json#terraform-resource:aws_s3_bucket:app",
                path="infra/main.tf.json",
                confidence="extracted",
                extractor="repo-config",
                extractor_version="0.1.0",
                metadata={
                    "format": "json",
                    "profile": "terraform_json",
                    "resource_type": "aws_s3_bucket",
                    "resource_name": "app",
                },
            ),
            RawObservation(
                kind="terraform.block",
                source_id="infra/main.tf#terraform-block:resource:1",
                path="infra/main.tf",
                confidence="extracted",
                extractor="repo-config",
                extractor_version="0.1.0",
                metadata={
                    "format": "terraform-hcl",
                    "profile": "terraform",
                    "block_type": "resource",
                    "labels": ["aws_s3_bucket", "app"],
                },
            ),
            RawObservation(
                kind="terraform.moved",
                source_id="infra/main.tf#terraform-moved:42",
                path="infra/main.tf",
                confidence="heuristic",
                extractor="repo-config",
                extractor_version="0.1.0",
                metadata={
                    "format": "terraform-hcl",
                    "profile": "terraform",
                    "from_summary": "aws_s3_bucket.old",
                    "to_summary": "aws_s3_bucket.app",
                },
            ),
            RawObservation(
                kind="terraform.parse_error",
                source_id="infra/broken.tf#terraform-parse-error:document",
                path="infra/broken.tf",
                confidence="unknown",
                extractor="repo-config",
                extractor_version="0.1.0",
                metadata={
                    "format": "terraform-hcl",
                    "profile": "terraform",
                    "error_kind": "terraform-unclosed-block",
                    "recovered": True,
                },
            ),
            RawObservation(
                kind="kubernetes.resource",
                source_id="deploy/app.json#kubernetes-resource:Deployment:app",
                path="deploy/app.json",
                confidence="extracted",
                extractor="repo-config",
                extractor_version="0.1.0",
                metadata={
                    "format": "json",
                    "profile": "kubernetes_json",
                    "kind": "Deployment",
                    "name": "app",
                },
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["diagnostics"], [])
        self.assertEqual(payload["summary"]["nodes"], 0)
        self.assertEqual(payload["summary"]["edges"], 0)
        self.assertEqual(payload["summary"]["evidence"], 6)
        self.assertEqual(payload["summary"]["node_evidence_links"], 0)
        self.assertEqual(payload["summary"]["edge_evidence_links"], 0)

    def test_toml_config_observations_reuse_config_canonicalization_contract(self):
        observations = extract_config_file_observations(
            "config.toml",
            """
[mcp_servers.repomap]
command = "python3"
cwd = "src/main/python"
""",
        )

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertIn(
            "config.document:file%3Aconfig.toml",
            {node["canonical_key"] for node in payload["nodes"]},
        )
        self.assertIn(
            "config.path:file%3Aconfig.toml:%2Fmcp_servers%2Frepomap%2Fcommand",
            {node["canonical_key"] for node in payload["nodes"]},
        )
        self.assertIn(
            (
                "file:config.toml",
                "defines",
                "config.document:file%3Aconfig.toml",
            ),
            {
                (edge["source_key"], edge["kind"], edge["target_key"])
                for edge in payload["edges"]
            },
        )
        self.assertIn(
            (
                "config.path:file%3Aconfig.toml:%2Fmcp_servers%2Frepomap%2Fcommand",
                "references",
                "tool:python3",
            ),
            {
                (edge["source_key"], edge["kind"], edge["target_key"])
                for edge in payload["edges"]
            },
        )


if __name__ == "__main__":
    unittest.main()
