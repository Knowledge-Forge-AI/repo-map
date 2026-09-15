import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from repomap_kg.cli import main
from repomap_kg.ops.ingestion.acquisition_contracts import non_publication_result


class CliSourceAcquisitionCommandUnitTests(unittest.TestCase):
    def test_sources_ingest_feed_prints_json_summary_from_config_only(self):
        from repomap_kg.ops.ingestion.source import FeedIngestionSummary

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "feed-source.toml"
            config_path.write_text("[source]\nid = \"example-news-feed\"\n")
            stdout = io.StringIO()
            expected = FeedIngestionSummary(
                source_id="example-news-feed",
                source_type="feed.rss",
                policy_status="allowed_with_limits",
                source_run_id="20260630T120000Z",
                artifact_path=".repomap/source-artifacts/example/rss.xml",
                artifact_sha256="0" * 64,
                artifact_bytes=512,
                observations=6,
                feed_observations=5,
                raw_observations=(),
                publication=non_publication_result(),
            )

            with patch(
                "repomap_kg.cli.ingest_feed_source",
                return_value=expected,
            ) as ingest:
                with redirect_stdout(stdout):
                    exit_code = main(
                        [
                            "sources",
                            "ingest-feed",
                            "--config",
                            str(config_path),
                            "--root-path",
                            "/tmp/fixture",
                            "--json",
                        ]
                    )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["source_id"], "example-news-feed")
        self.assertEqual(payload["publication"]["publication_state"], "not_published")
        self.assertEqual(payload["observations"], 6)
        ingest.assert_called_once()
        self.assertEqual(ingest.call_args.kwargs["config_path"], str(config_path))
        self.assertEqual(ingest.call_args.kwargs["root_path"], "/tmp/fixture")

    def test_sources_import_warc_prints_json_summary_from_config_only(self):
        from repomap_kg.ops.ingestion.source import WarcImportSummary

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "warc-source.toml"
            config_path.write_text("[source]\nid = \"example-warc-archive\"\n")
            stdout = io.StringIO()
            expected = WarcImportSummary(
                source_id="example-warc-archive",
                source_type="saved_page.archive",
                policy_status="allowed",
                artifact_run_id="20260630T120000Z",
                artifact_manifest_id="manifest123",
                record_count=3,
                parsed_records=3,
                skipped_records=0,
                routed_payloads=2,
                observations=12,
                raw_observations=(),
                manifest=None,
                publication=non_publication_result(),
            )

            with patch(
                "repomap_kg.cli.import_warc_source",
                return_value=expected,
            ) as import_warc:
                with redirect_stdout(stdout):
                    exit_code = main(
                        [
                            "sources",
                            "import-warc",
                            "--config",
                            str(config_path),
                            "--root-path",
                            "/tmp/fixture",
                            "--json",
                        ]
                    )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["source_id"], "example-warc-archive")
        self.assertEqual(payload["publication"]["publication_state"], "not_published")
        self.assertEqual(payload["record_count"], 3)
        self.assertEqual(payload["routed_payloads"], 2)
        import_warc.assert_called_once()
        self.assertEqual(import_warc.call_args.kwargs["config_path"], str(config_path))
        self.assertEqual(import_warc.call_args.kwargs["root_path"], "/tmp/fixture")

    def test_bulk_plan_prints_json_manifest_from_config_only(self):
        stdout = io.StringIO()
        expected = SimpleNamespace(
            to_jsonable=lambda: {
                "source_id": "bulk-fixture",
                "corpus_kind": "mixed_corpus",
                "file_count_included": 2,
                "file_count_skipped": 1,
                "no_provider_api": True,
                "no_external_fetch": True,
            }
        )

        with patch(
            "repomap_kg.cli.build_bulk_plan_from_config",
            return_value=expected,
        ) as build_plan:
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "bulk",
                        "plan",
                        "--config",
                        "/tmp/bulk.toml",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["source_id"], "bulk-fixture")
        self.assertEqual(payload["file_count_included"], 2)
        self.assertTrue(payload["no_provider_api"])
        build_plan.assert_called_once_with("/tmp/bulk.toml")

    def test_bulk_import_prints_non_publication_summary(self):
        stdout = io.StringIO()
        expected = SimpleNamespace(
            to_jsonable=lambda: {
                "source_id": "bulk-fixture",
                "corpus_kind": "mixed_corpus",
                "observations": 12,
                "publication": non_publication_result().to_jsonable(),
                "no_provider_api": True,
            }
        )

        with patch(
            "repomap_kg.cli.import_bulk_source",
            return_value=expected,
        ) as import_bulk:
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "bulk",
                        "import",
                        "--config",
                        "/tmp/bulk.toml",
                        "--root-path",
                        "/tmp/fixture",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["publication"]["publication_state"], "not_published")
        self.assertEqual(payload["observations"], 12)
        import_bulk.assert_called_once()
        self.assertEqual(import_bulk.call_args.kwargs["config_path"], "/tmp/bulk.toml")
        self.assertEqual(import_bulk.call_args.kwargs["root_path"], "/tmp/fixture")

    def test_api_plan_prints_json_manifest_from_config_only(self):
        stdout = io.StringIO()
        expected = SimpleNamespace(
            to_jsonable=lambda: {
                "source_id": "fixture-readonly-api",
                "api_source_class": "api.custom_documented_api",
                "request_count": 1,
                "no_network": True,
                "no_mutation": True,
            }
        )

        with patch(
            "repomap_kg.cli.build_api_plan_from_config",
            return_value=expected,
        ) as build_plan:
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "api",
                        "plan",
                        "--config",
                        "/tmp/api-source.toml",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["source_id"], "fixture-readonly-api")
        self.assertEqual(payload["request_count"], 1)
        self.assertTrue(payload["no_network"])
        self.assertTrue(payload["no_mutation"])
        build_plan.assert_called_once_with("/tmp/api-source.toml")

    def test_api_acquire_prints_non_publication_summary(self):
        stdout = io.StringIO()
        expected = SimpleNamespace(
            to_jsonable=lambda: {
                "source_id": "fixture-readonly-api",
                "observations": 9,
                "publication": non_publication_result().to_jsonable(),
                "no_network": True,
                "no_mutation": True,
            }
        )

        with patch(
            "repomap_kg.cli.acquire_api_source",
            return_value=expected,
        ) as acquire:
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "api",
                        "acquire",
                        "--config",
                        "/tmp/api-source.toml",
                        "--root-path",
                        "/tmp/fixture",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["publication"]["publication_state"], "not_published")
        self.assertEqual(payload["observations"], 9)
        self.assertTrue(payload["no_network"])
        acquire.assert_called_once()
        self.assertEqual(acquire.call_args.kwargs["config_path"], "/tmp/api-source.toml")
        self.assertEqual(acquire.call_args.kwargs["root_path"], "/tmp/fixture")

    def test_github_plan_prints_json_manifest_from_config_only(self):
        stdout = io.StringIO()
        expected = SimpleNamespace(
            to_jsonable=lambda: {
                "source_id": "github-public-fixture",
                "api_source_class": "api.github.repository",
                "owner": "fixture-owner",
                "repository": "fixture-repo",
                "request_count": 5,
                "fixture_transport_only": True,
                "no_network": True,
                "no_mutation": True,
            }
        )

        with patch(
            "repomap_kg.cli.build_github_api_plan_from_config",
            return_value=expected,
        ) as build_plan:
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "github",
                        "plan",
                        "--config",
                        "/tmp/github-source.toml",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["source_id"], "github-public-fixture")
        self.assertEqual(payload["api_source_class"], "api.github.repository")
        self.assertEqual(payload["owner"], "fixture-owner")
        self.assertEqual(payload["repository"], "fixture-repo")
        self.assertEqual(payload["request_count"], 5)
        self.assertTrue(payload["fixture_transport_only"])
        self.assertTrue(payload["no_network"])
        self.assertTrue(payload["no_mutation"])
        build_plan.assert_called_once_with("/tmp/github-source.toml")

    def test_github_acquire_prints_non_publication_summary(self):
        stdout = io.StringIO()
        expected = SimpleNamespace(
            to_jsonable=lambda: {
                "source_id": "github-public-fixture",
                "owner": "fixture-owner",
                "repository": "fixture-repo",
                "observations": 21,
                "publication": non_publication_result().to_jsonable(),
                "fixture_transport_only": True,
                "no_network": True,
                "no_mutation": True,
            }
        )

        with patch(
            "repomap_kg.cli.acquire_github_api_source",
            return_value=expected,
        ) as acquire:
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "github",
                        "acquire",
                        "--config",
                        "/tmp/github-source.toml",
                        "--root-path",
                        "/tmp/fixture",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["publication"]["publication_state"], "not_published")
        self.assertEqual(payload["observations"], 21)
        self.assertEqual(payload["owner"], "fixture-owner")
        self.assertTrue(payload["fixture_transport_only"])
        self.assertTrue(payload["no_network"])
        acquire.assert_called_once()
        self.assertEqual(
            acquire.call_args.kwargs["config_path"],
            "/tmp/github-source.toml",
        )
        self.assertEqual(acquire.call_args.kwargs["root_path"], "/tmp/fixture")


if __name__ == "__main__":
    unittest.main()
