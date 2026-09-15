import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from repomap_kg.cli import main
from repomap_kg.storage import CanonicalNodeRecord, StorageSchemaError


class CliStorageCanonicalNodesUnitTests(unittest.TestCase):
    def test_storage_canonical_nodes_prints_json_records(self):
        records = (
            CanonicalNodeRecord(
                canonical_key="file:bin/tool",
                graph_key_version=1,
                kind="file",
                display_name="bin/tool",
                confidence="extracted",
                conflict=False,
                metadata={"role": "entrypoint"},
                first_seen_run_id=10,
                last_seen_run_id=12,
            ),
        )
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_canonical_node_records",
            return_value=records,
        ) as query:
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "nodes",
                        "--root-path",
                        "/tmp/fixture",
                        "--path-prefix",
                        "bin/",
                        "--pg-database",
                        "postgres",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["items"][0]["canonical_key"], "file:bin/tool")
        self.assertEqual(payload["items"][0]["metadata"], {"role": "entrypoint"})
        self.assertEqual(query.call_args.args[0], ["-d", "postgres"])
        self.assertEqual(query.call_args.kwargs["root_path"], "/tmp/fixture")
        self.assertEqual(query.call_args.kwargs["kind"], "file")
        self.assertIsNone(query.call_args.kwargs["canonical_key"])
        self.assertEqual(query.call_args.kwargs["path_prefix"], "bin/")
        self.assertEqual(query.call_args.kwargs["graph_key_version"], 1)
        self.assertEqual(query.call_args.kwargs["limit"], 51)
        self.assertEqual(query.call_args.kwargs["offset"], 0)

    def test_storage_canonical_nodes_prints_table_records(self):
        records = (
            CanonicalNodeRecord(
                canonical_key="tool:nix",
                graph_key_version=1,
                kind="tool",
                display_name="nix",
                confidence="manual",
                conflict=False,
                metadata={"ignored": True},
                first_seen_run_id=None,
                last_seen_run_id=12,
            ),
        )
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_canonical_node_records",
            return_value=records,
        ):
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "nodes",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        self.assertIn("canonical_key", output)
        self.assertIn("tool:nix", output)
        self.assertIn("last_seen_run_id", output)
        self.assertNotIn("metadata", output)

    def test_storage_canonical_nodes_validates_canonical_key(self):
        stderr = io.StringIO()

        with patch("repomap_kg.cli.query_canonical_node_records") as query:
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "nodes",
                        "--root-path",
                        "/tmp/fixture",
                        "--canonical-key",
                        "file:bin/tool#line:12",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("invalid canonical key", stderr.getvalue())
        query.assert_not_called()

    def test_storage_canonical_nodes_rejects_unsupported_graph_key_version(self):
        stderr = io.StringIO()

        with patch("repomap_kg.cli.query_canonical_node_records") as query:
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "nodes",
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

    def test_storage_canonical_nodes_rejects_path_prefix_for_non_file_kind(self):
        stderr = io.StringIO()

        with patch("repomap_kg.cli.query_canonical_node_records") as query:
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "nodes",
                        "--root-path",
                        "/tmp/fixture",
                        "--kind",
                        "tool",
                        "--path-prefix",
                        "bin/",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("path-prefix only applies", stderr.getvalue())
        query.assert_not_called()

    def test_storage_canonical_nodes_reports_query_errors(self):
        stderr = io.StringIO()

        with patch(
            "repomap_kg.cli.query_canonical_node_records",
            side_effect=StorageSchemaError("psql did not return canonical nodes"),
        ):
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "nodes",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("psql did not return canonical nodes", stderr.getvalue())
