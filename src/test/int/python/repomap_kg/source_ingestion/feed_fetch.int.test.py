import json
from email.message import Message
from io import BytesIO
import tempfile
import unittest
import urllib.error
from pathlib import Path

from repomap_test_support.source_ingestion_integration import (
    FakeOpener,
    FakeResponse,
    fixed_clock,
    source_fixture,
)
from repomap_kg.ops.ingestion.source import (
    FeedFetchResponse,
    FeedSourceConfig,
    SourceAcquisitionError,
    SourcePolicyError,
    fetch_feed_source,
    ingest_feed_source,
    load_feed_source_config,
)


class FeedFetchSourceIngestionIntegrationTests(unittest.TestCase):
    def test_default_fetcher_uses_configured_timeout_method_and_user_agent(self):
        config = load_feed_source_config(source_fixture("allowed-rss.toml"))
        opener = FakeOpener(FakeResponse(200, b"<rss />", {"content-type": "text/xml"}))

        response = fetch_feed_source(config, opener=opener)

        self.assertEqual(response.status, 200)
        self.assertEqual(response.body, b"<rss />")
        self.assertEqual(response.headers["content-type"], "text/xml")
        self.assertEqual(opener.timeout, 10)
        request = opener.request
        self.assertIsNotNone(request)
        assert request is not None
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(
            dict(request.header_items())["User-agent"],
            "RepoMap feed ingestion test fixture",
        )

    def test_default_fetcher_captures_http_error_without_following_redirect_body(self):
        config = load_feed_source_config(source_fixture("allowed-rss.toml"))
        opener = FakeOpener(
            urllib.error.HTTPError(
                config.url,
                302,
                "Found",
                _redirect_headers(),
                BytesIO(b"redirect"),
            )
        )

        response = fetch_feed_source(config, opener=opener)

        self.assertEqual(response.status, 302)
        self.assertEqual(response.body, b"redirect")
        self.assertEqual(
            response.headers["location"],
            "https://example.invalid/redirect",
        )

    def test_policy_blocked_ingestion_stops_before_fetch(self):
        calls = []

        def blocked_fetcher(config: FeedSourceConfig) -> FeedFetchResponse:
            calls.append(config.url)
            return FeedFetchResponse(status=0)

        with self.assertRaises(SourcePolicyError):
            ingest_feed_source(
                source_fixture("blocked-policy.toml"),
                root_path=Path("/tmp/fixture"),
                fetcher=blocked_fetcher,
            )

        self.assertEqual(calls, [])
    def test_unrecognized_fetched_artifact_is_retained_but_not_loaded(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()

            with self.assertRaises(SourceAcquisitionError):
                ingest_feed_source(
                    source_fixture("allowed-json.toml"),
                    root_path=root,
                    fetcher=lambda _config: FeedFetchResponse(
                        status=200,
                        headers={"content-type": "application/json"},
                        body=b'{"not": "a feed"}',
                    ),
                )

            artifacts = list((root / ".repomap" / "source-artifacts").rglob("feed.json"))

        self.assertEqual(len(artifacts), 1)

    def test_oversized_and_redirect_responses_stop_before_load(self):
        cases = (
            (
                source_fixture("oversized-artifact.toml"),
                FeedFetchResponse(status=200, body=b"too many bytes"),
                "max_artifact_bytes",
            ),
            (
                source_fixture("allowed-rss.toml"),
                FeedFetchResponse(status=302, body=b"redirect"),
                "redirect",
            ),
        )
        for config_path, response, message in cases:
            with self.subTest(message=message):
                with tempfile.TemporaryDirectory() as tmpdir:
                    root = Path(tmpdir) / "repo"
                    root.mkdir()

                    with self.assertRaisesRegex(SourceAcquisitionError, message):
                        ingest_feed_source(
                            config_path,
                            root_path=root,
                            fetcher=lambda _config: response,
                        )

    def test_atom_and_json_feed_sources_retain_expected_artifact_names(self):
        cases = (
            (
                source_fixture("allowed-atom.toml"),
                b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>A</title><id>urn:a</id><entry><id>urn:a:1</id><title>One</title></entry></feed>""",
                "atom.xml",
                "atom",
            ),
            (
                source_fixture("allowed-json.toml"),
                b'{"version":"https://jsonfeed.org/version/1.1","title":"J","items":[{"id":"1","title":"One"}]}',
                "feed.json",
                "json-feed",
            ),
        )
        for config_path, body, artifact_name, feed_format in cases:
            with self.subTest(artifact_name=artifact_name):
                with tempfile.TemporaryDirectory() as tmpdir:
                    root = Path(tmpdir) / "repo"
                    root.mkdir()
                    summary = ingest_feed_source(
                        config_path,
                        root_path=root,
                        fetcher=lambda _config: FeedFetchResponse(
                            status=200,
                            body=body,
                        ),
                        clock=fixed_clock,
                    )

                self.assertTrue(summary.artifact_path.endswith(artifact_name))
                self.assertEqual(
                    [
                        observation.metadata["feed_format"]
                        for observation in summary.raw_observations
                        if observation.kind == "feed.document"
                    ],
                    [feed_format],
                )

    def test_secret_bearing_config_redacts_values_in_summary_and_observations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            summary = ingest_feed_source(
                source_fixture("secret-bearing.toml"),
                root_path=root,
                fetcher=lambda _config: FeedFetchResponse(
                    status=200,
                    headers={"content-type": "application/feed+json"},
                    body=b'{"version":"https://jsonfeed.org/version/1.1","title":"S","items":[]}',
                ),
                clock=fixed_clock,
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
        self.assertNotIn("fixture-secret-placeholder", payload)

    def test_artifact_directory_must_stay_inside_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()

            with self.assertRaisesRegex(SourcePolicyError, "artifact_dir"):
                ingest_feed_source(
                    source_fixture("allowed-rss.toml"),
                    root_path=root,
                    artifact_dir=Path(tmpdir) / "outside",
                    fetcher=lambda _config: FeedFetchResponse(
                        status=200,
                        body=b"<rss />",
                    ),
                )


def _redirect_headers() -> Message:
    headers: Message = Message()
    headers["location"] = "https://example.invalid/redirect"
    return headers
