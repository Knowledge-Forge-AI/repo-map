import json
import shutil
import tempfile
import unittest
import urllib.request
from pathlib import Path

from repomap_test_support.source_ingestion_integration import (
    IntFakeGitHubOpener,
    api_fixture_root,
    bulk_fixture_root,
    github_api_fixture_root,
)
from repomap_kg.ops.ingestion.api import (
    ApiPolicyError,
    FixtureApiTransport,
    acquire_api_source,
    build_api_plan_from_config,
    load_api_source_config,
)
from repomap_kg.ops.ingestion.bulk import (
    BulkPolicyError,
    bulk_observations_from_plan,
    build_bulk_plan,
    import_bulk_source,
    load_bulk_source_config,
)
from repomap_kg.ops.ingestion.github_api import (
    FixtureGitHubApiTransport,
    GitHubApiPolicyError,
    PublicGitHubRestTransport,
    acquire_github_api_source,
    build_github_api_plan_from_config,
    load_github_api_source_config,
)


class ApiGithubBulkSourceIngestionIntegrationTests(unittest.TestCase):
    def test_api_fixture_policy_plan_and_fail_closed_configs(self):
        config = load_api_source_config(
            api_fixture_root() / "readonly_fixture_api" / "api-source.toml"
        )
        manifest = build_api_plan_from_config(
            api_fixture_root() / "readonly_fixture_api" / "api-source.toml"
        )

        self.assertEqual(config.source_id, "fixture-readonly-api")
        self.assertEqual(config.source_type, "api.rest")
        self.assertEqual(config.api_source_class, "api.custom_documented_api")
        self.assertEqual(config.credentials_ref, "local_secret_ref:fixture-api-token")
        self.assertEqual(manifest.request_count, 1)
        self.assertEqual(manifest.requests[0].method, "GET")
        self.assertEqual(manifest.requests[0].path, "/v1/items")
        payload = json.dumps(manifest.to_jsonable(), sort_keys=True)
        self.assertIn('"no_network": true', payload)
        self.assertIn('"no_mutation": true', payload)
        self.assertNotIn("fixture-api-token", payload)
        self.assertNotIn(str(api_fixture_root()), payload)
        for fixture_name in (
            "blocked_policy",
            "missing_consent",
            "mutation_attempt",
            "missing_credentials",
            "non_allowlisted_endpoint",
        ):
            with self.subTest(fixture_name=fixture_name):
                with self.assertRaises(ApiPolicyError):
                    load_api_source_config(
                        api_fixture_root() / fixture_name / "api-source.toml"
                    )

    def test_api_acquire_uses_fixture_transport_owned_artifacts_and_provenance(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            shutil.copytree(
                api_fixture_root() / "readonly_fixture_api",
                root / "readonly_fixture_api",
            )
            config_path = root / "readonly_fixture_api" / "api-source.toml"
            source_text = (
                root / "readonly_fixture_api" / "responses" / "items.json"
            ).read_text(encoding="utf-8")
            summary = acquire_api_source(
                config_path,
                root_path=root,
                transport=FixtureApiTransport(),
            )
            manifest_exists = (summary.output_path / "manifest.json").is_file()
            response_records_exist = (
                summary.output_path / "redacted-responses.jsonl"
            ).is_file()
            artifact_exists = (
                summary.output_path / "artifacts" / "items.json"
            ).is_file()

        self.assertEqual(summary.source_id, "fixture-readonly-api")
        self.assertEqual(summary.requests, 1)
        self.assertEqual(summary.responses, 1)
        self.assertEqual(summary.publication.publication_state, "not_published")
        self.assertTrue(manifest_exists)
        self.assertTrue(response_records_exist)
        self.assertTrue(artifact_exists)
        kinds = {observation.kind for observation in summary.raw_observations}
        self.assertIn("api.source", kinds)
        self.assertIn("api.run", kinds)
        self.assertIn("api.response", kinds)
        self.assertIn("config.document", kinds)
        payload = json.dumps(
            [observation.to_dict() for observation in summary.raw_observations],
            sort_keys=True,
        )
        self.assertIn('"api_run_id"', payload)
        self.assertIn('"endpoint_name": "items"', payload)
        self.assertIn('"api_retention_policy": "local_user_controlled"', payload)
        self.assertNotIn(str(root), payload)
        self.assertNotIn("fixture-secret-value", payload)
        self.assertNotIn("fixture-api-token", payload)
        summary_payload = json.dumps(summary.to_jsonable(), sort_keys=True)
        self.assertIn('"no_network": true', summary_payload)
        self.assertIn('"no_mutation": true', summary_payload)
        self.assertNotIn(str(root), summary_payload)
        self.assertNotIn("fixture-secret-value", summary_payload)
        self.assertIn("fixture-secret-value", source_text)

    def test_github_api_fixture_policy_plan_and_fail_closed_configs(self):
        config = load_github_api_source_config(
            github_api_fixture_root() / "readonly_public_repo" / "github-source.toml"
        )
        manifest = build_github_api_plan_from_config(
            github_api_fixture_root() / "readonly_public_repo" / "github-source.toml"
        )

        self.assertEqual(config.source_id, "github-public-fixture")
        self.assertEqual(config.source_type, "api.rest")
        self.assertEqual(config.api_source_class, "api.github.repository")
        self.assertEqual(config.provider_name, "GitHub")
        self.assertEqual(config.provider_product, "GitHub REST API")
        self.assertEqual(config.owner, "fixture-owner")
        self.assertEqual(config.repository, "fixture-repo")
        self.assertEqual(config.repository_visibility, "public")
        self.assertEqual(config.credential_mode, "none_public_readonly")
        self.assertIsNone(config.credentials_ref)
        self.assertEqual(manifest.request_count, 5)
        self.assertEqual(manifest.requests[0].method, "GET")
        self.assertEqual(manifest.requests[0].path, "/repos/{owner}/{repo}")
        payload = json.dumps(manifest.to_jsonable(), sort_keys=True)
        self.assertIn('"fixture_transport_only": true', payload)
        self.assertIn('"no_network": true', payload)
        self.assertIn('"no_mutation": true', payload)
        self.assertNotIn("fixture-github-token", payload)
        self.assertNotIn(str(github_api_fixture_root()), payload)
        for fixture_name in (
            "blocked_policy",
            "private_missing_consent",
            "private_missing_credentials",
            "mutation_attempt",
            "non_allowlisted_endpoint",
            "bad_provider",
        ):
            with self.subTest(fixture_name=fixture_name):
                with self.assertRaises(GitHubApiPolicyError):
                    load_github_api_source_config(
                        github_api_fixture_root()
                        / fixture_name
                        / "github-source.toml"
                    )

    def test_github_api_redaction_fixture_masks_sensitive_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            summary = acquire_github_api_source(
                github_api_fixture_root() / "redaction" / "github-source.toml",
                root_path=root,
                transport=FixtureGitHubApiTransport(),
            )
            artifact_text = (
                summary.output_path / "artifacts" / "repository.json"
            ).read_text(encoding="utf-8")

        self.assertEqual(summary.source_id, "github-redaction-fixture")
        self.assertEqual(summary.requests, 1)
        self.assertEqual(summary.responses, 1)
        self.assertEqual(summary.publication.publication_state, "not_published")
        payload = json.dumps(
            [observation.to_dict() for observation in summary.raw_observations],
            sort_keys=True,
        )
        self.assertIn("github.repository", payload)
        self.assertIn("config.document", payload)
        self.assertNotIn("fixture-secret-value", payload)
        self.assertNotIn("fixture-github-token", payload)
        self.assertNotIn("fixture-private-key", payload)
        self.assertNotIn(str(root), payload)
        self.assertNotIn("fixture-secret-value", artifact_text)
        self.assertNotIn("fixture-github-token", artifact_text)
        self.assertNotIn("fixture-private-key", artifact_text)

    def test_github_api_public_rest_transport_uses_fixed_api_base_and_safe_headers(self):
        config_path = (
            github_api_fixture_root()
            / "public_real_transport_config"
            / "github-source.toml"
        )
        config = load_github_api_source_config(config_path)
        manifest = build_github_api_plan_from_config(config_path)
        opener = IntFakeGitHubOpener(
            status=200,
            headers={
                "content-type": "application/json; charset=utf-8",
                "x-ratelimit-limit": "60",
                "x-ratelimit-remaining": "59",
                "x-ratelimit-used": "1",
                "x-ratelimit-reset": "1782921600",
            },
            body=b'{"full_name":"fixture-owner/fixture-repo"}',
        )

        response = PublicGitHubRestTransport(opener=opener).fetch(
            config,
            manifest.requests[0],
        )

        self.assertEqual(config.acquisition_transport, "github_public_rest")
        self.assertEqual(manifest.transport, "github_public_rest")
        self.assertTrue(manifest.network_capable)
        self.assertFalse(manifest.fixture_transport_only)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.response_type, "application/json")
        self.assertEqual(response.rate_limit["x-ratelimit-remaining"], "59")
        request = opener.requests[0]
        assert isinstance(request, urllib.request.Request)
        self.assertEqual(
            request.full_url,
            "https://api.github.com/repos/fixture-owner/fixture-repo",
        )
        headers = {
            key.lower(): value
            for key, value in request.header_items()
        }
        self.assertIn("user-agent", headers)
        self.assertNotIn("authorization", headers)
        self.assertNotIn("cookie", headers)

    def test_bulk_fixture_policy_plan_and_observations(self):
        config = load_bulk_source_config(
            bulk_fixture_root() / "mixed_corpus" / "bulk.toml"
        )
        manifest = build_bulk_plan(
            config,
            repository_root=bulk_fixture_root() / "mixed_corpus",
        )
        observations = bulk_observations_from_plan(
            config,
            manifest,
            repository_root=bulk_fixture_root() / "mixed_corpus",
        )

        self.assertEqual(config.source_id, "fixture-mixed-corpus")
        self.assertEqual(manifest.corpus_kind, "mixed_corpus")
        self.assertEqual(
            [item.relative_path for item in manifest.included_files],
            [
                "config/settings.yaml",
                "docs/readme.md",
                "mail/single-message.eml",
                "src/example.py",
                "web/app.js",
                "web/index.html",
            ],
        )
        self.assertTrue(
            any(
                item.relative_path == "vendor/ignored.rb"
                and item.reason == "excluded_directory"
                for item in manifest.skipped_files
            )
        )
        kinds = {observation.kind for observation in observations}
        self.assertIn("email.message", kinds)
        self.assertIn("config.document", kinds)
        self.assertIn("html.document", kinds)
        self.assertIn("js.file", kinds)
        self.assertIn("python.module", kinds)
        self.assertIn("markdown.document", kinds)
        payload = json.dumps([item.to_dict() for item in observations], sort_keys=True)
        self.assertIn('"bulk_run_id"', payload)
        self.assertIn('"bulk_relative_path": "mail/single-message.eml"', payload)
        self.assertIn('"bulk_sensitivity": "private"', payload)
        self.assertIn(
            '"no_provider_api": true',
            json.dumps(manifest.to_jsonable(), sort_keys=True),
        )
        self.assertNotIn(str(bulk_fixture_root()), payload)
        self.assertNotIn("mixed-corpus-secret-value", payload)

    def test_bulk_email_export_fixture_routes_eml_and_mbox(self):
        config = load_bulk_source_config(
            bulk_fixture_root() / "email_export" / "bulk.toml"
        )
        manifest = build_bulk_plan(
            config,
            repository_root=bulk_fixture_root() / "email_export",
        )
        observations = bulk_observations_from_plan(
            config,
            manifest,
            repository_root=bulk_fixture_root() / "email_export",
        )

        routes = {item.relative_path: item.route for item in manifest.included_files}
        self.assertEqual(routes["messages/single-message.eml"], "eml")
        self.assertEqual(routes["messages/thread-reply.eml"], "eml")
        self.assertEqual(routes["archives/sample.mbox"], "mbox")
        skipped = {item.relative_path: item.reason for item in manifest.skipped_files}
        self.assertEqual(skipped[".hidden/hidden.eml"], "hidden_excluded")
        self.assertEqual(skipped["node_modules/ignored.js"], "excluded_directory")
        self.assertEqual(skipped["archive/export.zip"], "archive_deferred")
        self.assertEqual(skipped["archive/export.warc"], "warc_deferred")
        self.assertEqual(skipped["unsupported/ignored.pdf"], "unsupported_extension")
        kinds = {observation.kind for observation in observations}
        self.assertIn("email.message", kinds)
        self.assertIn("email.mailbox", kinds)
        payload = json.dumps([item.to_dict() for item in observations], sort_keys=True)
        self.assertIn('"corpus_kind": "email_export"', payload)
        self.assertIn('"bulk_extractor_route": "mbox"', payload)
        self.assertNotIn("fake-mailbox-secret-value", payload)

    def test_bulk_blocked_policy_fails_closed(self):
        with self.assertRaises(BulkPolicyError):
            load_bulk_source_config(bulk_fixture_root() / "blocked_policy" / "bulk.toml")

    def test_bulk_import_returns_non_publication_and_owned_manifests(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            shutil.copytree(bulk_fixture_root() / "mixed_corpus", root / "mixed_corpus")
            summary = import_bulk_source(
                root / "mixed_corpus" / "bulk.toml",
                root_path=root / "mixed_corpus",
            )

            source_text = (
                root / "mixed_corpus" / "mail" / "single-message.eml"
            ).read_text(encoding="utf-8")
            self.assertTrue(summary.output_path.name)
            self.assertTrue((summary.output_path / "manifest.json").is_file())
            self.assertTrue((summary.output_path / "included-files.jsonl").is_file())
            self.assertTrue((summary.output_path / "skipped-files.jsonl").is_file())

        self.assertEqual(summary.source_id, "fixture-mixed-corpus")
        self.assertEqual(summary.publication.publication_state, "not_published")
        self.assertGreater(len(summary.raw_observations), 6)
        self.assertIn("mixed-corpus-secret-value", source_text)
        payload = json.dumps(summary.to_jsonable(), sort_keys=True)
        self.assertIn('"no_source_mutation": true', payload)
        self.assertIn('"no_external_fetch": true', payload)
        self.assertNotIn(str(root), payload)
