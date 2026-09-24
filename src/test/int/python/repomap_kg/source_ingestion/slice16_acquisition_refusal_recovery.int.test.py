"""Configured acquisition refuses unsafe policy before transport and preserves artifacts."""
from pathlib import Path
import pytest
from repomap_kg.ops.ingestion.github_api import acquire_github_api_source, GitHubApiPolicyError
from repomap_test_support.run25_acquisition_fixtures import (
    Run25DeterministicGitHubTransport, make_run25_github_source_toml, snapshot_directory_state,
)

CASES = [
    ("private-unauthenticated", 'repository_visibility = "public"', 'repository_visibility = "private"', "only for public repositories"),
    ("unknown-transport", 'transport = "github_public_rest"', 'transport = "unreviewed"', "unsupported acquisition.transport"),
    ("header-newline", 'user_agent = "RepoMap/1.0"', 'user_agent = "RepoMap\\nInjected"', "safe header value"),
    ("foreign-api-root", 'base_url = "https://api.github.com"', 'base_url = "https://example.invalid"', "base_url must be"),
    ("redirect-authority", 'follow_redirects = false', 'follow_redirects = true', "must not follow redirects"),
    ("credentials-on-public-transport", '[acquisition]', '[credentials]\ncredentials_ref = "local_secret_ref:fixture"\n[acquisition]', "credentials table is not allowed"),
    ("endpoint-escape", 'path = "/repos/{owner}/{repo}"', 'path = "/repos/{owner}/{repo}/../other"', "remain under owner/repository"),
    ("credential-mode-on-rest", 'credential_mode = "none_public_readonly"', 'credential_mode = "pat_readonly_ref"', "requires credential_mode"),
    ("consent-without-data", 'authorized_data_classes = ["repository_metadata", "issues", "pull_requests"]', 'authorized_data_classes = []', "authorized_data_classes is required"),
    ("endpoint-without-consent", 'authorized_data_classes = ["repository_metadata", "issues", "pull_requests"]', 'authorized_data_classes = ["issues"]', "data class is not authorized"),
    ("missing-source-identity", 'source_id = "slice16-fixture"', 'source_id = ""', "source_id is required"),
    ("endpoint-list-absent", '[[endpoints]]', '[endpoint]', "at least one"),
    ("required-string-type", 'purpose = "Export repository metadata"', 'purpose = 42', "purpose is required"),
    ("request-limit-bool", 'max_requests_per_run = 10', 'max_requests_per_run = true', "positive integer"),
    ("negative-retries", 'max_retries = 0', 'max_retries = -1', "non-negative integer"),
    ("read-only-type", 'read_only = true', 'read_only = "true"', "read_only must be a boolean"),
    ("timeout-type", 'timeout_seconds = 10', 'timeout_seconds = "ten"', "positive integer"),
    ("redirect-type", 'follow_redirects = false', 'follow_redirects = "false"', "must be a boolean"),
    ("fixture-path-type", 'downstream_route = "config"', 'downstream_route = "config"\nfixture_response_path = 42', "must be a non-empty string"),
    ("fixture-path-required", 'transport = "github_public_rest"', 'transport = "fixture"', "fixture_response_path is required"),
]


@pytest.mark.parametrize("case,old,new,message", CASES, ids=[item[0] for item in CASES])
def test_policy_refusal_preserves_acquired_artifacts_then_recovers(tmp_path: Path, case, old, new, message):
    config = tmp_path / "source.toml"
    original = make_run25_github_source_toml(source_id="slice16-fixture")
    config.write_text(original)

    class ObservedTransport(Run25DeterministicGitHubTransport):
        calls = 0
        def fetch(self, config, request):
            self.calls += 1
            return super().fetch(config, request)

    transport = ObservedTransport()
    success = acquire_github_api_source(config, root_path=tmp_path, transport=transport)
    assert transport.calls == 1
    assert success.requests == success.responses == 1
    before = snapshot_directory_state(success.output_path)
    assert "manifest.json" in before and "artifacts/repository.json" in before
    assert old in original
    config.write_text(original.replace(old, new))
    with pytest.raises(GitHubApiPolicyError, match=message):
        acquire_github_api_source(config, root_path=tmp_path, transport=transport)
    assert transport.calls == 1
    assert snapshot_directory_state(success.output_path) == before
    config.write_text(original)
    recovered = acquire_github_api_source(config, root_path=tmp_path, transport=transport)
    assert transport.calls == 2
    assert recovered.requests == recovered.responses == 1
    assert recovered.raw_observations == success.raw_observations
    assert snapshot_directory_state(success.output_path) == before
