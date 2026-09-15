import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from typing import TYPE_CHECKING
from repomap_kg.cli import main

if TYPE_CHECKING:
    from repomap_kg.cli.parser import build_parser
    from repomap_kg.observations.raw import RawObservation, write_observations_jsonl
else:
    from repomap_kg.cli import build_parser
    from repomap_kg.observations import RawObservation, write_observations_jsonl
from repomap_kg.storage import (
    LoadSummary,
    StorageSchemaError,
)
from repomap_kg.storage.readback_driver import READBACK_DRIVER_ENV

class CliStorageCommonUnitTests(unittest.TestCase):
    def test_storage_subcommands_accept_shared_connection_options(self):
        parser = build_parser()
        cases = (
            (
                "load-files",
                [
                    "raw-observations.jsonl",
                    "--repository-name",
                    "fixture",
                    "--root-path",
                    "/tmp/fixture",
                ],
            ),
            (
                "explain-canonical-edge",
                [
                    "--root-path",
                    "/tmp/fixture",
                    "--source-key",
                    "file:bin/tool",
                    "--kind",
                    "executes",
                    "--target-key",
                    "tool:nix",
                ],
            ),
            ("nodes", ["--root-path", "/tmp/fixture"]),
            ("neighborhood", ["--root-path", "/tmp/fixture", "--node", "tool:nix"]),
            (
                "file-neighborhood",
                ["--root-path", "/tmp/fixture", "--path", "bin/tool"],
            ),
            ("edges", ["--root-path", "/tmp/fixture"]),
            ("host-mutators", ["--root-path", "/tmp/fixture"]),
            ("host-mutators-summary", ["--root-path", "/tmp/fixture"]),
            ("summary", ["--root-path", "/tmp/fixture"]),
            ("ruby-summary", ["--root-path", "/tmp/fixture"]),
            ("js-summary", ["--root-path", "/tmp/fixture"]),
            ("js-framework-summary", ["--root-path", "/tmp/fixture"]),
            ("terraform-summary", ["--root-path", "/tmp/fixture"]),
            ("python-summary", ["--root-path", "/tmp/fixture"]),
            ("nix-summary", ["--root-path", "/tmp/fixture"]),
            ("email-summary", ["--root-path", "/tmp/fixture"]),
        )

        for subcommand, required_args in cases:
            with self.subTest(subcommand=subcommand):
                args = parser.parse_args(
                    [
                        "storage",
                        subcommand,
                        *required_args,
                        "--pg-host",
                        "/tmp/socket",
                        "--pg-port",
                        "5432",
                        "--pg-user",
                        "repo_map_test",
                        "--pg-database",
                        "postgres",
                        "--psql-command",
                        "/bin/psql",
                    ]
                )

                self.assertEqual(args.pg_host, "/tmp/socket")
                self.assertEqual(args.pg_port, "5432")
                self.assertEqual(args.pg_user, "repo_map_test")
                self.assertEqual(args.pg_database, "postgres")
                self.assertEqual(args.psql_command, "/bin/psql")

    def test_smoke_harden1_storage_cli_connection_errors_are_sanitized(self):
        synthetic_root = "/Users/synthetic-user/private-repo"
        synthetic_values = (
            "synthetic-private-host.invalid",
            "synthetic_private_database",
            "synthetic_private_user",
            synthetic_root,
            "postgresql://synthetic-user:synthetic-secret@example.invalid/db",
            "synthetic-secret-token",
            "/private/tmp/synthetic/repo-map",
            "synthetic-user",
            "synthetic-secret",
        )
        query_error = StorageSchemaError(
            "storage connection failed: "
            "host=synthetic-private-host.invalid "
            "user=synthetic_private_user "
            "database=synthetic_private_database "
            "root=/Users/synthetic-user/private-repo "
            "url=postgresql://synthetic-user:synthetic-secret@example.invalid/db "
            "token=synthetic-secret-token "
            "socket=/private/tmp/synthetic/repo-map"
        )
        common_connection_args = [
            "--root-path",
            synthetic_root,
            "--pg-host",
            "synthetic-private-host.invalid",
            "--pg-port",
            "5432",
            "--pg-user",
            "synthetic_private_user",
            "--pg-database",
            "synthetic_private_database",
            "--psql-command",
            "/private/tmp/synthetic/repo-map/psql",
            "--json",
        ]
        cases = (
            (
                "storage summary",
                "repomap_kg.cli.query_canonical_storage_summary",
                ["storage", "summary", *common_connection_args],
            ),
            (
                "storage nodes",
                "repomap_kg.cli.query_canonical_node_records",
                [
                    "storage",
                    "nodes",
                    "--kind",
                    "file",
                    *common_connection_args,
                ],
            ),
            (
                "storage edges",
                "repomap_kg.cli.query_canonical_edge_records",
                [
                    "storage",
                    "edges",
                    "--kind",
                    "defines",
                    *common_connection_args,
                ],
            ),
            (
                "storage python-summary",
                "repomap_kg.cli.query_python_summary",
                ["storage", "python-summary", *common_connection_args],
            ),
            (
                "storage bulk-summary",
                "repomap_kg.cli.query_bulk_summary",
                ["storage", "bulk-summary", *common_connection_args],
            ),
            (
                "storage nix-summary",
                "repomap_kg.cli.query_nix_summary",
                ["storage", "nix-summary", *common_connection_args],
            ),
        )

        for label, patch_target, argv in cases:
            with self.subTest(label=label):
                stdout = io.StringIO()
                stderr = io.StringIO()
                with patch(patch_target, side_effect=query_error):
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        exit_code = main(argv)

                rendered = f"{stdout.getvalue()}\n{stderr.getvalue()}"
                self.assertEqual(exit_code, 1)
                self.assertEqual(stdout.getvalue(), "")
                self.assertIn("ERROR:", stderr.getvalue())
                self.assertIn("storage connection failed", stderr.getvalue())
                self.assertLess(len(stderr.getvalue()), 500)
                for synthetic_value in synthetic_values:
                    self.assertNotIn(synthetic_value, rendered)

    def test_psycopg7_storage_cli_driver_error_is_sanitized(self):
        synthetic_root = "/Users/synthetic-user/private-repo"
        synthetic_values = (
            "synthetic-private-host.invalid",
            "synthetic_private_database",
            "synthetic_private_user",
            synthetic_root,
            "postgresql://synthetic-user:synthetic-secret@example.invalid/db",
            "synthetic-secret",
            "/private/tmp/synthetic/repo-map",
            "synthetic-user",
        )
        previous_driver = os.environ.get(READBACK_DRIVER_ENV)
        os.environ[READBACK_DRIVER_ENV] = (
            "postgresql://synthetic-user:synthetic-secret@example.invalid/db"
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        try:
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "summary",
                        "--root-path",
                        synthetic_root,
                        "--pg-host",
                        "synthetic-private-host.invalid",
                        "--pg-port",
                        "5432",
                        "--pg-user",
                        "synthetic_private_user",
                        "--pg-database",
                        "synthetic_private_database",
                        "--psql-command",
                        "/private/tmp/synthetic/repo-map/psql",
                        "--json",
                    ]
                )
        finally:
            if previous_driver is None:
                os.environ.pop(READBACK_DRIVER_ENV, None)
            else:
                os.environ[READBACK_DRIVER_ENV] = previous_driver

        rendered = f"{stdout.getvalue()}\n{stderr.getvalue()}"
        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("unsupported storage readback driver", stderr.getvalue())
        self.assertLess(len(stderr.getvalue()), 500)
        for synthetic_value in synthetic_values:
            self.assertNotIn(synthetic_value, rendered)

    def test_storage_load_files_prints_json_summary(self):
        observation = RawObservation(
            kind="file",
            source_id="README.md",
            path="README.md",
            confidence="extracted",
            extractor="fixture-discovery",
            extractor_version="0.1.0",
            metadata={
                "language": "markdown",
                "role": "documentation",
                "content_hash": "0" * 64,
                "generated": False,
                "executable": False,
            },
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = Path(tmpdir) / "raw-observations.jsonl"
            write_observations_jsonl([observation], jsonl_path)
            stdout = io.StringIO()

            with patch(
                "repomap_kg.cli.publish_observation_generation",
                return_value=LoadSummary(repository_id=7, run_id=11, files=1),
            ) as load:
                with redirect_stdout(stdout):
                    exit_code = main(
                        [
                            "storage",
                            "load-files",
                            str(jsonl_path),
                            "--repository-name",
                            "fixture",
                            "--root-path",
                            "/tmp/fixture",
                            "--pg-host",
                            "/tmp/socket",
                            "--pg-port",
                            "5432",
                            "--pg-user",
                            "repo_map_test",
                            "--pg-database",
                            "postgres",
                            "--psql-command",
                            "/bin/psql",
                            "--json",
                        ]
                    )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["repository_id"], 7)
        self.assertEqual(payload["files"], 1)
        load.assert_called_once()
        self.assertEqual(
            load.call_args.args[0],
            [
                "-h",
                "/tmp/socket",
                "-p",
                "5432",
                "-U",
                "repo_map_test",
                "-d",
                "postgres",
            ],
        )

    def test_storage_load_files_reports_loader_errors(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = Path(tmpdir) / "raw-observations.jsonl"
            write_observations_jsonl([], jsonl_path)
            stderr = io.StringIO()

            with patch(
                "repomap_kg.cli.publish_observation_generation",
                side_effect=StorageSchemaError("psql did not return a summary"),
            ):
                with redirect_stderr(stderr):
                    exit_code = main(
                        [
                            "storage",
                            "load-files",
                            str(jsonl_path),
                            "--repository-name",
                            "fixture",
                            "--root-path",
                            "/tmp/fixture",
                            "--json",
                        ]
                    )

        self.assertEqual(exit_code, 1)
        self.assertIn("psql did not return", stderr.getvalue())
