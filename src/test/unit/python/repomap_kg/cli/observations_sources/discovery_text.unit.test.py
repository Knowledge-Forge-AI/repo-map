import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from repomap_kg.cli import main

class CliDiscoveryTextCommandUnitTests(unittest.TestCase):
    def test_discover_prints_text_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "src" / "main" / "python" / "app.py"
            source.parent.mkdir(parents=True)
            source.write_text("print('ok')\n")
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(["discover", str(root)])

        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout.getvalue().strip(), "discovered 2 observations")
    def test_discover_reports_profile_validation_errors(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            profile = root / "repomap-profile.toml"
            profile.write_text(
                """
[confidence_overrides]
"README.md" = "certain"
"""
            )
            stderr = io.StringIO()

            with redirect_stderr(stderr):
                exit_code = main(["discover", str(root), "--profile", str(profile)])

        self.assertEqual(exit_code, 1)
        self.assertIn("confidence_overrides", stderr.getvalue())
    def test_discover_jsonl_and_source_acquisition_commands_print_text_views(self):
        source_summary = SimpleNamespace(
            source_id="source-fixture",
            feed_observations=3,
            observations=4,
            routed_payloads=2,
        )
        plan_manifest = SimpleNamespace(
            source_id="plan-fixture",
            file_count_included=2,
            file_count_skipped=1,
            request_count=3,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            source_file = root / "src" / "main" / "python" / "app.py"
            source_file.parent.mkdir(parents=True)
            source_file.write_text("print('ok')\n", encoding="utf-8")
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["discover", str(root), "--jsonl"])
            self.assertEqual(exit_code, 0)
            json_lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
            self.assertTrue(any(item["kind"] == "file" for item in json_lines))

        patch_cases = (
            (
                "repomap_kg.cli.ingest_feed_source",
                [
                    "sources",
                    "ingest-feed",
                    "--config",
                    "/tmp/feed.toml",
                    "--root-path",
                    "/tmp/repo",
                ],
                source_summary,
                "ingested feed source source-fixture",
            ),
            (
                "repomap_kg.cli.import_archive_source",
                [
                    "sources",
                    "import-archive",
                    "--config",
                    "/tmp/archive.toml",
                    "--root-path",
                    "/tmp/repo",
                ],
                source_summary,
                "imported local artifact source source-fixture",
            ),
            (
                "repomap_kg.cli.import_warc_source",
                [
                    "sources",
                    "import-warc",
                    "--config",
                    "/tmp/warc.toml",
                    "--root-path",
                    "/tmp/repo",
                ],
                source_summary,
                "imported local WARC source source-fixture",
            ),
            (
                "repomap_kg.cli.build_bulk_plan_from_config",
                ["bulk", "plan", "--config", "/tmp/bulk.toml"],
                plan_manifest,
                "planned bulk source plan-fixture",
            ),
            (
                "repomap_kg.cli.import_bulk_source",
                [
                    "bulk",
                    "import",
                    "--config",
                    "/tmp/bulk.toml",
                    "--root-path",
                    "/tmp/repo",
                ],
                source_summary,
                "imported bulk source source-fixture",
            ),
            (
                "repomap_kg.cli.build_api_plan_from_config",
                ["api", "plan", "--config", "/tmp/api.toml"],
                plan_manifest,
                "planned API source plan-fixture",
            ),
            (
                "repomap_kg.cli.acquire_api_source",
                [
                    "api",
                    "acquire",
                    "--config",
                    "/tmp/api.toml",
                    "--root-path",
                    "/tmp/repo",
                ],
                source_summary,
                "acquired API source source-fixture",
            ),
            (
                "repomap_kg.cli.build_github_api_plan_from_config",
                ["github", "plan", "--config", "/tmp/github.toml"],
                plan_manifest,
                "planned GitHub API source plan-fixture",
            ),
            (
                "repomap_kg.cli.acquire_github_api_source",
                [
                    "github",
                    "acquire",
                    "--config",
                    "/tmp/github.toml",
                    "--root-path",
                    "/tmp/repo",
                ],
                source_summary,
                "acquired GitHub API source source-fixture",
            ),
        )
        for target, argv, return_value, expected in patch_cases:
            with self.subTest(argv=argv):
                stdout = io.StringIO()
                with patch(target, return_value=return_value):
                    with redirect_stdout(stdout):
                        exit_code = main(argv)
                self.assertEqual(exit_code, 0)
                self.assertIn(expected, stdout.getvalue())
