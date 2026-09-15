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
from repomap_kg.ops.graph_files import (
    GraphFilePage,
    OpsRefreshError,
    graph_file_record_from_payload,
)


class OpsGraphFilesCliUnitTests(unittest.TestCase):
    def test_parser_registers_new_contract_and_removes_storage_files(self):
        parser = build_parser()
        args = parser.parse_args(
            [
                "ops",
                "graph-files",
                "--graph",
                "public",
                "--path-prefix",
                "src",
                "--language",
                "python",
                "--role",
                "source",
                "--generated",
                "exclude",
                "--executable",
                "only",
                "--observation-state",
                "observed",
                "--ambiguity",
                "exclude",
                "--limit",
                "100",
                "--offset",
                "50",
                "--json",
            ]
        )
        self.assertEqual(args.ops_command, "graph-files")
        self.assertEqual(args.graph, "public")
        self.assertEqual(args.limit, 100)
        self.assertEqual(args.offset, 50)
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                parser.parse_args(
                    ["storage", "files", "--root-path", "/public/repository"]
                )
        self.assertEqual(raised.exception.code, 2)

    def test_parser_rejects_invalid_ranges_and_combined_paths(self):
        parser = build_parser()
        cases = (
            ["ops", "graph-files", "--graph", "public", "--limit", "201"],
            ["ops", "graph-files", "--graph", "public", "--offset", "-1"],
            [
                "ops",
                "graph-files",
                "--graph",
                "public",
                "--path",
                "a",
                "--path-prefix",
                "a",
            ],
        )
        for arguments in cases:
            with self.subTest(arguments=arguments), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    parser.parse_args(arguments)
            self.assertEqual(raised.exception.code, 2)

    def test_json_dispatch_forwards_filters_and_emits_stable_envelope(self):
        record = graph_file_record_from_payload(
            {
                "canonical_key": "file:src/app.py",
                "graph_key_version": 1,
                "confidence": "extracted",
                "conflict": False,
                "metadata": {
                    "language": "python",
                    "role": "entrypoint",
                    "generated": False,
                    "executable": True,
                },
                "evidence_count": 2,
                "file_observation_count": 1,
                "link_kinds": ["observed"],
            }
        )
        page = GraphFilePage(
            graph_id="public",
            repository_name="stable-repository",
            records=(record,),
            limit=50,
            offset=0,
            has_more=False,
        )
        stdout = io.StringIO()
        with (
            patch("repomap_kg.cli.load_ops_config_from_args", return_value="config"),
            patch("repomap_kg.cli.query_graph_files", return_value=page) as query,
            redirect_stdout(stdout),
        ):
            exit_code = main(
                [
                    "ops",
                    "graph-files",
                    "--graph",
                    "public",
                    "--language",
                    "python",
                    "--role",
                    "entrypoint",
                    "--observation-state",
                    "observed",
                    "--limit",
                    "50",
                    "--json",
                ]
            )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["command"], "graph-files")
        self.assertEqual(payload["graph"]["id"], "public")
        self.assertEqual(payload["pagination"]["returned"], 1)
        self.assertEqual(payload["files"][0]["canonical_key"], "file:src/app.py")
        self.assertEqual(query.call_args.args[:2], ("config", "public"))
        self.assertEqual(query.call_args.kwargs["filters"].language, "python")
        self.assertEqual(query.call_args.kwargs["filters"].role, "entrypoint")
        self.assertEqual(
            query.call_args.kwargs["filters"].observation_state,
            "observed",
        )
        self.assertEqual(query.call_args.kwargs["limit"], 50)

    def test_table_dispatch_and_storage_errors_are_bounded(self):
        page = GraphFilePage(
            graph_id="public",
            repository_name="stable-repository",
            records=(),
            limit=50,
            offset=0,
            has_more=False,
        )
        stdout = io.StringIO()
        with (
            patch("repomap_kg.cli.load_ops_config_from_args", return_value="config"),
            patch("repomap_kg.cli.query_graph_files", return_value=page),
            redirect_stdout(stdout),
        ):
            self.assertEqual(
                main(["ops", "graph-files", "--graph", "public"]),
                0,
            )
        self.assertIn("RepoMap canonical graph files", stdout.getvalue())
        self.assertIn("canonical_key", stdout.getvalue())

        stderr = io.StringIO()
        with (
            patch("repomap_kg.cli.load_ops_config_from_args", return_value="config"),
            patch(
                "repomap_kg.cli.query_graph_files",
                side_effect=OpsRefreshError("failed at /Users/private/path"),
            ),
            redirect_stderr(stderr),
        ):
            self.assertEqual(
                main(["ops", "graph-files", "--graph", "public"]),
                1,
            )
        self.assertIn("[redacted-path]", stderr.getvalue())
        self.assertNotIn("/Users/private", stderr.getvalue())
