import io
import json
import tempfile
import urllib.error
from email.message import Message
from pathlib import Path

from repomap_kg.ops.ingestion.github_api import (
    GitHubApiPolicyError,
    GitHubTransportResponse,
    PublicGitHubRestTransport,
    acquire_github_api_source,
    build_github_api_plan_from_config,
    content_type_from_headers,
    header_mapping,
    load_github_api_source_config,
    rate_limit_headers,
    redact_github_value,
    validate_no_auth_headers,
)
from repomap_test_support.github_api_ingestion import (
    FakeGitHubErrorOpener,
    FakeGitHubOpener,
    FakeGitHubTransport,
    GitHubApiIngestionTestSupport,
)


class GitHubApiIngestionTransportContract(GitHubApiIngestionTestSupport):
    __test__ = False

    def test_public_github_rest_transport_builds_safe_request_and_captures_rate_headers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = self.write_github_fixture(
                Path(tmpdir),
                transport_mode="github_public_rest",
                include_fixture_paths=False,
            )
            config = load_github_api_source_config(config_path)
            request = build_github_api_plan_from_config(config_path).requests[0]
            opener = FakeGitHubOpener(
                status=200,
                headers={
                    "content-type": "application/json; charset=utf-8",
                    "x-ratelimit-limit": "60",
                    "x-ratelimit-remaining": "59",
                    "x-ratelimit-used": "1",
                    "x-ratelimit-reset": "1782921600",
                    "x-ratelimit-resource": "core",
                },
                body=b'{"full_name":"fixture-owner/fixture-repo"}',
            )

            response = PublicGitHubRestTransport(opener=opener).fetch(config, request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.response_type, "application/json")
        self.assertEqual(response.body, b'{"full_name":"fixture-owner/fixture-repo"}')
        self.assertEqual(
            response.rate_limit,
            {
                "x-ratelimit-limit": "60",
                "x-ratelimit-remaining": "59",
                "x-ratelimit-used": "1",
                "x-ratelimit-reset": "1782921600",
                "x-ratelimit-resource": "core",
            },
        )
        self.assertEqual(
            opener.requests[0].full_url,
            "https://api.github.com/repos/fixture-owner/fixture-repo",
        )
        self.assertEqual(opener.requests[0].get_method(), "GET")
        request_headers = {key.lower(): value for key, value in opener.requests[0].header_items()}
        self.assertIn("user-agent", request_headers)
        self.assertNotIn("authorization", request_headers)
        self.assertNotIn("cookie", request_headers)

    def test_public_github_rest_transport_captures_http_errors_and_url_failures_safely(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = self.write_github_fixture(
                Path(tmpdir),
                transport_mode="github_public_rest",
                include_fixture_paths=False,
            )
            config = load_github_api_source_config(config_path)
            request = build_github_api_plan_from_config(config_path).requests[0]
            error_headers = Message()
            error_headers["content-type"] = "application/json"
            error_headers["x-ratelimit-remaining"] = "0"
            http_error = urllib.error.HTTPError(
                "https://api.github.com/repos/fixture-owner/fixture-repo",
                403,
                "rate limited",
                error_headers,
                io.BytesIO(b'{"message":"rate limit exceeded"}'),
            )
            response = PublicGitHubRestTransport(
                opener=FakeGitHubErrorOpener(http_error)
            ).fetch(config, request)

            with self.assertRaisesRegex(GitHubApiPolicyError, "failed"):
                PublicGitHubRestTransport(
                    opener=FakeGitHubErrorOpener(
                        urllib.error.URLError("socket disabled")
                    )
                ).fetch(config, request)

            with self.assertRaisesRegex(GitHubApiPolicyError, "github_public_rest"):
                PublicGitHubRestTransport(opener=FakeGitHubOpener(
                    status=200,
                    headers={"content-type": "application/json"},
                    body=b"{}",
                )).fetch(
                    load_github_api_source_config(
                        self.write_github_fixture(Path(tmpdir))
                    ),
                    request,
                )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.response_type, "application/json")
        self.assertEqual(response.rate_limit["x-ratelimit-remaining"], "0")
        self.assertIn(b"rate limit", response.body)

    def test_github_real_transport_rejects_unsafe_acquisition_settings(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            unsupported = self.write_github_fixture(
                root,
                transport_mode="browser",
                include_fixture_paths=False,
            )
            redirects = self.write_github_fixture(
                root,
                transport_mode="github_public_rest",
                follow_redirects=True,
                include_fixture_paths=False,
            )
            unsafe_agent = self.write_github_fixture(
                root,
                transport_mode="github_public_rest",
                user_agent="bad\nagent",
                include_fixture_paths=False,
            )

            with self.assertRaisesRegex(GitHubApiPolicyError, "transport"):
                load_github_api_source_config(unsupported)
            with self.assertRaisesRegex(GitHubApiPolicyError, "redirects"):
                load_github_api_source_config(redirects)
            with self.assertRaisesRegex(GitHubApiPolicyError, "user_agent"):
                load_github_api_source_config(unsafe_agent)

    def test_github_transport_header_helpers_keep_only_safe_metadata(self):
        headers = header_mapping(
            [
                ("Content-Type", "application/json; charset=utf-8"),
                ("X-RateLimit-Limit", "60"),
                ("Authorization", "token fixture-secret"),
            ]
        )

        self.assertEqual(headers["content-type"], "application/json; charset=utf-8")
        self.assertEqual(content_type_from_headers(headers), "application/json")
        self.assertEqual(content_type_from_headers({}), "application/octet-stream")
        self.assertEqual(
            rate_limit_headers(headers),
            {"x-ratelimit-limit": "60"},
        )
        with self.assertRaisesRegex(GitHubApiPolicyError, "auth headers"):
            validate_no_auth_headers(headers)
        self.assertEqual(
            redact_github_value(None, key="body"),
            {
                "body_present": False,
                "body_length": 0,
                "body_sha256": "",
                "body_redacted": True,
            },
        )

    def test_public_github_rest_acquire_uses_injected_transport_and_minimizes_bodies(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = self.write_github_fixture(
                root,
                transport_mode="github_public_rest",
                endpoint_names=("issues",),
                include_fixture_paths=False,
            )
            summary = acquire_github_api_source(
                config_path,
                root_path=root,
                transport=FakeGitHubTransport(
                    [
                        GitHubTransportResponse(
                            status_code=200,
                            body=json.dumps(
                                [
                                    {
                                        "number": 1,
                                        "title": "Public issue title",
                                        "body": "public issue body should be minimized",
                                        "token": "fixture-github-token",
                                    }
                                ]
                            ).encode("utf-8"),
                            response_type="application/json",
                            rate_limit={
                                "x-ratelimit-limit": "60",
                                "x-ratelimit-remaining": "59",
                            },
                        )
                    ]
                ),
            )
            artifact_text = (
                summary.output_path / "artifacts" / "issues.json"
            ).read_text(encoding="utf-8")
            manifest_text = (summary.output_path / "manifest.json").read_text(
                encoding="utf-8"
            )

        self.assertEqual(summary.transport, "github_public_rest")
        self.assertFalse(summary.fixture_transport_only)
        self.assertFalse(summary.no_network)
        self.assertEqual(summary.responses, 1)
        self.assertIn('"body_redacted": true', artifact_text)
        self.assertIn('"body_length"', artifact_text)
        self.assertIn('"body_sha256"', artifact_text)
        self.assertNotIn("public issue body should be minimized", artifact_text)
        self.assertNotIn("fixture-github-token", artifact_text)
        self.assertIn('"transport": "github_public_rest"', manifest_text)
        self.assertIn('"x-ratelimit-remaining": "59"', manifest_text)
        payload = json.dumps(
            [observation.to_dict() for observation in summary.raw_observations],
            sort_keys=True,
        )
        self.assertIn('"transport": "github_public_rest"', payload)
        self.assertIn("config.document", payload)
        self.assertNotIn("public issue body should be minimized", payload)
        self.assertNotIn("fixture-github-token", payload)
        self.assertNotIn(str(root), json.dumps(summary.to_jsonable(), sort_keys=True))

    def test_public_github_rest_acquire_fails_safely_on_http_and_payload_errors(self):
        cases = (
            (
                GitHubTransportResponse(status_code=302, body=b"{}", response_type="application/json"),
                "redirect",
            ),
            (
                GitHubTransportResponse(
                    status_code=403,
                    body=b'{"message":"rate limit exceeded"}',
                    response_type="application/json",
                    rate_limit={"x-ratelimit-remaining": "0"},
                ),
                "rate limit",
            ),
            (
                GitHubTransportResponse(status_code=200, body=b"not json", response_type="text/plain"),
                "JSON",
            ),
            (
                GitHubTransportResponse(status_code=200, body=b'{"ok": true}' * 20, response_type="application/json"),
                "max_bytes_per_run",
            ),
        )
        for response, message in cases:
            with self.subTest(message=message):
                with tempfile.TemporaryDirectory() as tmpdir:
                    root = Path(tmpdir)
                    config_path = self.write_github_fixture(
                        root,
                        transport_mode="github_public_rest",
                        include_fixture_paths=False,
                        max_bytes_per_run=40 if "max_bytes" in message else 10485760,
                    )

                    with self.assertRaisesRegex(GitHubApiPolicyError, message):
                        acquire_github_api_source(
                            config_path,
                            root_path=root,
                            transport=FakeGitHubTransport([response]),
                        )

                self.assertFalse((root / ".repomap" / "api-runs").exists())
