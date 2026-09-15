import unittest
from typing import TypedDict

from repomap_kg.ops.ingestion import github_api as github
from repomap_kg.ops.ingestion import github_api_config as github_config


class _SourceIdentity(TypedDict):
    source_type: str
    api_source_class: str
    provider_name: str
    provider_product: str
    policy_status: str
    owner: str
    repository: str
    repository_visibility: str
    credential_mode: str
    read_only: bool
    mutation_allowed: bool


class GitHubApiConfigBranchUnitTests(unittest.TestCase):
    def test_github_api_config_validation_branches(self):
        # 1. validate_source_identity valid baseline
        valid_kwargs: _SourceIdentity = {
            "source_type": "api.rest", "api_source_class": "api.github.repository",
            "provider_name": "GitHub", "provider_product": "GitHub REST API",
            "policy_status": "allowed", "owner": "safe-owner", "repository": "safe-repo",
            "repository_visibility": "public", "read_only": True, "mutation_allowed": False,
            "credential_mode": "none_public_readonly",
        }
        validate_identity = github_config.validate_source_identity
        validate_identity(**valid_kwargs)

        # Invalids for validate_source_identity
        identity_errors: tuple[_SourceIdentity, ...] = (
            {**valid_kwargs, 'source_type': 'bad_type'},
            {**valid_kwargs, 'api_source_class': 'bad_class'},
            {**valid_kwargs, 'provider_name': 'NotGitHub'},
            {**valid_kwargs, 'provider_product': 'NotREST'},
            {**valid_kwargs, 'policy_status': 'disabled'},
            {**valid_kwargs, 'owner': 'bad owner with spaces'},
            {**valid_kwargs, 'repository': 'bad/repo'},
            {**valid_kwargs, 'repository_visibility': 'invalid_vis'},
            {**valid_kwargs, 'read_only': False},
            {**valid_kwargs, 'mutation_allowed': True},
            {**valid_kwargs, 'credential_mode': 'unsupported_mode'},
            {**valid_kwargs, 'repository_visibility': 'private'},
        )
        for kwargs in identity_errors:
            with self.subTest(identity=kwargs):
                with self.assertRaises(github.GitHubApiPolicyError):
                    validate_identity(**kwargs)

        # 2. acquisition_config_from_payload
        self.assertEqual(
            github_config.acquisition_config_from_payload(
                {}, credential_mode="none_public_readonly", repository_visibility="public"
            )[0],
            "fixture",
        )
        with self.assertRaises(github.GitHubApiPolicyError):
            github_config.acquisition_config_from_payload(
                {"acquisition": "not-map"}, credential_mode="none_public_readonly", repository_visibility="public"
            )
        with self.assertRaises(github.GitHubApiPolicyError):
            github_config.acquisition_config_from_payload(
                {"acquisition": {"transport": "unsupported"}},
                credential_mode="none_public_readonly", repository_visibility="public"
            )
        with self.assertRaises(github.GitHubApiPolicyError):
            github_config.acquisition_config_from_payload(
                {"acquisition": {"user_agent": "bad\nagent"}},
                credential_mode="none_public_readonly", repository_visibility="public"
            )
        with self.assertRaises(github.GitHubApiPolicyError):
            github_config.acquisition_config_from_payload(
                {"acquisition": {"transport": "github_public_rest"}},
                credential_mode="none_public_readonly", repository_visibility="private"
            )
        with self.assertRaises(github.GitHubApiPolicyError):
            github_config.acquisition_config_from_payload(
                {"acquisition": {"transport": "github_public_rest"}},
                credential_mode="pat_readonly_ref", repository_visibility="public"
            )
        with self.assertRaises(github.GitHubApiPolicyError):
            github_config.acquisition_config_from_payload(
                {"acquisition": {"transport": "github_public_rest", "base_url": "https://other.api"}},
                credential_mode="none_public_readonly", repository_visibility="public"
            )
        with self.assertRaises(github.GitHubApiPolicyError):
            github_config.acquisition_config_from_payload(
                {"acquisition": {"transport": "github_public_rest", "follow_redirects": True}},
                credential_mode="none_public_readonly", repository_visibility="public"
            )

        # 3. credentials_ref_from_payload and validate_credential_ref
        with self.assertRaises(github.GitHubApiPolicyError):
            github_config.credentials_ref_from_payload(
                {"credentials": {"credentials_ref": "env_ref:GH_TOKEN"}},
                credential_mode="none_public_readonly",
                repository_visibility="public",
                acquisition_transport="github_public_rest",
            )
        with self.assertRaises(github.GitHubApiPolicyError):
            github_config.credentials_ref_from_payload(
                {},
                credential_mode="none_public_readonly",
                repository_visibility="private",
                acquisition_transport="fixture",
            )
        with self.assertRaises(github.GitHubApiPolicyError):
            github_config.credentials_ref_from_payload(
                {"credentials": "not-map"},
                credential_mode="pat_readonly_ref",
                repository_visibility="private",
                acquisition_transport="fixture",
            )
        ref = github_config.credentials_ref_from_payload(
            {"credentials": {"credentials_ref": "env_ref:MY_TOKEN"}},
            credential_mode="pat_readonly_ref",
            repository_visibility="private",
            acquisition_transport="fixture",
        )
        self.assertEqual(ref, "env_ref:MY_TOKEN")
        with self.assertRaises(github.GitHubApiPolicyError):
            github_config.validate_credential_ref("plain_token")

        # 4. validate_consent
        github_config.validate_consent(
            consent_ref="consent-1", authorized_operations=("read",), authorized_data_classes=("metadata",),
            consent_revoked=False, consent_mutation_allowed=False,
        )
        with self.assertRaises(github.GitHubApiPolicyError):
            github_config.validate_consent(
                consent_ref="", authorized_operations=("read",), authorized_data_classes=("metadata",),
                consent_revoked=False, consent_mutation_allowed=False,
            )
        with self.assertRaises(github.GitHubApiPolicyError):
            github_config.validate_consent(
                consent_ref="consent-1", authorized_operations=("read",), authorized_data_classes=("metadata",),
                consent_revoked=True, consent_mutation_allowed=False,
            )
        with self.assertRaises(github.GitHubApiPolicyError):
            github_config.validate_consent(
                consent_ref="consent-1", authorized_operations=("read",), authorized_data_classes=("metadata",),
                consent_revoked=False, consent_mutation_allowed=True,
            )
        with self.assertRaises(github.GitHubApiPolicyError):
            github_config.validate_consent(
                consent_ref="consent-1", authorized_operations=("write",), authorized_data_classes=("metadata",),
                consent_revoked=False, consent_mutation_allowed=False,
            )
        with self.assertRaises(github.GitHubApiPolicyError):
            github_config.validate_consent(
                consent_ref="consent-1", authorized_operations=("read",), authorized_data_classes=(),
                consent_revoked=False, consent_mutation_allowed=False,
            )

        # 5. validate_limits
        github_config.validate_limits(
            max_requests_per_run=5,
            endpoint_count=3,
            max_pages_per_endpoint=1,
            max_concurrent_requests=1,
            max_retries=0,
        )
        with self.assertRaises(github.GitHubApiPolicyError):
            github_config.validate_limits(
                max_requests_per_run=2,
                endpoint_count=3,
                max_pages_per_endpoint=1,
                max_concurrent_requests=1,
                max_retries=0,
            )
        with self.assertRaises(github.GitHubApiPolicyError):
            github_config.validate_limits(
                max_requests_per_run=5,
                endpoint_count=3,
                max_pages_per_endpoint=2,
                max_concurrent_requests=1,
                max_retries=0,
            )
        with self.assertRaises(github.GitHubApiPolicyError):
            github_config.validate_limits(
                max_requests_per_run=5,
                endpoint_count=3,
                max_pages_per_endpoint=1,
                max_concurrent_requests=2,
                max_retries=0,
            )
        with self.assertRaises(github.GitHubApiPolicyError):
            github_config.validate_limits(
                max_requests_per_run=5,
                endpoint_count=3,
                max_pages_per_endpoint=1,
                max_concurrent_requests=1,
                max_retries=1,
            )

        # 6. validate_retention_and_redaction
        github_config.validate_retention_and_redaction(
            retention_policy="local_user_controlled",
            raw_response_retention="minimized",
            redacted_response_retention="retain",
            redaction_profile="strict",
            sensitivity="confidential",
        )
        with self.assertRaises(github.GitHubApiPolicyError):
            github_config.validate_retention_and_redaction(
                retention_policy="cloud",
                raw_response_retention="minimized",
                redacted_response_retention="retain",
                redaction_profile="strict",
                sensitivity="confidential",
            )
        with self.assertRaises(github.GitHubApiPolicyError):
            github_config.validate_retention_and_redaction(
                retention_policy="local_user_controlled",
                raw_response_retention="retain",
                redacted_response_retention="retain",
                redaction_profile="strict",
                sensitivity="confidential",
            )
        with self.assertRaises(github.GitHubApiPolicyError):
            github_config.validate_retention_and_redaction(
                retention_policy="local_user_controlled",
                raw_response_retention="minimized",
                redacted_response_retention="purge",
                redaction_profile="strict",
                sensitivity="confidential",
            )
        with self.assertRaises(github.GitHubApiPolicyError):
            github_config.validate_retention_and_redaction(
                retention_policy="local_user_controlled",
                raw_response_retention="minimized",
                redacted_response_retention="retain",
                redaction_profile="loose",
                sensitivity="confidential",
            )
        with self.assertRaises(github.GitHubApiPolicyError):
            github_config.validate_retention_and_redaction(
                retention_policy="local_user_controlled",
                raw_response_retention="minimized",
                redacted_response_retention="retain",
                redaction_profile="strict",
                sensitivity="",
            )

        # 7. validate_fixture_response_path
        github_config.validate_fixture_response_path("responses/repo.json")
        for bad_path in ("/abs/path.json", "../escape.json", "http://url", ""):
            with self.subTest(bad_path=bad_path):
                with self.assertRaises(github.GitHubApiPolicyError):
                    github_config.validate_fixture_response_path(bad_path)

