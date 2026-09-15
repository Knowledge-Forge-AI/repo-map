import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from repomap_kg.cli.parser import build_parser
else:
    from repomap_kg.cli import build_parser
from repomap_kg.cli import main
from repomap_kg.storage import (
    CanonicalEdgeRecord,
    CanonicalNeighborhoodRecord,
    CanonicalNodeRecord,
    StorageSchemaError,
)


class CliStorageCanonicalNeighborhoodUnitTests(unittest.TestCase):
    def test_storage_canonical_neighborhood_prints_json_record(self):
        hash_text = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        record = CanonicalNeighborhoodRecord(
            center=CanonicalNodeRecord(
                canonical_key="tool:nix",
                graph_key_version=1,
                kind="tool",
                display_name="nix",
                confidence="extracted",
                conflict=False,
                metadata={},
                first_seen_run_id=10,
                last_seen_run_id=12,
            ),
            nodes=(
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
            ),
            edges=(
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
            ),
        )
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_canonical_neighborhood",
            return_value=record,
        ) as query:
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "neighborhood",
                        "--root-path",
                        "/tmp/fixture",
                        "--node",
                        "tool:nix",
                        "--direction",
                        "in",
                        "--pg-database",
                        "postgres",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["result_kind"], "canonical_neighborhood")
        self.assertEqual(payload["result"]["center"]["canonical_key"], "tool:nix")
        self.assertEqual(
            payload["result"]["nodes"][0]["canonical_key"],
            "file:bin/tool",
        )
        self.assertEqual(
            payload["result"]["edges"][0]["identity_metadata_hash"],
            hash_text,
        )
        self.assertEqual(payload["collections"]["nodes"]["returned"], 1)
        self.assertEqual(payload["collections"]["edges"]["returned"], 1)
        self.assertEqual(query.call_args.args[0], ["-d", "postgres"])
        self.assertEqual(query.call_args.kwargs["root_path"], "/tmp/fixture")
        self.assertEqual(query.call_args.kwargs["node"], "tool:nix")
        self.assertEqual(query.call_args.kwargs["direction"], "in")
        self.assertEqual(query.call_args.kwargs["depth"], 1)
        self.assertEqual(query.call_args.kwargs["graph_key_version"], 1)
        self.assertEqual(query.call_args.kwargs["node_limit"], 51)
        self.assertEqual(query.call_args.kwargs["node_offset"], 0)
        self.assertEqual(query.call_args.kwargs["edge_limit"], 51)
        self.assertEqual(query.call_args.kwargs["edge_offset"], 0)

    def test_storage_canonical_neighborhood_prints_table_record(self):
        hash_text = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        record = CanonicalNeighborhoodRecord(
            center=CanonicalNodeRecord(
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
            nodes=(
                CanonicalNodeRecord(
                    canonical_key="file:bin/tool",
                    graph_key_version=1,
                    kind="file",
                    display_name="bin/tool",
                    confidence="extracted",
                    conflict=False,
                    metadata={},
                    first_seen_run_id=10,
                    last_seen_run_id=12,
                ),
            ),
            edges=(
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
            ),
        )
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_canonical_neighborhood",
            return_value=record,
        ):
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "neighborhood",
                        "--root-path",
                        "/tmp/fixture",
                        "--node",
                        "tool:nix",
                    ]
                )

        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        self.assertIn("center: tool:nix", output)
        self.assertIn("Nodes:", output)
        self.assertIn("file:bin/tool", output)
        self.assertIn("Edges:", output)
        self.assertIn("identity_metadata_hash", output)
        self.assertIn(hash_text, output)
        self.assertNotIn("ignored", output)
        self.assertNotIn("commands", output)

    def test_storage_canonical_neighborhood_prints_missing_json_result(self):
        stdout = io.StringIO()

        with patch(
            "repomap_kg.cli.query_canonical_neighborhood",
            return_value=CanonicalNeighborhoodRecord(
                center=None,
                nodes=(),
                edges=(),
            ),
        ):
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "storage",
                        "neighborhood",
                        "--root-path",
                        "/tmp/fixture",
                        "--node",
                        "tool:missing",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            json.loads(stdout.getvalue()),
            {
                "collections": {
                    "edges": {
                        "limit": 50,
                        "next_offset": None,
                        "offset": 0,
                        "returned": 0,
                        "truncated": False,
                    },
                    "nodes": {
                        "limit": 50,
                        "next_offset": None,
                        "offset": 0,
                        "returned": 0,
                        "truncated": False,
                    },
                },
                "diagnostics": [],
                "result": {"center": None, "nodes": [], "edges": []},
                "result_kind": "canonical_neighborhood",
                "schema_version": 1,
            },
        )

    def test_storage_canonical_neighborhood_validates_node_key(self):
        stderr = io.StringIO()

        with patch("repomap_kg.cli.query_canonical_neighborhood") as query:
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "neighborhood",
                        "--root-path",
                        "/tmp/fixture",
                        "--node",
                        "tool:nix#line:12",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("invalid node canonical key", stderr.getvalue())
        query.assert_not_called()

    def test_storage_canonical_neighborhood_rejects_unsupported_graph_key_version(
        self,
    ):
        stderr = io.StringIO()

        with patch("repomap_kg.cli.query_canonical_neighborhood") as query:
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "neighborhood",
                        "--root-path",
                        "/tmp/fixture",
                        "--node",
                        "tool:nix",
                        "--graph-key-version",
                        "2",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("unsupported graph key version", stderr.getvalue())
        query.assert_not_called()

    def test_storage_canonical_neighborhood_rejects_depth_above_one(self):
        stderr = io.StringIO()

        with patch("repomap_kg.cli.query_canonical_neighborhood") as query:
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "neighborhood",
                        "--root-path",
                        "/tmp/fixture",
                        "--node",
                        "tool:nix",
                        "--depth",
                        "2",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("neighborhood only supports depth 1", stderr.getvalue())
        query.assert_not_called()

    def test_storage_canonical_neighborhood_rejects_invalid_direction(self):
        parser = build_parser()
        stderr = io.StringIO()

        with redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as caught:
                parser.parse_args(
                    [
                        "storage",
                        "neighborhood",
                        "--root-path",
                        "/tmp/fixture",
                        "--node",
                        "tool:nix",
                        "--direction",
                        "sideways",
                    ]
                )

        self.assertEqual(caught.exception.code, 2)

    def test_storage_canonical_neighborhood_reports_query_errors(self):
        stderr = io.StringIO()

        with patch(
            "repomap_kg.cli.query_canonical_neighborhood",
            side_effect=StorageSchemaError(
                "psql did not return canonical neighborhood"
            ),
        ):
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "neighborhood",
                        "--root-path",
                        "/tmp/fixture",
                        "--node",
                        "tool:nix",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("psql did not return canonical neighborhood", stderr.getvalue())
