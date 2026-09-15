import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from repomap_kg.cli import main
from repomap_kg.storage import (
    CanonicalEdgeEvidenceRecord,
    CanonicalEdgeExplanationRecord,
    CanonicalEdgeRecord,
    identity_metadata_hash,
)


class CliStorageCanonicalEdgeExplanationUnitTests(unittest.TestCase):
    def test_storage_explain_canonical_edge_prints_json_record(self):
        hash_text = identity_metadata_hash({"order": [2, 1], "scope": "flake"})
        record = CanonicalEdgeExplanationRecord(
            edge=CanonicalEdgeRecord(
                source_key="file:bin/tool",
                edge_kind="calls",
                target_key="tool:nix",
                graph_key_version=1,
                identity_metadata={"order": [2, 1], "scope": "flake"},
                identity_metadata_hash=hash_text,
                metadata={"commands": ["nix"]},
                confidence="extracted",
                conflict=False,
                first_seen_run_id=10,
                last_seen_run_id=12,
            ),
            evidence=(
                CanonicalEdgeEvidenceRecord(
                    evidence_key="evidence:bin/tool:1-1:repo-shell:nix",
                    link_kind="supports",
                    raw_observation={
                        "run_id": 10,
                        "ordinal": 0,
                        "payload_hash": (
                            "abcdef0123456789abcdef0123456789"
                            "abcdef0123456789abcdef0123456789"
                        ),
                        "kind": "shell.command",
                        "source_id": "bin/tool#call:nix",
                    },
                    path="bin/tool",
                    start_line=1,
                    end_line=1,
                    extractor="repo-shell",
                    extractor_version="0.1.0",
                    confidence="extracted",
                    metadata={"argv": ["nix", "build"]},
                ),
            ),
        )
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_canonical_edge_explanation",
            return_value=record,
        ) as query:
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "explain-canonical-edge",
                        "--root-path",
                        "/tmp/fixture",
                        "--source-key",
                        "file:bin/tool",
                        "--kind",
                        "calls",
                        "--target-key",
                        "tool:nix",
                        "--identity-metadata-json",
                        '{"scope": "flake", "order": [2, 1]}',
                        "--pg-database",
                        "postgres",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["result_kind"], "canonical_edge_explanation")
        self.assertEqual(payload["result"]["edge"]["source_key"], "file:bin/tool")
        self.assertEqual(
            payload["result"]["edge"]["identity_metadata_hash"],
            hash_text,
        )
        self.assertEqual(
            payload["result"]["evidence"][0]["raw_observation"]["ordinal"],
            0,
        )
        self.assertEqual(payload["collections"]["evidence"]["returned"], 1)
        self.assertEqual(query.call_args.args[0], ["-d", "postgres"])
        self.assertEqual(query.call_args.kwargs["root_path"], "/tmp/fixture")
        self.assertEqual(query.call_args.kwargs["source_key"], "file:bin/tool")
        self.assertEqual(query.call_args.kwargs["kind"], "calls")
        self.assertEqual(query.call_args.kwargs["target_key"], "tool:nix")
        self.assertEqual(query.call_args.kwargs["identity_metadata_hash"], hash_text)
        self.assertEqual(query.call_args.kwargs["graph_key_version"], 1)
        self.assertEqual(query.call_args.kwargs["evidence_limit"], 51)
        self.assertEqual(query.call_args.kwargs["evidence_offset"], 0)

    def test_storage_explain_canonical_edge_prints_table_record(self):
        hash_text = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        record = CanonicalEdgeExplanationRecord(
            edge=CanonicalEdgeRecord(
                source_key="file:bin/tool",
                edge_kind="executes",
                target_key="tool:nix",
                graph_key_version=1,
                identity_metadata={},
                identity_metadata_hash=hash_text,
                metadata={"ignored": True},
                confidence="extracted",
                conflict=False,
                first_seen_run_id=10,
                last_seen_run_id=12,
            ),
            evidence=(
                CanonicalEdgeEvidenceRecord(
                    evidence_key="evidence:bin/tool:1-1:repo-shell:nix",
                    link_kind="supports",
                    raw_observation={
                        "run_id": 10,
                        "ordinal": 0,
                        "payload_hash": (
                            "abcdef0123456789abcdef0123456789"
                            "abcdef0123456789abcdef0123456789"
                        ),
                        "kind": "shell.command",
                        "source_id": "bin/tool#call:nix",
                    },
                    path="bin/tool",
                    start_line=1,
                    end_line=1,
                    extractor="repo-shell",
                    extractor_version="0.1.0",
                    confidence="extracted",
                    metadata={"argv": ["nix", "build"]},
                ),
            ),
        )
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_canonical_edge_explanation",
            return_value=record,
        ):
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "explain-canonical-edge",
                        "--root-path",
                        "/tmp/fixture",
                        "--source-key",
                        "file:bin/tool",
                        "--kind",
                        "executes",
                        "--target-key",
                        "tool:nix",
                    ]
                )

        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        self.assertIn("edge:", output)
        self.assertIn("file:bin/tool", output)
        self.assertIn("identity_metadata_hash", output)
        self.assertIn(hash_text, output)
        self.assertIn("evidence:", output)
        self.assertIn("raw_observation.ordinal", output)
        self.assertIn("repo-shell", output)
        self.assertNotIn("ignored", output)
        self.assertNotIn("argv", output)

    def test_storage_explain_canonical_edge_prints_missing_json_result(self):
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_canonical_edge_explanation",
            return_value=CanonicalEdgeExplanationRecord(edge=None, evidence=()),
        ):
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "explain-canonical-edge",
                        "--root-path",
                        "/tmp/fixture",
                        "--source-key",
                        "file:bin/tool",
                        "--kind",
                        "executes",
                        "--target-key",
                        "tool:missing",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            json.loads(stdout.getvalue()),
            {
                "collections": {
                    "evidence": {
                        "limit": 50,
                        "next_offset": None,
                        "offset": 0,
                        "returned": 0,
                        "truncated": False,
                    }
                },
                "diagnostics": [],
                "result": {"edge": None, "evidence": []},
                "result_kind": "canonical_edge_explanation",
                "schema_version": 1,
            },
        )


if __name__ == "__main__":
    unittest.main()
