import io
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

from repomap_kg.cli import main


class CliSourceAcquisitionCommandBoundariesUnitTests(unittest.TestCase):
    def test_sources_ingest_feed_rejects_arbitrary_url_argument(self):
        stderr = io.StringIO()

        with redirect_stderr(stderr):
            with self.assertRaises(SystemExit):
                main(
                    [
                        "sources",
                        "ingest-feed",
                        "--config",
                        "/tmp/feed-source.toml",
                        "--url",
                        "https://example.invalid/rss.xml",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertIn("unrecognized arguments: --url", stderr.getvalue())

    def test_sources_import_warc_rejects_arbitrary_url_argument(self):
        stderr = io.StringIO()

        with redirect_stderr(stderr):
            with self.assertRaises(SystemExit):
                main(
                    [
                        "sources",
                        "import-warc",
                        "--config",
                        "/tmp/warc-source.toml",
                        "--url",
                        "https://example.invalid/archive.warc",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertIn("unrecognized arguments: --url", stderr.getvalue())

    def test_bulk_plan_reports_policy_errors(self):
        from repomap_kg.ops.ingestion.bulk import BulkPolicyError

        stderr = io.StringIO()
        with patch(
            "repomap_kg.cli.build_bulk_plan_from_config",
            side_effect=BulkPolicyError("source policy status blocked"),
        ):
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "bulk",
                        "plan",
                        "--config",
                        "/tmp/bulk.toml",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("source policy status blocked", stderr.getvalue())

    def test_bulk_import_rejects_arbitrary_root_argument_substitution(self):
        stderr = io.StringIO()

        with redirect_stderr(stderr):
            with self.assertRaises(SystemExit):
                main(
                    [
                        "bulk",
                        "import",
                        "--config",
                        "/tmp/bulk.toml",
                        "--url",
                        "https://example.invalid/export",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertIn("unrecognized arguments: --url", stderr.getvalue())

    def test_api_plan_reports_policy_errors(self):
        from repomap_kg.ops.ingestion.api import ApiPolicyError

        stderr = io.StringIO()
        with patch(
            "repomap_kg.cli.build_api_plan_from_config",
            side_effect=ApiPolicyError("source policy status blocked"),
        ):
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "api",
                        "plan",
                        "--config",
                        "/tmp/api-source.toml",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("source policy status blocked", stderr.getvalue())

    def test_api_acquire_rejects_arbitrary_url_argument(self):
        stderr = io.StringIO()

        with redirect_stderr(stderr):
            with self.assertRaises(SystemExit):
                main(
                    [
                        "api",
                        "acquire",
                        "--config",
                        "/tmp/api-source.toml",
                        "--url",
                        "https://example.invalid/items",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertIn("unrecognized arguments: --url", stderr.getvalue())

    def test_github_plan_reports_policy_errors(self):
        from repomap_kg.ops.ingestion.github_api import GitHubApiPolicyError

        stderr = io.StringIO()
        with patch(
            "repomap_kg.cli.build_github_api_plan_from_config",
            side_effect=GitHubApiPolicyError("source policy status blocked"),
        ):
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "github",
                        "plan",
                        "--config",
                        "/tmp/github-source.toml",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("source policy status blocked", stderr.getvalue())

    def test_github_acquire_rejects_arbitrary_url_argument(self):
        stderr = io.StringIO()

        with redirect_stderr(stderr):
            with self.assertRaises(SystemExit):
                main(
                    [
                        "github",
                        "acquire",
                        "--config",
                        "/tmp/github-source.toml",
                        "--url",
                        "https://github.com/fixture-owner/fixture-repo",
                        "--root-path",
                        "/tmp/fixture",
                    ]
                )

        self.assertIn("unrecognized arguments: --url", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
