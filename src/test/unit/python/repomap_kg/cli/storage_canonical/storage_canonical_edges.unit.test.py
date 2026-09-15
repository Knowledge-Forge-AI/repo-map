import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from repomap_kg.cli import main
from repomap_kg.storage import CanonicalEdgeRecord, StorageSchemaError


class CliStorageCanonicalEdgesUnitTests(unittest.TestCase):
    def test_storage_canonical_edges_prints_json_records(self):
        hash_text = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        records = (
            CanonicalEdgeRecord(
                source_key="file:bin/tool",
                edge_kind="executes",
                target_key="tool:nix",
                graph_key_version=1,
                identity_metadata={},
                identity_metadata_hash=hash_text,
                metadata={"commands": ["nix"]},
                confidence="extracted",
                conflict=False,
                first_seen_run_id=10,
                last_seen_run_id=12,
            ),
        )
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_canonical_edge_records",
            return_value=records,
        ) as query:
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "edges",
                        "--root-path",
                        "/tmp/fixture",
                        "--kind",
                        "executes",
                        "--source-key",
                        "file:bin/tool",
                        "--target-key",
                        "tool:nix",
                        "--pg-database",
                        "postgres",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["items"][0]["source_key"], "file:bin/tool")
        self.assertEqual(payload["items"][0]["edge_kind"], "executes")
        self.assertEqual(payload["items"][0]["target_key"], "tool:nix")
        self.assertEqual(payload["items"][0]["identity_metadata_hash"], hash_text)
        self.assertEqual(payload["items"][0]["metadata"], {"commands": ["nix"]})
        self.assertEqual(query.call_args.args[0], ["-d", "postgres"])
        self.assertEqual(query.call_args.kwargs["root_path"], "/tmp/fixture")
        self.assertEqual(query.call_args.kwargs["kind"], "executes")
        self.assertEqual(query.call_args.kwargs["source_key"], "file:bin/tool")
        self.assertEqual(query.call_args.kwargs["target_key"], "tool:nix")
        self.assertEqual(query.call_args.kwargs["graph_key_version"], 1)
        self.assertEqual(query.call_args.kwargs["limit"], 51)
        self.assertEqual(query.call_args.kwargs["offset"], 0)

    def test_storage_canonical_edges_prints_table_records(self):
        hash_text = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        records = (
            CanonicalEdgeRecord(
                source_key="file:bin/tool",
                edge_kind="executes",
                target_key="tool:nix",
                graph_key_version=1,
                identity_metadata={},
                identity_metadata_hash=hash_text,
                metadata={"commands": ["nix"]},
                confidence="extracted",
                conflict=False,
                first_seen_run_id=None,
                last_seen_run_id=12,
            ),
        )
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_canonical_edge_records",
            return_value=records,
        ):
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "edges",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        self.assertIn("source_key", output)
        self.assertIn("file:bin/tool", output)
        self.assertIn("identity_metadata_hash", output)
        self.assertIn(hash_text, output)
        self.assertIn("last_seen_run_id", output)
        self.assertNotIn("commands", output)

    def test_storage_canonical_edges_validates_source_key(self):
        stderr = io.StringIO()

        with patch("repomap_kg.cli.query_canonical_edge_records") as query:
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "edges",
                        "--root-path",
                        "/tmp/fixture",
                        "--source-key",
                        "file:bin/tool#line:12",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("invalid source canonical key", stderr.getvalue())
        query.assert_not_called()

    def test_storage_canonical_edges_validates_target_key(self):
        stderr = io.StringIO()

        with patch("repomap_kg.cli.query_canonical_edge_records") as query:
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "edges",
                        "--root-path",
                        "/tmp/fixture",
                        "--target-key",
                        "tool:nix#line:12",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("invalid target canonical key", stderr.getvalue())
        query.assert_not_called()

    def test_storage_canonical_edges_rejects_unsupported_kind(self):
        stderr = io.StringIO()

        with patch("repomap_kg.cli.query_canonical_edge_records") as query:
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "edges",
                        "--root-path",
                        "/tmp/fixture",
                        "--kind",
                        "invokes",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("unsupported canonical edge kind", stderr.getvalue())
        query.assert_not_called()

    def test_storage_canonical_edges_rejects_unsupported_graph_key_version(self):
        stderr = io.StringIO()

        with patch("repomap_kg.cli.query_canonical_edge_records") as query:
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "edges",
                        "--root-path",
                        "/tmp/fixture",
                        "--graph-key-version",
                        "2",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("unsupported graph key version", stderr.getvalue())
        query.assert_not_called()

    def test_storage_canonical_edges_reports_query_errors(self):
        stderr = io.StringIO()

        with patch(
            "repomap_kg.cli.query_canonical_edge_records",
            side_effect=StorageSchemaError("psql did not return canonical edges"),
        ):
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "edges",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("psql did not return canonical edges", stderr.getvalue())
