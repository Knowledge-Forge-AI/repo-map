"""Late external response refusal preserves the complete previously acquired run."""
from dataclasses import replace
import json
from pathlib import Path

import pytest

from repomap_kg.ops.ingestion.github_api import acquire_github_api_source, GitHubApiPolicyError
from repomap_kg.storage.staged_rows import build_staged_rows
from repomap_test_support.run25_acquisition_fixtures import (
    Run25DeterministicGitHubTransport, make_run25_github_source_toml, snapshot_directory_state,
)


@pytest.mark.parametrize("fault,message", [
    ("redirect", "redirect status"),
    ("rate-limit", "rate limit"),
    ("http", "HTTP status"),
    ("content-type", "JSON response"),
    ("malformed-json", "JSON"),
    ("aggregate-bytes", "response bytes"),
    ("items", "response items"),
])
def test_second_response_refusal_is_atomic_and_recovery_retains_redacted_rows(tmp_path: Path, fault, message):
    config = tmp_path / "source.toml"
    config.write_text(make_run25_github_source_toml(
        source_id="slice16-two-endpoints", max_bytes=4096, max_items=2,
        extra_body='''
[[endpoints]]
name = "issues"
method = "GET"
path = "/repos/{owner}/{repo}/issues"
purpose = "Export fixture issues"
response_type = "application/json"
max_page_size = 2
pagination = "none"
downstream_route = "config"
data_class = "issues"
''',
    ))

    class ResponseTransport(Run25DeterministicGitHubTransport):
        damage = False

        def __init__(self):
            super().__init__(canned_bodies={
                "repository": b'{"name":"fixture","private":false,"secret_note":"fixture-secret-note"}',
                "issues": b'[{"title":"Fixture issue","html_url":"https://example.invalid/item?token=token123"}]',
            })
            self.calls = []

        def fetch(self, source, request):
            self.calls.append(request.endpoint_name)
            response = super().fetch(source, request)
            if not self.damage:
                return response
            if fault == "aggregate-bytes":
                return replace(response, body=json.dumps({"description": "x" * 2500}).encode())
            if request.endpoint_name != "issues":
                return response
            if fault == "redirect":
                return replace(response, status_code=302)
            if fault == "rate-limit":
                return replace(response, rate_limit={"x-ratelimit-remaining": "0"})
            if fault == "http":
                return replace(response, status_code=503)
            if fault == "content-type":
                return replace(response, response_type="text/plain")
            if fault == "malformed-json":
                return replace(response, body=b"{invalid")
            return replace(response, body=b"[{}, {}, {}]")

    transport = ResponseTransport()
    original = acquire_github_api_source(config, root_path=tmp_path, transport=transport)
    assert original.requests == original.responses == 2
    retained = snapshot_directory_state(original.output_path)
    assert {"manifest.json", "artifacts/repository.json", "artifacts/issues.json"} <= retained.keys()
    transport.damage = True
    transport.calls.clear()
    with pytest.raises(GitHubApiPolicyError, match=message):
        acquire_github_api_source(config, root_path=tmp_path, transport=transport)
    assert transport.calls == ["repository", "issues"]
    assert snapshot_directory_state(original.output_path) == retained
    transport.damage = False
    transport.calls.clear()
    recovered = acquire_github_api_source(config, root_path=tmp_path, transport=transport)
    assert transport.calls == ["repository", "issues"]
    assert recovered.raw_observations == original.raw_observations
    assert snapshot_directory_state(recovered.output_path) == retained
    rows = build_staged_rows(recovered.raw_observations, repository_name="api-fixture", stage_id="fixture-stage")
    try:
        assert rows.row_counts["raw_observations"] == len(recovered.raw_observations) > 0
        assert rows.row_counts["canonical_edges"] > 0
        encoded = json.dumps({family: list(values) for family, values in rows.family_rows.items()})
        assert "fixture-secret-note" not in encoded
        assert "token123" not in encoded
        assert "ghp_faketoken" not in encoded
    finally:
        rows.close()


@pytest.mark.parametrize("authority", ["fixture-user:fixture-password", "fixture-user"], ids=["password", "username-only"])
def test_acquired_url_userinfo_does_not_survive_into_staged_rows(tmp_path: Path, authority):
    """Credentialed URL userinfo is removed before observation and row construction."""
    config = tmp_path / "source.toml"
    config.write_text(make_run25_github_source_toml(source_id="slice16-userinfo"))
    transport = Run25DeterministicGitHubTransport(canned_bodies={
        "repository": json.dumps({"html_url": f"https://{authority}@example.invalid/item"}).encode(),
    })
    result = acquire_github_api_source(config, root_path=tmp_path, transport=transport)
    assert all(b"fixture-user" not in path.read_bytes()
               for path in result.output_path.rglob("*") if path.is_file()), "credential retained in acquisition artifacts"
    rows = build_staged_rows(result.raw_observations, repository_name="api-fixture", stage_id="fixture-stage")
    try:
        encoded = json.dumps({family: list(values) for family, values in rows.family_rows.items()})
        leaked = "fixture-user" in encoded
        assert not leaked, "credentialed URL userinfo retained in staged acquisition rows"
    finally:
        rows.close()
