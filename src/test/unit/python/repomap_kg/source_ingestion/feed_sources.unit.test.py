from email.message import Message
import io
import json
import tempfile
import urllib.error
from pathlib import Path

from repomap_test_support.source_ingestion import (
    ATOM_BODY,
    FakeOpener,
    FakeResponse,
    JSON_FEED_BODY,
    RSS_BODY,
    SourceIngestionUnitTestCase,
)

from repomap_kg.ops.ingestion.source import (
    SourceAcquisitionError,
    SourcePolicyError,
    fetch_feed_source,
    ingest_feed_source,
    load_feed_source_config,
)


class FeedSourceIngestionUnitTests(SourceIngestionUnitTestCase):
    def test_allowed_feed_source_fetches_configured_url_and_records_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            config = self.write_config(root / "rss-source.toml")
            calls: list[str] = []

            summary = ingest_feed_source(
                config,
                root_path=root,
                fetcher=self.fetcher_returning(RSS_BODY, calls=calls),
                clock=self.fixed_clock,
            )

        self.assertEqual(calls, ["https://example.invalid/rss.xml"])
        self.assertEqual(summary.source_id, "example-news-feed")
        self.assertEqual(summary.source_type, "feed.rss")
        self.assertEqual(summary.policy_status, "allowed_with_limits")
        self.assertEqual(summary.observations, 7)
        self.assertEqual(summary.publication.publication_state, "not_published")
        self.assertTrue(summary.artifact_path.endswith("rss.xml"))
        self.assertEqual(summary.artifact_bytes, len(RSS_BODY))
        self.assertEqual(len(summary.artifact_sha256), 64)
        payload = json.dumps(
            [observation.to_dict() for observation in summary.raw_observations],
            sort_keys=True,
        )
        self.assertIn('"source_id_configured": "example-news-feed"', payload)
        self.assertIn('"source_run_id": "20260630T120000Z"', payload)
        self.assertIn('"source_artifact_sha256"', payload)
        self.assertNotIn("fixture-secret", payload)

    def test_blocked_and_manual_review_sources_stop_before_fetch(self):
        for status in ("blocked_terms_risk", "manual_review_required"):
            with self.subTest(status=status):
                with tempfile.TemporaryDirectory() as tmpdir:
                    root = Path(tmpdir) / "repo"
                    root.mkdir()
                    config = self.write_config(
                        root / f"{status}.toml",
                        policy_status=status,
                    )
                    calls: list[str] = []

                    with self.assertRaises(SourcePolicyError):
                        ingest_feed_source(
                            config,
                            root_path=root,
                            fetcher=self.fetcher_returning(RSS_BODY, calls=calls),
                            clock=self.fixed_clock,
                        )

                self.assertEqual(calls, [])

    def test_policy_validation_rejects_unknown_source_type_and_missing_timeout(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            unknown_type = self.write_config(
                root / "unknown-type.toml",
                source_type="unknown",
            )
            missing_timeout = self.write_config(
                root / "missing-timeout.toml",
                timeout_seconds=None,
            )
            zero_artifact_bytes = self.write_config(
                root / "zero-artifact-bytes.toml",
                max_artifact_bytes=0,
            )

            with self.assertRaisesRegex(SourcePolicyError, "source type"):
                load_feed_source_config(unknown_type)
            with self.assertRaisesRegex(SourcePolicyError, "timeout_seconds"):
                load_feed_source_config(missing_timeout)
            with self.assertRaisesRegex(SourcePolicyError, "positive integer"):
                load_feed_source_config(zero_artifact_bytes)

    def test_rejects_raw_url_as_source_id_and_secret_bearing_url(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            raw_url_id = self.write_config(
                root / "raw-url-id.toml",
                source_id="https://example.invalid/rss.xml",
            )
            credential_url = self.write_config(
                root / "credential-url.toml",
                url="https://user:fixture-secret@example.invalid/rss.xml",
            )

            with self.assertRaisesRegex(SourcePolicyError, "source id"):
                load_feed_source_config(raw_url_id)
            with self.assertRaisesRegex(SourcePolicyError, "credentials"):
                load_feed_source_config(credential_url)

    def test_max_artifact_bytes_is_enforced_before_extraction(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            config = self.write_config(root / "small.toml", max_artifact_bytes=8)
            with self.assertRaises(SourceAcquisitionError):
                ingest_feed_source(
                    config,
                    root_path=root,
                    fetcher=self.fetcher_returning(RSS_BODY),
                    clock=self.fixed_clock,
                )

    def test_redirect_response_is_rejected_without_fetching_redirect_target(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            config = self.write_config(root / "redirect.toml")

            with self.assertRaisesRegex(SourceAcquisitionError, "redirect"):
                ingest_feed_source(
                    config,
                    root_path=root,
                    fetcher=self.fetcher_returning(b"", status=302),
                    clock=self.fixed_clock,
                )

    def test_default_fetcher_uses_configured_timeout_method_and_user_agent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_feed_source_config(self.write_config(root / "rss.toml"))
            opener = FakeOpener(
                FakeResponse(200, b"<rss />", {"content-type": "text/xml"}),
            )

            response = fetch_feed_source(config, opener=opener)

        self.assertEqual(response.status, 200)
        self.assertEqual(response.body, b"<rss />")
        self.assertEqual(response.headers["content-type"], "text/xml")
        self.assertEqual(opener.timeout, 10)
        assert opener.request is not None
        self.assertEqual(opener.request.get_method(), "GET")
        self.assertEqual(
            dict(opener.request.header_items())["User-agent"],
            "RepoMap feed ingestion test fixture",
        )

    def test_default_fetcher_captures_http_error_without_following_redirect(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_feed_source_config(self.write_config(root / "rss.toml"))
            headers = Message()
            headers["location"] = "https://example.invalid/redirect"
            opener = FakeOpener(
                urllib.error.HTTPError(
                    config.url,
                    302,
                    "Found",
                    headers,
                    io.BytesIO(b"redirect"),
                ),
            )

            response = fetch_feed_source(config, opener=opener)

        self.assertEqual(response.status, 302)
        self.assertEqual(response.body, b"redirect")
        self.assertEqual(
            response.headers["location"],
            "https://example.invalid/redirect",
        )

    def test_default_fetcher_wraps_url_errors(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_feed_source_config(self.write_config(root / "rss.toml"))
            opener = FakeOpener(urllib.error.URLError("network unavailable"))

            with self.assertRaisesRegex(SourceAcquisitionError, "network unavailable"):
                fetch_feed_source(config, opener=opener)

    def test_fetched_atom_and_json_feed_artifacts_use_rss1_extractor(self):
        cases = (
            ("feed.atom", "atom.xml", ATOM_BODY, "atom"),
            ("feed.json", "feed.json", JSON_FEED_BODY, "json-feed"),
        )
        for source_type, artifact_name, body, expected_format in cases:
            with self.subTest(source_type=source_type):
                with tempfile.TemporaryDirectory() as tmpdir:
                    root = Path(tmpdir) / "repo"
                    root.mkdir()
                    config = self.write_config(
                        root / f"{source_type}.toml",
                        source_type=source_type,
                    )
                    summary = ingest_feed_source(
                        config,
                        root_path=root,
                        fetcher=self.fetcher_returning(body),
                        clock=self.fixed_clock,
                    )

                self.assertTrue(summary.artifact_path.endswith(artifact_name))
                documents = [
                    observation
                    for observation in summary.raw_observations
                    if observation.kind == "feed.document"
                ]
                self.assertEqual(documents[0].metadata["feed_format"], expected_format)

    def test_malformed_fetched_feed_remains_safe_parse_observation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            config = self.write_config(root / "malformed.toml")
            summary = ingest_feed_source(
                config,
                root_path=root,
                fetcher=self.fetcher_returning(b"<rss><channel>"),
                clock=self.fixed_clock,
            )

        self.assertIn(
            "feed.parse_error",
            {observation.kind for observation in summary.raw_observations},
        )

    def test_item_limit_stops_after_retaining_artifact(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            config = self.write_config(root / "limited.toml", max_items_per_run=0)
            with self.assertRaisesRegex(SourcePolicyError, "max_items_per_run"):
                ingest_feed_source(
                    config,
                    root_path=root,
                    fetcher=self.fetcher_returning(RSS_BODY),
                    clock=self.fixed_clock,
                )

            artifacts = list((root / ".repomap" / "source-artifacts").rglob("rss.xml"))

        self.assertEqual(len(artifacts), 1)

    def test_secret_config_values_are_not_added_to_summary_or_observations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            config = self.write_config(root / "secret.toml", secret=True)
            summary = ingest_feed_source(
                config,
                root_path=root,
                fetcher=self.fetcher_returning(JSON_FEED_BODY),
                clock=self.fixed_clock,
            )

        payload = json.dumps(
            {
                "summary": summary.to_jsonable(),
                "observations": [
                    observation.to_dict()
                    for observation in summary.raw_observations
                ],
            },
            sort_keys=True,
        )
        self.assertIn("credentials.token", payload)
        self.assertNotIn("fixture-secret", payload)

    def test_artifact_directory_must_stay_inside_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            config = self.write_config(root / "rss.toml")

            with self.assertRaisesRegex(SourcePolicyError, "artifact_dir"):
                ingest_feed_source(
                    config,
                    root_path=root,
                    artifact_dir=Path(tmpdir) / "outside",
                    fetcher=self.fetcher_returning(RSS_BODY),
                    clock=self.fixed_clock,
                )
