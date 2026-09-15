import json
import tempfile
from pathlib import Path

from repomap_kg.ops.ingestion.github_api import (
    GitHubApiPolicyError,
    build_github_api_plan_from_config,
    load_github_api_source_config,
)
from repomap_test_support.github_api_ingestion import (
    GitHubApiIngestionTestSupport,
)


class GitHubApiIngestionConfigContract(GitHubApiIngestionTestSupport):
    __test__ = False

    def test_github_config_requires_policy_provider_scope_consent_and_credentials(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            valid = self.write_github_fixture(root)
            blocked = self.write_github_fixture(root, policy_status="blocked")
            bad_provider = self.write_github_fixture(root, provider_name="GitLab")
            bad_class = self.write_github_fixture(
                root,
                api_source_class="api.github.issues",
            )
            invalid_owner = self.write_github_fixture(root, owner="bad/owner")
            private_no_ref = self.write_github_fixture(
                root,
                repository_visibility="private",
                credential_mode="pat_readonly_ref",
                include_credentials=False,
            )
            public_pat_no_ref = self.write_github_fixture(
                root,
                credential_mode="pat_readonly_ref",
                include_credentials=False,
            )
            public_none_private = self.write_github_fixture(
                root,
                repository_visibility="private",
                credential_mode="none_public_readonly",
            )
            invalid_ref = self.write_github_fixture(
                root,
                credential_mode="pat_readonly_ref",
                credentials_ref="github-token",
            )

            config = load_github_api_source_config(valid)
            with self.assertRaisesRegex(GitHubApiPolicyError, "policy status"):
                load_github_api_source_config(blocked)
            with self.assertRaisesRegex(GitHubApiPolicyError, "provider_name"):
                load_github_api_source_config(bad_provider)
            with self.assertRaisesRegex(GitHubApiPolicyError, "api_source_class"):
                load_github_api_source_config(bad_class)
            with self.assertRaisesRegex(GitHubApiPolicyError, "owner"):
                load_github_api_source_config(invalid_owner)
            with self.assertRaisesRegex(GitHubApiPolicyError, "credentials_ref"):
                load_github_api_source_config(private_no_ref)
            with self.assertRaisesRegex(GitHubApiPolicyError, "credentials_ref"):
                load_github_api_source_config(public_pat_no_ref)
            with self.assertRaisesRegex(GitHubApiPolicyError, "public"):
                load_github_api_source_config(public_none_private)
            with self.assertRaisesRegex(GitHubApiPolicyError, "credentials_ref"):
                load_github_api_source_config(invalid_ref)

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
        self.assertEqual([endpoint.name for endpoint in config.endpoints], ["repository"])

    def test_github_config_rejects_endpoint_escape_mutation_and_unsupported_routes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            non_get = self.write_github_fixture(root, method="POST")
            scheme_path = self.write_github_fixture(
                root,
                endpoint_path="https://api.github.com/repos/{owner}/{repo}",
            )
            wrong_scope = self.write_github_fixture(
                root,
                endpoint_path="/repos/other-owner/{repo}",
            )
            non_allowlisted = self.write_github_fixture(
                root,
                endpoint_path="/repos/{owner}/{repo}/contents/README.md",
            )
            pagination = self.write_github_fixture(root, pagination="page")
            downstream = self.write_github_fixture(root, downstream_route="bulk")
            fixture_escape = self.write_github_fixture(
                root,
                fixture_response_path="../repository.json",
            )

            with self.assertRaisesRegex(GitHubApiPolicyError, "GET"):
                load_github_api_source_config(non_get)
            with self.assertRaisesRegex(GitHubApiPolicyError, "relative API path"):
                load_github_api_source_config(scheme_path)
            with self.assertRaisesRegex(GitHubApiPolicyError, "owner/repository"):
                load_github_api_source_config(wrong_scope)
            with self.assertRaisesRegex(GitHubApiPolicyError, "allowlisted"):
                load_github_api_source_config(non_allowlisted)
            with self.assertRaisesRegex(GitHubApiPolicyError, "pagination"):
                load_github_api_source_config(pagination)
            with self.assertRaisesRegex(GitHubApiPolicyError, "downstream_route"):
                load_github_api_source_config(downstream)
            with self.assertRaisesRegex(GitHubApiPolicyError, "fixture_response_path"):
                load_github_api_source_config(fixture_escape)

    def test_github_plan_is_deterministic_and_does_not_call_transport(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = self.write_github_fixture(
                Path(tmpdir),
                endpoint_names=("repository", "issues", "pulls"),
            )

            first = build_github_api_plan_from_config(config_path)
            second = build_github_api_plan_from_config(config_path)

        self.assertEqual(first.api_run_id, second.api_run_id)
        self.assertEqual(first.api_manifest_id, second.api_manifest_id)
        self.assertEqual(first.request_count, 3)
        self.assertEqual(first.requests[0].endpoint_name, "repository")
        self.assertEqual(first.requests[0].method, "GET")
        self.assertEqual(first.requests[0].path, "/repos/{owner}/{repo}")
        payload = json.dumps(first.to_jsonable(), sort_keys=True)
        self.assertIn('"owner": "fixture-owner"', payload)
        self.assertIn('"repository": "fixture-repo"', payload)
        self.assertIn('"fixture_transport_only": true', payload)
        self.assertIn('"no_network": true', payload)
        self.assertIn('"no_mutation": true', payload)
        self.assertIn('"no_credentials_resolved": true', payload)
        self.assertIn('"no_scheduler": true', payload)
        self.assertNotIn("fixture-github-token", payload)
        self.assertNotIn(str(config_path.parent), payload)

    def test_github_real_public_transport_config_is_explicit_public_and_credential_free(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            valid = self.write_github_fixture(
                root,
                transport_mode="github_public_rest",
                include_fixture_paths=False,
            )
            private = self.write_github_fixture(
                root,
                transport_mode="github_public_rest",
                repository_visibility="private",
                credential_mode="none_public_readonly",
                include_fixture_paths=False,
            )
            pat_mode = self.write_github_fixture(
                root,
                transport_mode="github_public_rest",
                credential_mode="pat_readonly_ref",
                include_credentials=True,
                include_fixture_paths=False,
            )
            credentials = self.write_github_fixture(
                root,
                transport_mode="github_public_rest",
                include_credentials=True,
                include_fixture_paths=False,
            )
            bad_base = self.write_github_fixture(
                root,
                transport_mode="github_public_rest",
                base_url="https://example.invalid",
                include_fixture_paths=False,
            )

            config = load_github_api_source_config(valid)
            manifest = build_github_api_plan_from_config(valid)

            with self.assertRaisesRegex(GitHubApiPolicyError, "public"):
                load_github_api_source_config(private)
            with self.assertRaisesRegex(GitHubApiPolicyError, "none_public_readonly"):
                load_github_api_source_config(pat_mode)
            with self.assertRaisesRegex(GitHubApiPolicyError, "credentials"):
                load_github_api_source_config(credentials)
            with self.assertRaisesRegex(GitHubApiPolicyError, "base_url"):
                load_github_api_source_config(bad_base)

        self.assertEqual(config.acquisition_transport, "github_public_rest")
        self.assertEqual(config.base_url, "https://api.github.com")
        self.assertFalse(config.follow_redirects)
        payload = json.dumps(manifest.to_jsonable(), sort_keys=True)
        self.assertIn('"transport": "github_public_rest"', payload)
        self.assertIn('"network_capable": true', payload)
        self.assertIn('"fixture_transport_only": false', payload)
        self.assertIn('"no_credentials_resolved": true', payload)
        self.assertNotIn("fixture-github-token", payload)
