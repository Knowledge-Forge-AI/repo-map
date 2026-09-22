import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from repomap_kg.ops.ingestion._github_api_transport import (
    github_public_rest_url,
    validate_transport_response,
)
from repomap_kg.ops.ingestion.api import (
    ApiPolicyError,
    ApiTransportResponse,
    FixtureApiTransport,
    acquire_api_source,
    build_api_plan_from_config,
    load_api_source_config,
)
from repomap_kg.ops.ingestion.github_api import (
    FixtureGitHubApiTransport,
    GitHubApiPolicyError,
    GitHubTransportResponse,
    acquire_github_api_source,
    load_github_api_source_config,
)
from repomap_test_support.source_ingestion_integration import (
    api_fixture_root,
    github_api_fixture_root,
)


class Slice9ApiAcquisitionIntegrationTests(unittest.TestCase):
    """Integration slice 9 tests covering API acquisition and GitHub API policies."""

    def test_s9_b01_api_policy_gating_and_mutation_refusal(self) -> None:
        """API configs refuse forbidden policy status, mutation flags, and invalid limits."""
        base_text = (api_fixture_root() / "readonly_fixture_api" / "api-source.toml").read_text(
            encoding="utf-8"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = Path(tmpdir) / "test-api.toml"
            for old, new, expected_msg in (
                ('policy_status = "allowed_with_limits"', 'policy_status = "unapproved"', "source policy status is not allowed"),
                ('read_only = true', 'read_only = false', "source.read_only must be true"),
                ('mutation_allowed = false', 'mutation_allowed = true', "source.mutation_allowed must be false"),
                ('revoked = false', 'revoked = true', "consent is revoked"),
                ('max_concurrent_requests = 1', 'max_concurrent_requests = 2', "max_concurrent_requests must be 1 in API1"),
            ):
                cfg.write_text(base_text.replace(old, new), encoding="utf-8")
                with self.subTest(modification=new):
                    with self.assertRaises(ApiPolicyError) as cm_policy:
                        load_api_source_config(cfg)
                    self.assertIn(expected_msg, str(cm_policy.exception))

    def test_s9_b02_api_limits_max_bytes_and_max_items_exceeded(self) -> None:
        """API acquisition enforces max_bytes_per_run and max_items_per_run limits."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            shutil.copytree(api_fixture_root() / "readonly_fixture_api", root / "api_source")
            cfg_path = root / "api_source" / "api-source.toml"
            cfg = load_api_source_config(cfg_path)

            mock_transport = MagicMock()
            mock_transport.fetch.return_value = ApiTransportResponse(
                status_code=200,
                body=b"X" * (cfg.max_bytes_per_run + 100),
                response_type="application/json",
            )
            with self.assertRaises(ApiPolicyError) as ctx:
                acquire_api_source(cfg_path, root_path=root, transport=mock_transport)
            self.assertIn("response bytes exceed max_bytes_per_run", str(ctx.exception))

            huge_items = json.dumps({"items": [{"id": f"id_{i}"} for i in range(cfg.max_items_per_run + 50)]}).encode("utf-8")
            mock_transport.fetch.return_value = ApiTransportResponse(
                status_code=200,
                body=huge_items,
                response_type="application/json",
            )
            with self.assertRaises(ApiPolicyError) as ctx:
                acquire_api_source(cfg_path, root_path=root, transport=mock_transport)
            self.assertIn("response items exceed max_items_per_run", str(ctx.exception))

    def test_s9_b03_api_transport_status_and_missing_fixture_refusal(self) -> None:
        """API acquisition rejects non-2xx status codes and unreadable fixture paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            shutil.copytree(api_fixture_root() / "readonly_fixture_api", root / "api_source")
            cfg_path = root / "api_source" / "api-source.toml"

            mock_transport = MagicMock()
            for code in (404, 500, 301):
                mock_transport.fetch.return_value = ApiTransportResponse(
                    status_code=code,
                    body=b"{}",
                    response_type="application/json",
                )
                with self.subTest(status_code=code):
                    with self.assertRaises(ApiPolicyError) as ctx:
                        acquire_api_source(cfg_path, root_path=root, transport=mock_transport)
                    self.assertIn(f"returned status {code}", str(ctx.exception))

            missing_item = root / "api_source" / "responses" / "items.json"
            if missing_item.exists():
                missing_item.unlink()
            with self.assertRaises(ApiPolicyError) as ctx:
                acquire_api_source(cfg_path, root_path=root, transport=FixtureApiTransport())
            self.assertIn("fixture response is not readable", str(ctx.exception))

    def test_s9_b04_api_deterministic_manifest_and_observations(self) -> None:
        """Successful API acquisition produces deterministic manifest, records, and observations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            shutil.copytree(api_fixture_root() / "readonly_fixture_api", root / "api_source")
            cfg_path = root / "api_source" / "api-source.toml"

            plan = build_api_plan_from_config(cfg_path)
            self.assertTrue(plan.manifest_sha256)
            self.assertEqual(plan.request_count, 1)

            summary = acquire_api_source(cfg_path, root_path=root, transport=FixtureApiTransport())
            self.assertEqual(summary.source_id, "fixture-readonly-api")
            self.assertEqual(summary.requests, 1)
            self.assertEqual(summary.responses, 1)
            self.assertGreater(summary.observations, 0)
            self.assertEqual(summary.publication.publication_state, "not_published")

            kinds = {obs.kind for obs in summary.raw_observations}
            self.assertIn("api.source", kinds)
            self.assertIn("api.run", kinds)
            self.assertIn("api.response", kinds)
            self.assertTrue((summary.output_path / "manifest.json").is_file())
            self.assertTrue((summary.output_path / "plan.json").is_file())
            self.assertTrue((summary.output_path / "requests.jsonl").is_file())
            self.assertTrue((summary.output_path / "redacted-responses.jsonl").is_file())

    def test_s9_b05_github_config_consent_and_credential_validation(self) -> None:
        """GitHub API config loading validates consent, credentials, and query limits."""
        base_text = (
            github_api_fixture_root() / "readonly_public_repo" / "github-source.toml"
        ).read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = Path(tmpdir) / "gh-source.toml"
            for old, new, expected_msg in (
                ('policy_status = "allowed_with_limits"', 'policy_status = "forbidden"', "source policy status is not allowed"),
                ('credential_mode = "none_public_readonly"', 'credential_mode = "invalid_mode"', "unsupported credential_mode"),
                ('revoked = false', 'revoked = true', "consent is revoked"),
                ('mutation_allowed = false', 'mutation_allowed = true', "source.mutation_allowed must be false"),
                ('max_concurrent_requests = 1', 'max_concurrent_requests = 3', "max_concurrent_requests must be 1 in GITHUB_API1"),
            ):
                cfg.write_text(base_text.replace(old, new), encoding="utf-8")
                with self.subTest(modification=new):
                    with self.assertRaises(GitHubApiPolicyError) as cm_gh:
                        load_github_api_source_config(cfg)
                    self.assertIn(expected_msg, str(cm_gh.exception))

    def test_s9_b06_github_transport_url_and_response_validation(self) -> None:
        """GitHub transport validates HTTPS url construction and responds to HTTP codes."""
        cfg = load_github_api_source_config(
            github_api_fixture_root() / "readonly_public_repo" / "github-source.toml"
        )
        req = MagicMock()
        req.endpoint_name = "repo"
        req.path = "/repos/{owner}/{repo}"

        url = github_public_rest_url(cfg, req)
        self.assertTrue(url.startswith("https://api.github.com/repos/fixture-owner/fixture-repo"))

        req.path = "http://api.github.com/bad"
        with self.assertRaises(GitHubApiPolicyError):
            github_public_rest_url(cfg, req)

        req.path = "/repos/{owner}/{repo}?query=leak"
        with self.assertRaises(GitHubApiPolicyError):
            github_public_rest_url(cfg, req)

        req.path = "/users/other"
        with self.assertRaises(GitHubApiPolicyError):
            github_public_rest_url(cfg, req)

        resp_redirect = GitHubTransportResponse(
            status_code=301,
            body=b"{}",
            response_type="application/json",
            headers={},
            rate_limit={},
        )
        with self.assertRaises(GitHubApiPolicyError) as ctx:
            validate_transport_response(cfg, req, resp_redirect)
        self.assertIn("redirects are not followed", str(ctx.exception))

        resp_exhausted = GitHubTransportResponse(
            status_code=403,
            body=b"{}",
            response_type="application/json",
            headers={},
            rate_limit={"x-ratelimit-remaining": "0"},
        )
        with self.assertRaises(GitHubApiPolicyError):
            validate_transport_response(cfg, req, resp_exhausted)

    def test_s9_b07_github_api_observations_and_secret_redaction(self) -> None:
        """GitHub API acquisition runs locally with fixture transport and redacts outputs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            shutil.copytree(
                github_api_fixture_root() / "readonly_public_repo",
                root / "readonly_public_repo",
            )
            cfg_path = root / "readonly_public_repo" / "github-source.toml"

            summary = acquire_github_api_source(
                cfg_path,
                root_path=root,
                transport=FixtureGitHubApiTransport(),
            )
            self.assertEqual(summary.source_id, "github-public-fixture")
            self.assertEqual(summary.requests, 5)
            self.assertEqual(summary.responses, 5)
            self.assertTrue(summary.no_network)
            self.assertTrue(summary.fixture_transport_only)
            self.assertEqual(summary.publication.publication_state, "not_published")

            kinds = {obs.kind for obs in summary.raw_observations}
            self.assertIn("github.repository", kinds)
            self.assertIn("api.run", kinds)
            self.assertIn("api.response", kinds)

            redacted_file = summary.output_path / "redacted-responses.jsonl"
            self.assertTrue(redacted_file.is_file())
            content = redacted_file.read_text(encoding="utf-8")
            self.assertIn('"redacted": true', content)


if __name__ == "__main__":
    import sys
    sys.exit('Direct execution unsupported; use tools/run_tests.py for container sandbox admission.')
